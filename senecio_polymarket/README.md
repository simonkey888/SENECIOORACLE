# SENECIO ORACLE — Polymarket-Style Trading Intelligence Stack (ACT XX)

A modular, event-sourced, paper-only autonomous trading system inspired by
the Polymarket stack (`poly_data`, `polymarket-cli`, `Polymarket/agents`,
`poly-maker`). All 7 layers are wired through an asyncio event bus and
broadcast to a live dark-terminal dashboard over WebSocket (with SSE
fallback).

> **Paper-only by default.** The execution simulator refuses to place real
> orders. A separate broker adapter must be added to enable live trading.

---

## Architecture (7 Layers)

| # | Layer              | Module(s)                                            | Role                                                        |
|---|--------------------|------------------------------------------------------|-------------------------------------------------------------|
| 1 | **Data**           | `data_retriever.py`, `event_bus.py`, `audit_store.py`| Incremental retriever with resume cursors; append-only log  |
| 2 | **Scanner**        | `scanner_a.py`, `scanner_b.py`, `wallet_tracker.py`, `liquidity.py` | Rank opportunities before reasoning  |
| 3 | **Brain**          | `oracle_engine.py`                                   | 5-check decision pipeline → action vector                   |
| 4 | **Execution**      | `execution_simulator.py`                             | Paper fills, slippage, partials, exits                      |
| 5 | **Agentic**        | `scheduler.py`                                       | Single-planner / multi-tool orchestration loop              |
| 6 | **Liquidity**      | `liquidity.py`                                       | Orderbook depth, spread, slippage estimates                 |
| 7 | **Dashboard**      | `frontend/index.html`, `frontend/app.js`, `frontend/styles.css` | Live event-sourced cockpit (WS / SSE)        |

### Canonical Event Types

Every event that flows through the bus is one of:

- `MARKET_TICK`       — price/volume update
- `WALLET_ALERT`      — whale / smart-money activity
- `MARKET_CANDIDATE`  — scanner-ranked opportunity
- `SIGNAL`            — brain's decision (action + confidence + EV + reasons)
- `EXECUTION_SIM`     — paper order fill (BUY/SELL, qty, slippage, status)
- `RISK_STATE`        — portfolio snapshot (equity, exposure, drawdown)
- `AUDIT_TRACE`       — layer-level trace (INFO/WARN/ERROR)

All events are JSONL-persisted to `data/audit/YYYY-MM-DD.jsonl` (daily-rotated, replayable).

---

## Quick Start

