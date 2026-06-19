"""
SENECIO ORACLE — FastAPI Main App
==================================
Wires all 7 layers into a runnable service.

Run:
    uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

Endpoints:
    GET  /             — dashboard (static)
    GET  /api/health   — liveness probe
    GET  /api/stats    — bus + scheduler + audit stats
    GET  /api/audit?day=YYYY-MM-DD&limit=100  — recent audit events
    GET  /api/state    — current portfolio + scanner state
    GET  /api/catalog  — symbol catalog
    WS   /ws?type=...  — live event stream
    GET  /sse?type=... — SSE fallback
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
import json

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .audit_store import AuditStore
from .event_bus import EventBus
from .data_retriever import DataRetriever
from .scanner_a import ScannerA
from .scanner_b import ScannerB
from .wallet_tracker import WalletTracker
from .oracle_engine import OracleEngine
from .execution_simulator import ExecutionSimulator
from .scheduler import Scheduler
from .ws_server import make_router as make_ws_router
from . import oracle_runner

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")
log = logging.getLogger("senecio.main")

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

# module-level singletons (created once, used by both lifespan and route handlers)
_audit = AuditStore(root="data/audit")
_bus = EventBus(audit=_audit)
_retriever = DataRetriever(mode="LIVE", seed=42)
_scanner_a = ScannerA()
_scanner_b = ScannerB()
_wallet_tracker = WalletTracker()
_engine = OracleEngine()
_executor = ExecutionSimulator()
_scheduler = Scheduler(
    bus=_bus, retriever=_retriever, scanner_a=_scanner_a, scanner_b=_scanner_b,
    wallet_tracker=_wallet_tracker, engine=_engine, executor=_executor,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.audit = _audit
    app.state.bus = _bus
    app.state.retriever = _retriever
    app.state.scanner_a = _scanner_a
    app.state.scanner_b = _scanner_b
    app.state.wallet_tracker = _wallet_tracker
    app.state.engine = _engine
    app.state.executor = _executor
    app.state.scheduler = _scheduler

    _scheduler.start()
    oracle_runner.start()
    log.info("SENECIO ORACLE backend up — layers: data, scanner_a, scanner_b, wallet, brain, exec, ws + REAL ORACLE")

    yield

    await oracle_runner.stop()
    await _scheduler.stop()
    await _bus.close()
    log.info("SENECIO ORACLE backend down")


app = FastAPI(title="SENECIO ORACLE", version="ACT-XXII-prereq-historical-verifier", lifespan=lifespan)

# WebSocket / SSE router
app.include_router(make_ws_router(_bus))


# ---- REST endpoints ----
@app.get("/api/health")
async def health():
    """Real health check — includes oracle runner state."""
    oracle_state = oracle_runner.get_state()
    # Best-effort Supabase count (don't fail health if DB unreachable)
    sb_total = 0
    try:
        from . import supabase_client
        sb_total = await supabase_client.count_predictions()
    except Exception:
        pass
    return {
        "status": "ok",
        "version": "ACT-XXII-prereq-historical-verifier",
        "oracle": {
            "started_at": oracle_state.get("started_at"),
            "last_prediction_ts": oracle_state.get("last_prediction_ts"),
            "last_prediction_symbol": oracle_state.get("last_prediction_symbol"),
            "predictions_count": oracle_state.get("predictions_count", 0),
            "cycles_run": oracle_state.get("cycles_run", 0),
            "cycles_failed": oracle_state.get("cycles_failed", 0),
            "last_error": oracle_state.get("last_error"),
            "last_cycle_at": oracle_state.get("last_cycle_at"),
            "next_cycle_at": oracle_state.get("next_cycle_at"),
            "exchange_used_last": oracle_state.get("exchange_used_last"),
            "supabase_total": sb_total,
        },
    }


@app.get("/api/oracle/state")
async def oracle_state():
    """Detailed oracle runner state + last prediction."""
    state = oracle_runner.get_state()
    return {
        **state,
        "last_prediction": state.get("last_prediction_result"),
    }


@app.get("/api/oracle/predictions")
async def oracle_predictions(limit: int = Query(default=20, le=200)):
    """Return last N predictions from predictions.jsonl (most recent first)."""
    from pathlib import Path
    pred_path = Path(__file__).resolve().parent.parent / "oracle" / "senecio_output" / "predictions.jsonl"
    if not pred_path.exists():
        return {"count": 0, "predictions": []}
    rows = []
    with open(pred_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    # most recent first
    rows.reverse()
    # strip _audit for slim view (client can request /api/oracle/predictions/full for it)
    slim = [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows[:limit]]
    return {"count": len(slim), "total_in_file": len(rows), "predictions": slim}


@app.get("/api/oracle/predictions/db")
async def oracle_predictions_db(limit: int = Query(default=50, le=500), symbol: str | None = None):
    """Read predictions directly from Supabase — survives container redeploys."""
    from . import supabase_client
    rows = await supabase_client.fetch_predictions(limit=limit, symbol=symbol)
    total = await supabase_client.count_predictions()
    return {
        "source": "supabase",
        "count": len(rows),
        "total_in_db": total,
        "predictions": rows,
    }


@app.get("/api/oracle/score")
async def oracle_score():
    """Oracle accuracy score computed from Supabase (verified predictions only).

    Returns both aggregate and per-direction breakdown — the LONG vs SHORT
    asymmetry is a critical GO/NO-GO signal for live capital.
    """
    from . import supabase_client
    # Get all predictions with outcome filled
    rows = await supabase_client.fetch_predictions(limit=500)
    verified = [r for r in rows if r.get("outcome") in ("WIN", "LOSS")]
    wins = sum(1 for r in verified if r.get("outcome") == "WIN")
    losses = sum(1 for r in verified if r.get("outcome") == "LOSS")
    win_rate = (wins / len(verified) * 100) if verified else 0.0

    # Per-direction breakdown — surfaces edge asymmetry that the aggregate
    # win_rate hides (e.g. LONG 0% + SHORT 82% averages to 46% which looks
    # mediocre but actually means LONG is broken and SHORT is the alpha).
    by_direction: dict[str, dict] = {}
    for direction in ("LONG", "SHORT", "FLAT"):
        sub = [r for r in verified if (r.get("prediction") or "").upper() == direction]
        sub_w = sum(1 for r in sub if r.get("outcome") == "WIN")
        sub_l = sum(1 for r in sub if r.get("outcome") == "LOSS")
        sub_decided = sub_w + sub_l
        by_direction[direction] = {
            "verified": sub_decided,
            "wins": sub_w,
            "losses": sub_l,
            "win_rate_pct": round((sub_w / sub_decided * 100) if sub_decided > 0 else 0.0, 2),
        }

    return {
        "version": "ACT-XXII-prereq-historical-verifier",
        "total_predictions": len(rows),
        "verified": len(verified),
        "wins": wins,
        "losses": losses,
        "win_rate_pct": round(win_rate, 2),
        "by_direction": by_direction,
    }


@app.get("/api/stats")
async def stats():
    return {
        "scheduler": _scheduler.stats(),
        "bus": _bus.stats(),
        "audit": _audit.stats(),
        "executor": _executor.risk_state(),
        "wallet_tracker": _wallet_tracker.stats(),
        "cursors": _retriever.cursor_state(),
    }


@app.get("/api/audit")
async def audit_events(
    day: str | None = Query(default=None),
    limit: int = Query(default=100, le=1000),
    tail: bool = Query(default=False),
    type: str | None = Query(default=None),
):
    """If tail=True, return the most recent `limit` events (chronologically reversed).
    If type=... is provided, filter by event_type."""
    if tail:
        # collect all, then take last N (with optional type filter)
        all_events = []
        for ev in _audit.iter_events(day=day):
            if type and ev.event_type != type:
                continue
            all_events.append(ev.model_dump())
        events = all_events[-limit:]
        return {"count": len(events), "total_in_log": len(all_events), "events": events}
    else:
        events = []
        for ev in _audit.iter_events(day=day):
            if type and ev.event_type != type:
                continue
            events.append(ev.model_dump())
            if len(events) >= limit:
                break
        return {"count": len(events), "events": events}


@app.get("/api/state")
async def state():
    return {
        "latest_ticks": {sym: t.payload for sym, t in _scheduler.latest_tick.items()},
        "open_positions": [
            {
                "symbol": p.symbol, "qty": p.qty, "entry_price": p.entry_price,
                "entry_ts": p.entry_ts, "stop": p.stop_price, "target": p.target_price,
            } for p in _executor.positions.values() if p.status == "OPEN"
        ],
        "scanner_b_sma": {k: round(v, 4) for k, v in _scanner_b.sma_cache.items()},
        "cursors": _retriever.cursor_state(),
    }


@app.get("/api/catalog")
async def catalog():
    return {"instruments": _retriever.catalog()}


@app.get("/api/replay/{day}")
async def replay(day: str):
    events = [ev.model_dump() for ev in _audit.iter_events(day=day)]
    return {"day": day, "count": len(events), "events": events}


# ---- static frontend ----
@app.get("/")
async def root():
    idx = FRONTEND_DIR / "index.html"
    if idx.exists():
        return FileResponse(idx)
    return JSONResponse({"error": "frontend not built"}, status_code=404)


if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")
