"""SENECIO H-011b dashboard: observabilidad honesta para el dry-run.

El proceso sigue siendo de solo lectura.  El ledger contiene estimaciones
derivadas de VWAP histórico: no contiene fills del CLOB, ni operaciones reales,
ni resultados de mercados resueltos.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn


app = FastAPI(title="SENECIO H-011b Dashboard", docs_url=None, redoc_url=None)

RESULTS_DIR = Path(os.environ.get("H011_RESULTS_DIR", "/app/polymarket/results"))
TEMPLATE_FILE = Path(__file__).with_name("templates") / "dashboard.html"
VIRTUAL_BALANCE_INITIAL = 1000.0
FRESH_SCAN_MAX_AGE_SEC = int(os.environ.get("H011_FRESH_SCAN_MAX_AGE_SEC", "1200"))


@dataclass(frozen=True)
class JsonlRead:
    """Resultado de una lectura JSONL sin ocultar daños de persistencia."""

    rows: list[dict[str, Any]]
    skipped_lines: int = 0
    error: str | None = None


def read_jsonl(path: Path) -> JsonlRead:
    """Lee JSONL y contabiliza líneas inválidas en lugar de ignorarlas en silencio."""
    if not path.exists():
        return JsonlRead([])

    rows: list[dict[str, Any]] = []
    skipped = 0
    try:
        with path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    skipped += 1
                    continue
                if isinstance(value, dict):
                    rows.append(value)
                else:
                    skipped += 1
    except (OSError, UnicodeDecodeError) as exc:
        return JsonlRead(rows, skipped, f"{type(exc).__name__}: {exc}")
    return JsonlRead(rows, skipped)


def as_number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def latest_scan_file() -> Path | None:
    files = sorted(RESULTS_DIR.glob("scan_*.jsonl"))
    return files[-1] if files else None


def dry_run_stats(ledger: JsonlRead) -> dict[str, Any]:
    """Resume el ledger sin presentarlo como rendimiento realizado."""
    theoretical_pnl = sum(as_number(row.get("pnl")) for row in ledger.rows)
    positive_records = sum(as_number(row.get("pnl")) > 0 for row in ledger.rows)
    total_records = len(ledger.rows)
    return {
        "virtual_balance_theoretical": round(VIRTUAL_BALANCE_INITIAL + theoretical_pnl, 2),
        "theoretical_pnl": round(theoretical_pnl, 2),
        "total_records": total_records,
        "positive_expected_records": positive_records,
        "trades": ledger.rows[-10:],
        "execution_model": "historical_vwap_estimate",
        "is_realized": False,
        # Compatibilidad temporal con clientes que todavía leen estas claves.
        "virtual_balance": round(VIRTUAL_BALANCE_INITIAL + theoretical_pnl, 2),
        "profit_loss": round(theoretical_pnl, 2),
        "total_trades": total_records,
        "win_rate": None,
    }


def build_payload() -> dict[str, Any]:
    master = read_jsonl(RESULTS_DIR / "_master_log.jsonl")
    scan_path = latest_scan_file()
    scan = read_jsonl(scan_path) if scan_path else JsonlRead([])
    ledger = read_jsonl(RESULTS_DIR / "dry_run_ledger.jsonl")

    summary = master.rows[-1] if master.rows else {"error": "no master log yet"}
    flagged_scan = [
        row for row in scan.rows if row.get("flagged") or row.get("sustained")
    ]
    flagged_scan.sort(
        key=lambda row: as_number(row.get("dev_abs"), -1.0), reverse=True
    )

    timestamp = parse_timestamp(summary.get("timestamp_utc"))
    age_sec = (
        max(0, round((datetime.now(timezone.utc) - timestamp).total_seconds()))
        if timestamp
        else None
    )
    has_summary = not summary.get("error")
    freshness = {
        "source_timestamp_utc": summary.get("timestamp_utc"),
        "age_sec": age_sec,
        "is_fresh": bool(has_summary and age_sec is not None and age_sec <= FRESH_SCAN_MAX_AGE_SEC),
        "fresh_limit_sec": FRESH_SCAN_MAX_AGE_SEC,
        "label": (
            "scan fresco"
            if has_summary and age_sec is not None and age_sec <= FRESH_SCAN_MAX_AGE_SEC
            else "datos vencidos" if has_summary else "sin datos"
        ),
    }

    markets_scanned = int(as_number(summary.get("markets_scanned")))
    markets_with_trades = int(as_number(summary.get("markets_with_trades")))
    coverage = round((markets_with_trades / markets_scanned) * 100, 1) if markets_scanned else None
    under_candidates = sum(as_number(row.get("dev_signed")) < 0 for row in flagged_scan)
    readers = {
        "master_log": master,
        "latest_scan": scan,
        "dry_run_ledger": ledger,
    }

    return {
        "summary": summary,
        "scan": flagged_scan[:15],
        "history": master.rows[-20:],
        "dry_run": dry_run_stats(ledger),
        "freshness": freshness,
        "execution": {
            "mode": "dry-run",
            "orders_sent": False,
            "fills_verified": False,
            "clob_depth_modeled": False,
            "resolution_pnl_available": False,
        },
        "signal_quality": {
            "markets_scanned": markets_scanned,
            "markets_with_trades": markets_with_trades,
            "coverage_pct": coverage,
            "under_candidates": under_candidates,
        },
        "data_quality": {
            "corrupt_lines": sum(reader.skipped_lines for reader in readers.values()),
            "skipped_lines_by_source": {
                name: reader.skipped_lines for name, reader in readers.items()
            },
            "read_errors": {
                name: reader.error for name, reader in readers.items() if reader.error
            },
            "latest_scan_file": scan_path.name if scan_path else None,
        },
    }


@app.get("/api/data")
def api_data() -> JSONResponse:
    return JSONResponse(build_payload(), headers={"Cache-Control": "no-store"})


@app.get("/healthz")
def healthz() -> JSONResponse:
    payload = build_payload()
    return JSONResponse(
        {
            "ok": not payload["summary"].get("error"),
            "freshness": payload["freshness"],
            "corrupt_lines": payload["data_quality"]["corrupt_lines"],
        },
        headers={"Cache-Control": "no-store"},
    )


@app.get("/", response_class=HTMLResponse)
def dashboard() -> HTMLResponse:
    try:
        html = TEMPLATE_FILE.read_text(encoding="utf-8")
    except OSError as exc:
        return HTMLResponse(
            "<h1>SENECIO dashboard unavailable</h1>"
            f"<p>Template error: {type(exc).__name__}</p>",
            status_code=500,
        )
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
