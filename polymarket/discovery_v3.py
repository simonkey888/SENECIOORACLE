"""Auditable, refreshable and replayable BTC market discovery for H-011 V3."""
from __future__ import annotations

import gzip
import hashlib
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

import httpx

GAMMA_BASE = "https://gamma-api.polymarket.com"
DISCOVERY_VERSION = "h011-v3-discovery-v2"
REJECTION_REASONS = (
    "missing_condition_id", "btc_event_identity_unproven", "resolution_rule_unproven",
    "window_timestamps_unproven", "window_duration_mismatch",
    "up_down_token_identity_unproven",
)
ALL_REJECTION_REASONS = (*REJECTION_REASONS, "resolved_or_invalid_prices")


class GammaDiscoveryClient(Protocol):
    def fetch_pages(self, limit: int) -> dict[str, Any]: ...


class HttpxGammaDiscoveryClient:
    """Paginate active Gamma markets and report whether the source was exhausted."""

    def __init__(self, *, page_size: int = 100, transport=None):
        self.page_size = page_size
        self.transport = transport

    def fetch_pages(self, limit: int) -> dict[str, Any]:
        markets: list[dict] = []
        pages: list[dict] = []
        source_exhausted = False
        with httpx.Client(timeout=30.0, transport=self.transport) as client:
            for offset in range(0, limit, self.page_size):
                requested_limit = min(self.page_size, limit - offset)
                requested_at = datetime.now(timezone.utc).isoformat()
                response = client.get(f"{GAMMA_BASE}/markets", params={
                    "limit": requested_limit, "offset": offset,
                    "active": "true", "closed": "false",
                })
                received_at = datetime.now(timezone.utc).isoformat()
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, list):
                    raise ValueError("Gamma /markets response is not a list")
                pages.append({
                    "offset": offset, "limit": requested_limit,
                    "requested_at": requested_at, "received_at": received_at,
                    "status_code": response.status_code, "count": len(payload),
                })
                markets.extend(payload)
                if len(payload) < requested_limit:
                    source_exhausted = True
                    break
        limit_reached = not source_exhausted and len(markets) >= limit
        return {
            "markets": markets, "pages": pages,
            "source_exhausted": source_exhausted,
            "limit_reached": limit_reached,
            "next_offset": len(markets) if limit_reached else None,
        }


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


def _select(raw_gamma: list[dict], window_s: int, max_markets: int) -> dict[str, Any]:
    from h011_v3_pipeline import validate_btc_market_identity
    histogram = Counter()
    selected: list[dict] = []
    preliminary = 0
    for market in raw_gamma:
        preliminary += int(_preliminary_btc(market))
        ok, reasons = validate_btc_market_identity(market, window_s)
        if not ok:
            histogram.update(reasons)
            continue
        if _resolved_extreme(market):
            histogram["resolved_or_invalid_prices"] += 1
            continue
        selected.append({**market, "_validated_window_s": window_s})
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


def replay_discovery(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    evidence = json.loads(gzip.decompress(path.read_bytes()))
    recalculated = _select(evidence["raw_gamma"], evidence["window_s"], evidence["max_markets"])
    expected_status = evidence["status"]
    if evidence.get("source_error"):
        replay_status = "DISCOVERY_SOURCE_FAILED"
    elif evidence.get("limit_reached"):
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
        "version_matches": evidence.get("discovery_version") == DISCOVERY_VERSION,
    }
    return {**matches, "discovery_replay_verified": all(matches.values())}


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
    selected_data = _select(markets, config.window_s, max_markets) if source_error is None else {
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
        replay = replay_discovery(artifact_path)
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
