"""Tests for agenticlane.config.models -- P1.1 Config Models.

Covers:
  - default config validation
  - JSON roundtrip
  - partial override merging
  - boundary validators (physical_attempts, epsilon, parallel jobs)
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from agenticlane.config.models import (
    AgenticLaneConfig,
    BudgetConfig,
    NormalizationConfig,
    ParallelConfig,
)

# -------------------------------------------------------------------
# test_default_config_valid
# -------------------------------------------------------------------


def test_default_config_valid() -> None:
    """AgenticLaneConfig() with all defaults must validate without error."""
    cfg = AgenticLaneConfig()

    # Spot-check a selection of safe defaults
    assert cfg.project.name == "my_block"
    assert cfg.project.run_id == "auto"
    assert cfg.execution.mode == "local"
    assert cfg.execution.tool_timeout_seconds == 21600
    assert cfg.execution.workspace.isolation == "per_attempt"
    assert cfg.flow_control.budgets.physical_attempts_per_stage == 12
    assert cfg.flow_control.budgets.cognitive_retries_per_attempt == 3
    assert cfg.parallel.enabled is True
    assert cfg.parallel.max_parallel_branches == 3
    assert cfg.parallel.max_parallel_jobs == 2
    assert cfg.action_space.permissions.tcl is False
    assert cfg.action_space.permissions.rtl_eco is False
    assert cfg.action_space.sdc.mode == "templated"
    assert cfg.constraints.locked_vars == ["CLOCK_PERIOD"]
    assert cfg.constraints.guard.enabled is True
    assert cfg.scoring.normalization.epsilon == pytest.approx(1e-6)
    assert cfg.artifact_gc.compression == "zstd"
    assert cfg.llm.mode == "local"
    assert cfg.llm.temperature == 0.0
    assert cfg.llm.seed == 42
    assert cfg.llm.reproducibility_mode == "deterministic"


# -------------------------------------------------------------------
# test_config_roundtrip_json
# -------------------------------------------------------------------


def test_config_roundtrip_json() -> None:
    """Serializing to JSON and back must produce an identical config."""
    original = AgenticLaneConfig()
    json_str = original.model_dump_json()
    restored = AgenticLaneConfig.model_validate_json(json_str)

    # Compare full dict representations
    assert original.model_dump() == restored.model_dump()

    # Also verify the JSON is valid JSON (parse without error)
    parsed = json.loads(json_str)
    assert isinstance(parsed, dict)
    assert "project" in parsed
    assert "llm" in parsed


# -------------------------------------------------------------------
# test_config_partial_override
# -------------------------------------------------------------------


def test_config_partial_override() -> None:
    """A partial dict merged onto defaults must override only the given keys."""
    overrides = {
        "project": {"name": "overridden_block", "run_id": "run_42"},
        "execution": {"mode": "docker", "tool_timeout_seconds": 7200},
        "parallel": {"enabled": False, "max_parallel_branches": 1, "max_parallel_jobs": 1},
        "scoring": {"normalization": {"epsilon": 1e-3}},
    }
    cfg = AgenticLaneConfig.model_validate(overrides)

    # Overridden fields
    assert cfg.project.name == "overridden_block"
    assert cfg.project.run_id == "run_42"
    assert cfg.execution.mode == "docker"
    assert cfg.execution.tool_timeout_seconds == 7200
    assert cfg.parallel.enabled is False
    assert cfg.scoring.normalization.epsilon == pytest.approx(1e-3)

    # Defaults preserved for non-overridden fields
    assert cfg.project.output_dir.as_posix() == "runs"
    assert cfg.design.pdk == "sky130A"
    assert cfg.flow_control.deadlock_policy == "auto_relax"
    assert cfg.constraints.locked_vars == ["CLOCK_PERIOD"]
    assert cfg.llm.provider == "litellm"


# -------------------------------------------------------------------
# test_physical_attempts_gte_one
# -------------------------------------------------------------------


def test_physical_attempts_gte_one() -> None:
    """physical_attempts_per_stage must be >= 1."""
    with pytest.raises(ValidationError) as exc_info:
        BudgetConfig(physical_attempts_per_stage=0)

    errors = exc_info.value.errors()
    assert any(
        "physical_attempts_per_stage" in str(e.get("loc", ""))
        for e in errors
    )


# -------------------------------------------------------------------
# test_epsilon_must_be_positive
# -------------------------------------------------------------------


def test_epsilon_must_be_positive() -> None:
    """scoring.normalization.epsilon must be > 0."""
    with pytest.raises(ValidationError) as exc_info:
        NormalizationConfig(epsilon=0.0)

    errors = exc_info.value.errors()
    assert any("epsilon" in str(e.get("loc", "")) for e in errors)

    # Negative must also fail
    with pytest.raises(ValidationError):
        NormalizationConfig(epsilon=-1e-9)


# -------------------------------------------------------------------
# test_max_parallel_jobs_lte_branches
# -------------------------------------------------------------------


def test_max_parallel_jobs_lte_branches() -> None:
    """max_parallel_jobs must be <= max_parallel_branches."""
    # Valid: jobs == branches
    cfg = ParallelConfig(max_parallel_branches=4, max_parallel_jobs=4)
    assert cfg.max_parallel_jobs == 4

    # Valid: jobs < branches
    cfg = ParallelConfig(max_parallel_branches=5, max_parallel_jobs=2)
    assert cfg.max_parallel_jobs == 2

    # Invalid: jobs > branches
    with pytest.raises(ValidationError) as exc_info:
        ParallelConfig(max_parallel_branches=2, max_parallel_jobs=5)

    errors = exc_info.value.errors()
    assert any("max_parallel_jobs" in str(e) for e in errors)
