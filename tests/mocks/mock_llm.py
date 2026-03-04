"""MockLLMProvider for testing without real LLM API calls.

Returns pre-recorded responses keyed by prompt hash or stage.
Records all calls for assertion in tests.
"""

from __future__ import annotations

import hashlib
from typing import Any, Optional

from agenticlane.agents.llm_provider import LLMProvider
from agenticlane.config.models import LLMConfig


class MockLLMProvider(LLMProvider):
    """Mock LLM provider for testing.

    Returns pre-recorded responses keyed by prompt hash or stage.
    Records all calls for assertion in tests.

    Extends :class:`agenticlane.agents.llm_provider.LLMProvider` so it can be
    used anywhere the real provider is expected.  The rich stage/role/hash
    lookup and ``call_log`` API is preserved from the original test-only mock.

    Usage::

        llm = MockLLMProvider()
        llm.add_response("floorplan", {"config_vars": {"FP_CORE_UTIL": 40}})
        result = await llm.generate("Optimize floorplan", stage="floorplan")
        assert result == {"config_vars": {"FP_CORE_UTIL": 40}}
        assert len(llm.call_log) == 1
    """

    def __init__(
        self,
        responses: dict[str, Any] | None = None,
        config: LLMConfig | None = None,
    ) -> None:
        super().__init__(config=config or LLMConfig())
        self.responses: dict[str, Any] = responses or {}
        self.call_log: list[dict[str, Any]] = []
        self._default_response: Any = {}

    # ------------------------------------------------------------------
    # LLMProvider abstract contract
    # ------------------------------------------------------------------

    async def _call(
        self,
        prompt: str,
        model: str,
        temperature: float,
        seed: int,
    ) -> tuple[str, int, int]:
        """Fallback raw-call implementation (not normally reached).

        ``generate()`` is fully overridden, so ``_call`` is only invoked if
        a subclass explicitly calls ``super().generate()``.  Returns an empty
        JSON object in that case.
        """
        raw = "{}"
        tokens_in = len(prompt) // 4
        tokens_out = len(raw) // 4
        return raw, tokens_in, tokens_out

    # ------------------------------------------------------------------
    # Core API — override LLMProvider.generate / batch_generate
    # ------------------------------------------------------------------

    async def generate(  # type: ignore[override]
        self,
        prompt: str,
        response_model: type[Any] | None = None,
        *,
        model: str | None = None,
        stage: str = "",
        attempt: int = 1,
        branch: str = "B0",
        role: str = "worker",
        context: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Generate a response from pre-recorded responses.

        Lookup order:
        1. Exact prompt hash match
        2. Stage key match
        3. Role key match
        4. Default empty response

        Args:
            prompt: The prompt text.
            response_model: Optional Pydantic model class for structured output.
                If provided and the stored response is a dict, attempts to
                construct the model from the dict.
            stage: Current stage name (used as lookup key).
            role: Agent role making the call (used as lookup key).

        Returns:
            The pre-recorded response, or a default empty response.
        """
        prompt_hash = self._hash_prompt(prompt)

        # Record the call
        self.call_log.append(
            {
                "prompt": prompt,
                "prompt_hash": prompt_hash,
                "response_model": response_model,
                "stage": stage,
                "role": role,
            }
        )

        # Lookup: prompt hash -> stage -> role -> default
        response: Any
        if prompt_hash in self.responses:
            response = self.responses[prompt_hash]
        elif stage and stage in self.responses:
            response = self.responses[stage]
        elif role and role in self.responses:
            response = self.responses[role]
        else:
            response = self._default_response

        # If a response_model is requested and response is a dict, try to instantiate
        if response_model is not None and isinstance(response, dict):
            try:
                return response_model(**response)
            except Exception:  # noqa: BLE001
                return response

        return response

    async def batch_generate(  # type: ignore[override]
        self,
        prompts: list[str],
        response_model: type[Any] | None = None,
        *,
        models: list[str] | None = None,
        stage: str = "",
        attempt: int = 1,
        branch: str = "B0",
        role: str = "judge",
        max_concurrent: int = 3,
        **kwargs: Any,
    ) -> list[Any]:
        """Batch generate responses (calls generate for each prompt)."""
        results = []
        for prompt in prompts:
            result = await self.generate(
                prompt=prompt,
                response_model=response_model,
                stage=stage,
                attempt=attempt,
                branch=branch,
                role=role,
            )
            results.append(result)
        return results

    # ------------------------------------------------------------------
    # Configuration helpers
    # ------------------------------------------------------------------

    def add_response(self, key: str, response: Any) -> None:
        """Add a pre-recorded response for a given key.

        The key can be a prompt hash, stage name, or role name.

        Args:
            key: Lookup key for the response.
            response: The response to return when the key matches.
        """
        self.responses[key] = response

    def set_default_response(self, response: Any) -> None:
        """Set the default response returned when no key matches.

        Args:
            response: The default response value.
        """
        self._default_response = response

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def get_calls(self, role: Optional[str] = None) -> list[dict[str, Any]]:
        """Get recorded calls, optionally filtered by role.

        Args:
            role: If provided, only return calls with this role.

        Returns:
            List of call record dicts.
        """
        if role is None:
            return list(self.call_log)
        return [c for c in self.call_log if c["role"] == role]

    def get_calls_for_stage(self, stage: str) -> list[dict[str, Any]]:
        """Get recorded calls filtered by stage.

        Args:
            stage: Stage name to filter by.

        Returns:
            List of call record dicts for the given stage.
        """
        return [c for c in self.call_log if c["stage"] == stage]

    @property
    def call_count(self) -> int:
        """Total number of recorded calls."""
        return len(self.call_log)

    def reset(self) -> None:
        """Clear the call log (but keep configured responses)."""
        self.call_log.clear()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _hash_prompt(prompt: str) -> str:
        """SHA-256 hash of the prompt string."""
        return hashlib.sha256(prompt.encode()).hexdigest()
