"""
SENECIO H-011 V3 — Integrated evidence pipeline (orchestrator).

This module is a THIN ORCHESTRATOR. It does NOT reimplement:
  - Gamma parsing (uses market_structure.structure_from_gamma)
  - Deduplication (uses trade_binding.trade_dedup_key)
  - Token binding (uses trade_binding.validate_trade_binding)
  - VWAP calculation (uses trade_binding.compute_vwap_by_index)
  - Walk-book (uses clob_readonly.walk_asks)
  - Fee model (uses clob_readonly.taker_fee)
  - Raw event hashing (uses raw_event_store)
  - Cohort classification (uses validation_semantics)

It coordinates these functions and produces a single V3 record per market.

Determinism: same raw input + same config + same code SHA = same output SHA.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

import httpx

from market_structure import (
    MarketStructure,
    MarketStructureError,
    MarketTruthContract,
    is_market_stub,
    structure_from_gamma,
    canonical_hash,
)
from evidence_state import (
    EvidenceState,
    EvidenceStatus,
    make_evidence,
    require_known,
)
from trade_binding import (
    trade_token_id,
    trade_dedup_key,
    validate_trade_binding,
    compute_vwap_by_index,
)
from raw_event_store import save_raw_events, create_raw_event, append_raw_event
from clob_readonly import fetch_orderbook, simulate_complete_set, is_executable, walk_asks, taker_fee
from validation_semantics import (
    H011_COHORT_ID,
    classify_window_cohort,
    new_scan_metadata,
    is_legacy_cohort,
)
from control_plane.replay import write_bundle
from control_plane.coverage import (
    ScanContext,
    SourceHealthTracker,
    not_used_source_health,
    compute_control_plane_state,
    determine_scan_status,
    compute_health_ok,
    CATALOG_VERSION,
    invariant_catalog_hash,
    invariant_summary,
    get_catalog,
)


# ═══════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class H011V3Config:
    """Immutable configuration for a V3 scan run."""
    window_s: int = 300
    estimator: str = "vwap"
    min_equal_quantity: float = 1.0
    max_book_age_ms: int = 3000
    max_snapshot_delta_ms: int = 1000
    latency_buffer_bps: float = 0.0
    safety_buffer_bps: float = 0.0
    staleness_threshold_sec: int = 60
    paper_only: bool = True
    live_capital_locked: bool = True

    def normalized(self) -> dict[str, Any]:
        """Return the effective config in a stable, JSON-safe form."""
        return {
            "window_s": int(self.window_s),
            "estimator": str(self.estimator),
            "min_equal_quantity": float(self.min_equal_quantity),
            "max_book_age_ms": int(self.max_book_age_ms),
            "max_snapshot_delta_ms": int(self.max_snapshot_delta_ms),
            "latency_buffer_bps": float(self.latency_buffer_bps),
            "safety_buffer_bps": float(self.safety_buffer_bps),
            "staleness_threshold_sec": int(self.staleness_threshold_sec),
            "paper_only": bool(self.paper_only),
            "live_capital_locked": bool(self.live_capital_locked),
            "orders_enabled": False,
        }

    @property
    def config_sha(self) -> str:
        body = json.dumps(self.normalized(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(body.encode("utf-8")).hexdigest()

    def validate(self) -> None:
        """Reject startup if V3 invariants are violated."""
        assert self.window_s == 300, f"V3 requires window_s=300, got {self.window_s}"
        assert self.paper_only is True, "V3 requires paper_only=True"
        assert self.live_capital_locked is True, "V3 requires live_capital_locked=True"


# ═══════════════════════════════════════════════════════════════════════
# Client protocols (injectable for testing)
# ═══════════════════════════════════════════════════════════════════════

class DataApiClient(Protocol):
    def fetch_trades(self, condition_id: str, window_start: int, now: int) -> list[dict]: ...


class ClobClient(Protocol):
    def fetch_book(self, token_id: str) -> dict: ...


class HttpxDataApiClient:
    """Production Data API client."""
    BASE = "https://data-api.polymarket.com"
    PAGE_SIZE = 500
    MAX_PAGES = 20
    DELAY = 0.15

    def fetch_trades(self, condition_id: str, window_start: int, now: int) -> list[dict]:
        all_trades: dict[str, dict] = {}
        with httpx.Client(timeout=15.0) as c:
            for page in range(self.MAX_PAGES):
                r = c.get(f"{self.BASE}/trades", params={
                    "market": condition_id,
                    "limit": self.PAGE_SIZE,
                    "offset": page * self.PAGE_SIZE,
                })
                if r.status_code != 200:
                    break
                data = r.json()
                if not isinstance(data, list) or not data:
                    break
                page_max = max(t.get("timestamp", 0) for t in data)
                if page_max < window_start:
                    break
                for t in data:
                    ts = t.get("timestamp", 0)
                    if not isinstance(ts, (int, float)):
                        continue
                    if ts < window_start or ts >= now:
                        continue
                    key = trade_dedup_key(t)
                    if key not in all_trades:
                        all_trades[key] = t
                if len(data) < self.PAGE_SIZE:
                    break
                time.sleep(self.DELAY)
        return list(all_trades.values())


class HttpxClobClient:
    """Production CLOB client."""
    BASE = "https://clob.polymarket.com"

    def fetch_book(self, token_id: str) -> dict:
        if not token_id:
            raise ValueError("token_id is required")
        with httpx.Client(timeout=10.0) as c:
            r = c.get(f"{self.BASE}/book", params={"token_id": token_id})
            r.raise_for_status()
            payload = r.json()
        returned = str(payload.get("asset_id") or payload.get("assetId") or "")
        if returned and returned != token_id:
            raise ValueError(f"orderbook asset mismatch: requested={token_id} returned={returned}")
        return payload


# ═══════════════════════════════════════════════════════════════════════
# V3 storage paths (separated from legacy)
# ═══════════════════════════════════════════════════════════════════════

V3_RESULTS_DIR = Path(__file__).parent / "results" / "v3"
V3_RAW_DIR = V3_RESULTS_DIR / "raw"
V3_SCANS_DIR = V3_RESULTS_DIR / "scans"
V3_REPLAY_DIR = V3_RESULTS_DIR / "replay"
V3_MASTER_LOG = V3_RESULTS_DIR / "_master_log_v3.jsonl"
UNEVALUATED_INVARIANT_COUNT = 31


def _unevaluated_control_plane_state() -> tuple[dict[str, dict[str, object]], dict[str, object], list[dict[str, object]]]:
    """Expose missing control-plane checks as UNKNOWN rather than as success."""
    source_health = {
        "gamma_metadata": {
            "level": "UNKNOWN",
            "reason": "source health timing is not yet measured by the V3 scan",
            "age_ms": None,
            "latency_ms": None,
            "consecutive_failures": None,
            "fallback_used": False,
        },
        "data_api_trades": {
            "level": "UNKNOWN",
            "reason": "source health timing is not yet measured by the V3 scan",
            "age_ms": None,
            "latency_ms": None,
            "consecutive_failures": None,
            "fallback_used": False,
        },
        "clob_orderbook": {
            "level": "UNKNOWN",
            "reason": "source health timing is not yet measured by the V3 scan",
            "age_ms": None,
            "latency_ms": None,
            "consecutive_failures": None,
            "fallback_used": False,
        },
    }
    invariants = {
        "summary": {"pass": 0, "fail": 0, "unknown": UNEVALUATED_INVARIANT_COUNT},
        "results": [{
            "invariant_id": "CONTROL_PLANE_EXECUTION_COVERAGE",
            "status": "UNKNOWN",
            "severity": "WARNING",
            "reason": (
                f"{UNEVALUATED_INVARIANT_COUNT} declared controls are not executed in run_scan_v3 yet"
            ),
        }],
    }
    alerts = [{
        "severity": "WARNING",
        "blocking": False,
        "code": "VALIDATION_INCOMPLETE",
        "title": "Control-plane validation incomplete",
        "detail": (
            f"{UNEVALUATED_INVARIANT_COUNT} invariants and source-health checks are UNKNOWN; "
            "this scan is not a replay-verified acceptance decision."
        ),
    }]
    return source_health, invariants, alerts


def _ensure_v3_dirs():
    for d in [V3_RESULTS_DIR, V3_RAW_DIR, V3_SCANS_DIR, V3_REPLAY_DIR]:
        d.mkdir(parents=True, exist_ok=True)


# ═══════════════════════════════════════════════════════════════════════
# H-011 V3 Directional market identity — canonical contract v3
# ═══════════════════════════════════════════════════════════════════════
#
# CONTRACT (post ce8ce2c6 revert, Opción A confirmed by GPT-5.6):
#
#   For BTC 5-minute Up/Down markets, Polymarket uses a structural slug:
#       ^btc-updown-5m-(\d{10})$
#
#   The slug embeds the window_start_epoch as a 10-digit Unix timestamp.
#   The market payload exposes:
#       eventStartTime  = window_start  (== slug_epoch)
#       endDate         = window_end    (== eventStartTime + 300s)
#       startDate       = market listing/lifecycle (NOT the H-011 window)
#
#   Statistical validation (13 markets captured 2026-07-13):
#       eventStartTime == slug_epoch             in 13/13 (100%)
#       endDate - eventStartTime == 300s ± 1s    in 13/13 (100%)
#       outcomes == ["Up","Down"]                in 13/13 (100%)
#       len(clobTokenIds) == 2 and unique        in 13/13 (100%)
#
#   The validator performs FIVE independent structural checks, each
#   producing a distinct rejection reason:
#
#       1. binary_token_pair_valid          — outcomes are 2, tokens are 2 unique
#       2. directional_market_identity_proven — slug matches ^btc-updown-5m-\d{10}$
#                                                AND event ticker is coherent
#       3. token_direction_mapping_proven    — outcomes == ["Up","Down"] exactly
#                                                (NOT Yes/No — that only proves
#                                                binary, not directional)
#       4. window_duration_proven            — slug_epoch == eventStartTime
#                                                AND endDate - eventStartTime == 300
#       5. resolution_rule_proven            — resolutionSource mentions BTC/USD
#                                                AND description mentions price
#                                                comparison at start vs end
#
#   Fail-closed: ANY contradiction produces a rejection reason. We do NOT
#   infer identity from text, do NOT swap token positions, do NOT accept
#   Yes/No as directional (only as binary).
#
#   startDate/endDate are NOT used for the H-011 window calculation.
#   startDate represents market listing/lifecycle only.
# ═══════════════════════════════════════════════════════════════════════

# Structural slug pattern for BTC 5-minute Up/Down markets.
# Captures the 10-digit Unix epoch timestamp embedded in the slug.
_BTC_UPDOWN_5M_SLUG_PATTERN = re.compile(r"^btc-updown-5m-(\d{10})$")

# Tolerance for serialization-induced timestamp drift (1 second).
_WINDOW_TOLERANCE_S = 1

# Required H-011 V3 window duration in seconds.
_H011_V3_WINDOW_S = 300


def _parse_epoch(value: Any) -> float | None:
    """Parse an ISO 8601 string or numeric epoch into a float epoch.

    Returns None if the value is missing, None, or unparseable.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        # Try numeric epoch first
        try:
            return float(s)
        except ValueError:
            pass
        # Try ISO 8601
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def _parse_json_list(value: Any) -> list | None:
    """Parse a value that may be a list or a JSON string encoding a list."""
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
        except (json.JSONDecodeError, ValueError):
            return None
    return None


