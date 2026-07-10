"""
SENECIO — Admin authentication for control plane endpoints.
FAIL-CLOSED: if SENECIO_ADMIN_API_KEY is not set, all admin endpoints reject.
"""
from __future__ import annotations

import hmac
import os

from fastapi import Header, HTTPException, status


def _admin_key() -> str:
    value = os.environ.get("SENECIO_ADMIN_API_KEY", "")
    if not value:
        raise RuntimeError("SENECIO_ADMIN_API_KEY is not configured")
    return value


async def require_admin(
    x_senecio_admin_key: str | None = Header(default=None),
) -> None:
    expected = _admin_key()
    if (
        not x_senecio_admin_key
        or not hmac.compare_digest(x_senecio_admin_key, expected)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
        )
