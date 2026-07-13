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


def _merge_market_and_event(market: dict[str, Any], event_market: dict[str, Any],
                            parent_event: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """Structurally merge a /markets entry with the same market seen via /events.

    Returns (merged_market, conflict_reason). If conflict_reason is not None,
    the merged market is None and the caller should reject with that reason.
    """
    # Helper: a value is "missing" only if it is None or an empty string.
    # False, 0, and other falsy values are NOT missing — they are real data.
    def _is_missing(v: Any) -> bool:
        return v is None or (isinstance(v, str) and v == "")

    # Check material contradictions on priority fields.
    for field in _MARKET_PRIORITY_FIELDS:
        m_val = market.get(field)
        e_val = event_market.get(field)
        m_has = not _is_missing(m_val)
        e_has = not _is_missing(e_val)
        if m_has and e_has:
            # Both present — must match (after JSON normalization for strings)
            m_norm = m_val
            e_norm = e_val
            if isinstance(m_val, str) and isinstance(e_val, str):
                try:
                    m_norm = json.loads(m_val) if m_val.startswith(("[", "{")) else m_val
                    e_norm = json.loads(e_val) if e_val.startswith(("[", "{")) else e_val
                except (json.JSONDecodeError, ValueError):
                    pass
            elif isinstance(m_val, str) and isinstance(e_val, list):
                try:
                    m_norm = json.loads(m_val) if m_val.startswith(("[", "{")) else m_val
                except (json.JSONDecodeError, ValueError):
                    pass
            elif isinstance(m_val, list) and isinstance(e_val, str):
                try:
                    e_norm = json.loads(e_val) if e_val.startswith(("[", "{")) else e_val
                except (json.JSONDecodeError, ValueError):
                    pass
            if m_norm != e_norm:
                return None, "cross_source_identity_conflict"

    # Start from /markets (canonical), enrich with /events fields where missing.
    merged = dict(market)
    for field in _MARKET_PRIORITY_FIELDS:
        if _is_missing(merged.get(field)) and not _is_missing(event_market.get(field)):
            merged[field] = event_market[field]

    # Enrich with parent event fields (under "events" key for downstream validation).
    existing_events = merged.get("events") or []
    if not isinstance(existing_events, list):
        existing_events = []
    event_enrichment = {}
    for field in _EVENT_ENRICHMENT_FIELDS:
        if not _is_missing(parent_event.get(field)):
            event_enrichment[field] = parent_event[field]
    for field in ("description", "resolutionSource", "resolutionRules"):
        if _is_missing(merged.get(field)) and not _is_missing(parent_event.get(field)):
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

    Pagination rules:
      - Continue while the page is full (count == requested_limit).
      - Stop only when a page is empty or partial (source exhausted).
      - Detect repeated pages (same first conditionId at same offset) to
        avoid infinite loops.
      - No silent cap at 500/1000/2000 — the `limit` parameter is a hard
        upper bound but we always try to reach source exhaustion.
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

    def _fetch_endpoint_full(self, client: httpx.Client, endpoint: str,
                             limit: int, pages: list[dict]) -> tuple[list[dict], bool, bool]:
        """Paginate a single endpoint to source exhaustion.

        Returns (records, source_exhausted, limit_reached).
        For /events, records are flattened markets extracted from event objects.

        Stops when:
          - A page returns fewer records than requested (source exhausted)
          - We've collected `limit` records (limit reached)
          - max_pages_per_endpoint safety net is hit
          - A loop is detected (same first record at same offset)
        """
        records: list[dict] = []
        source_exhausted = False
        seen_page_signatures: set[tuple[int, str]] = set()
        page_count = 0

        for offset in range(0, limit, self.page_size):
            if page_count >= self.max_pages_per_endpoint:
                break
            if len(records) >= limit:
                break
            page_count += 1
            requested_limit = min(self.page_size, limit - offset)
            requested_at = datetime.now(timezone.utc).isoformat()
            try:
                response = client.get(f"{GAMMA_BASE}{endpoint}", params={
                    "limit": requested_limit, "offset": offset,
                    "active": "true", "closed": "false",
                })
                received_at = datetime.now(timezone.utc).isoformat()
                response.raise_for_status()
                payload = response.json()
            except Exception as e:
                pages.append({
                    "endpoint": endpoint, "offset": offset, "limit": requested_limit,
                    "requested_at": requested_at, "received_at": received_at,
                    "status_code": getattr(response, "status_code", None),
                    "count": 0, "error": f"{type(e).__name__}: {e}",
                })
                break

            if not isinstance(payload, list):
                pages.append({
                    "endpoint": endpoint, "offset": offset, "limit": requested_limit,
                    "requested_at": requested_at, "received_at": received_at,
                    "status_code": response.status_code, "count": 0,
                    "error": "response is not a list",
                })
                break

            pages.append({
                "endpoint": endpoint, "offset": offset, "limit": requested_limit,
                "requested_at": requested_at, "received_at": received_at,
                "status_code": response.status_code,
                "count": len(payload),  # raw records from API
            })

            # Loop detection
            page_signature = (offset, "")
            if payload:
                first = payload[0] if isinstance(payload[0], dict) else {}
                page_signature = (offset, str(first.get("conditionId") or first.get("id") or ""))
            if page_signature in seen_page_signatures and page_signature[1]:
                break
            seen_page_signatures.add(page_signature)

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
                source_exhausted = True
                break

        limit_reached = not source_exhausted and len(records) >= limit
        return records, source_exhausted, limit_reached

    def fetch_pages(self, limit: int) -> dict[str, Any]:
        pages: list[dict] = []
        merged_markets: dict[str, dict[str, Any]] = {}
        cross_source_conflicts: list[dict[str, Any]] = []
        missing_identifiers: int = 0
        markets_count = 0
        events_count = 0
        markets_exhausted = False
        events_exhausted = False

        with httpx.Client(timeout=30.0, transport=self.transport) as client:
            if self.fetch_markets:
                try:
                    mkts, markets_exhausted, _ = self._fetch_endpoint_full(
                        client, "/markets", limit, pages)
                    markets_count = len(mkts)
                    for m in mkts:
                        key = _structural_key(m)
                        if key is None:
                            missing_identifiers += 1
                            # Still keep with synthetic key for diagnostic
                            key = f"noid:{id(m)}"
                        if key not in merged_markets:
                            merged_markets[key] = dict(m)
                        else:
                            # Same market appearing twice in /markets — keep first
                            # (within-source duplicates are rare and not a conflict)
                            pass
                except Exception:
                    if not self.fetch_events:
                        raise

            if self.fetch_events:
                try:
                    ev_mkts, events_exhausted, _ = self._fetch_endpoint_full(
                        client, "/events", limit, pages)
                    events_count = len(ev_mkts)
                    for m in ev_mkts:
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
                                # Material contradiction — mark the market as conflicted
                                # but keep it in the cohort so the validator can emit
                                # the cross_source_identity_conflict reason.
                                merged_markets[key]["_cross_source_conflict"] = conflict
                                cross_source_conflicts.append({
                                    "key": key,
                                    "field_conflict": conflict,
                                })
                            elif merged is not None:
                                merged_markets[key] = merged
                        else:
                            # New market from /events only
                            new_m = dict(m)
                            if "_parent_event" in new_m:
                                parent_event = new_m.pop("_parent_event")
                                # Stash parent event under "events" for downstream validation
                                new_m["events"] = [parent_event] if parent_event else []
                            merged_markets[key] = new_m
                except Exception:
                    if not self.fetch_markets:
                        raise

        any_source_exhausted = markets_exhausted or events_exhausted
        markets_list = list(merged_markets.values())
        # limit_reached = neither endpoint exhausted AND we hit the limit
        limit_reached = (not any_source_exhausted) and len(markets_list) >= limit
        # next_offset is only meaningful when limit_reached
        next_offset = len(markets_list) if limit_reached else None

        return {
            "markets": markets_list,
            "pages": pages,
            "source_exhausted": any_source_exhausted,
            "limit_reached": limit_reached,
            "next_offset": next_offset,
            "discovery_metrics": {
                "markets_endpoint_records": markets_count,
                "events_endpoint_records": events_count,
                "merged_markets_count": len(markets_list),
                "cross_source_conflicts_count": len(cross_source_conflicts),
                "missing_identifiers_count": missing_identifiers,
                "markets_endpoint_exhausted": markets_exhausted,
                "events_endpoint_exhausted": events_exhausted,
            },
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
    """
    pages = evidence.get("pages", [])
    total_received = evidence.get("total_received")
    gamma_limit = evidence.get("gamma_limit")

    # Group pages by endpoint (legacy pages have no endpoint field → treat as "/markets")
    pages_by_endpoint: dict[str, list[dict]] = {}
    for page in pages:
        endpoint = page.get("endpoint", "/markets")
        pages_by_endpoint.setdefault(endpoint, []).append(page)

    # For each endpoint, verify offsets are continuous and counts are valid
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

    # Sum of all page counts across all endpoints.
    # For single-endpoint: should match total_received (no dedup).
    # For multi-endpoint: sum >= total_received (dedup reduces count).
    # We use `records_added` (post-flatten count) when available, falling
    # back to `count` (raw API record count) for legacy page entries.
    # We exclude pages where records_added/count is 0 (client stopped).
    def _page_record_count(page: dict) -> int:
        # Prefer records_added (post-flatten) when present; else use count
        if "records_added" in page:
            return page.get("records_added", 0) or 0
        return page.get("count", 0) or 0

    sum_page_counts = sum(
        _page_record_count(page) for page in pages
        if isinstance(pages, list) and _page_record_count(page) > 0
    )
    single_endpoint = len(pages_by_endpoint) <= 1
    if single_endpoint:
        page_counts_match = sum_page_counts == total_received
    else:
        # Multi-endpoint: sum of non-empty page counts >= total_received
        page_counts_match = sum_page_counts >= total_received

    # Terminal short = last NON-EMPTY page (across all endpoints) returned fewer
    # than requested. Empty pages (count=0) indicate the client stopped fetching
    # (likely hit limit or max_pages) and don't count as source exhaustion.
    terminal_short_per_endpoint = {}
    for endpoint, ep_pages in pages_by_endpoint.items():
        # Find the last non-empty page
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

    # source_exhausted = at least one endpoint had a terminal short page
    # (real source exhaustion, not just hitting limit)
    inferred_exhausted = any(terminal_short_per_endpoint.values()) if terminal_short_per_endpoint else False
    # limit_reached = no endpoint was exhausted AND total >= gamma_limit
    inferred_limit = (not inferred_exhausted) and total_received >= gamma_limit

    flags_match = (evidence.get("source_exhausted") == inferred_exhausted
                   and evidence.get("limit_reached") == inferred_limit)
    # next_offset: when limit_reached, should be >= gamma_limit (the client
    # may have collected more than gamma_limit records due to multi-endpoint
    # merge). When not limit_reached, should be None.
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
    """Fetch, validate and persist one bounded, replayable discovery attempt."""
    started_at = datetime.now(timezone.utc).isoformat()
    try:
        fetched = gamma_client.fetch_pages(gamma_limit)
        markets, pages = fetched["markets"], fetched["pages"]
        source_exhausted = bool(fetched["source_exhausted"])
        limit_reached = bool(fetched["limit_reached"])
        next_offset = fetched.get("next_offset")
        source_error = None
    except Exception as exc:
        markets, pages, source_exhausted, limit_reached, next_offset = [], [], False, False, None
        source_error = f"{type(exc).__name__}: {str(exc)[:200]}"
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
