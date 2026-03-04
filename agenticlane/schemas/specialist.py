"""Specialist advice schemas for AgenticLane.

Defines the SpecialistAdvice model returned by specialist agents when
plateau detection triggers domain-specific analysis.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class KnobRecommendation(BaseModel):
    """A single recommended knob change from a specialist."""

    knob_name: str = Field(description="LibreLane config variable name")
    current_value: Optional[Any] = Field(
        default=None,
        description="Current value (if known)",
    )
    recommended_value: Any = Field(
        description="Recommended new value",
    )
    rationale: str = Field(
        default="",
        description="Why this change is recommended",
    )


class SpecialistAdvice(BaseModel):
    """Structured advice from a specialist agent.

    Returned when plateau detection triggers a domain-specific analysis
    of timing, routability, or DRC issues.
    """

    specialist_type: Literal["timing", "routability", "drc"] = Field(
        description="Which specialist produced this advice",
    )
    focus_areas: list[str] = Field(
        default_factory=list,
        description=(
            "Ordered list of areas the specialist recommends focusing on. "
            "E.g. ['setup_timing_corner_nom', 'hold_timing', 'clock_tree']"
        ),
    )
    recommended_knobs: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Recommended knob changes as {knob_name: recommended_value}. "
            "These are suggestions for the worker agent's next patch."
        ),
    )
    strategy_summary: str = Field(
        default="",
        description=(
            "A concise natural-language summary of the recommended strategy "
            "for breaking out of the plateau."
        ),
    )
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Specialist's confidence in its recommendations (0.0-1.0)",
    )
    detailed_recommendations: list[KnobRecommendation] = Field(
        default_factory=list,
        description="Detailed per-knob recommendations with rationale",
    )
    stage: str = Field(
        default="",
        description="Stage where the plateau was detected",
    )
    plateau_info: Optional[dict[str, Any]] = Field(
        default=None,
        description="Plateau diagnostics from the detector (window, mean, range)",
    )
