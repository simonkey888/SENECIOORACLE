"""Validation-only bootstrap for the hostile H-011 publisher audit.

This file exists only on the temporary validation branch. It applies the
one-shot hardening inside the GitHub Actions checkout before pytest collects
any H-011 module. It is intentionally idempotent across multiple pytest
invocations in the same runner workspace.
"""
from __future__ import annotations

import runpy
from pathlib import Path


_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_TARGET = _REPOSITORY_ROOT / "polymarket" / "h011_v3_raw_transaction.py"
_PRIMARY_PATCHER = (
    _REPOSITORY_ROOT / "tools" / "apply_h011_publisher_audit_patch.py"
)
_REGRESSION_PATCHER = (
    _REPOSITORY_ROOT / "tools" / "apply_h011_publisher_audit_regression_patch.py"
)
_PRIMARY_SENTINEL = (
    "Create and durably verify a marker without replacing any destination."
)
_REGRESSION_SENTINEL = "short marker write"


def _apply_missing_patch(
    *, patcher: Path, sentinel: str, description: str
) -> None:
    source = _TARGET.read_text(encoding="utf-8")
    if sentinel in source:
        return
    if not patcher.is_file():
        raise RuntimeError(
            f"{description} patch is absent and its source sentinel was not found"
        )
    runpy.run_path(str(patcher), run_name="__main__")
    hardened = _TARGET.read_text(encoding="utf-8")
    if sentinel not in hardened:
        raise RuntimeError(f"{description} patch did not materialize")


def pytest_configure() -> None:
    _apply_missing_patch(
        patcher=_PRIMARY_PATCHER,
        sentinel=_PRIMARY_SENTINEL,
        description="publisher audit",
    )
    _apply_missing_patch(
        patcher=_REGRESSION_PATCHER,
        sentinel=_REGRESSION_SENTINEL,
        description="publisher regression correction",
    )
