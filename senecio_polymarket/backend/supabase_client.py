"""
SENECIO ORACLE — Supabase Client (ACT XXIII)
=============================================

Lightweight async REST client for Supabase PostgREST.
Uses the publishable (anon) key — table is RLS-protected for INSERT+SELECT.

ACT XXIII changes:
  - Dual-window outcome support: stores outcome_15m + outcome_1h side-by-side
    in the audit JSONB (avoids schema migration on RLS-restricted anon key).
  - The primary `outcome` column now mirrors `outcome_1h` (the gating window).
  - `price_15m_later` column keeps its original meaning (price at ts+15min).
  - `update_outcome_dual()` fetches existing audit, merges `outcomes_dual` sub-dict,
    then PATCHes (avoids clobbering existing audit signal metadata).
  - `fetch_pending_outcomes_dual()` fetches predictions older than 1h (the gating
    window) so the verifier can settle both 15m and 1h outcomes atomically.
  - Backward-compat: `update_outcome()` kept for callers that only have 1h data.

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

    Used by the verifier to find predictions whose settlement window has elapsed
    and need to be settled (WIN/LOSS).

    ACT XXIII: default `older_than_seconds` was raised from 900 (15min) to 3600
    (1h) at the call-site, since the primary gating window is now 1h. The 15min
    outcome is still computed for research but is no longer the live gate.

    Returns rows with at least: id, ts, symbol, prediction, price_now.
    """
    try:
        from datetime import datetime, timezone, timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=older_than_seconds)).isoformat()
        c = _get_client()
        # PostgREST filter: outcome=is.null AND ts=lt.{cutoff}
        params = {
            "select": "id,ts,symbol,prediction,confidence,price_now,exchange_used,audit",
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
    """Update a prediction row with the settled outcome (single-window legacy path).

    Args:
        prediction_id: Supabase row id
        outcome: "WIN" or "LOSS"
        price_15m_later: actual price 15min after prediction

    Returns True on success.

    RLS safety: PostgREST returns HTTP 200 with an empty array [] when an
    UPDATE is blocked by RLS or the row id doesn't exist. Status code alone
    is NOT a reliable success signal — we must check len(response body) > 0.

    ACT XXIII: prefer update_outcome_dual() for new code — it stores both
    15m and 1h outcomes in the audit JSONB. This legacy function is kept for
    backward compat with the bogus_backfill path that only has 15m data.
    """
    try:
        c = _get_client()
        # PostgREST PATCH with row filter: PATCH /table?id=eq.{id}
        # Prefer: return=representation (already in default headers) so the
        # response body contains the updated row(s).
        r = await c.patch(
            f"/{SUPABASE_TABLE}",
            params={"id": f"eq.{prediction_id}"},
            json={
                "outcome": outcome,
                "price_15m_later": float(price_15m_later),
            },
        )
        if r.status_code in (200, 204):
            # ACT XXI patch: validate that a row was actually updated.
            # PostgREST returns [] when 0 rows match (RLS-blocked or id missing)
            # — silently treating that as success caused a false positive
            # on the first verifier run before RLS UPDATE was enabled.
            try:
                body = r.json() if r.content else []
            except Exception:
                body = []
            if isinstance(body, list) and len(body) > 0:
                log.info("supabase update_outcome OK id=%s outcome=%s", prediction_id, outcome)
                return True
            log.error(
                "supabase update_outcome NO-OP id=%s outcome=%s status=%s body=%r "
                "— RLS likely blocked UPDATE (check UPDATE policy on table)",
                prediction_id, outcome, r.status_code, body,
            )
            return False
        log.error("supabase update_outcome failed: %s %s", r.status_code, r.text[:300])
        return False
    except Exception as e:
        log.error("supabase update_outcome error: %s", e)
        return False


async def update_outcome_dual(
    prediction_id: int,
    outcome_15m: str,
    outcome_1h: str,
    price_15m_later: float,
    price_1h_later: float,
    primary_window: str = "1h",
) -> bool:
    """Settle a prediction with BOTH 15m and 1h outcomes (ACT XXIII dual-window path).

    Storage strategy (avoids schema migration on RLS-restricted anon key):
      - Primary `outcome` column  ← outcome_1h (the gating source of truth)
      - Primary `price_15m_later` ← price at ts+15min (preserves original column meaning)
      - `audit` JSONB             ← merge `outcomes_dual` sub-dict containing:
            {outcome_15m, outcome_1h, price_15m_later, price_1h_later, primary_window}

    Implementation: fetch existing audit dict (so we don't clobber signal metadata
    like pressures/regime_hint), merge the new outcomes_dual sub-dict, then PATCH.
    Two round-trips per row, but the verifier runs at most 100 rows per cycle.

    RLS safety: same as update_outcome() — require len(response body) > 0.
    """
    try:
        c = _get_client()

        # 1) Fetch the existing audit dict (and verify row exists)
        r_get = await c.get(
            f"/{SUPABASE_TABLE}",
            params={"select": "id,audit", "id": f"eq.{prediction_id}", "limit": "1"},
        )
        if r_get.status_code != 200:
            log.error(
                "update_outcome_dual: GET audit failed id=%s status=%s body=%s",
                prediction_id, r_get.status_code, r_get.text[:200],
            )
            return False
        existing_rows = r_get.json() or []
        if not existing_rows:
            log.error(
                "update_outcome_dual: row not found id=%s (RLS or bad id)",
                prediction_id,
            )
            return False
        existing_audit = existing_rows[0].get("audit") or {}
        if not isinstance(existing_audit, dict):
            # Audit might be a JSON string in some edge cases — try parsing
            try:
                if isinstance(existing_audit, str):
                    existing_audit = json.loads(existing_audit)
                else:
                    existing_audit = {}
            except Exception:
                existing_audit = {}

        # 2) Merge new outcomes_dual sub-dict (preserves any pre-existing fields)
        outcomes_dual = {
            "outcome_15m": outcome_15m,
            "outcome_1h": outcome_1h,
            "price_15m_later": float(price_15m_later) if price_15m_later is not None else None,
            "price_1h_later": float(price_1h_later) if price_1h_later is not None else None,
            "primary_window": primary_window,
        }
        existing_audit["outcomes_dual"] = outcomes_dual

        # 3) PATCH with primary outcome (1h = gating) + dual audit
        patch_body = {
            "outcome": outcome_1h,                  # primary = 1h
            "price_15m_later": float(price_15m_later) if price_15m_later is not None else None,
            "audit": existing_audit,
        }
        r = await c.patch(
            f"/{SUPABASE_TABLE}",
            params={"id": f"eq.{prediction_id}"},
            json=patch_body,
        )
        if r.status_code in (200, 204):
            try:
                body = r.json() if r.content else []
            except Exception:
                body = []
            if isinstance(body, list) and len(body) > 0:
                log.info(
                    "supabase update_outcome_dual OK id=%s 15m=%s 1h=%s primary=%s",
                    prediction_id, outcome_15m, outcome_1h, primary_window,
                )
                return True
            log.error(
                "supabase update_outcome_dual NO-OP id=%s status=%s body=%r "
                "— RLS likely blocked UPDATE (check UPDATE policy on table)",
                prediction_id, r.status_code, body,
            )
            return False
        log.error(
            "supabase update_outcome_dual failed: %s %s",
            r.status_code, r.text[:300],
        )
        return False
    except Exception as e:
        log.error("supabase update_outcome_dual error: %s", e)
        return False


async def close() -> None:
    global _client
    if _client and not _client.is_closed:
        await _client.aclose()
        _client = None
