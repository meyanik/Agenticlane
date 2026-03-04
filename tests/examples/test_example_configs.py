"""Tests for the bundled example designs (examples/ directory).

Validates that all YAML configs parse correctly, Verilog files exist,
SDC files have clock definitions, and agentic_config.yaml loads
through the config loader.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

# Root of the examples directory
EXAMPLES_ROOT = Path(__file__).resolve().parent.parent.parent / "examples"

EXAMPLE_DIRS = [
    EXAMPLES_ROOT / "counter_sky130",
    EXAMPLES_ROOT / "counter_gf180",
]


# ---------------------------------------------------------------------------
# Parametrize over all example directories
# ---------------------------------------------------------------------------


@pytest.fixture(params=EXAMPLE_DIRS, ids=[d.name for d in EXAMPLE_DIRS])
def example_dir(request: pytest.FixtureRequest) -> Path:
    return request.param


# ---------------------------------------------------------------------------
# Tests: directory structure
# ---------------------------------------------------------------------------


def test_example_dir_exists(example_dir: Path):
    """Example directory must exist."""
    assert example_dir.is_dir(), f"Missing example dir: {example_dir}"


def test_verilog_file_exists(example_dir: Path):
    """src/counter.v must exist and be non-empty."""
    verilog = example_dir / "src" / "counter.v"
    assert verilog.is_file(), f"Missing Verilog file: {verilog}"
    content = verilog.read_text()
    assert len(content) > 0, "Verilog file is empty"
    assert "module counter" in content, "Verilog file doesn't define module counter"


def test_sdc_file_exists(example_dir: Path):
    """constraints.sdc must exist and have a clock definition."""
    sdc = example_dir / "constraints.sdc"
    assert sdc.is_file(), f"Missing SDC file: {sdc}"
    content = sdc.read_text()
    assert "create_clock" in content, "SDC file has no create_clock definition"


# ---------------------------------------------------------------------------
# Tests: config.yaml (LibreLane design config)
# ---------------------------------------------------------------------------


def test_design_config_parses(example_dir: Path):
    """config.yaml must be valid YAML with required keys."""
    config_path = example_dir / "config.yaml"
    assert config_path.is_file(), f"Missing config.yaml: {config_path}"

    with open(config_path) as f:
        data = yaml.safe_load(f)

    assert isinstance(data, dict), "config.yaml should be a dict"
    assert "DESIGN_NAME" in data
    assert "VERILOG_FILES" in data
    assert "CLOCK_PORT" in data
    assert "CLOCK_PERIOD" in data
    assert "PDK" in data


def test_design_config_has_pdk(example_dir: Path):
    """config.yaml must specify a valid PDK."""
    with open(example_dir / "config.yaml") as f:
        data = yaml.safe_load(f)

    pdk = data["PDK"]
    assert pdk in {"sky130A", "sky130B", "gf180mcuC", "gf180mcuD"}, (
        f"Unexpected PDK: {pdk}"
    )


def test_design_config_clock_period_positive(example_dir: Path):
    """Clock period must be a positive number."""
    with open(example_dir / "config.yaml") as f:
        data = yaml.safe_load(f)

    period = data["CLOCK_PERIOD"]
    assert isinstance(period, (int, float))
    assert period > 0, f"Clock period must be positive, got {period}"


# ---------------------------------------------------------------------------
# Tests: agentic_config.yaml (AgenticLane orchestration config)
# ---------------------------------------------------------------------------


def test_agentic_config_parses(example_dir: Path):
    """agentic_config.yaml must be valid YAML with expected sections."""
    config_path = example_dir / "agentic_config.yaml"
    assert config_path.is_file(), f"Missing agentic_config.yaml: {config_path}"

    with open(config_path) as f:
        data = yaml.safe_load(f)

    assert isinstance(data, dict), "agentic_config.yaml should be a dict"
    assert "project" in data
    assert "design" in data
    assert "llm" in data


def test_agentic_config_loads_via_config_loader(example_dir: Path):
    """agentic_config.yaml must load through the AgenticLane config loader."""
    from agenticlane.config.loader import load_config

    config_path = example_dir / "agentic_config.yaml"
    merged = load_config(
        profile="safe",
        user_config_path=config_path,
    )

    assert isinstance(merged, dict)
    # The user config should merge with profile defaults
    assert "project" in merged


def test_agentic_config_validates(example_dir: Path):
    """agentic_config.yaml must pass Pydantic validation."""
    from agenticlane.config.loader import load_config
    from agenticlane.config.models import AgenticLaneConfig

    config_path = example_dir / "agentic_config.yaml"
    merged = load_config(
        profile="safe",
        user_config_path=config_path,
    )

    config = AgenticLaneConfig(**merged)
    assert config.project.name in {"counter_sky130", "counter_gf180"}


def test_agentic_config_llm_section(example_dir: Path):
    """LLM config section should have valid provider and model settings."""
    with open(example_dir / "agentic_config.yaml") as f:
        data = yaml.safe_load(f)

    llm = data["llm"]
    assert llm["provider"] == "litellm"
    assert "models" in llm
    assert "worker" in llm["models"]


# ---------------------------------------------------------------------------
# Tests: sky130-specific and gf180-specific
# ---------------------------------------------------------------------------


def test_sky130_pdk():
    """sky130 example must use sky130A PDK."""
    config_path = EXAMPLES_ROOT / "counter_sky130" / "config.yaml"
    if not config_path.exists():
        pytest.skip("sky130 example not present")
    with open(config_path) as f:
        data = yaml.safe_load(f)
    assert data["PDK"] == "sky130A"
    assert data["CLOCK_PERIOD"] == 10.0


def test_gf180_pdk():
    """gf180 example must use gf180mcuD PDK."""
    config_path = EXAMPLES_ROOT / "counter_gf180" / "config.yaml"
    if not config_path.exists():
        pytest.skip("gf180 example not present")
    with open(config_path) as f:
        data = yaml.safe_load(f)
    assert data["PDK"] == "gf180mcuD"
    assert data["CLOCK_PERIOD"] == 24.0