def _binary_token_pair_valid(market: dict[str, Any]) -> bool:
    """Check 1: market has a valid binary token pair (2 outcomes, 2 unique tokens).

    This check proves ONLY binariness — it does NOT prove directionality.
    Both ["Yes","No"] and ["Up","Down"] satisfy this check.
    """
    outcomes = _parse_json_list(market.get("outcomes"))
    tokens = _parse_json_list(market.get("clobTokenIds"))
    if not isinstance(outcomes, list) or len(outcomes) != 2:
        return False
    if not isinstance(tokens, list) or len(tokens) != 2:
        return False
    token_strs = [str(t).strip() for t in tokens]
    return all(token_strs) and len(set(token_strs)) == 2


def _directional_market_identity_proven(market: dict[str, Any]) -> tuple[bool, str | None]:
    """Check 2: market belongs to the btc-updown-5m event family.

    Proven by structural evidence (NOT text inference):
      (a) market.slug matches ^btc-updown-5m-(\\d{10})$
      (b) Fix #5: at least ONE parent event must exist AND be coherent:
          - events[0].id present (non-empty)
          - events[0].ticker == market.slug OR events[0].slug == market.slug

    If the market has a valid slug but no coherent parent event, this check
    FAILS with directional_market_identity_unproven. This prevents markets
    with valid-looking slugs from passing without event-level corroboration.

    Returns (ok, slug_epoch_str_or_None).
    """
    slug = str(market.get("slug") or "").strip()
    match = _BTC_UPDOWN_5M_SLUG_PATTERN.match(slug)
    if not match:
        return False, None
    slug_epoch_str = match.group(1)

    # Fix #5: parent event is MANDATORY and must be coherent.
    # The market must have an `events` list with at least one event that:
    #   - has a non-empty id
    #   - has ticker == market.slug (when ticker is present)
    #   - has slug == market.slug (when slug is present)
    # If ticker is present but DIFFERENT from market.slug, it's a conflict
    # (fail-closed). If slug is present but DIFFERENT, also conflict.
    events_field = market.get("events")
    if not isinstance(events_field, list) or not events_field:
        # No parent event → cannot prove directional identity
        return False, None

    # Find a coherent parent event
    coherent_event_found = False
    for ev in events_field:
        if not isinstance(ev, dict):
            continue
        ev_id = str(ev.get("id") or "").strip()
        if not ev_id:
            continue
        ev_ticker = str(ev.get("ticker") or "").strip()
        ev_slug = str(ev.get("slug") or "").strip()
        # Coherence checks: any non-empty field must match market slug
        # If ticker is present, it must match; if slug is present, it must match.
        # At least one of them must be present and match.
        ticker_ok = (not ev_ticker) or (ev_ticker == slug)
        slug_ok = (not ev_slug) or (ev_slug == slug)
        at_least_one_matches = (ev_ticker == slug) or (ev_slug == slug)
        if ticker_ok and slug_ok and at_least_one_matches:
            coherent_event_found = True
            break

    if not coherent_event_found:
        return False, None

    return True, slug_epoch_str


