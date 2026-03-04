"""Subprocess-based run manager for the AgenticLane dashboard.

Launches ``agenticlane run`` as child processes and tracks their
lifecycle so the dashboard can list active runs and stop them.
"""
from __future__ import annotations

import contextlib
import logging
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Optional

import yaml

logger = logging.getLogger(__name__)


class DashboardRunManager:
    """Launches and manages agenticlane runs as subprocesses.

    Each run is spawned via ``subprocess.Popen`` and tracked by run_id.
    The manager polls subprocess status and can send SIGTERM to stop.
    """

    def __init__(self) -> None:
        self._active: dict[str, _RunProcess] = {}

    async def start_run(
        self,
        config: dict[str, Any],
        runs_dir: Path,
    ) -> dict[str, Any]:
        """Start a new agenticlane run from a config dict.

        Parameters
        ----------
        config:
            Full agenticlane YAML config as a dictionary.
        runs_dir:
            The runs output directory.

        Returns
        -------
        dict
            ``{"run_id": ..., "status": "started", "pid": ...}``
        """
        # Generate run_id if not in config
        run_id = config.get("project", {}).get("run_id")
        if not run_id or run_id == "auto":
            run_id = f"run_{uuid.uuid4().hex[:8]}"
            config.setdefault("project", {})["run_id"] = run_id

        # Ensure output dir is set
        config.setdefault("project", {})["output_dir"] = str(runs_dir)

        # Write config to temp file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", prefix=f"agenticlane_{run_id}_",
            delete=False,
        ) as tmp:
            yaml.dump(config, tmp, default_flow_style=False)
            config_path = tmp.name

        logger.info("Starting run %s with config %s", run_id, config_path)

        # Launch subprocess
        proc = subprocess.Popen(
            [sys.executable, "-m", "agenticlane.cli.main", "run", config_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(runs_dir.parent) if runs_dir.parent.exists() else None,
        )

        self._active[run_id] = _RunProcess(
            run_id=run_id,
            process=proc,
            config_path=config_path,
            start_time=time.time(),
        )

        return {
            "run_id": run_id,
            "status": "started",
            "pid": proc.pid,
            "config_path": config_path,
        }

    async def stop_run(self, run_id: str) -> bool:
        """Stop an active run by sending SIGTERM.

        Returns True if the run was found and signaled.
        """
        rp = self._active.get(run_id)
        if rp is None:
            return False

        if rp.process.poll() is not None:
            # Already exited
            self._active.pop(run_id, None)
            return False

        logger.info("Stopping run %s (pid=%d)", run_id, rp.process.pid)
        with contextlib.suppress(OSError):
            rp.process.send_signal(signal.SIGTERM)
        return True

    def get_active(self) -> list[dict[str, Any]]:
        """Return info about all active (still running) processes."""
        self._reap_finished()
        result: list[dict[str, Any]] = []
        for rp in self._active.values():
            result.append({
                "run_id": rp.run_id,
                "pid": rp.process.pid,
                "elapsed_seconds": time.time() - rp.start_time,
                "status": "running",
            })
        return result

    def get_run_status(self, run_id: str) -> Optional[dict[str, Any]]:
        """Get status of a specific run (active or recently finished)."""
        self._reap_finished()
        rp = self._active.get(run_id)
        if rp is None:
            return None
        return {
            "run_id": rp.run_id,
            "pid": rp.process.pid,
            "elapsed_seconds": time.time() - rp.start_time,
            "status": "running",
        }

    def _reap_finished(self) -> None:
        """Remove finished processes from the active dict."""
        finished = [
            rid for rid, rp in self._active.items()
            if rp.process.poll() is not None
        ]
        for rid in finished:
            rp = self._active.pop(rid)
            rc = rp.process.returncode
            logger.info(
                "Run %s finished (exit_code=%s, elapsed=%.1fs)",
                rid, rc, time.time() - rp.start_time,
            )


class _RunProcess:
    """Internal record for a running subprocess."""

    __slots__ = ("run_id", "process", "config_path", "start_time")

    def __init__(
        self,
        run_id: str,
        process: subprocess.Popen[bytes],
        config_path: str,
        start_time: float,
    ) -> None:
        self.run_id = run_id
        self.process = process
        self.config_path = config_path
        self.start_time = start_time
