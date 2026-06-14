"""
Module: entropy_guard.py — ENTROPY GUARD (RISK GOVERNOR COMPONENT)

MYTHOS: "Is the system going CRAZY? If yes → REDUCE. If very crazy → KILL."

This is one of the 3 components of the RISK GOVERNOR:
    1. absolute_kill_switch     — existential threats
    2. capital_survival_forward_model (CSC) — capital trajectory
    3. entropy_guard (THIS)     — decision stability monitoring

The entropy guard monitors whether the system's decisions are becoming
chaotic, flip-flopping, or otherwise unstable. Unlike the kill switch
(which reacts to CAPITAL threats) and CSC (which reacts to TRAJECTORY
threats), the entropy guard reacts to BEHAVIORAL threats.

KEY QUESTION: "Is the system making STABLE decisions?"

INDICATORS OF ENTROPY INSTABILITY:
    1. Noise level swinging wildly (0.3 one tick, 0.8 the next)
    2. Direction flipping rapidly (LONG→SHORT→LONG→SHORT)
    3. Conviction oscillating (0.6→0.1→0.7→0.05)
    4. Excessive trading (overtrading)
    5. Excessive holding (paralysis)

OUTPUT:
    ALLOW   — decisions are stable, proceed normally
    REDUCE  — decisions are somewhat unstable, reduce position size
    KILL    — decisions are chaotic, cease trading

KEY PROPERTY: MONOTONICITY
    If entropy increases → guard action becomes MORE conservative.
    There is NO override. The guard does not think. It MEASURES.

DECISION RULES:
    entropy_index < 0.3  → ALLOW (stable)
    entropy_index < 0.6  → REDUCE (unstable)
    entropy_index >= 0.6 → KILL (chaotic)
"""

import math
from collections import deque
from typing import Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


# ---------------------------------------------------------------------------
# Entropy Guard
# ---------------------------------------------------------------------------

