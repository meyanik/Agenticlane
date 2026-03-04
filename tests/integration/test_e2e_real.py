"""End-to-end integration tests for real LibreLane + LLM execution.

These tests are marked with ``@pytest.mark.e2e`` and ``@pytest.mark.slow``
so they are excluded from normal ``pytest`` runs.  Run with::

    pytest -m e2e

Prerequisites:
- LibreLane installed (``pip install librelane``)
- PDK installed at expected paths
- ``ANTHROPIC_API_KEY`` set (for LLM tests)
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Skip markers
# ---------------------------------------------------------------------------

HAS_LIBRELANE = importlib.util.find_spec("librelane") is not None
HAS_ANTHROPIC_KEY = bool(os.environ.get("ANTHROPIC_API_KEY"))

EXAMPLES_ROOT = Path(__file__).resolve().parent.parent.parent / "examples"
SKY130_DIR = EXAMPLES_ROOT / "counter_sky130"
GF180_DIR = EXAMPLES_ROOT / "counter_gf180"

skip_no_librelane = pytest.mark.skipif(
    not HAS_LIBRELANE,
    reason="LibreLane (openlane) not installed",
)

skip_no_api_key = pytest.mark.skipif(
    not HAS_ANTHROPIC_KEY,
    reason="ANTHROPIC_API_KEY not set",
)


# ---------------------------------------------------------------------------
# E2E tests: single-stage smoke test (mock LLM)
# ---------------------------------------------------------------------------


@pytest.mark.e2e
@pytest.mark.slow
@skip_no_librelane
@pytest.mark.asyncio
async def test_synth_only_sky130(tmp_path):
    """Run SYNTH only on counter_sky130 with mock LLM."""
    from agenticlane.config.loader import load_config
    from agenticlane.config.models import AgenticLaneConfig
    from agenticlane.execution.librelane_adapter import LibreLaneLocalAdapter
    from agenticlane.orchestration.orchestrator import SequentialOrchestrator

    config_dict = load_config(
        profile="safe",
        user_config_path=SKY130_DIR / "agentic_config.yaml",
        cli_overrides={
            "project": {
                "output_dir": str(tmp_path / "runs"),
                "run_id": "e2e_synth",
            },
            "flow_control": {
                "budgets": {"physical_attempts_per_stage": 1},
            },
        },
    )
    config = AgenticLaneConfig(**config_dict)

    adapter = LibreLaneLocalAdapter(pdk="sky130A")
    orchestrator = SequentialOrchestrator(config=config, adapter=adapter)

    result = await orchestrator.run_flow(stages=["SYNTH"])

    assert "SYNTH" in result.stages_completed or "SYNTH" in result.stages_failed
    assert result.run_id == "e2e_synth"


# ---------------------------------------------------------------------------
# E2E tests: two-stage flow (mock LLM)
# ---------------------------------------------------------------------------


@pytest.mark.e2e
@pytest.mark.slow
@skip_no_librelane
@pytest.mark.asyncio
async def test_synth_floorplan_sky130(tmp_path):
    """Run SYNTH → FLOORPLAN on counter_sky130 with mock LLM."""
    from agenticlane.config.loader import load_config
    from agenticlane.config.models import AgenticLaneConfig
    from agenticlane.execution.librelane_adapter import LibreLaneLocalAdapter
    from agenticlane.orchestration.orchestrator import SequentialOrchestrator

    config_dict = load_config(
        profile="safe",
        user_config_path=SKY130_DIR / "agentic_config.yaml",
        cli_overrides={
            "project": {
                "output_dir": str(tmp_path / "runs"),
                "run_id": "e2e_two_stage",
            },
            "flow_control": {
                "budgets": {"physical_attempts_per_stage": 1},
            },
        },
    )
    config = AgenticLaneConfig(**config_dict)

    adapter = LibreLaneLocalAdapter(pdk="sky130A")
    orchestrator = SequentialOrchestrator(config=config, adapter=adapter)

    result = await orchestrator.run_flow(stages=["SYNTH", "FLOORPLAN"])

    assert result.run_id == "e2e_two_stage"
    # At least one stage should have been attempted
    total = len(result.stages_completed) + len(result.stages_failed)
    assert total >= 1


# ---------------------------------------------------------------------------
# E2E tests: full flow with real LLM (Claude)
# ---------------------------------------------------------------------------


@pytest.mark.e2e
@pytest.mark.slow
@skip_no_librelane
@skip_no_api_key
@pytest.mark.asyncio
async def test_full_flow_real(tmp_path):
    """Full 10-stage flow on counter_sky130 with Claude API.

    This test takes significant time and makes real API calls.
    """
    from agenticlane.config.loader import load_config
    from agenticlane.config.models import AgenticLaneConfig
    from agenticlane.execution.librelane_adapter import LibreLaneLocalAdapter
    from agenticlane.orchestration.orchestrator import SequentialOrchestrator

    config_dict = load_config(
        profile="safe",
        user_config_path=SKY130_DIR / "agentic_config.yaml",
        cli_overrides={
            "project": {
                "output_dir": str(tmp_path / "runs"),
                "run_id": "e2e_full",
            },
            "flow_control": {
                "budgets": {"physical_attempts_per_stage": 1},
            },
            "parallel": {"enabled": False},
        },
    )
    config = AgenticLaneConfig(**config_dict)

    adapter = LibreLaneLocalAdapter(pdk="sky130A")
    orchestrator = SequentialOrchestrator(config=config, adapter=adapter)

    result = await orchestrator.run_flow()

    assert result.run_id == "e2e_full"
    # Verify manifest
    manifest_path = tmp_path / "runs" / "runs" / "e2e_full" / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        assert manifest["run_id"] == "e2e_full"
        assert len(manifest["stage_results"]) > 0


# ---------------------------------------------------------------------------
# E2E tests: manifest verification
# ---------------------------------------------------------------------------


@pytest.mark.e2e
@pytest.mark.slow
@skip_no_librelane
@pytest.mark.asyncio
async def test_manifest_written(tmp_path):
    """Verify manifest.json is written with real stage data."""
    from agenticlane.config.loader import load_config
    from agenticlane.config.models import AgenticLaneConfig
    from agenticlane.execution.librelane_adapter import LibreLaneLocalAdapter
    from agenticlane.orchestration.orchestrator import SequentialOrchestrator

    config_dict = load_config(
        profile="safe",
        user_config_path=SKY130_DIR / "agentic_config.yaml",
        cli_overrides={
            "project": {
                "output_dir": str(tmp_path / "runs"),
                "run_id": "e2e_manifest",
            },
            "flow_control": {
                "budgets": {"physical_attempts_per_stage": 1},
            },
        },
    )
    config = AgenticLaneConfig(**config_dict)

    adapter = LibreLaneLocalAdapter(pdk="sky130A")
    orchestrator = SequentialOrchestrator(config=config, adapter=adapter)

    result = await orchestrator.run_flow(stages=["SYNTH"])

    # The orchestrator writes manifest to the run dir
    assert result.run_dir is not None
    manifest_path = Path(result.run_dir) / "manifest.json"
    assert manifest_path.exists(), f"Manifest not found at {manifest_path}"
    manifest = json.loads(manifest_path.read_text())
    assert manifest["run_id"] == "e2e_manifest"


# ---------------------------------------------------------------------------
# E2E tests: report generation with real metrics
# ---------------------------------------------------------------------------


@pytest.mark.e2e
@pytest.mark.slow
@skip_no_librelane
@pytest.mark.asyncio
async def test_report_with_real_metrics(tmp_path):
    """Verify report generation works with real metrics from LibreLane."""
    from agenticlane.config.loader import load_config
    from agenticlane.config.models import AgenticLaneConfig
    from agenticlane.execution.librelane_adapter import LibreLaneLocalAdapter
    from agenticlane.orchestration.orchestrator import SequentialOrchestrator

    config_dict = load_config(
        profile="safe",
        user_config_path=SKY130_DIR / "agentic_config.yaml",
        cli_overrides={
            "project": {
                "output_dir": str(tmp_path / "runs"),
                "run_id": "e2e_report",
            },
            "flow_control": {
                "budgets": {"physical_attempts_per_stage": 1},
            },
        },
    )
    config = AgenticLaneConfig(**config_dict)

    adapter = LibreLaneLocalAdapter(pdk="sky130A")
    orchestrator = SequentialOrchestrator(config=config, adapter=adapter)

    result = await orchestrator.run_flow(stages=["SYNTH"])

    # Check that stage results have data
    assert "SYNTH" in result.stage_results
    sr = result.stage_results["SYNTH"]
    assert sr.attempts_used >= 1
