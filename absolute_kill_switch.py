"""
Module: absolute_kill_switch.py — SINGLE ABSOLUTE KILL SWITCH

Purpose: ONE kill switch. Absolute. Non-negotiable. No override.

The current system has MULTIPLE kill-like mechanisms:
- kill_switch.py (proposes kill_score)
- risk_kernel.py (7 checks that can block)
- SDC survivability guard
- BORG hold_bias
- OMEGA noise threshold

This creates DECISION DILUTION through SEMANTIC INFLATION.
Too many "safety" mechanisms that overlap and compete.

This module provides the SINGLE kill switch that sits ABOVE
everything else. It is the FINAL ARBITER of whether trading
is allowed at all.

ARCHITECTURE:
    There is ONE kill switch. It has ONE rule:
    
    KILL if ANY of these is TRUE:
        1. Capital survival constraint → CEASE
        2. Regime collapse detected → COLLAPSE
        3. Drawdown exceeds hard limit (mathematical death)
        4. Daily loss exceeds hard limit (circuit breaker)
        5. Manual kill activated (human override)

    When KILL is active:
        - NO new positions
        - NO position increases
        - ONLY position reductions and closes
        - This is NOT negotiable
        - There is NO "intelligence" override
        - The only way out is for conditions to improve

    When KILL is NOT active:
        - All other systems operate normally
        - This switch does NOT interfere with day-to-day decisions
        - It ONLY intervenes in existential situations

KEY PROPERTY: SIMPLICITY
    This is the "arbitro más estúpido pero más rígido".
    It doesn't think. It doesn't feel. It RULES.

Self-tests use deterministic synthetic data — no API keys required.
"""

import math
import time
from collections import deque
from typing import Optional


# ---------------------------------------------------------------------------
# Absolute Kill Switch
# ---------------------------------------------------------------------------

