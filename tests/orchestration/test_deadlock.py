"""P5.7 Deadlock Detection and Resolution tests."""
from __future__ import annotations

import pytest

from agenticlane.orchestration.deadlock import (
    DeadlockDetector,
    DeadlockResolver,
)


class TestDeadlockDetector:
    @pytest.fixture()
    def detector(self) -> DeadlockDetector:
        return DeadlockDetector(
            max_no_progress_attempts=5,
            policy="stop",
            progress_threshold=0.005,
        )

    # ------------------------------------------------------------------
    # test_deadlock_detected_after_n_attempts
    # ------------------------------------------------------------------
    def test_deadlock_detected_after_n_attempts(self, detector: DeadlockDetector) -> None:
        """No progress for N attempts -> deadlock."""
        # 6 scores: baseline + 5 stagnant (all within 0.005)
        scores = [0.50, 0.501, 0.502, 0.503, 0.504, 0.505]
        assert detector.check_deadlock(scores) is True

    # ------------------------------------------------------------------
    # test_no_deadlock_with_progress
    # ------------------------------------------------------------------
    def test_no_deadlock_with_progress(self, detector: DeadlockDetector) -> None:
        """Improving scores -> no deadlock."""
        scores = [0.50, 0.51, 0.52, 0.53, 0.54, 0.55]
        assert detector.check_deadlock(scores) is False

    # ------------------------------------------------------------------
    # test_ask_human_policy
    # ------------------------------------------------------------------
    def test_ask_human_policy(self) -> None:
        """Policy returns ask_human action."""
        det = DeadlockDetector(policy="ask_human")
        assert det.get_action() == "ask_human"

    # ------------------------------------------------------------------
    # test_auto_relax_policy
    # ------------------------------------------------------------------
    def test_auto_relax_policy(self) -> None:
        """Policy returns auto_relax action."""
        det = DeadlockDetector(policy="auto_relax")
        assert det.get_action() == "auto_relax"

    # ------------------------------------------------------------------
    # test_stop_policy
    # ------------------------------------------------------------------
    def test_stop_policy(self) -> None:
        """Policy returns stop action."""
        det = DeadlockDetector(policy="stop")
        assert det.get_action() == "stop"

    # ------------------------------------------------------------------
    # test_configurable_threshold
    # ------------------------------------------------------------------
    def test_configurable_threshold(self) -> None:
        """Custom progress threshold respected."""
        det = DeadlockDetector(
            max_no_progress_attempts=3,
            progress_threshold=0.1,
        )
        # Scores with step = 0.05 < threshold 0.1 -> deadlock
        scores = [0.50, 0.55, 0.60, 0.65]
        assert det.check_deadlock(scores) is True

        # One step exceeds threshold -> no deadlock
        scores2 = [0.50, 0.55, 0.70, 0.75]
        assert det.check_deadlock(scores2) is False

    # ------------------------------------------------------------------
    # test_insufficient_attempts
    # ------------------------------------------------------------------
    def test_insufficient_attempts(self, detector: DeadlockDetector) -> None:
        """Fewer than max_no_progress_attempts + 1 -> no deadlock."""
        scores = [0.50, 0.50, 0.50]
        assert detector.check_deadlock(scores) is False


class TestDeadlockResolver:
    # ------------------------------------------------------------------
    # test_resolver_ask_human
    # ------------------------------------------------------------------
    def test_resolver_ask_human(self) -> None:
        """Resolver returns correct structure for ask_human."""
        result = DeadlockResolver.resolve("ask_human")
        assert result["action_taken"] == "ask_human"
        assert result["result"] == "paused"
        assert "message" in result

    # ------------------------------------------------------------------
    # test_resolver_auto_relax
    # ------------------------------------------------------------------
    def test_resolver_auto_relax(self) -> None:
        """Resolver returns correct structure for auto_relax."""
        result = DeadlockResolver.resolve("auto_relax")
        assert result["action_taken"] == "auto_relax"
        assert result["result"] == "relaxed"
        assert "message" in result

    # ------------------------------------------------------------------
    # test_resolver_stop
    # ------------------------------------------------------------------
    def test_resolver_stop(self) -> None:
        """Resolver returns correct structure for stop."""
        result = DeadlockResolver.resolve("stop")
        assert result["action_taken"] == "stop"
        assert result["result"] == "stopped"
        assert "message" in result
