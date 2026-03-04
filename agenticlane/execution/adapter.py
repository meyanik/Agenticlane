"""Abstract base class for execution adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from agenticlane.schemas.execution import ExecutionResult


class ExecutionAdapter(ABC):
    """Abstract execution adapter for running LibreLane stages.

    Subclasses must implement ``run_stage`` which executes a single
    LibreLane stage inside an isolated workspace/attempt directory.
    """

    @abstractmethod
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
        """Run a single stage in an isolated workspace.

        Parameters
        ----------
        run_root:
            Absolute path to the run directory root.
        stage_name:
            Name of the LibreLane stage to execute (e.g. ``"synth"``,
            ``"floorplan"``).
        librelane_config_path:
            Path to the base LibreLane configuration file.
        resolved_design_config_path:
            Path to the resolved design configuration file.
        patch:
            Dictionary of patch actions (config_vars, sdc_edits, etc.)
            to apply before running the stage.
        state_in_path:
            Path to the incoming state baton JSON, or ``None`` for the
            first stage.
        attempt_dir:
            Path to the attempt directory where outputs should be written.
        timeout_seconds:
            Maximum wall-clock time for the stage run.

        Returns
        -------
        ExecutionResult
            A structured result capturing status, runtime, paths, and
            any error information.
        """
        ...
