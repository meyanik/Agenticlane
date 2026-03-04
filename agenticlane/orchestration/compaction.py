"""History compaction for AgenticLane.

Condenses prior attempt history into compact Lessons Learned tables
for LLM prompt inclusion.  Uses a sliding window to show recent
attempts in detail while summarizing older ones as a trend line.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class AttemptRecord(BaseModel):
    """Record of a single physical attempt for history tracking."""

    attempt_num: int = Field(ge=1)
    patch_summary: str = ""
    config_changes: dict[str, str] = Field(default_factory=dict)
    composite_score: Optional[float] = None
    judge_decision: str = "UNKNOWN"  # PASS / FAIL / UNKNOWN
    was_rollback: bool = False
    metrics_delta: dict[str, float] = Field(default_factory=dict)


class LessonAttempt(BaseModel):
    """One row in the lessons-learned table."""

    attempt_num: int
    patch_summary: str
    metrics_delta: dict[str, float] = Field(default_factory=dict)
    score_composite: Optional[float] = None
    judge_decision: str = "UNKNOWN"
    was_rollback: bool = False


class LessonsLearned(BaseModel):
    """Compacted attempt history for prompt inclusion."""

    schema_version: int = 1
    stage: str
    branch_id: str
    attempts_total: int
    window_size: int
    full_attempts: list[LessonAttempt] = Field(default_factory=list)
    older_summary: Optional[str] = None
    trend: str = "none"  # improving / flat / declining / none
    best_composite_score: float = 0.0
    best_attempt_num: int = 0


class HistoryCompactor:
    """Compact attempt history into LessonsLearned for prompts.

    Rules:
    1. Show last `window_size` attempts in full detail
    2. Summarize older attempts as trend text
    3. Compute trend from sliding window of composite scores
    4. Track best composite score and which attempt achieved it
    """

    def __init__(self, window_size: int = 5) -> None:
        self.window_size = window_size

    def compact(
        self,
        stage_name: str,
        branch_id: str,
        all_attempts: list[AttemptRecord],
    ) -> LessonsLearned:
        """Produce compacted history from attempt records."""
        if not all_attempts:
            return LessonsLearned(
                stage=stage_name,
                branch_id=branch_id,
                attempts_total=0,
                window_size=self.window_size,
                trend="none",
            )

        # Determine trend
        scores = [a.composite_score for a in all_attempts if a.composite_score is not None]
        trend = self._compute_trend(scores)

        # Best attempt
        best_idx = 0
        best_score = 0.0
        for i, att in enumerate(all_attempts):
            s = att.composite_score if att.composite_score is not None else -float("inf")
            if s > best_score or i == 0:
                best_score = s if att.composite_score is not None else 0.0
                best_idx = i

        # Full attempts (last N)
        window = all_attempts[-self.window_size :]
        full_attempts = [
            LessonAttempt(
                attempt_num=att.attempt_num,
                patch_summary=att.patch_summary,
                metrics_delta=att.metrics_delta,
                score_composite=att.composite_score,
                judge_decision=att.judge_decision,
                was_rollback=att.was_rollback,
            )
            for att in window
        ]

        # Older summary
        older_summary = None
        if len(all_attempts) > self.window_size:
            older = all_attempts[: -self.window_size]
            older_summary = self._summarize_older(older)

        return LessonsLearned(
            stage=stage_name,
            branch_id=branch_id,
            attempts_total=len(all_attempts),
            window_size=self.window_size,
            full_attempts=full_attempts,
            older_summary=older_summary,
            trend=trend,
            best_composite_score=best_score,
            best_attempt_num=all_attempts[best_idx].attempt_num,
        )

    def render_markdown(self, lessons: LessonsLearned) -> str:
        """Render LessonsLearned as a Markdown table for prompt injection."""
        lines: list[str] = []
        lines.append(f"# {lessons.stage} - Attempt History")
        lines.append("")
        lines.append(
            f"**Trend:** {lessons.trend} | "
            f"**Best Score:** {lessons.best_composite_score:.4f} "
            f"(Attempt {lessons.best_attempt_num}) | "
            f"**Total Attempts:** {lessons.attempts_total}"
        )
        lines.append("")

        if not lessons.full_attempts:
            lines.append("_No attempts recorded._")
            return "\n".join(lines)

        # Table header
        lines.append("| # | Patch Summary | Metrics \u0394 | Score | Judge | Notes |")
        lines.append("|---|---|---|---|---|---|")

        for att in lessons.full_attempts:
            delta_parts = [f"{k}={v:+.3f}" for k, v in list(att.metrics_delta.items())[:3]]
            delta_str = ", ".join(delta_parts) if delta_parts else "-"
            score_str = f"{att.score_composite:.4f}" if att.score_composite is not None else "-"
            notes = "rollback" if att.was_rollback else ""
            summary = att.patch_summary[:50] if att.patch_summary else "-"
            lines.append(
                f"| {att.attempt_num} | {summary} | {delta_str} | "
                f"{score_str} | {att.judge_decision} | {notes} |"
            )

        if lessons.older_summary:
            lines.append("")
            lines.append(f"**Older attempts:** {lessons.older_summary}")

        return "\n".join(lines)

    @staticmethod
    def _compute_trend(scores: list[float]) -> str:
        """Determine trend from score sequence."""
        if len(scores) < 2:
            return "none"

        recent = scores[-3:] if len(scores) >= 3 else scores

        delta = recent[-1] - recent[0]
        if delta > 0.01:
            return "improving"
        elif delta < -0.01:
            return "declining"
        return "flat"

    @staticmethod
    def _summarize_older(older: list[AttemptRecord]) -> str:
        """Summarize attempts before the window as a short text."""
        scores = [a.composite_score for a in older if a.composite_score is not None]
        pass_count = sum(1 for a in older if a.judge_decision == "PASS")
        fail_count = sum(1 for a in older if a.judge_decision == "FAIL")

        parts: list[str] = [f"{len(older)} earlier attempt(s)"]
        if scores:
            parts.append(f"scores ranged {min(scores):.3f}\u2013{max(scores):.3f}")
        if pass_count or fail_count:
            parts.append(f"{pass_count} passed, {fail_count} failed")

        return "; ".join(parts) + "."
