"""
SENECIO H-011 — Dashboard web minimalista (Apple Dark / Twenty style)
=====================================================================
Servidor FastAPI que sirve un dashboard HTML ultra-minimalista con los
resultados del último scan de vwap_detector_v2.py.

Lee del filesystem del pod:
- /app/polymarket/results/_master_log.jsonl (resumen por scan)
- /app/polymarket/results/scan_*.jsonl (detalle por mercado)

Auto-refresh cada 15 segundos vía JavaScript (sin recargar página).

Diseño: negro puro #000, tipografía SF Pro / Inter, acentos sutiles solo
cuando la data lo exige (rojo para sustained, gris para flagged).

Run standalone:
  python3 dashboard.py
  # → http://localhost:8080
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

app = FastAPI(title="SENECIO H-011 Dashboard", docs_url=None, redoc_url=None)

RESULTS_DIR = Path(os.environ.get("H011_RESULTS_DIR", "/app/polymarket/results"))


def _safe_read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Lee un JSONL y devuelve lista de dicts. Tolerante a líneas malformadas."""
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
    """Lee la última línea del _master_log.jsonl (resumen del último scan)."""
    master_log = RESULTS_DIR / "_master_log.jsonl"
    lines = _safe_read_jsonl(master_log)
    if not lines:
        return {"error": "no master log yet", "results_dir": str(RESULTS_DIR)}
    return lines[-1]


def get_latest_scan(flagged_only: bool = True, limit: int = 15) -> list[dict[str, Any]]:
    """
    Lee el archivo scan_*.jsonl más reciente.
    Filtra solo flagged/sustained (por defecto).
    Ordena por dev_abs descendente, limita a `limit` resultados.
    """
    scan_files = sorted(RESULTS_DIR.glob("scan_*.jsonl"))
    if not scan_files:
        return []
    latest_file = scan_files[-1]  # sort by filename (timestamp embedded in name)
    trades = _safe_read_jsonl(latest_file)

    if flagged_only:
        trades = [t for t in trades if t.get("flagged") or t.get("sustained")]

    # Sort por dev_abs desc, None al final
    trades.sort(key=lambda x: x.get("dev_abs") if x.get("dev_abs") is not None else -1, reverse=True)

    return trades[:limit]


def get_history(n: int = 20) -> list[dict[str, Any]]:
    """Últimas N entradas del master_log (para mini-trend)."""
    master_log = RESULTS_DIR / "_master_log.jsonl"
    lines = _safe_read_jsonl(master_log)
    return lines[-n:]


def get_full_history() -> list[dict[str, Any]]:
    """TODAS las entradas del master_log (para análisis Día 8)."""
    master_log = RESULTS_DIR / "_master_log.jsonl"
    return _safe_read_jsonl(master_log)


@app.get("/api/data")
def api_data() -> JSONResponse:
    """API JSON para el frontend JavaScript."""
    summary = get_latest_summary()
    scan = get_latest_scan(flagged_only=True, limit=15)
    history = get_history(n=20)
    full_history = get_full_history()
    return JSONResponse({
        "summary": summary,
        "scan": scan,
        "history": history,
        "full_history": full_history,
    })


@app.get("/", response_class=HTMLResponse)
def dashboard() -> HTMLResponse:
    """Dashboard HTML ultra-minimalista."""
    html = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<meta name="theme-color" content="#000000">