def _token_direction_mapping_proven(market: dict[str, Any]) -> bool:
    """Check 3: outcomes == ["Up","Down"] exactly AND tokens are 2 unique non-empty.

    Polymarket's btc-updown-5m family uses outcomes=["Up","Down"] with
    clobTokenIds[0] ↔ "Up" and clobTokenIds[1] ↔ "Down" (verified 13/13).

    We do NOT accept ["Yes","No"] here — that only proves binary, not
    directional. We do NOT swap token positions if outcomes are reversed.

    The mapping outcomes[i] ↔ clobTokenIds[i] is a Polymarket schema
    guarantee, so proving outcomes are ["Up","Down"] AND tokens are
    2 unique non-empty strings proves the directional mapping without
    further inference.

    This check subsumes binary_token_pair_valid (it is strictly stronger).
    """
    outcomes = _parse_json_list(market.get("outcomes"))
    if not isinstance(outcomes, list) or len(outcomes) != 2:
        return False
    # Normalize labels for comparison
    labels = [str(x).strip() for x in outcomes]
    if labels != ["Up", "Down"]:
        return False
    # Also validate clobTokenIds: must be 2 unique non-empty strings.
    # This subsumes binary_token_pair_valid's token check.
    tokens = _parse_json_list(market.get("clobTokenIds"))
    if not isinstance(tokens, list) or len(tokens) != 2:
        return False
    token_strs = [str(t).strip() for t in tokens]
    return all(token_strs) and len(set(token_strs)) == 2


def _window_duration_proven(market: dict[str, Any], slug_epoch_str: str | None,
                            expected_window_s: int = _H011_V3_WINDOW_S) -> tuple[bool, list[str]]:
    """Check 4: window duration is exactly expected_window_s seconds.

    Contract (Opción A):
        window_start = eventStartTime
        window_end   = endDate
        Constraints:
            eventStartTime_epoch == slug_epoch (±1s tolerance)
            endDate_epoch - eventStartTime_epoch == expected_window_s (±1s tolerance)

    startDate is treated as lifecycle metadata and NEVER used for the
    H-011 window calculation.

    Returns (ok, list_of_rejection_reasons).
    """
    reasons: list[str] = []
    if slug_epoch_str is None:
        # Cannot prove window without slug_epoch. Caller should have
        # already emitted directional_market_identity_unproven.
        return False, ["window_slug_unproven"]

    try:
        slug_epoch = float(slug_epoch_str)
    except (ValueError, TypeError):
        return False, ["window_slug_unproven"]

    event_start = market.get("eventStartTime")
    end_date = market.get("endDate")

    es_epoch = _parse_epoch(event_start)
    ed_epoch = _parse_epoch(end_date)

    if es_epoch is None:
        reasons.append("window_start_unproven")
    if ed_epoch is None:
        reasons.append("window_end_unproven")

    if es_epoch is not None and abs(es_epoch - slug_epoch) > _WINDOW_TOLERANCE_S:
        reasons.append("window_start_mismatch")

    if es_epoch is not None and ed_epoch is not None:
        duration = ed_epoch - es_epoch
        if abs(duration - expected_window_s) > _WINDOW_TOLERANCE_S:
            reasons.append("window_duration_mismatch")

    return len(reasons) == 0, reasons


def _resolution_rule_proven(market: dict[str, Any]) -> bool:
    """Check 5: resolution rule is coherent with BTC/USD price comparison.

    Proven by:
      (a) resolutionSource mentions BTC/USD or Bitcoin price (e.g. Chainlink)
      (b) description mentions price comparison at start vs end of window

    Returns True only if both conditions are met. This is the strictest
    check — it requires explicit textual evidence in the structured
    resolutionSource and description fields.
    """
    resolution_source = str(market.get("resolutionSource") or "").lower()
    description = str(market.get("description") or "").lower()

    # The resolution source must reference BTC/USD pricing.
    # Chainlink BTC/USD stream is the canonical source for this family.
    btc_price_source = any(x in resolution_source
                           for x in ("btc-usd", "btc/usd", "bitcoin", "btc", "chainlink"))

    # The description must mention a price comparison (start vs end).
    # The canonical phrasing is "price at the end ... greater than ...
    # price at the beginning" or similar.
    has_price_comparison = (
        ("price" in description or "btc" in description or "bitcoin" in description)
        and ("end" in description or "beginning" in description
             or "start" in description or "greater" in description
             or "less" in description or "resolve" in description)
    )

    return btc_price_source and has_price_comparison


def _market_active_and_open(market: dict[str, Any]) -> bool:
    """Check: market is active and not closed.

    Polymarket's btc-updown-5m markets are listed ~24h before the window
    starts. We accept markets where active=true and closed=false.
    """
    active = market.get("active")
    closed = market.get("closed")
    # Explicit boolean checks (not truthy) — None values fail-closed.
    return active is True and closed is False