class AbsoluteKillSwitch:
    """ONE kill switch. Absolute. Non-negotiable.

    This is the FINAL ARBITER. If it says KILL, the system stops.
    Period. No negotiation.

    It combines multiple existential threats into a single binary:
    ALIVE or DEAD. When DEAD, no trading occurs.

    The kill switch is NOT a proposal. It is a COMMAND.
    It does NOT consult other systems. It OBSERVES state and RULES.

    Kill conditions (ANY triggers KILL):
    1. Capital survival constraint: trades_until_death < critical threshold
    2. Regime collapse: market is no longer understood
    3. Hard drawdown limit: mathematical death
    4. Daily loss limit: circuit breaker
    5. Manual kill: human override

    Release conditions (ALL must be TRUE to release):
    1. Capital survival constraint: SAFE or WARNING zone
    2. Regime collapse: NOMINAL or DRIFT alarm
    3. Drawdown: recovering (velocity negative)
    4. Manual kill: explicitly released

    Release requires EXPLICIT action. Kill is AUTOMATIC.
    This asymmetry is intentional: it's easy to get killed,
    hard to come back to life. That's the point.
    """

    def __init__(
        self,
        # ── Hard limits ──
        max_drawdown_pct: float = 0.20,      # 20% drawdown = death
        max_daily_loss_pct: float = 0.05,     # 5% daily loss = circuit breaker
        # ── Capital survival thresholds ──
        kill_trades_remaining: int = 5,       # Kill if fewer trades until death
        # ── Regime collapse thresholds ──
        kill_on_regime_collapse: bool = True,  # Kill on COLLAPSE alarm
        kill_on_regime_break: bool = False,    # Kill on BREAK alarm (usually too aggressive)
        # ── Cooldown ──
        release_cooldown_seconds: float = 300.0,  # 5 minutes minimum between kill and release
    ):
        """Initialize Absolute Kill Switch.

        Args:
            max_drawdown_pct: Maximum drawdown before automatic kill.
            max_daily_loss_pct: Maximum daily loss before circuit breaker.
            kill_trades_remaining: Kill if capital can survive fewer than this many trades.
            kill_on_regime_collapse: Whether to kill on regime COLLAPSE alarm.
            kill_on_regime_break: Whether to kill on regime BREAK alarm.
            release_cooldown_seconds: Minimum time between kill and potential release.
        """
        self.max_drawdown_pct = max_drawdown_pct
        self.max_daily_loss_pct = max_daily_loss_pct
        self.kill_trades_remaining = kill_trades_remaining
        self.kill_on_regime_collapse = kill_on_regime_collapse
        self.kill_on_regime_break = kill_on_regime_break
        self.release_cooldown_seconds = release_cooldown_seconds

        # Kill state
        self._killed = False
        self._kill_reason = ""
        self._kill_timestamp = 0
        self._manual_kill = False

        # History for audit
        self._kill_history = deque(maxlen=100)

    # ===================================================================
    # 1. EVALUATE — THE SINGLE RULE
    # ===================================================================

    def evaluate(
        self,
        current_drawdown_pct: float,
        daily_pnl_pct: float,
        trades_until_death: float = float('inf'),
        capital_zone: str = "SAFE",
        regime_alarm: str = "NOMINAL",
    ) -> dict:
        """Evaluate the kill switch rule.

        This is THE function. It takes the current system state
        and produces a binary: ALIVE or KILLED.

        MONOTONIC: if any input worsens, the kill state can only
        go from ALIVE to KILLED, never the reverse in a single call.

        Args:
            current_drawdown_pct: Current drawdown as percentage.
            daily_pnl_pct: Today's PnL as percentage.
            trades_until_death: From CapitalSurvivalConstraint.
            capital_zone: From CapitalSurvivalConstraint (SAFE/WARNING/CRITICAL/TERMINAL).
            regime_alarm: From RegimeCollapseDetector (NOMINAL/DRIFT/BREAK/COLLAPSE).

        Returns:
            Dict with kill state and full details.
        """
        now = time.time() * 1000
        kill_triggered = False
        kill_reasons = []

        # ── CHECK 1: Hard drawdown limit ──
        if current_drawdown_pct >= self.max_drawdown_pct:
            kill_triggered = True
            kill_reasons.append(
                f"HARD_DRAWDOWN: {current_drawdown_pct:.2%} >= {self.max_drawdown_pct:.2%}"
            )

        # ── CHECK 2: Daily loss circuit breaker ──
        if daily_pnl_pct <= -self.max_daily_loss_pct:
            kill_triggered = True
            kill_reasons.append(
                f"DAILY_CIRCUIT_BREAKER: {daily_pnl_pct:.2%} <= -{self.max_daily_loss_pct:.2%}"
            )

        # ── CHECK 3: Capital survival constraint ──
        if trades_until_death < self.kill_trades_remaining:
            kill_triggered = True
            kill_reasons.append(
                f"CAPITAL_SURVIVAL: {trades_until_death:.1f} trades until death "
                f"< {self.kill_trades_remaining} threshold"
            )

        if capital_zone in ("TERMINAL", "CRITICAL"):
            kill_triggered = True
            kill_reasons.append(
                f"CAPITAL_ZONE_{capital_zone}: system in existential danger"
            )

        # ── CHECK 4: Regime collapse ──
        if self.kill_on_regime_collapse and regime_alarm == "COLLAPSE":
            kill_triggered = True
            kill_reasons.append("REGIME_COLLAPSE: market is no longer understood")

        if self.kill_on_regime_break and regime_alarm == "BREAK":
            kill_triggered = True
            kill_reasons.append("REGIME_BREAK: market structure has broken")

        # ── CHECK 5: Manual kill ──
        if self._manual_kill:
            kill_triggered = True
            kill_reasons.append("MANUAL_KILL: activated by human operator")

        # ── APPLY KILL ──
        if kill_triggered and not self._killed:
            self._killed = True
            self._kill_timestamp = now
            self._kill_reason = " | ".join(kill_reasons)
            self._kill_history.append({
                "timestamp": now,
                "event": "KILLED",
                "reasons": kill_reasons,
            })

        # ── CHECK RELEASE CONDITIONS ──
        if self._killed and not self._manual_kill:
            # Can we release? ALL conditions must be met:
            elapsed_since_kill = (now - self._kill_timestamp) / 1000.0
            cooldown_passed = elapsed_since_kill >= self.release_cooldown_seconds

            drawdown_safe = current_drawdown_pct < self.max_drawdown_pct * 0.5
            daily_pnl_safe = daily_pnl_pct > -self.max_daily_loss_pct * 0.5
            capital_safe = capital_zone in ("SAFE", "WARNING") and trades_until_death > self.kill_trades_remaining * 2
            regime_safe = regime_alarm in ("NOMINAL", "DRIFT")

            can_release = (
                cooldown_passed
                and drawdown_safe
                and daily_pnl_safe
                and capital_safe
                and regime_safe
            )

            if can_release:
                self._killed = False
                self._kill_reason = ""
                self._kill_history.append({
                    "timestamp": now,
                    "event": "RELEASED",
                    "reasons": [
                        f"cooldown_passed ({elapsed_since_kill:.0f}s)",
                        f"drawdown_safe ({current_drawdown_pct:.2%})",
                        f"daily_pnl_safe ({daily_pnl_pct:.2%})",
                        f"capital_safe (zone={capital_zone}, trades={trades_until_death:.0f})",
                        f"regime_safe (alarm={regime_alarm})",
                    ],
                })

        return {
            "killed": self._killed,
            "kill_reason": self._kill_reason if self._killed else "",
            "kill_reasons": kill_reasons if self._killed else [],
            "manual_kill": self._manual_kill,
            "timestamp": now,
            "cooldown_remaining_seconds": max(
                0.0,
                self.release_cooldown_seconds - (now - self._kill_timestamp) / 1000.0
            ) if self._killed else 0.0,
        }

    # ===================================================================
    # 2. MANUAL KILL / RELEASE
    # ===================================================================

    def activate_manual_kill(self, reason: str = "manual"):
        """Manually activate the kill switch.

        This is the EMERGENCY STOP. Use when you need to
        immediately cease all trading regardless of conditions.

        Once activated, it can ONLY be released by calling
        release_manual_kill(). Automatic release is disabled.

        Args:
            reason: Explanation for the manual kill.
        """
        self._manual_kill = True
        self._killed = True
        self._kill_timestamp = time.time() * 1000
        self._kill_reason = f"MANUAL: {reason}"
        self._kill_history.append({
            "timestamp": self._kill_timestamp,
            "event": "MANUAL_KILL",
            "reasons": [f"MANUAL: {reason}"],
        })

    def release_manual_kill(self, reason: str = "manual_release"):
        """Release the manual kill.

        This requires EXPLICIT action. The system does NOT
        auto-release from a manual kill.

        Args:
            reason: Explanation for the release.
        """
        self._manual_kill = False
        self._killed = False
        self._kill_reason = ""
        self._kill_history.append({
            "timestamp": time.time() * 1000,
            "event": "MANUAL_RELEASE",
            "reasons": [f"MANUAL_RELEASE: {reason}"],
        })

    # ===================================================================
    # 3. STATE INSPECTION
    # ===================================================================

    def is_killed(self) -> bool:
        """Check if the kill switch is currently active."""
        return self._killed

    def get_state(self) -> dict:
        """Get full kill switch state for dashboard."""
        return {
            "killed": self._killed,
            "manual_kill": self._manual_kill,
            "kill_reason": self._kill_reason,
            "history_count": len(self._kill_history),
        }

    def get_history(self, limit: int = 10) -> list:
        """Get recent kill switch history for audit."""
        return list(self._kill_history)[-limit:]


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("absolute_kill_switch.py — Self-Test")
    print("=" * 60)

    aks = AbsoluteKillSwitch(
        max_drawdown_pct=0.20,
        max_daily_loss_pct=0.05,
        kill_trades_remaining=5,
        release_cooldown_seconds=0.0,  # No cooldown for tests
    )

    # ── Test 1: Normal state → alive ────────────────────────────────
    print("\n[Test 1] Normal state → alive...")
    result = aks.evaluate(
        current_drawdown_pct=0.05,
        daily_pnl_pct=0.01,
        trades_until_death=100,
        capital_zone="SAFE",
        regime_alarm="NOMINAL",
    )
    assert not result["killed"], "Normal state should be alive"
    print(f"  killed={result['killed']}")
    print(f"  ✓ Normal state → alive")

    # ── Test 2: Hard drawdown → killed ──────────────────────────────
    print("\n[Test 2] Hard drawdown → killed...")
    aks2 = AbsoluteKillSwitch(max_drawdown_pct=0.20, release_cooldown_seconds=0.0)
    result = aks2.evaluate(
        current_drawdown_pct=0.22,  # > 20%
        daily_pnl_pct=0.0,
        trades_until_death=100,
        capital_zone="SAFE",
        regime_alarm="NOMINAL",
    )
    assert result["killed"], "Drawdown > 20% should kill"
    assert any("HARD_DRAWDOWN" in r for r in result["kill_reasons"])
    print(f"  killed={result['killed']}, reasons={result['kill_reasons']}")
    print(f"  ✓ Hard drawdown → killed")

    # ── Test 3: Daily loss circuit breaker → killed ─────────────────
    print("\n[Test 3] Daily loss circuit breaker → killed...")
    aks3 = AbsoluteKillSwitch(max_daily_loss_pct=0.05, release_cooldown_seconds=0.0)
    result = aks3.evaluate(
        current_drawdown_pct=0.0,
        daily_pnl_pct=-0.06,  # > 5% loss
        trades_until_death=100,
        capital_zone="SAFE",
        regime_alarm="NOMINAL",
    )
    assert result["killed"], "Daily loss > 5% should kill"
    assert any("DAILY_CIRCUIT_BREAKER" in r for r in result["kill_reasons"])
    print(f"  killed={result['killed']}, reasons={result['kill_reasons']}")
    print(f"  ✓ Daily loss circuit breaker → killed")

    # ── Test 4: Capital survival constraint → killed ────────────────
    print("\n[Test 4] Capital survival constraint → killed...")
    aks4 = AbsoluteKillSwitch(kill_trades_remaining=5, release_cooldown_seconds=0.0)
    result = aks4.evaluate(
        current_drawdown_pct=0.10,
        daily_pnl_pct=-0.02,
        trades_until_death=3,  # < 5
        capital_zone="CRITICAL",
        regime_alarm="NOMINAL",
    )
    assert result["killed"], "Trades until death < 5 should kill"
    print(f"  killed={result['killed']}, reasons={result['kill_reasons']}")
    print(f"  ✓ Capital survival constraint → killed")

    # ── Test 5: Regime collapse → killed ────────────────────────────
    print("\n[Test 5] Regime collapse → killed...")
    aks5 = AbsoluteKillSwitch(kill_on_regime_collapse=True, release_cooldown_seconds=0.0)
    result = aks5.evaluate(
        current_drawdown_pct=0.05,
        daily_pnl_pct=0.01,
        trades_until_death=100,
        capital_zone="SAFE",
        regime_alarm="COLLAPSE",
    )
    assert result["killed"], "Regime collapse should kill"
    assert any("REGIME_COLLAPSE" in r for r in result["kill_reasons"])
    print(f"  killed={result['killed']}, reasons={result['kill_reasons']}")
    print(f"  ✓ Regime collapse → killed")

    # ── Test 6: Manual kill ─────────────────────────────────────────
    print("\n[Test 6] Manual kill...")
    aks6 = AbsoluteKillSwitch(release_cooldown_seconds=0.0)
    aks6.activate_manual_kill("emergency test")
    assert aks6.is_killed()
    result = aks6.evaluate(
        current_drawdown_pct=0.0,
        daily_pnl_pct=0.0,
        trades_until_death=1000,
        capital_zone="SAFE",
        regime_alarm="NOMINAL",
    )
    assert result["killed"], "Manual kill should override everything"
    # Release
    aks6.release_manual_kill("test complete")
    assert not aks6.is_killed()
    print(f"  ✓ Manual kill activates and releases correctly")

    # ── Test 7: Monotonicity — can't go from killed to alive in one call ──
    print("\n[Test 7] Kill is sticky (with cooldown)...")
    aks7 = AbsoluteKillSwitch(release_cooldown_seconds=300.0)
    # Trigger kill
    aks7.evaluate(0.22, 0.0, 100, "SAFE", "NOMINAL")
    assert aks7.is_killed()
    # Even if conditions improve, kill stays during cooldown
    result = aks7.evaluate(0.01, 0.01, 100, "SAFE", "NOMINAL")
    assert result["killed"], "Kill should persist during cooldown"
    print(f"  killed after improvement={result['killed']}, cooldown={result['cooldown_remaining_seconds']:.0f}s")
    print(f"  ✓ Kill is sticky during cooldown")

    # ── Test 8: Release when conditions improve (no cooldown) ───────
    print("\n[Test 8] Release when conditions improve (no cooldown)...")
    aks8 = AbsoluteKillSwitch(
        max_drawdown_pct=0.20,
        kill_trades_remaining=5,
        release_cooldown_seconds=0.0,
    )
    # Trigger kill via critical zone
    aks8.evaluate(0.10, -0.02, 3, "CRITICAL", "NOMINAL")
    assert aks8.is_killed()
    # Conditions improve significantly
    result = aks8.evaluate(0.05, 0.01, 50, "SAFE", "NOMINAL")
    print(f"  killed after improvement={result['killed']}")
    # Should be released because all conditions are safe
    assert not result["killed"], "Should release when conditions improve"
    print(f"  ✓ Release when conditions improve")

    # ── Test 9: DRIFT does not kill ─────────────────────────────────
    print("\n[Test 9] DRIFT alarm does not kill (only COLLAPSE does)...")
    aks9 = AbsoluteKillSwitch(kill_on_regime_collapse=True, kill_on_regime_break=False)
    result = aks9.evaluate(0.05, 0.01, 100, "SAFE", "DRIFT")
    assert not result["killed"], "DRIFT should not kill"
    print(f"  killed={result['killed']}")
    print(f"  ✓ DRIFT alarm does not trigger kill")

    # ── Test 10: History tracking ───────────────────────────────────
    print("\n[Test 10] History tracking...")
    aks10 = AbsoluteKillSwitch(release_cooldown_seconds=0.0)
    aks10.evaluate(0.22, 0.0, 100, "SAFE", "NOMINAL")  # Kill
    aks10.evaluate(0.01, 0.01, 100, "SAFE", "NOMINAL")  # Release
    history = aks10.get_history(limit=5)
    events = [h["event"] for h in history]
    print(f"  history events: {events}")
    assert "KILLED" in events
    assert "RELEASED" in events
    print(f"  ✓ History tracking works")

    print("\n" + "=" * 60)
    print("All self-tests PASSED")
    print("=" * 60)
