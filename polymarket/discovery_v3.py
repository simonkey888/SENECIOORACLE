"""Auditable, refreshable BTC market discovery for H-011 V3."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

import httpx

GAMMA_BASE = "https://gamma-api.polymarket.com"
DISCOVERY_VERSION = "h011-v3-discovery-v1"
REJECTION_REASONS = (
    "missing_condition_id",
    "btc_event_identity_unproven",
    "resolution_rule_unproven",
    "window_timestamps_unproven",
    "window_duration_mismatch",
    "up_down_token_identity_unproven",
)


class GammaDiscoveryClient(Protocol):
    def fetch_pages(self, limit: int) -> tuple[list[dict], list[dict]]: ...


class HttpxGammaDiscoveryClient:
    """Paginate active Gamma markets far beyond the generic first 200."""

    def __init__(self, *, page_size: int = 100):
        self.page_size = page_size

    def fetch_pages(self, limit: int) -> tuple[list[dict], list[dict]]:
        markets: list[dict] = []
        pages: list[dict] = []
        with httpx.Client(timeout=30.0) as client:
            for offset in range(0, limit, self.page_size):
                requested_at = datetime.now(timezone.utc).isoformat()
                response = client.get(f"{GAMMA_BASE}/markets", params={
                    "limit": min(self.page_size, limit - offset),
                    "offset": offset,
                    "active": "true",
                    "closed": "false",
                })
                received_at = datetime.now(timezone.utc).isoformat()
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, list):
                    raise ValueError("Gamma /markets response is not a list")
                pages.append({
                    "offset": offset,
                    "limit": min(self.page_size, limit - offset),
                    "requested_at": requested_at,
                    "received_at": received_at,
                    "status_code": response.status_code,
                    "count": len(payload),
                })
                markets.extend(payload)
                if len(payload) < self.page_size:
                    break
        return markets, pages


def _preliminary_btc(market: dict[str, Any]) -> bool:
    event = market.get("event") if isinstance(market.get("event"), dict) else {}
    haystack = " ".join(str(market.get(k) or event.get(k) or "").lower()
                        for k in ("slug", "eventSlug", "title", "question"))
    return "bitcoin" in haystack or "btc" in haystack


def _resolved_extreme(market: dict[str, Any]) -> bool:
    try:
        prices = market.get("outcomePrices", [])
        prices = json.loads(prices) if isinstance(prices, str) else prices
        return isinstance(prices, list) and len(prices) == 2 and any(float(p) > 0.95 for p in prices)
    except (TypeError, ValueError, json.JSONDecodeError):
        return True


def _write_evidence(directory: Path, evidence: dict[str, Any]) -> tuple[Path, str]:
    directory.mkdir(parents=True, exist_ok=True)
    stamp = evidence["finished_at"].replace(":", "").replace("+", "_")
    path = directory / f"discovery_{stamp}.json"
    payload = json.dumps(evidence, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    path.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    path.with_suffix(path.suffix + ".sha256").write_text(digest + "\n", encoding="ascii")
    return path, digest


def discover_markets_v3(config, gamma_limit: int, gamma_client: GammaDiscoveryClient,
                        *, max_markets: int = 100,
                        evidence_dir: Path | None = None) -> dict[str, Any]:
    """Fetch, validate and persist one complete discovery attempt."""
    from h011_v3_pipeline import validate_btc_market_identity

    started_at = datetime.now(timezone.utc).isoformat()
    try:
        markets, pages = gamma_client.fetch_pages(gamma_limit)
        source_error = None
    except Exception as exc:
        markets, pages = [], []
        source_error = f"{type(exc).__name__}: {str(exc)[:200]}"

    histogram = Counter()
    selected: list[dict] = []
    preliminary = 0
    if source_error is None:
        for market in markets:
            if _preliminary_btc(market):
                preliminary += 1
            ok, reasons = validate_btc_market_identity(market, config.window_s)
            if not ok:
                histogram.update(reasons)
                continue
            if _resolved_extreme(market):
                histogram["resolved_or_invalid_prices"] += 1
                continue
            selected.append({**market, "_validated_window_s": config.window_s})
        selected.sort(key=lambda item: float(item.get("volumeNum", 0) or 0), reverse=True)
        selected = selected[:max_markets]

    if source_error is not None:
        status = "DISCOVERY_SOURCE_FAILED"
    elif not markets:
        status = "DISCOVERY_SOURCE_EMPTY"
    elif not selected:
        status = "EMPTY_SELECTED_COHORT"
    else:
        status = "SELECTED_NONEMPTY"

    finished_at = datetime.now(timezone.utc).isoformat()
    evidence = {
        "schema_version": "h011-v3-discovery-evidence-v1",
        "discovery_version": DISCOVERY_VERSION,
        "started_at": started_at,
        "finished_at": finished_at,
        "status": status,
        "source_health": "FAILED" if source_error else "HEALTHY",
        "source_error": source_error,
        "gamma_limit": gamma_limit,
        "pages": pages,
        "total_received": len(markets),
        "preliminary_btc_candidates": preliminary,
        "selected_count": len(selected),
        "rejection_histogram": {reason: histogram.get(reason, 0) for reason in (*REJECTION_REASONS, "resolved_or_invalid_prices")},
        "raw_gamma": markets,
        "selected_condition_ids": [
            str(market.get("conditionId") or market.get("condition_id") or "") for market in selected
        ],
        "discovery_complete": source_error is None,
        "discovery_replay_verified": False,
    }
    artifact_path = None
    file_sha256 = None
    if evidence_dir is not None:
        artifact_path, file_sha256 = _write_evidence(evidence_dir, evidence)
    return {
        "status": status,
        "markets": selected,
        "evidence": evidence,
        "artifact_path": str(artifact_path) if artifact_path else None,
        "file_sha256": file_sha256,
        "file_sha256_matches": bool(artifact_path and hashlib.sha256(artifact_path.read_bytes()).hexdigest() == file_sha256),
        "discovery_complete": source_error is None,
        "discovery_replay_verified": False,
    }


def monitor_discovery_loop(*, discover: Callable[[], dict[str, Any]],
                           process: Callable[[dict[str, Any]], Any],
                           sleep: Callable[[float], None],
                           interval_s: int = 900,
                           max_cycles: int | None = None) -> list[Any]:
    """Refresh discovery before every scan; finite max_cycles is for tests."""
    results = []
    cycle = 0
    while max_cycles is None or cycle < max_cycles:
        discovery = discover()
        results.append(process(discovery))
        cycle += 1
        if max_cycles is None or cycle < max_cycles:
            sleep(interval_s)
    return results
