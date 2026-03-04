"""Stage graph and stage specification registry for AgenticLane.

Defines the 10 ASIC PnR stages, their LibreLane step mappings,
required outputs, rollback edges, relevant metrics, and typical failures.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class StageSpec:
    """Specification for a single ASIC PnR stage.

    Attributes:
        name: Canonical stage name (e.g. "SYNTH", "FLOORPLAN").
        librelane_steps: Ordered list of LibreLane step IDs in this stage.
        first_step: The ``--from`` step ID for LibreLane partial execution.
        last_step: The ``--to`` step ID for LibreLane partial execution.
        required_outputs: DesignFormat names that must be present after the stage.
        rollback_targets: Stages this stage can roll back to on failure.
        relevant_metrics: Metric keys extracted by the distillation layer.
        typical_failures: Common failure modes for this stage.
    """

    name: str
    librelane_steps: list[str]
    first_step: str
    last_step: str
    required_outputs: list[str]
    rollback_targets: list[str] = field(default_factory=list)
    relevant_metrics: list[str] = field(default_factory=list)
    typical_failures: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Stage definitions -- derived from docs/integration/LIBRELANE_INTEGRATION.md
# ---------------------------------------------------------------------------

STAGE_GRAPH: dict[str, StageSpec] = {
    "SYNTH": StageSpec(
        name="SYNTH",
        librelane_steps=[
            "Verilator.Lint",
            "Checker.LintTimingConstructs",
            "Checker.LintErrors",
            "Checker.LintWarnings",
            "Yosys.JsonHeader",
            "Yosys.Synthesis",
            "Checker.YosysUnmappedCells",
            "Checker.YosysSynthChecks",
            "Checker.NetlistAssignStatements",
        ],
        first_step="Verilator.Lint",
        last_step="Checker.NetlistAssignStatements",
        required_outputs=["NETLIST"],
        rollback_targets=[],
        relevant_metrics=[
            "cell_count",
            "area_um2",
            "unmapped_cells",
        ],
        typical_failures=[
            "syntax_error",
            "unmapped_cells",
            "lint_errors",
            "assign_statement_violations",
        ],
    ),
    "FLOORPLAN": StageSpec(
        name="FLOORPLAN",
        librelane_steps=[
            "OpenROAD.CheckSDCFiles",
            "OpenROAD.CheckMacroInstances",
            "OpenROAD.STAPrePNR",
            "OpenROAD.Floorplan",
            "Odb.CheckMacroAntennaProperties",
            "Odb.SetPowerConnections",
            "Odb.ManualMacroPlacement",
            "OpenROAD.CutRows",
            "OpenROAD.TapEndcapInsertion",
        ],
        first_step="OpenROAD.CheckSDCFiles",
        last_step="OpenROAD.TapEndcapInsertion",
        required_outputs=["ODB", "DEF"],
        rollback_targets=[],
        relevant_metrics=[
            "core_area_um2",
            "utilization_pct",
            "setup_wns_ns",
            "hold_wns_ns",
        ],
        typical_failures=[
            "invalid_sdc",
            "macro_placement_error",
            "utilization_too_high",
            "tap_endcap_failure",
        ],
    ),
    "PDN": StageSpec(
        name="PDN",
        librelane_steps=[
            "Odb.AddPDNObstructions",
            "OpenROAD.GeneratePDN",
            "Odb.RemovePDNObstructions",
            "Odb.AddRoutingObstructions",
        ],
        first_step="Odb.AddPDNObstructions",
        last_step="Odb.AddRoutingObstructions",
        required_outputs=["ODB"],
        rollback_targets=[],
        relevant_metrics=[
            "pdn_wire_length",
            "ir_drop_estimate",
        ],
        typical_failures=[
            "pdn_generation_error",
            "obstruction_conflict",
        ],
    ),
    "PLACE_GLOBAL": StageSpec(
        name="PLACE_GLOBAL",
        librelane_steps=[
            "OpenROAD.GlobalPlacementSkipIO",
            "OpenROAD.IOPlacement",
            "Odb.CustomIOPlacement",
            "Odb.ApplyDEFTemplate",
            "OpenROAD.GlobalPlacement",
            "Odb.WriteVerilogHeader",
            "Checker.PowerGridViolations",
            "OpenROAD.STAMidPNR",
            "OpenROAD.RepairDesignPostGPL",
            "Odb.ManualGlobalPlacement",
        ],
        first_step="OpenROAD.GlobalPlacementSkipIO",
        last_step="Odb.ManualGlobalPlacement",
        required_outputs=["ODB"],
        rollback_targets=[],
        relevant_metrics=[
            "setup_wns_ns",
            "tns_ns",
            "hold_wns_ns",
            "total_wire_length",
            "congestion_overflow_pct",
        ],
        typical_failures=[
            "placement_divergence",
            "power_grid_violations",
            "timing_regression",
        ],
    ),
    "PLACE_DETAILED": StageSpec(
        name="PLACE_DETAILED",
        librelane_steps=[
            "OpenROAD.DetailedPlacement",
        ],
        first_step="OpenROAD.DetailedPlacement",
        last_step="OpenROAD.DetailedPlacement",
        required_outputs=["ODB"],
        rollback_targets=[],
        relevant_metrics=[
            "displacement_um",
            "legalization_violations",
        ],
        typical_failures=[
            "legalization_failure",
            "overlap_violations",
        ],
    ),
    "CTS": StageSpec(
        name="CTS",
        librelane_steps=[
            "OpenROAD.CTS",
            "OpenROAD.STAMidPNR",
            "OpenROAD.ResizerTimingPostCTS",
            "OpenROAD.STAMidPNR",
        ],
        first_step="OpenROAD.CTS",
        last_step="OpenROAD.STAMidPNR",
        required_outputs=["ODB"],
        rollback_targets=["PLACE_DETAILED"],
        relevant_metrics=[
            "clock_skew_ps",
            "setup_wns_ns",
            "hold_wns_ns",
            "tns_ns",
            "clock_wire_length",
        ],
        typical_failures=[
            "clock_tree_convergence",
            "hold_violation_post_cts",
            "setup_degradation",
        ],
    ),
    "ROUTE_GLOBAL": StageSpec(
        name="ROUTE_GLOBAL",
        librelane_steps=[
            "OpenROAD.GlobalRouting",
            "OpenROAD.CheckAntennas",
            "OpenROAD.RepairDesignPostGRT",
            "Odb.DiodesOnPorts",
            "Odb.HeuristicDiodeInsertion",
            "OpenROAD.RepairAntennas",
            "OpenROAD.ResizerTimingPostGRT",
            "OpenROAD.STAMidPNR",
        ],
        first_step="OpenROAD.GlobalRouting",
        last_step="OpenROAD.STAMidPNR",
        required_outputs=["ODB"],
        rollback_targets=[],
        relevant_metrics=[
            "congestion_overflow_pct",
            "antenna_violations",
            "setup_wns_ns",
            "hold_wns_ns",
            "tns_ns",
        ],
        typical_failures=[
            "routing_overflow",
            "antenna_violations",
            "timing_regression_post_grt",
        ],
    ),
    "ROUTE_DETAILED": StageSpec(
        name="ROUTE_DETAILED",
        librelane_steps=[
            "OpenROAD.DetailedRouting",
            "Odb.RemoveRoutingObstructions",
            "OpenROAD.CheckAntennas",
            "Checker.TrDRC",
            "Odb.ReportDisconnectedPins",
            "Checker.DisconnectedPins",
            "Odb.ReportWireLength",
            "Checker.WireLength",
        ],
        first_step="OpenROAD.DetailedRouting",
        last_step="Checker.WireLength",
        required_outputs=["ODB", "DEF"],
        rollback_targets=["ROUTE_GLOBAL", "PLACE_DETAILED", "FLOORPLAN"],
        relevant_metrics=[
            "drc_count",
            "total_wire_length",
            "disconnected_pins",
            "antenna_violations",
        ],
        typical_failures=[
            "drc_violations",
            "short_circuits",
            "open_nets",
            "antenna_violations",
            "wire_length_exceeded",
        ],
    ),
    "FINISH": StageSpec(
        name="FINISH",
        librelane_steps=[
            "OpenROAD.FillInsertion",
            "Odb.CellFrequencyTables",
            "OpenROAD.RCX",
            "OpenROAD.STAPostPNR",
            "OpenROAD.IRDropReport",
        ],
        first_step="OpenROAD.FillInsertion",
        last_step="OpenROAD.IRDropReport",
        required_outputs=["SPEF"],
        rollback_targets=[],
        relevant_metrics=[
            "setup_wns_ns",
            "hold_wns_ns",
            "tns_ns",
            "max_ir_drop",
            "cell_count_by_type",
        ],
        typical_failures=[
            "fill_insertion_error",
            "rcx_extraction_failure",
            "ir_drop_violation",
            "timing_closure_failure",
        ],
    ),
    "SIGNOFF": StageSpec(
        name="SIGNOFF",
        librelane_steps=[
            "Magic.StreamOut",
            "KLayout.StreamOut",
            "Magic.WriteLEF",
            "Odb.CheckDesignAntennaProperties",
            "KLayout.XOR",
            "Checker.XOR",
            "Magic.DRC",
            "KLayout.DRC",
            "Checker.MagicDRC",
            "Checker.KLayoutDRC",
            "Magic.SpiceExtraction",
            "Checker.IllegalOverlap",
            "Netgen.LVS",
            "Checker.LVS",
            "Yosys.EQY",
            "Checker.SetupViolations",
            "Checker.HoldViolations",
            "Checker.MaxSlewViolations",
            "Checker.MaxCapViolations",
            "Misc.ReportManufacturability",
        ],
        first_step="Magic.StreamOut",
        last_step="Misc.ReportManufacturability",
        required_outputs=["GDS"],
        rollback_targets=["ROUTE_DETAILED", "FLOORPLAN"],
        relevant_metrics=[
            "drc_count",
            "lvs_pass",
            "antenna_violations",
            "setup_violations",
            "hold_violations",
            "max_slew_violations",
            "max_cap_violations",
        ],
        typical_failures=[
            "drc_violations",
            "lvs_mismatch",
            "antenna_violations",
            "timing_violations",
            "gds_xor_mismatch",
            "illegal_overlap",
        ],
    ),
}

# ---------------------------------------------------------------------------
# Ordered stage list -- defines the canonical execution order
# ---------------------------------------------------------------------------

STAGE_ORDER: list[str] = [
    "SYNTH",
    "FLOORPLAN",
    "PDN",
    "PLACE_GLOBAL",
    "PLACE_DETAILED",
    "CTS",
    "ROUTE_GLOBAL",
    "ROUTE_DETAILED",
    "FINISH",
    "SIGNOFF",
]

# ---------------------------------------------------------------------------
# Rollback edges -- pre-computed mapping of stage -> rollback targets
# ---------------------------------------------------------------------------

ROLLBACK_EDGES: dict[str, list[str]] = {
    stage_name: spec.rollback_targets
    for stage_name, spec in STAGE_GRAPH.items()
}


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def get_stage(name: str) -> StageSpec:
    """Return the StageSpec for a given stage name.

    Args:
        name: Canonical stage name (e.g. "SYNTH").

    Returns:
        The corresponding StageSpec.

    Raises:
        KeyError: If the stage name is not found.
    """
    try:
        return STAGE_GRAPH[name]
    except KeyError:
        raise KeyError(
            f"Unknown stage '{name}'. Valid stages: {list(STAGE_GRAPH.keys())}"
        ) from None


def get_rollback_targets(stage_name: str) -> list[str]:
    """Return the rollback target stages for a given stage.

    Args:
        stage_name: Canonical stage name.

    Returns:
        List of stage names that this stage can roll back to.
        Empty list if no rollback targets exist.

    Raises:
        KeyError: If the stage name is not found.
    """
    return get_stage(stage_name).rollback_targets


def get_stage_index(stage_name: str) -> int:
    """Return the zero-based index of a stage in STAGE_ORDER.

    Args:
        stage_name: Canonical stage name.

    Returns:
        The index (0 = SYNTH, 9 = SIGNOFF).

    Raises:
        ValueError: If the stage name is not in STAGE_ORDER.
    """
    try:
        return STAGE_ORDER.index(stage_name)
    except ValueError:
        raise ValueError(
            f"Unknown stage '{stage_name}'. Valid stages: {STAGE_ORDER}"
        ) from None
