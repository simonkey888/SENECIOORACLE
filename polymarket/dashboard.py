"""
SENECIO H-011b — Dashboard web minimalista (Apple Black Mode)
=============================================================
Servidor FastAPI que sirve:
1. Stats del último scan H-011 (detector V2)
2. Paper trading ledger de H-011b (dry_run_ledger.jsonl)
3. Balance virtual, win rate, PnL acumulado

Lee del filesystem del pod:
- /app/polymarket/results/_master_log.jsonl (resumen por scan)
- /app/polymarket/results/scan_*.jsonl (detalle por mercado)
- /app/polymarket/results/dry_run_ledger.jsonl (trades simulados H-011b)

Auto-refresh cada 10 segundos vía JavaScript.
"""
from __future__ import annotations

import os
import json
import glob
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

app = FastAPI(title="SENECIO H-011b Dashboard", docs_url=None, redoc_url=None)

RESULTS_DIR = Path(os.environ.get("H011_RESULTS_DIR", "/app/polymarket/results"))
VIRTUAL_BALANCE_INITIAL = 1000.0


def _safe_read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return out


def get_latest_summary() -> dict[str, Any]:
    master_log = RESULTS_DIR / "_master_log.jsonl"
    lines = _safe_read_jsonl(master_log)
    if not lines:
        return {"error": "no master log yet"}
    return lines[-1]


def get_latest_scan(flagged_only: bool = True, limit: int = 15) -> list[dict[str, Any]]:
    scan_files = sorted(RESULTS_DIR.glob("scan_*.jsonl"))
    if not scan_files:
        return []
    latest_file = scan_files[-1]
    trades = _safe_read_jsonl(latest_file)
    if flagged_only:
        trades = [t for t in trades if t.get("flagged") or t.get("sustained")]
    trades.sort(key=lambda x: x.get("dev_abs") if x.get("dev_abs") is not None else -1, reverse=True)
    return trades[:limit]


def get_dry_run_stats() -> dict[str, Any]:
    """Lee dry_run_ledger.jsonl y calcula stats de paper trading."""
    ledger_file = RESULTS_DIR / "dry_run_ledger.jsonl"
    ledger = _safe_read_jsonl(ledger_file)

    total_trades = len(ledger)
    virtual_balance = VIRTUAL_BALANCE_INITIAL
    profit_loss = 0.0
    win_rate = 0.0

    if total_trades > 0:
        profit_loss = sum(t.get("pnl", 0.0) for t in ledger)
        virtual_balance += profit_loss
        wins = sum(1 for t in ledger if t.get("pnl", 0.0) > 0)
        win_rate = (wins / total_trades) * 100

    return {
        "virtual_balance": round(virtual_balance, 2),
        "total_trades": total_trades,
        "win_rate": round(win_rate, 1),
        "profit_loss": round(profit_loss, 2),
        "trades": ledger[-10:],  # últimos 10 trades
    }


def get_history(n: int = 20) -> list[dict[str, Any]]:
    master_log = RESULTS_DIR / "_master_log.jsonl"
    lines = _safe_read_jsonl(master_log)
    return lines[-n:]


def get_full_history() -> list[dict[str, Any]]:
    master_log = RESULTS_DIR / "_master_log.jsonl"
    return _safe_read_jsonl(master_log)


@app.get("/api/data")
def api_data() -> JSONResponse:
    summary = get_latest_summary()
    scan = get_latest_scan(flagged_only=True, limit=15)
    history = get_history(n=20)
    full_history = get_full_history()
    dry_run = get_dry_run_stats()
    return JSONResponse({
        "summary": summary,
        "scan": scan,
        "history": history,
        "full_history": full_history,
        "dry_run": dry_run,
    })


@app.get("/", response_class=HTMLResponse)
def dashboard() -> HTMLResponse:
    html = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<meta name="theme-color" content="#000000">
