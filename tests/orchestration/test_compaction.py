"""P3.7 History Compaction tests."""
from __future__ import annotations

import pytest

from agenticlane.orchestration.compaction import (
    AttemptRecord,
    HistoryCompactor,
    LessonsLearned,
)


def _make_attempt(
    num: int,
    score: float = 0.0,
    decision: str = "FAIL",
    summary: str = "",
    rollback: bool = False,
    deltas: dict[str, float] | None = None,
) -> AttemptRecord:
    return AttemptRecord(
        attempt_num=num,
        patch_summary=summary or f"Attempt {num} changes",
        composite_score=score,
        judge_decision=decision,
        was_rollback=rollback,
        metrics_delta=deltas or {},
    )


class TestHistoryCompactor:
    @pytest.fixture()
    def compactor(self) -> HistoryCompactor:
        return HistoryCompactor(window_size=3)

    def test_empty_history(self, compactor: HistoryCompactor) -> None:
        lessons = compactor.compact("PLACE_GLOBAL", "B0", [])
        assert lessons.attempts_total == 0
        assert lessons.trend == "none"
        assert lessons.full_attempts == []

    def test_single_attempt(self, compactor: HistoryCompactor) -> None:
        attempts = [_make_attempt(1, score=0.1, decision="FAIL")]
        lessons = compactor.compact("SYNTH", "B0", attempts)
        assert lessons.attempts_total == 1
        assert len(lessons.full_attempts) == 1
        assert lessons.full_attempts[0].attempt_num == 1
        assert lessons.best_attempt_num == 1
        assert lessons.older_summary is None

    def test_sliding_window_last_n(self, compactor: HistoryCompactor) -> None:
        attempts = [_make_attempt(i, score=i * 0.1) for i in range(1, 8)]
        lessons = compactor.compact("PLACE_GLOBAL", "B0", attempts)
        # Window=3, so last 3 attempts shown in detail
        assert len(lessons.full_attempts) == 3
        assert lessons.full_attempts[0].attempt_num == 5
        assert lessons.full_attempts[1].attempt_num == 6
        assert lessons.full_attempts[2].attempt_num == 7

    def test_older_summary_present(self, compactor: HistoryCompactor) -> None:
        attempts = [_make_attempt(i, score=i * 0.1) for i in range(1, 8)]
        lessons = compactor.compact("PLACE_GLOBAL", "B0", attempts)
        assert lessons.older_summary is not None
        assert "4 earlier attempt" in lessons.older_summary

    def test_improving_trend(self, compactor: HistoryCompactor) -> None:
        attempts = [_make_attempt(i, score=i * 0.1) for i in range(1, 5)]
        lessons = compactor.compact("SYNTH", "B0", attempts)
        assert lessons.trend == "improving"

    def test_declining_trend(self, compactor: HistoryCompactor) -> None:
        attempts = [_make_attempt(i, score=(10 - i) * 0.1) for i in range(1, 5)]
        lessons = compactor.compact("SYNTH", "B0", attempts)
        assert lessons.trend == "declining"

    def test_flat_trend(self, compactor: HistoryCompactor) -> None:
        attempts = [_make_attempt(i, score=0.5) for i in range(1, 5)]
        lessons = compactor.compact("SYNTH", "B0", attempts)
        assert lessons.trend == "flat"

    def test_best_composite_score_tracked(self, compactor: HistoryCompactor) -> None:
        attempts = [
            _make_attempt(1, score=0.1),
            _make_attempt(2, score=0.5),
            _make_attempt(3, score=0.3),
        ]
        lessons = compactor.compact("CTS", "B0", attempts)
        assert lessons.best_composite_score == 0.5
        assert lessons.best_attempt_num == 2

    def test_rollback_flagged(self, compactor: HistoryCompactor) -> None:
        attempts = [
            _make_attempt(1, score=0.2),
            _make_attempt(2, score=0.1, rollback=True),
        ]
        lessons = compactor.compact("ROUTE_DETAILED", "B0", attempts)
        assert lessons.full_attempts[1].was_rollback is True


class TestMarkdownRendering:
    @pytest.fixture()
    def compactor(self) -> HistoryCompactor:
        return HistoryCompactor(window_size=5)

    def test_markdown_has_table_header(self, compactor: HistoryCompactor) -> None:
        attempts = [_make_attempt(1, score=0.1, deltas={"wns": 0.05})]
        lessons = compactor.compact("PLACE_GLOBAL", "B0", attempts)
        md = compactor.render_markdown(lessons)
        assert "| # | Patch Summary" in md
        assert "|---|" in md

    def test_markdown_empty_history(self, compactor: HistoryCompactor) -> None:
        lessons = compactor.compact("SYNTH", "B0", [])
        md = compactor.render_markdown(lessons)
        assert "No attempts recorded" in md

    def test_markdown_includes_scores(self, compactor: HistoryCompactor) -> None:
        attempts = [_make_attempt(1, score=0.1234, decision="PASS")]
        lessons = compactor.compact("CTS", "B0", attempts)
        md = compactor.render_markdown(lessons)
        assert "0.1234" in md
        assert "PASS" in md

    def test_markdown_includes_older_summary(self, compactor: HistoryCompactor) -> None:
        compactor.window_size = 2
        attempts = [_make_attempt(i, score=i * 0.1) for i in range(1, 6)]
        lessons = compactor.compact("SYNTH", "B0", attempts)
        md = compactor.render_markdown(lessons)
        assert "Older attempts:" in md

    def test_golden_lessons_learned(self, compactor: HistoryCompactor) -> None:
        """Known 5-attempt history produces expected markdown structure."""
        compactor.window_size = 5
        attempts = [
            _make_attempt(
                1, score=0.0, decision="FAIL", summary="Initial baseline", deltas={}
            ),
            _make_attempt(
                2,
                score=0.15,
                decision="FAIL",
                summary="Increase density",
                deltas={"wns": 0.05, "area": -0.02},
            ),
            _make_attempt(
                3,
                score=0.25,
                decision="FAIL",
                summary="Add CTS buffer",
                deltas={"wns": 0.10},
            ),
            _make_attempt(
                4,
                score=0.40,
                decision="PASS",
                summary="Route opt",
                deltas={"wns": 0.08, "cong": -0.15},
            ),
            _make_attempt(
                5,
                score=0.35,
                decision="FAIL",
                summary="Area recovery",
                deltas={"area": 0.05},
            ),
        ]
        lessons = compactor.compact("PLACE_GLOBAL", "B0", attempts)
        md = compactor.render_markdown(lessons)

        # Structural checks
        assert "PLACE_GLOBAL" in md
        assert "improving" in md  # 0.0 -> 0.25 -> 0.35 (last 3)
        assert "**Best Score:** 0.4000" in md
        assert "Attempt 4" in md
        assert "| 1 |" in md
        assert "| 5 |" in md
        assert "PASS" in md
        assert "FAIL" in md


class TestLessonsLearnedSchema:
    def test_json_roundtrip(self) -> None:
        lessons = LessonsLearned(
            stage="SYNTH",
            branch_id="B0",
            attempts_total=3,
            window_size=5,
            trend="improving",
            best_composite_score=0.5,
            best_attempt_num=2,
        )
        json_str = lessons.model_dump_json()
        parsed = LessonsLearned.model_validate_json(json_str)
        assert parsed.stage == "SYNTH"
        assert parsed.best_composite_score == 0.5

    def test_schema_version(self) -> None:
        lessons = LessonsLearned(
            stage="X", branch_id="B0", attempts_total=0, window_size=5
        )
        assert lessons.schema_version == 1
