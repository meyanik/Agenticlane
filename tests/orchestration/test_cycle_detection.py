"""P5.6 Cycle Detection tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agenticlane.orchestration.cycle_detection import CycleDetector


class TestCycleDetector:
    @pytest.fixture()
    def detector(self) -> CycleDetector:
        return CycleDetector()

    # ------------------------------------------------------------------
    # test_same_patch_detected_as_cycle
    # ------------------------------------------------------------------
    def test_same_patch_detected_as_cycle(self, detector: CycleDetector) -> None:
        """Identical patches -> cycle detected."""
        patch = {"config_vars": {"CLOCK_PERIOD": "10"}, "overrides": {"util": "0.6"}}
        is_cycle_1, prev_1 = detector.check_and_record(patch, attempt_num=1)
        assert is_cycle_1 is False
        assert prev_1 is None

        is_cycle_2, prev_2 = detector.check_and_record(patch, attempt_num=3)
        assert is_cycle_2 is True
        assert prev_2 == 1

    # ------------------------------------------------------------------
    # test_different_patch_no_cycle
    # ------------------------------------------------------------------
    def test_different_patch_no_cycle(self, detector: CycleDetector) -> None:
        """Different patches -> no cycle."""
        patch_a = {"config_vars": {"CLOCK_PERIOD": "10"}}
        patch_b = {"config_vars": {"CLOCK_PERIOD": "12"}}
        detector.check_and_record(patch_a, attempt_num=1)
        is_cycle, prev = detector.check_and_record(patch_b, attempt_num=2)
        assert is_cycle is False
        assert prev is None

    # ------------------------------------------------------------------
    # test_cycle_event_logged
    # ------------------------------------------------------------------
    def test_cycle_event_logged(self, detector: CycleDetector, tmp_path: Path) -> None:
        """Cycle writes to JSONL file."""
        log_file = tmp_path / "cycles.jsonl"
        detector.log_cycle_event(log_file, "abc123", current_attempt=5, previous_attempt=2)

        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 1
        event = json.loads(lines[0])
        assert event["event"] == "cycle_detected"
        assert event["patch_hash"] == "abc123"
        assert event["current_attempt"] == 5
        assert event["previous_attempt"] == 2

    # ------------------------------------------------------------------
    # test_hash_deterministic
    # ------------------------------------------------------------------
    def test_hash_deterministic(self, detector: CycleDetector) -> None:
        """Same patch always produces same hash."""
        patch = {"a": 1, "b": [2, 3]}
        h1 = detector.compute_patch_hash(patch)
        h2 = detector.compute_patch_hash(patch)
        assert h1 == h2

    # ------------------------------------------------------------------
    # test_key_order_independent
    # ------------------------------------------------------------------
    def test_key_order_independent(self, detector: CycleDetector) -> None:
        """Different key order produces same hash."""
        patch_a = {"z_key": "val1", "a_key": "val2"}
        patch_b = {"a_key": "val2", "z_key": "val1"}
        assert detector.compute_patch_hash(patch_a) == detector.compute_patch_hash(patch_b)

    # ------------------------------------------------------------------
    # test_reset_clears_history
    # ------------------------------------------------------------------
    def test_reset_clears_history(self, detector: CycleDetector) -> None:
        """After reset, same patch not detected as cycle."""
        patch = {"var": "value"}
        detector.check_and_record(patch, attempt_num=1)
        detector.reset()
        is_cycle, prev = detector.check_and_record(patch, attempt_num=2)
        assert is_cycle is False
        assert prev is None

    # ------------------------------------------------------------------
    # test_returns_previous_attempt
    # ------------------------------------------------------------------
    def test_returns_previous_attempt(self, detector: CycleDetector) -> None:
        """Cycle returns correct previous attempt number."""
        patch = {"x": 42}
        detector.check_and_record(patch, attempt_num=7)
        is_cycle, prev = detector.check_and_record(patch, attempt_num=15)
        assert is_cycle is True
        assert prev == 7
