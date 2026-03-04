"""Timing specialist agent for AgenticLane.

Focuses on setup/hold timing violations (WNS/TNS), clock tree issues,
and timing-related knob recommendations when a plateau is detected
in timing-sensitive stages.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from agenticlane.agents.specialists.base import BaseSpecialist
from agenticlane.schemas.evidence import EvidencePack
from agenticlane.schemas.metrics import MetricsPayload

logger = logging.getLogger(__name__)


class TimingSpecialist(BaseSpecialist):
    """Specialist agent for timing analysis and optimization.

    Analyzes setup/hold timing violations, WNS/TNS trends across
    attempts, and recommends timing-related knob changes such as
    clock period adjustments, CTS parameters, and placement density.
    """

    specialist_type: Literal["timing"] = "timing"

    def _get_domain_context(
        self,
        metrics: MetricsPayload,
        evidence: EvidencePack,
    ) -> dict[str, Any]:
        """Extract timing-specific context for the prompt template."""
        ctx: dict[str, Any] = {}

        # Timing metrics
        if metrics.timing and metrics.timing.setup_wns_ns:
            ctx["wns_by_corner"] = metrics.timing.setup_wns_ns
            worst_wns = min(
                (v for v in metrics.timing.setup_wns_ns.values() if v is not None),
                default=None,
            )
            ctx["worst_wns"] = worst_wns
            ctx["has_timing_violations"] = worst_wns is not None and worst_wns < 0
        else:
            ctx["wns_by_corner"] = {}
            ctx["worst_wns"] = None
            ctx["has_timing_violations"] = False

        # Physical context that affects timing
        if metrics.physical:
            ctx["utilization_pct"] = metrics.physical.utilization_pct
            ctx["core_area_um2"] = metrics.physical.core_area_um2
        else:
            ctx["utilization_pct"] = None
            ctx["core_area_um2"] = None

        # Timing-related errors and warnings
        timing_keywords = {
            "timing", "slack", "wns", "tns", "setup", "hold",
            "clock", "skew", "period", "cts", "buffer",
        }
        timing_errors = [
            err for err in evidence.errors
            if any(kw in err.message.lower() for kw in timing_keywords)
        ]
        timing_warnings = [
            warn for warn in evidence.warnings
            if any(kw in warn.message.lower() for kw in timing_keywords)
        ]
        ctx["timing_errors"] = [
            {"source": e.source, "message": e.message} for e in timing_errors[:5]
        ]
        ctx["timing_warnings"] = [
            {"source": w.source, "message": w.message} for w in timing_warnings[:5]
        ]

        # Relevant knob suggestions based on common timing fixes
        ctx["timing_knobs"] = [
            "CTS_CLK_BUFFER_LIST",
            "CTS_MAX_CAP",
            "CTS_SINK_CLUSTERING_SIZE",
            "CTS_SINK_CLUSTERING_MAX_DIAMETER",
            "PL_TARGET_DENSITY",
            "PL_RESIZER_SETUP_SLACK_MARGIN",
            "PL_RESIZER_HOLD_SLACK_MARGIN",
            "PL_RESIZER_MAX_WIRE_LENGTH",
            "GRT_RESIZER_SETUP_SLACK_MARGIN",
            "GRT_RESIZER_HOLD_SLACK_MARGIN",
        ]

        logger.debug(
            "TimingSpecialist domain context built "
            "worst_wns=%s has_violations=%s timing_errors=%d timing_warnings=%d",
            ctx["worst_wns"],
            ctx["has_timing_violations"],
            len(ctx["timing_errors"]),
            len(ctx["timing_warnings"]),
            extra={
                "agent": "specialist",
                "specialist_type": "timing",
                "event": "domain_context_built",
                "worst_wns": ctx["worst_wns"],
                "has_timing_violations": ctx["has_timing_violations"],
                "wns_by_corner": ctx["wns_by_corner"],
                "utilization_pct": ctx["utilization_pct"],
                "timing_error_count": len(ctx["timing_errors"]),
                "timing_warning_count": len(ctx["timing_warnings"]),
            },
        )

        return ctx
