"""Parallel Job Scheduling for AgenticLane (P5.2).

Provides asyncio-based concurrent branch execution with semaphore-limited
parallelism.  Each branch runs in an isolated workspace directory and is
executed by a user-supplied *BranchExecutor* coroutine.

Key components
--------------
- BranchResult: outcome of a single branch execution
- ParallelExecutionResult: aggregate outcome of all branches
- ParallelBranchRunner: semaphore-gated parallel runner
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class BranchResult:
    """Result from executing a single branch."""

    branch_id: str
    success: bool
    final_score: float | None = None
    stages_completed: int = 0
    error: str | None = None
    artifacts_dir: Path | None = None


@dataclass
class ParallelExecutionResult:
    """Result from executing all branches in parallel."""

    branch_results: list[BranchResult] = field(default_factory=list)
    total_branches: int = 0
    completed_branches: int = 0
    failed_branches: int = 0
    best_branch_id: str | None = None
    best_score: float | None = None


# Type alias for the async function that executes a single branch.
BranchExecutor = Callable[[str, Path, dict | None], Coroutine[Any, Any, BranchResult]]


class ParallelBranchRunner:
    """Execute multiple branches concurrently with semaphore-limited parallelism.

    Uses :class:`asyncio.Semaphore` to limit how many branches run
    simultaneously.  Each branch gets its own isolated workspace directory.
    """

    def __init__(
        self,
        *,
        max_parallel_jobs: int = 2,
    ) -> None:
        self._max_parallel = max_parallel_jobs
        self._semaphore: asyncio.Semaphore | None = None
        self._active_count: int = 0
        self._peak_concurrent: int = 0
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run_branches(
        self,
        branches: list[dict],  # list of {branch_id, workspace_root, init_patch}
        executor: BranchExecutor,
    ) -> ParallelExecutionResult:
        """Run all branches concurrently, limited by semaphore.

        Args:
            branches: List of branch info dicts with keys ``branch_id``,
                ``workspace_root``, and optionally ``init_patch``.
            executor: Async function that executes a single branch.

        Returns:
            :class:`ParallelExecutionResult` with all branch outcomes.
        """
        self._semaphore = asyncio.Semaphore(self._max_parallel)
        self._active_count = 0
        self._peak_concurrent = 0

        tasks = [self._run_with_semaphore(b, executor) for b in branches]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        branch_results: list[BranchResult] = []
        for i, result in enumerate(results):
            if isinstance(result, BaseException):
                branch_results.append(
                    BranchResult(
                        branch_id=branches[i]["branch_id"],
                        success=False,
                        error=str(result),
                    )
                )
            else:
                assert isinstance(result, BranchResult)
                branch_results.append(result)

        # Find best scoring successful branch
        best_id: str | None = None
        best_score: float | None = None
        for br in branch_results:
            if (
                br.success
                and br.final_score is not None
                and (best_score is None or br.final_score > best_score)
            ):
                best_score = br.final_score
                best_id = br.branch_id

        completed = sum(1 for br in branch_results if br.success)
        failed = sum(1 for br in branch_results if not br.success)

        return ParallelExecutionResult(
            branch_results=branch_results,
            total_branches=len(branches),
            completed_branches=completed,
            failed_branches=failed,
            best_branch_id=best_id,
            best_score=best_score,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _run_with_semaphore(
        self,
        branch: dict,
        executor: BranchExecutor,
    ) -> BranchResult:
        """Run a single branch, acquiring the semaphore first."""
        assert self._semaphore is not None  # noqa: S101
        async with self._semaphore:
            async with self._lock:
                self._active_count += 1
                self._peak_concurrent = max(self._peak_concurrent, self._active_count)
            try:
                result = await executor(
                    branch["branch_id"],
                    Path(branch["workspace_root"]),
                    branch.get("init_patch"),
                )
            except Exception as exc:
                logger.error("Branch %s failed: %s", branch["branch_id"], exc)
                return BranchResult(
                    branch_id=branch["branch_id"],
                    success=False,
                    error=str(exc),
                )
            else:
                return result
            finally:
                async with self._lock:
                    self._active_count -= 1

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def peak_concurrent(self) -> int:
        """Return peak number of concurrently running branches."""
        return self._peak_concurrent
