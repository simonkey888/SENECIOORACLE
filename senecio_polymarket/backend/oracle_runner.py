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
        if candle_ts and check_candle_duplicate(candle_ts, str(PREDICTIONS_PATH)):
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


async def _oracle_loop() -> None:
    """Main loop: every CYCLE_INTERVAL_S, run predictions for all symbols."""
    log.info("oracle_loop waiting %ds before first cycle...", INITIAL_DELAY_S)
    await asyncio.sleep(INITIAL_DELAY_S)

    while True:
        cycle_start = datetime.now(timezone.utc)
        _state["last_cycle_at"] = cycle_start.isoformat()
        _state["cycles_run"] += 1
        log.info("=== oracle cycle #%d start @ %s ===", _state["cycles_run"], cycle_start.isoformat())

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
    log.info("oracle_runner stopped")
