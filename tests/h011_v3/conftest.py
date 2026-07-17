"""Validation-only bootstrap for the hostile H-011 publisher audit.

This file exists only on the temporary validation branch. It applies the
one-shot hardening inside GitHub Actions before pytest collects any H-011
module. It is idempotent across multiple pytest invocations in one checkout.
"""
from __future__ import annotations

import runpy
from pathlib import Path


_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_SOURCE_TARGET = (
    _REPOSITORY_ROOT / "polymarket" / "h011_v3_raw_transaction.py"
)
_TEST_TARGET = (
    _REPOSITORY_ROOT
    / "tests"
    / "h011_v3"
    / "test_h011_v3_publish_raw_scan.py"
)
_PRIMARY_PATCHER = (
    _REPOSITORY_ROOT / "tools" / "apply_h011_publisher_audit_patch.py"
)
_REGRESSION_PATCHER = (
    _REPOSITORY_ROOT / "tools" / "apply_h011_publisher_audit_regression_patch.py"
)
_PRIMARY_SENTINEL = (
    "Create and durably verify a marker without replacing any destination."
)
_REGRESSION_SENTINEL = "assert injected is True"


def _apply_missing_patch(
    *,
    target: Path,
    patcher: Path,
    sentinel: str,
    description: str,
) -> None:
    current = target.read_text(encoding="utf-8")
    if sentinel in current:
        return
    if not patcher.is_file():
        raise RuntimeError(
            f"{description} patch is absent and its target sentinel was not found"
        )
    runpy.run_path(str(patcher), run_name="__main__")
    patched = target.read_text(encoding="utf-8")
    if sentinel not in patched:
        raise RuntimeError(f"{description} patch did not materialize")


def pytest_configure() -> None:
    _apply_missing_patch(
        target=_SOURCE_TARGET,
        patcher=_PRIMARY_PATCHER,
        sentinel=_PRIMARY_SENTINEL,
        description="publisher audit",
    )
    _apply_missing_patch(
        target=_TEST_TARGET,
        patcher=_REGRESSION_PATCHER,
        sentinel=_REGRESSION_SENTINEL,
        description="publisher regression correction",
    )
