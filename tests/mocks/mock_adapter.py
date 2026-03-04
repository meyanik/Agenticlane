"""MockExecutionAdapter for testing without real EDA tools.

Provides a deterministic, configurable mock that:
- Generates metrics that respond to knob changes
- Supports failure injection (crash, timeout, OOM)
- Creates realistic directory structures with synthetic files
- Is deterministic given the same inputs + seed
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any, Optional

from agenticlane.execution.adapter import ExecutionAdapter
from agenticlane.schemas.execution import ExecutionResult

# ---------------------------------------------------------------------------
# Default baseline metrics per stage
# ---------------------------------------------------------------------------

_STAGE_BASELINES: dict[str, dict[str, float]] = {
    "synth": {
        "core_area_um2": 500_000.0,
        "utilization_pct": 45.0,
        "setup_wns_ns": -0.15,
        "congestion_overflow_pct": 0.0,
    },
    "floorplan": {
        "core_area_um2": 520_000.0,
        "utilization_pct": 42.0,
        "setup_wns_ns": -0.12,
        "congestion_overflow_pct": 1.2,
    },
    "place_global": {
        "core_area_um2": 510_000.0,
        "utilization_pct": 44.0,
        "setup_wns_ns": -0.20,
        "congestion_overflow_pct": 3.5,
    },
    "place_detail": {
        "core_area_um2": 510_000.0,
        "utilization_pct": 44.0,
        "setup_wns_ns": -0.18,
        "congestion_overflow_pct": 2.8,
    },
    "cts": {
        "core_area_um2": 515_000.0,
        "utilization_pct": 44.5,
        "setup_wns_ns": -0.10,
        "congestion_overflow_pct": 2.5,
    },
    "route_global": {
        "core_area_um2": 515_000.0,
        "utilization_pct": 44.5,
        "setup_wns_ns": -0.08,
        "congestion_overflow_pct": 2.0,
    },
    "route_detail": {
        "core_area_um2": 515_000.0,
        "utilization_pct": 44.5,
        "setup_wns_ns": -0.05,
        "congestion_overflow_pct": 1.0,
    },
    "signoff": {
        "core_area_um2": 515_000.0,
        "utilization_pct": 44.5,
        "setup_wns_ns": -0.03,
        "congestion_overflow_pct": 0.5,
    },
}

# Fallback baseline for unknown stages
_DEFAULT_BASELINE: dict[str, float] = {
    "core_area_um2": 500_000.0,
    "utilization_pct": 45.0,
    "setup_wns_ns": -0.15,
    "congestion_overflow_pct": 2.0,
}


def _deterministic_hash(seed: int, *args: str) -> float:
    """Produce a deterministic float in [0, 1) from seed + string args."""
    h = hashlib.sha256(f"{seed}:{'|'.join(args)}".encode()).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


class MockExecutionAdapter(ExecutionAdapter):
    """Mock adapter for testing without real EDA tools.

    Features:
    - Deterministic: same knob values produce same metrics (with configurable noise)
    - Responds to knob changes: lower FP_CORE_UTIL -> larger area but less congestion
    - Configurable per-stage success probability
    - Failure injection: crash, timeout, OOM modes
    - Produces realistic directory structure with synthetic files
    """

    def __init__(
        self,
        *,
        success_probability: float = 1.0,
        failure_mode: str = "tool_crash",  # tool_crash | timeout | oom_killed
        noise_seed: int = 42,
        stage_configs: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        if not 0.0 <= success_probability <= 1.0:
            raise ValueError(
                f"success_probability must be in [0, 1], got {success_probability}"
            )
        valid_modes: set[str] = {"tool_crash", "timeout", "oom_killed"}
        if failure_mode not in valid_modes:
            raise ValueError(
                f"failure_mode must be one of {valid_modes}, got {failure_mode!r}"
            )

        self.success_probability = success_probability
        self.failure_mode = failure_mode
        self.noise_seed = noise_seed
        self.stage_configs: dict[str, dict[str, Any]] = stage_configs or {}

        # Track all calls for test assertions
        self.call_log: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

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
        """Run a mocked stage, creating synthetic outputs."""
        start = time.monotonic()

        # Record the call
        self.call_log.append(
            {
                "run_root": run_root,
                "stage_name": stage_name,
                "librelane_config_path": librelane_config_path,
                "resolved_design_config_path": resolved_design_config_path,
                "patch": patch,
                "state_in_path": state_in_path,
                "attempt_dir": attempt_dir,
                "timeout_seconds": timeout_seconds,
            }
        )

        # Create directory structure
        workspace_dir = os.path.join(attempt_dir, "workspace")
        artifacts_dir = os.path.join(attempt_dir, "artifacts")
        os.makedirs(workspace_dir, exist_ok=True)
        os.makedirs(artifacts_dir, exist_ok=True)

        # Determine success/failure
        stage_lower = stage_name.lower()
        stage_cfg = self.stage_configs.get(stage_lower, {})
        prob = stage_cfg.get("success_probability", self.success_probability)
        mode = stage_cfg.get("failure_mode", self.failure_mode)

        # Deterministic success check using hash
        success_roll = _deterministic_hash(
            self.noise_seed, stage_name, json.dumps(patch, sort_keys=True)
        )
        is_success = success_roll < prob

        if not is_success:
            return self._make_failure_result(
                failure_mode=mode,
                attempt_dir=attempt_dir,
                workspace_dir=workspace_dir,
                artifacts_dir=artifacts_dir,
                runtime=time.monotonic() - start,
            )

        # Generate metrics based on config_vars in patch
        config_vars = patch.get("config_vars", {})
        metrics = self._generate_metrics(stage_lower, config_vars)

        # Write synthetic output files
        state_out_path = self._write_synthetic_outputs(
            attempt_dir=attempt_dir,
            artifacts_dir=artifacts_dir,
            stage_name=stage_lower,
            metrics=metrics,
            config_vars=config_vars,
            state_in_path=state_in_path,
        )

        runtime = time.monotonic() - start

        return ExecutionResult(
            execution_status="success",
            exit_code=0,
            runtime_seconds=runtime,
            attempt_dir=attempt_dir,
            workspace_dir=workspace_dir,
            artifacts_dir=artifacts_dir,
            state_out_path=state_out_path,
            stderr_tail=None,
            error_summary=None,
        )

    # ------------------------------------------------------------------
    # Metric generation
    # ------------------------------------------------------------------

    def _generate_metrics(
        self,
        stage_name: str,
        config_vars: dict[str, Any],
    ) -> dict[str, float]:
        """Generate deterministic metrics that respond to knob changes.

        Knob effects:
        - FP_CORE_UTIL (default 45): higher -> smaller area, more congestion
        - PL_TARGET_DENSITY_PCT (default 60): higher -> worse (less) timing slack
        - GRT_ADJUSTMENT (default 0.0): higher -> more routing congestion
        """
        baseline = _STAGE_BASELINES.get(stage_name, _DEFAULT_BASELINE).copy()

        # --- FP_CORE_UTIL effects ---
        fp_util = float(config_vars.get("FP_CORE_UTIL", 45))
        # Utilization is directly set by the knob
        baseline["utilization_pct"] = fp_util

        # Higher utilization -> smaller area (inversely proportional)
        # baseline area at 45% util; scale: area * (45 / fp_util)
        area_scale = 45.0 / max(fp_util, 1.0)
        baseline["core_area_um2"] *= area_scale

        # Higher utilization -> more congestion (positive correlation)
        congestion_delta = (fp_util - 45.0) * 0.1  # +0.1% overflow per % util above 45
        baseline["congestion_overflow_pct"] = max(
            0.0, baseline["congestion_overflow_pct"] + congestion_delta
        )

        # --- PL_TARGET_DENSITY_PCT effects ---
        pl_density = float(config_vars.get("PL_TARGET_DENSITY_PCT", 60))
        # Higher density -> less timing slack (WNS gets worse / more negative)
        wns_delta = -(pl_density - 60.0) * 0.005  # -0.005 ns per % above 60
        baseline["setup_wns_ns"] += wns_delta

        # --- GRT_ADJUSTMENT effects ---
        grt_adj = float(config_vars.get("GRT_ADJUSTMENT", 0.0))
        # Higher adjustment -> more congestion
        baseline["congestion_overflow_pct"] = max(
            0.0, baseline["congestion_overflow_pct"] + grt_adj * 2.0
        )

        # Add small deterministic noise
        for key in baseline:
            noise = _deterministic_hash(
                self.noise_seed,
                stage_name,
                key,
                json.dumps(config_vars, sort_keys=True),
            )
            # Noise range: +/- 0.5% of the value
            noise_factor = 1.0 + (noise - 0.5) * 0.01
            baseline[key] *= noise_factor

        return baseline

    # ------------------------------------------------------------------
    # Synthetic file writing
    # ------------------------------------------------------------------

    def _write_synthetic_outputs(
        self,
        *,
        attempt_dir: str,
        artifacts_dir: str,
        stage_name: str,
        metrics: dict[str, float],
        config_vars: dict[str, Any],
        state_in_path: Optional[str],
    ) -> str:
        """Write synthetic state_out.json and report files. Returns state_out path."""
        # state_out.json
        state_out_path = os.path.join(attempt_dir, "state_out.json")
        state_out = {
            "stage": stage_name,
            "status": "success",
            "config_vars_applied": config_vars,
            "state_in": state_in_path,
            "outputs": {
                "def": os.path.join(artifacts_dir, f"{stage_name}.def"),
                "sdc": os.path.join(artifacts_dir, f"{stage_name}.sdc"),
                "netlist": os.path.join(artifacts_dir, f"{stage_name}.v"),
            },
            "metrics_snapshot": metrics,
        }
        with open(state_out_path, "w") as f:
            json.dump(state_out, f, indent=2)

        # timing.rpt
        timing_path = os.path.join(artifacts_dir, "timing.rpt")
        wns = metrics.get("setup_wns_ns", 0.0)
        with open(timing_path, "w") as f:
            f.write(f"# Synthetic timing report for {stage_name}\n")
            f.write("# Generated by MockExecutionAdapter\n")
            f.write(f"wns {wns:.4f}\n")
            f.write(f"tns {wns * 10:.4f}\n")
            f.write("Clock clk Period: 10.000\n")
            f.write(f"  Setup WNS: {wns:.4f} ns\n")
            f.write(f"  Setup TNS: {wns * 10:.4f} ns\n")

        # area.rpt
        area_path = os.path.join(artifacts_dir, "area.rpt")
        area = metrics.get("core_area_um2", 0.0)
        util = metrics.get("utilization_pct", 0.0)
        with open(area_path, "w") as f:
            f.write(f"# Synthetic area report for {stage_name}\n")
            f.write("# Generated by MockExecutionAdapter\n")
            f.write(f"Design area {area:.2f} u^2\n")
            f.write(f"Core utilization: {util:.2f}%\n")
            f.write(f"  Core area: {area:.2f} um^2\n")
            f.write(f"  Utilization: {util:.2f}%\n")

        # congestion.rpt (for routing stages)
        congestion_path = os.path.join(artifacts_dir, "congestion.rpt")
        overflow = metrics.get("congestion_overflow_pct", 0.0)
        with open(congestion_path, "w") as f:
            f.write(f"# Synthetic congestion report for {stage_name}\n")
            f.write("# Generated by MockExecutionAdapter\n")
            f.write(f"Overflow: {overflow:.4f}%\n")

        # Synthetic DEF file (placeholder)
        def_path = os.path.join(artifacts_dir, f"{stage_name}.def")
        with open(def_path, "w") as f:
            f.write(f"# Synthetic DEF for {stage_name}\n")
            f.write("VERSION 5.8 ;\n")
            f.write("DESIGN mock_design ;\n")
            f.write("END DESIGN\n")

        # For SIGNOFF stage, also produce LEF and GDS (needed for hierarchical flow)
        if stage_name == "signoff":
            lef_path = os.path.join(artifacts_dir, "design.lef")
            with open(lef_path, "w") as f:
                f.write("VERSION 5.8 ;\n")
                f.write("MACRO mock_design\n")
                f.write("  CLASS BLOCK ;\n")
                f.write("  SIZE 100.0 BY 100.0 ;\n")
                f.write("END mock_design\n")
                f.write("END LIBRARY\n")

            gds_path = os.path.join(artifacts_dir, "design.gds")
            with open(gds_path, "wb") as f:
                # Minimal GDS header (placeholder binary)
                f.write(b"\x00\x06\x00\x02\x00\x07")  # GDS magic bytes
                f.write(b"\x00" * 50)  # padding

        return state_out_path

    # ------------------------------------------------------------------
    # Failure result construction
    # ------------------------------------------------------------------

    def _make_failure_result(
        self,
        *,
        failure_mode: str,
        attempt_dir: str,
        workspace_dir: str,
        artifacts_dir: str,
        runtime: float,
    ) -> ExecutionResult:
        """Construct an ExecutionResult for a failure scenario."""
        error_messages: dict[str, str] = {
            "tool_crash": (
                "OpenROAD crashed with SIGSEGV at detailed_route.cpp:1234\n"
                "Backtrace:\n"
                "  #0 0x7f8a in odb::dbNet::getSigType()\n"
                "  #1 0x7f8b in grt::GlobalRouter::findRoutes()\n"
                "Aborted (core dumped)"
            ),
            "timeout": (
                f"Stage execution exceeded timeout. "
                f"Process killed after {runtime:.1f}s."
            ),
            "oom_killed": (
                "Process killed by OOM killer.\n"
                "Memory usage peaked at 32.1 GB (limit: 16 GB).\n"
                "dmesg: Out of memory: Killed process 12345 (openroad)"
            ),
        }

        exit_codes: dict[str, int] = {
            "tool_crash": 139,  # SIGSEGV
            "timeout": 124,    # timeout exit code
            "oom_killed": 137,  # SIGKILL
        }

        stderr_tail = error_messages.get(failure_mode, f"Unknown failure: {failure_mode}")
        exit_code = exit_codes.get(failure_mode, 1)

        # Write a crash log in the attempt dir
        crash_log_path = os.path.join(attempt_dir, "crash.log")
        with open(crash_log_path, "w") as f:
            f.write(stderr_tail)

        return ExecutionResult(
            execution_status=failure_mode,  # type: ignore[arg-type]
            exit_code=exit_code,
            runtime_seconds=runtime,
            attempt_dir=attempt_dir,
            workspace_dir=workspace_dir,
            artifacts_dir=artifacts_dir,
            state_out_path=None,
            stderr_tail=stderr_tail,
            error_summary=f"Stage failed with {failure_mode}",
        )
