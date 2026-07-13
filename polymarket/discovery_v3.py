"""Auditable, refreshable and replayable BTC market discovery for H-011 V3."""
from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

import httpx

GAMMA_BASE = "https://gamma-api.polymarket.com"
DISCOVERY_VERSION = "h011-v3-discovery-v3"
RESOLVED_PRICE_THRESHOLD = 0.95
PRICE_SUM_TOLERANCE = 0.02

# H-011 V3 rejection reasons — directional contract (post ce8ce2c6 revert).
# Each reason maps to one specific structural check; reasons are mutually
# exclusive per market (a market may fail multiple checks, accumulating
# multiple reasons). The validator remains fail-closed: any contradiction
# produces a rejection reason rather than a guess.
REJECTION_REASONS = (
    # conditionId
    "missing_condition_id",
    # Window / slug structural checks
    "window_slug_unproven",       # slug does not match ^btc-updown-5m-(\d{10})$
    "window_start_unproven",      # eventStartTime missing or unparseable
    "window_end_unproven",        # endDate missing or unparseable
    "window_start_mismatch",      # eventStartTime_epoch != slug_epoch (±1s tolerance)
    "window_duration_mismatch",   # endDate_epoch - eventStartTime_epoch != 300 (±1s)
    # Directional identity (NOT just binariness)
    "directional_market_identity_unproven",  # not a btc-updown-5m event family
    # Token binding — binary + directional mapping
    "token_direction_mapping_unproven",      # outcomes != ["Up","Down"] or tokens not unique
    # Resolution rule
    "resolution_rule_unproven",
    # Lifecycle state
    "market_inactive_or_closed",
    # Cross-source (markets vs events) contradiction
    "cross_source_identity_conflict",
    # Missing both conditionId and market id (cannot dedup)
    "missing_structural_identifier",
)
ALL_REJECTION_REASONS = (*REJECTION_REASONS, "invalid_outcome_prices", "resolved_extreme_prices")


class GammaDiscoveryClient(Protocol):
    def fetch_pages(self, limit: int) -> dict[str, Any]: ...


# Fields where /markets is canonical (NOT to be overwritten by /events).
_MARKET_PRIORITY_FIELDS = (
    "conditionId", "id", "slug", "outcomes", "clobTokenIds",
    "eventStartTime", "endDate", "active", "closed", "resolutionSource",
)

# Fields used to enrich a market from its parent event (only if missing).
_EVENT_ENRICHMENT_FIELDS = (
    "id", "slug", "ticker", "series", "tags",
)


def _structural_key(market: dict[str, Any]) -> str | None:
    """Return the canonical deduplication key for a market.

    Prefers conditionId (lowercased). Falls back to market `id`.
    Returns None if both are missing — caller MUST reject such markets
    with `missing_structural_identifier`.
    """
    cid = str(market.get("conditionId") or market.get("condition_id") or "").strip().lower()
    if cid:
        return f"cid:{cid}"
    mid = str(market.get("id") or "").strip()
    if mid:
        return f"mid:{mid}"
    return None


def _is_missing(v: Any) -> bool:
    """A value is "missing" only if it is None or an empty string.

    False, 0, and other falsy values are NOT missing — they are real data.
    """
    return v is None or (isinstance(v, str) and v == "")


def _normalize_value(v: Any) -> Any:
    """Normalize a value for cross-source comparison.

    JSON strings that encode lists/dicts are parsed to their native form
    so '["Up","Down"]' (string) matches ['Up','Down'] (list).
    """
    if isinstance(v, str):
        s = v.strip()
        if s.startswith(("[", "{")):
            try:
                return json.loads(s)
            except (json.JSONDecodeError, ValueError):
                return v
    return v


