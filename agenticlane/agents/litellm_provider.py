"""LiteLLM-based LLM provider for AgenticLane.

Routes to Claude API (or any litellm-supported backend) using
``litellm.acompletion``.  Implements the :class:`LLMProvider` ABC
so that the orchestrator can swap between mock and real LLM seamlessly.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

from agenticlane.agents.llm_provider import LLMProvider
from agenticlane.config.models import LLMConfig

try:
    import litellm  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    litellm = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# Default model when none is specified in config
_DEFAULT_MODEL = "gemini/gemini-2.5-pro"

# Regex to strip ``<think>...</think>`` blocks that some local models
# (e.g. Qwen3) prepend before the actual JSON response.
_THINK_TAG_RE = re.compile(r"<think>[\s\S]*?</think>\s*", re.DOTALL)


class LiteLLMProvider(LLMProvider):
    """LLM provider backed by litellm (Claude API by default).

    Parameters
    ----------
    config:
        LLM configuration from AgenticLane config.
    log_dir:
        Optional directory for JSONL call logging.
    default_model:
        Override the default model string.  If *None*, uses
        ``config.models.worker`` with ``anthropic/`` prefix routing
        when needed.
    """

    def __init__(
        self,
        config: LLMConfig,
        log_dir: Optional[Path] = None,
        default_model: Optional[str] = None,
    ) -> None:
        super().__init__(config=config, log_dir=log_dir)
        # Resolve default model: explicit arg > config worker > hardcoded fallback
        _placeholders = {
            "model_worker", "model_master", "default", "auto", "",
        }
        if default_model:
            self._default_model = default_model
        elif config.models.worker not in _placeholders:
            self._default_model = config.models.worker
        else:
            self._default_model = _DEFAULT_MODEL
        self._api_base: Optional[str] = config.api_base
        self._is_local = self._api_base is not None
        # For local servers, ensure the default model has the openai/ prefix
        # so that placeholder resolution returns a properly-prefixed name.
        if self._is_local and not self._default_model.startswith("openai/"):
            self._default_model = f"openai/{self._default_model}"

        # Tell litellm to silently drop parameters unsupported by a
        # provider (e.g. ``seed`` for Anthropic, ``response_format`` for
        # some endpoints) instead of raising UnsupportedParamsError.
        if litellm is not None:
            litellm.drop_params = True

    async def _call(
        self,
        prompt: str,
        model: str,
        temperature: float,
        seed: int,
    ) -> tuple[str, int, int]:
        """Make an async LLM call via litellm.

        Returns
        -------
        tuple
            ``(response_text, prompt_tokens, completion_tokens)``

        Raises
        ------
        ImportError
            If litellm is not installed.
        """
        if litellm is None:
            raise ImportError(
                "litellm is required for LiteLLMProvider. "
                "Install with: pip install litellm"
            )

        # Apply model prefix routing if the model string doesn't already
        # contain a provider prefix (e.g. "anthropic/", "openai/")
        effective_model = self._resolve_model(model)

        messages: list[dict[str, str]] = [
            {
                "role": "system",
                "content": (
                    "You are an expert ASIC design assistant. "
                    "Always respond with ONLY valid JSON — no markdown, "
                    "no explanation text, no code blocks. "
                    "Output raw JSON objects directly."
                ),
            },
            {"role": "user", "content": prompt},
        ]

        call_kwargs: dict[str, object] = {
            "model": effective_model,
            "messages": messages,
            "temperature": temperature,
        }

        # --- Local server (LM Studio, Ollama, vLLM, etc.) ---
        if self._is_local:
            call_kwargs["api_base"] = self._api_base
            # Local servers don't need a real API key but litellm
            # requires one to be set for the openai provider.
            call_kwargs["api_key"] = "lm-studio"
            call_kwargs["seed"] = seed
            # LM Studio doesn't support ``{"type": "json_object"}``;
            # the system prompt already instructs JSON-only output and
            # we strip ``<think>`` tags from the response below.
        else:
            # --- Cloud APIs ---
            # Force JSON output mode for cloud providers that support it
            call_kwargs["response_format"] = {"type": "json_object"}
            # Gemini and Anthropic do not support the seed parameter
            if not effective_model.startswith(("gemini/", "anthropic/")):
                call_kwargs["seed"] = seed

        response = await litellm.acompletion(**call_kwargs)

        # Extract text and token counts from the litellm response
        choice = response.choices[0]
        text: str = choice.message.content or ""

        # Strip chain-of-thought ``<think>...</think>`` blocks that some
        # local models (Qwen3, DeepSeek-R1) prepend before JSON output.
        if self._is_local:
            text = _strip_think_tags(text)

        usage = response.usage
        prompt_tokens: int = usage.prompt_tokens if usage else 0
        completion_tokens: int = usage.completion_tokens if usage else 0

        return text, prompt_tokens, completion_tokens

    def _resolve_model(self, model: str) -> str:
        """Ensure the model string has a provider prefix for litellm routing.

        If the model is one of the placeholder names from config defaults
        (e.g. ``model_worker``, ``model_master``), substitute the real
        default model.  If the model already contains a ``/``, assume
        it's fully qualified.  Bare model names are routed by prefix:
        ``gemini-*`` → ``gemini/``, ``gpt-*``/``o1-*``/``o3-*`` → ``openai/``,
        ``claude-*`` → ``anthropic/``.

        For local servers (``api_base`` set), models are prefixed with
        ``openai/`` to use litellm's OpenAI-compatible provider.
        """
        # Placeholder names from default config
        placeholders = {
            "model_worker", "model_master", "model_j1", "model_j2", "model_j3",
            "judge_model_a", "judge_model_b", "judge_model_c",
            "default", "auto", "",
        }
        if not model or model in placeholders:
            return self._default_model

        # For local servers, ensure the openai/ prefix for litellm routing
        if self._is_local:
            if not model.startswith("openai/"):
                return f"openai/{model}"
            return model

        # Already has a provider prefix
        if "/" in model:
            return model

        # Detect provider from bare model name
        if model.startswith("gemini-"):
            return f"gemini/{model}"
        if model.startswith(("gpt-", "o1-", "o3-")):
            return f"openai/{model}"
        if model.startswith("claude-"):
            return f"anthropic/{model}"

        # Unknown bare name -- pass through as-is (let litellm figure it out)
        return model


def _strip_think_tags(text: str) -> str:
    """Remove ``<think>...</think>`` blocks from LLM output.

    Some local models (Qwen3, DeepSeek-R1) use chain-of-thought tags.
    We strip them to get the raw JSON response.
    """
    return _THINK_TAG_RE.sub("", text).strip()
