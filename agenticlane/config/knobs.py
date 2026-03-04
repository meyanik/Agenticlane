"""Knob registry for AgenticLane.

Defines all tunable design parameters (knobs) that the agentic loop can
modify, along with their types, valid ranges, safety tiers, and constraint
flags.  The registry is the single source of truth for knob metadata used
by ConstraintGuard validation, patch materialization, and the LLM prompt
templates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional


@dataclass(frozen=True)
class KnobSpec:
    """Specification for a single tunable design knob.

    Attributes:
        name: LibreLane configuration variable name (e.g. "FP_CORE_UTIL").
        dtype: Python type (``int``, ``float``, ``str``, ``bool``).
        range_min: Minimum allowed numeric value (inclusive). ``None`` for
            non-numeric or unbounded knobs.
        range_max: Maximum allowed numeric value (inclusive). ``None`` for
            non-numeric or unbounded knobs.
        default: Default value used when no explicit override is provided.
        pdk_overrides: Per-PDK default overrides, e.g.
            ``{"sky130A": {"default": 45}}``.
        safety_tier: Risk classification -- "safe" (agent freely tunes),
            "moderate" (agent warns), "expert" (requires human approval).
        is_constraint: If ``True``, this knob represents a design constraint
            that the agent should not normally change.
        locked_by_default: If ``True``, ConstraintGuard rejects patches
            that modify this knob unless explicitly unlocked.
        cheat_risk: If ``True``, changing this knob can trivially improve
            metrics without real improvement (e.g. relaxing clock period).
        stage_applicability: List of stage names where this knob is relevant.
    """

    name: str
    dtype: type
    range_min: Optional[float] = None
    range_max: Optional[float] = None
    default: Any = None
    pdk_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)
    safety_tier: Literal["safe", "moderate", "expert"] = "safe"
    is_constraint: bool = False
    locked_by_default: bool = False
    cheat_risk: bool = False
    stage_applicability: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# All PnR stage names (for CLOCK_PERIOD applicability)
# ---------------------------------------------------------------------------

_ALL_PNR_STAGES: list[str] = [
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
# Knob registry -- keyed by LibreLane configuration variable name
# ---------------------------------------------------------------------------

KNOB_REGISTRY: dict[str, KnobSpec] = {
    # ── Synthesis knobs ──────────────────────────────────────────────────
    "SYNTH_STRATEGY": KnobSpec(
        name="SYNTH_STRATEGY",
        dtype=str,
        default="AREA",
        safety_tier="safe",
        stage_applicability=["SYNTH"],
    ),
    "SYNTH_MAX_FANOUT": KnobSpec(
        name="SYNTH_MAX_FANOUT",
        dtype=int,
        range_min=5,
        range_max=20,
        default=10,
        safety_tier="safe",
        stage_applicability=["SYNTH"],
    ),
    "SYNTH_BUFFERING": KnobSpec(
        name="SYNTH_BUFFERING",
        dtype=bool,
        default=True,
        safety_tier="safe",
        stage_applicability=["SYNTH"],
    ),
    "SYNTH_SIZING": KnobSpec(
        name="SYNTH_SIZING",
        dtype=bool,
        default=True,
        safety_tier="safe",
        stage_applicability=["SYNTH"],
    ),

    # ── Floorplan knobs ──────────────────────────────────────────────────
    "FP_CORE_UTIL": KnobSpec(
        name="FP_CORE_UTIL",
        dtype=int,
        range_min=20,
        range_max=80,
        default=50,
        pdk_overrides={
            "sky130A": {"default": 45},
        },
        safety_tier="safe",
        stage_applicability=["FLOORPLAN"],
    ),
    "FP_ASPECT_RATIO": KnobSpec(
        name="FP_ASPECT_RATIO",
        dtype=float,
        range_min=0.5,
        range_max=2.0,
        default=1.0,
        safety_tier="safe",
        stage_applicability=["FLOORPLAN"],
    ),
    "FP_SIZING": KnobSpec(
        name="FP_SIZING",
        dtype=str,
        default="relative",
        safety_tier="safe",
        stage_applicability=["FLOORPLAN"],
    ),
    "DIE_AREA": KnobSpec(
        name="DIE_AREA",
        dtype=list,
        default=None,  # None = let LibreLane auto-size via FP_SIZING=relative
        safety_tier="safe",
        stage_applicability=["FLOORPLAN"],
    ),

    # ── Placement knobs ──────────────────────────────────────────────────
    "PL_TARGET_DENSITY_PCT": KnobSpec(
        name="PL_TARGET_DENSITY_PCT",
        dtype=int,
        range_min=20,
        range_max=95,
        default=60,
        safety_tier="safe",
        stage_applicability=["PLACE_GLOBAL", "PLACE_DETAILED"],
    ),
    "PL_ROUTABILITY_DRIVEN": KnobSpec(
        name="PL_ROUTABILITY_DRIVEN",
        dtype=bool,
        default=True,
        safety_tier="safe",
        stage_applicability=["PLACE_GLOBAL", "PLACE_DETAILED"],
    ),

    # ── CTS knobs ────────────────────────────────────────────────────────
    "CTS_CLK_MAX_WIRE_LENGTH": KnobSpec(
        name="CTS_CLK_MAX_WIRE_LENGTH",
        dtype=float,
        range_min=0,
        range_max=1000,
        default=0,
        safety_tier="safe",
        stage_applicability=["CTS"],
    ),
    "CTS_SINK_CLUSTERING_SIZE": KnobSpec(
        name="CTS_SINK_CLUSTERING_SIZE",
        dtype=int,
        range_min=10,
        range_max=50,
        default=25,
        safety_tier="safe",
        stage_applicability=["CTS"],
    ),

    # ── Routing knobs ────────────────────────────────────────────────────
    "GRT_ADJUSTMENT": KnobSpec(
        name="GRT_ADJUSTMENT",
        dtype=float,
        range_min=0.0,
        range_max=1.0,
        default=0.0,
        safety_tier="safe",
        stage_applicability=["ROUTE_GLOBAL"],
    ),
    "GRT_OVERFLOW_ITERS": KnobSpec(
        name="GRT_OVERFLOW_ITERS",
        dtype=int,
        range_min=20,
        range_max=100,
        default=50,
        safety_tier="safe",
        stage_applicability=["ROUTE_GLOBAL"],
    ),
    "DRT_OPT_ITERS": KnobSpec(
        name="DRT_OPT_ITERS",
        dtype=int,
        range_min=10,
        range_max=64,
        default=12,
        safety_tier="safe",
        stage_applicability=["ROUTE_DETAILED"],
    ),

    # ── Constraint knobs (locked by default) ─────────────────────────────
    "CLOCK_PERIOD": KnobSpec(
        name="CLOCK_PERIOD",
        dtype=float,
        range_min=0.1,
        range_max=1000.0,
        default=10.0,
        safety_tier="expert",
        is_constraint=True,
        locked_by_default=True,
        cheat_risk=True,
        stage_applicability=_ALL_PNR_STAGES,
    ),
}


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def get_knob(name: str) -> KnobSpec:
    """Return the KnobSpec for a given knob name.

    Args:
        name: LibreLane configuration variable name.

    Returns:
        The corresponding KnobSpec.

    Raises:
        KeyError: If the knob name is not in the registry.
    """
    try:
        return KNOB_REGISTRY[name]
    except KeyError:
        raise KeyError(
            f"Unknown knob '{name}'. "
            f"Registered knobs: {list(KNOB_REGISTRY.keys())}"
        ) from None


def get_knobs_for_stage(stage_name: str) -> list[KnobSpec]:
    """Return all KnobSpecs applicable to a given stage.

    Args:
        stage_name: Canonical stage name (e.g. "SYNTH").

    Returns:
        List of KnobSpec instances whose ``stage_applicability`` includes
        the given stage.
    """
    return [
        spec
        for spec in KNOB_REGISTRY.values()
        if stage_name in spec.stage_applicability
    ]


def validate_knob_value(
    name: str,
    value: Any,
    pdk: Optional[str] = None,
) -> None:
    """Validate that a knob value is within the allowed range and type.

    Performs type checking and range checking.  For string knobs with a
    known set of valid values (e.g. SYNTH_STRATEGY), validation is limited
    to type checking.

    Args:
        name: Knob name.
        value: Proposed value.
        pdk: Optional PDK name for PDK-specific validation (currently
            affects default lookup but not range enforcement).

    Raises:
        KeyError: If the knob name is not in the registry.
        ValueError: If the value is out of range.
        TypeError: If the value has the wrong type.
    """
    spec = get_knob(name)

    # --- Type check ---
    # Allow int for float knobs (common Python numeric coercion)
    if spec.dtype is list:
        if not isinstance(value, list):
            raise TypeError(
                f"Knob '{name}' expects list, got {type(value).__name__}"
            )
        # DIE_AREA must be a list of 4 numbers
        if name == "DIE_AREA":
            if len(value) != 4:
                raise ValueError(
                    f"Knob '{name}' expects a list of 4 numbers "
                    f"[x_min, y_min, x_max, y_max], got {len(value)} elements"
                )
            for i, v in enumerate(value):
                if not isinstance(v, (int, float)):
                    raise TypeError(
                        f"Knob '{name}' element {i} must be a number, "
                        f"got {type(v).__name__}"
                    )
    elif spec.dtype is float:
        if not isinstance(value, (int, float)):
            raise TypeError(
                f"Knob '{name}' expects {spec.dtype.__name__}, "
                f"got {type(value).__name__}"
            )
    elif spec.dtype is bool:
        # In Python, bool is a subclass of int, so check bool first
        if not isinstance(value, bool):
            raise TypeError(
                f"Knob '{name}' expects bool, got {type(value).__name__}"
            )
    elif not isinstance(value, spec.dtype):
        raise TypeError(
            f"Knob '{name}' expects {spec.dtype.__name__}, "
            f"got {type(value).__name__}"
        )

    # --- Range check (numeric knobs only) ---
    if spec.dtype in (int, float) and not isinstance(value, bool):
        numeric_value = float(value)
        if spec.range_min is not None and numeric_value < spec.range_min:
            raise ValueError(
                f"Knob '{name}' value {value} is below minimum "
                f"{spec.range_min}"
            )
        if spec.range_max is not None and numeric_value > spec.range_max:
            raise ValueError(
                f"Knob '{name}' value {value} is above maximum "
                f"{spec.range_max}"
            )

    # --- String enum validation (known enum knobs) ---
    enum_knobs: dict[str, list[str]] = {
        "SYNTH_STRATEGY": ["AREA", "DELAY"],
        "FP_SIZING": ["absolute", "relative"],
    }
    if name in enum_knobs and isinstance(value, str):
        allowed = enum_knobs[name]
        if value not in allowed:
            raise ValueError(
                f"Knob '{name}' value '{value}' is not one of the "
                f"allowed values: {allowed}"
            )