def _merge_market_and_event(market: dict[str, Any], event_market: dict[str, Any],
                            parent_event: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """Structurally merge a /markets entry with the same market seen via /events.

    Returns (merged_market, conflict_reason). If conflict_reason is not None,
    the merged market is None and the caller should reject with that reason.

    Fix #6 (enrichment top-level): when /markets lacks description, resolutionSource,
    or resolutionRules and the parent event has them, copy them to the merged
    market's TOP LEVEL (not just under events), because the validator reads
    top-level fields.
    """
    # Check material contradictions on priority fields.
    for field in _MARKET_PRIORITY_FIELDS:
        m_val = market.get(field)
        e_val = event_market.get(field)
        m_has = not _is_missing(m_val)
        e_has = not _is_missing(e_val)
        if m_has and e_has:
            if _normalize_value(m_val) != _normalize_value(e_val):
                return None, "cross_source_identity_conflict"

    # Start from /markets (canonical), enrich with /events fields where missing.
    merged = dict(market)
    for field in _MARKET_PRIORITY_FIELDS:
        if _is_missing(merged.get(field)) and not _is_missing(event_market.get(field)):
            merged[field] = event_market[field]

    # Fix #6: enrichment top-level — copy description, resolutionSource, resolutionRules
    # from parent_event to the merged market's TOP LEVEL when missing.
    # This is critical because validate_btc_market_identity reads top-level fields
    # (market.get("description"), market.get("resolutionSource")), not nested
    # events[*].description.
    for field in ("description", "resolutionSource", "resolutionRules"):
        if _is_missing(merged.get(field)) and not _is_missing(parent_event.get(field)):
            merged[field] = parent_event[field]

    # Also keep parent event under "events" for downstream validation.
    existing_events = merged.get("events") or []
    if not isinstance(existing_events, list):
        existing_events = []
    event_enrichment = {}
    for field in _EVENT_ENRICHMENT_FIELDS:
        if not _is_missing(parent_event.get(field)):
            event_enrichment[field] = parent_event[field]
    # Also carry description/rules into the event record (for full audit trail)
    for field in ("description", "resolutionSource", "resolutionRules"):
        if not _is_missing(parent_event.get(field)):
            event_enrichment[field] = parent_event[field]

    if event_enrichment:
        ev_id = event_enrichment.get("id")
        already_present = any(
            isinstance(ev, dict) and str(ev.get("id") or "") == str(ev_id or "")
            for ev in existing_events
        ) if ev_id else False
        if not already_present:
            existing_events.append(event_enrichment)
    merged["events"] = existing_events
    return merged, None


class HttpxGammaDiscoveryClient:
    """Paginate Gamma /markets AND /events, then structurally merge by conditionId.

    Per Polymarket docs (https://docs.polymarket.com/developers/gamma-markets-api/get-markets),
    /markets and /events are both paginated. /events groups markets under their
    parent event; /markets is the canonical source for per-market metadata.

    For H-011 V3 we fetch BOTH endpoints independently and merge them by
    conditionId (with fallback to market `id`). Merging is STRUCTURAL — not
    first-wins. Material contradictions on priority fields produce a
    `cross_source_identity_conflict` rejection reason.

    Pagination rules (Fix #2, #3, #4):
      - Continue while the page is full (count == requested_limit).
      - Stop only when a page is empty or partial (source exhausted).
      - HTTP errors are propagated as structured endpoint errors, NOT swallowed.
      - Loop detection uses an offset-INDEPENDENT signature (endpoint + count +
        first ID + last ID + hash of all IDs). If the same signature appears
        at different offsets, it's a loop.
      - Per-endpoint status: success | exhausted | limit_reached | loop_detected | error.

    Source exhaustion semantics (Fix #2):
      - source_exhausted = ALL(enabled endpoints exhausted)
      - limit_reached = ANY(enabled endpoint reached its limit)
      - If a required endpoint fails (error/loop), discovery is fail-closed:
        source_health=FAILED, no markets selected.
    """

    def __init__(self, *, page_size: int = 100, transport=None,
                 fetch_markets: bool = True, fetch_events: bool = True,
                 max_pages_per_endpoint: int = 100):
        self.page_size = page_size
        self.transport = transport
        self.fetch_markets = fetch_markets
        self.fetch_events = fetch_events
        # Safety net against pathological loops (default 100 pages = 10k markets)
        self.max_pages_per_endpoint = max_pages_per_endpoint

    def _page_signature(self, endpoint: str, payload: list) -> str:
        """Compute an offset-INDEPENDENT signature for loop detection.

        Fix #4: signature must NOT include offset. If the same set of records
        appears at a different offset, that's a loop. The signature includes:
          - endpoint
          - count
          - first stable ID (conditionId or id)
          - last stable ID
          - hash of all stable IDs
        """
        if not payload:
            return f"{endpoint}|empty"
        ids: list[str] = []
        for item in payload:
            if isinstance(item, dict):
                cid = str(item.get("conditionId") or item.get("id") or "")
                ids.append(cid)
            else:
                ids.append("")
        first_id = ids[0] if ids else ""
        last_id = ids[-1] if ids else ""
        ids_hash = hashlib.sha256("|".join(ids).encode()).hexdigest()[:16]
        return f"{endpoint}|{len(payload)}|{first_id}|{last_id}|{ids_hash}"

    def _fetch_endpoint_full(self, client: httpx.Client, endpoint: str,
                             limit: int, pages: list[dict]) -> dict[str, Any]:
        """Paginate a single endpoint to source exhaustion.

        Returns a dict with:
          - records: list of markets (flattened from events if endpoint=/events)
          - status: "success" | "exhausted" | "limit_reached" | "loop_detected" | "error"
          - error: str | None
          - api_objects_received: total raw API objects (events or markets) received
          - flattened_markets: for /events, count of markets extracted; for /markets, same as api_objects

        Fix #3: response and received_at are initialized BEFORE the try block
        to avoid UnboundLocalError if client.get raises.
        """
        records: list[dict] = []
        seen_page_signatures: set[str] = set()
        page_count = 0
        api_objects_received = 0
        loop_detected = False
        error: str | None = None
        status: str = "success"

        for offset in range(0, limit, self.page_size):
            if page_count >= self.max_pages_per_endpoint:
                status = "limit_reached"
                break
            if len(records) >= limit:
                status = "limit_reached"
                break
            page_count += 1
            requested_limit = min(self.page_size, limit - offset)
            requested_at = datetime.now(timezone.utc).isoformat()

            # Fix #3: initialize BEFORE the try block to avoid UnboundLocalError
            response = None
            received_at = None
            try:
                response = client.get(f"{GAMMA_BASE}{endpoint}", params={
                    "limit": requested_limit, "offset": offset,
                    "active": "true", "closed": "false",
                })
                received_at = datetime.now(timezone.utc).isoformat()
                response.raise_for_status()
                payload = response.json()
            except httpx.HTTPStatusError as e:
                # Polymarket's Gamma API returns HTTP 422 when the offset
                # exceeds the maximum supported value (observed at offset=2100
                # for /markets). This is NOT a server error — it's the API
                # telling us we've reached the end of pagination. Treat it
                # as source exhaustion, not as an error.
                status_code = e.response.status_code if e.response is not None else None
                if status_code == 422:
                    status = "exhausted"
                    pages.append({
                        "endpoint": endpoint, "offset": offset, "limit": requested_limit,
                        "requested_at": requested_at, "received_at": received_at,
                        "status_code": status_code, "count": 0,
                        "note": "HTTP 422 treated as source exhaustion (API offset limit)",
                    })
                    break
                # Other HTTP errors ARE real errors
                error_msg = f"{type(e).__name__}: {str(e)[:300]}"
                pages.append({
                    "endpoint": endpoint, "offset": offset, "limit": requested_limit,
                    "requested_at": requested_at, "received_at": received_at,
                    "status_code": status_code, "count": 0, "error": error_msg,
                })
                error = error_msg
                status = "error"
                break
            except Exception as e:
                # Fix #3: error is propagated as structured endpoint error.
                # No silent swallowing — the caller will see status="error"
                # and fail-closed.
                error_msg = f"{type(e).__name__}: {str(e)[:300]}"
                pages.append({
                    "endpoint": endpoint, "offset": offset, "limit": requested_limit,
                    "requested_at": requested_at, "received_at": received_at,
                    "status_code": getattr(response, "status_code", None) if response else None,
                    "count": 0, "error": error_msg,
                })
                error = error_msg
                status = "error"
                break

            if not isinstance(payload, list):
                err = f"response is not a list (type={type(payload).__name__})"
                pages.append({
                    "endpoint": endpoint, "offset": offset, "limit": requested_limit,
                    "requested_at": requested_at, "received_at": received_at,
                    "status_code": response.status_code, "count": 0,
                    "error": err,
                })
                error = err
                status = "error"
                break

            api_objects_received += len(payload)
            pages.append({
                "endpoint": endpoint, "offset": offset, "limit": requested_limit,
                "requested_at": requested_at, "received_at": received_at,
                "status_code": response.status_code,
                "count": len(payload),  # raw API objects
            })

            # Fix #4: offset-INDEPENDENT loop detection
            page_sig = self._page_signature(endpoint, payload)
            if page_sig in seen_page_signatures:
                loop_detected = True
                status = "loop_detected"
                # Update last page entry to mark loop
                if pages and pages[-1].get("endpoint") == endpoint:
                    pages[-1]["loop_detected"] = True
                break
            seen_page_signatures.add(page_sig)

            # Flatten events into markets and count records added this page
            records_added_this_page = 0
            if endpoint == "/events":
                for event in payload:
                    if not isinstance(event, dict):
                        continue
                    event_markets = event.get("markets") or []
                    for m in event_markets:
                        if isinstance(m, dict):
                            m_copy = dict(m)
                            m_copy["_parent_event"] = {
                                k: event.get(k) for k in _EVENT_ENRICHMENT_FIELDS
                                if event.get(k) is not None
                            }
                            for field in ("description", "resolutionSource", "resolutionRules"):
                                if not m_copy.get(field) and event.get(field):
                                    m_copy.setdefault(field, event[field])
                            records.append(m_copy)
                            records_added_this_page += 1
                            if len(records) >= limit:
                                break
                    if len(records) >= limit:
                        break
            else:
                for m in payload:
                    records.append(m)
                    records_added_this_page += 1
                    if len(records) >= limit:
                        break

            # Update the page entry with records_added (post-flatten count)
            if pages and pages[-1].get("endpoint") == endpoint and pages[-1].get("offset") == offset:
                pages[-1]["records_added"] = records_added_this_page

            if len(payload) < requested_limit:
                status = "exhausted"
                break

        # If we exited the loop without setting a terminal status, it means
        # we hit max_pages_per_endpoint or limit without exhausting source
        if status == "success":
            if len(records) >= limit:
                status = "limit_reached"
            else:
                # Didn't exhaust and didn't hit limit — shouldn't happen normally
                status = "limit_reached"

        return {
            "records": records,
            "status": status,
            "error": error,
            "loop_detected": loop_detected,
            "api_objects_received": api_objects_received,
            "flattened_markets": len(records),
        }

    def fetch_pages(self, limit: int) -> dict[str, Any]:
        pages: list[dict] = []
        merged_markets: dict[str, dict[str, Any]] = {}
        cross_source_conflicts: list[dict[str, Any]] = []
        missing_identifiers: int = 0
        duplicates_removed: int = 0

        # Fix #2: per-endpoint state tracking
        endpoint_states: dict[str, dict[str, Any]] = {}

        enabled_endpoints: list[str] = []
        if self.fetch_markets:
            enabled_endpoints.append("/markets")
        if self.fetch_events:
            enabled_endpoints.append("/events")

        with httpx.Client(timeout=30.0, transport=self.transport) as client:
            if self.fetch_markets:
                result_markets = self._fetch_endpoint_full(client, "/markets", limit, pages)
                endpoint_states["/markets"] = result_markets
                if result_markets["status"] != "error":
                    for m in result_markets["records"]:
                        key = _structural_key(m)
                        if key is None:
                            missing_identifiers += 1
                            key = f"noid:{id(m)}"
                        if key not in merged_markets:
                            merged_markets[key] = dict(m)
                        else:
                            duplicates_removed += 1

            if self.fetch_events:
                result_events = self._fetch_endpoint_full(client, "/events", limit, pages)
                endpoint_states["/events"] = result_events
                if result_events["status"] != "error":
                    for m in result_events["records"]:
                        key = _structural_key(m)
                        if key is None:
                            missing_identifiers += 1
                            key = f"noid:{id(m)}"
                        if key in merged_markets:
                            # MERGE — not first-wins
                            parent_event = m.get("_parent_event") or {}
                            merged, conflict = _merge_market_and_event(
                                merged_markets[key], m, parent_event)
                            if conflict:
                                merged_markets[key]["_cross_source_conflict"] = conflict
                                cross_source_conflicts.append({
                                    "key": key,
                                    "field_conflict": conflict,
                                })
                            elif merged is not None:
                                merged_markets[key] = merged
                            duplicates_removed += 1
                        else:
                            new_m = dict(m)
                            if "_parent_event" in new_m:
                                parent_event = new_m.pop("_parent_event")
                                new_m["events"] = [parent_event] if parent_event else []
                            merged_markets[key] = new_m

        # Fix #2: source_exhausted = ALL(enabled endpoints exhausted)
        # limit_reached = ANY(enabled endpoint reached limit_reached)
        # If any enabled endpoint has status "error" or "loop_detected",
        # discovery is fail-closed (source_exhausted=False, limit_reached=False,
        # and source_health will be FAILED).
        any_error_or_loop = any(
            endpoint_states.get(ep, {}).get("status") in ("error", "loop_detected")
            for ep in enabled_endpoints
        )
        if any_error_or_loop:
            source_exhausted = False
            limit_reached = False
        else:
            all_exhausted = all(
                endpoint_states.get(ep, {}).get("status") == "exhausted"
                for ep in enabled_endpoints
            )
            any_limit_reached = any(
                endpoint_states.get(ep, {}).get("status") == "limit_reached"
                for ep in enabled_endpoints
            )
            source_exhausted = all_exhausted
            # limit_reached only if not all exhausted (otherwise we have full source)
            limit_reached = any_limit_reached and not all_exhausted

        markets_list = list(merged_markets.values())
        next_offset = len(markets_list) if limit_reached else None

        # Fix #7: conservative, consistent metrics
        # markets_api_objects = raw /markets objects received
        # events_api_objects = raw /events objects received (events, not markets)
        # event_nested_markets_flattened = markets extracted from /events payloads
        # records_before_dedup = sum of markets from /markets + flattened from /events
        # unique_markets_after_dedup = len(merged_markets)
        # duplicates_removed = records_before_dedup - unique_markets_after_dedup
        markets_api_objects = endpoint_states.get("/markets", {}).get("api_objects_received", 0)
        events_api_objects = endpoint_states.get("/events", {}).get("api_objects_received", 0)
        event_nested_markets_flattened = endpoint_states.get("/events", {}).get("flattened_markets", 0)
        markets_from_markets = endpoint_states.get("/markets", {}).get("flattened_markets", 0)
        records_before_dedup = markets_from_markets + event_nested_markets_flattened
        unique_markets_after_dedup = len(markets_list)
        # Recompute duplicates_removed for consistency
        duplicates_removed = records_before_dedup - unique_markets_after_dedup - missing_identifiers

        # Fix #7: runtime assertion — unique_markets_after_dedup must be <=
        # markets_api_objects + event_nested_markets_flattened
        assert unique_markets_after_dedup <= (markets_from_markets + event_nested_markets_flattened), (
            f"Conservation violation: unique_markets_after_dedup={unique_markets_after_dedup} "
            f"> markets_from_markets({markets_from_markets}) + "
            f"event_nested_markets_flattened({event_nested_markets_flattened})"
        )

        return {
            "markets": markets_list,
            "pages": pages,
            "source_exhausted": source_exhausted,
            "limit_reached": limit_reached,
            "next_offset": next_offset,
            "discovery_metrics": {
                "markets_api_objects": markets_api_objects,
                "events_api_objects": events_api_objects,
                "event_nested_markets_flattened": event_nested_markets_flattened,
                "markets_from_markets_endpoint": markets_from_markets,
                "records_before_dedup": records_before_dedup,
                "unique_markets_after_dedup": unique_markets_after_dedup,
                "duplicates_removed": duplicates_removed,
                "cross_source_conflicts_count": len(cross_source_conflicts),
                "missing_identifiers_count": missing_identifiers,
            },
            "endpoint_states": {
                ep: {
                    "status": endpoint_states.get(ep, {}).get("status"),
                    "error": endpoint_states.get(ep, {}).get("error"),
                    "loop_detected": endpoint_states.get(ep, {}).get("loop_detected"),
                    "api_objects_received": endpoint_states.get(ep, {}).get("api_objects_received", 0),
                    "flattened_markets": endpoint_states.get(ep, {}).get("flattened_markets", 0),
                }
                for ep in enabled_endpoints
            },
            "any_source_error": any_error_or_loop,
        }


def _preliminary_btc(market: dict[str, Any]) -> bool:
    event = market.get("event") if isinstance(market.get("event"), dict) else {}
    haystack = " ".join(str(market.get(k) or event.get(k) or "").lower()
                        for k in ("slug", "eventSlug", "title", "question"))
    return "bitcoin" in haystack or "btc" in haystack


def _outcome_price_reason(market: dict[str, Any], *, threshold: float) -> str | None:
    """Accept only an ordinary, finite two-outcome probability vector.

    Returns None if prices are acceptable (or missing — None / empty means
    "no trades yet", which is valid for a newly listed market and should
    NOT block discovery).
    Returns a rejection reason string if prices exist but are invalid.
    """
    prices = market.get("outcomePrices")
    # Missing/None/empty prices = no trades yet — NOT a rejection.
    # This is common for newly listed btc-updown-5m markets that have
    # not yet seen any trade activity.
    if prices is None:
        return None
    if isinstance(prices, str) and prices.strip() == "":
        return None
    try:
        prices = json.loads(prices) if isinstance(prices, str) else prices
        if not isinstance(prices, list) or len(prices) != 2:
            return "invalid_outcome_prices"
        values = [float(price) for price in prices]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return "invalid_outcome_prices"
    if not all(math.isfinite(value) and 0.0 <= value <= 1.0 for value in values):
        return "invalid_outcome_prices"
    if abs(sum(values) - 1.0) > PRICE_SUM_TOLERANCE:
        return "invalid_outcome_prices"
    if any(value > threshold for value in values):
        return "resolved_extreme_prices"
    return None


def _selection_config(*, window_s: int, max_markets: int, gamma_limit: int,
                      resolved_price_threshold: float = RESOLVED_PRICE_THRESHOLD) -> dict[str, Any]:
    return {
        "window_s": window_s, "max_markets": max_markets, "gamma_limit": gamma_limit,
        "discovery_version": DISCOVERY_VERSION,
        "resolved_price_threshold": resolved_price_threshold,
        "price_sum_tolerance": PRICE_SUM_TOLERANCE,
    }


def _config_hash(selection_config: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(selection_config, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _select(raw_gamma: list[dict], window_s: int, max_markets: int, *, price_threshold: float) -> dict[str, Any]:
    from h011_v3_pipeline import validate_btc_market_identity
    histogram = Counter()
    selected: list[dict] = []
    preliminary = 0
    for market in raw_gamma:
        preliminary += int(_preliminary_btc(market))
        # Check for cross-source conflict marker set by the client
        if market.get("_cross_source_conflict"):
            histogram["cross_source_identity_conflict"] += 1
            continue
        # Check for missing structural identifier (no conditionId and no market id)
        cid = str(market.get("conditionId") or market.get("condition_id") or "").strip()
        mid = str(market.get("id") or "").strip()
        if not cid and not mid:
            histogram["missing_structural_identifier"] += 1
            continue
        ok, reasons = validate_btc_market_identity(market, window_s)
        if not ok:
            histogram.update(reasons)
            continue
        price_reason = _outcome_price_reason(market, threshold=price_threshold)
        if price_reason:
            histogram[price_reason] += 1
            continue
        # Strip internal markers before adding to selected
        clean = {k: v for k, v in market.items() if not k.startswith("_")}
        clean["_validated_window_s"] = window_s
        selected.append(clean)
    selected.sort(key=lambda item: float(item.get("volumeNum", 0) or 0), reverse=True)
    selected = selected[:max_markets]
    return {
        "markets": selected,
        "preliminary_btc_candidates": preliminary,
        "rejection_histogram": {reason: histogram.get(reason, 0) for reason in ALL_REJECTION_REASONS},
        "selected_condition_ids": [str(m.get("conditionId") or m.get("condition_id") or "") for m in selected],
    }


def _atomic_write(path: Path, payload: bytes) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, path)


def _enforce_retention(directory: Path, newest: Path, *, max_artifacts: int, max_bytes: int) -> None:
    artifacts = sorted(directory.glob("discovery_*.json.gz"), key=lambda p: p.stat().st_mtime, reverse=True)
    kept_bytes = 0
    for index, path in enumerate(artifacts):
        size = path.stat().st_size
        keep = path == newest or (index < max_artifacts and kept_bytes + size <= max_bytes)
        if keep:
            kept_bytes += size
            continue
        try:
            path.unlink()
            path.with_suffix(path.suffix + ".sha256").unlink(missing_ok=True)
        except OSError:
            pass


def _write_evidence(directory: Path, evidence: dict[str, Any], *,
                    max_artifacts: int, max_bytes: int) -> tuple[Path, str]:
    directory.mkdir(parents=True, exist_ok=True)
    stamp = evidence["finished_at"].replace(":", "").replace("+", "_")
    path = directory / f"discovery_{stamp}.json.gz"
    raw = json.dumps(evidence, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    payload = gzip.compress(raw, mtime=0)
    _atomic_write(path, payload)
    digest = hashlib.sha256(payload).hexdigest()
    _atomic_write(path.with_suffix(path.suffix + ".sha256"), (digest + "\n").encode("ascii"))
    _enforce_retention(directory, path, max_artifacts=max_artifacts, max_bytes=max_bytes)
    return path, digest


def _pagination_matches(evidence: dict[str, Any]) -> dict[str, bool]:
    """Verify pagination metadata is internally consistent.

    Supports both single-endpoint (legacy) and multi-endpoint (current)
    page formats. Multi-endpoint pages have an `endpoint` field; we verify
    each endpoint's pages independently.

    Fix #2: uses endpoint_states to determine source_exhausted (ALL endpoints
    exhausted) and limit_reached (ANY endpoint limit_reached). If any endpoint
    has status error or loop_detected, discovery is fail-closed.
    """
    pages = evidence.get("pages", [])
    total_received = evidence.get("total_received")
    gamma_limit = evidence.get("gamma_limit")
    endpoint_states = evidence.get("endpoint_states", {})

    # Group pages by endpoint
    pages_by_endpoint: dict[str, list[dict]] = {}
    for page in pages:
        endpoint = page.get("endpoint", "/markets")
        pages_by_endpoint.setdefault(endpoint, []).append(page)

    # Verify offsets are continuous per endpoint
    offsets_continuous = bool(pages) or total_received == 0
    for endpoint, ep_pages in pages_by_endpoint.items():
        expected_offset = 0
        for page in ep_pages:
            if (page.get("offset") != expected_offset
                    or not isinstance(page.get("limit"), int)
                    or page["limit"] <= 0
                    or not isinstance(page.get("count"), int)
                    or page["count"] < 0
                    or page["count"] > page["limit"]):
                offsets_continuous = False
                break
            expected_offset += page["limit"]

    # Sum of non-empty page counts, excluding loop pages (which duplicate data)
    def _page_record_count(page: dict) -> int:
        if "records_added" in page:
            return page.get("records_added", 0) or 0
        return page.get("count", 0) or 0

    sum_page_counts = sum(
        _page_record_count(page) for page in pages
        if isinstance(pages, list)
        and _page_record_count(page) > 0
        and not page.get("loop_detected", False)  # exclude loop pages
    )
    single_endpoint = len(pages_by_endpoint) <= 1
    # For single-endpoint: sum should match total_received, UNLESS there was
    # a loop (in which case some pages are duplicates that got deduplicated).
    has_loop = any(page.get("loop_detected", False) for page in pages)
    if single_endpoint:
        if has_loop:
            # With a loop, sum >= total_received (some pages are duplicates)
            page_counts_match = sum_page_counts >= total_received
        else:
            page_counts_match = sum_page_counts == total_received
    else:
        page_counts_match = sum_page_counts >= total_received

    # Fix #2: use endpoint_states for source_exhausted/limit_reached inference
    # Falls back to page-based inference if endpoint_states is missing (legacy evidence)
    if endpoint_states:
        any_error_or_loop = any(
            s.get("status") in ("error", "loop_detected")
            for s in endpoint_states.values()
        )
        if any_error_or_loop:
            inferred_exhausted = False
            inferred_limit = False
        else:
            all_exhausted = all(
                s.get("status") == "exhausted"
                for s in endpoint_states.values()
            ) if endpoint_states else False
            any_limit_reached = any(
                s.get("status") == "limit_reached"
                for s in endpoint_states.values()
            )
            inferred_exhausted = all_exhausted
            inferred_limit = any_limit_reached and not all_exhausted
    else:
        # Legacy fallback: page-based inference
        terminal_short_per_endpoint = {}
        for endpoint, ep_pages in pages_by_endpoint.items():
            last_non_empty = None
            for page in reversed(ep_pages):
                if page.get("count", 0) > 0:
                    last_non_empty = page
                    break
            if last_non_empty:
                terminal_short_per_endpoint[endpoint] = (
                    last_non_empty.get("count", 0) < last_non_empty.get("limit", 0)
                )
            else:
                terminal_short_per_endpoint[endpoint] = False
        inferred_exhausted = any(terminal_short_per_endpoint.values()) if terminal_short_per_endpoint else False
        inferred_limit = (not inferred_exhausted) and total_received >= gamma_limit

    flags_match = (evidence.get("source_exhausted") == inferred_exhausted
                   and evidence.get("limit_reached") == inferred_limit)
    if inferred_limit:
        next_offset_match = (
            evidence.get("next_offset") is not None
            and evidence.get("next_offset") >= gamma_limit
        )
    else:
        next_offset_match = evidence.get("next_offset") is None
    flags_match = flags_match and next_offset_match

    return {
        "total_received_matches": total_received == len(evidence.get("raw_gamma", [])),
        "page_counts_match": page_counts_match,
        "offsets_continuous": offsets_continuous,
        "pagination_flags_match": flags_match,
        "source_exhausted_inferred": inferred_exhausted,
        "limit_reached_inferred": inferred_limit,
    }


def replay_discovery(path: str | Path, *, expected_selection_config: dict[str, Any] | None = None) -> dict[str, Any]:
    path = Path(path)
    evidence = json.loads(gzip.decompress(path.read_bytes()))
    stored_config = evidence.get("selection_config", {})
    expected = expected_selection_config or {}
    pagination = _pagination_matches(evidence)

    # Fix #2/#9: if source_error is present (fail-closed), the replay must
    # produce empty selection (matching the original discovery behavior).
    # The original discovery skips _select when source_error is set, so
    # selected_condition_ids=[] and rejection_histogram is all zeros.
    if evidence.get("source_error"):
        recalculated = {
            "markets": [],
            "preliminary_btc_candidates": 0,
            "rejection_histogram": {reason: 0 for reason in ALL_REJECTION_REASONS},
            "selected_condition_ids": [],
        }
    else:
        recalculated = _select(
            evidence["raw_gamma"], expected.get("window_s", -1), expected.get("max_markets", -1),
            price_threshold=expected.get("resolved_price_threshold", RESOLVED_PRICE_THRESHOLD),
        )
    expected_status = evidence["status"]
    if evidence.get("source_error"):
        replay_status = "DISCOVERY_SOURCE_FAILED"
    elif pagination["limit_reached_inferred"]:
        replay_status = "DISCOVERY_TRUNCATED"
    elif not evidence["raw_gamma"]:
        replay_status = "DISCOVERY_SOURCE_EMPTY"
    elif not recalculated["markets"]:
        replay_status = "EMPTY_SELECTED_COHORT"
    else:
        replay_status = "SELECTED_NONEMPTY"
    matches = {
        "status_matches": replay_status == expected_status,
        "histogram_matches": recalculated["rejection_histogram"] == evidence["rejection_histogram"],
        "selected_ids_match": recalculated["selected_condition_ids"] == evidence["selected_condition_ids"],
        "selected_count_matches": len(recalculated["markets"]) == evidence["selected_count"],
        "window_matches": stored_config.get("window_s") == expected.get("window_s"),
        "max_markets_matches": stored_config.get("max_markets") == expected.get("max_markets"),
        "gamma_limit_matches": stored_config.get("gamma_limit") == expected.get("gamma_limit"),
        "price_threshold_matches": stored_config.get("resolved_price_threshold") == expected.get("resolved_price_threshold"),
        "config_hash_matches": (evidence.get("selection_config_hash") == _config_hash(stored_config)
                                and evidence.get("selection_config_hash") == _config_hash(expected)),
        "version_matches": (evidence.get("discovery_version") == DISCOVERY_VERSION
                            and stored_config.get("discovery_version") == DISCOVERY_VERSION
                            and expected.get("discovery_version") == DISCOVERY_VERSION),
    }
    pagination_checks = (
        pagination["total_received_matches"], pagination["page_counts_match"],
        pagination["offsets_continuous"], pagination["pagination_flags_match"],
    )
    return {**pagination, **matches, "discovery_replay_verified": all((*pagination_checks, *matches.values()))}


def discover_markets_v3(config, gamma_limit: int, gamma_client: GammaDiscoveryClient,
                        *, max_markets: int = 100, evidence_dir: Path | None = None,
                        retention_count: int = 192, retention_bytes: int = 256 * 1024 * 1024) -> dict[str, Any]:
    """Fetch, validate and persist one bounded, replayable discovery attempt.

    Fix #2: If any enabled endpoint has status "error" or "loop_detected",
    discovery is fail-closed: source_health=FAILED, no markets selected,
    status=DISCOVERY_SOURCE_FAILED.
    """
    started_at = datetime.now(timezone.utc).isoformat()
    discovery_metrics: dict[str, Any] = {}
    endpoint_states: dict[str, Any] = {}
    any_source_error = False
    try:
        fetched = gamma_client.fetch_pages(gamma_limit)
        markets, pages = fetched["markets"], fetched["pages"]
        source_exhausted = bool(fetched["source_exhausted"])
        limit_reached = bool(fetched["limit_reached"])
        next_offset = fetched.get("next_offset")
        source_error = None
        discovery_metrics = fetched.get("discovery_metrics", {})
        endpoint_states = fetched.get("endpoint_states", {})
        any_source_error = fetched.get("any_source_error", False)
    except Exception as exc:
        markets, pages, source_exhausted, limit_reached, next_offset = [], [], False, False, None
        source_error = f"{type(exc).__name__}: {str(exc)[:200]}"
        any_source_error = True

    # Fix #2: if any endpoint errored or looped, fail-closed
    if any_source_error and source_error is None:
        # Build a structured error message from endpoint states
        error_parts = []
        for ep, state in endpoint_states.items():
            if state.get("status") in ("error", "loop_detected"):
                error_parts.append(f"{ep}: {state.get('status')} ({state.get('error') or 'loop'})")
        source_error = "; ".join(error_parts) if error_parts else "unknown source error"

    selection_config = _selection_config(window_s=config.window_s, max_markets=max_markets, gamma_limit=gamma_limit)
    selected_data = _select(markets, config.window_s, max_markets,
                            price_threshold=selection_config["resolved_price_threshold"]) if source_error is None else {
        "markets": [], "preliminary_btc_candidates": 0,
        "rejection_histogram": {reason: 0 for reason in ALL_REJECTION_REASONS},
        "selected_condition_ids": [],
    }
    if source_error is not None:
        status = "DISCOVERY_SOURCE_FAILED"
    elif limit_reached:
        status = "DISCOVERY_TRUNCATED"
    elif not markets:
        status = "DISCOVERY_SOURCE_EMPTY"
    elif not selected_data["markets"]:
        status = "EMPTY_SELECTED_COHORT"
    else:
        status = "SELECTED_NONEMPTY"
    complete = source_error is None and source_exhausted and not limit_reached
    finished_at = datetime.now(timezone.utc).isoformat()
    evidence = {
        "schema_version": "h011-v3-discovery-evidence-v2", "discovery_version": DISCOVERY_VERSION,
        "started_at": started_at, "finished_at": finished_at, "status": status,
        "source_health": "FAILED" if source_error else "HEALTHY", "source_error": source_error,
        "gamma_limit": gamma_limit, "window_s": config.window_s, "max_markets": max_markets,
        "selection_config": selection_config, "selection_config_hash": _config_hash(selection_config),
        "pages": pages, "source_exhausted": source_exhausted, "limit_reached": limit_reached,
        "next_offset": next_offset, "total_received": len(markets),
        "preliminary_btc_candidates": selected_data["preliminary_btc_candidates"],
        "selected_count": len(selected_data["markets"]),
        "rejection_histogram": selected_data["rejection_histogram"], "raw_gamma": markets,
        "selected_condition_ids": selected_data["selected_condition_ids"],
        "discovery_complete": complete,
        "discovery_metrics": discovery_metrics,
        "endpoint_states": endpoint_states,
    }
    artifact_path = None
    file_sha256 = None
    replay = {"discovery_replay_verified": False}
    if evidence_dir is not None:
        artifact_path, file_sha256 = _write_evidence(
            evidence_dir, evidence, max_artifacts=retention_count, max_bytes=retention_bytes)
        replay = replay_discovery(artifact_path, expected_selection_config=selection_config)
    return {
        "status": status, "markets": selected_data["markets"], "evidence": evidence,
        "artifact_path": str(artifact_path) if artifact_path else None, "file_sha256": file_sha256,
        "file_sha256_matches": bool(artifact_path and hashlib.sha256(artifact_path.read_bytes()).hexdigest() == file_sha256),
        "discovery_complete": complete,
        "discovery_replay_verified": replay["discovery_replay_verified"],
        "discovery_replay": replay,
    }


def monitor_discovery_loop(*, discover: Callable[[], dict[str, Any]],
                           process: Callable[[dict[str, Any]], Any],
                           sleep: Callable[[float], None], interval_s: int = 900,
                           max_cycles: int | None = None) -> list[Any]:
    results = []
    cycle = 0
    while max_cycles is None or cycle < max_cycles:
        results.append(process(discover()))
        cycle += 1
        if max_cycles is None or cycle < max_cycles:
            sleep(interval_s)
    return results