<title>SENECIO H-011 — VWAP Cross-Leg</title>
<style>
:root {
    --bg: #000000;
    --surface: #0e0e0e;
    --surface-2: #161616;
    --border: #1f1f1f;
    --border-hover: #2a2a2a;
    --text-primary: #f5f5f7;
    --text-secondary: #86868b;
    --text-tertiary: #48484a;
    --accent-red: #ff453a;
    --accent-blue: #0a84ff;
    --accent-green: #30d158;
    --accent-orange: #ff9f0a;
}
* { box-sizing: border-box; }
html, body {
    background-color: var(--bg);
    color: var(--text-primary);
    margin: 0; padding: 0;
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Inter", "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
    font-feature-settings: "tnum" 1; /* tabular numbers */
    line-height: 1.4;
}
body {
    padding: 48px 24px 80px;
    display: flex;
    justify-content: center;
    min-height: 100vh;
}
.container {
    max-width: 980px;
    width: 100%;
}
/* HEADER */
.header {
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
    margin-bottom: 48px;
    padding-bottom: 24px;
    border-bottom: 1px solid var(--border);
}
.title {
    font-size: 28px;
    font-weight: 500;
    letter-spacing: -0.022em;
    margin: 0;
}
.title .sub {
    color: var(--text-secondary);
    font-weight: 400;
    margin-left: 6px;
}
.status {
    font-size: 13px;
    color: var(--text-secondary);
    text-align: right;
}
.status .dot {
    display: inline-block;
    width: 8px; height: 8px;
    border-radius: 50%;
    background: var(--text-tertiary);
    margin-right: 6px;
    vertical-align: middle;
}
.status .dot.live { background: var(--accent-green); box-shadow: 0 0 8px rgba(48,209,88,0.5); }
.status .dot.stale { background: var(--accent-orange); }
.status .dot.dead { background: var(--accent-red); }

/* STATS GRID */
.stats-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 16px;
    margin-bottom: 56px;
}
.stat-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 20px 22px;
    transition: border-color 0.2s;
}
.stat-card:hover { border-color: var(--border-hover); }
.stat-label {
    font-size: 11px;
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-bottom: 10px;
    font-weight: 500;
}
.stat-value {
    font-size: 32px;
    font-weight: 400;
    margin: 0;
    letter-spacing: -0.02em;
}
.stat-value.red { color: var(--accent-red); }
.stat-value.blue { color: var(--accent-blue); }
.stat-value.orange { color: var(--accent-orange); }
.stat-sub {
    font-size: 11px;
    color: var(--text-tertiary);
    margin-top: 6px;
}

/* SECTION TITLE */
.section-title {
    font-size: 14px;
    font-weight: 500;
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin: 0 0 16px 4px;
}

/* TABLE */
.table-wrap {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 14px;
    overflow: hidden;
}
table {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
}
th, td {
    text-align: left;
    padding: 14px 16px;
    border-bottom: 1px solid var(--border);
    vertical-align: middle;
}
th {
    color: var(--text-secondary);
    font-weight: 500;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    background: var(--surface-2);
}
tr:last-child td { border-bottom: none; }
tr:hover td { background: rgba(255,255,255,0.02); }
.name-cell {
    max-width: 320px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    color: var(--text-primary);
}
.cid-cell {
    font-family: "SF Mono", "JetBrains Mono", Menlo, monospace;
    font-size: 11px;
    color: var(--text-tertiary);
}
.num { font-variant-numeric: tabular-nums; }
.tag {
    font-size: 10px;
    padding: 3px 8px;
    border-radius: 4px;
    background: rgba(255,255,255,0.06);
    color: var(--text-secondary);
    font-weight: 500;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    display: inline-block;
}
.tag.sustained {
    background: rgba(255, 69, 58, 0.12);
    color: var(--accent-red);
    border: 1px solid rgba(255, 69, 58, 0.25);
}
.tag.flagged {
    background: rgba(255, 159, 10, 0.12);
    color: var(--accent-orange);
    border: 1px solid rgba(255, 159, 10, 0.25);
}
.tag.underpriced {
    background: rgba(48, 209, 88, 0.12);
    color: var(--accent-green);
    border: 1px solid rgba(48, 209, 88, 0.25);
}
.dev-pos { color: var(--accent-orange); }
.dev-neg { color: var(--accent-green); }
.empty {
    text-align: center;
    color: var(--text-tertiary);
    padding: 60px 20px;
    font-size: 14px;
}

/* MINI TREND */
.trend-row {
    display: flex;
    align-items: end;
    gap: 2px;
    height: 24px;
    margin-top: 8px;
}
.trend-bar {
    flex: 1;
    background: var(--border);
    border-radius: 1px;
    min-height: 2px;
    transition: background 0.2s;
}
.trend-bar.high { background: var(--accent-red); }
.trend-bar.med { background: var(--accent-orange); }
.trend-bar.low { background: var(--text-tertiary); }

