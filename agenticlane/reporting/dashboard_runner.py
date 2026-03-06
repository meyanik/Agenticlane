"""Subprocess-based run manager for the AgenticLane dashboard.

Launches ``agenticlane run`` as child processes and tracks their
lifecycle so the dashboard can list active runs and stop them.
"""
from __future__ import annotations

import contextlib
import logging
import os
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
        self._finished: dict[str, _FinishedRun] = {}
        self._on_start_callbacks: list[Any] = []
        # Register cleanup so child processes don't become orphans
        # when the dashboard server exits.
        import atexit
        atexit.register(self._shutdown_all)

    def on_run_start(self, callback: Any) -> None:
        """Register a callback invoked with (run_id, runs_dir) after start."""
        self._on_start_callbacks.append(callback)

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

        # Ensure output dir is set.
        # WorkspaceManager.create_run_dir() appends "runs/<run_id>" to output_dir,
        # so we set output_dir to the PARENT of runs_dir to avoid double "runs/runs/".
        config.setdefault("project", {})["output_dir"] = str(runs_dir.parent.resolve())

        # Write config to temp file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", prefix=f"agenticlane_{run_id}_",
            delete=False,
        ) as tmp:
            yaml.dump(config, tmp, default_flow_style=False)
            config_path = tmp.name

        logger.info("Starting run %s with config %s", run_id, config_path)

        # Write stdout/stderr to log files instead of PIPE to avoid deadlock.
        # (PIPE buffers are ~64KB; once full the subprocess blocks on write.)
        log_dir = runs_dir / run_id
        log_dir.mkdir(parents=True, exist_ok=True)
        stdout_log = open(log_dir / "stdout.log", "w")  # noqa: SIM115
        stderr_log = open(log_dir / "stderr.log", "w")  # noqa: SIM115

        # Launch subprocess.
        # PYTHONUNBUFFERED=1 forces line-buffered output so logs appear in
        # real-time rather than being stuck in Python's 8KB write buffer.
        env = {**os.environ, "PYTHONUNBUFFERED": "1"}
        proc = subprocess.Popen(
            [sys.executable, "-m", "agenticlane.cli.main", "run", config_path],
            stdout=stdout_log,
            stderr=stderr_log,
            env=env,
            cwd=str(runs_dir.parent) if runs_dir.parent.exists() else None,
        )

        self._active[run_id] = _RunProcess(
            run_id=run_id,
            process=proc,
            config_path=config_path,
            start_time=time.time(),
            stdout_log=stdout_log,
            stderr_log=stderr_log,
            log_dir=log_dir,
        )

        # Notify callbacks (e.g. file watcher registration)
        for cb in self._on_start_callbacks:
            try:
                result = cb(run_id, runs_dir)
                if hasattr(result, "__await__"):
                    await result
            except Exception:  # noqa: BLE001
                logger.warning("on_run_start callback failed for %s", run_id, exc_info=True)

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
        if rp is not None:
            return {
                "run_id": rp.run_id,
                "pid": rp.process.pid,
                "elapsed_seconds": time.time() - rp.start_time,
                "status": "running",
            }
        # Check finished runs
        fr = self._finished.get(run_id)
        if fr is not None:
            return {
                "run_id": run_id,
                "pid": fr.pid,
                "elapsed_seconds": fr.elapsed_seconds,
                "status": "crashed" if fr.exit_code != 0 else "finished",
                "exit_code": fr.exit_code,
                "error": fr.stderr_tail,
            }
        return None

    def _reap_finished(self) -> None:
        """Remove finished processes from the active dict, preserving exit info."""
        finished = [
            rid for rid, rp in self._active.items()
            if rp.process.poll() is not None
        ]
        for rid in finished:
            rp = self._active.pop(rid)
            rc = rp.process.returncode
            elapsed = time.time() - rp.start_time
            # Close log file handles
            for fh in (rp.stdout_log, rp.stderr_log):
                if fh is not None:
                    try:
                        fh.close()
                    except Exception:  # noqa: BLE001
                        pass
            # Read stderr from log file for crash diagnosis
            stderr_tail = ""
            if rc != 0 and rp.log_dir is not None:
                try:
                    stderr_path = rp.log_dir / "stderr.log"
                    if stderr_path.exists():
                        stderr_tail = stderr_path.read_text()[-2000:]
                except Exception:  # noqa: BLE001
                    stderr_tail = "(could not read stderr.log)"
            logger.info(
                "Run %s finished (exit_code=%s, elapsed=%.1fs)",
                rid, rc, elapsed,
            )
            if rc != 0:
                logger.error("Run %s crashed. stderr tail:\n%s", rid, stderr_tail)
            self._finished[rid] = _FinishedRun(
                run_id=rid,
                pid=rp.process.pid,
                exit_code=rc or 0,
                elapsed_seconds=elapsed,
                stderr_tail=stderr_tail,
            )

    def _shutdown_all(self) -> None:
        """Kill all active child processes (called on dashboard exit)."""
        for run_id, rp in list(self._active.items()):
            if rp.process.poll() is None:
                logger.info("Shutting down run %s (pid=%d)", run_id, rp.process.pid)
                with contextlib.suppress(OSError):
                    rp.process.send_signal(signal.SIGTERM)
                try:
                    rp.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    with contextlib.suppress(OSError):
                        rp.process.kill()
            # Close log file handles
            for fh in (rp.stdout_log, rp.stderr_log):
                if fh is not None:
                    with contextlib.suppress(Exception):
                        fh.close()


class _RunProcess:
    """Internal record for a running subprocess."""

    __slots__ = ("run_id", "process", "config_path", "start_time",
                 "stdout_log", "stderr_log", "log_dir")

    def __init__(
        self,
        run_id: str,
        process: subprocess.Popen[bytes],
        config_path: str,
        start_time: float,
        stdout_log: Any = None,
        stderr_log: Any = None,
        log_dir: Optional[Path] = None,
    ) -> None:
        self.run_id = run_id
        self.process = process
        self.config_path = config_path
        self.start_time = start_time
        self.stdout_log = stdout_log
        self.stderr_log = stderr_log
        self.log_dir = log_dir


class _FinishedRun:
    """Record for a finished (or crashed) run."""

    __slots__ = ("run_id", "pid", "exit_code", "elapsed_seconds", "stderr_tail")

    def __init__(
        self,
        run_id: str,
        pid: int,
        exit_code: int,
        elapsed_seconds: float,
        stderr_tail: str,
    ) -> None:
        self.run_id = run_id
        self.pid = pid
        self.exit_code = exit_code
        self.elapsed_seconds = elapsed_seconds
        self.stderr_tail = stderr_tail
