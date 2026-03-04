"""Tests for agenticlane.orchestration.scheduler -- P5.1 Scheduler + Branch Manager."""
from __future__ import annotations

from pathlib import Path

import pytest

from agenticlane.orchestration.scheduler import (
    BranchScheduler,
    DiverseSamplingStrategy,
    MutationalStrategy,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def output_dir(tmp_path: Path) -> Path:
    """Provide a temporary output directory for scheduler tests."""
    return tmp_path / "runs" / "test_run"


@pytest.fixture()
def knob_ranges() -> dict[str, tuple[float, float]]:
    """Standard knob ranges for testing."""
    return {
        "FP_CORE_UTIL": (20.0, 80.0),
        "PL_TARGET_DENSITY_PCT": (20.0, 95.0),
        "GRT_ADJUSTMENT": (0.0, 0.5),
    }


@pytest.fixture()
def scheduler(output_dir: Path, knob_ranges: dict[str, tuple[float, float]]) -> BranchScheduler:
    """Create a basic BranchScheduler with diverse strategy."""
    return BranchScheduler(
        n_branches=3,
        output_dir=output_dir,
        divergence_strategy="diverse",
        knob_ranges=knob_ranges,
        prune_delta_score=0.1,
        prune_patience_attempts=3,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBranchIdAssignment:
    """test_branch_id_assignment -- Branches get B0, B1, B2."""

    def test_branch_ids_sequential(self, scheduler: BranchScheduler) -> None:
        branches = scheduler.create_branches()
        assert [b.branch_id for b in branches] == ["B0", "B1", "B2"]

    def test_branch_ids_accessible_by_id(self, scheduler: BranchScheduler) -> None:
        scheduler.create_branches()
        for i in range(3):
            branch = scheduler.get_branch(f"B{i}")
            assert branch.branch_id == f"B{i}"


class TestBranchStatusTracking:
    """test_branch_status_tracking -- Status transitions: active -> pruned / completed."""

    def test_initial_status_is_active(self, scheduler: BranchScheduler) -> None:
        branches = scheduler.create_branches()
        for b in branches:
            assert b.status == "active"

    def test_transition_to_pruned(self, scheduler: BranchScheduler) -> None:
        scheduler.create_branches()
        scheduler.prune_branch("B0", reason="underperforming")
        branch = scheduler.get_branch("B0")
        assert branch.status == "pruned"
        assert branch.pruned_at is not None

    def test_transition_to_completed(self, scheduler: BranchScheduler) -> None:
        scheduler.create_branches()
        scheduler.complete_branch("B1")
        branch = scheduler.get_branch("B1")
        assert branch.status == "completed"
        assert branch.completed_at is not None

    def test_pruned_not_in_active(self, scheduler: BranchScheduler) -> None:
        scheduler.create_branches()
        scheduler.prune_branch("B0")
        active = scheduler.get_active_branches()
        assert all(b.branch_id != "B0" for b in active)
        assert len(active) == 2


class TestDiverseSamplingStrategy:
    """test_diverse_sampling_strategy -- Latin Hypercube produces spread-out knob sets."""

    def test_produces_n_knob_sets(
        self, knob_ranges: dict[str, tuple[float, float]]
    ) -> None:
        strategy = DiverseSamplingStrategy(knob_ranges=knob_ranges)
        result = strategy.generate(3)
        assert len(result) == 3

    def test_all_knobs_present_in_each_set(
        self, knob_ranges: dict[str, tuple[float, float]]
    ) -> None:
        strategy = DiverseSamplingStrategy(knob_ranges=knob_ranges)
        result = strategy.generate(3)
        for knob_set in result:
            assert set(knob_set.keys()) == set(knob_ranges.keys())

    def test_values_within_ranges(
        self, knob_ranges: dict[str, tuple[float, float]]
    ) -> None:
        strategy = DiverseSamplingStrategy(knob_ranges=knob_ranges)
        result = strategy.generate(3)
        for knob_set in result:
            for name, val in knob_set.items():
                lo, hi = knob_ranges[name]
                assert lo <= val <= hi, f"{name}={val} out of [{lo}, {hi}]"

    def test_spread_out_values(
        self, knob_ranges: dict[str, tuple[float, float]]
    ) -> None:
        """For each knob, the 3 samples should be distinct and spread across the range."""
        strategy = DiverseSamplingStrategy(knob_ranges=knob_ranges)
        result = strategy.generate(3)
        for name in knob_ranges:
            lo, hi = knob_ranges[name]
            vals = sorted(ks[name] for ks in result)
            # With 3 branches, segment width = (hi - lo) / 3.
            # Centres should be at lo + w/2, lo + 3w/2, lo + 5w/2
            # Each value should be unique (gap > 0).
            for i in range(len(vals) - 1):
                gap = vals[i + 1] - vals[i]
                # Due to rotation, gap may vary but each value should be unique
                assert gap > 0, f"{name}: duplicate samples"

    def test_deterministic(
        self, knob_ranges: dict[str, tuple[float, float]]
    ) -> None:
        s1 = DiverseSamplingStrategy(knob_ranges=knob_ranges)
        s2 = DiverseSamplingStrategy(knob_ranges=knob_ranges)
        assert s1.generate(3) == s2.generate(3)


class TestMutationalStrategy:
    """test_mutational_strategy -- Perturbation within +/-10-20% of best patch."""

    def test_produces_n_knob_sets(self) -> None:
        base = {"FP_CORE_UTIL": 50.0, "PL_TARGET_DENSITY_PCT": 60.0}
        strategy = MutationalStrategy(base_config_vars=base, perturbation_pct=0.15)
        result = strategy.generate(3)
        assert len(result) == 3

    def test_perturbation_within_range(self) -> None:
        base = {"FP_CORE_UTIL": 50.0, "PL_TARGET_DENSITY_PCT": 60.0}
        pct = 0.15
        strategy = MutationalStrategy(base_config_vars=base, perturbation_pct=pct)
        result = strategy.generate(5)
        for knob_set in result:
            for name, val in knob_set.items():
                base_val = base[name]
                lo = base_val * (1.0 - pct)
                hi = base_val * (1.0 + pct)
                assert lo - 1e-9 <= val <= hi + 1e-9, (
                    f"{name}={val} outside [{lo}, {hi}]"
                )

    def test_first_branch_is_low_perturbation(self) -> None:
        """With 3 branches, first should be at -pct, middle at 0, last at +pct."""
        base = {"FP_CORE_UTIL": 100.0}
        pct = 0.10
        strategy = MutationalStrategy(base_config_vars=base, perturbation_pct=pct)
        result = strategy.generate(3)
        # First: 100 * (1 - 0.10) = 90
        assert abs(result[0]["FP_CORE_UTIL"] - 90.0) < 1e-9
        # Middle: 100 * (1 + 0) = 100
        assert abs(result[1]["FP_CORE_UTIL"] - 100.0) < 1e-9
        # Last: 100 * (1 + 0.10) = 110
        assert abs(result[2]["FP_CORE_UTIL"] - 110.0) < 1e-9

    def test_single_branch_no_perturbation(self) -> None:
        base = {"FP_CORE_UTIL": 50.0}
        strategy = MutationalStrategy(base_config_vars=base, perturbation_pct=0.15)
        result = strategy.generate(1)
        assert len(result) == 1
        assert abs(result[0]["FP_CORE_UTIL"] - 50.0) < 1e-9

    def test_empty_base_returns_empty_dicts(self) -> None:
        strategy = MutationalStrategy(base_config_vars={}, perturbation_pct=0.15)
        result = strategy.generate(3)
        assert result == [{}, {}, {}]


class TestBranchIsolatedDirectories:
    """test_branch_isolated_directories -- Each branch has separate workspace root."""

    def test_unique_workspace_roots(self, scheduler: BranchScheduler) -> None:
        branches = scheduler.create_branches()
        roots = [b.workspace_root for b in branches]
        assert len(set(roots)) == len(roots), "Workspace roots must be unique"

    def test_directories_created(self, scheduler: BranchScheduler) -> None:
        branches = scheduler.create_branches()
        for b in branches:
            assert b.workspace_root.is_dir(), f"{b.workspace_root} not created"

    def test_directory_structure(self, scheduler: BranchScheduler) -> None:
        branches = scheduler.create_branches()
        for b in branches:
            expected = scheduler.output_dir / "branches" / b.branch_id
            assert b.workspace_root == expected


class TestBranchTipTracked:
    """test_branch_tip_tracked -- Current best attempt for each branch recorded."""

    def test_initial_tip_is_none(self, scheduler: BranchScheduler) -> None:
        branches = scheduler.create_branches()
        for b in branches:
            assert b.tip_stage is None
            assert b.tip_attempt == 0

    def test_tip_updated_on_score(self, scheduler: BranchScheduler) -> None:
        scheduler.create_branches()
        scheduler.update_branch_score("B0", score=0.5, stage="SYNTH", attempt=1)
        branch = scheduler.get_branch("B0")
        assert branch.tip_stage == "SYNTH"
        assert branch.tip_attempt == 1

    def test_best_score_tracked(self, scheduler: BranchScheduler) -> None:
        scheduler.create_branches()
        scheduler.update_branch_score("B0", score=0.3, stage="SYNTH", attempt=1)
        scheduler.update_branch_score("B0", score=0.7, stage="FLOORPLAN", attempt=2)
        scheduler.update_branch_score("B0", score=0.5, stage="PDN", attempt=3)
        branch = scheduler.get_branch("B0")
        assert branch.best_composite_score == 0.7
        assert branch.best_attempt == 2


class TestPruneUnderperformingBranch:
    """test_prune_underperforming_branch -- Branch below threshold for patience attempts pruned."""

    def test_prune_after_patience_exceeded(self, scheduler: BranchScheduler) -> None:
        scheduler.create_branches()
        # B0 gets high scores
        scheduler.update_branch_score("B0", score=0.8, stage="SYNTH", attempt=1)
        scheduler.update_branch_score("B0", score=0.85, stage="FLOORPLAN", attempt=2)
        scheduler.update_branch_score("B0", score=0.9, stage="PDN", attempt=3)

        # B1 gets low scores -- below best (0.9) - delta (0.1) = 0.8 threshold
        # for prune_patience_attempts=3 consecutive
        scheduler.update_branch_score("B1", score=0.3, stage="SYNTH", attempt=1)
        scheduler.update_branch_score("B1", score=0.2, stage="FLOORPLAN", attempt=2)
        scheduler.update_branch_score("B1", score=0.25, stage="PDN", attempt=3)

        assert scheduler.should_prune("B1") is True


class TestNoPruneWithinPatience:
    """test_no_prune_within_patience -- Branch below threshold but within patience survives."""

    def test_not_enough_scores(self, scheduler: BranchScheduler) -> None:
        scheduler.create_branches()
        # B0 gets a high score
        scheduler.update_branch_score("B0", score=0.9, stage="SYNTH", attempt=1)
        # B1 has only 2 low scores (patience=3)
        scheduler.update_branch_score("B1", score=0.1, stage="SYNTH", attempt=1)
        scheduler.update_branch_score("B1", score=0.15, stage="FLOORPLAN", attempt=2)

        assert scheduler.should_prune("B1") is False

    def test_recent_score_above_threshold(self, scheduler: BranchScheduler) -> None:
        """If the most recent score is above threshold, don't prune."""
        scheduler.create_branches()
        scheduler.update_branch_score("B0", score=0.9, stage="SYNTH", attempt=1)
        # B1 has 3 scores but the last one is above threshold (0.9 - 0.1 = 0.8)
        scheduler.update_branch_score("B1", score=0.1, stage="SYNTH", attempt=1)
        scheduler.update_branch_score("B1", score=0.2, stage="FLOORPLAN", attempt=2)
        scheduler.update_branch_score("B1", score=0.85, stage="PDN", attempt=3)

        assert scheduler.should_prune("B1") is False


class TestBestBranchSelected:
    """test_best_branch_selected -- Branch with highest composite score selected."""

    def test_selects_highest_score(self, scheduler: BranchScheduler) -> None:
        scheduler.create_branches()
        scheduler.update_branch_score("B0", score=0.5, stage="SYNTH", attempt=1)
        scheduler.update_branch_score("B1", score=0.8, stage="SYNTH", attempt=1)
        scheduler.update_branch_score("B2", score=0.3, stage="SYNTH", attempt=1)

        best = scheduler.select_best_branch()
        assert best is not None
        assert best.branch_id == "B1"

    def test_no_scores_returns_none(self, scheduler: BranchScheduler) -> None:
        scheduler.create_branches()
        assert scheduler.select_best_branch() is None


class TestCreateBranchesWithDiverseStrategy:
    """test_create_branches_with_diverse_strategy -- Creates n_branches with diverse sampling."""

    def test_branches_have_diverse_init_patches(
        self,
        output_dir: Path,
        knob_ranges: dict[str, tuple[float, float]],
    ) -> None:
        sched = BranchScheduler(
            n_branches=3,
            output_dir=output_dir,
            divergence_strategy="diverse",
            knob_ranges=knob_ranges,
        )
        branches = sched.create_branches()
        assert len(branches) == 3

        # Each branch should have config_vars from diverse sampling
        patches = [b.init_patch for b in branches]
        for p in patches:
            assert p is not None
            assert "config_vars" in p

        # Config vars should differ across branches
        config_vars_list = [p["config_vars"] for p in patches if p]
        fp_util_vals = [cv["FP_CORE_UTIL"] for cv in config_vars_list]  # type: ignore[index]
        assert len(set(fp_util_vals)) == 3, "Diverse strategy should produce unique values"


class TestCreateBranchesWithMutationalStrategy:
    """test_create_branches_with_mutational_strategy -- Creates n_branches with mutational."""

    def test_branches_have_perturbed_patches(self, output_dir: Path) -> None:
        init_patch = {"config_vars": {"FP_CORE_UTIL": 50.0, "PL_TARGET_DENSITY_PCT": 60.0}}
        sched = BranchScheduler(
            n_branches=3,
            output_dir=output_dir,
            divergence_strategy="mutational",
        )
        branches = sched.create_branches(init_patch=init_patch)
        assert len(branches) == 3

        patches = [b.init_patch for b in branches]
        for p in patches:
            assert p is not None
            assert "config_vars" in p

        # Values should differ across branches
        fp_vals = [
            p["config_vars"]["FP_CORE_UTIL"]  # type: ignore[index]
            for p in patches
            if p
        ]
        assert len(set(fp_vals)) == 3


class TestGetBranchSummary:
    """test_get_branch_summary -- Summary dict has correct structure."""

    def test_summary_structure(self, scheduler: BranchScheduler) -> None:
        scheduler.create_branches()
        scheduler.update_branch_score("B0", score=0.5, stage="SYNTH", attempt=1)
        scheduler.prune_branch("B1")
        scheduler.complete_branch("B2")

        summary = scheduler.get_branch_summary()
        assert summary["total_branches"] == 3
        assert summary["active"] == 1
        assert summary["pruned"] == 1
        assert summary["completed"] == 1
        assert summary["failed"] == 0

        branches_detail = summary["branches"]
        assert isinstance(branches_detail, dict)
        assert "B0" in branches_detail
        assert branches_detail["B0"]["status"] == "active"
        assert branches_detail["B0"]["best_score"] == 0.5
        assert branches_detail["B1"]["status"] == "pruned"
        assert branches_detail["B2"]["status"] == "completed"


class TestFailBranch:
    """test_fail_branch -- Failed branch tracked correctly."""

    def test_fail_sets_status(self, scheduler: BranchScheduler) -> None:
        scheduler.create_branches()
        scheduler.fail_branch("B2", reason="execution error")
        branch = scheduler.get_branch("B2")
        assert branch.status == "failed"

    def test_failed_branch_not_active(self, scheduler: BranchScheduler) -> None:
        scheduler.create_branches()
        scheduler.fail_branch("B2")
        active = scheduler.get_active_branches()
        assert all(b.branch_id != "B2" for b in active)


class TestCompleteBranch:
    """test_complete_branch -- Completed branch tracked correctly."""

    def test_complete_sets_status(self, scheduler: BranchScheduler) -> None:
        scheduler.create_branches()
        scheduler.complete_branch("B0")
        branch = scheduler.get_branch("B0")
        assert branch.status == "completed"
        assert branch.completed_at is not None

    def test_completed_branch_not_active(self, scheduler: BranchScheduler) -> None:
        scheduler.create_branches()
        scheduler.complete_branch("B0")
        active = scheduler.get_active_branches()
        assert all(b.branch_id != "B0" for b in active)
