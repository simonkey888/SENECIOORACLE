"""Validation-only bootstrap for the hostile H-011 publisher audit.

This file exists only on the temporary validation branch. It applies the
one-shot source hardening inside the GitHub Actions checkout before pytest
collects any H-011 module. It is intentionally idempotent across multiple
pytest invocations in the same runner workspace.
"""
from __future__ import annotations

import runpy
from pathlib import Path


_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_TARGET = _REPOSITORY_ROOT / "polymarket" / "h011_v3_raw_transaction.py"
_PATCHER = _REPOSITORY_ROOT / "tools" / "apply_h011_publisher_audit_patch.py"
_PATCH_SENTINEL = "Create and durably verify a marker without replacing any destination."


def pytest_configure() -> None:
    source = _TARGET.read_text(encoding="utf-8")
    if _PATCH_SENTINEL in source:
        return
    if not _PATCHER.is_file():
        raise RuntimeError(
            "publisher audit patch is absent and the hardened source sentinel "
            "was not found"
        )
    runpy.run_path(str(_PATCHER), run_name="__main__")
    hardened = _TARGET.read_text(encoding="utf-8")
    if _PATCH_SENTINEL not in hardened:
        raise RuntimeError("publisher audit patch did not materialize hardening")
