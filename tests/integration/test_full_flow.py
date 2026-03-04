"""Full integration test for AgenticLane E2E flow (P5.12).

Proves all Phase 5 components work together:
- 3 branches with divergent configs
- Parallel execution with semaphore limiting
- Score-based pruning (at least one branch pruned)
- Best branch selection
- Complete manifest with provenance
- Report generation from manifest
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from agenticlane.orchestration.checkpoint import Checkpoint, CheckpointManager
from agenticlane.orchestration.cycle_detection import CycleDetector
from agenticlane.orchestration.deadlock import DeadlockDetector
from agenticlane.orchestration.manifest import ManifestBuilder, StageDecision
from agenticlane.orchestration.parallel import BranchResult, ParallelBranchRunner
from agenticlane.orchestration.plateau import PlateauDetector
from agenticlane.orchestration.pruning import PruningEngine
from agenticlane.orchestration.scheduler import BranchScheduler
from agenticlane.orchestration.zero_shot import ZeroShotInitializer
from agenticlane.reporting.report import ReportGenerator

STAGES = [
    "SYNTH",
    "FLOORPLAN",
    "PDN",
    "PLACE_GLOBAL",
    "PLACE_DETAILED",
    "CTS",
    "ROUTE_GLOBAL",
    "ROUTE_DETAILED",
    "FINISH",
    "SIGNOFF",
]

# Deterministic score sequences per branch
BRANCH_SCORES: dict[str, list[float]] = {
    "B0": [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.82, 0.84, 0.85],
    "B1": [0.30, 0.28, 0.25, 0.22, 0.20, 0.18, 0.15, 0.12, 0.10, 0.08],
    "B2": [0.40, 0.42, 0.44, 0.46, 0.48, 0.50, 0.52, 0.54, 0.56, 0.58],
}


async def _simulate_branch_execution(
    branch_id: str,
    workspace: Path,
    init_patch: dict[str, Any] | None,
    *,
    manifest_builder: ManifestBuilder,
    pruning_engine: PruningEngine,
    all_branch_scores: dict[str, list[float]],
    plateau_detector: PlateauDetector,
    cycle_detector: CycleDetector,
    checkpoint_mgr: CheckpointManager,
) -> BranchResult:
    """Simulate executing a branch through all stages."""
    scores = BRANCH_SCORES.get(branch_id, [0.5] * 10)
    workspace.mkdir(parents=True, exist_ok=True)

    stages_completed = 0
    final_score: float | None = None

    for i, stage in enumerate(STAGES):
        score = scores[i] if i < len(scores) else 0.5

        # Record decision in manifest
        manifest_builder.record_decision(
            StageDecision(
                stage=stage,
                branch_id=branch_id,
                attempt=i + 1,
                action="accept",
                composite_score=score,
            )
        )

        # Track score in shared dict
        all_branch_scores.setdefault(branch_id, []).append(score)

        # Check cycle
        patch_data = {"branch_id": branch_id, "stage": stage, "score": score}
        cycle_detector.check_and_record(patch_data, i + 1)

        # Write checkpoint
        cp = Checkpoint(
            run_id="e2e_run",
            current_stage=stage,
            last_attempt=i + 1,
            branch_id=branch_id,
            composite_score=score,
        )
        attempt_dir = workspace / f"attempt_{i + 1:03d}"
        checkpoint_mgr.write_checkpoint(cp, attempt_dir)

        stages_completed += 1
        final_score = score

        # Check pruning after 3 stages
        if stages_completed >= 3:
            decisions = pruning_engine.evaluate_all_branches(all_branch_scores)
            my_decision = next(
                (d for d in decisions if d.branch_id == branch_id), None
            )
            if my_decision and my_decision.should_prune:
                return BranchResult(
                    branch_id=branch_id,
                    success=True,
                    final_score=final_score,
                    stages_completed=stages_completed,
                    artifacts_dir=workspace,
                )

        # Small delay for async realism and interleaving
        await asyncio.sleep(0.001)

    return BranchResult(
        branch_id=branch_id,
        success=True,
        final_score=final_score,
        stages_completed=stages_completed,
        artifacts_dir=workspace,
    )


class TestFullFlow:
    """End-to-end integration tests for the full AgenticLane flow."""

    @pytest.fixture()
    def run_dir(self, tmp_path: Path) -> Path:
        return tmp_path / "runs" / "e2e_run"

    @pytest.fixture()
    def scheduler(self, tmp_path: Path) -> BranchScheduler:
        return BranchScheduler(
            n_branches=3,
            output_dir=tmp_path,
            divergence_strategy="diverse",
            knob_ranges={
                "FP_CORE_UTIL": (30.0, 70.0),
                "FP_ASPECT_RATIO": (0.8, 1.5),
            },
            prune_delta_score=0.1,
            prune_patience_attempts=3,
        )

    async def test_e2e_3_branches_10_stages(
        self, tmp_path: Path, run_dir: Path
    ) -> None:
        """3 branches execute stages with mock scoring, pruning, manifest, report."""
        # 1. Zero-shot init
        initializer = ZeroShotInitializer()
        init_patch = await initializer.generate_init_patch(
            {"optimize_for": "balanced"}, "FLOORPLAN"
        )
        ZeroShotInitializer.write_init_patch(init_patch, run_dir)

        # 2. Create branches
        scheduler = BranchScheduler(
            n_branches=3,
            output_dir=tmp_path / "branches",
            divergence_strategy="diverse",
            knob_ranges={"FP_CORE_UTIL": (30.0, 70.0)},
        )
        branches = scheduler.create_branches(
            init_patch=init_patch.config_vars,
        )
        assert len(branches) == 3

        # 3. Setup tracking components
        manifest_builder = ManifestBuilder(
            run_id="e2e_run",
            config={"parallel_jobs": 2},
            seed=42,
        )
        manifest_builder.set_stages(10)

        pruning_engine = PruningEngine(
            prune_delta_score=0.15,
            prune_patience_attempts=3,
            min_attempts_before_prune=3,
        )
        plateau_detector = PlateauDetector(window_size=5, threshold=0.01)
        cycle_detector = CycleDetector()
        _deadlock_detector = DeadlockDetector(max_no_progress_attempts=10)
        checkpoint_mgr = CheckpointManager(runs_dir=tmp_path / "runs")

        all_branch_scores: dict[str, list[float]] = {}

        # 4. Execute branches in parallel
        runner = ParallelBranchRunner(max_parallel_jobs=2)

        branch_infos = [
            {
                "branch_id": b.branch_id,
                "workspace_root": str(b.workspace_root),
                "init_patch": b.init_patch,
            }
            for b in branches
        ]

        async def branch_executor(
            branch_id: str,
            workspace: Path,
            init_patch_arg: dict[str, Any] | None,
        ) -> BranchResult:
            return await _simulate_branch_execution(
                branch_id,
                workspace,
                init_patch_arg,
                manifest_builder=manifest_builder,
                pruning_engine=pruning_engine,
                all_branch_scores=all_branch_scores,
                plateau_detector=plateau_detector,
                cycle_detector=cycle_detector,
                checkpoint_mgr=checkpoint_mgr,
            )

        parallel_result = await runner.run_branches(branch_infos, branch_executor)

        # 5. Verify branches executed
        assert parallel_result.total_branches == 3
        # All branches return success=True (even pruned ones)
        assert parallel_result.completed_branches == 3

        # 6. Check pruning occurred
        # B1 should have been pruned (low scores vs B0's high scores)
        b1_result = next(
            br for br in parallel_result.branch_results if br.branch_id == "B1"
        )
        assert b1_result.stages_completed < 10  # pruned early

        # B0 should complete all stages
        b0_result = next(
            br for br in parallel_result.branch_results if br.branch_id == "B0"
        )
        assert b0_result.stages_completed == 10

        # 7. Select best branch
        pruned_ids: set[str] = set()
        for br in parallel_result.branch_results:
            if br.stages_completed < 10:
                pruned_ids.add(br.branch_id)

        selection = pruning_engine.select_winner(
            all_branch_scores,
            pruned_ids=pruned_ids,
        )
        assert selection.winning_branch_id == "B0"
        assert selection.winning_score is not None
        assert selection.winning_score > 0.8

        # Record branch results in manifest
        for br in parallel_result.branch_results:
            status = "completed" if br.stages_completed == 10 else "pruned"
            manifest_builder.record_branch(
                br.branch_id,
                status=status,
                best_score=br.final_score,
                stages_completed=br.stages_completed,
            )

        manifest_builder.set_winner("B0", selection.winning_score)

        # 8. Finalize manifest
        manifest = manifest_builder.finalize()
        manifest_path = ManifestBuilder.write_manifest(manifest, run_dir)
        assert manifest_path.exists()

        # 9. Verify manifest contents
        loaded = ManifestBuilder.load_manifest(manifest_path)
        assert loaded.run_id == "e2e_run"
        assert loaded.random_seed == 42
        assert loaded.best_branch_id == "B0"
        assert loaded.total_stages == 10
        assert len(loaded.decisions) > 0
        assert loaded.duration_seconds is not None
        assert loaded.python_version
        assert loaded.platform_info

        # 10. Generate report
        manifest_data = json.loads(manifest_path.read_text())
        report = ReportGenerator.from_manifest(manifest_data)
        assert report.run_id == "e2e_run"
        assert report.best_branch_id == "B0"
        assert len(report.branch_reports) == 3

        terminal_output = ReportGenerator.render_terminal(report)
        assert "e2e_run" in terminal_output
        assert "B0" in terminal_output

        json_output = ReportGenerator.to_json(report)
        parsed = json.loads(json_output)
        assert parsed["run_id"] == "e2e_run"

    async def test_e2e_parallel_execution(self, tmp_path: Path) -> None:
        """Branches run concurrently (verified by peak_concurrent)."""
        runner = ParallelBranchRunner(max_parallel_jobs=2)

        async def slow_executor(
            branch_id: str,
            workspace: Path,
            init_patch: dict[str, Any] | None,
        ) -> BranchResult:
            await asyncio.sleep(0.02)
            return BranchResult(
                branch_id=branch_id,
                success=True,
                final_score=0.5,
                stages_completed=10,
            )

        branches = [
            {"branch_id": f"B{i}", "workspace_root": str(tmp_path / f"B{i}")}
            for i in range(3)
        ]
        result = await runner.run_branches(branches, slow_executor)
        assert result.completed_branches == 3
        assert runner.peak_concurrent <= 2

    async def test_e2e_pruning_occurs(self, tmp_path: Path) -> None:
        """At least one branch gets pruned during execution."""
        engine = PruningEngine(
            prune_delta_score=0.1,
            prune_patience_attempts=3,
            min_attempts_before_prune=3,
        )

        # B0 improving, B1 stagnant and low
        branch_scores: dict[str, list[float]] = {
            "B0": [0.5, 0.6, 0.7, 0.8],
            "B1": [0.3, 0.28, 0.25, 0.22],
        }

        decisions = engine.evaluate_all_branches(branch_scores)
        pruned = [d for d in decisions if d.should_prune]
        assert len(pruned) >= 1
        assert any(d.branch_id == "B1" for d in pruned)

    async def test_e2e_best_branch_selected(self, tmp_path: Path) -> None:
        """Winning branch has highest composite score."""
        engine = PruningEngine()
        branch_scores: dict[str, list[float]] = {
            "B0": [0.5, 0.6, 0.7, 0.85],
            "B1": [0.3, 0.28, 0.25],  # pruned
            "B2": [0.4, 0.45, 0.5, 0.58],
        }
        result = engine.select_winner(branch_scores, pruned_ids={"B1"})
        assert result.winning_branch_id == "B0"
        assert result.winning_score == 0.85

    async def test_e2e_manifest_complete(self, tmp_path: Path) -> None:
        """manifest.json has full provenance."""
        builder = ManifestBuilder(run_id="e2e_test", config={"k": "v"}, seed=123)
        builder.set_stages(10)
        builder.record_decision(
            StageDecision(
                stage="SYNTH",
                branch_id="B0",
                attempt=1,
                action="accept",
                composite_score=0.7,
            )
        )
        builder.record_branch("B0", "completed", best_score=0.85, stages_completed=10)
        builder.set_winner("B0", 0.85)
        manifest = builder.finalize()

        path = ManifestBuilder.write_manifest(manifest, tmp_path)
        loaded = ManifestBuilder.load_manifest(path)

        assert loaded.python_version
        assert loaded.platform_info
        assert loaded.resolved_config == {"k": "v"}
        assert loaded.random_seed == 123
        assert loaded.best_branch_id == "B0"
        assert loaded.duration_seconds is not None
        assert len(loaded.decisions) == 1

    async def test_e2e_report_generated(self, tmp_path: Path) -> None:
        """Report command works on completed run data."""
        manifest_data: dict[str, Any] = {
            "run_id": "e2e_report_test",
            "best_branch_id": "B0",
            "best_composite_score": 0.85,
            "branches": {
                "B0": {
                    "status": "completed",
                    "best_score": 0.85,
                    "stages_completed": 10,
                },
                "B1": {
                    "status": "pruned",
                    "best_score": 0.3,
                    "stages_completed": 3,
                },
            },
            "decisions": [
                {
                    "stage": "SYNTH",
                    "branch_id": "B0",
                    "attempt": 1,
                    "action": "accept",
                    "composite_score": 0.7,
                },
            ],
        }

        report = ReportGenerator.from_manifest(manifest_data)
        assert report.run_id == "e2e_report_test"
        assert report.completed_branches == 1
        assert report.pruned_branches == 1

        terminal = ReportGenerator.render_terminal(report)
        assert "e2e_report_test" in terminal

        json_str = ReportGenerator.to_json(report)
        parsed = json.loads(json_str)
        assert parsed["best_branch_id"] == "B0"

    async def test_e2e_checkpoint_and_resume(self, tmp_path: Path) -> None:
        """Checkpoint written and resume state detected."""
        mgr = CheckpointManager(runs_dir=tmp_path)

        cp = Checkpoint(
            run_id="e2e_run",
            current_stage="CTS",
            last_attempt=6,
            branch_id="B0",
            composite_score=0.75,
        )
        attempt_dir = tmp_path / "e2e_run" / "attempt_006"
        mgr.write_checkpoint(cp, attempt_dir)

        state = mgr.get_resume_state("e2e_run")
        assert state is not None
        assert state["resume_stage"] == "CTS"
        assert state["resume_attempt"] == 6

        resumed = mgr.create_resume_checkpoint(
            state["checkpoint"], state["checkpoint_path"]
        )
        assert resumed.resumed is True

    async def test_e2e_plateau_detection_during_run(self) -> None:
        """Plateau detector identifies stagnation in branch scores."""
        detector = PlateauDetector(window_size=5, threshold=0.01)

        # B2's moderate scores plateau toward the end
        b2_scores = [0.40, 0.42, 0.44, 0.46, 0.48, 0.50, 0.52, 0.54, 0.56, 0.58]
        assert not detector.is_plateau(b2_scores)

        # Flat scores trigger plateau
        flat_scores = [0.50, 0.501, 0.502, 0.503, 0.504]
        assert detector.is_plateau(flat_scores)

        info = detector.get_plateau_info(flat_scores)
        assert info is not None
        assert info["range"] < 0.01

    async def test_e2e_cycle_detection_unique_patches(self) -> None:
        """Cycle detector sees no cycles for unique per-stage patches."""
        detector = CycleDetector()

        for i, stage in enumerate(STAGES):
            patch_data: dict[str, Any] = {
                "branch_id": "B0",
                "stage": stage,
                "score": BRANCH_SCORES["B0"][i],
            }
            is_cycle, _ = detector.check_and_record(patch_data, i + 1)
            assert not is_cycle

        # Repeating the same patch triggers a cycle
        dup_data: dict[str, Any] = {
            "branch_id": "B0",
            "stage": "SYNTH",
            "score": BRANCH_SCORES["B0"][0],
        }
        is_cycle, prev_attempt = detector.check_and_record(dup_data, 11)
        assert is_cycle
        assert prev_attempt == 1

    async def test_e2e_deadlock_detector_no_false_positive(self) -> None:
        """Deadlock detector does not fire on healthy B0 scores."""
        detector = DeadlockDetector(
            max_no_progress_attempts=10, progress_threshold=0.005
        )
        b0_scores = list(BRANCH_SCORES["B0"])
        # B0 has consistent improvement, no deadlock
        assert not detector.check_deadlock(b0_scores)

    async def test_e2e_deadlock_detector_fires_on_stagnation(self) -> None:
        """Deadlock detector fires when scores are flat for too long."""
        detector = DeadlockDetector(
            max_no_progress_attempts=5, progress_threshold=0.005
        )
        # 7 flat scores (6 gaps, all below threshold)
        stagnant = [0.50, 0.501, 0.502, 0.503, 0.504, 0.505, 0.506]
        assert detector.check_deadlock(stagnant)

    async def test_e2e_scheduler_creates_divergent_branches(
        self, scheduler: BranchScheduler
    ) -> None:
        """BranchScheduler produces branches with distinct knob sets."""
        branches = scheduler.create_branches()
        assert len(branches) == 3

        # Each branch should have a unique workspace
        workspaces = {str(b.workspace_root) for b in branches}
        assert len(workspaces) == 3

        # Branches should have divergent config_vars from DiverseSamplingStrategy
        knob_vals: list[float] = []
        for b in branches:
            if b.init_patch and "config_vars" in b.init_patch:
                cv = b.init_patch["config_vars"]
                if isinstance(cv, dict) and "FP_CORE_UTIL" in cv:
                    knob_vals.append(float(cv["FP_CORE_UTIL"]))

        # With 3 branches and range (30, 70), we expect 3 distinct values
        assert len(knob_vals) == 3
        assert len(set(knob_vals)) == 3  # all different
