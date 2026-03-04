"""Integration test: Run all 10 stages through LibreLaneLocalAdapter.

Requires: nix develop shell with EDA tools + .venv-nix activated.

Run with::

    pytest tests/integration/test_adapter_pipeline.py -m integration -v

This file is excluded from the normal ``pytest`` invocation because it
requires real EDA tools (yosys, openroad, magic, etc.) that are only
available inside the Nix development shell.
"""
from __future__ import annotations

import os
import shutil
import tempfile

import pytest

from agenticlane.execution.librelane_adapter import LibreLaneLocalAdapter
from agenticlane.orchestration.graph import STAGE_ORDER


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PDK_ROOT = os.environ.get(
    "PDK_ROOT",
    os.path.expanduser(
        "~/.ciel/ciel/sky130/versions/"
        "54435919abffb937387ec956209f9cf5fd2dfbee"
    ),
)
CONFIG_PATH = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "examples",
        "counter_sky130",
        "config.yaml",
    )
)


# ---------------------------------------------------------------------------
# Marker + skip guard
# ---------------------------------------------------------------------------


def _eda_tools_available() -> bool:
    """Return True when the minimum required EDA tool (yosys) is on PATH."""
    return shutil.which("yosys") is not None


@pytest.mark.integration
@pytest.mark.skipif(
    not _eda_tools_available(),
    reason="EDA tools not available — run inside `nix develop` shell",
)
@pytest.mark.asyncio
async def test_full_pipeline() -> None:
    """Run all 10 LibreLane stages sequentially and assert each one succeeds.

    The test mirrors the original ``run_pipeline()`` script but replaces
    ``print()`` calls with assertions so that failures surface as proper
    pytest errors with informative messages.
    """
    adapter = LibreLaneLocalAdapter(
        pdk_root=PDK_ROOT,
        pdk="sky130A",
        scl="sky130_fd_sc_hd",
    )

    run_root = tempfile.mkdtemp(prefix="agenticlane_pipeline_")
    config_path = CONFIG_PATH

    assert os.path.isfile(config_path), (
        f"Design config not found: {config_path}\n"
        "Check that the counter_sky130 example exists under examples/."
    )

    state_in_path: str | None = None
    results: dict[str, object] = {}

    for stage_name in STAGE_ORDER:
        attempt_dir = os.path.join(run_root, "B0", stage_name, "attempt_001")
        os.makedirs(attempt_dir, exist_ok=True)

        result = await adapter.run_stage(
            run_root=run_root,
            stage_name=stage_name,
            librelane_config_path=config_path,
            resolved_design_config_path=config_path,
            patch={"config_vars": {}},
            state_in_path=state_in_path,
            attempt_dir=attempt_dir,
            timeout_seconds=300,
        )

        results[stage_name] = result

        # The attempt_dir and artifacts_dir must always be populated
        assert result.attempt_dir, (
            f"[{stage_name}] result.attempt_dir is empty"
        )
        assert result.artifacts_dir, (
            f"[{stage_name}] result.artifacts_dir is empty"
        )

        # runtime must be a non-negative number
        assert result.runtime_seconds >= 0.0, (
            f"[{stage_name}] runtime_seconds={result.runtime_seconds!r} is negative"
        )

        # The stage must succeed — if it fails, emit a descriptive message
        assert result.execution_status == "success", (
            f"[{stage_name}] execution_status={result.execution_status!r}  "
            f"exit_code={result.exit_code}  "
            f"error_summary={result.error_summary!r}\n"
            f"stderr_tail={result.stderr_tail[:500] if result.stderr_tail else '(none)'}"
        )

        # On success the adapter must hand back a state_out path so the next
        # stage can pick it up as its state_in.
        assert result.state_out_path is not None, (
            f"[{stage_name}] succeeded but state_out_path is None — "
            "subsequent stages will have no state_in"
        )
        assert os.path.isfile(result.state_out_path), (
            f"[{stage_name}] state_out_path={result.state_out_path!r} does not exist on disk"
        )

        # Artifacts directory must exist (may be empty for some stages, but
        # the path itself should be real after a successful run).
        assert os.path.isdir(result.artifacts_dir), (
            f"[{stage_name}] artifacts_dir={result.artifacts_dir!r} is not a directory"
        )

        # Thread state forward
        state_in_path = result.state_out_path

    # All 10 stages in STAGE_ORDER must have been executed
    assert len(results) == len(STAGE_ORDER), (
        f"Expected {len(STAGE_ORDER)} stage results, got {len(results)}. "
        f"Completed: {list(results.keys())}"
    )

    # Summarise pass/fail counts as a final sanity assertion
    passed = sum(
        1 for r in results.values() if r.execution_status == "success"  # type: ignore[union-attr]
    )
    assert passed == len(STAGE_ORDER), (
        f"Only {passed}/{len(STAGE_ORDER)} stages passed. "
        f"Failed stages: "
        f"{[s for s, r in results.items() if r.execution_status != 'success']}"  # type: ignore[union-attr]
    )
