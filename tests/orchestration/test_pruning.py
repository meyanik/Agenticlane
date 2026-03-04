"""Tests for agenticlane.orchestration.pruning (P5.3)."""
from __future__ import annotations

import pytest

from agenticlane.orchestration.pruning import (
    PruneDecision,
    PruningEngine,
    SelectionResult,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def engine() -> PruningEngine:
    """Default PruningEngine (delta=0.1, patience=3, min_attempts=2)."""
    return PruningEngine()


# ---------------------------------------------------------------------------
# Pruning tests
# ---------------------------------------------------------------------------


class TestEvaluateBranch:
    """Tests for PruningEngine.evaluate_branch."""

    def test_prune_underperforming_branch(self, engine: PruningEngine) -> None:
        """Branch consistently below threshold gets pruned."""
        # Best global is 0.9; delta is 0.1 => threshold is 0.8
        # Branch has 3 scores all < 0.8 (patience = 3)
        scores = [0.5, 0.6, 0.7]
        decision = engine.evaluate_branch(scores, best_global_score=0.9)

        assert decision.should_prune is True
        assert "underperforming" in decision.reason
        assert decision.current_score == 0.7
        assert decision.best_global_score == 0.9
        assert decision.score_gap is not None
        assert decision.score_gap == pytest.approx(0.2)

    def test_no_prune_within_patience(self, engine: PruningEngine) -> None:
        """Branch below threshold but within patience window survives."""
        # Only 2 scores => fewer than patience (3), but >= min_attempts (2)
        # However, len(recent) < patience so reason is within_patience_window
        scores = [0.5, 0.6]
        decision = engine.evaluate_branch(scores, best_global_score=0.9)

        assert decision.should_prune is False
        assert decision.reason == "within_patience_window"

    def test_no_prune_insufficient_attempts(self, engine: PruningEngine) -> None:
        """Branch with fewer than min_attempts not pruned."""
        scores = [0.3]
        decision = engine.evaluate_branch(scores, best_global_score=0.9)

        assert decision.should_prune is False
        assert decision.reason == "insufficient_attempts"

    def test_branch_recovering_not_pruned(self, engine: PruningEngine) -> None:
        """Branch that was below but recent score above threshold survives."""
        # Best global = 0.9, threshold = 0.8
        # Last 3 scores: [0.5, 0.6, 0.85]  -- 0.85 >= 0.8 so NOT all below
        scores = [0.5, 0.6, 0.85]
        decision = engine.evaluate_branch(scores, best_global_score=0.9)

        assert decision.should_prune is False
        assert decision.reason == "within_threshold"

    def test_configurable_delta_and_patience(self) -> None:
        """Custom delta/patience values are respected."""
        engine = PruningEngine(
            prune_delta_score=0.05,
            prune_patience_attempts=2,
            min_attempts_before_prune=1,
        )
        # Best global = 1.0, delta = 0.05 => threshold = 0.95
        # patience = 2, last 2 scores below 0.95
        scores = [0.8, 0.89]
        decision = engine.evaluate_branch(scores, best_global_score=1.0)

        assert decision.should_prune is True
        assert "underperforming_for_2_attempts" in decision.reason

        # Now verify a larger delta keeps the branch alive
        engine_lenient = PruningEngine(
            prune_delta_score=0.5,
            prune_patience_attempts=2,
            min_attempts_before_prune=1,
        )
        decision2 = engine_lenient.evaluate_branch(scores, best_global_score=1.0)
        assert decision2.should_prune is False


# ---------------------------------------------------------------------------
# evaluate_all_branches tests
# ---------------------------------------------------------------------------


class TestEvaluateAllBranches:
    """Tests for PruningEngine.evaluate_all_branches."""

    def test_evaluate_all_branches(self, engine: PruningEngine) -> None:
        """Multiple branches evaluated correctly."""
        branch_scores = {
            "B0": [0.9, 0.92, 0.95],  # best performer
            "B1": [0.5, 0.5, 0.5],    # underperforming (all below 0.95 - 0.1 = 0.85)
            "B2": [0.8, 0.85, 0.88],  # above threshold
        }

        decisions = engine.evaluate_all_branches(branch_scores)

        assert len(decisions) == 3

        by_id = {d.branch_id: d for d in decisions}

        # B0 is the best and should not be pruned
        assert by_id["B0"].should_prune is False

        # B1 is consistently below 0.85 => pruned
        assert by_id["B1"].should_prune is True

        # B2 has scores at or above threshold => not pruned
        assert by_id["B2"].should_prune is False


# ---------------------------------------------------------------------------
# Selection tests
# ---------------------------------------------------------------------------


class TestSelectWinner:
    """Tests for PruningEngine.select_winner."""

    def test_best_branch_selected(self, engine: PruningEngine) -> None:
        """Branch with highest best score selected as winner."""
        branch_scores = {
            "B0": [0.7, 0.8],
            "B1": [0.85, 0.9],
            "B2": [0.6, 0.75],
        }

        result = engine.select_winner(branch_scores)

        assert result.winning_branch_id == "B1"
        assert result.winning_score == pytest.approx(0.9)
        assert result.reason == "highest_best_score"

    def test_pruned_branch_excluded_from_selection(
        self, engine: PruningEngine
    ) -> None:
        """Pruned branches excluded from winner selection."""
        branch_scores = {
            "B0": [0.7, 0.85],
            "B1": [0.85, 0.95],  # highest, but pruned
            "B2": [0.6, 0.82],
        }

        result = engine.select_winner(branch_scores, pruned_ids={"B1"})

        assert result.winning_branch_id == "B0"
        assert result.winning_score == pytest.approx(0.85)
        assert "B1" in result.pruned_branches

    def test_no_branches_no_winner(self, engine: PruningEngine) -> None:
        """Empty input returns no winner."""
        result = engine.select_winner({})

        assert result.winning_branch_id is None
        assert result.winning_score is None
        assert result.reason == "no_active_branches_with_scores"

    def test_single_branch_wins(self, engine: PruningEngine) -> None:
        """Single branch always wins."""
        result = engine.select_winner({"B0": [0.42]})

        assert result.winning_branch_id == "B0"
        assert result.winning_score == pytest.approx(0.42)

    def test_winning_branch_in_manifest(self, engine: PruningEngine) -> None:
        """SelectionResult has correct winning_branch_id field."""
        branch_scores = {
            "B0": [0.5, 0.6],
            "B1": [0.7, 0.8],
        }

        result = engine.select_winner(branch_scores)

        assert isinstance(result, SelectionResult)
        assert result.winning_branch_id == "B1"
        assert result.winning_score == pytest.approx(0.8)
        assert "B0" in result.all_scores
        assert "B1" in result.all_scores


# ---------------------------------------------------------------------------
# Summary tests
# ---------------------------------------------------------------------------


class TestPruningSummary:
    """Tests for PruningEngine.get_pruning_summary."""

    def test_pruning_summary_structure(self, engine: PruningEngine) -> None:
        """Summary dict has correct keys and counts."""
        decisions = [
            PruneDecision(branch_id="B0", should_prune=False, reason="ok"),
            PruneDecision(branch_id="B1", should_prune=True, reason="bad"),
            PruneDecision(branch_id="B2", should_prune=False, reason="ok"),
        ]

        summary = engine.get_pruning_summary(decisions)

        assert summary["total_branches"] == 3
        assert summary["to_prune"] == 1
        assert summary["to_keep"] == 2
        assert summary["prune_ids"] == ["B1"]
        assert set(summary["keep_ids"]) == {"B0", "B2"}
        assert len(summary["decisions"]) == 3

        # Each decision entry should have expected keys
        for entry in summary["decisions"]:
            assert "branch_id" in entry
            assert "should_prune" in entry
            assert "reason" in entry
            assert "current_score" in entry
            assert "score_gap" in entry