<title>SENECIO H-011b — Dry-Run Ledger</title>
<style>
:root {
    --bg: #000000;
    --surface: #0a0a0a;
    --border: #1c1c1e;
    --text-primary: #ededed;
    --text-secondary: #767677;
    --accent-green: #32d74b;
    --accent-red: #ff453a;
    --accent-blue: #0a84ff;
    --accent-orange: #ff9f0a;
}
* { box-sizing: border-box; }
html, body {
    background-color: var(--bg);
    color: var(--text-primary);
    margin: 0; padding: 0;
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Inter", sans-serif;
    -webkit-font-smoothing: antialiased;
    font-feature-settings: "tnum" 1;
    line-height: 1.4;
}
body { padding: 40px 20px 80px; display: flex; justify-content: center; min-height: 100vh; }
.container { max-width: 900px; width: 100%; }
.header {
    display: flex; justify-content: space-between; align-items: baseline;
    border-bottom: 1px solid var(--border);
    padding-bottom: 20px; margin-bottom: 30px;
}
h1 { font-size: 22px; font-weight: 500; margin: 0; letter-spacing: -0.022em; }
h1 .sub { font-weight: 300; color: var(--text-secondary); margin-left: 6px; }
h2 { font-size: 14px; font-weight: 500; color: var(--text-secondary); margin: 30px 0 15px 0; text-transform: uppercase; letter-spacing: 0.5px;}
.status { font-size: 12px; color: var(--text-secondary); text-align: right; }
.status .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: var(--text-secondary); margin-right: 6px; vertical-align: middle; }
.status .dot.live { background: var(--accent-green); box-shadow: 0 0 8px rgba(50,215,75,0.5); }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 15px; margin-bottom: 30px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 20px; }
.card-label { font-size: 11px; color: var(--text-secondary); text-transform: uppercase; margin-bottom: 6px; letter-spacing: 0.06em; }
.card-value { font-size: 26px; font-weight: 400; letter-spacing: -0.02em; }
.green { color: var(--accent-green); }
.red { color: var(--accent-red); }
.blue { color: var(--accent-blue); }
.orange { color: var(--accent-orange); }
table { width: 100%; border-collapse: collapse; }
th, td { text-align: left; padding: 12px 8px; border-bottom: 1px solid var(--border); font-size: 13px; }
th { color: var(--text-secondary); font-weight: 400; font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em; }
.mono { font-family: "SF Mono", "JetBrains Mono", Menlo, monospace; font-variant-numeric: tabular-nums; }
.tag { font-size: 10px; padding: 3px 8px; border-radius: 4px; background: rgba(10,132,255,0.12); color: var(--accent-blue); border: 1px solid rgba(10,132,255,0.25); display: inline-block; }
.empty { text-align: center; color: var(--text-secondary); padding: 40px 20px; font-size: 14px; }
.footer { margin-top: 40px; padding-top: 20px; border-top: 1px solid var(--border); color: var(--text-secondary); font-size: 11px; display: flex; justify-content: space-between; }
@media (max-width: 600px) { body { padding: 20px 12px 60px; } h1 { font-size: 18px; } .card-value { font-size: 22px; } }
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>SENECIO H-011b <span class="sub">Dry-Run Ledger</span></h1>
        <div class="status">
            <div><span class="dot" id="status-dot"></span><span id="status-text">conectando…</span></div>
            <div id="last-updated" style="margin-top:4px;color:var(--text-secondary);font-size:11px;">—</div>
        </div>
    </div>

    <div class="grid">
        <div class="card">
            <div class="card-label">Balance Virtual</div>
            <div class="card-value green" id="val-balance">$1000.00</div>
        </div>
        <div class="card">
            <div class="card-label">Trades Simulados</div>
            <div class="card-value" id="val-trades">0</div>
        </div>
        <div class="card">
            <div class="card-label">Win Rate</div>
            <div class="card-value" id="val-wr">0.0%</div>
        </div>
        <div class="card">
            <div class="card-label">PnL Acumulado</div>
            <div class="card-value" id="val-pnl">$0.00</div>
        </div>
    </div>

    <h2>Detector H-011 (último scan)</h2>
    <div class="grid">
        <div class="card">
            <div class="card-label">Mercados escaneados</div>
            <div class="card-value" id="stat-scanned">—</div>
        </div>
        <div class="card">
            <div class="card-label">Sustained ≥5pp</div>
            <div class="card-value red" id="stat-sustained">—</div>
        </div>
        <div class="card">
            <div class="card-label">Max desviación</div>
            <div class="card-value" id="stat-maxdev">—</div>
        </div>
    </div>

    <h2>Historial de ejecución simulada (H-011b)</h2>
    <table>
        <thead>
            <tr>
                <th>Timestamp</th>
                <th>Mercado</th>
                <th>Precio YES</th>
                <th>Precio NO</th>
                <th>Suma</th>
                <th>Tamaño</th>
                <th>PnL Est.</th>
            </tr>
        </thead>
        <tbody id="trades-body">
            <tr><td colspan="7" class="empty">Esperando primera transacción simulada…</td></tr>
        </tbody>
    </table>

    <h2>Top desviaciones activas (último scan)</h2>
    <table>
        <thead>
            <tr>
                <th>Estado</th>
                <th>Mercado</th>
                <th>Suma</th>
                <th>Desv</th>
            </tr>
        </thead>
        <tbody id="table-body">
            <tr><td colspan="4" class="empty">Cargando…</td></tr>
        </tbody>
    </table>

    <div class="footer">
        <div>SENECIO H-011b FASE_0.5 · DRY-RUN · sin capital real</div>
        <div><a href="/api/data" target="_blank" style="color:var(--text-secondary);text-decoration:none;">/api/data</a></div>
    </div>
