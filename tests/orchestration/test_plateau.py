"""P5.5 Plateau Detection tests."""
from __future__ import annotations

import pytest

from agenticlane.orchestration.plateau import PlateauDetector


class TestPlateauDetector:
    @pytest.fixture()
    def detector(self) -> PlateauDetector:
        return PlateauDetector(window_size=5, threshold=0.01)

    # ------------------------------------------------------------------
    # test_plateau_detected
    # ------------------------------------------------------------------
    def test_plateau_detected(self, detector: PlateauDetector) -> None:
        """Flat scores across window_size triggers plateau."""
        scores = [0.50, 0.50, 0.50, 0.50, 0.50]
        assert detector.is_plateau(scores) is True

    # ------------------------------------------------------------------
    # test_no_plateau_when_improving
    # ------------------------------------------------------------------
    def test_no_plateau_when_improving(self, detector: PlateauDetector) -> None:
        """Increasing scores don't trigger plateau."""
        scores = [0.50, 0.52, 0.54, 0.56, 0.58]
        assert detector.is_plateau(scores) is False

    # ------------------------------------------------------------------
    # test_no_plateau_insufficient_scores
    # ------------------------------------------------------------------
    def test_no_plateau_insufficient_scores(self, detector: PlateauDetector) -> None:
        """Fewer than window_size scores -> no plateau."""
        scores = [0.50, 0.50, 0.50]
        assert detector.is_plateau(scores) is False

    # ------------------------------------------------------------------
    # test_configurable_window_and_threshold
    # ------------------------------------------------------------------
    def test_configurable_window_and_threshold(self) -> None:
        """Custom window/threshold respected."""
        detector = PlateauDetector(window_size=3, threshold=0.05)
        # Range = 0.04 < 0.05 -> plateau
        scores = [0.50, 0.52, 0.54]
        assert detector.is_plateau(scores) is True

        # Range = 0.06 >= 0.05 -> no plateau
        scores2 = [0.50, 0.52, 0.56]
        assert detector.is_plateau(scores2) is False

    # ------------------------------------------------------------------
    # test_plateau_info_structure
    # ------------------------------------------------------------------
    def test_plateau_info_structure(self, detector: PlateauDetector) -> None:
        """get_plateau_info returns correct dict with expected keys."""
        scores = [0.50, 0.50, 0.50, 0.50, 0.50]
        info = detector.get_plateau_info(scores)
        assert info is not None
        assert "window" in info
        assert "mean" in info
        assert "range" in info
        assert info["window"] == [0.50, 0.50, 0.50, 0.50, 0.50]
        assert info["mean"] == pytest.approx(0.50)
        assert info["range"] == pytest.approx(0.0)

    def test_plateau_info_none_when_no_plateau(self, detector: PlateauDetector) -> None:
        """get_plateau_info returns None when no plateau."""
        scores = [0.50, 0.60, 0.70, 0.80, 0.90]
        assert detector.get_plateau_info(scores) is None

    # ------------------------------------------------------------------
    # test_declining_scores_no_plateau
    # ------------------------------------------------------------------
    def test_declining_scores_no_plateau(self, detector: PlateauDetector) -> None:
        """Large declining scores don't trigger plateau."""
        scores = [0.90, 0.80, 0.70, 0.60, 0.50]
        assert detector.is_plateau(scores) is False

    # ------------------------------------------------------------------
    # test_exactly_at_threshold
    # ------------------------------------------------------------------
    def test_exactly_at_threshold(self, detector: PlateauDetector) -> None:
        """Scores with range exactly equal to threshold -> not plateau (strictly less)."""
        # threshold = 0.01, so range == 0.01 should NOT be plateau
        scores = [0.500, 0.500, 0.500, 0.500, 0.510]
        assert detector.is_plateau(scores) is False