```bash
cd /home/z/my-project/senecio_polymarket
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

Then open:
- **Dashboard:** http://localhost:8000/
- **API docs (Swagger):** http://localhost:8000/docs
- **Stats:** http://localhost:8000/api/stats
- **Audit (latest 100):** http://localhost:8000/api/audit?limit=100&tail=true
- **WebSocket stream:** ws://localhost:8000/ws
- **SSE fallback:** http://localhost:8000/sse

---

## REST + WS API

| Method | Path                                  | Description                                       |
|--------|---------------------------------------|---------------------------------------------------|
| GET    | `/api/health`                         | Liveness probe                                    |
| GET    | `/api/stats`                          | Scheduler + bus + audit + executor + cursor stats |
| GET    | `/api/audit?limit=N&tail=true&type=X` | Audit log (tail mode returns latest N)            |
| GET    | `/api/state`                          | Latest ticks + open positions + SMA cache         |
| GET    | `/api/catalog`                        | Instrument catalog                                |
| GET    | `/api/replay/{YYYY-MM-DD}`            | Full event replay for a given day                 |
| WS     | `/ws?type=...`                        | Live event stream (optional type filter)          |
| SSE    | `/sse?type=...`                       | Server-Sent Events fallback                       |

---

## Decision Brain — 5-Check Pipeline

`OracleEngine.decide()` runs every candidate through:

1. **Base rate**      — historical win rate of this setup type (rolling, self-calibrating)
2. **Catalyst**       — is there a fresh news catalyst? (Benzinga-style headlines)
3. **Market structure** — trend, depth, momentum
4. **Wallet behavior**  — smart-money net flow positive or negative
5. **Calibration**      — weighted confidence must clear `min_confidence=0.55` and `min_ev=0.05`

Output: `SIGNAL` event with `{action, confidence, ev, sizing_usd, checks, reasons}`.

Action vector: `LONG | SHORT | HOLD | EXIT | WATCH`

---

## Execution Simulator — Paper Only

- Fill simulation: midpoint + slippage (2-6 bps)
- Latency: 50-300ms random
- Partial fills: based on book depth
- Position tracking: stop (2% / -2%), target (+4%), time-stop (30min)
- Exits produce `EXECUTION_SIM` events with `realized_pnl`
- `allow_real=True` is intentionally a hard error — real trading requires a separate adapter

---

## File Layout

```
senecio_polymarket/
├── backend/
│   ├── __init__.py
│   ├── models.py                # canonical event schema (Pydantic)
│   ├── event_bus.py             # in-memory pub/sub
│   ├── audit_store.py           # JSONL persistence + replay
│   ├── data_retriever.py        # poly_data-style incremental retriever
│   ├── scanner_a.py             # pre-market gap scanner
│   ├── scanner_b.py             # Trend Join Long breakout scanner
│   ├── wallet_tracker.py        # whale / concentration tracker
│   ├── liquidity.py             # orderbook depth + slippage
│   ├── oracle_engine.py         # LLM-style 5-check brain
│   ├── execution_simulator.py   # paper execution
│   ├── ws_server.py             # WebSocket + SSE
│   ├── scheduler.py             # agentic orchestration loop
│   └── main.py                  # FastAPI app wiring everything
├── frontend/
│   ├── index.html               # dark terminal dashboard
│   ├── app.js                   # WS consumer + renderers + canvas charts
│   └── styles.css               # Polymarket-style dark theme
├── data/audit/                  # daily JSONL event log
├── scripts/
│   ├── run.sh                   # launch uvicorn
│   └── test_run.py              # full verification suite
└── README.md
```

---

## Operational Rules (enforced)

- ✅ No real trading by default (`allow_real=False` is the only safe mode)
- ✅ No manual refresh dependency (WS / SSE push live)
- ✅ No single snapshot source of truth (every decision is event-sourced)
- ✅ All signals are auditable (JSONL log + replay endpoint)
- ✅ All data is timestamped (ISO8601 UTC, every event)
- ✅ Archived repos used as reference architecture only

---

## Production Hardening Roadmap

To take this from paper to production:

1. Replace `data_retriever.py` synthetic feeds with real adapters:
   - CLOB: Polymarket `real-time-data-client` / gamma API
   - On-chain: Alchemy / Etherscan
   - Price feeds: yfinance / ccxt
2. Add a real LLM call in `oracle_engine.py` (`llm_enabled=True`)
3. Add a broker adapter (IB / Alpaca / Polymarket CLOB) that consumes `SIGNAL` events and respects `allow_real`
4. Move audit store from JSONL to SQLite / Postgres for higher throughput
5. Add horizontal scale: multiple scanner workers → Redis pub/sub → multiple brain workers

---

## Test Run (last verified)

```
[+] /api/stats:
    scheduler:  ticks=576 cands_a=9 cands_b=0 signals=9
    bus:        events_published=635
    audit:      files=1 bytes=874472
    executor:   equity=10042.53 open=3 closed=5 pnl=42.53
[+] WS received 200 events; types: ['EXECUTION_SIM', 'MARKET_CANDIDATE', 'MARKET_TICK', 'RISK_STATE', 'SIGNAL', 'WALLET_ALERT']
[+] latest 3 signals:
    GOOGL → LONG conf=0.7 ev=0.2 size=$850.0
    TSLA → LONG conf=0.55 ev=0.05 size=$775.0
    TSLA → LONG conf=0.7 ev=0.2 size=$850.0
[✓] ALL CHECKS PASSED — SENECIO ORACLE ACT XX is operational
```
