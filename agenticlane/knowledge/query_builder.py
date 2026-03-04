"""Build context-aware retrieval queries from stage metrics and evidence."""

from __future__ import annotations

from agenticlane.schemas.evidence import EvidencePack
from agenticlane.schemas.metrics import MetricsPayload


def build_query(
    stage: str,
    metrics: MetricsPayload | None = None,
    evidence: EvidencePack | None = None,
) -> str:
    """Build a retrieval query from the current stage context.

    Combines stage name with specific issues found in metrics/evidence
    to produce a focused query that retrieves the most relevant knowledge.
    """
    parts: list[str] = [f"{stage} stage optimization"]

    if metrics is not None:
        parts.extend(_query_parts_from_metrics(stage, metrics))

    if evidence is not None:
        parts.extend(_query_parts_from_evidence(evidence))

    return " ".join(parts)


def _query_parts_from_metrics(
    stage: str, metrics: MetricsPayload
) -> list[str]:
    """Extract query keywords from metrics issues."""
    parts: list[str] = []

    if metrics.timing and metrics.timing.setup_wns_ns:
        for _corner, wns in metrics.timing.setup_wns_ns.items():
            if isinstance(wns, (int, float)) and wns < 0:
                parts.append("setup timing violation negative slack")
                break

    if (
        metrics.route
        and metrics.route.congestion_overflow_pct is not None
        and metrics.route.congestion_overflow_pct > 0
    ):
        parts.append("routing congestion overflow")

    if metrics.signoff:
        if metrics.signoff.drc_count is not None and metrics.signoff.drc_count > 0:
            parts.append("DRC violations design rule check")
        if metrics.signoff.lvs_pass is not None and not metrics.signoff.lvs_pass:
            parts.append("LVS layout versus schematic mismatch")

    if metrics.physical and metrics.physical.utilization_pct is not None:
        util = metrics.physical.utilization_pct
        if util > 85:
            parts.append("high utilization density congestion")
        elif util < 30:
            parts.append("low utilization area optimization")

    return parts


def _query_parts_from_evidence(evidence: EvidencePack) -> list[str]:
    """Extract query keywords from evidence issues."""
    parts: list[str] = []

    if evidence.crash_info:
        crash = evidence.crash_info.crash_type or ""
        if "oom" in crash.lower() or "memory" in crash.lower():
            parts.append("out of memory resource optimization")
        elif "timeout" in crash.lower():
            parts.append("timeout runtime optimization")
        else:
            parts.append(f"crash error {crash}")

    for err in evidence.errors[:3]:
        msg = err.message[:60] if err.message else ""
        if msg:
            parts.append(msg)

    for hs in evidence.spatial_hotspots[:2]:
        parts.append(f"{hs.type} hotspot")

    return parts
