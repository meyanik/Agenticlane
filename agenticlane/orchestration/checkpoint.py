"""Checkpoint + Resume for AgenticLane (P5.11).

Provides checkpoint writing after successful attempts and resume capability.
Checkpoints are serialized as JSON files in attempt directories, enabling
runs to be resumed from the last successful checkpoint.

Key components:
- Checkpoint: Serializable dataclass capturing run state at a point in time
- CheckpointManager: Manages writing, loading, finding, and resuming checkpoints
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Checkpoint:
    """Serializable checkpoint for resume capability."""

    run_id: str
    current_stage: str
    last_attempt: int
    branch_id: str | None = None
    branch_tip: dict[str, Any] | None = None  # branch_id -> {stage, attempt, score}
    composite_score: float | None = None
    config_snapshot: dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""
    resumed: bool = False
    resume_from: str | None = None  # path to checkpoint we resumed from

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(tz=timezone.utc).isoformat()


class CheckpointManager:
    """Manages checkpoint writing and loading for run resume capability."""

    CHECKPOINT_FILENAME = "checkpoint.json"

    def __init__(self, runs_dir: Path) -> None:
        self._runs_dir = runs_dir

    def write_checkpoint(
        self,
        checkpoint: Checkpoint,
        attempt_dir: Path,
    ) -> Path:
        """Write checkpoint to attempt directory.

        Args:
            checkpoint: The checkpoint data to write.
            attempt_dir: The attempt directory to write into.

        Returns:
            Path to the written checkpoint file.
        """
        attempt_dir.mkdir(parents=True, exist_ok=True)
        path = attempt_dir / self.CHECKPOINT_FILENAME
        data = asdict(checkpoint)
        path.write_text(json.dumps(data, indent=2, default=str) + "\n")
        logger.info("Wrote checkpoint to %s", path)
        return path

    def load_checkpoint(self, path: Path) -> Checkpoint:
        """Load a checkpoint from a file path.

        Args:
            path: Path to checkpoint.json file.

        Returns:
            Checkpoint instance.

        Raises:
            FileNotFoundError: If checkpoint file doesn't exist.
            json.JSONDecodeError: If checkpoint file is invalid JSON.
        """
        data = json.loads(path.read_text())
        return Checkpoint(**data)

    def find_latest_checkpoint(self, run_id: str) -> Path | None:
        """Find the latest checkpoint for a given run.

        Searches through run directory for checkpoint.json files,
        returns the one with the highest attempt number.

        Args:
            run_id: The run ID to search for.

        Returns:
            Path to latest checkpoint, or None if not found.
        """
        run_dir = self._runs_dir / run_id
        if not run_dir.exists():
            return None

        checkpoints: list[tuple[int, Path]] = []

        # Search in attempt directories (attempt_NNN/)
        for attempt_dir in sorted(run_dir.glob("**/attempt_*")):
            cp_path = attempt_dir / self.CHECKPOINT_FILENAME
            if cp_path.exists():
                # Extract attempt number from directory name
                try:
                    attempt_num = int(attempt_dir.name.split("_")[-1])
                except (ValueError, IndexError):
                    attempt_num = 0
                checkpoints.append((attempt_num, cp_path))

        # Also check run root
        root_cp = run_dir / self.CHECKPOINT_FILENAME
        if root_cp.exists():
            checkpoints.append((-1, root_cp))

        if not checkpoints:
            return None

        # Return the one with highest attempt number
        checkpoints.sort(key=lambda x: x[0], reverse=True)
        return checkpoints[0][1]

    def create_resume_checkpoint(
        self,
        original: Checkpoint,
        resume_path: Path,
    ) -> Checkpoint:
        """Create a new checkpoint marked as resumed.

        Args:
            original: The checkpoint being resumed from.
            resume_path: Path to the original checkpoint file.

        Returns:
            New Checkpoint with resumed=True and resume_from set.
        """
        return Checkpoint(
            run_id=original.run_id,
            current_stage=original.current_stage,
            last_attempt=original.last_attempt,
            branch_id=original.branch_id,
            branch_tip=original.branch_tip,
            composite_score=original.composite_score,
            config_snapshot=original.config_snapshot,
            resumed=True,
            resume_from=str(resume_path),
        )

    def get_resume_state(self, run_id: str) -> dict[str, Any] | None:
        """Get the state needed to resume a run.

        Returns None if no checkpoint found. Otherwise returns dict with:
        - checkpoint: The Checkpoint object
        - checkpoint_path: Path to the checkpoint file
        - resume_stage: Stage to resume from
        - resume_attempt: Attempt number to resume from
        """
        cp_path = self.find_latest_checkpoint(run_id)
        if cp_path is None:
            return None

        checkpoint = self.load_checkpoint(cp_path)

        return {
            "checkpoint": checkpoint,
            "checkpoint_path": cp_path,
            "resume_stage": checkpoint.current_stage,
            "resume_attempt": checkpoint.last_attempt,
        }
