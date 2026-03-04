"""Tests for the ExecutionAdapter abstract base class."""

from __future__ import annotations

import pytest

from agenticlane.execution.adapter import ExecutionAdapter


class TestExecutionAdapterABC:
    """Verify that ExecutionAdapter enforces the ABC contract."""

    def test_adapter_is_abstract(self) -> None:
        """Cannot instantiate ExecutionAdapter directly."""
        with pytest.raises(TypeError, match="abstract method"):
            ExecutionAdapter()  # type: ignore[abstract]

    def test_adapter_requires_run_stage(self) -> None:
        """A subclass that omits ``run_stage`` raises TypeError on
        instantiation."""

        class IncompleteAdapter(ExecutionAdapter):
            pass

        with pytest.raises(TypeError, match="abstract method"):
            IncompleteAdapter()  # type: ignore[abstract]

    def test_adapter_subclass_with_run_stage_is_instantiable(self) -> None:
        """A proper subclass that implements ``run_stage`` can be
        instantiated."""
        from typing import Any, Optional

        from agenticlane.schemas.execution import ExecutionResult

        class DummyAdapter(ExecutionAdapter):
            async def run_stage(
                self,
                *,
                run_root: str,
                stage_name: str,
                librelane_config_path: str,
                resolved_design_config_path: str,
                patch: dict[str, Any],
                state_in_path: Optional[str],
                attempt_dir: str,
                timeout_seconds: int,
            ) -> ExecutionResult:
                return ExecutionResult(
                    execution_status="success",
                    exit_code=0,
                    runtime_seconds=0.0,
                    attempt_dir=attempt_dir,
                    workspace_dir=attempt_dir,
                    artifacts_dir=attempt_dir,
                )

        adapter = DummyAdapter()
        assert isinstance(adapter, ExecutionAdapter)
