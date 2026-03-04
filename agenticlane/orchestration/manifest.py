from __future__ import annotations

import json
import logging
import platform
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class StageDecision:
    """Record of a decision made at a stage."""

    stage: str
    branch_id: str
    attempt: int
    action: str  # "accept", "reject", "retry", "rollback", "prune"
    composite_score: float | None = None
    reason: str = ""
    timestamp: str = ""


@dataclass
class RunManifest:
    """Complete provenance record for a run."""

    # Identity
    run_id: str
    agenticlane_version: str = "0.1.0"
    python_version: str = ""
    platform_info: str = ""

    # Config
    resolved_config: dict[str, Any] = field(default_factory=dict)
    random_seed: int | None = None

    # Timing
    start_time: str = ""
    end_time: str = ""
    duration_seconds: float | None = None

    # Results
    best_branch_id: str | None = None
    best_composite_score: float | None = None
    total_stages: int = 0
    total_attempts: int = 0

    # Branch info
    branches: dict[str, dict[str, Any]] = field(default_factory=dict)

    # Decision log
    decisions: list[dict[str, Any]] = field(default_factory=list)

    # Flow mode
    flow_mode: str = "flat"

    # Hierarchical module results
    module_results: dict[str, dict[str, Any]] = field(default_factory=dict)

    # Metadata
    resumed: bool = False
    resume_from: str | None = None

    def __post_init__(self) -> None:
        if not self.python_version:
            self.python_version = sys.version
        if not self.platform_info:
            self.platform_info = platform.platform()


class ManifestBuilder:
    """Builds the manifest incrementally during a run."""

    def __init__(
        self,
        run_id: str,
        config: dict[str, Any] | None = None,
        seed: int | None = None,
    ) -> None:
        self._manifest = RunManifest(
            run_id=run_id,
            resolved_config=config or {},
            random_seed=seed,
            start_time=datetime.now(tz=timezone.utc).isoformat(),
        )

    def record_decision(self, decision: StageDecision) -> None:
        """Record a stage/branch decision."""
        if not decision.timestamp:
            decision.timestamp = datetime.now(tz=timezone.utc).isoformat()
        self._manifest.decisions.append(asdict(decision))
        self._manifest.total_attempts += 1

    def record_branch(
        self,
        branch_id: str,
        status: str,
        best_score: float | None = None,
        stages_completed: int = 0,
    ) -> None:
        """Record branch final state."""
        self._manifest.branches[branch_id] = {
            "status": status,
            "best_score": best_score,
            "stages_completed": stages_completed,
        }

    def set_winner(self, branch_id: str, score: float) -> None:
        """Set the winning branch."""
        self._manifest.best_branch_id = branch_id
        self._manifest.best_composite_score = score

    def set_stages(self, total: int) -> None:
        """Set total stages count."""
        self._manifest.total_stages = total

    def set_flow_mode(self, flow_mode: str) -> None:
        """Set the flow mode (flat/hierarchical)."""
        self._manifest.flow_mode = flow_mode

    def record_module(self, module_name: str, result: dict[str, Any]) -> None:
        """Record a hierarchical sub-module's result."""
        self._manifest.module_results[module_name] = result

    def set_resumed(self, resume_from: str) -> None:
        """Mark as resumed run."""
        self._manifest.resumed = True
        self._manifest.resume_from = resume_from

    def finalize(self) -> RunManifest:
        """Finalize the manifest with end time and duration."""
        self._manifest.end_time = datetime.now(tz=timezone.utc).isoformat()
        if self._manifest.start_time:
            start = datetime.fromisoformat(self._manifest.start_time)
            end = datetime.fromisoformat(self._manifest.end_time)
            self._manifest.duration_seconds = (end - start).total_seconds()
        return self._manifest

    @property
    def manifest(self) -> RunManifest:
        """Get current manifest state (without finalizing)."""
        return self._manifest

    @staticmethod
    def write_manifest(manifest: RunManifest, output_dir: Path) -> Path:
        """Write manifest.json to disk."""
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "manifest.json"
        data = asdict(manifest)
        path.write_text(json.dumps(data, indent=2, default=str) + "\n")
        logger.info("Wrote manifest.json to %s", path)
        return path

    @staticmethod
    def load_manifest(path: Path) -> RunManifest:
        """Load a manifest from disk."""
        data = json.loads(path.read_text())
        # Extract decisions and branches before creating RunManifest
        decisions = data.pop("decisions", [])
        branches = data.pop("branches", {})
        manifest = RunManifest(**data)
        manifest.decisions = decisions
        manifest.branches = branches
        return manifest
