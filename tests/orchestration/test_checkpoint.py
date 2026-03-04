"""Tests for checkpoint + resume (P5.11)."""
from __future__ import annotations

import json
from pathlib import Path

from agenticlane.orchestration.checkpoint import (
    Checkpoint,
    CheckpointManager,
)


class TestCheckpoint:
    def test_checkpoint_defaults(self) -> None:
        cp = Checkpoint(run_id="run_001", current_stage="FLOORPLAN", last_attempt=3)
        assert cp.run_id == "run_001"
        assert cp.current_stage == "FLOORPLAN"
        assert cp.last_attempt == 3
        assert cp.timestamp  # auto-populated
        assert cp.resumed is False
        assert cp.resume_from is None

    def test_checkpoint_contains_state(self) -> None:
        cp = Checkpoint(
            run_id="run_001",
            current_stage="CTS",
            last_attempt=5,
            branch_id="B0",
            branch_tip={"B0": {"stage": "CTS", "attempt": 5, "score": 0.8}},
            composite_score=0.8,
            config_snapshot={"FP_CORE_UTIL": 50},
        )
        assert cp.branch_id == "B0"
        assert cp.composite_score == 0.8
        assert cp.config_snapshot["FP_CORE_UTIL"] == 50


class TestCheckpointManager:
    def test_write_checkpoint(self, tmp_path: Path) -> None:
        mgr = CheckpointManager(runs_dir=tmp_path)
        cp = Checkpoint(run_id="run_001", current_stage="FLOORPLAN", last_attempt=1)
        attempt_dir = tmp_path / "run_001" / "attempt_001"
        path = mgr.write_checkpoint(cp, attempt_dir)
        assert path.exists()
        assert path.name == "checkpoint.json"
        data = json.loads(path.read_text())
        assert data["run_id"] == "run_001"

    def test_load_checkpoint(self, tmp_path: Path) -> None:
        mgr = CheckpointManager(runs_dir=tmp_path)
        cp = Checkpoint(run_id="run_001", current_stage="CTS", last_attempt=3)
        attempt_dir = tmp_path / "run_001" / "attempt_003"
        path = mgr.write_checkpoint(cp, attempt_dir)
        loaded = mgr.load_checkpoint(path)
        assert loaded.run_id == "run_001"
        assert loaded.current_stage == "CTS"
        assert loaded.last_attempt == 3

    def test_find_latest_checkpoint(self, tmp_path: Path) -> None:
        mgr = CheckpointManager(runs_dir=tmp_path)

        # Write checkpoints at attempt 1 and 3
        for attempt_num in [1, 3]:
            cp = Checkpoint(
                run_id="run_001",
                current_stage="FLOORPLAN",
                last_attempt=attempt_num,
            )
            attempt_dir = tmp_path / "run_001" / f"attempt_{attempt_num:03d}"
            mgr.write_checkpoint(cp, attempt_dir)

        latest = mgr.find_latest_checkpoint("run_001")
        assert latest is not None
        loaded = mgr.load_checkpoint(latest)
        assert loaded.last_attempt == 3

    def test_find_no_checkpoint(self, tmp_path: Path) -> None:
        mgr = CheckpointManager(runs_dir=tmp_path)
        assert mgr.find_latest_checkpoint("nonexistent") is None

    def test_resume_detects_checkpoint(self, tmp_path: Path) -> None:
        mgr = CheckpointManager(runs_dir=tmp_path)
        cp = Checkpoint(run_id="run_001", current_stage="PLACE_GLOBAL", last_attempt=2)
        attempt_dir = tmp_path / "run_001" / "attempt_002"
        mgr.write_checkpoint(cp, attempt_dir)

        state = mgr.get_resume_state("run_001")
        assert state is not None
        assert state["resume_stage"] == "PLACE_GLOBAL"
        assert state["resume_attempt"] == 2

    def test_resume_restores_state(self, tmp_path: Path) -> None:
        mgr = CheckpointManager(runs_dir=tmp_path)
        cp = Checkpoint(
            run_id="run_001",
            current_stage="CTS",
            last_attempt=4,
            branch_id="B1",
            composite_score=0.75,
            config_snapshot={"FP_CORE_UTIL": 55},
        )
        attempt_dir = tmp_path / "run_001" / "attempt_004"
        mgr.write_checkpoint(cp, attempt_dir)

        state = mgr.get_resume_state("run_001")
        assert state is not None
        restored = state["checkpoint"]
        assert restored.branch_id == "B1"
        assert restored.composite_score == 0.75
        assert restored.config_snapshot["FP_CORE_UTIL"] == 55

    def test_resume_status_in_checkpoint(self, tmp_path: Path) -> None:
        mgr = CheckpointManager(runs_dir=tmp_path)
        original = Checkpoint(
            run_id="run_001", current_stage="CTS", last_attempt=4
        )
        cp_path = tmp_path / "run_001" / "attempt_004" / "checkpoint.json"
        mgr.write_checkpoint(original, cp_path.parent)

        resumed = mgr.create_resume_checkpoint(original, cp_path)
        assert resumed.resumed is True
        assert resumed.resume_from == str(cp_path)
        assert resumed.current_stage == "CTS"

    def test_no_checkpoint_no_resume(self, tmp_path: Path) -> None:
        mgr = CheckpointManager(runs_dir=tmp_path)
        (tmp_path / "run_001").mkdir()  # empty run dir
        state = mgr.get_resume_state("run_001")
        assert state is None

    def test_checkpoint_roundtrip_with_branch_tip(self, tmp_path: Path) -> None:
        mgr = CheckpointManager(runs_dir=tmp_path)
        cp = Checkpoint(
            run_id="run_001",
            current_stage="ROUTE_DETAILED",
            last_attempt=7,
            branch_tip={
                "B0": {"stage": "ROUTE_DETAILED", "attempt": 7, "score": 0.85},
                "B1": {"stage": "CTS", "attempt": 5, "score": 0.72},
            },
        )
        attempt_dir = tmp_path / "run_001" / "attempt_007"
        path = mgr.write_checkpoint(cp, attempt_dir)
        loaded = mgr.load_checkpoint(path)
        assert loaded.branch_tip is not None
        assert loaded.branch_tip["B0"]["score"] == 0.85
        assert loaded.branch_tip["B1"]["stage"] == "CTS"
