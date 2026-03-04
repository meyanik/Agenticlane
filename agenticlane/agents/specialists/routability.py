"""Routability specialist agent for AgenticLane.

Focuses on congestion, overflow, routing failures, and routability-related
knob recommendations when a plateau is detected in routing-sensitive stages.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from agenticlane.agents.specialists.base import BaseSpecialist
from agenticlane.schemas.evidence import EvidencePack
from agenticlane.schemas.metrics import MetricsPayload

logger = logging.getLogger(__name__)


class RoutabilitySpecialist(BaseSpecialist):
    """Specialist agent for routability analysis and optimization.

    Analyzes congestion overflow, spatial hotspots, routing failures,
    and recommends routability-related knob changes such as placement
    density, global routing adjustments, and layer configuration.
    """

    specialist_type: Literal["routability"] = "routability"

    def _get_domain_context(
        self,
        metrics: MetricsPayload,
        evidence: EvidencePack,
    ) -> dict[str, Any]:
        """Extract routability-specific context for the prompt template."""
        ctx: dict[str, Any] = {}

        # Routing metrics
        if metrics.route:
            ctx["congestion_overflow_pct"] = metrics.route.congestion_overflow_pct
            ctx["has_congestion"] = (
                metrics.route.congestion_overflow_pct is not None
                and metrics.route.congestion_overflow_pct > 0
            )
        else:
            ctx["congestion_overflow_pct"] = None
            ctx["has_congestion"] = False

        # Physical context that affects routability
        if metrics.physical:
            ctx["utilization_pct"] = metrics.physical.utilization_pct
            ctx["core_area_um2"] = metrics.physical.core_area_um2
        else:
            ctx["utilization_pct"] = None
            ctx["core_area_um2"] = None

        # Congestion hotspots from evidence
        congestion_hotspots = [
            hs for hs in evidence.spatial_hotspots
            if hs.type == "congestion"
        ]
        ctx["congestion_hotspots"] = [
            {
                "grid_bin": hs.grid_bin,
                "severity": hs.severity,
                "region_label": hs.region_label,
                "nearby_macros": hs.nearby_macros,
            }
            for hs in congestion_hotspots[:5]
        ]
        ctx["hotspot_count"] = len(congestion_hotspots)

        # Routing-related errors and warnings
        route_keywords = {
            "routing", "route", "congestion", "overflow", "antenna",
            "via", "wire", "metal", "layer", "net", "global_route",
            "detailed_route", "drt", "grt",
        }
        route_errors = [
            err for err in evidence.errors
            if any(kw in err.message.lower() for kw in route_keywords)
        ]
        route_warnings = [
            warn for warn in evidence.warnings
            if any(kw in warn.message.lower() for kw in route_keywords)
        ]
        ctx["route_errors"] = [
            {"source": e.source, "message": e.message} for e in route_errors[:5]
        ]
        ctx["route_warnings"] = [
            {"source": w.source, "message": w.message} for w in route_warnings[:5]
        ]

        # Relevant knob suggestions for routability fixes
        ctx["routability_knobs"] = [
            "PL_TARGET_DENSITY",
            "FP_CORE_UTIL",
            "GRT_ADJUSTMENT",
            "GRT_OVERFLOW_ITERS",
            "GRT_ANT_ITERS",
            "GRT_MACRO_EXTENSION",
            "DRT_OPT_ITERS",
            "GRT_LAYER_ADJUSTMENTS",
            "PL_ROUTABILITY_DRIVEN",
        ]

        logger.debug(
            "RoutabilitySpecialist domain context built "
            "congestion_overflow_pct=%s has_congestion=%s hotspots=%d "
            "route_errors=%d route_warnings=%d",
            ctx["congestion_overflow_pct"],
            ctx["has_congestion"],
            ctx["hotspot_count"],
            len(ctx["route_errors"]),
            len(ctx["route_warnings"]),
            extra={
                "agent": "specialist",
                "specialist_type": "routability",
                "event": "domain_context_built",
                "congestion_overflow_pct": ctx["congestion_overflow_pct"],
                "has_congestion": ctx["has_congestion"],
                "hotspot_count": ctx["hotspot_count"],
                "utilization_pct": ctx["utilization_pct"],
                "route_error_count": len(ctx["route_errors"]),
                "route_warning_count": len(ctx["route_warnings"]),
            },
        )

        return ctx
