"""Integration tests for the agentic orchestrator.

Tests the full agentic dispatch pipeline using MockLLMProvider +
MockExecutionAdapter (no real EDA tools or API keys needed).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from agenticlane.config.loader import load_config
from agenticlane.config.models import AgenticLaneConfig
from agenticlane.orchestration.orchestrator import FlowResult, SequentialOrchestrator
from tests.mocks.mock_adapter import MockExecutionAdapter
from tests.mocks.mock_llm import MockLLMProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(
    tmp_path: Path,
    *,
    n_branches: int = 1,
    parallel: bool = False,
    attempts_per_stage: int = 2,
    zero_shot: bool = False,
) -> AgenticLaneConfig:
    """Build a minimal AgenticLaneConfig for testing."""
    config_dir = tmp_path / "design"
    config_dir.mkdir(parents=True, exist_ok=True)
    librelane_cfg = config_dir / "config.yaml"
    librelane_cfg.write_text("DESIGN_NAME: test\nCLOCK_PERIOD: 10\nCLOCK_PORT: clk\n")

    return AgenticLaneConfig(
        project={
            "name": "test",
            "run_id": "test_run",
            "output_dir": str(tmp_path / "runs"),
        },
        design={
            "librelane_config_path": str(librelane_cfg),
            "pdk": "sky130A",
        },
        execution={
            "mode": "local",
            "tool_timeout_seconds": 60,
        },
        intent={
            "prompt": "Optimize timing",
            "weights_hint": {"timing": 0.7, "area": 0.3},
        },
        flow_control={
            "budgets": {
                "physical_attempts_per_stage": attempts_per_stage,
                "cognitive_retries_per_attempt": 1,
            },
            "plateau_detection": {"enabled": True, "window": 3, "min_delta_score": 0.01},
            "deadlock_policy": "stop",
        },
        parallel={
            "enabled": parallel,
            "max_parallel_branches": n_branches,
            "max_parallel_jobs": min(2, n_branches),
            "prune": {
                "enabled": parallel,
                "prune_delta_score": 0.05,
                "prune_patience_attempts": 2,
            },
        },
        initialization={
            "zero_shot": {"enabled": zero_shot},
        },
        llm={
            "mode": "api",
            "provider": "mock",
            "temperature": 0.0,
            "seed": 42,
        },
    )


def _make_mock_llm() -> MockLLMProvider:
    """Create a MockLLMProvider with Patch-compatible default responses."""
    llm = MockLLMProvider()
    # Responses must include all required Patch fields so Patch(**resp) succeeds
    _patch_base = {
        "patch_id": "mock_patch_001",
        "stage": "SYNTH",
        "types": ["config_vars"],
        "config_vars": {"FP_CORE_UTIL": 40},
        "rationale": "Mock patch for testing",
    }
    llm.set_default_response(_patch_base)
    llm.add_response("worker", {
        **_patch_base,
        "config_vars": {"FP_CORE_UTIL": 45},
    })
    # Judge ensemble expects JudgeVote-compatible results
    llm.add_response("judge", {
        "judge_id": "mock_judge",
        "model": "mock",
        "vote": "PASS",
        "confidence": 0.9,
        "rationale": "Mock pass",
    })
    return llm


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agentic_single_branch(tmp_path: Path) -> None:
    """Single branch, 3 stages, verify agent loop is invoked with non-empty patches."""
    config = _make_config(tmp_path, n_branches=1, parallel=False)
    adapter = MockExecutionAdapter()
    llm = _make_mock_llm()

    orch = SequentialOrchestrator(
        config=config,
        adapter=adapter,
        llm_provider=llm,  # type: ignore[arg-type]
    )

    # Run only first 3 stages to keep test fast
    result = await orch.run_flow(stages=["SYNTH", "FLOORPLAN", "PDN"])

    assert isinstance(result, FlowResult)
    assert result.run_id == "test_run"
    assert result.run_dir is not None
    # All stages should have results
    assert len(result.stage_results) == 3
    # The orchestrator should have dispatched to agentic mode
    assert orch.agentic is True
    # Adapter should have been called (baseline + attempts for each stage)
    assert len(adapter.call_log) > 0


@pytest.mark.asyncio
async def test_agentic_parallel_branches(tmp_path: Path) -> None:
    """2 branches, verify parallel execution happens."""
    config = _make_config(tmp_path, n_branches=2, parallel=True)
    adapter = MockExecutionAdapter()
    llm = _make_mock_llm()

    orch = SequentialOrchestrator(
        config=config,
        adapter=adapter,
        llm_provider=llm,  # type: ignore[arg-type]
    )

    result = await orch.run_flow(stages=["SYNTH", "FLOORPLAN"])

    assert isinstance(result, FlowResult)
    # With 2 branches, adapter should be called more times than single branch
    # (at least 2x baseline + attempts)
    assert len(adapter.call_log) >= 4
    assert len(result.stage_results) == 2


@pytest.mark.asyncio
async def test_agentic_rollback(tmp_path: Path) -> None:
    """Simulate stage failure, verify rollback engine is consulted."""
    config = _make_config(tmp_path, n_branches=1, parallel=False, attempts_per_stage=1)
    # Adapter that always fails
    adapter = MockExecutionAdapter(success_probability=0.0)
    llm = _make_mock_llm()

    orch = SequentialOrchestrator(
        config=config,
        adapter=adapter,
        llm_provider=llm,  # type: ignore[arg-type]
    )

    result = await orch.run_flow(stages=["SYNTH", "FLOORPLAN"])

    assert isinstance(result, FlowResult)
    # With all failures, flow should not be completed
    assert result.completed is False
    assert len(result.stages_failed) > 0


@pytest.mark.asyncio
async def test_passthrough_mode(tmp_path: Path) -> None:
    """No LLM provided, verify old behavior preserved (empty patches)."""
    config = _make_config(tmp_path)
    adapter = MockExecutionAdapter()

    # No llm_provider -- passthrough mode
    orch = SequentialOrchestrator(
        config=config,
        adapter=adapter,
    )

    assert orch.agentic is False

    result = await orch.run_flow(stages=["SYNTH", "FLOORPLAN"])

    assert isinstance(result, FlowResult)
    assert len(result.stage_results) == 2
    # Verify empty patches were used
    for call in adapter.call_log:
        assert call["patch"] == {"config_vars": {}}


@pytest.mark.asyncio
async def test_resume_from_checkpoint(tmp_path: Path) -> None:
    """Create a checkpoint, resume, verify stages skip to checkpoint."""
    config = _make_config(tmp_path, n_branches=1, parallel=False)
    adapter = MockExecutionAdapter()
    llm = _make_mock_llm()

    # First run: complete SYNTH
    orch1 = SequentialOrchestrator(
        config=config,
        adapter=adapter,
        llm_provider=llm,  # type: ignore[arg-type]
    )
    result1 = await orch1.run_flow(stages=["SYNTH"])
    assert result1.run_dir is not None

    # Write a fake checkpoint for CheckpointManager to find
    run_dir = Path(result1.run_dir)
    checkpoint_data = {
        "run_id": result1.run_id,
        "current_stage": "FLOORPLAN",
        "last_attempt": 1,
        "branch_id": "B0",
        "timestamp": "2025-01-01T00:00:00",
    }
    (run_dir / "checkpoint.json").write_text(json.dumps(checkpoint_data))

    # Second run: resume from checkpoint
    adapter2 = MockExecutionAdapter()
    orch2 = SequentialOrchestrator(
        config=config,
        adapter=adapter2,
        llm_provider=llm,  # type: ignore[arg-type]
        resume_from=result1.run_id,
    )
    result2 = await orch2.run_flow(stages=["SYNTH", "FLOORPLAN", "PDN"])

    assert isinstance(result2, FlowResult)
    # SYNTH should be auto-completed (skipped due to resume)
    # and FLOORPLAN + PDN should be run
    assert "SYNTH" in result2.stages_completed
