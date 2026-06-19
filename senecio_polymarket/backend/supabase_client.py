"""
SENECIO ORACLE — Supabase Client (ACT XIX)
===========================================

Lightweight async REST client for Supabase PostgREST.
Uses the publishable (anon) key — table is RLS-protected for INSERT+SELECT.

Only depends on httpx (already in requirements.txt).
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

import httpx

log = logging.getLogger("senecio.supabase")

# Configuration — can be overridden by env vars at runtime
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://okgxqapbldtldmvjvzfh.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "sb_publishable_ND41HJx4ef7JtjoDetI7RQ_P9JU-Y7Z")
SUPABASE_TABLE = os.environ.get("SUPABASE_TABLE", "oracle_predictions")

# Single reusable client (connection pooling)
_client: Optional[httpx.AsyncClient] = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            base_url=f"{SUPABASE_URL}/rest/v1",
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": "application/json",
                "Prefer": "return=representation",
            },
            timeout=httpx.Timeout(15.0, connect=5.0),
        )
    return _client


async def insert_prediction(prediction: dict) -> Optional[dict]:
    """Insert a single prediction into Supabase.

    Maps the prediction dict to the table schema:
      timestamp        -> ts
      symbol           -> symbol
      prediction       -> prediction
      confidence       -> confidence
      ev               -> ev
      price_now        -> price_now
      price_15m_later  -> price_15m_later
      outcome          -> outcome
      exchange_used    -> exchange_used
      _audit           -> audit (jsonb)

    Returns the inserted row (with id) on success, None on failure.
    """
    row = {
        "ts": prediction.get("timestamp"),
        "symbol": prediction.get("symbol"),
        "prediction": prediction.get("prediction"),
        "confidence": float(prediction.get("confidence", 0)),
        "ev": float(prediction.get("ev", 0)),
        "price_now": float(prediction.get("price_now", 0)),
        "price_15m_later": prediction.get("price_15m_later"),
        "outcome": prediction.get("outcome"),
        "exchange_used": prediction.get("exchange_used", "unknown"),
        "audit": prediction.get("_audit"),
    }
    try:
        c = _get_client()
        r = await c.post(f"/{SUPABASE_TABLE}", json=row)
        if r.status_code in (200, 201):
            data = r.json()
            if isinstance(data, list) and data:
                log.info("supabase insert OK id=%s", data[0].get("id"))
                return data[0]
            return data
        log.error("supabase insert failed: %s %s", r.status_code, r.text[:300])
        return None
    except Exception as e:
        log.error("supabase insert error: %s", e)
        return None


async def fetch_predictions(limit: int = 50, symbol: Optional[str] = None) -> list[dict]:
    """Fetch recent predictions (most recent first)."""
    try:
        c = _get_client()
        params = {"limit": str(limit), "order": "ts.desc"}
        if symbol:
            params["symbol"] = f"eq.{symbol}"
        r = await c.get(f"/{SUPABASE_TABLE}", params=params)
        if r.status_code == 200:
            return r.json()
        log.error("supabase fetch failed: %s %s", r.status_code, r.text[:200])
        return []
    except Exception as e:
        log.error("supabase fetch error: %s", e)
        return []


async def count_predictions() -> int:
    """Get total prediction count by fetching all IDs (works around content-range header issues)."""
    try:
        c = _get_client()
        # Fetch just the id column, limit to 10k (we won't exceed this for a long time)
        r = await c.get(
            f"/{SUPABASE_TABLE}",
            params={"select": "id", "limit": "10000"},
        )
        if r.status_code == 200:
            data = r.json()
            return len(data) if isinstance(data, list) else 0
        # Fallback: try content-range header
        range_header = r.headers.get("content-range", "")
        if "/" in range_header:
            total = range_header.split("/")[-1]
            return int(total) if total.isdigit() else 0
        return 0
    except Exception as e:
        log.debug("supabase count error: %s", e)
        return 0


async def fetch_pending_outcomes(older_than_seconds: int = 900, limit: int = 100) -> list[dict]:
    """Fetch predictions that have outcome=NULL and are older than `older_than_seconds`.

    Used by the verifier to find predictions whose 15min window has elapsed
    and need to be settled (WIN/LOSS).

    Returns rows with at least: id, ts, symbol, prediction, price_now.
    """
    try:
        from datetime import datetime, timezone, timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=older_than_seconds)).isoformat()
        c = _get_client()
        # PostgREST filter: outcome=is.null AND ts=lt.{cutoff}
        params = {
            "select": "id,ts,symbol,prediction,confidence,price_now,exchange_used",
            "outcome": "is.null",
            "ts": f"lt.{cutoff}",
            "order": "ts.asc",
            "limit": str(limit),
        }
        r = await c.get(f"/{SUPABASE_TABLE}", params=params)
        if r.status_code == 200:
            return r.json() or []
        log.error("supabase fetch_pending_outcomes failed: %s %s", r.status_code, r.text[:200])
        return []
    except Exception as e:
        log.error("supabase fetch_pending_outcomes error: %s", e)
        return []


async def update_outcome(prediction_id: int, outcome: str, price_15m_later: float) -> bool:
    """Update a prediction row with the settled outcome.

    Args:
        prediction_id: Supabase row id
        outcome: "WIN" or "LOSS"
        price_15m_later: actual price 15min after prediction

    Returns True on success.
    """
    try:
        c = _get_client()
        # PostgREST PATCH with row filter: PATCH /table?id=eq.{id}
        r = await c.patch(
            f"/{SUPABASE_TABLE}",
            params={"id": f"eq.{prediction_id}"},
            json={
                "outcome": outcome,
                "price_15m_later": float(price_15m_later),
            },
        )
        if r.status_code in (200, 204):
            log.info("supabase update_outcome OK id=%s outcome=%s", prediction_id, outcome)
            return True
        log.error("supabase update_outcome failed: %s %s", r.status_code, r.text[:300])
        return False
    except Exception as e:
        log.error("supabase update_outcome error: %s", e)
        return False


async def close() -> None:
    global _client
    if _client and not _client.is_closed:
        await _client.aclose()
        _client = None