/* FOOTER */
.footer {
    margin-top: 60px;
    padding-top: 24px;
    border-top: 1px solid var(--border);
    color: var(--text-tertiary);
    font-size: 11px;
    display: flex;
    justify-content: space-between;
}
.footer a { color: var(--text-secondary); text-decoration: none; }
.footer a:hover { color: var(--text-primary); }

@media (max-width: 600px) {
    body { padding: 24px 16px 60px; }
    .title { font-size: 22px; }
    .stat-value { font-size: 26px; }
    .name-cell { max-width: 180px; }
    th, td { padding: 12px 10px; font-size: 12px; }
}
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1 class="title">SENECIO H-011 <span class="sub">VWAP Cross-Leg</span></h1>
        <div class="status">
            <div><span class="dot" id="status-dot"></span><span id="status-text">conectando…</span></div>
            <div id="last-updated" style="margin-top:4px;color:var(--text-tertiary);font-size:11px;">—</div>
        </div>
    </div>

    <div class="stats-grid">
        <div class="stat-card">
            <div class="stat-label">Mercados escaneados</div>
            <div class="stat-value num" id="stat-scanned">—</div>
            <div class="stat-sub" id="stat-trades">— con trades</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Sustained ≥5pp</div>
            <div class="stat-value num red" id="stat-sustained">—</div>
            <div class="stat-sub" id="stat-flagged">— flagged ≥2pp</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Desviación máx</div>
            <div class="stat-value num" id="stat-maxdev">—</div>
            <div class="stat-sub" id="stat-median">mediana —</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Criterio Día 8</div>
            <div class="stat-value num" id="stat-criteria" style="font-size:22px;">—</div>
            <div class="stat-sub">≥5 sustained en ≥3 scans</div>
            <div class="trend-row" id="trend-row"></div>
        </div>
    </div>

    <h2 class="section-title">Top desviaciones activas (último scan)</h2>
    <div class="table-wrap">
        <table>
            <thead>
                <tr>
                    <th style="width:36px;"></th>
                    <th>Mercado</th>
                    <th>VWAP Y</th>
                    <th>VWAP N</th>
                    <th>Suma</th>
                    <th>Desv</th>
                    <th>Trades</th>
                </tr>
            </thead>
            <tbody id="table-body">
                <tr><td colspan="7" class="empty">Cargando datos…</td></tr>
            </tbody>
        </table>
    </div>

    <div class="footer">
        <div>SENECIO H-011 FASE_0 · READ-ONLY · sin ejecución de órdenes</div>
        <div><a href="/api/data" target="_blank">/api/data</a></div>
    </div>
</div>

<script>
const fmt = (n, d=4) => n !== null && n !== undefined ? Number(n).toFixed(d) : '—';
const fmtPct = (n, d=2) => n !== null && n !== undefined ? (n * 100).toFixed(d) + 'pp' : '—';
const fmtSigned = (n, d=2) => {
    if (n === null || n === undefined) return '—';
    const v = (n * 100).toFixed(d);
    return (n > 0 ? '+' : '') + v + 'pp';
};

