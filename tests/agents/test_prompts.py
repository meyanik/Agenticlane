"""P3.6 Prompt Template tests."""
from pathlib import Path

import jinja2
import pytest

TEMPLATE_DIR = Path(__file__).resolve().parent.parent.parent / "agenticlane" / "agents" / "prompts"


class TestPromptTemplates:
    @pytest.fixture
    def env(self) -> jinja2.Environment:
        return jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(TEMPLATE_DIR)),
            undefined=jinja2.StrictUndefined,
        )

    @pytest.fixture
    def base_context(self) -> dict:  # type: ignore[type-arg]
        return {
            "stage": "PLACE_GLOBAL",
            "attempt_number": 1,
            "intent_summary": "timing: 70%, area: 30%",
            "allowed_knobs": {},
            "knobs_table": "No knobs.",
            "locked_constraints": ["CLOCK_PERIOD"],
            "metrics_summary": "Setup WNS (tt): -0.5 ns",
            "evidence_summary": "No issues found.",
            "constraint_digest": None,
            "lessons_learned": "",
            "last_rejection_feedback": None,
            "patch_schema": {},
        }

    def test_worker_base_renders(
        self, env: jinja2.Environment, base_context: dict  # type: ignore[type-arg]
    ) -> None:
        tpl = env.get_template("worker_base.j2")
        rendered = tpl.render(**base_context)
        assert "PLACE_GLOBAL" in rendered
        assert "CLOCK_PERIOD" in rendered

    def test_synth_template_renders(
        self, env: jinja2.Environment, base_context: dict  # type: ignore[type-arg]
    ) -> None:
        base_context["stage"] = "SYNTH"
        tpl = env.get_template("synth.j2")
        rendered = tpl.render(**base_context)
        assert "SYNTH" in rendered

    def test_placement_template_renders(
        self, env: jinja2.Environment, base_context: dict  # type: ignore[type-arg]
    ) -> None:
        tpl = env.get_template("placement.j2")
        rendered = tpl.render(**base_context)
        assert "placement" in rendered.lower() or "PLACE" in rendered

    def test_floorplan_template_renders(
        self, env: jinja2.Environment, base_context: dict  # type: ignore[type-arg]
    ) -> None:
        base_context["stage"] = "FLOORPLAN"
        tpl = env.get_template("floorplan.j2")
        rendered = tpl.render(**base_context)
        assert "FLOORPLAN" in rendered or "floorplan" in rendered.lower()

    def test_cts_template_renders(
        self, env: jinja2.Environment, base_context: dict  # type: ignore[type-arg]
    ) -> None:
        base_context["stage"] = "CTS"
        tpl = env.get_template("cts.j2")
        rendered = tpl.render(**base_context)
        assert "CTS" in rendered

    def test_routing_template_renders(
        self, env: jinja2.Environment, base_context: dict  # type: ignore[type-arg]
    ) -> None:
        tpl = env.get_template("routing.j2")
        rendered = tpl.render(**base_context)
        assert "routing" in rendered.lower()

    def test_place_global_template_renders(
        self, env: jinja2.Environment, base_context: dict  # type: ignore[type-arg]
    ) -> None:
        tpl = env.get_template("place_global.j2")
        rendered = tpl.render(**base_context)
        assert "placement" in rendered.lower() or "global" in rendered.lower()

    def test_route_global_template_renders(
        self, env: jinja2.Environment, base_context: dict  # type: ignore[type-arg]
    ) -> None:
        tpl = env.get_template("route_global.j2")
        rendered = tpl.render(**base_context)
        assert "routing" in rendered.lower() or "global" in rendered.lower()

    def test_judge_template_renders(self, env: jinja2.Environment) -> None:
        context = {
            "stage": "PLACE_GLOBAL",
            "attempt_number": 2,
            "baseline_metrics": "WNS: -0.5",
            "current_metrics": "WNS: -0.3",
            "evidence_summary": "No issues.",
            "constraint_digest": None,
            "judge_index": 0,
            "model_name": "test_model",
        }
        tpl = env.get_template("judge.j2")
        rendered = tpl.render(**context)
        assert "PASS" in rendered or "FAIL" in rendered

    def test_template_with_rejection_feedback(
        self, env: jinja2.Environment, base_context: dict  # type: ignore[type-arg]
    ) -> None:
        base_context["last_rejection_feedback"] = "Remove CLOCK_PERIOD"
        tpl = env.get_template("worker_base.j2")
        rendered = tpl.render(**base_context)
        assert "Remove CLOCK_PERIOD" in rendered

    def test_template_with_lessons_learned(
        self, env: jinja2.Environment, base_context: dict  # type: ignore[type-arg]
    ) -> None:
        base_context["lessons_learned"] = "Attempt 1 failed due to high utilization."
        tpl = env.get_template("worker_base.j2")
        rendered = tpl.render(**base_context)
        assert "high utilization" in rendered

    def test_missing_required_var_raises(self, env: jinja2.Environment) -> None:
        tpl = env.get_template("worker_base.j2")
        with pytest.raises(jinja2.UndefinedError):
            tpl.render(stage="X")  # Missing many required vars

    def test_all_stage_templates_exist(self, env: jinja2.Environment) -> None:
        """At least worker_base and judge exist."""
        assert env.get_template("worker_base.j2") is not None
        assert env.get_template("judge.j2") is not None

    def test_all_specific_templates_loadable(self, env: jinja2.Environment) -> None:
        """All stage-specific templates load without error."""
        for name in [
            "synth.j2",
            "floorplan.j2",
            "placement.j2",
            "cts.j2",
            "routing.j2",
            "place_global.j2",
            "place_detailed.j2",
            "route_global.j2",
            "route_detailed.j2",
        ]:
            tpl = env.get_template(name)
            assert tpl is not None


