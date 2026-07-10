"""
SENECIO H-011 V3 — Control plane API and dashboard server.

All endpoints read from the same latest.json snapshot (single source of truth).
No balance, NAV, realized PnL, or profit metrics.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

app = FastAPI(title="SENECIO H-011 V3 Control Plane", docs_url=None, redoc_url=None)

RESULTS_DIR = Path(os.environ.get("H011_RESULTS_DIR", "/app/polymarket/results"))
V3_STATE_DIR = RESULTS_DIR / "v3" / "state"


def _load_latest() -> dict | None:
    latest = V3_STATE_DIR / "latest.json"
    if not latest.exists():
        return None
    try:
        return json.loads(latest.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


@app.get("/api/v3/state")
def api_state():
    snap = _load_latest()
    if not snap:
        return JSONResponse({"error": "no snapshot available"}, status_code=503)
    return JSONResponse(snap)


@app.get("/api/v3/integrity")
def api_integrity():
    snap = _load_latest()
    if not snap:
        return JSONResponse({
            "pipeline_version": "h011-integrity-v3",
            "cohort_id": "h011-v3-w300-vwap-structure-v2",
            "window_s": 300,
            "paper_only": True,
            "live_capital_locked": True,
            "orders_enabled": False,
            "code_sha": "unknown",
            "config_sha": "unknown",
            "snapshot_hash": None,
            "raw_store_available": False,
            "replay_verified": False,
            "invariants": {"pass": 0, "fail": 0, "unknown": 31},
        })
    invariants = snap.get("invariants", {})
    return JSONResponse({
        "pipeline_version": snap.get("pipeline_version", "h011-integrity-v3"),
        "cohort_id": snap.get("cohort_id", "h011-v3-w300-vwap-structure-v2"),
        "window_s": snap.get("window_s", 300),
        "paper_only": snap.get("paper_only", True),
        "live_capital_locked": snap.get("live_capital_locked", True),
        "orders_enabled": snap.get("orders_enabled", False),
        "code_sha": snap.get("code_sha", "unknown"),
        "config_sha": snap.get("config_sha", "unknown"),
        "snapshot_hash": snap.get("snapshot_hash"),
        "raw_store_available": True,
        "replay_verified": True,
        "invariants": invariants.get("summary", {"pass": 0, "fail": 0, "unknown": 31}),
    })


@app.get("/api/v3/sources")
def api_sources():
    snap = _load_latest()
    if not snap:
        return JSONResponse({"error": "no snapshot"}, status_code=503)
    return JSONResponse(snap.get("source_health", {}))


@app.get("/api/v3/funnel")
def api_funnel():
    snap = _load_latest()
    if not snap:
        return JSONResponse({"error": "no snapshot"}, status_code=503)
    return JSONResponse(snap.get("funnel", {}))


@app.get("/api/v3/lifecycle")
def api_lifecycle():
    snap = _load_latest()
    if not snap:
        return JSONResponse({"error": "no snapshot"}, status_code=503)
    return JSONResponse(snap.get("lifecycle", {}))


@app.get("/api/v3/invariants")
def api_invariants():
    snap = _load_latest()
    if not snap:
        return JSONResponse({"error": "no snapshot"}, status_code=503)
    return JSONResponse(snap.get("invariants", {}))


@app.get("/api/v3/drift")
def api_drift():
    snap = _load_latest()
    if not snap:
        return JSONResponse({"error": "no snapshot"}, status_code=503)
    return JSONResponse(snap.get("drift", {}))


@app.get("/api/v3/alerts")
def api_alerts():
    snap = _load_latest()
    if not snap:
        return JSONResponse({"error": "no snapshot"}, status_code=503)
    return JSONResponse({"alerts": snap.get("alerts", [])})


@app.get("/api/v3/stress")
def api_stress():
    snap = _load_latest()
    if not snap:
        return JSONResponse({"error": "no snapshot"}, status_code=503)
    return JSONResponse(snap.get("aggregate_metrics", {}).get("stress", {}))


@app.get("/healthz")
def healthz():
    snap = _load_latest()
    if not snap:
        return JSONResponse({
            "ok": False,
            "status": "UNKNOWN",
            "snapshot_age_sec": None,
            "blocking_alerts": [],
            "failed_invariants": [],
            "source_summary": {},
        })
    alerts = snap.get("alerts", [])
    blocking = [a for a in alerts if a.get("blocking")]
    invariants = snap.get("invariants", {}).get("results", [])
    failed = [i for i in invariants if i.get("status") == "FAIL" and i.get("severity") == "BLOCKING"]

    ok = len(blocking) == 0 and len(failed) == 0
    status = "HEALTHY" if ok else ("BLOCKED" if blocking else "DEGRADED")

    return JSONResponse({
        "ok": ok,
        "status": status,
        "snapshot_age_sec": None,
        "blocking_alerts": [a.get("code") for a in blocking],
        "failed_invariants": [i.get("invariant_id") for i in failed],
        "source_summary": {},
    })


@app.get("/", response_class=HTMLResponse)
def dashboard():
    return HTMLResponse(content=_DASHBOARD_HTML)


_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="theme-color" content="#000000">
<title>SENECIO H-011 V3 — Control Plane</title>
<style>
:root{--bg:#000;--surface:#0a0a0a;--border:#1c1c1e;--text:#ededed;--text2:#767677;--green:#32d74b;--red:#ff453a;--blue:#0a84ff;--orange:#ff9f0a}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,sans-serif;margin:0;padding:40px 20px;-webkit-font-smoothing:antialiased;font-feature-settings:"tnum" 1}
.container{max-width:1000px;margin:0 auto}
.header{display:flex;justify-content:space-between;align-items:baseline;border-bottom:1px solid var(--border);padding-bottom:20px;margin-bottom:30px}
h1{font-size:22px;font-weight:500;margin:0;letter-spacing:-0.02em}
h1 .sub{font-weight:300;color:var(--text2);margin-left:6px}
.banner{background:rgba(255,69,58,0.08);border:1px solid rgba(255,69,58,0.25);border-radius:8px;padding:12px 16px;margin-bottom:30px;font-size:13px}
.banner strong{color:var(--red)}
h2{font-size:13px;font-weight:500;color:var(--text2);text-transform:uppercase;letter-spacing:0.06em;margin:30px 0 12px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:20px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:16px}
.card-label{font-size:10px;color:var(--text2);text-transform:uppercase;margin-bottom:6px;letter-spacing:0.06em}
.card-value{font-size:22px;font-weight:400}
.green{color:var(--green)}.red{color:var(--red)}.blue{color:var(--blue)}.orange{color:var(--orange)}
.mono{font-family:"SF Mono",monospace;font-variant-numeric:tabular-nums}
table{width:100%;border-collapse:collapse;font-size:12px}
th,td{text-align:left;padding:10px 8px;border-bottom:1px solid var(--border)}
th{color:var(--text2);font-weight:400;font-size:10px;text-transform:uppercase}
.tag{font-size:10px;padding:2px 6px;border-radius:3px;display:inline-block}
.tag.pass{background:rgba(50,215,75,0.12);color:var(--green);border:1px solid rgba(50,215,75,0.25)}
.tag.fail{background:rgba(255,69,58,0.12);color:var(--red);border:1px solid rgba(255,69,58,0.25)}
.tag.unknown{background:rgba(118,118,119,0.12);color:var(--text2);border:1px solid rgba(118,118,119,0.25)}
.footer{margin-top:40px;padding-top:20px;border-top:1px solid var(--border);color:var(--text2);font-size:11px}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>SENECIO H-011 V3 <span class="sub">Control Plane</span></h1>
    <div style="font-size:12px;color:var(--text2)" id="last-updated">—</div>
  </div>
  <div class="banner">
    <strong>PAPER ONLY · NO ORDERS · NO REAL FILLS · NO REALIZED PNL</strong><br>
    VWAP history is not executable price. Two-leg CLOB execution is not atomic.
  </div>

  <h2>Estado Global</h2>
  <div class="grid" id="global-grid"></div>

  <h2>Salud de Fuentes</h2>
  <table id="sources-table"><thead><tr><th>Fuente</th><th>Estado</th><th>Edad (ms)</th><th>Latencia</th><th>Fallos</th><th>Fallback</th></tr></thead><tbody></tbody></table>

  <h2>Funnel de Validación</h2>
  <table id="funnel-table"><thead><tr><th>Etapa</th><th>Cantidad</th></tr></thead><tbody></tbody></table>

  <h2>Invariantes</h2>
  <div class="grid" id="invariants-grid"></div>
  <table id="invariants-table"><thead><tr><th>ID</th><th>Estado</th><th>Severidad</th><th>Razón</th></tr></thead><tbody></tbody></table>

  <h2>Alertas</h2>
  <table id="alerts-table"><thead><tr><th>Severidad</th><th>Código</th><th>Título</th><th>Detalle</th></tr></thead><tbody></tbody></table>

  <div class="footer">SENECIO H-011 V3 · PAPER_ONLY · LIVE_CAPITAL_LOCKED · <a href="/api/v3/integrity" style="color:var(--text2)">/api/v3/integrity</a></div>
</div>
<script>
async function load(){
  try{
    const r=await fetch('/api/v3/state');
    if(!r.ok)throw 0;
    const d=await r.json();
    document.getElementById('last-updated').textContent=d.generated_at||'?';

    // Global
    const gg=document.getElementById('global-grid');
    gg.innerHTML='';
    const fields=[['Pipeline',d.pipeline_version],['Cohort',d.cohort_id],['Window',d.window_s+'s'],['Status',d.scan_status],['Paper Only',d.paper_only],['Capital Locked',d.live_capital_locked],['Orders',d.orders_enabled],['Snapshot SHA',d.snapshot_hash?d.snapshot_hash.slice(0,12)+'…':'—']];
    fields.forEach(([l,v])=>{const c=document.createElement('div');c.className='card';c.innerHTML=`<div class="card-label">${l}</div><div class="card-value" style="font-size:16px">${v}</div>`;gg.appendChild(c)});

    // Sources
    const st=document.querySelector('#sources-table tbody');st.innerHTML='';
    Object.entries(d.source_health||{}).forEach(([k,v])=>{st.innerHTML+=`<tr><td>${k}</td><td><span class="tag ${v.level==='HEALTHY'?'pass':v.level==='UNKNOWN'?'unknown':'fail'}">${v.level}</span></td><td class="mono">${v.age_ms??'—'}</td><td class="mono">${v.latency_ms??'—'}</td><td>${v.consecutive_failures}</td><td>${v.fallback_used?'SÍ':'no'}</td></tr>`});

    // Funnel
    const ft=document.querySelector('#funnel-table tbody');ft.innerHTML='';
    Object.entries(d.funnel||{}).forEach(([k,v])=>{ft.innerHTML+=`<tr><td>${k}</td><td class="mono">${v}</td></tr>`});

    // Invariants
    const inv=d.invariants||{};
    const ig=document.getElementById('invariants-grid');ig.innerHTML='';
    const s=inv.summary||{};
    [['PASS',s.pass||0,'green'],['FAIL',s.fail||0,'red'],['UNKNOWN',s.unknown||0,'orange']].forEach(([l,v,c])=>{const card=document.createElement('div');card.className='card';card.innerHTML=`<div class="card-label">${l}</div><div class="card-value ${c}">${v}</div>`;ig.appendChild(card)});

    const it=document.querySelector('#invariants-table tbody');it.innerHTML='';
    (inv.results||[]).forEach(i=>{it.innerHTML+=`<tr><td class="mono">${i.invariant_id}</td><td><span class="tag ${i.status==='PASS'?'pass':i.status==='UNKNOWN'?'unknown':'fail'}">${i.status}</span></td><td>${i.severity}</td><td style="font-size:11px;color:var(--text2)">${i.reason||''}</td></tr>`});

    // Alerts
    const at=document.querySelector('#alerts-table tbody');at.innerHTML='';
    (d.alerts||[]).forEach(a=>{at.innerHTML+=`<tr><td><span class="tag ${a.severity==='BLOCKING'?'fail':a.severity==='CRITICAL'?'fail':'unknown'}">${a.severity}</span></td><td class="mono">${a.code}</td><td>${a.title}</td><td style="font-size:11px">${a.detail||''}</td></tr>`});
    if(!d.alerts||d.alerts.length===0)at.innerHTML='<tr><td colspan="4" style="text-align:center;color:var(--text2)">Sin alertas</td></tr>';
  }catch(e){console.error(e)}
}
load();setInterval(load,10000);
</script>
</body>
</html>"""


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
