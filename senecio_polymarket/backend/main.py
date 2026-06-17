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
    log.info("SENECIO ORACLE backend up — layers: data, scanner_a, scanner_b, wallet, brain, exec, ws")

    yield

    await _scheduler.stop()
    await _bus.close()
    log.info("SENECIO ORACLE backend down")


app = FastAPI(title="SENECIO ORACLE", version="ACT-XX-polymarket-style", lifespan=lifespan)

# WebSocket / SSE router
app.include_router(make_ws_router(_bus))


# ---- REST endpoints ----
@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "ACT-XX-polymarket-style"}


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
