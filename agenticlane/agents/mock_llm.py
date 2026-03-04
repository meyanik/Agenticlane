"""Mock LLM provider for deterministic testing.

Returns pre-configured responses for specific Pydantic models,
enabling full testing without any real LLM calls.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel

from agenticlane.agents.llm_provider import LLMProvider
from agenticlane.config.models import LLMConfig


class MockLLMProvider(LLMProvider):
    """Mock LLM provider returning pre-configured responses.

    Supports:
    - A single default response (returned on every call).
    - A FIFO queue of responses (consumed in order; falls back to default).
    - Failure injection (next *N* calls raise :class:`ConnectionError`).
    """

    def __init__(
        self,
        config: Optional[LLMConfig] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(config=config or LLMConfig(), **kwargs)
        self._response_queue: list[str] = []
        self._default_response: str = "{}"
        self._call_count: int = 0
        self._fail_until: int = 0
        self._fail_error: str = "Mock failure"

    # ------------------------------------------------------------------ #
    # Configuration helpers
    # ------------------------------------------------------------------ #

    def set_response(self, instance: BaseModel) -> None:
        """Set a single default response (returned on every call)."""
        self._default_response = instance.model_dump_json()

    def queue_responses(self, *instances: BaseModel) -> None:
        """Queue responses in order.  After the queue is depleted the default is used."""
        for inst in instances:
            self._response_queue.append(inst.model_dump_json())

    def queue_raw(self, *raw_jsons: str) -> None:
        """Queue raw JSON strings (useful for testing malformed responses)."""
        self._response_queue.extend(raw_jsons)

    def set_failure(self, count: int = 1, error: str = "Mock failure") -> None:
        """Make the next *count* ``_call`` invocations raise :class:`ConnectionError`."""
        self._fail_until = self._call_count + count
        self._fail_error = error

    # ------------------------------------------------------------------ #
    # Introspection
    # ------------------------------------------------------------------ #

    @property
    def call_count(self) -> int:
        """Number of ``_call`` invocations so far."""
        return self._call_count

    # ------------------------------------------------------------------ #
    # LLMProvider contract
    # ------------------------------------------------------------------ #

    async def _call(
        self,
        prompt: str,
        model: str,
        temperature: float,
        seed: int,
    ) -> tuple[str, int, int]:
        """Return the next pre-configured mock response."""
        self._call_count += 1

        if self._call_count <= self._fail_until:
            raise ConnectionError(self._fail_error)

        raw = self._response_queue.pop(0) if self._response_queue else self._default_response
        tokens_in = len(prompt) // 4
        tokens_out = len(raw) // 4
        return raw, tokens_in, tokens_out
