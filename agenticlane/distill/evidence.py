"""EvidencePack assembly pipeline.

Runs all registered extractors against an attempt directory and
assembles the results into canonical ``MetricsPayload`` and
``EvidencePack`` objects.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from agenticlane.config.models import DistillConfig
from agenticlane.distill.registry import get_all_extractors
from agenticlane.schemas.constraints import (
    ClockDefinition,
    ConstraintDigest,
    DelayCounts,
    ExceptionCounts,
    UncertaintyCounts,
)
from agenticlane.schemas.evidence import (
    CrashInfo,
    ErrorWarning,
    EvidencePack,
    SpatialHotspot,
)
from agenticlane.schemas.execution import ExecutionResult
from agenticlane.schemas.metrics import (
    MetricsPayload,
    PhysicalMetrics,
    PowerMetrics,
    RouteMetrics,
    RuntimeMetrics,
    SignoffMetrics,
    SynthesisMetrics,
    TimingMetrics,
)

logger = logging.getLogger(__name__)


async def assemble_evidence(
    attempt_dir: Path,
    stage_name: str,
    attempt_num: int,
    execution_result: ExecutionResult,
    config: DistillConfig,
    *,
    run_id: str = "",
    branch_id: str = "",
) -> tuple[MetricsPayload, EvidencePack]:
    """Run all extractors and assemble MetricsPayload + EvidencePack.

    Parameters
    ----------
    attempt_dir:
        Path to the attempt directory containing artifacts/ etc.
    stage_name:
        Name of the stage that was executed.
    attempt_num:
        1-indexed attempt number.
    execution_result:
        The ``ExecutionResult`` from the execution adapter.
    config:
        Distillation configuration (crash handling, spatial, etc.).
    run_id:
        Run identifier for the MetricsPayload.
    branch_id:
        Branch identifier for the MetricsPayload.

    Returns
    -------
    tuple[MetricsPayload, EvidencePack]
        The assembled metrics payload and evidence pack.
    """
    # Baseline runs use attempt_num=0 but MetricsPayload requires >= 1
    safe_attempt = max(attempt_num, 1)

    # Collect all extractor outputs
    raw: dict[str, dict] = {}
    extractors = get_all_extractors()
    missing_reports: list[str] = []

    for name, extractor in extractors.items():
        try:
            raw[name] = extractor.extract(attempt_dir, stage_name)
        except Exception:
            logger.exception("Extractor %r failed (non-fatal)", name)
            raw[name] = {}
            missing_reports.append(f"extractor:{name}")

    # Build MetricsPayload
    missing_metrics: list[str] = []
    metrics = _build_metrics(
        raw=raw,
        stage_name=stage_name,
        attempt_num=safe_attempt,
        execution_result=execution_result,
        missing_metrics=missing_metrics,
        run_id=run_id,
        branch_id=branch_id,
    )

    # Override runtime from execution result if extractor didn't find it
    if metrics.runtime is None or metrics.runtime.stage_seconds is None:
        metrics.runtime = RuntimeMetrics(
            stage_seconds=execution_result.runtime_seconds
        )

    # Build EvidencePack
    evidence = _build_evidence(
        raw=raw,
        stage_name=stage_name,
        attempt_num=safe_attempt,
        execution_result=execution_result,
        missing_reports=missing_reports,
        config=config,
    )

    return metrics, evidence


def _build_metrics(
    *,
    raw: dict[str, dict],
    stage_name: str,
    attempt_num: int,
    execution_result: ExecutionResult,
    missing_metrics: list[str],
    run_id: str,
    branch_id: str,
) -> MetricsPayload:
    """Assemble a MetricsPayload from raw extractor outputs."""
    # Timing
    timing_raw = raw.get("timing", {})
    timing: Optional[TimingMetrics] = None
    wns = timing_raw.get("setup_wns_ns")
    if wns:
        timing = TimingMetrics(setup_wns_ns=wns)
    elif wns is not None:
        # Empty dict is valid (no corners found)
        timing = TimingMetrics(setup_wns_ns=wns)
    else:
        missing_metrics.append("timing")

    # Physical
    area_raw = raw.get("area", {})
    physical: Optional[PhysicalMetrics] = None
    if area_raw.get("core_area_um2") is not None or area_raw.get("utilization_pct") is not None:
        physical = PhysicalMetrics(
            core_area_um2=area_raw.get("core_area_um2"),
            utilization_pct=area_raw.get("utilization_pct"),
        )
    else:
        missing_metrics.append("physical")

    # Route
    route_raw = raw.get("route", {})
    route: Optional[RouteMetrics] = None
    if route_raw.get("congestion_overflow_pct") is not None:
        route = RouteMetrics(
            congestion_overflow_pct=route_raw["congestion_overflow_pct"]
        )
    else:
        missing_metrics.append("route")

    # Signoff
    drc_raw = raw.get("drc", {})
    lvs_raw = raw.get("lvs", {})
    signoff: Optional[SignoffMetrics] = None
    if drc_raw.get("drc_count") is not None or lvs_raw.get("lvs_pass") is not None:
        signoff = SignoffMetrics(
            drc_count=drc_raw.get("drc_count"),
            lvs_pass=lvs_raw.get("lvs_pass"),
        )
    else:
        missing_metrics.append("signoff")

    # Runtime
    runtime_raw = raw.get("runtime", {})
    runtime: Optional[RuntimeMetrics] = None
    if runtime_raw.get("stage_seconds") is not None:
        runtime = RuntimeMetrics(stage_seconds=runtime_raw["stage_seconds"])

    # Synthesis
    synth_raw = raw.get("synth", {})
    synthesis: Optional[SynthesisMetrics] = None
    if any(synth_raw.get(k) is not None for k in ("cell_count", "net_count", "area_estimate_um2")):
        synthesis = SynthesisMetrics(
            cell_count=synth_raw.get("cell_count"),
            net_count=synth_raw.get("net_count"),
            area_estimate_um2=synth_raw.get("area_estimate_um2"),
        )

    # Power
    power_raw = raw.get("power", {})
    power: Optional[PowerMetrics] = None
    if any(
        power_raw.get(k) is not None
        for k in (
            "total_power_mw",
            "internal_power_mw",
            "switching_power_mw",
            "leakage_power_mw",
            "leakage_pct",
        )
    ):
        power = PowerMetrics(
            total_power_mw=power_raw.get("total_power_mw"),
            internal_power_mw=power_raw.get("internal_power_mw"),
            switching_power_mw=power_raw.get("switching_power_mw"),
            leakage_power_mw=power_raw.get("leakage_power_mw"),
            leakage_pct=power_raw.get("leakage_pct"),
        )
    else:
        missing_metrics.append("power")

    # Constraints digest path
    constraints_digest_path: Optional[str] = None
    constraints_raw = raw.get("constraints", {})
    cd = constraints_raw.get("constraint_digest")
    if cd and cd.get("clocks"):
        constraints_digest_path = "constraint_digest.json"

    return MetricsPayload(
        run_id=run_id,
        branch_id=branch_id,
        stage=stage_name,
        attempt=attempt_num,
        execution_status=execution_result.execution_status,
        missing_metrics=missing_metrics,
        constraints_digest_path=constraints_digest_path,
        timing=timing,
        physical=physical,
        route=route,
        signoff=signoff,
        runtime=runtime,
        synthesis=synthesis,
        power=power,
    )


def _build_evidence(
    *,
    raw: dict[str, dict],
    stage_name: str,
    attempt_num: int,
    execution_result: ExecutionResult,
    missing_reports: list[str],
    config: DistillConfig,
) -> EvidencePack:
    """Assemble an EvidencePack from raw extractor outputs."""
    # Crash info
    crash_raw = raw.get("crash", {})
    crash_info: Optional[CrashInfo] = None
    ci = crash_raw.get("crash_info")
    if ci is not None:
        crash_info = CrashInfo(
            crash_type=ci["crash_type"],
            stderr_tail=ci.get("stderr_tail"),
            error_signature=ci.get("error_signature"),
        )

    # Spatial hotspots
    spatial_raw = raw.get("spatial", {})
    hotspot_dicts = spatial_raw.get("spatial_hotspots", [])
    spatial_hotspots: list[SpatialHotspot] = []
    for h in hotspot_dicts:
        try:
            spatial_hotspots.append(
                SpatialHotspot(
                    type=h.get("type", "congestion"),
                    grid_bin=h.get("grid_bin", {"x": 0, "y": 0}),
                    region_label=h.get("region_label", ""),
                    severity=h.get("severity", 0.0),
                    nearby_macros=h.get("nearby_macros", []),
                    x_min_um=h.get("x_min_um"),
                    y_min_um=h.get("y_min_um"),
                    x_max_um=h.get("x_max_um"),
                    y_max_um=h.get("y_max_um"),
                )
            )
        except Exception:
            logger.warning("Failed to parse spatial hotspot: %s", h)

    # Errors/warnings (currently not extracted from reports, but
    # crash errors can be surfaced)
    errors: list[ErrorWarning] = []
    warnings: list[ErrorWarning] = []

    if execution_result.execution_status != "success" and execution_result.error_summary:
        errors.append(
            ErrorWarning(
                source="execution",
                severity="error",
                message=execution_result.error_summary,
            )
        )

    # Constraint digest as bounded snippet
    bounded_snippets: list[dict[str, str]] = []
    constraints_raw = raw.get("constraints", {})
    cd = constraints_raw.get("constraint_digest")
    if cd:
        clocks = cd.get("clocks", [])
        if clocks:
            clock_lines = "; ".join(
                f"{c.get('name', '?')}={c.get('period_ns', '?')}ns"
                for c in clocks
            )
            bounded_snippets.append(
                {"source": "constraints", "content": f"Clocks: {clock_lines}"}
            )

    return EvidencePack(
        stage=stage_name,
        attempt=attempt_num,
        execution_status=execution_result.execution_status,
        errors=errors,
        warnings=warnings,
        spatial_hotspots=spatial_hotspots,
        crash_info=crash_info,
        missing_reports=missing_reports,
        stderr_tail=execution_result.stderr_tail,
        bounded_snippets=bounded_snippets,
    )


def build_constraint_digest(raw_digest: dict) -> ConstraintDigest:
    """Convert a raw constraint digest dict into a ConstraintDigest model.

    Parameters
    ----------
    raw_digest:
        The ``constraint_digest`` dict from the ConstraintExtractor.

    Returns
    -------
    ConstraintDigest
    """
    clocks_raw = raw_digest.get("clocks", [])
    clocks = [
        ClockDefinition(
            name=c.get("name", "unknown"),
            period_ns=c.get("period_ns", 1.0),
            targets=c.get("targets", []),
        )
        for c in clocks_raw
    ]

    exc_raw = raw_digest.get("exceptions", {})
    exceptions = ExceptionCounts(
        false_path_count=exc_raw.get("false_path_count", 0),
        multicycle_path_count=exc_raw.get("multicycle_path_count", 0),
        disable_timing_count=exc_raw.get("disable_timing_count", 0),
    )

    delays_raw = raw_digest.get("delays", {})
    delays = DelayCounts(
        set_max_delay_count=delays_raw.get("set_max_delay_count", 0),
        set_min_delay_count=delays_raw.get("set_min_delay_count", 0),
    )

    unc_raw = raw_digest.get("uncertainty", {})
    uncertainty = UncertaintyCounts(
        set_clock_uncertainty_count=unc_raw.get("set_clock_uncertainty_count", 0),
    )

    return ConstraintDigest(
        opaque=raw_digest.get("opaque", False),
        clocks=clocks,
        exceptions=exceptions,
        delays=delays,
        uncertainty=uncertainty,
        notes=raw_digest.get("notes", []),
    )
