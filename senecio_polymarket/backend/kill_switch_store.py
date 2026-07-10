"""
SENECIO — Kill switch persistent state with fail-closed semantics.
Stores kill switch state in an atomic file on the persistent volume.
If the file is corrupt or unreadable, the kill switch defaults to ACTIVE (fail-closed).
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import logging

log = logging.getLogger(__name__)

CONTROL_STORE_PATH = Path(
    os.environ.get(
        "SENECIO_CONTROL_STORE",
        "/app/polymarket/results/control_state.json",
    )
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_control_state() -> dict:
    """Load kill switch state. FAIL-CLOSED on any error."""
    try:
        if not CONTROL_STORE_PATH.exists():
            log.warning("Control store not found — kill switch defaulting to ACTIVE (fail-closed)")
            return {
                "kill_switch_active": True,
                "kill_switch_reason": "control_store_missing",
                "kill_switch_set_at": _now_iso(),
                "daily_pnl_pct": 0.0,
                "drawdown_pct": 0.0,
                "loss_streak": 0,
            }
        data = json.loads(CONTROL_STORE_PATH.read_text(encoding="utf-8"))
        # Fail-closed: if any required field is missing, activate kill switch
        if "kill_switch_active" not in data:
            log.error("Control store corrupt: missing kill_switch_active — FAILING CLOSED")
            return {
                "kill_switch_active": True,
                "kill_switch_reason": "control_store_corrupt",
                "kill_switch_set_at": _now_iso(),
                "daily_pnl_pct": 0.0,
                "drawdown_pct": 0.0,
                "loss_streak": 0,
            }
        return data
    except (json.JSONDecodeError, OSError) as e:
        log.error("Control store read error: %s — FAILING CLOSED", e)
        return {
            "kill_switch_active": True,
            "kill_switch_reason": f"control_store_error: {e}",
            "kill_switch_set_at": _now_iso(),
            "daily_pnl_pct": 0.0,
            "drawdown_pct": 0.0,
            "loss_streak": 0,
        }


def save_control_state(state: dict) -> None:
    """Atomically write control state to persistent volume."""
    CONTROL_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write: write to temp file, then rename
    fd, tmp_path = tempfile.mkstemp(
        dir=str(CONTROL_STORE_PATH.parent),
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        os.rename(tmp_path, str(CONTROL_STORE_PATH))
        log.info("Control state saved to %s", CONTROL_STORE_PATH)
    except OSError as e:
        log.error("Failed to save control state: %s", e)
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def activate_kill_switch(reason: str = "manual") -> dict:
    """Activate the kill switch and persist state."""
    state = load_control_state()
    state["kill_switch_active"] = True
    state["kill_switch_reason"] = reason
    state["kill_switch_set_at"] = _now_iso()
    save_control_state(state)
    log.warning("KILL SWITCH ACTIVATED: %s", reason)
    return state


def reset_kill_switch(
    reason: str = "manual reset",
    max_daily_loss_pct: float = 5.0,
    max_drawdown_pct: float = 15.0,
) -> bool:
    """
    Attempt to reset the kill switch.
    REJECTED if active risk conditions (daily breach or drawdown breach) are still in effect.
    Does NOT clear: drawdown, daily loss, cooldown, or loss streak.
    Returns True if reset was accepted, False if rejected.
    """
    state = load_control_state()

    daily_breach = state.get("daily_pnl_pct", 0.0) <= -max_daily_loss_pct
    drawdown_breach = state.get("drawdown_pct", 0.0) >= max_drawdown_pct

    if daily_breach or drawdown_breach:
        log.error(
            "KILL SWITCH RESET REJECTED: active risk condition "
            "daily_breach=%s drawdown_breach=%s",
            daily_breach,
            drawdown_breach,
        )
        return False

    state["kill_switch_active"] = False
    state["kill_switch_reason"] = ""
    state["kill_switch_set_at"] = None
    save_control_state(state)
    log.warning("KILL SWITCH RESET: %s", reason)
    return True


def is_kill_switch_active() -> bool:
    """Check if kill switch is currently active. FAIL-CLOSED."""
    state = load_control_state()
    return state.get("kill_switch_active", True)