class EntropyGuard:
    """Monitor decision stability and guard against entropy chaos.

    The entropy guard is the BEHAVIORAL risk governor. While the
    kill switch guards against capital death and CSC guards against
    trajectory death, the entropy guard guards against DECISION death.

    Decision death is when the system's decisions become so chaotic
    that they are essentially random. This is WORSE than losing money
    in a predictable way, because:
    1. You can't learn from random decisions
    2. You can't fix random decisions
    3. Random decisions indicate the model has lost its anchor

    The entropy guard measures:
    1. NOISE VARIANCE — is noise swinging wildly?
    2. DIRECTION FLIP RATE — is the system flip-flopping?
    3. CONVICTION VOLATILITY — is conviction oscillating?
    4. OVERTRADING INDEX — is the system trading too much?
    5. PARALYSIS INDEX — is the system unable to decide?

    Output: ALLOW / REDUCE / KILL + size_multiplier + entropy_index
    """

    def __init__(
        self,
        # ── Windows ──
        decision_window: int = 100,      # Recent decisions for analysis
        # ── Thresholds ──
        allow_threshold: float = 0.30,    # Below this → ALLOW
        reduce_threshold: float = 0.60,   # Below this → REDUCE, above → KILL
        # ── Overtrading ──
        overtrade_threshold: float = 0.5, # More than 50% action = overtrading
        # ── Paralysis ──
        paralysis_threshold: float = 0.95, # More than 95% HOLD = paralysis
    ):
        """Initialize Entropy Guard.

        Args:
            decision_window: Window for stability analysis.
            allow_threshold: Entropy index below this → ALLOW.
            reduce_threshold: Entropy index below this → REDUCE, else KILL.
            overtrade_threshold: Action ratio above this → overtrading.
            paralysis_threshold: HOLD ratio above this → paralysis.
        """
        self.decision_window = decision_window
        self.allow_threshold = allow_threshold
        self.reduce_threshold = reduce_threshold
        self.overtrade_threshold = overtrade_threshold
        self.paralysis_threshold = paralysis_threshold

        # ── Data buffers ──
        self._noises = deque(maxlen=decision_window)
        self._convictions = deque(maxlen=decision_window)
        self._actions = deque(maxlen=decision_window)
        self._sides = deque(maxlen=decision_window)

        # ── State ──
        self._entropy_index = 0.0
        self._last_verdict = "ALLOW"
        self._last_size_multiplier = 1.0

    # ===================================================================
    # 1. RECORD DECISION
    # ===================================================================

    def record_decision(self, action: str, side: str,
                        noise: float, conviction: float):
        """Record a pipeline decision for entropy analysis.

        Args:
            action: HOLD or EXECUTE.
            side: LONG, SHORT, or None.
            noise: Noise level from probability field.
            conviction: Conviction from probability field.
        """
        self._noises.append(noise)
        self._convictions.append(conviction)
        self._actions.append(action)
        self._sides.append(side)

    # ===================================================================
    # 2. COMPUTE ENTROPY INDEX
    # ===================================================================

    def compute_entropy_index(self) -> dict:
        """Compute the composite entropy index.

        The entropy index is [0, 1] where:
            0 = perfectly stable decisions
            1 = completely chaotic decisions

        Components (all [0, 1], higher = worse):
            1. noise_variance    — is noise swinging wildly?
            2. flip_flop_rate    — is direction changing rapidly?
            3. conviction_volatility — is conviction oscillating?
            4. overtrade_index   — is the system trading too much?
            5. paralysis_index   — is the system unable to decide?

        Returns:
            Dict with entropy index and component breakdown.
        """
        if len(self._noises) < 5:
            return {
                "entropy_index": 0.0,
                "verdict": "ALLOW",
                "components": {},
                "reason": "insufficient_data",
            }

        # ── 1. Noise variance ──
        noises = list(self._noises)
        noise_mean = sum(noises) / len(noises)
        noise_var = sum((n - noise_mean) ** 2 for n in noises) / len(noises)
        noise_std = math.sqrt(noise_var) if noise_var > 0 else 0
        # Normalize: variance > 0.05 is very unstable
        noise_stability = _clamp(noise_var / 0.05, 0.0, 1.0)

        # ── 2. Direction flip-flop rate ──
        sides = [s for s in self._sides if s is not None]
        flip_flops = 0
        for i in range(1, len(sides)):
            if sides[i] != sides[i - 1]:
                flip_flops += 1
        flip_flop_rate = flip_flops / max(len(sides) - 1, 1)
        # flip_flop_rate > 0.7 = very chaotic
        flip_flop_stability = _clamp(flip_flop_rate / 0.7, 0.0, 1.0)

        # ── 3. Conviction volatility ──
        convictions = list(self._convictions)
        if len(convictions) >= 2:
            conv_changes = [abs(convictions[i] - convictions[i-1])
                           for i in range(1, len(convictions))]
            avg_change = sum(conv_changes) / len(conv_changes)
            # avg_change > 0.3 = very volatile conviction
            conviction_vol = _clamp(avg_change / 0.3, 0.0, 1.0)
        else:
            conviction_vol = 0.0

        # ── 4. Overtrading index ──
        actions = list(self._actions)
        if actions:
            action_ratio = sum(1 for a in actions if a == "EXECUTE") / len(actions)
            if action_ratio > self.overtrade_threshold:
                overtrade = _clamp(
                    (action_ratio - self.overtrade_threshold) /
                    (1.0 - self.overtrade_threshold), 0.0, 1.0
                )
            else:
                overtrade = 0.0
        else:
            overtrade = 0.0

        # ── 5. Paralysis index ──
        if actions:
            hold_ratio = sum(1 for a in actions if a == "HOLD") / len(actions)
            if hold_ratio > self.paralysis_threshold:
                paralysis = _clamp(
                    (hold_ratio - self.paralysis_threshold) /
                    (1.0 - self.paralysis_threshold), 0.0, 1.0
                )
            else:
                paralysis = 0.0
        else:
            paralysis = 0.0

        # ── Composite entropy index (weighted) ──
        entropy_index = (
            noise_stability * 0.25 +
            flip_flop_stability * 0.30 +
            conviction_vol * 0.20 +
            overtrade * 0.15 +
            paralysis * 0.10
        )
        entropy_index = _clamp(entropy_index, 0.0, 1.0)

        # ── Verdict ──
        if entropy_index < self.allow_threshold:
            verdict = "ALLOW"
            size_multiplier = 1.0
        elif entropy_index < self.reduce_threshold:
            verdict = "REDUCE"
            # Scale: at reduce_threshold → 0.5 multiplier
            scale = 1.0 - (entropy_index - self.allow_threshold) / \
                    (self.reduce_threshold - self.allow_threshold)
            size_multiplier = _clamp(scale * 0.5 + 0.5, 0.3, 1.0)
        else:
            verdict = "KILL"
            size_multiplier = 0.0

        # ── Reason string ──
        worst_component = max(
            ("noise_variance", noise_stability),
            ("flip_flop", flip_flop_stability),
            ("conviction_vol", conviction_vol),
            ("overtrade", overtrade),
            ("paralysis", paralysis),
            key=lambda x: x[1],
        )

        reason = f"entropy={entropy_index:.3f} worst={worst_component[0]}({worst_component[1]:.3f})"

        # Update state
        self._entropy_index = entropy_index
        self._last_verdict = verdict
        self._last_size_multiplier = size_multiplier

        return {
            "entropy_index": round(entropy_index, 4),
            "verdict": verdict,
            "size_multiplier": round(size_multiplier, 4),
            "reason": reason,
            "components": {
                "noise_variance": round(noise_stability, 4),
                "flip_flop_rate": round(flip_flop_stability, 4),
                "conviction_volatility": round(conviction_vol, 4),
                "overtrade_index": round(overtrade, 4),
                "paralysis_index": round(paralysis, 4),
            },
            "raw_metrics": {
                "noise_mean": round(noise_mean, 4),
                "noise_std": round(noise_std, 4),
                "flip_flop_rate_raw": round(flip_flop_rate, 4),
                "avg_conviction_change": round(
                    sum(conv_changes) / len(conv_changes) if conv_changes else 0, 4
                ),
                "action_ratio": round(
                    sum(1 for a in actions if a == "EXECUTE") / max(len(actions), 1), 4
                ),
                "hold_ratio": round(
                    sum(1 for a in actions if a == "HOLD") / max(len(actions), 1), 4
                ),
            },
        }

    # ===================================================================
    # 3. CONVENIENCE
    # ===================================================================

    def get_verdict(self) -> str:
        """Get the current verdict without recomputing."""
        return self._last_verdict

    def get_size_multiplier(self) -> float:
        """Get the current size multiplier."""
        return self._last_size_multiplier

    def get_entropy_index(self) -> float:
        """Get the current entropy index."""
        return self._entropy_index


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("entropy_guard.py — Self-Test")
    print("=" * 60)

    eg = EntropyGuard()

    # ── Test 1: Fresh system → ALLOW ─────────────────────────────────
    print("\n[Test 1] Fresh system → ALLOW...")
    result = eg.compute_entropy_index()
    assert result["verdict"] == "ALLOW"
    print(f"  verdict={result['verdict']}, entropy={result['entropy_index']:.4f}")
    print(f"  ✓ Fresh system is ALLOW")

    # ── Test 2: Stable decisions → ALLOW ─────────────────────────────
    print("\n[Test 2] Stable decisions → ALLOW...")
    eg2 = EntropyGuard()
    for i in range(30):
        eg2.record_decision("LONG", "LONG", 0.3, 0.6)
    result2 = eg2.compute_entropy_index()
    print(f"  verdict={result2['verdict']}, entropy={result2['entropy_index']:.4f}")
    assert result2["verdict"] == "ALLOW"
    print(f"  ✓ Stable decisions → ALLOW")

    # ── Test 3: Flip-flopping → REDUCE or KILL ───────────────────────
    print("\n[Test 3] Flip-flopping decisions → REDUCE/KILL...")
    eg3 = EntropyGuard()
    for i in range(30):
        action = "EXECUTE"
        side = "LONG" if i % 2 == 0 else "SHORT"
        noise = 0.3 if i % 2 == 0 else 0.8
        conviction = 0.7 if i % 2 == 0 else 0.1
        eg3.record_decision(action, side, noise, conviction)
    result3 = eg3.compute_entropy_index()
    print(f"  verdict={result3['verdict']}, entropy={result3['entropy_index']:.4f}")
    print(f"  flip_flop={result3['components']['flip_flop_rate']:.4f}")
    assert result3["entropy_index"] > result2["entropy_index"]
    print(f"  ✓ Flip-flopping increases entropy")

    # ── Test 4: Monotonicity — worse decisions → higher entropy ──────
    print("\n[Test 4] Monotonicity — worse decisions → higher entropy...")
    eg4a = EntropyGuard()
    for i in range(50):
        eg4a.record_decision("LONG", "LONG", 0.3, 0.6)
    stable = eg4a.compute_entropy_index()

    eg4b = EntropyGuard()
    for i in range(50):
        noise = 0.3 + 0.5 * abs(math.sin(i * 0.5))  # Oscillating noise
        conviction = 0.6 - 0.4 * abs(math.cos(i * 0.3))  # Oscillating conviction
        side = "LONG" if i % 3 != 0 else "SHORT"  # Some flips
        eg4b.record_decision("EXECUTE", side, noise, conviction)
    chaotic = eg4b.compute_entropy_index()

    assert chaotic["entropy_index"] > stable["entropy_index"], \
        "Chaotic decisions must have higher entropy"
    print(f"  stable_entropy={stable['entropy_index']:.4f}")
    print(f"  chaotic_entropy={chaotic['entropy_index']:.4f}")
    print(f"  ✓ Monotonicity confirmed")

    # ── Test 5: Overtrading detection ────────────────────────────────
    print("\n[Test 5] Overtrading detection...")
    eg5 = EntropyGuard(overtrade_threshold=0.5)
    for i in range(50):
        eg5.record_decision("EXECUTE", "LONG", 0.3, 0.5)  # 100% action
    result5 = eg5.compute_entropy_index()
    print(f"  overtrade_index={result5['components']['overtrade_index']:.4f}")
    assert result5["components"]["overtrade_index"] > 0
    print(f"  ✓ Overtrading detected")

    # ── Test 6: Paralysis detection ──────────────────────────────────
    print("\n[Test 6] Paralysis detection...")
    eg6 = EntropyGuard(paralysis_threshold=0.95)
    for i in range(50):
        eg6.record_decision("HOLD", None, 0.7, 0.05)  # 100% HOLD
    result6 = eg6.compute_entropy_index()
    print(f"  paralysis_index={result6['components']['paralysis_index']:.4f}")
    assert result6["components"]["paralysis_index"] > 0
    print(f"  ✓ Paralysis detected")

    # ── Test 7: Deterministic — same inputs = same output ────────────
    print("\n[Test 7] Deterministic...")
    eg7a = EntropyGuard()
    eg7b = EntropyGuard()
    for i in range(30):
        noise = 0.3 + (i % 5) * 0.1
        conviction = 0.5 + (i % 3) * 0.05
        side = "LONG" if i % 4 != 0 else "SHORT"
        eg7a.record_decision("EXECUTE", side, noise, conviction)
        eg7b.record_decision("EXECUTE", side, noise, conviction)
    r7a = eg7a.compute_entropy_index()
    r7b = eg7b.compute_entropy_index()
    assert abs(r7a["entropy_index"] - r7b["entropy_index"]) < 1e-10
    assert r7a["verdict"] == r7b["verdict"]
    print(f"  a={r7a['entropy_index']:.4f}, b={r7b['entropy_index']:.4f}")
    print(f"  ✓ Deterministic output confirmed")

    print("\n" + "=" * 60)
    print("All self-tests PASSED")
    print("=" * 60)
