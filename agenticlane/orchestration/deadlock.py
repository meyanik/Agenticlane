"""P5.7 Deadlock Detection and Resolution for AgenticLane.

Detects when the optimization loop has made no meaningful progress for
a configurable number of attempts, and applies a policy-driven resolution
strategy.
"""
from __future__ import annotations

from typing import Literal

DeadlockAction = Literal["ask_human", "auto_relax", "stop"]


class DeadlockDetector:
    """Detect deadlocks based on score stagnation.

    A deadlock is declared when the last ``max_no_progress_attempts``
    scores all show improvement less than ``progress_threshold`` from
    one score to the next.
    """

    def __init__(
        self,
        *,
        max_no_progress_attempts: int = 10,
        policy: DeadlockAction = "stop",
        progress_threshold: float = 0.005,
    ) -> None:
        self.max_no_progress_attempts = max_no_progress_attempts
        self.policy = policy
        self.progress_threshold = progress_threshold

    def check_deadlock(self, scores: list[float]) -> bool:
        """Return True if no meaningful progress for *max_no_progress_attempts*.

        Requires at least ``max_no_progress_attempts + 1`` scores
        (the baseline plus N stagnant ones).  Progress is measured as
        successive improvement exceeding *progress_threshold*.
        """
        needed = self.max_no_progress_attempts + 1
        if len(scores) < needed:
            return False

        recent = scores[-needed:]
        for i in range(1, len(recent)):
            if recent[i] - recent[i - 1] > self.progress_threshold:
                return False
        return True

    def get_action(self) -> DeadlockAction:
        """Return the configured deadlock policy action."""
        return self.policy


class DeadlockResolver:
    """Execute a deadlock resolution action."""

    @staticmethod
    def resolve(
        action: DeadlockAction, context: dict[str, object] | None = None
    ) -> dict[str, object]:
        """Execute the given deadlock resolution *action*.

        Returns a dict with keys ``action_taken``, ``result``, and
        ``message``.  The optional *context* is reserved for future use
        (e.g. passing state to a human review UI).
        """
        if action == "ask_human":
            return {
                "action_taken": "ask_human",
                "result": "paused",
                "message": "Deadlock detected. Awaiting human guidance.",
            }
        if action == "auto_relax":
            return {
                "action_taken": "auto_relax",
                "result": "relaxed",
                "message": "Deadlock detected. Constraints automatically relaxed.",
                "relax_signoff_hard_gates": True,
            }
        # action == "stop"
        return {
            "action_taken": "stop",
            "result": "stopped",
            "message": "Deadlock detected. Optimization stopped.",
        }
