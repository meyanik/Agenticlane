"""Tests for the Docker execution adapter.

All tests mock subprocess/asyncio calls so no real Docker daemon is needed.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agenticlane.config.models import DockerConfig
from agenticlane.execution.docker_adapter import DockerAdapter
from agenticlane.orchestration.graph import STAGE_GRAPH

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_adapter(
    *,
    image: str = "agenticlane:latest",
    pdk: str = "sky130A",
    pdk_root: str | None = None,
    design_dir: str | None = None,
    extra_env: dict[str, str] | None = None,
    extra_docker_args: list[str] | None = None,
) -> DockerAdapter:
    """Create a DockerAdapter with the given settings."""
    dc = DockerConfig(image=image)
    return DockerAdapter(
        docker_config=dc,
        pdk=pdk,
        pdk_root=pdk_root,
        design_dir=design_dir,
        extra_env=extra_env,
        extra_docker_args=extra_docker_args,
    )


async def _fake_create_subprocess_exec(
    *cmd: str,
    stdout: Any = None,
    stderr: Any = None,
    exit_code: int = 0,
    stdout_data: bytes = b"",
    stderr_data: bytes = b"",
    workspace_dir: str | None = None,
    write_state_out: bool = False,
) -> MagicMock:
    """Create a mock subprocess that simulates docker run."""
    proc = MagicMock()
    proc.returncode = exit_code

    # Optionally write outputs to simulate container side-effects
    if workspace_dir and write_state_out:
        os.makedirs(workspace_dir, exist_ok=True)
        state_out = {"stage": "test", "status": "success"}
        state_path = os.path.join(workspace_dir, "state_out.json")
        with open(state_path, "w") as f:
            json.dump(state_out, f)
        # Write a timing report
        reports_dir = os.path.join(workspace_dir, "reports")
        os.makedirs(reports_dir, exist_ok=True)
        with open(os.path.join(reports_dir, "timing.rpt"), "w") as f:
            f.write("Setup WNS: -0.050 ns\n")

    async def communicate():
        return stdout_data, stderr_data

    proc.communicate = communicate
    return proc


@pytest.fixture
def adapter():
    return _make_adapter()


@pytest.fixture
def attempt_dir(tmp_path: Path) -> str:
    d = tmp_path / "attempt_001"
    d.mkdir()
    return str(d)


# ---------------------------------------------------------------------------
# Test 1: Successful stage run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_stage_success(adapter: DockerAdapter, attempt_dir: str, tmp_path: Path) -> None:
    """Successful docker run returns success status with exit code 0."""
    workspace_dir = os.path.join(attempt_dir, "workspace")

    async def fake_exec(*cmd, **kwargs):
        return await _fake_create_subprocess_exec(
            *cmd,
            exit_code=0,
            stdout_data=b"All steps completed.",
            workspace_dir=workspace_dir,
            write_state_out=True,
        )

    with patch("agenticlane.execution.docker_adapter.asyncio.create_subprocess_exec", side_effect=fake_exec):
        result = await adapter.run_stage(
            run_root=str(tmp_path),
            stage_name="SYNTH",
            librelane_config_path=str(tmp_path / "config.yaml"),
            resolved_design_config_path=str(tmp_path / "config.yaml"),
            patch={"config_vars": {"SYNTH_STRATEGY": "AREA"}},
            state_in_path=None,
            attempt_dir=attempt_dir,
            timeout_seconds=3600,
        )

    assert result.execution_status == "success"
    assert result.exit_code == 0
    assert result.runtime_seconds >= 0
    assert result.attempt_dir == attempt_dir
    assert os.path.isdir(result.workspace_dir)
    assert os.path.isdir(result.artifacts_dir)


# ---------------------------------------------------------------------------
# Test 2: State out collected on success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_state_out_collected(adapter: DockerAdapter, attempt_dir: str, tmp_path: Path) -> None:
    """state_out.json from workspace should be copied to attempt_dir."""
    workspace_dir = os.path.join(attempt_dir, "workspace")

    async def fake_exec(*cmd, **kwargs):
        return await _fake_create_subprocess_exec(
            *cmd,
            exit_code=0,
            workspace_dir=workspace_dir,
            write_state_out=True,
        )

    with patch("agenticlane.execution.docker_adapter.asyncio.create_subprocess_exec", side_effect=fake_exec):
        result = await adapter.run_stage(
            run_root=str(tmp_path),
            stage_name="SYNTH",
            librelane_config_path=str(tmp_path / "config.yaml"),
            resolved_design_config_path=str(tmp_path / "config.yaml"),
            patch={"config_vars": {}},
            state_in_path=None,
            attempt_dir=attempt_dir,
            timeout_seconds=3600,
        )

    assert result.state_out_path is not None
    assert os.path.isfile(result.state_out_path)
    # Verify it was copied to attempt_dir
    assert result.state_out_path == os.path.join(attempt_dir, "state_out.json")


# ---------------------------------------------------------------------------
# Test 3: Unknown stage returns config_error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_stage_returns_config_error(adapter: DockerAdapter, attempt_dir: str, tmp_path: Path) -> None:
    """Unknown stage name should return config_error without running docker."""
    result = await adapter.run_stage(
        run_root=str(tmp_path),
        stage_name="NONEXISTENT_STAGE",
        librelane_config_path=str(tmp_path / "config.yaml"),
        resolved_design_config_path=str(tmp_path / "config.yaml"),
        patch={"config_vars": {}},
        state_in_path=None,
        attempt_dir=attempt_dir,
        timeout_seconds=3600,
    )

    assert result.execution_status == "config_error"
    assert result.exit_code == 1
    assert "Unknown stage" in (result.stderr_tail or "")


# ---------------------------------------------------------------------------
# Test 4: Timeout returns timeout status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_timeout_returns_timeout_status(adapter: DockerAdapter, attempt_dir: str, tmp_path: Path) -> None:
    """Stage exceeding timeout should return timeout status."""

    async def slow_exec(*cmd, **kwargs):
        proc = MagicMock()
        proc.returncode = None

        async def slow_communicate():
            await asyncio.sleep(10)
            return b"", b""

        proc.communicate = slow_communicate
        return proc

    with patch("agenticlane.execution.docker_adapter.asyncio.create_subprocess_exec", side_effect=slow_exec):
        result = await adapter.run_stage(
            run_root=str(tmp_path),
            stage_name="SYNTH",
            librelane_config_path=str(tmp_path / "config.yaml"),
            resolved_design_config_path=str(tmp_path / "config.yaml"),
            patch={"config_vars": {}},
            state_in_path=None,
            attempt_dir=attempt_dir,
            timeout_seconds=1,
        )

    assert result.execution_status == "timeout"
    assert result.exit_code == 124
    assert "timed out" in (result.stderr_tail or "").lower()


# ---------------------------------------------------------------------------
# Test 5: Non-zero exit returns tool_crash
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_nonzero_exit_returns_tool_crash(adapter: DockerAdapter, attempt_dir: str, tmp_path: Path) -> None:
    """Non-zero exit code (not 137) returns tool_crash status."""

    async def failing_exec(*cmd, **kwargs):
        return await _fake_create_subprocess_exec(
            *cmd,
            exit_code=1,
            stderr_data=b"Error: OpenROAD crashed",
        )

    with patch("agenticlane.execution.docker_adapter.asyncio.create_subprocess_exec", side_effect=failing_exec):
        result = await adapter.run_stage(
            run_root=str(tmp_path),
            stage_name="SYNTH",
            librelane_config_path=str(tmp_path / "config.yaml"),
            resolved_design_config_path=str(tmp_path / "config.yaml"),
            patch={"config_vars": {}},
            state_in_path=None,
            attempt_dir=attempt_dir,
            timeout_seconds=3600,
        )

    assert result.execution_status == "tool_crash"
    assert result.exit_code == 1
    assert "exited with code 1" in (result.error_summary or "")


# ---------------------------------------------------------------------------
# Test 6: Exit code 137 returns oom_killed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exit_137_returns_oom_killed(adapter: DockerAdapter, attempt_dir: str, tmp_path: Path) -> None:
    """Exit code 137 (SIGKILL) should be reported as oom_killed."""

    async def oom_exec(*cmd, **kwargs):
        return await _fake_create_subprocess_exec(
            *cmd,
            exit_code=137,
            stderr_data=b"Killed",
        )

    with patch("agenticlane.execution.docker_adapter.asyncio.create_subprocess_exec", side_effect=oom_exec):
        result = await adapter.run_stage(
            run_root=str(tmp_path),
            stage_name="FLOORPLAN",
            librelane_config_path=str(tmp_path / "config.yaml"),
            resolved_design_config_path=str(tmp_path / "config.yaml"),
            patch={"config_vars": {}},
            state_in_path=None,
            attempt_dir=attempt_dir,
            timeout_seconds=3600,
        )

    assert result.execution_status == "oom_killed"
    assert result.exit_code == 137
    assert "OOM" in (result.error_summary or "")


# ---------------------------------------------------------------------------
# Test 7: Docker command includes correct volume mounts
# ---------------------------------------------------------------------------


def test_build_docker_cmd_volume_mounts(tmp_path: Path) -> None:
    """Docker command should include -v mounts for run_root and attempt_dir."""
    adapter = _make_adapter(pdk_root="/opt/pdks", design_dir="/home/user/design")
    stage_spec = STAGE_GRAPH["SYNTH"]

    cmd = adapter._build_docker_cmd(
        stage_spec=stage_spec,
        librelane_config_path="/home/user/design/config.yaml",
        resolved_design_config_path="/home/user/design/config.yaml",
        patch={"config_vars": {}},
        state_in_path=None,
        attempt_dir="/tmp/attempt_001",
        workspace_dir="/tmp/attempt_001/workspace",
        run_root="/tmp/runs/run_abc",
    )

    cmd_str = " ".join(cmd)

    # Check run_root mount
    assert "-v /tmp/runs/run_abc:/run_root" in cmd_str
    # Check attempt_dir mount
    assert "-v /tmp/attempt_001:/attempt" in cmd_str
    # Check PDK mount (read-only)
    assert "-v /opt/pdks:/pdk:ro" in cmd_str
    # Check design dir mount (read-only)
    assert "-v /home/user/design:/design:ro" in cmd_str
    # Check --rm flag
    assert "--rm" in cmd


# ---------------------------------------------------------------------------
# Test 8: Config vars passed as environment variable
# ---------------------------------------------------------------------------


def test_build_docker_cmd_config_vars_env(tmp_path: Path) -> None:
    """Config vars from patch should be passed via LIBRELANE_CONFIG_OVERRIDES env."""
    adapter = _make_adapter()
    stage_spec = STAGE_GRAPH["FLOORPLAN"]

    cmd = adapter._build_docker_cmd(
        stage_spec=stage_spec,
        librelane_config_path=str(tmp_path / "config.yaml"),
        resolved_design_config_path=str(tmp_path / "config.yaml"),
        patch={"config_vars": {"FP_CORE_UTIL": 55, "FP_SIZING": "absolute"}},
        state_in_path=None,
        attempt_dir=str(tmp_path / "attempt"),
        workspace_dir=str(tmp_path / "attempt" / "workspace"),
        run_root=str(tmp_path / "runs"),
    )

    # Find the LIBRELANE_CONFIG_OVERRIDES value
    env_idx = None
    for i, arg in enumerate(cmd):
        if arg == "-e" and i + 1 < len(cmd) and cmd[i + 1].startswith("LIBRELANE_CONFIG_OVERRIDES="):
            env_idx = i + 1
            break

    assert env_idx is not None, "LIBRELANE_CONFIG_OVERRIDES not found in docker cmd"
    env_val = cmd[env_idx].split("=", 1)[1]
    assert "FP_CORE_UTIL=55" in env_val
    assert "FP_SIZING=absolute" in env_val


# ---------------------------------------------------------------------------
# Test 9: Empty config vars do not add override env
# ---------------------------------------------------------------------------


def test_build_docker_cmd_empty_config_vars(tmp_path: Path) -> None:
    """Empty config_vars should not inject LIBRELANE_CONFIG_OVERRIDES."""
    adapter = _make_adapter()
    stage_spec = STAGE_GRAPH["SYNTH"]

    cmd = adapter._build_docker_cmd(
        stage_spec=stage_spec,
        librelane_config_path=str(tmp_path / "config.yaml"),
        resolved_design_config_path=str(tmp_path / "config.yaml"),
        patch={"config_vars": {}},
        state_in_path=None,
        attempt_dir=str(tmp_path / "attempt"),
        workspace_dir=str(tmp_path / "attempt" / "workspace"),
        run_root=str(tmp_path / "runs"),
    )

    cmd_str = " ".join(cmd)
    assert "LIBRELANE_CONFIG_OVERRIDES" not in cmd_str


# ---------------------------------------------------------------------------
# Test 10: Stage frm/to passed correctly to container
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("stage_name", ["SYNTH", "FLOORPLAN", "PLACE_GLOBAL"])
def test_build_docker_cmd_stage_steps(stage_name: str, tmp_path: Path) -> None:
    """Container command should include --from and --to matching STAGE_GRAPH."""
    adapter = _make_adapter()
    stage_spec = STAGE_GRAPH[stage_name]

    cmd = adapter._build_docker_cmd(
        stage_spec=stage_spec,
        librelane_config_path=str(tmp_path / "config.yaml"),
        resolved_design_config_path=str(tmp_path / "config.yaml"),
        patch={"config_vars": {}},
        state_in_path=None,
        attempt_dir=str(tmp_path / "attempt"),
        workspace_dir=str(tmp_path / "attempt" / "workspace"),
        run_root=str(tmp_path / "runs"),
    )

    # Find --from and --to values
    from_idx = cmd.index("--from")
    to_idx = cmd.index("--to")
    assert cmd[from_idx + 1] == stage_spec.first_step
    assert cmd[to_idx + 1] == stage_spec.last_step


# ---------------------------------------------------------------------------
# Test 11: Extra docker args included
# ---------------------------------------------------------------------------


def test_build_docker_cmd_extra_args(tmp_path: Path) -> None:
    """extra_docker_args should be appended to the docker run command."""
    adapter = _make_adapter(extra_docker_args=["--gpus", "all", "--memory", "8g"])
    stage_spec = STAGE_GRAPH["SYNTH"]

    cmd = adapter._build_docker_cmd(
        stage_spec=stage_spec,
        librelane_config_path=str(tmp_path / "config.yaml"),
        resolved_design_config_path=str(tmp_path / "config.yaml"),
        patch={"config_vars": {}},
        state_in_path=None,
        attempt_dir=str(tmp_path / "attempt"),
        workspace_dir=str(tmp_path / "attempt" / "workspace"),
        run_root=str(tmp_path / "runs"),
    )

    assert "--gpus" in cmd
    assert "all" in cmd
    assert "--memory" in cmd
    assert "8g" in cmd


# ---------------------------------------------------------------------------
# Test 12: Extra environment variables passed to container
# ---------------------------------------------------------------------------


def test_build_docker_cmd_extra_env(tmp_path: Path) -> None:
    """extra_env should be passed as -e flags to docker run."""
    adapter = _make_adapter(extra_env={"MY_VAR": "hello", "ANOTHER": "world"})
    stage_spec = STAGE_GRAPH["SYNTH"]

    cmd = adapter._build_docker_cmd(
        stage_spec=stage_spec,
        librelane_config_path=str(tmp_path / "config.yaml"),
        resolved_design_config_path=str(tmp_path / "config.yaml"),
        patch={"config_vars": {}},
        state_in_path=None,
        attempt_dir=str(tmp_path / "attempt"),
        workspace_dir=str(tmp_path / "attempt" / "workspace"),
        run_root=str(tmp_path / "runs"),
    )

    # Find all env vars
    env_args = []
    for i, arg in enumerate(cmd):
        if arg == "-e" and i + 1 < len(cmd):
            env_args.append(cmd[i + 1])

    assert "MY_VAR=hello" in env_args
    assert "ANOTHER=world" in env_args


# ---------------------------------------------------------------------------
# Test 13: State in path mounted correctly (inside attempt_dir)
# ---------------------------------------------------------------------------


def test_build_docker_cmd_state_in_inside_attempt(tmp_path: Path) -> None:
    """State in file inside attempt_dir should be translated to container path."""
    adapter = _make_adapter()
    stage_spec = STAGE_GRAPH["FLOORPLAN"]
    attempt_dir = str(tmp_path / "attempt_001")
    state_in = os.path.join(attempt_dir, "prev_state_out.json")
    # Create the file so os.path.isfile() returns True
    os.makedirs(attempt_dir, exist_ok=True)
    Path(state_in).write_text("{}")

    cmd = adapter._build_docker_cmd(
        stage_spec=stage_spec,
        librelane_config_path=str(tmp_path / "config.yaml"),
        resolved_design_config_path=str(tmp_path / "config.yaml"),
        patch={"config_vars": {}},
        state_in_path=state_in,
        attempt_dir=attempt_dir,
        workspace_dir=os.path.join(attempt_dir, "workspace"),
        run_root=str(tmp_path / "runs"),
    )

    # Find STATE_IN_PATH
    env_args = []
    for i, arg in enumerate(cmd):
        if arg == "-e" and i + 1 < len(cmd):
            env_args.append(cmd[i + 1])

    state_in_env = [e for e in env_args if e.startswith("STATE_IN_PATH=")]
    assert len(state_in_env) == 1
    # Should be translated to container path under /attempt
    assert state_in_env[0] == "STATE_IN_PATH=/attempt/prev_state_out.json"


# ---------------------------------------------------------------------------
# Test 14: State in path mounted separately when outside known dirs
# ---------------------------------------------------------------------------


def test_build_docker_cmd_state_in_external(tmp_path: Path) -> None:
    """State in file outside run_root/attempt_dir gets a separate mount."""
    adapter = _make_adapter()
    stage_spec = STAGE_GRAPH["FLOORPLAN"]
    attempt_dir = str(tmp_path / "attempt_001")
    run_root = str(tmp_path / "runs")
    # State file in a completely separate location
    external_state = str(tmp_path / "external" / "state_out.json")
    os.makedirs(str(tmp_path / "external"), exist_ok=True)
    Path(external_state).write_text("{}")

    cmd = adapter._build_docker_cmd(
        stage_spec=stage_spec,
        librelane_config_path=str(tmp_path / "config.yaml"),
        resolved_design_config_path=str(tmp_path / "config.yaml"),
        patch={"config_vars": {}},
        state_in_path=external_state,
        attempt_dir=attempt_dir,
        workspace_dir=os.path.join(attempt_dir, "workspace"),
        run_root=run_root,
    )

    cmd_str = " ".join(cmd)
    # Should mount the file separately
    assert f"-v {external_state}:/state_in.json:ro" in cmd_str
    # Container path should be /state_in.json
    assert "STATE_IN_PATH=/state_in.json" in cmd_str


# ---------------------------------------------------------------------------
# Test 15: Artifacts collected from workspace
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_artifacts_collected(adapter: DockerAdapter, attempt_dir: str, tmp_path: Path) -> None:
    """Report files written by the container should be copied to artifacts_dir."""
    workspace_dir = os.path.join(attempt_dir, "workspace")

    async def fake_exec(*cmd, **kwargs):
        return await _fake_create_subprocess_exec(
            *cmd,
            exit_code=0,
            workspace_dir=workspace_dir,
            write_state_out=True,
        )

    with patch("agenticlane.execution.docker_adapter.asyncio.create_subprocess_exec", side_effect=fake_exec):
        result = await adapter.run_stage(
            run_root=str(tmp_path),
            stage_name="SYNTH",
            librelane_config_path=str(tmp_path / "config.yaml"),
            resolved_design_config_path=str(tmp_path / "config.yaml"),
            patch={"config_vars": {}},
            state_in_path=None,
            attempt_dir=attempt_dir,
            timeout_seconds=3600,
        )

    artifacts_path = Path(result.artifacts_dir)
    assert (artifacts_path / "timing.rpt").is_file()


# ---------------------------------------------------------------------------
# Test 16: Subprocess exception returns tool_crash
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subprocess_exception_returns_tool_crash(
    adapter: DockerAdapter, attempt_dir: str, tmp_path: Path
) -> None:
    """Exception during subprocess creation should return tool_crash."""

    async def boom(*cmd, **kwargs):
        raise OSError("Docker daemon not responding")

    with patch("agenticlane.execution.docker_adapter.asyncio.create_subprocess_exec", side_effect=boom):
        result = await adapter.run_stage(
            run_root=str(tmp_path),
            stage_name="SYNTH",
            librelane_config_path=str(tmp_path / "config.yaml"),
            resolved_design_config_path=str(tmp_path / "config.yaml"),
            patch={"config_vars": {}},
            state_in_path=None,
            attempt_dir=attempt_dir,
            timeout_seconds=3600,
        )

    assert result.execution_status == "tool_crash"
    assert "Docker error" in (result.error_summary or "")


# ---------------------------------------------------------------------------
# Test 17: check_docker_available returns True on success
# ---------------------------------------------------------------------------


def test_check_docker_available_true() -> None:
    """check_docker_available returns True when docker info succeeds."""
    mock_result = MagicMock()
    mock_result.returncode = 0
    with patch("agenticlane.execution.docker_adapter.subprocess.run", return_value=mock_result):
        assert DockerAdapter.check_docker_available() is True


# ---------------------------------------------------------------------------
# Test 18: check_docker_available returns False on failure
# ---------------------------------------------------------------------------


def test_check_docker_available_false() -> None:
    """check_docker_available returns False when docker is not installed."""
    with patch("agenticlane.execution.docker_adapter.subprocess.run", side_effect=FileNotFoundError):
        assert DockerAdapter.check_docker_available() is False


# ---------------------------------------------------------------------------
# Test 19: check_image_exists returns True/False
# ---------------------------------------------------------------------------


def test_check_image_exists_true() -> None:
    """check_image_exists returns True when image exists."""
    mock_result = MagicMock()
    mock_result.returncode = 0
    with patch("agenticlane.execution.docker_adapter.subprocess.run", return_value=mock_result):
        assert DockerAdapter.check_image_exists("agenticlane:latest") is True


def test_check_image_exists_false() -> None:
    """check_image_exists returns False when image does not exist."""
    mock_result = MagicMock()
    mock_result.returncode = 1
    with patch("agenticlane.execution.docker_adapter.subprocess.run", return_value=mock_result):
        assert DockerAdapter.check_image_exists("nonexistent:latest") is False


# ---------------------------------------------------------------------------
# Test 20: Patch JSON written to attempt_dir
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_json_materialized(adapter: DockerAdapter, attempt_dir: str, tmp_path: Path) -> None:
    """patch.json should be written to attempt_dir before docker run."""

    async def fake_exec(*cmd, **kwargs):
        return await _fake_create_subprocess_exec(*cmd, exit_code=0)

    with patch("agenticlane.execution.docker_adapter.asyncio.create_subprocess_exec", side_effect=fake_exec):
        await adapter.run_stage(
            run_root=str(tmp_path),
            stage_name="SYNTH",
            librelane_config_path=str(tmp_path / "config.yaml"),
            resolved_design_config_path=str(tmp_path / "config.yaml"),
            patch={"config_vars": {"SYNTH_STRATEGY": "DELAY"}, "sdc_edits": []},
            state_in_path=None,
            attempt_dir=attempt_dir,
            timeout_seconds=3600,
        )

    patch_path = os.path.join(attempt_dir, "patch.json")
    assert os.path.isfile(patch_path)
    with open(patch_path) as f:
        written_patch = json.load(f)
    assert written_patch["config_vars"]["SYNTH_STRATEGY"] == "DELAY"


# ---------------------------------------------------------------------------
# Test 21: Default DockerConfig used when none provided
# ---------------------------------------------------------------------------


def test_default_docker_config() -> None:
    """Adapter should use default DockerConfig when none is provided."""
    adapter = DockerAdapter(pdk="sky130A")
    assert adapter.docker_config.image == "agenticlane:latest"
    assert adapter.docker_config.mount_root == "/run_root"
    assert adapter.docker_config.attempt_root == "/attempt"


# ---------------------------------------------------------------------------
# Test 22: Adapter is a proper ExecutionAdapter subclass
# ---------------------------------------------------------------------------


def test_adapter_is_execution_adapter_subclass() -> None:
    """DockerAdapter should be a subclass of ExecutionAdapter."""
    from agenticlane.execution.adapter import ExecutionAdapter

    adapter = DockerAdapter(pdk="sky130A")
    assert isinstance(adapter, ExecutionAdapter)
