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
# ACT-XXVII: research layer (lazy-initialized to avoid import-time failures
# if optional deps like shap are missing)
try:
    from .research import ResearchCoordinator, get_registry
    _research_coord = ResearchCoordinator()
    _metrics_registry = get_registry()
except Exception as _research_init_err:  # pragma: no cover — research layer must never break the app
    _research_coord = None
    _metrics_registry = None
    _research_init_err_msg = str(_research_init_err)
else:
    _research_init_err_msg = None

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


app = FastAPI(title="SENECIO ORACLE", version="ACT-XXVII-research-grade-validation", lifespan=lifespan)

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
        "version": "ACT-XXVII-research-grade-validation",
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

    ACT XXIII: now returns per-direction × per-window breakdown + gate states.
    The LONG vs SHORT asymmetry is a critical GO/NO-GO signal for live capital.

    Returns:
      - total_predictions: count of all rows in Supabase
      - verified: count of rows with WIN/LOSS outcome (= outcome_1h, the gating column)
      - wins/losses/win_rate_pct: aggregate across all verified
      - by_direction: per-direction breakdown using outcome_1h (primary column)
      - by_window: {15m: {LONG, SHORT, FLAT, global}, 1h: {...}} — 15m reads from
                   audit.outcomes_dual.outcome_15m, 1h reads primary `outcome` column
      - gates: {long_1h, short_1h, global_1h} with pass/fail + thresholds + n
      - short_only_paper_mode: True when SHORT passes 1h gate but LONG fails
      - trade_mode: "PAPER" (always, per ACT XXIII directive 5 — no live capital)
      - live_capital_locked: True (hard guard)
    """
    from . import supabase_client
    from . import oracle_runner
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

    # ACT XXIII: pull full state from oracle_runner (directional stats + gates)
    runner_state = oracle_runner.get_state()
    by_window = runner_state.get("directional_stats", {}).get("by_window", {})
    gates = runner_state.get("gates", {})
    short_only_paper_mode = runner_state.get("short_only_paper_mode", False)
    trade_mode = runner_state.get("trade_mode", "PAPER")
    live_capital_locked = runner_state.get("live_capital_locked", True)

    return {
        "version": "ACT-XXVII-research-grade-validation",
        "total_predictions": len(rows),
        "verified": len(verified),
        "wins": wins,
        "losses": losses,
        "win_rate_pct": round(win_rate, 2),
        "by_direction": by_direction,           # 1h-window primary breakdown (backward compat)
        "by_window": by_window,                 # ACT XXIII: {15m: {...}, 1h: {...}}
        "gates": gates,                         # ACT XXIII: directional GO/NO-GO
        "short_only_paper_mode": short_only_paper_mode,
        "trade_mode": trade_mode,               # always "PAPER" per directive 5
        "live_capital_locked": live_capital_locked,
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


# ---- ACT-XXV: Portfolio endpoints ----

def _get_coordinator():
    """Lazy access to the portfolio coordinator from oracle_runner."""
    try:
        return oracle_runner._get_portfolio_coordinator()
    except Exception:
        return None


@app.get("/api/portfolio/state")
async def portfolio_state():
    """ACT-XXV/XXVI: full portfolio subsystem snapshot (includes microstructure + regime_hmm)."""
    coord = _get_coordinator()
    if coord is None:
        return {"error": "portfolio coordinator not initialized", "version": "ACT-XXVII-research-grade-validation"}
    return coord.get_state()


@app.get("/api/portfolio/analytics")
async def portfolio_analytics():
    """ACT-XXV: Sharpe / Sortino / PF / Expectancy / Recovery / Calmar / Kelly / MaxDD."""
    coord = _get_coordinator()
    if coord is None:
        return {"error": "portfolio coordinator not initialized"}
    return coord.get_analytics()


@app.get("/api/portfolio/trades")
async def portfolio_trades(limit: int = Query(default=50, le=500)):
    """ACT-XXV: recent closed trades from the journal."""
    coord = _get_coordinator()
    if coord is None:
        return {"error": "portfolio coordinator not initialized", "trades": []}
    return {"count": limit, "trades": coord.get_recent_trades(limit=limit)}


@app.get("/api/portfolio/audit")
async def portfolio_audit(limit: int = Query(default=50, le=500)):
    """ACT-XXV: recent execution audit events (order lifecycle)."""
    coord = _get_coordinator()
    if coord is None:
        return {"error": "portfolio coordinator not initialized", "events": []}
    return {"count": limit, "events": coord.get_audit_log(limit=limit)}


@app.get("/api/portfolio/shadow")
async def portfolio_shadow():
    """ACT-XXV: ShadowLive status + recent shadow trades."""
    coord = _get_coordinator()
    if coord is None:
        return {"error": "portfolio coordinator not initialized"}
    return {
        "status": coord.shadow_live.stats(),
        "report": coord.shadow_live.generate_report(),
        "recent_trades": coord.shadow_live.fetch_trades(limit=20),
    }


@app.get("/api/portfolio/microstructure")
async def portfolio_microstructure():
    """ACT-XXVI: microstructure intelligence snapshot.

    Returns the most recent MicrostructureReport with:
      - toxic_score (0..1 composite)
      - VPIN, OFI normalized, liquidation cluster proximity
      - funding/OI extremity flags
      - action recommendation (ALLOW / REDUCE / REJECT)
    """
    coord = _get_coordinator()
    if coord is None:
        return {"error": "portfolio coordinator not initialized"}
    return {
        "version": "ACT-XXVII-research-grade-validation",
        "report": coord.get_microstructure_report(),
        "stats": coord.microstructure.stats(),
    }


@app.get("/api/portfolio/regime_hmm")
async def portfolio_regime_hmm():
    """ACT-XXVI: HMM regime overlay — probabilistic belief over BULL/BEAR/HIGH_VOL.

    Returns the most recent RegimeBelief with:
      - probabilities: {BULL, BEAR, HIGH_VOL} posterior
      - dominant state
      - entropy (uncertainty)
      - transition_risk_to_bear (prob of flipping bearish next step)
      - long_bias / short_bias / size_mult
    """
    coord = _get_coordinator()
    if coord is None:
        return {"error": "portfolio coordinator not initialized"}
    return {
        "version": "ACT-XXVII-research-grade-validation",
        "belief": coord.get_regime_belief(),
        "stats": coord.regime_hmm.stats(),
    }


@app.get("/api/portfolio/meta_labeler")
async def portfolio_meta_labeler():
    """ACT-XXVI: meta-labeler (triple-barrier LONG-side filter) stats.

    Returns per-direction outcome counts + current loss streaks +
    ML-readiness flag (becomes True once 300+ LONG outcomes recorded).
    """
    coord = _get_coordinator()
    if coord is None:
        return {"error": "portfolio coordinator not initialized"}
    return {
        "version": "ACT-XXVII-research-grade-validation",
        "stats": coord.meta_labeler.stats(),
    }


@app.get("/api/portfolio/live_gate")
async def portfolio_live_gate():
    """ACT-XXV: evaluate the 6 LIVE_GATE unlock conditions.

    Returns the current gate status. The gate stays LOCKED (PAPER mode)
    until ALL 6 conditions pass simultaneously:
      1. global_win_rate_pct >= 52
      2. verified >= 300
      3. profit_factor > 1.20
      4. max_drawdown_pct < 10
      5. shadow_live_passed = True
      6. execution_engine_verified = True
    """
    coord = _get_coordinator()
    if coord is None:
        return {"error": "portfolio coordinator not initialized"}
    # Pull oracle score for gate evaluation
    try:
        from . import supabase_client
        rows = await supabase_client.fetch_predictions(limit=500)
        verified = [r for r in rows if r.get("outcome") in ("WIN", "LOSS")]
        wins = sum(1 for r in verified if r.get("outcome") == "WIN")
        win_rate = (wins / len(verified) * 100) if verified else 0.0
        oracle_score = {
            "win_rate_pct": win_rate,
            "verified": len(verified),
            "by_window": oracle_runner.get_state().get("directional_stats", {}).get("by_window", {}),
        }
    except Exception:
        oracle_score = {}
    status = coord.evaluate_live_gate(oracle_score=oracle_score)
    return status.to_dict()


@app.post("/api/portfolio/kill_switch")
async def portfolio_kill_switch(reason: str = "manual API trigger"):
    """ACT-XXV: manually trip the kill switch (halts all new trades)."""
    coord = _get_coordinator()
    if coord is None:
        return {"error": "portfolio coordinator not initialized"}
    coord.trip_kill_switch(reason)
    return {"status": "kill_switch_tripped", "reason": reason}


@app.post("/api/portfolio/reset_kill_switch")
async def portfolio_reset_kill_switch(reason: str = "manual API reset"):
    """ACT-XXV: manually reset the kill switch (requires explicit action)."""
    coord = _get_coordinator()
    if coord is None:
        return {"error": "portfolio coordinator not initialized"}
    coord.reset_kill_switch(reason)
    return {"status": "kill_switch_reset", "reason": reason}


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


# ---- ACT-XXVII: Research endpoints (STRICT_ADDITIVE) ----
#
# All endpoints below are NEW — they do not touch any existing endpoint or
# module. They expose the 6 research-layer priorities (PurgedKFold/CPCV,
# calibration, drift detection, research metrics, explainability, and
# observability) via JSON + Prometheus exposition.

@app.get("/api/research/state")
async def research_state():
    """ACT-XXVII: research coordinator state + last full-pass summary."""
    if _research_coord is None:
        return {
            "error": "research coordinator not initialized",
            "init_error": _research_init_err_msg,
            "version": "ACT-XXVII-research-grade-validation",
        }
    last = _research_coord.get_last_report()
    return {
        "version": "ACT-XXVII-research-grade-validation",
        "initialized": True,
        "n_predictions_loaded": len(_research_coord.predictions),
        "feature_names": _research_coord.feature_names,
        "last_pass": (last.to_dict() if last is not None else None),
        "drift_stats": _research_coord.get_drift_stats(),
        "explainer_stats": (
            _research_coord.get_explainer().stats()
            if _research_coord.get_explainer() is not None else None
        ),
    }


@app.post("/api/research/run_full_pass")
async def research_run_full_pass(limit: int = Query(default=0, ge=0, le=10000)):
    """ACT-XXVII Priority 1-5: run a full research pass on loaded predictions.

    Loads predictions from `predictions.jsonl` (or whatever was last loaded),
    then runs PurgedKFold + CPCV + calibration × 3 methods + drift replay +
    research metrics + explainer fit. Returns the aggregate report.
    Pass limit=0 to use all available records.
    """
    if _research_coord is None:
        return {"error": "research coordinator not initialized",
                "init_error": _research_init_err_msg}
    if limit > 0:
        _research_coord.load_predictions(limit=limit)
    elif len(_research_coord.predictions) == 0:
        _research_coord.load_predictions()
    report = _research_coord.run_full_pass()
    return report.to_dict()


@app.get("/api/research/calibration")
async def research_calibration(method: str = "isotonic"):
    """ACT-XXVII Priority 2: run calibration for one method on loaded predictions.

    Returns the CalibrationReport (Brier + ECE + reliability curve before/after).
    """
    if _research_coord is None:
        return {"error": "research coordinator not initialized"}
    if _research_coord.confidences is None or _research_coord.confidences.shape[0] == 0:
        _research_coord.load_predictions()
    if _research_coord.confidences is None or _research_coord.confidences.shape[0] == 0:
        return {"error": "no predictions loaded"}
    from .research import fit_and_evaluate
    rep = fit_and_evaluate(
        y_true=_research_coord.y,
        y_prob=_research_coord.confidences,
        method=method,
        extra={"endpoint": "/api/research/calibration"},
    )
    return rep.to_dict()


@app.get("/api/research/drift")
async def research_drift():
    """ACT-XXVII Priority 3: drift monitor state + last warnings."""
    if _research_coord is None:
        return {"error": "research coordinator not initialized"}
    return {
        "version": "ACT-XXVII-research-grade-validation",
        "drift_stats": _research_coord.get_drift_stats(),
    }


@app.get("/api/research/metrics")
async def research_metrics(window: int = Query(default=50, ge=10, le=1000)):
    """ACT-XXVII Priority 4: research metrics (IC + rolling Sharpe/PF/MDD)."""
    if _research_coord is None:
        return {"error": "research coordinator not initialized"}
    if _research_coord.confidences is None or _research_coord.confidences.shape[0] == 0:
        _research_coord.load_predictions()
    if _research_coord.confidences is None or _research_coord.confidences.shape[0] == 0:
        return {"error": "no predictions loaded"}
    from .research import compute_research_metrics
    preds_signed = _research_coord.confidences * (2 * _research_coord.y - 1)
    realized = (2 * _research_coord.y - 1).astype(float)
    report = compute_research_metrics(
        predictions=preds_signed,
        realized_returns=realized,
        window=window,
        step=max(1, window // 10),
        extra={"endpoint": "/api/research/metrics"},
    )
    return report.to_dict()


@app.post("/api/research/explainer/fit")
async def research_explainer_fit(
    model_type: str = Query(default="tree"),
    prefer_shap: bool = Query(default=True),
):
    """ACT-XXVII Priority 5: fit the explainer surrogate model."""
    if _research_coord is None:
        return {"error": "research coordinator not initialized"}
    if _research_coord.X is None or _research_coord.X.shape[0] == 0:
        _research_coord.load_predictions()
        # Force rebuild of feature matrix
        _research_coord.X, _research_coord.y, _research_coord.confidences, _research_coord.timestamps = \
            _research_coord._build_feature_matrix()
    if _research_coord.X is None or _research_coord.X.shape[0] == 0:
        return {"error": "no predictions loaded"}
    from .research import fit_explainer
    expl = fit_explainer(
        X=_research_coord.X,
        y=_research_coord.y,
        feature_names=_research_coord.feature_names,
        model_type=model_type,
        prefer_shap=prefer_shap,
    )
    _research_coord.explainer = expl
    return {
        "version": "ACT-XXVII-research-grade-validation",
        "stats": expl.stats(),
    }


@app.post("/api/research/explainer/explain")
async def research_explainer_explain(prediction: dict):
    """ACT-XXVII Priority 5: explain a single prediction's feature contributions.

    Body: a prediction dict (must contain the feature fields configured in
    ResearchCoordinator.feature_names).
    """
    if _research_coord is None:
        return {"error": "research coordinator not initialized"}
    if _research_coord.get_explainer() is None:
        return {"error": "explainer not fitted — POST /api/research/explainer/fit first"}
    explanation = _research_coord.explain_prediction(prediction)
    if explanation is None:
        return {"error": "explanation failed"}
    return {
        "version": "ACT-XXVII-research-grade-validation",
        "explanation": explanation,
    }


@app.get("/api/research/explainer/history")
async def research_explainer_history():
    """ACT-XXVII Priority 5: feature importance history (for stability analysis)."""
    if _research_coord is None or _research_coord.get_explainer() is None:
        return {"error": "explainer not fitted",
                "history": []}
    history = _research_coord.get_explainer().feature_importance_history()
    return {
        "version": "ACT-XXVII-research-grade-validation",
        "n_snapshots": len(history),
        "history": history,
    }


@app.get("/api/observability")
async def observability():
    """ACT-XXVII Priority 6: JSON snapshot of all Prometheus metrics."""
    if _metrics_registry is None:
        return {"error": "metrics registry not initialized",
                "init_error": _research_init_err_msg}
    return {
        "version": "ACT-XXVII-research-grade-validation",
        "snapshot": _metrics_registry.stats(),
    }


@app.get("/metrics")
async def prometheus_metrics():
    """ACT-XXVII Priority 6: Prometheus exposition endpoint.

    Returns text/plain Prometheus format (scrape target for Prometheus /
    Grafana / VictoriaMetrics / etc.).
    """
    if _metrics_registry is None:
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(
            "# metrics registry not initialized\n",
            media_type="text/plain; version=0.0.4",
        )
    body, content_type = _metrics_registry.expose()
    # Refresh runtime gauges on each scrape
    _metrics_registry.update_runtime_metrics()
    from fastapi.responses import Response
    return Response(content=body, media_type=content_type)


# ---- static frontend ----
@app.get("/")
async def root():
    idx = FRONTEND_DIR / "index.html"
    if idx.exists():
        return FileResponse(idx)
    return JSONResponse({"error": "frontend not built"}, status_code=404)


if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")
