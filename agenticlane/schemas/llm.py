"""LLM call logging schema for AgenticLane.

Defines the LLMCallRecord model for structured logging of all
LLM API calls to JSONL files for reproducibility and debugging.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class LLMCallRecord(BaseModel):
    """Record of a single LLM API call.

    Written to llm_calls.jsonl in each attempt directory.
    Captures full provenance for reproducibility and debugging.
    """

    timestamp: str = Field(
        description="ISO 8601 timestamp of the call"
    )
    call_id: str = Field(
        description="Unique call identifier (UUID)"
    )
    model: str = Field(
        description="Model identifier (e.g., openai/local-model)"
    )
    provider: str = Field(
        description="Provider name (e.g., litellm, openai, anthropic)"
    )
    role: str = Field(
        description="Agent role making the call (e.g., worker, judge, master)"
    )
    stage: str = Field(
        description="Current stage name"
    )
    attempt: int = Field(
        ge=1, description="Current attempt number"
    )
    branch: str = Field(
        description="Current branch identifier"
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="LLM call parameters (temperature, max_tokens, etc.)",
    )
    prompt_hash: str = Field(
        description="SHA-256 hash of the full prompt for deduplication"
    )
    response_hash: str = Field(
        description="SHA-256 hash of the full response for verification"
    )
    latency_ms: int = Field(
        ge=0, description="Call latency in milliseconds"
    )
    tokens_in: int = Field(
        ge=0, description="Number of input tokens"
    )
    tokens_out: int = Field(
        ge=0, description="Number of output tokens"
    )
    structured_output_valid: bool = Field(
        default=True,
        description="Whether the structured output parsed successfully",
    )
    retries: int = Field(
        default=0,
        ge=0,
        description="Number of retries before getting a valid response",
    )
    error: Optional[str] = Field(
        default=None,
        description="Error message if the call failed (None on success)",
    )
