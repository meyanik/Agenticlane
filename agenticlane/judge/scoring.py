"""Scoring formula for AgenticLane.

Computes composite scores for design iterations using weighted normalized
metric improvements, with anti-cheat mechanisms based on ConstraintDigest.
"""

from __future__ import annotations

from typing import Optional

from agenticlane.config.models import ScoringConfig
from agenticlane.schemas.constraints import ConstraintDigest
from agenticlane.schemas.metrics import MetricsPayload


def normalize_metric(
    current_value: Optional[float],
    baseline_value: Optional[float],
    *,
    epsilon: float = 1e-6,
    clamp: float = 1.0,
    direction: str = "lower_is_better",
) -> Optional[float]:
    """Compute normalized improvement score.

    Returns value in [-clamp, +clamp]:
    - Positive = improvement (current better than baseline)
    - Negative = regression (current worse than baseline)
    - 0.0 = no change
    - None = insufficient data

    For direction="lower_is_better": improvement = (baseline - current) / (|baseline| + epsilon)
    For direction="higher_is_better": improvement = (current - baseline) / (|baseline| + epsilon)
    """
    if current_value is None or baseline_value is None:
        return None

    denominator = abs(baseline_value) + epsilon

    if direction == "lower_is_better":
        improvement = (baseline_value - current_value) / denominator
    elif direction == "higher_is_better":
        improvement = (current_value - baseline_value) / denominator
    else:
        raise ValueError(f"Unknown direction: {direction}")

    return max(-clamp, min(clamp, improvement))


class ScoringEngine:
    """Computes composite scores with anti-cheat timing.

    Anti-cheat: Uses effective_setup_period = applied_clock_period - setup_wns
    (from ConstraintDigest, not config vars) to defeat clock relaxation cheats.
    """

    def __init__(self, config: ScoringConfig) -> None:
        self.config = config

    def compute_composite_score(
        self,
        baseline_metrics: MetricsPayload,
        current_metrics: MetricsPayload,
        constraint_digest: Optional[ConstraintDigest] = None,
        intent_weights: Optional[dict[str, float]] = None,
    ) -> float:
        """Compute weighted composite improvement score.

        Components (by intent weight key):
        - "timing": effective setup period or raw WNS
        - "area": core area
        - "route": congestion overflow
        - "power": (future, returns 0.0 for now)

        Returns composite score in [-1.0, 1.0].
        """
        weights = intent_weights or {"timing": 0.7, "area": 0.3}
        epsilon = self.config.normalization.epsilon
        clamp = self.config.normalization.clamp

        component_scores: dict[str, Optional[float]] = {}

        if "timing" in weights:
            component_scores["timing"] = self._compute_timing_score(
                baseline_metrics,
                current_metrics,
                constraint_digest,
                epsilon=epsilon,
                clamp=clamp,
            )

        if "area" in weights:
            component_scores["area"] = self._compute_area_score(
                baseline_metrics,
                current_metrics,
                epsilon=epsilon,
                clamp=clamp,
            )

        if "route" in weights:
            component_scores["route"] = self._compute_route_score(
                baseline_metrics,
                current_metrics,
                epsilon=epsilon,
                clamp=clamp,
            )

        if "power" in weights:
            component_scores["power"] = self._compute_power_score(
                baseline_metrics,
                current_metrics,
                epsilon=epsilon,
                clamp=clamp,
            )

        # Weighted sum with only non-None components
        composite = 0.0
        total_weight = 0.0
        for key, weight in weights.items():
            score = component_scores.get(key)
            if score is not None:
                composite += weight * score
                total_weight += weight

        if total_weight > 0:
            composite /= total_weight

        return composite

    def _compute_timing_score(
        self,
        baseline: MetricsPayload,
        current: MetricsPayload,
        constraint_digest: Optional[ConstraintDigest],
        *,
        epsilon: float,
        clamp: float,
    ) -> Optional[float]:
        """Timing score using effective setup period (anti-cheat).

        effective_setup_period = applied_clock_period - worst_corner_wns
        Lower effective period = tighter timing = better.
        """
        baseline_wns = self._get_worst_corner_wns(baseline)
        current_wns = self._get_worst_corner_wns(current)

        if baseline_wns is None or current_wns is None:
            return None

        if (
            self.config.timing.effective_clock.enabled
            and constraint_digest is not None
            and constraint_digest.clocks
        ):
            # Anti-cheat: use applied clock from ConstraintDigest
            applied_period = constraint_digest.clocks[0].period_ns
            baseline_eff = applied_period - baseline_wns
            current_eff = applied_period - current_wns
            return normalize_metric(
                current_eff,
                baseline_eff,
                epsilon=epsilon,
                clamp=clamp,
                direction="lower_is_better",
            )

        # Fallback: raw WNS improvement (higher WNS = less negative = better)
        return normalize_metric(
            current_wns,
            baseline_wns,
            epsilon=epsilon,
            clamp=clamp,
            direction="higher_is_better",
        )

    def _compute_area_score(
        self,
        baseline: MetricsPayload,
        current: MetricsPayload,
        *,
        epsilon: float,
        clamp: float,
    ) -> Optional[float]:
        """Area score (lower area = better)."""
        baseline_area = baseline.physical.core_area_um2 if baseline.physical else None
        current_area = current.physical.core_area_um2 if current.physical else None
        return normalize_metric(
            current_area,
            baseline_area,
            epsilon=epsilon,
            clamp=clamp,
            direction="lower_is_better",
        )

    def _compute_route_score(
        self,
        baseline: MetricsPayload,
        current: MetricsPayload,
        *,
        epsilon: float,
        clamp: float,
    ) -> Optional[float]:
        """Routing congestion score (lower overflow = better)."""
        baseline_cong = (
            baseline.route.congestion_overflow_pct if baseline.route else None
        )
        current_cong = (
            current.route.congestion_overflow_pct if current.route else None
        )
        return normalize_metric(
            current_cong,
            baseline_cong,
            epsilon=epsilon,
            clamp=clamp,
            direction="lower_is_better",
        )

    def _compute_power_score(
        self,
        baseline: MetricsPayload,
        current: MetricsPayload,
        *,
        epsilon: float,
        clamp: float,
    ) -> Optional[float]:
        """Power score (lower total power = better)."""
        baseline_power = (
            baseline.power.total_power_mw if baseline.power else None
        )
        current_power = (
            current.power.total_power_mw if current.power else None
        )
        return normalize_metric(
            current_power,
            baseline_power,
            epsilon=epsilon,
            clamp=clamp,
            direction="lower_is_better",
        )

    @staticmethod
    def _get_worst_corner_wns(metrics: MetricsPayload) -> Optional[float]:
        """Extract worst-corner setup WNS (minimum value = worst slack)."""
        if metrics.timing is None or not metrics.timing.setup_wns_ns:
            return None
        values = [v for v in metrics.timing.setup_wns_ns.values() if v is not None]
        if not values:
            return None
        return min(values)
