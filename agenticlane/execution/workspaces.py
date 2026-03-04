"""Workspace and attempt directory manager.

Creates the hierarchical run directory structure used by AgenticLane:

    runs/<run_id>/
      branches/<branch_id>/
        stages/<stage>/
          attempt_001/
            proposals/
            constraints/
            workspace/
            artifacts/

Supports hardlink-based workspace cloning for state baton handoff,
with a ``shutil.copytree`` fallback when hardlinks are unavailable
(e.g. cross-filesystem copies).
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

# Sub-directories created inside every attempt directory.
_ATTEMPT_SUBDIRS = ("proposals", "constraints", "workspace", "artifacts")


class WorkspaceManager:
    """Manages the run/branch/attempt directory hierarchy."""

    # ------------------------------------------------------------------
    # Directory creation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def create_run_dir(run_root: Path, run_id: str) -> Path:
        """Create and return ``<run_root>/runs/<run_id>``."""
        run_dir = run_root / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Created run directory: %s", run_dir)
        return run_dir

    @staticmethod
    def create_branch_dir(run_dir: Path, branch_id: str) -> Path:
        """Create and return ``<run_dir>/branches/<branch_id>``."""
        branch_dir = run_dir / "branches" / branch_id
        branch_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Created branch directory: %s", branch_dir)
        return branch_dir

    @staticmethod
    def create_attempt_dir(
        branch_dir: Path,
        stage_name: str,
        attempt_num: int,
    ) -> Path:
        """Create an attempt directory with standard sub-directories.

        The directory layout is::

            <branch_dir>/stages/<stage_name>/attempt_<NNN>/
              proposals/
              constraints/
              workspace/
              artifacts/

        Parameters
        ----------
        branch_dir:
            Path to the branch directory.
        stage_name:
            LibreLane stage name (e.g. ``"synth"``).
        attempt_num:
            1-based attempt number; will be zero-padded to 3 digits.

        Returns
        -------
        Path
            The newly-created attempt directory.
        """
        attempt_dir = (
            branch_dir / "stages" / stage_name / f"attempt_{attempt_num:03d}"
        )
        attempt_dir.mkdir(parents=True, exist_ok=True)

        for subdir in _ATTEMPT_SUBDIRS:
            (attempt_dir / subdir).mkdir(exist_ok=True)

        logger.info("Created attempt directory: %s", attempt_dir)
        return attempt_dir

    @staticmethod
    def get_next_attempt_num(branch_dir: Path, stage_name: str) -> int:
        """Return the next available attempt number for a stage.

        Scans existing ``attempt_NNN`` directories under
        ``<branch_dir>/stages/<stage_name>/`` and returns ``max + 1``,
        or ``1`` if none exist yet.
        """
        stage_dir = branch_dir / "stages" / stage_name
        if not stage_dir.exists():
            return 1

        max_num = 0
        for child in stage_dir.iterdir():
            if child.is_dir() and child.name.startswith("attempt_"):
                try:
                    num = int(child.name.split("_", 1)[1])
                    max_num = max(max_num, num)
                except (ValueError, IndexError):
                    continue
        return max_num + 1

    @staticmethod
    def create_module_dir(run_dir: Path, module_name: str) -> Path:
        """Create and return ``<run_dir>/modules/<module_name>``."""
        module_dir = run_dir / "modules" / module_name
        module_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Created module directory: %s", module_dir)
        return module_dir

    # ------------------------------------------------------------------
    # Workspace cloning
    # ------------------------------------------------------------------

    @staticmethod
    def clone_workspace(
        source_dir: Path,
        target_dir: Path,
        strategy: str = "reflink_or_hardlink",
    ) -> None:
        """Clone *source_dir* into *target_dir* using the given strategy.

        Strategies
        ----------
        ``"reflink_or_hardlink"`` (default):
            Attempt to hardlink each file.  If any hardlink fails (e.g.
            cross-device), fall back to a full ``shutil.copytree`` for
            the remaining files.
        ``"copy"``:
            Always use ``shutil.copytree``.

        The *target_dir* **must not** already exist (it will be created
        by the clone operation).
        """
        if strategy == "copy":
            shutil.copytree(source_dir, target_dir)
            logger.info("Copied workspace via shutil: %s -> %s", source_dir, target_dir)
            return

        # Default strategy: try hardlinks, fall back to copy.
        try:
            _hardlink_tree(source_dir, target_dir)
            logger.info(
                "Cloned workspace via hardlinks: %s -> %s",
                source_dir,
                target_dir,
            )
        except OSError:
            logger.warning(
                "Hardlink clone failed; falling back to copy: %s -> %s",
                source_dir,
                target_dir,
            )
            # Clean up any partial hardlink tree before retrying.
            if target_dir.exists():
                shutil.rmtree(target_dir)
            shutil.copytree(source_dir, target_dir)


def _hardlink_tree(src: Path, dst: Path) -> None:
    """Recursively hardlink every file from *src* into *dst*.

    Directory structure is replicated via ``mkdir``; regular files are
    hard-linked with ``os.link``.  Raises ``OSError`` on the first
    failure so the caller can fall back to a copy strategy.
    """
    dst.mkdir(parents=True, exist_ok=True)
    for entry in src.iterdir():
        target = dst / entry.name
        if entry.is_dir():
            _hardlink_tree(entry, target)
        else:
            os.link(entry, target)