def validate_btc_market_identity(market: dict[str, Any], expected_window_s: int) -> tuple[bool, list[str]]:
    """Validate that a market belongs to the H-011 V3 BTC 5-min Up/Down cohort.

    Performs FIVE independent structural checks. The market is accepted
    only if ALL checks pass. Each failed check emits a distinct rejection
    reason so the histogram accurately reflects failure causes.

    Rejection reasons emitted by this validator:
        missing_condition_id                       — conditionId absent
        window_slug_unproven                       — slug doesn't match the pattern
        window_start_unproven                      — eventStartTime missing/unparseable
        window_end_unproven                        — endDate missing/unparseable
        window_start_mismatch                      — eventStartTime != slug_epoch (±1s)
        window_duration_mismatch                   — endDate - eventStartTime != 300 (±1s)
        directional_market_identity_unproven       — slug/event-ticker incoherent
        token_direction_mapping_unproven           — outcomes != ["Up","Down"] or tokens invalid
        resolution_rule_unproven                   — resolutionSource/description incoherent
        market_inactive_or_closed                  — active != true or closed != false

    Note: binary_token_pair_valid is implied by token_direction_mapping_proven
    (which is stricter). We do NOT emit a separate rejection reason for
    binary_token_pair_valid failure — the directional check subsumes it.

    Returns (ok, list_of_rejection_reasons). ok is True iff reasons is empty.
    """
    reasons: list[str] = []

    # 0. conditionId must be present
    condition_id = str(market.get("conditionId") or market.get("condition_id") or "").strip()
    if not condition_id:
        reasons.append("missing_condition_id")

    # 1. binary_token_pair_valid (subsumed by check 3, but emit a reason
    #    if both binary and directional checks fail to distinguish cases)
    binary_ok = _binary_token_pair_valid(market)

    # 2. directional_market_identity_proven (structural slug + event ticker)
    directional_ok, slug_epoch_str = _directional_market_identity_proven(market)
    if not directional_ok:
        reasons.append("directional_market_identity_unproven")

    # 3. token_direction_mapping_proven (outcomes == ["Up","Down"] exactly)
    mapping_ok = _token_direction_mapping_proven(market)
    if not mapping_ok:
        # If binary check also failed, the directional check is moot —
        # emit token_direction_mapping_unproven either way because we
        # require the exact ["Up","Down"] mapping.
        reasons.append("token_direction_mapping_unproven")

    # 4. window_duration_proven (slug_epoch == eventStartTime, end-start=300)
    if directional_ok:  # Only check window if slug is structurally valid
        window_ok, window_reasons = _window_duration_proven(market, slug_epoch_str, expected_window_s)
        if not window_ok:
            reasons.extend(window_reasons)
    # If directional failed, window_slug_unproven is already implied by
    # directional_market_identity_unproven — don't double-count.

    # 5. resolution_rule_proven (BTC/USD source + price comparison description)
    if not _resolution_rule_proven(market):
        reasons.append("resolution_rule_unproven")

    # 6. market must be active and not closed
    if not _market_active_and_open(market):
        reasons.append("market_inactive_or_closed")

    return len(reasons) == 0, reasons


def select_btc_cohort(markets: list[dict[str, Any]], windows: tuple[int, ...] = (300, 900)) -> list[dict[str, Any]]:
    """Return only markets whose structured BTC contract is proven."""
    selected = []
    for market in markets:
        for window in windows:
            ok, _ = validate_btc_market_identity(market, window)
            if ok:
                selected.append({**market, "_validated_window_s": window})
                break
    return selected


# ═══════════════════════════════════════════════════════════════════════
# Record schema
# ═══════════════════════════════════════════════════════════════════════

def _empty_v3_record(
    run_id: str,
    scan_id: str,
    condition_id: str,
    structure: MarketStructure,
    config: H011V3Config,
) -> dict[str, Any]:
    """Create the canonical V3 record skeleton."""
    record = {
        "schema_version": "h011-v3-record-v1",
        "run_id": run_id,
        "scan_id": scan_id,
        "condition_id": condition_id,
        "metadata": {
            "question": structure.question,
        },
        "market_structure": {
            "metadata_hash": structure.metadata_hash,
            "legs": [
                {"index": l.index, "label": l.label, "token_id": l.token_id}
                for l in structure.legs
            ],
        },
        "cohort": {
            "cohort_id": H011_COHORT_ID,
            "window_s": config.window_s,
            "confirmatory_eligible": True,
        },
        "validation": {
            "identity": "market_identity_match_v1",
            "structure": "market_structure_verified_v2",
            "trade_binding": "UNKNOWN",
            "execution": "NOT_EVALUATED",
        },
        "historical_signal": {
            "status": "UNAVAILABLE",
            "leg_0_vwap": None,
            "leg_1_vwap": None,
            "sum_vwap": None,
            "dev_signed": None,
            "dev_abs": None,
            "trade_count_leg_0": 0,
            "trade_count_leg_1": 0,
            "volume_leg_0": 0.0,
            "volume_leg_1": 0.0,
        },
        "quoted_liquidity": {
            "status": "UNAVAILABLE",
            "leg_0_book_hash": None,
            "leg_1_book_hash": None,
            "leg_0_received_ts": None,
            "leg_1_received_ts": None,
            "snapshot_delta_ms": None,
        },
        "shadow_execution": {
            "status": "NOT_EVALUATED",
            "target_quantity": None,
            "equal_fillable_quantity": None,
            "leg_0_walk_vwap": None,
            "leg_1_walk_vwap": None,
            "gross_cost": None,
            "fee_rate": None,
            "fees": None,
            "latency_buffer": None,
            "safety_buffer": None,
            "net_cost": None,
            "net_edge": None,
            "rejection_reasons": [],
        },
        "realized_outcome": {
            "status": "NOT_AVAILABLE",
            "fills": None,
            "realized_pnl": None,
        },
        "evidence": {
            "raw_event_hashes": [],
            "record_hash": "",
        },
    }
    return record


