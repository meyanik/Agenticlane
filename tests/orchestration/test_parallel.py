"""Tests for parallel branch execution (P5.2)."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from agenticlane.orchestration.parallel import (
    BranchResult,
    ParallelBranchRunner,
)


async def _mock_executor(
    branch_id: str, workspace: Path, init_patch: dict | None
) -> BranchResult:
    """Simple mock executor that succeeds with a score based on branch ID."""
    # Small delay to simulate work
    await asyncio.sleep(0.01)
    score = float(hash(branch_id) % 100) / 100.0
    return BranchResult(
        branch_id=branch_id,
        success=True,
        final_score=score,
        stages_completed=10,
        artifacts_dir=workspace,
    )


async def _failing_executor(
    branch_id: str, workspace: Path, init_patch: dict | None
) -> BranchResult:
    """Mock executor that fails for B1."""
    await asyncio.sleep(0.01)
    if branch_id == "B1":
        raise RuntimeError("Simulated failure in B1")
    return BranchResult(
        branch_id=branch_id,
        success=True,
        final_score=0.5,
        stages_completed=10,
    )


async def _slow_executor(
    branch_id: str, workspace: Path, init_patch: dict | None
) -> BranchResult:
    """Slow executor to test semaphore limiting."""
    await asyncio.sleep(0.05)
    return BranchResult(
        branch_id=branch_id,
        success=True,
        final_score=0.5,
        stages_completed=5,
    )


def _make_branches(n: int, tmp_path: Path) -> list[dict]:
    return [
        {
            "branch_id": f"B{i}",
            "workspace_root": str(tmp_path / f"B{i}"),
            "init_patch": {"FP_CORE_UTIL": 40 + i},
        }
        for i in range(n)
    ]


class TestParallelBranchRunner:
    @pytest.mark.asyncio
    async def test_all_branches_complete(self, tmp_path: Path) -> None:
        runner = ParallelBranchRunner(max_parallel_jobs=3)
        branches = _make_branches(3, tmp_path)
        result = await runner.run_branches(branches, _mock_executor)
        assert result.total_branches == 3
        assert result.completed_branches == 3
        assert result.failed_branches == 0

    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrency(self, tmp_path: Path) -> None:
        runner = ParallelBranchRunner(max_parallel_jobs=2)
        branches = _make_branches(4, tmp_path)
        result = await runner.run_branches(branches, _slow_executor)
        assert result.total_branches == 4
        assert result.completed_branches == 4
        assert runner.peak_concurrent <= 2

    @pytest.mark.asyncio
    async def test_failure_in_one_doesnt_affect_others(self, tmp_path: Path) -> None:
        runner = ParallelBranchRunner(max_parallel_jobs=3)
        branches = _make_branches(3, tmp_path)
        result = await runner.run_branches(branches, _failing_executor)
        assert result.completed_branches == 2
        assert result.failed_branches == 1
        # B0 and B2 should succeed
        success_ids = {br.branch_id for br in result.branch_results if br.success}
        assert "B0" in success_ids
        assert "B2" in success_ids

    @pytest.mark.asyncio
    async def test_best_branch_selected(self, tmp_path: Path) -> None:
        runner = ParallelBranchRunner(max_parallel_jobs=3)
        branches = _make_branches(3, tmp_path)
        result = await runner.run_branches(branches, _mock_executor)
        assert result.best_branch_id is not None
        assert result.best_score is not None

    @pytest.mark.asyncio
    async def test_isolation_no_shared_writes(self, tmp_path: Path) -> None:
        """Each branch gets its own workspace path."""
        runner = ParallelBranchRunner(max_parallel_jobs=3)
        branches = _make_branches(3, tmp_path)
        result = await runner.run_branches(branches, _mock_executor)
        workspace_roots = {
            br.artifacts_dir for br in result.branch_results if br.artifacts_dir
        }
        # All workspace roots should be unique
        assert len(workspace_roots) == 3

    @pytest.mark.asyncio
    async def test_single_branch(self, tmp_path: Path) -> None:
        runner = ParallelBranchRunner(max_parallel_jobs=1)
        branches = _make_branches(1, tmp_path)
        result = await runner.run_branches(branches, _mock_executor)
        assert result.total_branches == 1
        assert result.completed_branches == 1

    @pytest.mark.asyncio
    async def test_empty_branches(self, tmp_path: Path) -> None:
        runner = ParallelBranchRunner(max_parallel_jobs=2)
        result = await runner.run_branches([], _mock_executor)
        assert result.total_branches == 0
        assert result.completed_branches == 0

    @pytest.mark.asyncio
    async def test_error_captured_in_result(self, tmp_path: Path) -> None:
        runner = ParallelBranchRunner(max_parallel_jobs=3)
        branches = _make_branches(3, tmp_path)
        result = await runner.run_branches(branches, _failing_executor)
        failed = [br for br in result.branch_results if not br.success]
        assert len(failed) == 1
        assert failed[0].branch_id == "B1"
        assert "Simulated failure" in (failed[0].error or "")

    @pytest.mark.asyncio
    async def test_init_patch_passed_to_executor(self, tmp_path: Path) -> None:
        """Executor receives the init_patch from branch config."""
        received_patches: list[dict | None] = []

        async def capturing_executor(
            branch_id: str, workspace: Path, init_patch: dict | None
        ) -> BranchResult:
            received_patches.append(init_patch)
            return BranchResult(branch_id=branch_id, success=True, final_score=0.5)

        runner = ParallelBranchRunner(max_parallel_jobs=3)
        branches = _make_branches(3, tmp_path)
        await runner.run_branches(branches, capturing_executor)
        assert len(received_patches) == 3
        assert all(p is not None for p in received_patches)
