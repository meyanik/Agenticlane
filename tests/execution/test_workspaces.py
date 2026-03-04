"""Tests for the WorkspaceManager."""

from __future__ import annotations

from pathlib import Path

import pytest

from agenticlane.execution.workspaces import WorkspaceManager


@pytest.fixture
def ws() -> WorkspaceManager:
    return WorkspaceManager()


class TestCreateAttemptDir:
    """Verify attempt directory creation and structure."""

    def test_create_attempt_dir(self, tmp_path: Path, ws: WorkspaceManager) -> None:
        """Creates the correct directory structure with all sub-dirs."""
        branch_dir = ws.create_branch_dir(
            ws.create_run_dir(tmp_path, "run_001"), "main"
        )
        attempt = ws.create_attempt_dir(branch_dir, "synth", 1)

        assert attempt.exists()
        assert attempt.name == "attempt_001"

        for subdir in ("proposals", "constraints", "workspace", "artifacts"):
            assert (attempt / subdir).is_dir(), f"Missing sub-directory: {subdir}"

    def test_attempt_dir_numbering(
        self, tmp_path: Path, ws: WorkspaceManager
    ) -> None:
        """Sequential attempts get incrementing, zero-padded numbers."""
        branch_dir = ws.create_branch_dir(
            ws.create_run_dir(tmp_path, "run_002"), "main"
        )

        a1 = ws.create_attempt_dir(branch_dir, "floorplan", 1)
        a2 = ws.create_attempt_dir(branch_dir, "floorplan", 2)
        a3 = ws.create_attempt_dir(branch_dir, "floorplan", 3)

        assert a1.name == "attempt_001"
        assert a2.name == "attempt_002"
        assert a3.name == "attempt_003"

        # All must be siblings under the same stage directory.
        assert a1.parent == a2.parent == a3.parent


class TestGetNextAttemptNum:
    """Verify the automatic attempt numbering logic."""

    def test_get_next_attempt_num_empty(
        self, tmp_path: Path, ws: WorkspaceManager
    ) -> None:
        """Returns 1 when no attempts exist yet."""
        branch_dir = ws.create_branch_dir(
            ws.create_run_dir(tmp_path, "run_003"), "main"
        )
        assert ws.get_next_attempt_num(branch_dir, "synth") == 1

    def test_get_next_attempt_num_sequential(
        self, tmp_path: Path, ws: WorkspaceManager
    ) -> None:
        """Returns the correct next number after creating several attempts."""
        branch_dir = ws.create_branch_dir(
            ws.create_run_dir(tmp_path, "run_004"), "main"
        )

        ws.create_attempt_dir(branch_dir, "cts", 1)
        ws.create_attempt_dir(branch_dir, "cts", 2)

        assert ws.get_next_attempt_num(branch_dir, "cts") == 3

    def test_get_next_attempt_num_gap(
        self, tmp_path: Path, ws: WorkspaceManager
    ) -> None:
        """If there is a gap (e.g. attempt_001 and attempt_005), returns
        max + 1, not gap-fill."""
        branch_dir = ws.create_branch_dir(
            ws.create_run_dir(tmp_path, "run_005"), "main"
        )

        ws.create_attempt_dir(branch_dir, "route", 1)
        ws.create_attempt_dir(branch_dir, "route", 5)

        assert ws.get_next_attempt_num(branch_dir, "route") == 6


class TestIsolation:
    """Verify that different stages / attempts are isolated."""

    def test_isolation_between_attempts(
        self, tmp_path: Path, ws: WorkspaceManager
    ) -> None:
        """Files written in one attempt directory do not appear in another."""
        branch_dir = ws.create_branch_dir(
            ws.create_run_dir(tmp_path, "run_006"), "main"
        )

        a1 = ws.create_attempt_dir(branch_dir, "synth", 1)
        a2 = ws.create_attempt_dir(branch_dir, "synth", 2)

        # Write a file in attempt_001
        sentinel = a1 / "workspace" / "sentinel.txt"
        sentinel.write_text("hello")

        # It must not be visible in attempt_002
        assert not (a2 / "workspace" / "sentinel.txt").exists()


class TestCloneWorkspace:
    """Verify workspace cloning strategies."""

    def test_clone_via_hardlink(
        self, tmp_path: Path, ws: WorkspaceManager
    ) -> None:
        """Default strategy creates hardlinks (same inode)."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "file.txt").write_text("content")
        (src / "sub").mkdir()
        (src / "sub" / "nested.txt").write_text("nested")

        dst = tmp_path / "dst"
        ws.clone_workspace(src, dst)

        assert (dst / "file.txt").read_text() == "content"
        assert (dst / "sub" / "nested.txt").read_text() == "nested"

        # On the same filesystem, hardlinks should share the inode.
        assert (
            (dst / "file.txt").stat().st_ino == (src / "file.txt").stat().st_ino
        )

    def test_clone_via_copy(
        self, tmp_path: Path, ws: WorkspaceManager
    ) -> None:
        """Explicit 'copy' strategy uses shutil.copytree (different inode)."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "file.txt").write_text("content")

        dst = tmp_path / "dst"
        ws.clone_workspace(src, dst, strategy="copy")

        assert (dst / "file.txt").read_text() == "content"
        # Copy should produce a distinct inode.
        assert (
            (dst / "file.txt").stat().st_ino != (src / "file.txt").stat().st_ino
        )
