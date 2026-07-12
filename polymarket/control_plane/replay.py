"""Deterministic H-011 raw bundle manifests and semantic replay."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def config_sha(config: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(config)).hexdigest()


def semantic_material(bundle: dict[str, Any]) -> dict[str, Any]:
    """Remove persistence timestamps and artifact-only fields."""
    return {
        "schema_version": bundle["schema_version"],
        "scan_id": bundle["scan_id"],
        "code_sha": bundle["code_sha"],
        "config_sha": bundle["config_sha"],
        "config": bundle["config"],
        "gamma": bundle["gamma"],
        "trades": bundle["trades"],
        "books": bundle["books"],
        "fees": bundle["fees"],
        "records": bundle["records"],
    }


def semantic_hash(bundle: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(semantic_material(bundle))).hexdigest()


def write_bundle(path: Path, *, scan_id: str, code_sha: str, config: dict[str, Any],
                 gamma: list[dict], trades: dict[str, list[dict]],
                 books: dict[str, dict], fees: dict[str, Any],
                 records: list[dict]) -> dict[str, Any]:
    normalized_config = json.loads(json.dumps(config, sort_keys=True, separators=(",", ":")))
    bundle = {
        "schema_version": "h011-v3-raw-bundle-v1",
        "scan_id": scan_id,
        "code_sha": code_sha,
        "config_sha": config_sha(normalized_config),
        "config": normalized_config,
        "gamma": gamma,
        "trades": trades,
        "books": books,
        "fees": fees,
        "records": records,
    }
    bundle["semantic_hash"] = semantic_hash(bundle)
    payload = canonical_bytes({**bundle, "artifact_hash": ""})
    bundle["artifact_hash"] = hashlib.sha256(payload).hexdigest()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(bundle))
    return bundle


def replay_bundle(path: Path) -> dict[str, Any]:
    bundle = json.loads(path.read_bytes())
    calculated = semantic_hash(bundle)
    artifact_material = dict(bundle)
    artifact_material["artifact_hash"] = ""
    artifact_calculated = hashlib.sha256(canonical_bytes(artifact_material)).hexdigest()
    return {
        "scan_id": bundle.get("scan_id"),
        "semantic_hash": calculated,
        "semantic_hash_matches": calculated == bundle.get("semantic_hash"),
        "artifact_hash_present": bool(bundle.get("artifact_hash")),
        "artifact_hash_matches": artifact_calculated == bundle.get("artifact_hash"),
        "config_sha_matches": config_sha(bundle.get("config", {})) == bundle.get("config_sha"),
        "raw_complete": all(bundle.get(k) is not None for k in ("gamma", "trades", "books", "fees")),
        "records": len(bundle.get("records", [])),
    }
