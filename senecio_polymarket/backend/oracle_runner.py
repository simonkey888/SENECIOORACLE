"""
SENECIO ORACLE — Real Oracle Runner (ACT XIX)
==============================================

Bridges the FastAPI dashboard with the REAL oracle pipeline (predict_only.py).

Responsibilities:
  1. On startup: count existing predictions in the seed file
  2. Every 15 min: call predict_only.fetch_market_snapshot + run_prediction
     for ETH/USDT and BTC/USDT, append to predictions.jsonl
  3. Expose state: last_prediction_ts, predictions_count, last_prediction
  4. Optional: every N cycles, run verify_predictions() to fill outcomes

This module does NOT touch the demo scheduler (which still powers the live
dashboard panels with synthetic ticks). Both run in parallel.

Memory budget: ccxt + SDC + predict_only ~ 50-80MB. Fits in 256MB.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Make oracle modules importable
ORACLE_DIR = Path(__file__).resolve().parent.parent / "oracle"
sys.path.insert(0, str(ORACLE_DIR))

log = logging.getLogger("senecio.oracle_runner")

# Path to predictions JSONL — must match predict_only.DEFAULT_PREDICTIONS_PATH
PREDICTIONS_PATH = ORACLE_DIR / "senecio_output" / "predictions.jsonl"

# Runtime state (read by /api/health and /api/oracle/*)
_state: dict[str, Any] = {
    "started_at": None,
    "last_prediction_ts": None,
    "last_prediction_symbol": None,
    "last_prediction_result": None,   # cleaned (no _audit) dict
    "predictions_count": 0,
    "cycles_run": 0,
    "cycles_failed": 0,
    "last_error": None,
    "last_cycle_at": None,
    "next_cycle_at": None,
    "exchange_used_last": None,
    # Outcome verifier state (ACT XXI)
    "last_verify_at": None,
    "last_verify_count": None,        # how many outcomes were settled in last run
    "last_verify_ids": [],            # ids settled in last run (for debug, capped at 10)
    "verified_total": 0,              # running total of verified predictions
}

# Cycle config
CYCLE_INTERVAL_S = 900  # 15 minutes
SYMBOLS = ["ETH/USDT", "BTC/USDT"]
TIMEFRAME = "15m"
INITIAL_DELAY_S = 30    # wait for uvicorn + scheduler to stabilize
MAX_CONCURRENT_PREDICTIONS = 1  # serialize to keep memory bounded


def _count_predictions() -> int:
    """Count existing lines in predictions.jsonl (seed from repo + runtime)."""
    try:
        if not PREDICTIONS_PATH.exists():
            return 0
        with open(PREDICTIONS_PATH, "r", encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())
    except Exception as e:
        log.warning("failed to count predictions: %s", e)
        return 0


def _get_last_prediction() -> Optional[dict]:
    """Return the last line of predictions.jsonl as dict, or None."""
    try:
        if not PREDICTIONS_PATH.exists():
            return None
        last = None
        with open(PREDICTIONS_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    last = json.loads(line)
                except Exception:
                    continue
        return last
    except Exception:
        return None


def _seed_state_from_existing() -> None:
    """On startup, populate state from existing predictions.jsonl (seed from repo)."""
    _state["predictions_count"] = _count_predictions()
    last = _get_last_prediction()
    if last:
        _state["last_prediction_ts"] = last.get("timestamp")
        _state["last_prediction_symbol"] = last.get("symbol")
        _state["last_prediction_result"] = {k: v for k, v in last.items() if not k.startswith("_")}
        _state["exchange_used_last"] = last.get("_audit", {}).get("exchange_used") or last.get("exchange_used")
    log.info(
        "oracle_runner seeded: count=%d last_ts=%s",
        _state["predictions_count"], _state["last_prediction_ts"],
    )


def get_state() -> dict[str, Any]:
    """Public accessor for /api/health and /api/oracle/state."""
    return dict(_state)


async def _run_one_prediction(symbol: str) -> Optional[dict]:
    """Run a single prediction for a symbol. Returns the prediction dict or None."""
    # Import inside the function so module load is cheap and errors are isolated
    try:
        from predict_only import fetch_market_snapshot, run_prediction, log_prediction, check_candle_duplicate
    except Exception as e:
        log.exception("failed to import predict_only: %s", e)
        _state["last_error"] = f"import_error: {e}"
        _state["cycles_failed"] += 1
        return None

    try:
        log.info("fetching market snapshot for %s @ %s", symbol, TIMEFRAME)
        market_data = await asyncio.to_thread(fetch_market_snapshot, symbol, TIMEFRAME)
        if not market_data:
            log.warning("no market data for %s", symbol)
            _state["last_error"] = f"no_market_data: {symbol}"
            _state["cycles_failed"] += 1
            return None

        # Check for candle duplicate (avoid logging same 15m candle twice)
        candle_ts = market_data.get("candle_ts", 0)
        if candle_ts and check_candle_duplicate(candle_ts, str(PREDICTIONS_PATH), symbol):
            log.info("skip duplicate candle_ts=%s for %s", candle_ts, symbol)
            return None

        # Run the pipeline (CPU-bound, run in thread)
        prediction = await asyncio.to_thread(run_prediction, market_data)
        if not prediction:
            log.warning("no prediction produced for %s", symbol)
            _state["last_error"] = f"no_prediction: {symbol}"
            _state["cycles_failed"] += 1
            return None

        # Tag with exchange used (extract from market_data)
        exchange_used = market_data.get("exchange_used") or "unknown"
        prediction["exchange_used"] = exchange_used
        if "_audit" in prediction:
            prediction["_audit"]["exchange_used"] = exchange_used

        # Persist
        await asyncio.to_thread(log_prediction, prediction, str(PREDICTIONS_PATH))

        # Dual-write to Supabase (best-effort — failure doesn't block the cycle)
        try:
            from . import supabase_client
            sb_row = await supabase_client.insert_prediction(prediction)
            if sb_row:
                log.info("supabase insert OK id=%s", sb_row.get("id"))
            else:
                log.warning("supabase insert returned None — predictions.jsonl is source of truth")
        except Exception as sb_err:
            log.warning("supabase insert failed (continuing): %s", sb_err)

        # Update runtime state
        _state["last_prediction_ts"] = prediction.get("timestamp")
        _state["last_prediction_symbol"] = prediction.get("symbol")
        _state["last_prediction_result"] = {k: v for k, v in prediction.items() if not k.startswith("_")}
        _state["predictions_count"] += 1
        _state["exchange_used_last"] = exchange_used
        _state["last_error"] = None

        log.info(
            "prediction logged: %s %s conf=%.4f ev=%.8f price=%s exchange=%s",
            prediction.get("symbol"),
            prediction.get("prediction"),
            prediction.get("confidence", 0),
            prediction.get("ev", 0),
            prediction.get("price_now"),
            exchange_used,
        )
        return prediction

    except Exception as e:
        log.exception("prediction cycle failed for %s: %s", symbol, e)
        _state["last_error"] = f"cycle_error: {symbol}: {e}"
        _state["cycles_failed"] += 1
        return None


async def _fetch_current_price(symbol: str) -> Optional[float]:
    """Fetch the latest price for a symbol via ccxt (OKX public ticker).

    Lightweight: only fetches ticker (no OHLCV/orderbook), so ~10x faster than
    full fetch_market_snapshot. Used by the verifier to settle old predictions.

    Args:
        symbol: e.g. "ETH/USDT" (ccxt format with slash)
    Returns:
        Last price as float, or None on failure.
    """
    def _fetch() -> Optional[float]:
        try:
            import ccxt
            ex = ccxt.okx({"enableRateLimit": True})
            t = ex.fetch_ticker(symbol)
            return float(t.get("last") or 0) or None
        except Exception as e:
            log.warning("ccxt fetch_ticker failed for %s: %s", symbol, e)
            return None
    return await asyncio.to_thread(_fetch)


async def _verify_pending_outcomes() -> int:
    """Settle predictions whose 15-min window has elapsed.

    For each prediction with outcome=NULL and ts older than 15min:
      1. Fetch current price via ccxt
      2. Compare with price_now at prediction time
      3. Determine WIN/LOSS (skip FLAT — no directional bet)
      4. Update Supabase row with outcome + price_15m_later

    Returns the number of outcomes settled in this run.
    """
    try:
        from . import supabase_client
    except Exception as e:
        log.warning("supabase_client unavailable, skipping verifier: %s", e)
        return 0

    try:
        pending = await supabase_client.fetch_pending_outcomes(
            older_than_seconds=900, limit=100
        )
    except Exception as e:
        log.exception("fetch_pending_outcomes failed: %s", e)
        return 0

    if not pending:
        log.info("verifier: no pending outcomes to settle")
        _state["last_verify_at"] = datetime.now(timezone.utc).isoformat()
        _state["last_verify_count"] = 0
        _state["last_verify_ids"] = []
        return 0

    log.info("verifier: %d pending predictions to settle", len(pending))

    # Group by symbol so we only fetch price once per symbol
    # (predictions in same 15m cycle share the same settlement price anyway)
    symbol_prices: dict[str, Optional[float]] = {}
    symbols_needed = set()
    for row in pending:
        # Symbol stored as "ETHUSDT" in DB — convert back to ccxt format "ETH/USDT"
        sym_raw = row.get("symbol", "")
        sym_ccxt = sym_raw[:3] + "/" + sym_raw[3:] if len(sym_raw) >= 6 else sym_raw
        symbols_needed.add(sym_ccxt)

    for sym in symbols_needed:
        symbol_prices[sym] = await _fetch_current_price(sym)
        await asyncio.sleep(0.5)  # gentle on OKX rate limit

    settled = 0
    settled_ids: list[int] = []
    skipped = 0
    errors = 0

    for row in pending:
        pred_id = row.get("id")
        sym_raw = row.get("symbol", "")
        sym_ccxt = sym_raw[:3] + "/" + sym_raw[3:] if len(sym_raw) >= 6 else sym_raw
        direction = (row.get("prediction") or "").upper()
        price_now = float(row.get("price_now") or 0)
        price_later = symbol_prices.get(sym_ccxt)

        if price_later is None or price_later <= 0:
            log.warning("verifier: no price for %s, skipping id=%s", sym_ccxt, pred_id)
            errors += 1
            continue

        # Skip FLAT — no directional bet to verify
        if direction == "FLAT":
            skipped += 1
            continue

        # Determine WIN/LOSS
        # LONG correct if price went up (price_later > price_now)
        # SHORT correct if price went down (price_later < price_now)
        # Equal price → treat as LOSS (no edge realized, costs would have eaten it)
        if direction == "LONG":
            outcome = "WIN" if price_later > price_now else "LOSS"
        elif direction == "SHORT":
            outcome = "WIN" if price_later < price_now else "LOSS"
        else:
            # Unknown direction (shouldn't happen) — skip
            skipped += 1
            continue

        ok = await supabase_client.update_outcome(pred_id, outcome, price_later)
        if ok:
            settled += 1
            if len(settled_ids) < 10:
                settled_ids.append(pred_id)
        else:
            errors += 1
        # Gentle pacing
        await asyncio.sleep(0.1)

    _state["last_verify_at"] = datetime.now(timezone.utc).isoformat()
    _state["last_verify_count"] = settled
    _state["last_verify_ids"] = settled_ids
    _state["verified_total"] = (_state.get("verified_total") or 0) + settled

    log.info(
        "verifier done: settled=%d skipped=%d errors=%d total_verified_so_far=%d",
        settled, skipped, errors, _state["verified_total"],
    )
    return settled


async def _oracle_loop() -> None:
    """Main loop: every CYCLE_INTERVAL_S, run predictions for all symbols."""
    log.info("oracle_loop waiting %ds before first cycle...", INITIAL_DELAY_S)
    await asyncio.sleep(INITIAL_DELAY_S)

    while True:
        cycle_start = datetime.now(timezone.utc)
        _state["last_cycle_at"] = cycle_start.isoformat()
        _state["cycles_run"] += 1
        log.info("=== oracle cycle #%d start @ %s ===", _state["cycles_run"], cycle_start.isoformat())

        # ACT XXI: Verify pending outcomes BEFORE producing new predictions.
        # This settles predictions whose 15min window elapsed in the previous cycle.
        # First cycle after boot will backfill all 200+ accumulated predictions.
        try:
            settled = await _verify_pending_outcomes()
            if settled > 0:
                log.info("verifier settled %d outcomes in cycle #%d", settled, _state["cycles_run"])
        except Exception as e:
            log.exception("verifier error (non-fatal, continuing): %s", e)

        for symbol in SYMBOLS:
            try:
                await _run_one_prediction(symbol)
            except Exception as e:
                log.exception("unexpected error for %s: %s", symbol, e)
                _state["last_error"] = f"unexpected: {symbol}: {e}"
                _state["cycles_failed"] += 1
            # Small breather between symbols to keep memory bounded
            await asyncio.sleep(2)

        # Schedule next cycle
        next_at = datetime.now(timezone.utc).timestamp() + CYCLE_INTERVAL_S
        _state["next_cycle_at"] = datetime.fromtimestamp(next_at, tz=timezone.utc).isoformat()
        log.info(
            "=== cycle #%d done — next at %s ===",
            _state["cycles_run"], _state["next_cycle_at"],
        )
        await asyncio.sleep(CYCLE_INTERVAL_S)


_tasks: list[asyncio.Task] = []


def start() -> None:
    """Start the oracle runner. Called from main.py lifespan()."""
    if _state["started_at"] is not None:
        return  # already started
    _state["started_at"] = datetime.now(timezone.utc).isoformat()
    _seed_state_from_existing()
    t = asyncio.create_task(_oracle_loop(), name="oracle_loop")
    _tasks.append(t)
    log.info("oracle_runner started — interval=%ds symbols=%s", CYCLE_INTERVAL_S, SYMBOLS)


async def stop() -> None:
    """Graceful shutdown."""
    for t in _tasks:
        t.cancel()
    for t in _tasks:
        try:
            await t
        except asyncio.CancelledError:
            pass
    _tasks.clear()
    # Close Supabase HTTP client
    try:
        from . import supabase_client
        await supabase_client.close()
    except Exception:
        pass
    log.info("oracle_runner stopped")
