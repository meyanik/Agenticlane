"""Canonical schemas for AgenticLane.

All Pydantic v2 models for data exchange between AgenticLane components.
Based on Appendix A of the AgenticLane Build Spec v0.6 FINAL.
"""

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
from agenticlane.schemas.execution import ExecutionResult, ExecutionStatus
from agenticlane.schemas.judge import BlockingIssue, JudgeAggregate, JudgeVote
from agenticlane.schemas.knowledge import KnowledgeChunk, KnowledgeContext
from agenticlane.schemas.llm import LLMCallRecord
from agenticlane.schemas.metrics import (
    MetricsPayload,
    PhysicalMetrics,
    PowerMetrics,
    RouteMetrics,
    RuntimeMetrics,
    SignoffMetrics,
    TimingMetrics,
)
from agenticlane.schemas.patch import (
    MacroPlacement,
    Patch,
    PatchRejected,
    SDCEdit,
    TclEdit,
)
from agenticlane.schemas.specialist import (
    KnobRecommendation,
    SpecialistAdvice,
)

__all__ = [
    # execution
    "ExecutionStatus",
    "ExecutionResult",
    # patch
    "MacroPlacement",
    "SDCEdit",
    "TclEdit",
    "Patch",
    "PatchRejected",
    # metrics
    "TimingMetrics",
    "PhysicalMetrics",
    "PowerMetrics",
    "RouteMetrics",
    "SignoffMetrics",
    "RuntimeMetrics",
    "MetricsPayload",
    # evidence
    "ErrorWarning",
    "SpatialHotspot",
    "CrashInfo",
    "EvidencePack",
    # constraints
    "ClockDefinition",
    "ExceptionCounts",
    "DelayCounts",
    "UncertaintyCounts",
    "ConstraintDigest",
    # judge
    "BlockingIssue",
    "JudgeVote",
    "JudgeAggregate",
    # llm
    "LLMCallRecord",
    # knowledge
    "KnowledgeChunk",
    "KnowledgeContext",
    # specialist
    "KnobRecommendation",
    "SpecialistAdvice",
]
