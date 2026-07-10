"""
SENECIO H-011 V3 — Field-level evidence provenance.

Every relevant data point can answer: where it came from, when it was
observed, what raw event contains it, what transform produced it, and
whether a fallback was used.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from polymarket.control_plane.semantic_status import DataOrigin


@dataclass(frozen=True)
class FieldProvenance:
    """Provenance record for a single field."""
    field_path: str
    source_id: str
    origin: DataOrigin
    source_ts: str | None
    received_ts: str
    raw_event_hash: str | None
    parent_hashes: tuple[str, ...]
    transform_id: str
    transform_version: str
    code_sha: str
    config_sha: str
    fallback_used: bool
    provenance_hash: str

    def to_dict(self) -> dict:
        return {
            "field_path": self.field_path,
            "source_id": self.source_id,
            "origin": self.origin.value,
            "source_ts": self.source_ts,
            "received_ts": self.received_ts,
            "raw_event_hash": self.raw_event_hash,
            "parent_hashes": list(self.parent_hashes),
            "transform_id": self.transform_id,
            "transform_version": self.transform_version,
            "code_sha": self.code_sha,
            "config_sha": self.config_sha,
            "fallback_used": self.fallback_used,
            "provenance_hash": self.provenance_hash,
        }


def build_field_provenance(
    *,
    field_path: str,
    source_id: str,
    origin: DataOrigin,
    source_ts: str | None,
    received_ts: str,
    raw_event_hash: str | None = None,
    parent_hashes: tuple[str, ...] = (),
    transform_id: str = "identity",
    transform_version: str = "v1",
    code_sha: str = "",
    config_sha: str = "",
    fallback_used: bool = False,
) -> FieldProvenance:
    """Build a FieldProvenance with auto-computed hash."""
    hash_input = json.dumps({
        "field_path": field_path,
        "source_id": source_id,
        "origin": origin.value,
        "source_ts": source_ts,
        "received_ts": received_ts,
        "raw_event_hash": raw_event_hash,
        "parent_hashes": list(parent_hashes),
        "transform_id": transform_id,
        "transform_version": transform_version,
        "code_sha": code_sha,
        "config_sha": config_sha,
        "fallback_used": fallback_used,
    }, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    provenance_hash = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()

    return FieldProvenance(
        field_path=field_path,
        source_id=source_id,
        origin=origin,
        source_ts=source_ts,
        received_ts=received_ts,
        raw_event_hash=raw_event_hash,
        parent_hashes=parent_hashes,
        transform_id=transform_id,
        transform_version=transform_version,
        code_sha=code_sha,
        config_sha=config_sha,
        fallback_used=fallback_used,
        provenance_hash=provenance_hash,
    )