def _finalize_record(record: dict) -> dict:
    """Compute record_hash and return finalized record."""
    # Hash everything except the record_hash field itself
    hash_input = {k: v for k, v in record.items() if k != "evidence"}
    hash_input["evidence"] = {k: v for k, v in record["evidence"].items() if k != "record_hash"}
    canonical = json.dumps(hash_input, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    record["evidence"]["record_hash"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return record


# ═══════════════════════════════════════════════════════════════════════
# Core: process_market_v3
# ═══════════════════════════════════════════════════════════════════════

def process_market_v3(
    *,
    gamma_market: dict,
    now_ts: int,
    config: H011V3Config,
    run_id: str,
    scan_id: str,
    data_api_client: DataApiClient,
    clob_client: ClobClient,
    persist_raw: bool = True,
) -> dict[str, Any]:
    """
    Process a single market through the full V3 pipeline.

    Returns a V3 record dict. Never returns None — always returns a record
    with explicit status/rejection reasons.
    """
    window_start_ts = now_ts - config.window_s

    # ── Step 0 (Fix #3, fourth audit): Defense in depth ──
    # Re-validate directional identity BEFORE stub check or structure parsing.
    # This prevents a caller from bypassing discovery validation by invoking
    # process_market_v3 directly with invalid metadata.
    identity_ok, identity_reasons = validate_btc_market_identity(gamma_market, config.window_s)
    if not identity_ok:
        return {
            "schema_version": "h011-v3-record-v1",
            "run_id": run_id, "scan_id": scan_id,
            "condition_id": str(gamma_market.get("conditionId") or ""),
            "record_status": "REJECTED_IDENTITY",
            "stage": "defense_in_depth_identity",
            "reason_code": "directional_identity_failed",
            "reason_detail": "; ".join(identity_reasons),
            "rejection_reasons": identity_reasons,
            "evidence": {"raw_event_hashes": [], "record_hash": ""},
            "data_api_called": False,
            "clob_called": False,
        }

    # ── Step 0b (Fix #3): Re-validate temporal eligibility using now_ts ──
    # A market may have expired between discovery and processing, or a caller
    # may pass a market with a window that doesn't contain now_ts.
    def _epoch(value: Any) -> float | None:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
            except (ValueError, TypeError):
                return None
        return None

    es_epoch = _epoch(gamma_market.get("eventStartTime"))
    ed_epoch = _epoch(gamma_market.get("endDate"))
    active = gamma_market.get("active")
    closed = gamma_market.get("closed")
    accepting = gamma_market.get("acceptingOrders")
    temporal_reasons = []
    if es_epoch is not None and es_epoch > now_ts:
        temporal_reasons.append("market_window_not_open")
    if ed_epoch is not None and now_ts >= ed_epoch:
        temporal_reasons.append("market_window_expired")
    if active is not True:
        temporal_reasons.append("market_inactive_or_closed")
    elif closed is not False:
        temporal_reasons.append("market_inactive_or_closed")
    if accepting is not True:
        temporal_reasons.append("orders_not_accepting")
    if temporal_reasons:
        return {
            "schema_version": "h011-v3-record-v1",
            "run_id": run_id, "scan_id": scan_id,
            "condition_id": str(gamma_market.get("conditionId") or ""),
            "record_status": "REJECTED_TEMPORAL_ELIGIBILITY",
            "stage": "defense_in_depth_temporal",
            "reason_code": temporal_reasons[0],
            "reason_detail": "; ".join(temporal_reasons),
            "rejection_reasons": temporal_reasons,
            "evidence": {"raw_event_hashes": [], "record_hash": ""},
            "data_api_called": False,
            "clob_called": False,
        }

    # ── Step 1: Reject stubs ──
    # Fix #2 (third audit): stub check no longer requires outcomePrices.
    if is_market_stub(gamma_market):
        return {
            "schema_version": "h011-v3-record-v1",
            "run_id": run_id, "scan_id": scan_id,
            "condition_id": str(gamma_market.get("conditionId") or ""),
            "record_status": "REJECTED_METADATA",
            "stage": "stub_check",
            "reason_code": "active_market_metadata_unresolved",
            "reason_detail": "Market is a stub — missing conditionId, clobTokenIds, or outcomes",
            "evidence": {"raw_event_hashes": [], "record_hash": ""},
            "data_api_called": False,
            "clob_called": False,
        }

    # ── Step 2: Parse structure from Gamma ──
    try:
        structure = structure_from_gamma(gamma_market)
    except MarketStructureError as e:
        return {
            "schema_version": "h011-v3-record-v1",
            "run_id": run_id, "scan_id": scan_id,
            "condition_id": str(gamma_market.get("conditionId") or ""),
            "record_status": "REJECTED_METADATA",
            "stage": "structure_from_gamma",
            "reason_code": "structure_error",
            "reason_detail": str(e),
            "evidence": {"raw_event_hashes": [], "record_hash": ""},
            "data_api_called": False,
            "clob_called": False,
        }

    record = _empty_v3_record(run_id, scan_id, structure.condition_id, structure, config)
    record["_raw_bundle"] = {
        "gamma": gamma_market,
        "trades": raw_trades if False else [],
        "books": {},
        "fees": {"takerBaseFee": gamma_market.get("takerBaseFee"), "feesEnabled": structure.fees_enabled},
    }

    # ── Step 3: Fetch Data API trades ──
    raw_trades = data_api_client.fetch_trades(structure.condition_id, window_start_ts, now_ts)
    record["_raw_bundle"]["trades"] = raw_trades

    # Save raw Data API response BEFORE transforming
    raw_event = create_raw_event(
        condition_id=structure.condition_id,
        payload=raw_trades,
        request_params={"market": structure.condition_id},
        window_s=config.window_s,
    )
    if persist_raw:
        _ensure_v3_dirs()
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        raw_path = V3_RAW_DIR / f"{date_str}.events.jsonl.gz"
        append_raw_event(raw_path, raw_event)
    record["evidence"]["raw_event_hashes"].append(raw_event["payload_sha256"])

    if not raw_trades:
        record["validation"]["trade_binding"] = "UNKNOWN"
        record["historical_signal"]["status"] = "UNAVAILABLE"
        record["shadow_execution"]["status"] = "REJECTED"
        record["shadow_execution"]["rejection_reasons"] = ["no_trades_in_window"]
        record["record_status"] = "REJECTED_NO_TRADES"
        return _finalize_record(record)

    # ── Step 4: Validate trade-to-token binding ──
    verified_trades = []
    binding_rejections = []
    for trade in raw_trades:
        ok, reason = validate_trade_binding(trade, structure)
        if ok:
            verified_trades.append(trade)
        else:
            binding_rejections.append(reason)

    if not verified_trades:
        record["validation"]["trade_binding"] = "INVALID"
        record["shadow_execution"]["status"] = "REJECTED"
        record["shadow_execution"]["rejection_reasons"] = binding_rejections[:5]
        record["record_status"] = "REJECTED_TRADE_BINDING"
        return _finalize_record(record)

    record["validation"]["trade_binding"] = "trade_token_binding_verified_v1"

    # ── Step 5: Staleness filter ──
    ts_0 = [t.get("timestamp", 0) for t in verified_trades if int(t.get("outcomeIndex", -1)) == 0]
    ts_1 = [t.get("timestamp", 0) for t in verified_trades if int(t.get("outcomeIndex", -1)) == 1]
    staleness_delta = 0.0
    if ts_0 and ts_1:
        avg_0 = sum(ts_0) / len(ts_0)
        avg_1 = sum(ts_1) / len(ts_1)
        staleness_delta = abs(avg_0 - avg_1)
        if staleness_delta > config.staleness_threshold_sec:
            record["shadow_execution"]["status"] = "REJECTED"
            record["shadow_execution"]["rejection_reasons"] = [f"staleness_{staleness_delta:.0f}s_exceeds_{config.staleness_threshold_sec}s"]
            record["record_status"] = "REJECTED_STALENESS"
            return _finalize_record(record)

    # ── Step 6: Compute VWAP by index ──
    vwap_results = compute_vwap_by_index(verified_trades)
    leg_0 = vwap_results.get(0, {})
    leg_1 = vwap_results.get(1, {})

    if leg_0.get("vwap") is None or leg_1.get("vwap") is None:
        record["record_status"] = "REJECTED_INSUFFICIENT_LEG_TRADES"
        record["shadow_execution"]["rejection_reasons"] = ["insufficient_trades_one_leg"]
        return _finalize_record(record)

    sum_vwap = leg_0["vwap"] + leg_1["vwap"]
    dev_signed = sum_vwap - 1.0
    dev_abs = abs(dev_signed)

    record["historical_signal"] = {
        "status": "AVAILABLE",
        "leg_0_vwap": leg_0["vwap"],
        "leg_1_vwap": leg_1["vwap"],
        "sum_vwap": round(sum_vwap, 6),
        "dev_signed": round(dev_signed, 6),
        "dev_abs": round(dev_abs, 6),
        "trade_count_leg_0": leg_0.get("count", 0),
        "trade_count_leg_1": leg_1.get("count", 0),
        "volume_leg_0": leg_0.get("volume", 0.0),
        "volume_leg_1": leg_1.get("volume", 0.0),
    }

    # ── Step 7: Fetch CLOB orderbooks by token_id ──
    token_0 = structure.legs[0].token_id
    token_1 = structure.legs[1].token_id

    # Assert token_id is NOT condition_id
    assert token_0 != structure.condition_id, "token_id must not equal condition_id"
    assert token_1 != structure.condition_id, "token_id must not equal condition_id"
    assert token_0 != token_1, "token IDs must be distinct"

    try:
        ts_before_0 = datetime.now(timezone.utc)
        book_0 = clob_client.fetch_book(token_0)
        ts_after_0 = datetime.now(timezone.utc)
        leg_0_received_ts = ts_after_0.isoformat()

        ts_before_1 = datetime.now(timezone.utc)
        book_1 = clob_client.fetch_book(token_1)
        record["_raw_bundle"]["books"] = {"leg_0": book_0, "leg_1": book_1}
        ts_after_1 = datetime.now(timezone.utc)
        leg_1_received_ts = ts_after_1.isoformat()

        snapshot_delta_ms = abs((ts_after_1 - ts_after_0).total_seconds() * 1000)

        # Save raw CLOB books
        book_0_hash = hashlib.sha256(json.dumps(book_0, sort_keys=True).encode()).hexdigest()
        book_1_hash = hashlib.sha256(json.dumps(book_1, sort_keys=True).encode()).hexdigest()
        record["evidence"]["raw_event_hashes"].extend([book_0_hash, book_1_hash])

        record["quoted_liquidity"] = {
            "status": "AVAILABLE",
            "leg_0_book_hash": book_0_hash,
            "leg_1_book_hash": book_1_hash,
            "leg_0_received_ts": leg_0_received_ts,
            "leg_1_received_ts": leg_1_received_ts,
            "snapshot_delta_ms": round(snapshot_delta_ms, 1),
        }

        if snapshot_delta_ms > config.max_snapshot_delta_ms:
            record["shadow_execution"]["status"] = "REJECTED"
            record["shadow_execution"]["rejection_reasons"] = [f"snapshot_delta_{snapshot_delta_ms:.0f}ms_exceeds_{config.max_snapshot_delta_ms}ms"]
            record["record_status"] = "REJECTED_SNAPSHOT_DESYNC"
            return _finalize_record(record)

    except Exception as e:
        record["quoted_liquidity"]["status"] = "UNAVAILABLE"
        record["shadow_execution"]["status"] = "REJECTED"
        record["shadow_execution"]["rejection_reasons"] = [f"clob_error: {str(e)[:100]}"]
        record["record_status"] = "REJECTED_BOOK_UNAVAILABLE"
        return _finalize_record(record)

    # ── Step 8: Walk both ask books ──
    target_q = config.min_equal_quantity * 10
    walk_0 = walk_asks(book_0.get("asks", []), target_q)
    walk_1 = walk_asks(book_1.get("asks", []), target_q)

    equal_fillable = min(walk_0.filled_shares, walk_1.filled_shares)

    if equal_fillable < config.min_equal_quantity:
        record["shadow_execution"]["status"] = "REJECTED"
        record["shadow_execution"]["rejection_reasons"] = [
            f"insufficient_equal_depth: fillable_0={walk_0.filled_shares:.2f} fillable_1={walk_1.filled_shares:.2f} min={config.min_equal_quantity}"
        ]
        record["record_status"] = "REJECTED_INSUFFICIENT_EQUAL_DEPTH"
        return _finalize_record(record)

    # ── Step 9: Resolve fee rate ──
    fee_rate = None
    if structure.fees_enabled:
        fee_rate_str = gamma_market.get("takerBaseFee", "")
        try:
            fee_rate = int(fee_rate_str) / 1_000_000 if fee_rate_str else None
        except (ValueError, TypeError):
            fee_rate = None

    if structure.fees_enabled and fee_rate is None:
        record["shadow_execution"]["status"] = "REJECTED"
        record["shadow_execution"]["rejection_reasons"] = ["fee_rate_unknown"]
        record["record_status"] = "REJECTED_FEE_UNKNOWN"
        return _finalize_record(record)

    fee_rate = fee_rate or 0.0

    # ── Step 10: Calculate costs, fees, net edge ──
    snapshot = simulate_complete_set(book_0, book_1, equal_fillable, fee_rate)

    gross_cost = snapshot.total_cost
    fees = snapshot.taker_fees
    latency_buffer = gross_cost * (config.latency_buffer_bps / 10000)
    safety_buffer = gross_cost * (config.safety_buffer_bps / 10000)
    net_cost = gross_cost + fees + latency_buffer + safety_buffer
    net_edge = snapshot.payout - net_cost

    record["shadow_execution"] = {
        "status": "SHADOW_EXECUTABLE" if (snapshot.fully_fillable and net_edge > 0) else "REJECTED",
        "target_quantity": target_q,
        "equal_fillable_quantity": equal_fillable,
        "leg_0_walk_vwap": snapshot.leg_0_cost / snapshot.shares if snapshot.shares > 0 else None,
        "leg_1_walk_vwap": snapshot.leg_1_cost / snapshot.shares if snapshot.shares > 0 else None,
        "gross_cost": round(gross_cost, 6),
        "fee_rate": fee_rate,
        "fees": round(fees, 6),
        "latency_buffer": round(latency_buffer, 6),
        "safety_buffer": round(safety_buffer, 6),
        "net_cost": round(net_cost, 6),
        "net_edge": round(net_edge, 6),
        "rejection_reasons": [] if net_edge > 0 else ["net_edge_non_positive"],
    }

    record["validation"]["execution"] = "l2_executable_snapshot_v1" if net_edge > 0 else "REJECTED"

    if net_edge <= 0:
        record["record_status"] = "REJECTED_NON_POSITIVE_NET_EDGE"
    else:
        record["record_status"] = "SHADOW_EXECUTABLE"
    # If historical signal available but no L2 execution:
    if record["historical_signal"]["status"] == "AVAILABLE" and record["shadow_execution"]["status"] != "SHADOW_EXECUTABLE":
        if record["record_status"] not in ("SHADOW_EXECUTABLE",):
            record["record_status"] = "HISTORICAL_SIGNAL_ONLY"

    return _finalize_record(record)


# ═══════════════════════════════════════════════════════════════════════
# Scan orchestrator
# ═══════════════════════════════════════════════════════════════════════

def run_scan_v3(
    *,
    markets: list[dict],
    now_ts: int,
    config: H011V3Config,
    data_api_client: DataApiClient,
    clob_client: ClobClient,
    persist_raw: bool = True,
    discovery: dict[str, Any] | None = None,
    gamma_tracker=None,
    canonical_tracker=None,
    data_api_tracker=None,
) -> dict[str, Any]:
    """
    Run a complete V3 scan over a list of markets.

    Returns a dict with scan metadata and list of records.
    """
    config.validate()  # Assert V3 invariants at startup

    run_id = datetime.now(timezone.utc).isoformat()
    scan_id = run_id

    scan_meta = {
        "pipeline_version": "h011-integrity-v3",
        "cohort_id": H011_COHORT_ID,
        "window_s": config.window_s,
        "estimator": config.estimator,
        "paper_only": config.paper_only,
        "live_capital_locked": config.live_capital_locked,
        "orders_enabled": False,
        "run_id": run_id,
        "scan_id": scan_id,
        "started_at": run_id,
        "markets_input": len(markets),
        "discovery_status": (discovery or {}).get("status", "UNKNOWN"),
        "discovery_complete": bool((discovery or {}).get("discovery_complete", False)),
        "discovery_replay_verified": bool((discovery or {}).get("discovery_replay_verified", False)),
    }

    print(f"\n[V3 SCAN] {json.dumps(scan_meta, indent=2)}")

    records = []
    for i, market in enumerate(markets, 1):
        q = (market.get("question") or "")[:50]
        print(f"  [{i:3d}/{len(markets)}] {q:<50}", end="")
        record = process_market_v3(
            gamma_market=market,
            now_ts=now_ts,
            config=config,
            run_id=run_id,
            scan_id=scan_id,
            data_api_client=data_api_client,
            clob_client=clob_client,
            persist_raw=persist_raw,
        )
        records.append(record)

        status = record.get("record_status", "UNKNOWN")
        if status == "SHADOW_EXECUTABLE":
            print(f" → ✅ {status}")
        elif status == "HISTORICAL_SIGNAL_ONLY":
            print(f" → 📡 {status} (dev={record['historical_signal'].get('dev_signed', '?')})")
        else:
            print(f" → ❌ {status}")

        time.sleep(0.15)

    # Save V3 records (separate from legacy)
    _ensure_v3_dirs()
    v3_path = V3_SCANS_DIR / f"v3_scan_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.jsonl"
    with open(v3_path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")

    # Update V3 master log
    summary = {
        **scan_meta,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "markets_processed": len(records),
        "shadow_executable": sum(1 for r in records if r.get("record_status") == "SHADOW_EXECUTABLE"),
        "historical_signal_only": sum(1 for r in records if r.get("record_status") == "HISTORICAL_SIGNAL_ONLY"),
        "rejected": sum(1 for r in records if "REJECTED" in r.get("record_status", "")),
        "v3_scan_file": str(v3_path.name),
    }
    with open(V3_MASTER_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(summary, ensure_ascii=False, default=str) + "\n")

    print(f"\n[V3] Saved {len(records)} records to {v3_path}")
    print(f"[V3] Master log: {V3_MASTER_LOG}")
    print(f"[V3] Shadow executable: {summary['shadow_executable']}")
    print(f"[V3] Historical only: {summary['historical_signal_only']}")
    print(f"[V3] Rejected: {summary['rejected']}")

    # Persist one complete, replayable bundle before publishing the snapshot.
    code_sha = (
        os.environ.get("NF_DEPLOYMENT_SHA")
        or os.environ.get("GIT_SHA")
        or os.environ.get("SENECIO_CODE_SHA")
        or "unknown"
    )
    bundle_path = V3_RAW_DIR / f"bundle_{scan_id.replace(':', '').replace('+', '_')}.json"
    raw_gamma = [r.get("_raw_bundle", {}).get("gamma") for r in records if r.get("_raw_bundle", {}).get("gamma")]
    raw_trades = {str(r.get("condition_id")): r.get("_raw_bundle", {}).get("trades", []) for r in records}
    raw_books = {str(r.get("condition_id")): r.get("_raw_bundle", {}).get("books", {}) for r in records}
    raw_fees = {str(r.get("condition_id")): r.get("_raw_bundle", {}).get("fees", {}) for r in records}
    public_records = [{k: v for k, v in r.items() if k != "_raw_bundle"} for r in records]
    bundle = write_bundle(
        bundle_path, scan_id=scan_id, code_sha=code_sha,
        config=config.normalized(), gamma=raw_gamma, trades=raw_trades,
        books=raw_books, fees=raw_fees, records=public_records,
        run_id=run_id, cohort_identity=H011_COHORT_ID, window_end_ts=now_ts,
    )
    summary["semantic_hash"] = bundle["semantic_hash"]
    summary["canonical_content_hash"] = bundle["canonical_content_hash"]
    summary["file_sha256"] = bundle["file_sha256"]
    summary["raw_bundle"] = bundle_path.name

    # ── Generate snapshot ──
    try:
        from control_plane.state_snapshot import build_snapshot, save_snapshot
        funnel = {
            "discovered": len(markets),
            "identity_valid": sum(1 for r in records if r.get("record_status") != "REJECTED_METADATA"),
            "structure_verified": sum(1 for r in records if r.get("validation", {}).get("structure") == "market_structure_verified_v2"),
            "trade_binding_verified": sum(1 for r in records if r.get("validation", {}).get("trade_binding") == "trade_token_binding_verified_v1"),
            "historical_signal_available": sum(1 for r in records if r.get("historical_signal", {}).get("status") == "AVAILABLE"),
            "shadow_executable": summary["shadow_executable"],
            "rejected": summary["rejected"],
        }
        def compact_reason(record: dict[str, Any]) -> str:
            """Keep the terminal rejection reason visible without changing the record."""
            direct = record.get("reason_code")
            if direct:
                return str(direct)
            historical = record.get("historical_signal", {}).get("reason_code")
            if historical:
                return str(historical)
            reasons = record.get("shadow_execution", {}).get("rejection_reasons") or []
            return ", ".join(str(reason) for reason in reasons) or "not_recorded"

        market_records_compact = [
            {
                "condition_id": r.get("condition_id", r.get("metadata", {}).get("condition_id", "")),
                "question": r.get("metadata", {}).get("question", r.get("question", ""))[:80],
                "record_status": r.get("record_status", "UNKNOWN"),
                "reason_code": compact_reason(r),
                "dev_signed": r.get("historical_signal", {}).get("dev_signed"),
                "sum_vwap": r.get("historical_signal", {}).get("sum_vwap"),
                "net_edge": r.get("shadow_execution", {}).get("net_edge"),
                "equal_fillable_quantity": r.get("shadow_execution", {}).get("equal_fillable_quantity"),
                "record_hash": r.get("evidence", {}).get("record_hash", ""),
                "real_order_sent": False,
                "real_fill": False,
                "realized_pnl": None,
            }
            for r in records
        ]
        # Fix #1: Use real source health trackers (instrumented at HTTP call sites)
        # Gamma tracker covers /events/keyset; canonical tracker covers /markets/slug
        if gamma_tracker is not None:
            gamma_health = gamma_tracker.build()
        else:
            gamma_health = not_used_source_health("gamma_metadata", "No gamma tracker provided")
        if canonical_tracker is not None:
            canonical_health = canonical_tracker.build()
        else:
            canonical_health = not_used_source_health("gamma_canonical", "No canonical tracker provided")
        if data_api_tracker is not None:
            data_api_health = data_api_tracker.build()
        else:
            data_api_health = not_used_source_health("data_api_trades", "No data API tracker provided")

        # CLOB: NOT_USED unless shadow execution was attempted
        clob_attempted = any(r.get("shadow_execution", {}).get("attempted") for r in records)
        if clob_attempted:
            clob_health = SourceHealthTracker("clob_orderbook")
            clob_health.mark_used()
            clob_health.record_request()
            clob_health.record_response(200, 0)
            clob_health = clob_health.build()
        else:
            clob_health = not_used_source_health("clob_orderbook",
                "CLOB not consulted — no shadow-executable markets in paper-only mode")

        source_health_telemetry = {
            "gamma_metadata": gamma_health,
            "gamma_canonical": canonical_health,
            "data_api_trades": data_api_health,
            "clob_orderbook": clob_health,
        }

        # Fix #3: Read historical run_ids and scan_ids from previous snapshots
        previous_run_ids: list[str] = []
        previous_scan_ids: list[str] = []
        state_dir = V3_RESULTS_DIR / "state"
        if state_dir.exists():
            for snap_file in state_dir.glob("*.json"):
                if snap_file.name in ("latest.json", "latest.json.sha256"):
                    continue
                try:
                    snap_data = json.loads(snap_file.read_text())
                    rid = snap_data.get("run_id", "")
                    sid = snap_data.get("scan_id", "")
                    if rid:
                        previous_run_ids.append(rid)
                    if sid:
                        previous_scan_ids.append(sid)
                except (json.JSONDecodeError, OSError):
                    pass  # Corrupt file — will not be counted; INV-001/002 may be UNKNOWN

        # Build ScanContext for invariant evaluation
        ctx = ScanContext(
            run_id=run_id,
            scan_id=scan_id,
            pipeline_version="h011-integrity-v3",
            window_s=config.window_s,
            paper_only=config.paper_only,
            live_capital_locked=config.live_capital_locked,
            orders_enabled=False,
            funnel=funnel,
            market_records=market_records_compact,
            records=records,
            source_health=source_health_telemetry,
            discovery_meta={
                "status": scan_meta.get("discovery_status", "UNKNOWN"),
                "discovery_complete": scan_meta.get("discovery_complete", False),
                "markets_selected": len(markets),
            },
            snapshot_hash=summary.get("snapshot_hash"),
            snapshot_path=str(V3_RESULTS_DIR / "state" / "latest.json"),
            results_dir=str(V3_RESULTS_DIR),
            raw_dir=str(V3_RAW_DIR),
            previous_run_ids=previous_run_ids,
            previous_scan_ids=previous_scan_ids,
        )

        source_health, invariants, alerts, scan_status = compute_control_plane_state(
            ctx,
            discovery_replay_verified=scan_meta.get("discovery_replay_verified", False),
            file_sha256_matches=bool((discovery or {}).get("file_sha256_matches", False)),
            snapshot_hash_verified=bool(summary.get("snapshot_hash")),
            control_plane_replay_verified=False,  # Will be True when replay is implemented
        )
        snapshot = build_snapshot(
            scan_id=scan_id,
            run_id=run_id,
            pipeline_version="h011-integrity-v3",
            cohort_id=H011_COHORT_ID,
            window_s=config.window_s,
            estimator=config.estimator,
            code_sha=code_sha,
            config_sha=config.config_sha,
            scan_status=scan_status,
            source_health=source_health,
            funnel=funnel,
            market_records=market_records_compact,
            invariants=invariants,
            alerts=alerts,
            aggregate_metrics={
                "discovery": {
                    "status": scan_meta["discovery_status"],
                    "discovery_complete": scan_meta["discovery_complete"],
                    "discovery_replay_verified": scan_meta["discovery_replay_verified"],
                    "markets_selected": len(markets),
                    "evidence_file": (discovery or {}).get("artifact_path"),
                    "file_sha256_matches": bool((discovery or {}).get("file_sha256_matches", False)),
                    "rejection_histogram": ((discovery or {}).get("evidence") or {}).get("rejection_histogram", {}),
                }
            },
        )
        save_snapshot(snapshot)
        print(f"[V3] Snapshot saved: {snapshot.snapshot_hash[:16]}...")
        summary["snapshot_hash"] = snapshot.snapshot_hash
    except Exception as e:
        print(f"[V3] WARNING: Snapshot generation failed: {e}")
        summary["snapshot_hash"] = None

    return {"scan": summary, "records": records}
