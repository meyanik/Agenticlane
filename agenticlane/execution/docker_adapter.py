"""Docker execution adapter for AgenticLane.

Implements :class:`ExecutionAdapter` by running LibreLane inside a Docker
container via ``docker run``.  The host workspace and design directories
are bind-mounted into the container so that artifacts are accessible
after the run completes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

from agenticlane.config.models import DockerConfig
from agenticlane.execution.adapter import ExecutionAdapter
from agenticlane.orchestration.graph import STAGE_GRAPH, StageSpec
from agenticlane.schemas.execution import ExecutionResult

logger = logging.getLogger(__name__)

# Report file patterns to collect as artifacts
_REPORT_GLOBS = [
    "*.rpt",
    "*.log",
    "*.json",
    "*.def",
    "*.v",
    "*.nl.v",
    "*.sdc",
    "*.spef",
    "*.gds",
    "*.lef",
]


class DockerAdapter(ExecutionAdapter):
    """Runs LibreLane stages inside a Docker container.

    Parameters
    ----------
    docker_config:
        Docker-specific settings (image name, mount paths).
    pdk:
        PDK name (e.g. ``sky130A``).
    pdk_root:
        Host path to the PDK installation root.  Mounted read-only
        into the container at ``/pdk``.
    design_dir:
        Host path to the design directory containing Verilog sources.
        If *None*, derived from the config file's parent directory.
    extra_env:
        Additional environment variables passed to the container.
    extra_docker_args:
        Extra arguments appended to the ``docker run`` command
        (e.g. ``["--gpus", "all"]``).
    """

    def __init__(
        self,
        *,
        docker_config: Optional[DockerConfig] = None,
        pdk: str = "sky130A",
        pdk_root: Optional[str] = None,
        design_dir: Optional[str] = None,
        extra_env: Optional[dict[str, str]] = None,
        extra_docker_args: Optional[list[str]] = None,
    ) -> None:
        self.docker_config = docker_config or DockerConfig()
        self.pdk = pdk
        self.pdk_root = pdk_root
        self.design_dir = design_dir
        self.extra_env = extra_env or {}
        self.extra_docker_args = extra_docker_args or []

    async def run_stage(
        self,
        *,
        run_root: str,
        stage_name: str,
        librelane_config_path: str,
        resolved_design_config_path: str,
        patch: dict[str, Any],
        state_in_path: Optional[str],
        attempt_dir: str,
        timeout_seconds: int,
    ) -> ExecutionResult:
        """Run a single LibreLane stage inside a Docker container."""
        start = time.monotonic()

        # Create directory structure
        workspace_dir = os.path.join(attempt_dir, "workspace")
        artifacts_dir = os.path.join(attempt_dir, "artifacts")
        os.makedirs(workspace_dir, exist_ok=True)
        os.makedirs(artifacts_dir, exist_ok=True)

        # Look up stage spec
        stage_upper = stage_name.upper()
        try:
            stage_spec: StageSpec = STAGE_GRAPH[stage_upper]
        except KeyError:
            runtime = time.monotonic() - start
            return ExecutionResult(
                execution_status="config_error",
                exit_code=1,
                runtime_seconds=runtime,
                attempt_dir=attempt_dir,
                workspace_dir=workspace_dir,
                artifacts_dir=artifacts_dir,
                state_out_path=None,
                stderr_tail=f"Unknown stage: {stage_name}",
                error_summary=f"Unknown stage '{stage_name}'",
            )

        # Materialize patch into the workspace so the container can read it
        patch_path = os.path.join(attempt_dir, "patch.json")
        with open(patch_path, "w") as f:
            json.dump(patch, f)

        try:
            # Build and run the docker command
            exit_code, stdout, stderr = await asyncio.wait_for(
                self._run_docker(
                    stage_spec=stage_spec,
                    librelane_config_path=librelane_config_path,
                    resolved_design_config_path=resolved_design_config_path,
                    patch=patch,
                    patch_path=patch_path,
                    state_in_path=state_in_path,
                    attempt_dir=attempt_dir,
                    workspace_dir=workspace_dir,
                    run_root=run_root,
                ),
                timeout=timeout_seconds,
            )

            runtime = time.monotonic() - start

            # Collect artifacts from the workspace
            self._collect_artifacts(workspace_dir, artifacts_dir)

            # Find state_out.json
            final_state_out = self._find_state_out(workspace_dir)
            if final_state_out:
                dest = os.path.join(attempt_dir, "state_out.json")
                shutil.copy2(final_state_out, dest)
                final_state_out = dest

            if exit_code == 0:
                return ExecutionResult(
                    execution_status="success",
                    exit_code=0,
                    runtime_seconds=runtime,
                    attempt_dir=attempt_dir,
                    workspace_dir=workspace_dir,
                    artifacts_dir=artifacts_dir,
                    state_out_path=final_state_out,
                    stderr_tail=None,
                    error_summary=None,
                )
            elif exit_code == 137:
                # Docker killed with SIGKILL -- likely OOM
                return ExecutionResult(
                    execution_status="oom_killed",
                    exit_code=exit_code,
                    runtime_seconds=runtime,
                    attempt_dir=attempt_dir,
                    workspace_dir=workspace_dir,
                    artifacts_dir=artifacts_dir,
                    state_out_path=final_state_out,
                    stderr_tail=stderr[-2000:] if stderr else None,
                    error_summary="Container killed (OOM or SIGKILL, exit 137)",
                )
            else:
                return ExecutionResult(
                    execution_status="tool_crash",
                    exit_code=exit_code,
                    runtime_seconds=runtime,
                    attempt_dir=attempt_dir,
                    workspace_dir=workspace_dir,
                    artifacts_dir=artifacts_dir,
                    state_out_path=final_state_out,
                    stderr_tail=stderr[-2000:] if stderr else None,
                    error_summary=f"Container exited with code {exit_code}",
                )

        except asyncio.TimeoutError:
            runtime = time.monotonic() - start
            self._collect_artifacts(workspace_dir, artifacts_dir)
            return ExecutionResult(
                execution_status="timeout",
                exit_code=124,
                runtime_seconds=runtime,
                attempt_dir=attempt_dir,
                workspace_dir=workspace_dir,
                artifacts_dir=artifacts_dir,
                state_out_path=None,
                stderr_tail=f"Stage {stage_name} timed out after {timeout_seconds}s",
                error_summary=f"Timeout after {timeout_seconds}s",
            )

        except Exception as exc:  # noqa: BLE001
            runtime = time.monotonic() - start
            self._collect_artifacts(workspace_dir, artifacts_dir)
            return ExecutionResult(
                execution_status="tool_crash",
                exit_code=1,
                runtime_seconds=runtime,
                attempt_dir=attempt_dir,
                workspace_dir=workspace_dir,
                artifacts_dir=artifacts_dir,
                state_out_path=None,
                stderr_tail=str(exc)[-2000:],
                error_summary=f"Docker error: {exc}",
            )

    # ------------------------------------------------------------------
    # Docker invocation
    # ------------------------------------------------------------------

    def _build_docker_cmd(
        self,
        *,
        stage_spec: StageSpec,
        librelane_config_path: str,
        resolved_design_config_path: str,
        patch: dict[str, Any],
        state_in_path: Optional[str],
        attempt_dir: str,
        workspace_dir: str,
        run_root: str,
    ) -> list[str]:
        """Build the ``docker run`` command line.

        The container receives:
        - The run_root mounted at ``docker_config.mount_root``
        - The attempt_dir mounted at ``docker_config.attempt_root``
        - PDK root mounted read-only at ``/pdk`` (if provided)
        - Design dir mounted read-only at ``/design`` (if provided)
        - Config override strings via environment variables
        - The LibreLane stage frm/to as command arguments
        """
        dc = self.docker_config
        cmd: list[str] = [
            "docker",
            "run",
            "--rm",
            # Mount run_root
            "-v",
            f"{run_root}:{dc.mount_root}",
            # Mount attempt_dir
            "-v",
            f"{attempt_dir}:{dc.attempt_root}",
        ]

        # Mount PDK if provided
        if self.pdk_root:
            cmd.extend(["-v", f"{self.pdk_root}:/pdk:ro"])
            cmd.extend(["-e", "PDK_ROOT=/pdk"])

        # Mount design dir if provided
        design_dir = self.design_dir or str(Path(librelane_config_path).parent)
        cmd.extend(["-v", f"{design_dir}:/design:ro"])

        # Set PDK env var
        cmd.extend(["-e", f"PDK={self.pdk}"])

        # Inject config_vars as environment variable
        config_vars = patch.get("config_vars", {})
        if config_vars:
            override_str = ";".join(f"{k}={v}" for k, v in config_vars.items())
            cmd.extend(["-e", f"LIBRELANE_CONFIG_OVERRIDES={override_str}"])

        # Inject state_in_path
        if state_in_path and os.path.isfile(state_in_path):
            # Determine container-side path for state_in
            # If state_in is inside attempt_dir, translate to container path
            if state_in_path.startswith(attempt_dir):
                rel = os.path.relpath(state_in_path, attempt_dir)
                container_state_in = os.path.join(dc.attempt_root, rel)
            elif state_in_path.startswith(run_root):
                rel = os.path.relpath(state_in_path, run_root)
                container_state_in = os.path.join(dc.mount_root, rel)
            else:
                # Mount the state file separately
                cmd.extend(["-v", f"{state_in_path}:/state_in.json:ro"])
                container_state_in = "/state_in.json"
            cmd.extend(["-e", f"STATE_IN_PATH={container_state_in}"])

        # Extra user-provided env vars
        for key, value in self.extra_env.items():
            cmd.extend(["-e", f"{key}={value}"])

        # Extra docker args (e.g. --gpus, --memory, --cpus)
        cmd.extend(self.extra_docker_args)

        # Image name
        cmd.append(dc.image)

        # Container entrypoint arguments: run the stage
        # The container image is expected to have a LibreLane entrypoint
        # that accepts --config, --from, --to, --run-dir flags.
        container_config = os.path.join(
            "/design", os.path.basename(librelane_config_path)
        )
        container_workspace = os.path.join(dc.attempt_root, "workspace")

        cmd.extend([
            "librelane",
            "--config",
            container_config,
            "--from",
            stage_spec.first_step,
            "--to",
            stage_spec.last_step,
            "--run-dir",
            container_workspace,
            "--pdk",
            self.pdk,
        ])

        return cmd

    async def _run_docker(
        self,
        *,
        stage_spec: StageSpec,
        librelane_config_path: str,
        resolved_design_config_path: str,
        patch: dict[str, Any],
        patch_path: str,
        state_in_path: Optional[str],
        attempt_dir: str,
        workspace_dir: str,
        run_root: str,
    ) -> tuple[int, str, str]:
        """Execute ``docker run`` and return (exit_code, stdout, stderr).

        Runs the subprocess asynchronously via ``asyncio.create_subprocess_exec``.
        """
        cmd = self._build_docker_cmd(
            stage_spec=stage_spec,
            librelane_config_path=librelane_config_path,
            resolved_design_config_path=resolved_design_config_path,
            patch=patch,
            state_in_path=state_in_path,
            attempt_dir=attempt_dir,
            workspace_dir=workspace_dir,
            run_root=run_root,
        )

        logger.info("Docker command: %s", " ".join(cmd))

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout_bytes, stderr_bytes = await proc.communicate()

        stdout = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
        stderr = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""

        exit_code = proc.returncode if proc.returncode is not None else 1

        logger.info(
            "Docker exited with code %d (stdout: %d bytes, stderr: %d bytes)",
            exit_code,
            len(stdout),
            len(stderr),
        )

        return exit_code, stdout, stderr

    # ------------------------------------------------------------------
    # Artifact collection (shared logic with local adapter)
    # ------------------------------------------------------------------

    def _collect_artifacts(self, workspace_dir: str, artifacts_dir: str) -> None:
        """Copy report and output files from workspace into artifacts dir."""
        workspace_path = Path(workspace_dir)
        artifacts_path = Path(artifacts_dir)

        if not workspace_path.is_dir():
            return

        for pattern in _REPORT_GLOBS:
            for f in workspace_path.rglob(pattern):
                if f.is_file():
                    dest = artifacts_path / f.name
                    if not dest.exists():
                        try:
                            shutil.copy2(f, dest)
                        except OSError:
                            logger.debug("Failed to copy artifact: %s", f)

    def _find_state_out(self, search_dir: str) -> Optional[str]:
        """Find the last step's state_out.json in the directory tree."""
        candidates = sorted(
            Path(search_dir).rglob("state_out.json"),
            key=lambda p: p.parent.name,
        )
        for path in reversed(candidates):
            if path.is_file():
                return str(path)
        return None

    # ------------------------------------------------------------------
    # Docker availability check
    # ------------------------------------------------------------------

    @staticmethod
    def check_docker_available() -> bool:
        """Return True if Docker is available and running."""
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                timeout=10,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return False

    @staticmethod
    def check_image_exists(image: str) -> bool:
        """Return True if the specified Docker image exists locally."""
        try:
            result = subprocess.run(
                ["docker", "image", "inspect", image],
                capture_output=True,
                timeout=10,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return False