class TestMasterTemplate:
    """Tests for the master agent prompt template."""

    @pytest.fixture
    def env(self) -> jinja2.Environment:
        return jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(TEMPLATE_DIR)),
            undefined=jinja2.StrictUndefined,
        )

    @pytest.fixture
    def master_context(self) -> dict:  # type: ignore[type-arg]
        return {
            "failed_stage": "ROUTE_DETAILED",
            "attempts_used": 3,
            "is_improving": False,
            "stage_history": [
                {"stage": "SYNTH", "attempts": 1, "best_score": 0.85, "outcome": "PASS"},
                {"stage": "FLOORPLAN", "attempts": 2, "best_score": 0.72, "outcome": "PASS"},
                {"stage": "PDN", "attempts": 1, "best_score": 0.80, "outcome": "PASS"},
                {"stage": "ROUTE_DETAILED", "attempts": 3, "best_score": 0.45, "outcome": "FAIL"},
            ],
            "score_history": [
                {"attempt": 1, "score": 0.40, "judge": "FAIL"},
                {"attempt": 2, "score": 0.43, "judge": "FAIL"},
                {"attempt": 3, "score": 0.45, "judge": "FAIL"},
            ],
            "rollback_targets": [
                {"stage": "ROUTE_GLOBAL", "best_score": 0.70, "best_attempt": 1},
                {"stage": "PLACE_DETAILED", "best_score": 0.68, "best_attempt": 2},
                {"stage": "FLOORPLAN", "best_score": 0.72, "best_attempt": 2},
            ],
            "execution_status": "success",
            "error_summary": [
                {"severity": "high", "message": "DRC violations: 42 shorts"},
                {"severity": "medium", "message": "Wire length exceeded 150%"},
            ],
            "current_metrics": "DRC: 42 violations, Wire length: 12500um",
            "lessons_learned": "Attempt 1: high congestion. Attempt 2: reduced util but still shorts.",
        }

    def test_master_template_loads(self, env: jinja2.Environment) -> None:
        """Master template exists and loads without error."""
        tpl = env.get_template("master.j2")
        assert tpl is not None

    def test_master_renders_with_full_context(
        self, env: jinja2.Environment, master_context: dict  # type: ignore[type-arg]
    ) -> None:
        """Master template renders with all context variables."""
        tpl = env.get_template("master.j2")
        rendered = tpl.render(**master_context)
        assert "ROUTE_DETAILED" in rendered
        assert "retry" in rendered
        assert "rollback" in rendered
        assert "escalate" in rendered

    def test_master_includes_stage_history_table(
        self, env: jinja2.Environment, master_context: dict  # type: ignore[type-arg]
    ) -> None:
        """Stage history table renders with all stages."""
        tpl = env.get_template("master.j2")
        rendered = tpl.render(**master_context)
        assert "SYNTH" in rendered
        assert "FLOORPLAN" in rendered
        assert "0.8500" in rendered or "0.85" in rendered

    def test_master_includes_score_history(
        self, env: jinja2.Environment, master_context: dict  # type: ignore[type-arg]
    ) -> None:
        """Score history shows attempt scores."""
        tpl = env.get_template("master.j2")
        rendered = tpl.render(**master_context)
        assert "0.4000" in rendered or "0.40" in rendered
        assert "FAIL" in rendered

    def test_master_includes_rollback_targets(
        self, env: jinja2.Environment, master_context: dict  # type: ignore[type-arg]
    ) -> None:
        """Rollback targets are listed with scores."""
        tpl = env.get_template("master.j2")
        rendered = tpl.render(**master_context)
        assert "ROUTE_GLOBAL" in rendered
        assert "PLACE_DETAILED" in rendered
        assert "checkpoint" in rendered.lower()

    def test_master_includes_evidence(
        self, env: jinja2.Environment, master_context: dict  # type: ignore[type-arg]
    ) -> None:
        """Evidence section renders with errors."""
        tpl = env.get_template("master.j2")
        rendered = tpl.render(**master_context)
        assert "DRC violations" in rendered
        assert "high" in rendered

    def test_master_includes_lessons_learned(
        self, env: jinja2.Environment, master_context: dict  # type: ignore[type-arg]
    ) -> None:
        """Lessons learned section renders when provided."""
        tpl = env.get_template("master.j2")
        rendered = tpl.render(**master_context)
        assert "high congestion" in rendered

    def test_master_includes_current_metrics(
        self, env: jinja2.Environment, master_context: dict  # type: ignore[type-arg]
    ) -> None:
        """Current metrics section renders."""
        tpl = env.get_template("master.j2")
        rendered = tpl.render(**master_context)
        assert "DRC: 42" in rendered

    def test_master_includes_json_example(
        self, env: jinja2.Environment, master_context: dict  # type: ignore[type-arg]
    ) -> None:
        """JSON response example is present in rendered output."""
        tpl = env.get_template("master.j2")
        rendered = tpl.render(**master_context)
        assert '"action"' in rendered
        assert '"target_stage"' in rendered
        assert '"reasoning"' in rendered

    def test_master_without_rollback_targets(
        self, env: jinja2.Environment, master_context: dict  # type: ignore[type-arg]
    ) -> None:
        """Master renders gracefully when no rollback targets are available."""
        master_context["rollback_targets"] = []
        tpl = env.get_template("master.j2")
        rendered = tpl.render(**master_context)
        assert "no rollback targets" in rendered.lower()

    def test_master_without_lessons_learned(
        self, env: jinja2.Environment, master_context: dict  # type: ignore[type-arg]
    ) -> None:
        """Master renders without lessons_learned section when empty."""
        master_context["lessons_learned"] = ""
        tpl = env.get_template("master.j2")
        rendered = tpl.render(**master_context)
        assert "Lessons Learned" not in rendered

    def test_master_empty_stage_history(
        self, env: jinja2.Environment, master_context: dict  # type: ignore[type-arg]
    ) -> None:
        """Master handles empty stage history."""
        master_context["stage_history"] = []
        tpl = env.get_template("master.j2")
        rendered = tpl.render(**master_context)
        assert "No stages completed" in rendered

    def test_master_no_errors(
        self, env: jinja2.Environment, master_context: dict  # type: ignore[type-arg]
    ) -> None:
        """Master handles no errors gracefully."""
        master_context["error_summary"] = []
        tpl = env.get_template("master.j2")
        rendered = tpl.render(**master_context)
        assert "no errors" in rendered.lower()
