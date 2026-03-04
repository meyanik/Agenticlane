"""P5.5 Plateau Detection for AgenticLane.

Detects when optimization scores have stagnated within a sliding window,
indicating that the current strategy is no longer making meaningful progress.
"""
from __future__ import annotations


class PlateauDetector:
    """Detect score plateaus using a sliding window.

    A plateau is detected when the last ``window_size`` scores all fall
    within a range strictly less than ``threshold``.
    """

    def __init__(
        self,
        *,
        window_size: int = 5,
        threshold: float = 0.01,
    ) -> None:
        self.window_size = window_size
        self.threshold = threshold

    def is_plateau(self, scores: list[float]) -> bool:
        """Return True if the last *window_size* scores are within *threshold*.

        Requires at least *window_size* scores.  The range (max - min)
        must be **strictly less than** the threshold for a plateau.
        """
        if len(scores) < self.window_size:
            return False

        window = scores[-self.window_size :]
        score_range = max(window) - min(window)
        return score_range < self.threshold

    def get_plateau_info(self, scores: list[float]) -> dict[str, object] | None:
        """Return plateau diagnostics if a plateau is detected, else ``None``.

        The returned dict contains:
        - ``window``: the score values in the detection window
        - ``mean``: arithmetic mean of the window
        - ``range``: max - min of the window
        """
        if not self.is_plateau(scores):
            return None

        window = scores[-self.window_size :]
        mean = sum(window) / len(window)
        score_range = max(window) - min(window)

        return {
            "window": window,
            "mean": mean,
            "range": score_range,
        }
