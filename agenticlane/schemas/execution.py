"""Execution result schemas for AgenticLane.

Defines ExecutionStatus literal type and ExecutionResult model
for capturing the outcome of a LibreLane stage execution.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

ExecutionStatus = Literal[
    "success",
    "tool_crash",
    "timeout",
    "oom_killed",
    "config_error",
    "patch_rejected",
    "unknown_fail",
]


class ExecutionResult(BaseModel):
    """Result of a single stage execution attempt.

    Produced by the ExecutionAdapter after running a LibreLane stage.
    Contains exit information, paths to outputs, and optional error details.
    """

    execution_status: ExecutionStatus
    exit_code: int = Field(description="Process exit code (0 = success)")
    runtime_seconds: float = Field(
        ge=0.0, description="Wall-clock time for the execution"
    )
    attempt_dir: str = Field(
        description="Path to the attempt directory containing all outputs"
    )
    workspace_dir: str = Field(
        description="Path to the workspace directory used by the EDA tool"
    )
    artifacts_dir: str = Field(
        description="Path to the artifacts directory with stage outputs"
    )
    state_out_path: Optional[str] = Field(
        default=None,
        description="Path to the state_out.json produced by the stage (None on failure)",
    )
    stderr_tail: Optional[str] = Field(
        default=None,
        description="Last N lines of stderr for crash diagnostics",
    )
    error_summary: Optional[str] = Field(
        default=None,
        description="Human-readable summary of the error (None on success)",
    )
