"""Shared test fixtures for AgenticLane test suite."""

from pathlib import Path

import pytest


@pytest.fixture
def project_root() -> Path:
    """Return the project root directory."""
    return Path(__file__).parent.parent


@pytest.fixture
def golden_dir() -> Path:
    """Return the golden test data directory."""
    return Path(__file__).parent / "golden"


@pytest.fixture
def sample_design_config() -> dict:
    """Return a minimal design config dict for testing."""
    return {
        "DESIGN_NAME": "spm",
        "CLOCK_PERIOD": 10.0,
        "CLOCK_PORT": "clk",
        "VERILOG_FILES": "dir::src/*.v",
        "FP_CORE_UTIL": 45,
    }


@pytest.fixture
def sample_agentic_config() -> dict:
    """Return a minimal AgenticLane config dict for testing."""
    return {
        "project": {
            "name": "test_design",
            "run_id": "test_run_001",
            "output_dir": "./runs",
        },
        "design": {
            "librelane_config_path": "./design/config.yaml",
            "pdk": "sky130A",
        },
        "execution": {
            "mode": "local",
            "tool_timeout_seconds": 3600,
        },
        "llm": {
            "mode": "local",
            "provider": "litellm",
        },
    }
