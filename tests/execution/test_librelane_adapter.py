"""Tests for the LibreLane local execution adapter.

All tests monkeypatch the LibreLane imports (Flow.factory, ClassicFlow)
so no real EDA tools are needed.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agenticlane.execution.librelane_adapter import LibreLaneLocalAdapter
from agenticlane.orchestration.graph import STAGE_GRAPH

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fake_flow(workspace_dir: str | None = None, write_state_out: bool = True):
    """Create a mock Classic flow that writes synthetic outputs on start()."""
    flow = MagicMock()

    def fake_start(tag=None, frm=None, to=None, **kwargs):
        # Simulate LibreLane writing outputs
        if workspace_dir and write_state_out:
            state_out = {"stage": "test", "status": "success", "metrics_snapshot": {}}
            state_path = os.path.join(workspace_dir, "state_out.json")
            with open(state_path, "w") as f:
                json.dump(state_out, f)
            # Write a timing report
            os.makedirs(os.path.join(workspace_dir, "reports"), exist_ok=True)
            with open(os.path.join(workspace_dir, "reports", "timing.rpt"), "w") as f:
                f.write("Setup WNS: -0.100 ns\n")

    flow.start = fake_start
    return flow


def _patch_flow_factory(fake_flow):
    """Return a context manager that patches Flow.factory.get to return a class
    whose instances are ``fake_flow``."""
    mock_flow_cls = MagicMock(return_value=fake_flow)
    mock_factory = MagicMock()
    mock_factory.get.return_value = mock_flow_cls
    mock_flow = MagicMock()
    mock_flow.factory = mock_factory
    return patch("agenticlane.execution.librelane_adapter.Flow", mock_flow), mock_flow_cls


@pytest.fixture
def adapter():
    return LibreLaneLocalAdapter(pdk="sky130A")


@pytest.fixture
def attempt_dir(tmp_path):
    d = tmp_path / "attempt_001"
    d.mkdir()
    return str(d)


# ---------------------------------------------------------------------------
# Tests: run_stage success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_stage_success(adapter, attempt_dir, tmp_path):
    """Successful stage run returns success status."""
    workspace_dir = os.path.join(attempt_dir, "workspace")
    fake_flow = _make_fake_flow(workspace_dir=workspace_dir)
    patcher, mock_flow_cls = _patch_flow_factory(fake_flow)

    with patcher:
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


@pytest.mark.asyncio
async def test_run_stage_state_out_collected(adapter, attempt_dir, tmp_path):
    """state_out.json should be copied to attempt_dir."""
    workspace_dir = os.path.join(attempt_dir, "workspace")
    fake_flow = _make_fake_flow(workspace_dir=workspace_dir)
    patcher, _ = _patch_flow_factory(fake_flow)

    with patcher:
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


# ---------------------------------------------------------------------------
# Tests: step mapping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("stage_name", list(STAGE_GRAPH.keys()))
async def test_step_mapping_for_all_stages(adapter, attempt_dir, tmp_path, stage_name):
    """Each stage should use correct first_step/last_step from STAGE_GRAPH."""
    # Track what frm/to arguments flow.start receives
    call_args: dict[str, Any] = {}

    def capture_start(tag=None, frm=None, to=None, **kwargs):
        call_args["frm"] = frm
        call_args["to"] = to
        call_args["tag"] = tag

    fake_flow = MagicMock()
    fake_flow.start = capture_start
    patcher, _ = _patch_flow_factory(fake_flow)

    with patcher:
        await adapter.run_stage(
            run_root=str(tmp_path),
            stage_name=stage_name,
            librelane_config_path=str(tmp_path / "config.yaml"),
            resolved_design_config_path=str(tmp_path / "config.yaml"),
            patch={"config_vars": {}},
            state_in_path=None,
            attempt_dir=attempt_dir,
            timeout_seconds=3600,
        )

    spec = STAGE_GRAPH[stage_name]
    assert call_args["frm"] == spec.first_step
    assert call_args["to"] == spec.last_step


# ---------------------------------------------------------------------------
# Tests: config patching via override strings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_config_vars_applied_as_override_strings(adapter, attempt_dir, tmp_path):
    """config_vars from patch should be passed as config_override_strings."""
    fake_flow = MagicMock()
    fake_flow.start = MagicMock()

    mock_flow_cls = MagicMock(return_value=fake_flow)
    mock_factory = MagicMock()
    mock_factory.get.return_value = mock_flow_cls
    mock_flow_mod = MagicMock()
    mock_flow_mod.factory = mock_factory

    with patch("agenticlane.execution.librelane_adapter.Flow", mock_flow_mod):
        await adapter.run_stage(
            run_root=str(tmp_path),
            stage_name="FLOORPLAN",
            librelane_config_path=str(tmp_path / "config.yaml"),
            resolved_design_config_path=str(tmp_path / "config.yaml"),
            patch={"config_vars": {"FP_CORE_UTIL": 55}},
            state_in_path=None,
            attempt_dir=attempt_dir,
            timeout_seconds=3600,
        )

    # Verify ClassicFlow was instantiated with override strings
    call_kwargs = mock_flow_cls.call_args.kwargs
    overrides = call_kwargs.get("config_override_strings")
    assert overrides is not None
    assert "FP_CORE_UTIL=55" in overrides


@pytest.mark.asyncio
async def test_empty_config_vars_no_override_strings(adapter, attempt_dir, tmp_path):
    """Empty config_vars should pass None for config_override_strings."""
    fake_flow = MagicMock()
    fake_flow.start = MagicMock()

    mock_flow_cls = MagicMock(return_value=fake_flow)
    mock_factory = MagicMock()
    mock_factory.get.return_value = mock_flow_cls
    mock_flow_mod = MagicMock()
    mock_flow_mod.factory = mock_factory

    with patch("agenticlane.execution.librelane_adapter.Flow", mock_flow_mod):
        await adapter.run_stage(
            run_root=str(tmp_path),
            stage_name="SYNTH",
            librelane_config_path=str(tmp_path / "config.yaml"),
            resolved_design_config_path=str(tmp_path / "config.yaml"),
            patch={"config_vars": {}},
            state_in_path=None,
            attempt_dir=attempt_dir,
            timeout_seconds=3600,
        )

    call_kwargs = mock_flow_cls.call_args.kwargs
    assert call_kwargs.get("config_override_strings") is None


# ---------------------------------------------------------------------------
# Tests: timeout handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_timeout_returns_timeout_status(attempt_dir, tmp_path):
    """Stage exceeding timeout should return timeout status."""
    adapter = LibreLaneLocalAdapter(pdk="sky130A")

    fake_flow = MagicMock()
    fake_flow.start = MagicMock()
    patcher, _ = _patch_flow_factory(fake_flow)

    async def _slow_to_thread(fn, *args, **kwargs):
        """Simulate a slow LibreLane run via asyncio.to_thread."""
        await asyncio.sleep(10)

    with patcher, patch(
        "agenticlane.execution.librelane_adapter.asyncio.to_thread",
        side_effect=_slow_to_thread,
    ):
        result = await adapter.run_stage(
            run_root=str(tmp_path),
            stage_name="SYNTH",
            librelane_config_path=str(tmp_path / "config.yaml"),
            resolved_design_config_path=str(tmp_path / "config.yaml"),
            patch={"config_vars": {}},
            state_in_path=None,
            attempt_dir=attempt_dir,
            timeout_seconds=1,  # 1 second timeout
        )

    assert result.execution_status == "timeout"
    assert result.exit_code == 124
    assert "timed out" in (result.stderr_tail or "").lower()


# ---------------------------------------------------------------------------
# Tests: error handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_crash_returns_tool_crash_status(adapter, attempt_dir, tmp_path):
    """LibreLane exceptions should be caught and return tool_crash."""
    fake_flow = MagicMock()
    fake_flow.start = MagicMock(side_effect=RuntimeError("OpenROAD segfault"))
    patcher, _ = _patch_flow_factory(fake_flow)

    with patcher:
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
    assert "OpenROAD segfault" in (result.error_summary or "")


@pytest.mark.asyncio
async def test_unknown_stage_returns_config_error(adapter, attempt_dir, tmp_path):
    """Unknown stage name should return config_error."""
    result = await adapter.run_stage(
        run_root=str(tmp_path),
        stage_name="NONEXISTENT",
        librelane_config_path=str(tmp_path / "config.yaml"),
        resolved_design_config_path=str(tmp_path / "config.yaml"),
        patch={"config_vars": {}},
        state_in_path=None,
        attempt_dir=attempt_dir,
        timeout_seconds=3600,
    )

    assert result.execution_status == "config_error"
    assert "Unknown stage" in (result.stderr_tail or "")


# ---------------------------------------------------------------------------
# Tests: artifact collection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_artifacts_collected(adapter, attempt_dir, tmp_path):
    """Report files should be copied from workspace to artifacts dir."""
    workspace_dir = os.path.join(attempt_dir, "workspace")
    fake_flow = _make_fake_flow(workspace_dir=workspace_dir)
    patcher, _ = _patch_flow_factory(fake_flow)

    with patcher:
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
    # The timing.rpt should have been collected
    assert (artifacts_path / "timing.rpt").is_file()


# ---------------------------------------------------------------------------
# Tests: pdk_root / scl passthrough
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pdk_root_and_scl_passed_to_flow(attempt_dir, tmp_path):
    """pdk_root and scl should be forwarded to the flow constructor."""
    adapter = LibreLaneLocalAdapter(
        pdk_root="/opt/pdks",
        pdk="gf180mcuD",
        scl="gf180mcu_fd_sc_mcu7t5v0",
    )

    fake_flow = MagicMock()
    fake_flow.start = MagicMock()

    mock_flow_cls = MagicMock(return_value=fake_flow)
    mock_factory = MagicMock()
    mock_factory.get.return_value = mock_flow_cls
    mock_flow_mod = MagicMock()
    mock_flow_mod.factory = mock_factory

    with patch("agenticlane.execution.librelane_adapter.Flow", mock_flow_mod):
        await adapter.run_stage(
            run_root=str(tmp_path),
            stage_name="SYNTH",
            librelane_config_path=str(tmp_path / "config.yaml"),
            resolved_design_config_path=str(tmp_path / "config.yaml"),
            patch={"config_vars": {}},
            state_in_path=None,
            attempt_dir=attempt_dir,
            timeout_seconds=3600,
        )

    call_kwargs = mock_flow_cls.call_args.kwargs
    assert call_kwargs["pdk_root"] == "/opt/pdks"
    assert call_kwargs["pdk"] == "gf180mcuD"
    assert call_kwargs["scl"] == "gf180mcu_fd_sc_mcu7t5v0"


# ---------------------------------------------------------------------------
# Tests: Flow.factory.get("Classic") is called
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classic_flow_resolved_via_factory(adapter, attempt_dir, tmp_path):
    """The adapter should use Flow.factory.get('Classic') to get the flow class."""
    fake_flow = MagicMock()
    fake_flow.start = MagicMock()

    mock_flow_cls = MagicMock(return_value=fake_flow)
    mock_factory = MagicMock()
    mock_factory.get.return_value = mock_flow_cls
    mock_flow_mod = MagicMock()
    mock_flow_mod.factory = mock_factory

    with patch("agenticlane.execution.librelane_adapter.Flow", mock_flow_mod):
        await adapter.run_stage(
            run_root=str(tmp_path),
            stage_name="SYNTH",
            librelane_config_path=str(tmp_path / "config.yaml"),
            resolved_design_config_path=str(tmp_path / "config.yaml"),
            patch={"config_vars": {}},
            state_in_path=None,
            attempt_dir=attempt_dir,
            timeout_seconds=3600,
        )

    mock_factory.get.assert_called_once_with("Classic")
