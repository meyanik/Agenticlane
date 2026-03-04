"""DRC specialist agent for AgenticLane.

Focuses on DRC violations, spatial DRC hotspots, and DRC-fixing strategies
when a plateau is detected in signoff-sensitive stages.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from agenticlane.agents.specialists.base import BaseSpecialist
from agenticlane.schemas.evidence import EvidencePack
from agenticlane.schemas.metrics import MetricsPayload

logger = logging.getLogger(__name__)


class DRCSpecialist(BaseSpecialist):
    """Specialist agent for DRC analysis and remediation.

    Analyzes DRC violation counts, spatial DRC hotspots, violation
    types, and recommends DRC-fixing strategies such as density
    adjustments, routing layer changes, and placement refinements.
    """

    specialist_type: Literal["drc"] = "drc"

    def _get_domain_context(
        self,
        metrics: MetricsPayload,
        evidence: EvidencePack,
    ) -> dict[str, Any]:
        """Extract DRC-specific context for the prompt template."""
        ctx: dict[str, Any] = {}

        # Signoff metrics
        if metrics.signoff:
            ctx["drc_count"] = metrics.signoff.drc_count
            ctx["lvs_pass"] = metrics.signoff.lvs_pass
            ctx["has_drc_violations"] = (
                metrics.signoff.drc_count is not None
                and metrics.signoff.drc_count > 0
            )
        else:
            ctx["drc_count"] = None
            ctx["lvs_pass"] = None
            ctx["has_drc_violations"] = False

        # Physical context that affects DRC
        if metrics.physical:
            ctx["utilization_pct"] = metrics.physical.utilization_pct
            ctx["core_area_um2"] = metrics.physical.core_area_um2
        else:
            ctx["utilization_pct"] = None
            ctx["core_area_um2"] = None

        # DRC hotspots from evidence
        drc_hotspots = [
            hs for hs in evidence.spatial_hotspots
            if hs.type == "drc"
        ]
        ctx["drc_hotspots"] = [
            {
                "grid_bin": hs.grid_bin,
                "severity": hs.severity,
                "region_label": hs.region_label,
                "nearby_macros": hs.nearby_macros,
            }
            for hs in drc_hotspots[:5]
        ]
        ctx["drc_hotspot_count"] = len(drc_hotspots)

        # DRC-related errors and warnings
        drc_keywords = {
            "drc", "violation", "spacing", "width", "enclosure",
            "overlap", "short", "antenna", "density", "minimum",
            "metal", "via", "fill",
        }
        drc_errors = [
            err for err in evidence.errors
            if any(kw in err.message.lower() for kw in drc_keywords)
        ]
        drc_warnings = [
            warn for warn in evidence.warnings
            if any(kw in warn.message.lower() for kw in drc_keywords)
        ]
        ctx["drc_errors"] = [
            {"source": e.source, "message": e.message} for e in drc_errors[:5]
        ]
        ctx["drc_warnings"] = [
            {"source": w.source, "message": w.message} for w in drc_warnings[:5]
        ]

        # Relevant knob suggestions for DRC fixes
        ctx["drc_knobs"] = [
            "PL_TARGET_DENSITY",
            "FP_CORE_UTIL",
            "GRT_ADJUSTMENT",
            "DRT_OPT_ITERS",
            "FP_PDN_VPITCH",
            "FP_PDN_HPITCH",
            "FP_PDN_VWIDTH",
            "FP_PDN_HWIDTH",
            "CELL_PAD",
            "DIODE_INSERTION_STRATEGY",
        ]

        logger.debug(
            "DRCSpecialist domain context built "
            "drc_count=%s has_violations=%s lvs_pass=%s hotspots=%d "
            "drc_errors=%d drc_warnings=%d",
            ctx["drc_count"],
            ctx["has_drc_violations"],
            ctx["lvs_pass"],
            ctx["drc_hotspot_count"],
            len(ctx["drc_errors"]),
            len(ctx["drc_warnings"]),
            extra={
                "agent": "specialist",
                "specialist_type": "drc",
                "event": "domain_context_built",
                "drc_count": ctx["drc_count"],
                "has_drc_violations": ctx["has_drc_violations"],
                "lvs_pass": ctx["lvs_pass"],
                "drc_hotspot_count": ctx["drc_hotspot_count"],
                "utilization_pct": ctx["utilization_pct"],
                "drc_error_count": len(ctx["drc_errors"]),
                "drc_warning_count": len(ctx["drc_warnings"]),
            },
        )

        return ctx
