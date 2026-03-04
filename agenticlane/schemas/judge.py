"""Judge schemas for AgenticLane.

Defines BlockingIssue, JudgeVote, and JudgeAggregate models
for the judge ensemble evaluation system.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class BlockingIssue(BaseModel):
    """A single blocking issue identified by a judge.

    Represents a specific metric or design quality concern
    that prevents the attempt from passing.
    """

    metric_key: str = Field(
        description="The metric key that is blocking (e.g., setup_wns_ns.tt)",
    )
    description: str = Field(
        description="Human-readable description of the issue",
    )
    severity: str = Field(
        default="high",
        description="Issue severity (high, medium, low)",
    )


class JudgeVote(BaseModel):
    """A single judge's vote on an attempt.

    Each judge in the ensemble independently votes PASS or FAIL
    with a confidence score and optional blocking issues.
    """

    judge_id: str = Field(
        default="judge_0",
        description="Unique identifier for this judge instance",
    )
    model: str = Field(
        default="unknown",
        description="LLM model used by this judge",
    )
    vote: Literal["PASS", "FAIL"] = Field(
        description="Judge's verdict"
    )
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Confidence in the vote (0.0 to 1.0)",
    )
    blocking_issues: list[BlockingIssue] = Field(
        default_factory=list,
        description="List of blocking issues (expected non-empty for FAIL votes)",
    )
    rationale: str = Field(
        default="",
        description="Judge's reasoning for the vote",
    )


class JudgeAggregate(BaseModel):
    """Aggregated result from the judge ensemble.

    Combines individual judge votes into a single PASS/FAIL decision
    via majority voting (or tie-breaking rules).
    """

    votes: list[JudgeVote] = Field(
        default_factory=list,
        description="Individual judge votes",
    )
    result: Literal["PASS", "FAIL"] = Field(
        description="Aggregated verdict (majority vote)",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Aggregated confidence score",
    )
    blocking_issues: list[BlockingIssue] = Field(
        default_factory=list,
        description="Union of all blocking issues from FAIL votes",
    )