async function fetchData() {
    try {
        const res = await fetch('/api/data');
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();

        const s = data.summary || {};
        const scan = data.scan || [];
        const history = data.history || [];

        // Status dot
        const dot = document.getElementById('status-dot');
        const statusText = document.getElementById('status-text');
        if (s.error) {
            dot.className = 'dot dead';
            statusText.textContent = 'sin datos';
        } else {
            const ts = s.timestamp_utc ? new Date(s.timestamp_utc) : null;
            const ageMin = ts ? (Date.now() - ts.getTime()) / 60000 : 999;
            if (ageMin < 20) { dot.className = 'dot live'; statusText.textContent = 'en vivo'; }
            else if (ageMin < 60) { dot.className = 'dot stale'; statusText.textContent = 'scan reciente'; }
            else { dot.className = 'dot dead'; statusText.textContent = 'sin scans recientes'; }
        }

        // Last updated
        if (s.timestamp_utc) {
            const d = new Date(s.timestamp_utc);
            document.getElementById('last-updated').textContent =
                'último scan: ' + d.toISOString().slice(0,16).replace('T',' ') + ' UTC';
        }

        // Stats
        document.getElementById('stat-scanned').textContent = s.markets_scanned ?? '—';
        document.getElementById('stat-trades').textContent = (s.markets_with_trades ?? '—') + ' con trades';
        document.getElementById('stat-sustained').textContent = s.markets_sustained ?? '—';
        document.getElementById('stat-flagged').textContent = (s.markets_flagged ?? '—') + ' flagged ≥2pp';

        const ds = s.deviation_stats || {};
        document.getElementById('stat-maxdev').textContent = ds.max !== undefined ? fmtPct(ds.max) : '—';
        document.getElementById('stat-median').textContent = 'mediana ' + (ds.median !== undefined ? fmtPct(ds.median) : '—');

        // Trend (últimos N scans, sustained count)
        const trendRow = document.getElementById('trend-row');
        trendRow.innerHTML = '';
        const maxSust = Math.max(...history.map(h => h.markets_sustained || 0), 1);
        history.slice(-20).forEach(h => {
            const v = h.markets_sustained || 0;
            const bar = document.createElement('div');
            bar.className = 'trend-bar ' + (v >= 5 ? 'high' : v >= 1 ? 'med' : 'low');
            bar.style.height = ((v / maxSust) * 100) + '%';
            bar.title = (h.timestamp_utc || '?').slice(0,16) + ' · ' + v + ' sustained';
            trendRow.appendChild(bar);
        });

        // Criterio Día 8 status
        const sustainedMarkets = new Set();
        const marketCounts = {};
        history.forEach(h => {
            (h.sustained_markets || []).forEach(cid => {
                sustainedMarkets.add(cid);
                marketCounts[cid] = (marketCounts[cid] || 0) + 1;
            });
        });
        const passingNow = Object.values(marketCounts).filter(c => c >= 3).length;
        const criteriaEl = document.getElementById('stat-criteria');
        criteriaEl.textContent = passingNow + ' / 5';
        criteriaEl.className = 'stat-value num ' + (passingNow >= 5 ? 'red' : passingNow >= 1 ? 'orange' : '');

        // Table
        const tbody = document.getElementById('table-body');
        if (scan.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" class="empty">Sin anomalías en el último scan.</td></tr>';
        } else {
            tbody.innerHTML = '';
            scan.forEach(m => {
                const isSustained = m.sustained;
                const isUnderpriced = (m.dev_signed || 0) < 0;
                const tag = isSustained
                    ? '<span class="tag sustained">SUSTAINED</span>'
                    : '<span class="tag flagged">FLAGGED</span>';
                const dir = isUnderpriced
                    ? '<span class="tag underpriced" style="margin-left:4px;">UNDERPRICED</span>'
                    : '';
                const devClass = (m.dev_signed || 0) > 0 ? 'dev-pos' : 'dev-neg';
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td>${tag}${dir}</td>
                    <td>
                        <div class="name-cell" title="${(m.question || '').replace(/"/g,'&quot;')}">${m.question || '—'}</div>
                        <div class="cid-cell">${(m.market || '').slice(0,18)}…</div>
                    </td>
                    <td class="num">${fmt(m.vwap_yes)}</td>
                    <td class="num">${fmt(m.vwap_no)}</td>
                    <td class="num">${fmt(m.sum_vwap)}</td>
                    <td class="num ${devClass}">${fmtSigned(m.dev_signed)}</td>
                    <td class="num" style="color:var(--text-secondary);">${(m.num_trades_yes||0)+(m.num_trades_no||0)}</td>
                `;
                tbody.appendChild(tr);
            });
        }
    } catch (err) {
        console.error('fetch error', err);
        document.getElementById('status-dot').className = 'dot dead';
        document.getElementById('status-text').textContent = 'error de conexión';
    }
}

fetchData();
setInterval(fetchData, 15000); // 15s autorefresh
</script>
</body>
</html>
"""
    return HTMLResponse(content=html)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
