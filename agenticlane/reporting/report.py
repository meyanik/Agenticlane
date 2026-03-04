from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class BranchReport:
    """Summary of a single branch's performance."""

    branch_id: str
    status: str
    best_score: float | None = None
    stages_completed: int = 0
    total_attempts: int = 0


@dataclass
class StageReport:
    """Summary of a stage across all branches."""

    stage_name: str
    branches: dict[str, dict[str, Any]] = field(default_factory=dict)
    best_branch: str | None = None
    best_score: float | None = None


@dataclass
class RunReport:
    """Complete run report."""

    run_id: str
    status: str = "unknown"
    best_branch_id: str | None = None
    best_score: float | None = None
    total_branches: int = 0
    completed_branches: int = 0
    pruned_branches: int = 0
    failed_branches: int = 0
    total_stages: int = 0
    total_attempts: int = 0
    duration_seconds: float | None = None
    branch_reports: list[BranchReport] = field(default_factory=list)
    stage_reports: list[StageReport] = field(default_factory=list)


class ReportGenerator:
    """Generate reports from run manifest data."""

    @staticmethod
    def from_manifest(manifest_data: dict[str, Any]) -> RunReport:
        """Generate a RunReport from manifest.json data."""
        branches = manifest_data.get("branches", {})
        decisions = manifest_data.get("decisions", [])

        branch_reports = []
        completed = 0
        pruned = 0
        failed = 0
        for bid, bdata in sorted(branches.items()):
            status = bdata.get("status", "unknown")
            if status == "completed":
                completed += 1
            elif status == "pruned":
                pruned += 1
            elif status == "failed":
                failed += 1

            branch_attempts = sum(1 for d in decisions if d.get("branch_id") == bid)
            branch_reports.append(
                BranchReport(
                    branch_id=bid,
                    status=status,
                    best_score=bdata.get("best_score"),
                    stages_completed=bdata.get("stages_completed", 0),
                    total_attempts=branch_attempts,
                )
            )

        # Build stage reports from decisions
        stage_data: dict[str, dict[str, dict[str, Any]]] = {}
        for d in decisions:
            stage = d.get("stage", "unknown")
            bid = d.get("branch_id", "unknown")
            if stage not in stage_data:
                stage_data[stage] = {}
            stage_data[stage][bid] = {
                "action": d.get("action"),
                "score": d.get("composite_score"),
                "attempt": d.get("attempt"),
            }

        stage_reports = []
        for stage_name, branch_info in sorted(stage_data.items()):
            best_bid = None
            best_s = None
            for bid, info in branch_info.items():
                s = info.get("score")
                if s is not None and (best_s is None or s > best_s):
                    best_s = s
                    best_bid = bid
            stage_reports.append(
                StageReport(
                    stage_name=stage_name,
                    branches=branch_info,
                    best_branch=best_bid,
                    best_score=best_s,
                )
            )

        return RunReport(
            run_id=manifest_data.get("run_id", "unknown"),
            status="completed" if completed > 0 else "failed",
            best_branch_id=manifest_data.get("best_branch_id"),
            best_score=manifest_data.get("best_composite_score"),
            total_branches=len(branches),
            completed_branches=completed,
            pruned_branches=pruned,
            failed_branches=failed,
            total_stages=manifest_data.get("total_stages", len(stage_data)),
            total_attempts=manifest_data.get("total_attempts", len(decisions)),
            duration_seconds=manifest_data.get("duration_seconds"),
            branch_reports=branch_reports,
            stage_reports=stage_reports,
        )

    @staticmethod
    def to_json(report: RunReport) -> str:
        """Serialize report to JSON string."""
        from dataclasses import asdict

        return json.dumps(asdict(report), indent=2, default=str)

    @staticmethod
    def render_terminal(report: RunReport) -> str:
        """Render report as plain-text terminal output (no Rich dependency required).

        Returns a string suitable for printing to terminal.
        """
        lines: list[str] = []
        lines.append(f"=== Run Report: {report.run_id} ===")
        lines.append(f"Status: {report.status}")
        if report.best_branch_id:
            lines.append(
                f"Best Branch: {report.best_branch_id} (score: {report.best_score:.4f})"
            )
        lines.append(
            f"Branches: {report.total_branches} total, "
            f"{report.completed_branches} completed, "
            f"{report.pruned_branches} pruned, "
            f"{report.failed_branches} failed"
        )
        lines.append(f"Stages: {report.total_stages}, Attempts: {report.total_attempts}")
        if report.duration_seconds is not None:
            lines.append(f"Duration: {report.duration_seconds:.1f}s")
        lines.append("")

        # Branch table
        lines.append("--- Branches ---")
        lines.append(
            f"{'Branch':<10} {'Status':<12} {'Best Score':<12} {'Stages':<8} {'Attempts':<10}"
        )
        lines.append("-" * 52)
        for br in report.branch_reports:
            score_str = f"{br.best_score:.4f}" if br.best_score is not None else "N/A"
            lines.append(
                f"{br.branch_id:<10} {br.status:<12} {score_str:<12} "
                f"{br.stages_completed:<8} {br.total_attempts:<10}"
            )
        lines.append("")

        # Stage summary
        if report.stage_reports:
            lines.append("--- Stages ---")
            for sr in report.stage_reports:
                best_str = (
                    f" (best: {sr.best_branch}={sr.best_score:.4f})"
                    if sr.best_score is not None
                    else ""
                )
                lines.append(f"  {sr.stage_name}: {len(sr.branches)} branches{best_str}")

        return "\n".join(lines)