</div>
<script>
const fmt = (n, d=4) => n !== null && n !== undefined ? Number(n).toFixed(d) : '—';
const fmtPct = (n, d=2) => n !== null && n !== undefined ? (n*100).toFixed(d)+'pp' : '—';
const fmtSigned = (n, d=2) => { if(n===null||n===undefined) return '—'; const v=(n*100).toFixed(d); return (n>0?'+':'')+v+'pp'; };

async function fetchData() {
    try {
        const res = await fetch('/api/data');
        if (!res.ok) throw new Error('HTTP '+res.status);
        const data = await res.json();

        const s = data.summary || {};
        const scan = data.scan || [];
        const dr = data.dry_run || {};

        // Status dot
        const dot = document.getElementById('status-dot');
        const statusText = document.getElementById('status-text');
        if (s.error) { dot.className='dot'; statusText.textContent='sin datos'; }
        else {
            const ts = s.timestamp_utc ? new Date(s.timestamp_utc) : null;
            const ageMin = ts ? (Date.now()-ts.getTime())/60000 : 999;
            if (ageMin < 20) { dot.className='dot live'; statusText.textContent='en vivo'; }
            else { dot.className='dot'; statusText.textContent='scan reciente'; }
        }
        if (s.timestamp_utc) {
            const d = new Date(s.timestamp_utc);
            document.getElementById('last-updated').textContent = 'último scan: '+d.toISOString().slice(0,16).replace('T',' ')+' UTC';
        }

        // Dry-run stats
        document.getElementById('val-balance').textContent = '$'+(dr.virtual_balance||1000).toFixed(2);
        document.getElementById('val-trades').textContent = dr.total_trades||0;
        document.getElementById('val-wr').textContent = (dr.win_rate||0).toFixed(1)+'%';
        const pnlEl = document.getElementById('val-pnl');
        const pnl = dr.profit_loss||0;
        pnlEl.textContent = (pnl>=0?'+$':'-$')+Math.abs(pnl).toFixed(2);
        pnlEl.className = 'card-value '+(pnl>=0?'green':'red');

        // Detector stats
        document.getElementById('stat-scanned').textContent = s.markets_scanned||'—';
        document.getElementById('stat-sustained').textContent = s.markets_sustained||'—';
        const ds = s.deviation_stats||{};
        document.getElementById('stat-maxdev').textContent = ds.max!==undefined ? fmtPct(ds.max) : '—';

        // Dry-run trades table
        const tradesBody = document.getElementById('trades-body');
        if (dr.trades && dr.trades.length > 0) {
            tradesBody.innerHTML = '';
            dr.trades.slice().reverse().forEach(t => {
                const pnlClass = t.pnl >= 0 ? 'green' : 'red';
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td class="mono">${new Date(t.timestamp).toLocaleTimeString()}</td>
                    <td>${(t.question||'?').substring(0,30)}…</td>
                    <td class="mono">${fmt(t.price_yes)}</td>
                    <td class="mono">${fmt(t.price_no)}</td>
                    <td class="mono">${fmt(t.sum)}</td>
                    <td class="mono">$${(t.size||0).toFixed(2)}</td>
                    <td class="mono ${pnlClass}">${t.pnl>=0?'+':''}$${(t.pnl||0).toFixed(2)}</td>
                `;
                tradesBody.appendChild(tr);
            });
        } else {
            tradesBody.innerHTML = '<tr><td colspan="7" class="empty">Sin trades simulados aún.</td></tr>';
        }

        // Scan deviations table
        const tbody = document.getElementById('table-body');
        if (scan.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" class="empty">Sin anomalías.</td></tr>';
        } else {
            tbody.innerHTML = '';
            scan.forEach(m => {
                const isSust = m.sustained;
                const isUnder = (m.dev_signed||0) < 0;
                const tag = isSust ? '<span class="tag" style="background:rgba(255,69,58,0.12);color:var(--accent-red);border-color:rgba(255,69,58,0.25);">SUST</span>' :
                            '<span class="tag">FLAG</span>';
                const under = isUnder ? ' <span class="tag" style="background:rgba(50,215,75,0.12);color:var(--accent-green);border-color:rgba(50,215,75,0.25);">UNDER</span>' : '';
                const devClass = (m.dev_signed||0) > 0 ? 'orange' : 'green';
                const tr = document.createElement('tr');
                tr.innerHTML = `<td>${tag}${under}</td><td style="max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${m.question||'—'}</td><td class="mono">${fmt(m.sum_vwap)}</td><td class="mono ${devClass}">${fmtSigned(m.dev_signed)}</td>`;
                tbody.appendChild(tr);
            });
        }
    } catch(err) {
        console.error('fetch error', err);
        document.getElementById('status-dot').className = 'dot';
        document.getElementById('status-text').textContent = 'error';
    }
}
fetchData();
setInterval(fetchData, 10000);
</script>
</body>
</html>
"""
    return HTMLResponse(content=html)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
