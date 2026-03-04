"""LLM Provider stack for AgenticLane.

Provides a unified async interface to LLM backends with structured output
enforcement, retry logic, call logging, and reproducibility support.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, TypeVar

from pydantic import BaseModel

from agenticlane.config.models import LLMConfig
from agenticlane.schemas.llm import LLMCallRecord

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


def hash_content(content: str) -> str:
    """Deterministic SHA-256 hash of string content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _now_ms() -> int:
    """Current time in milliseconds (monotonic clock)."""
    return int(time.monotonic() * 1000)


class LLMProvider(ABC):
    """Abstract LLM provider interface.

    Subclasses implement :meth:`_call` for actual LLM interaction.
    This base class handles logging, retries, and structured output parsing.
    """

    def __init__(self, config: LLMConfig, log_dir: Optional[Path] = None) -> None:
        self.config = config
        self._log_dir = log_dir
        self._call_records: list[LLMCallRecord] = []

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #

    def resolve_model_for_stage(self, role: str, stage: str) -> str:
        """Resolve the model name for a given role and pipeline stage.

        Checks ``config.models.stage_overrides[stage]`` first, then
        falls back to the global default for *role*.

        Parameters
        ----------
        role:
            ``"worker"`` or ``"judge"`` (judge returns first judge model).
        stage:
            Pipeline stage name (e.g. ``"ROUTE_DETAILED"``).

        Returns
        -------
        str
            Resolved model name string.
        """
        override = self.config.models.stage_overrides.get(stage)
        if override is not None:
            if role == "worker" and override.worker is not None:
                return override.worker
            if role == "judge" and override.judge:
                return override.judge[0]
        # Fall back to global defaults
        if role == "judge":
            return self.config.models.judge[0] if self.config.models.judge else self.config.models.worker
        return self.config.models.worker

    def resolve_judge_models_for_stage(self, stage: str) -> list[str]:
        """Resolve the full judge model list for a pipeline stage.

        Checks ``config.models.stage_overrides[stage].judge`` first,
        then falls back to the global ``config.models.judge``.
        """
        override = self.config.models.stage_overrides.get(stage)
        if override is not None and override.judge:
            return list(override.judge)
        return list(self.config.models.judge)

    async def generate(
        self,
        prompt: str,
        response_model: type[T],
        *,
        model: Optional[str] = None,
        stage: str = "",
        attempt: int = 1,
        branch: str = "B0",
        role: str = "worker",
        context: Optional[dict[str, Any]] = None,
    ) -> T | None:
        """Generate structured output from an LLM.

        Args:
            prompt: The full prompt text.
            response_model: Pydantic model class for structured output.
            model: Model name override (defaults to config worker model).
            stage: Stage name for logging and per-stage model resolution.
            attempt: Attempt number for logging (>= 1).
            branch: Branch ID for logging.
            role: Agent role (``worker`` / ``judge`` / ``master`` / ``specialist``).
            context: Optional context dict for debugging.

        Returns:
            Parsed *response_model* instance, or ``None`` on permanent failure.
        """
        effective_model = model or self.resolve_model_for_stage(role, stage)
        max_retries = (
            self.config.structured_output.max_retries
            if self.config.structured_output.enabled
            else 0
        )

        prompt_hash = hash_content(prompt)
        call_id = uuid.uuid4().hex
        start_ms = _now_ms()

        last_error: Optional[str] = None
        retries_used = 0

        for retry in range(max_retries + 1):
            try:
                raw_response, tokens_in, tokens_out = await self._call(
                    prompt=prompt,
                    model=effective_model,
                    temperature=self.config.temperature,
                    seed=self.config.seed,
                )

                # Parse structured output
                parsed = self._parse_response(raw_response, response_model)

                latency_ms = _now_ms() - start_ms
                response_hash = hash_content(raw_response)

                record = LLMCallRecord(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    call_id=call_id,
                    model=effective_model,
                    provider=self.config.provider,
                    role=role,
                    stage=stage,
                    attempt=attempt,
                    branch=branch,
                    parameters={
                        "temperature": self.config.temperature,
                        "seed": self.config.seed,
                    },
                    prompt_hash=prompt_hash,
                    response_hash=response_hash,
                    latency_ms=latency_ms,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    structured_output_valid=True,
                    retries=retries_used,
                    error=None,
                )
                self._log_call(record)
                return parsed

            except (ValueError, json.JSONDecodeError) as exc:
                retries_used = retry + 1
                last_error = str(exc)
                logger.warning(
                    "Structured output parse failed (retry %d/%d): %s",
                    retries_used,
                    max_retries,
                    last_error,
                )
                continue
            except Exception as exc:  # noqa: BLE001
                retries_used = retry + 1
                last_error = str(exc)
                logger.error("LLM call failed: %s", last_error)
                continue

        # All retries exhausted
        latency_ms = _now_ms() - start_ms
        record = LLMCallRecord(
            timestamp=datetime.now(timezone.utc).isoformat(),
            call_id=call_id,
            model=effective_model,
            provider=self.config.provider,
            role=role,
            stage=stage,
            attempt=attempt,
            branch=branch,
            parameters={
                "temperature": self.config.temperature,
                "seed": self.config.seed,
            },
            prompt_hash=prompt_hash,
            response_hash="",
            latency_ms=latency_ms,
            tokens_in=0,
            tokens_out=0,
            structured_output_valid=False,
            retries=retries_used,
            error=last_error,
        )
        self._log_call(record)
        return None

    async def batch_generate(
        self,
        prompts: list[str],
        response_model: type[T],
        *,
        models: Optional[list[str]] = None,
        stage: str = "",
        attempt: int = 1,
        branch: str = "B0",
        role: str = "judge",
        max_concurrent: int = 3,
    ) -> list[T | None]:
        """Generate multiple structured responses (e.g. for judge ensemble).

        Args:
            prompts: List of prompt texts.
            response_model: Pydantic model for each response.
            models: Optional per-prompt model names (round-robin if fewer).
            stage, attempt, branch, role: Logging context.
            max_concurrent: Max concurrent LLM calls.

        Returns:
            List of parsed responses (``None`` for individual failures).
        """
        import asyncio

        effective_models = models or self.resolve_judge_models_for_stage(stage)
        semaphore = asyncio.Semaphore(max_concurrent)

        async def _limited_generate(idx: int, prompt: str) -> T | None:
            async with semaphore:
                model_name = effective_models[idx % len(effective_models)]
                return await self.generate(
                    prompt=prompt,
                    response_model=response_model,
                    model=model_name,
                    stage=stage,
                    attempt=attempt,
                    branch=branch,
                    role=role,
                )

        tasks = [_limited_generate(i, p) for i, p in enumerate(prompts)]
        return list(await asyncio.gather(*tasks))

    # --------------------------------------------------------------------- #
    # Subclass contract
    # --------------------------------------------------------------------- #

    @abstractmethod
    async def _call(
        self,
        prompt: str,
        model: str,
        temperature: float,
        seed: int,
    ) -> tuple[str, int, int]:
        """Make the actual LLM API call.

        Returns:
            ``(raw_response_text, tokens_in, tokens_out)``
        """
        ...

    # --------------------------------------------------------------------- #
    # Structured output parsing
    # --------------------------------------------------------------------- #

    def _parse_response(self, raw: str, response_model: type[T]) -> T:
        """Parse raw LLM response into a structured Pydantic model.

        Tries multiple strategies in order:
        1. Parse as dict, fix field aliases, validate
        2. JSON from markdown code blocks (same alias-fixing)
        3. Find first JSON object {...} in the text
        4. Direct JSON string validation (last resort)
        """
        text = raw.strip()

        # Strategy 1: Parse dict and fix aliases (handles aliased field names)
        if text.startswith("{"):
            try:
                data = json.loads(text)
                data = self._fix_field_aliases(data, response_model)
                return response_model.model_validate(data)
            except (ValueError, json.JSONDecodeError, TypeError):
                pass

        # Strategy 2: Extract from markdown code blocks
        if "```" in text:
            block = self._extract_json_block(text)
            try:
                data = json.loads(block)
                data = self._fix_field_aliases(data, response_model)
                return response_model.model_validate(data)
            except (ValueError, json.JSONDecodeError, TypeError):
                pass

        # Strategy 3: Find first JSON object in text
        json_text = self._find_json_object(text)
        if json_text:
            try:
                data = json.loads(json_text)
                data = self._fix_field_aliases(data, response_model)
                return response_model.model_validate(data)
            except (ValueError, json.JSONDecodeError, TypeError):
                pass

        # All strategies failed — raise for retry
        return response_model.model_validate_json(text)

    @staticmethod
    def _extract_json_block(text: str) -> str:
        """Extract JSON from markdown code blocks."""
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if match:
            return match.group(1).strip()
        return text

    @staticmethod
    def _find_json_object(text: str) -> str | None:
        """Find the first balanced JSON object {...} in text."""
        start = text.find("{")
        if start == -1:
            return None
        depth = 0
        in_string = False
        escape_next = False
        for i in range(start, len(text)):
            ch = text[i]
            if escape_next:
                escape_next = False
                continue
            if ch == "\\":
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
        return None

    @staticmethod
    def _fix_field_aliases(data: dict[str, Any], response_model: type[T]) -> dict[str, Any]:
        """Map common LLM field name variants to the model's expected names.

        E.g. Gemini often returns 'decision'/'choice' instead of 'action'.
        """
        # Build a set of known field names for the model
        model_fields = set(response_model.model_fields.keys())

        # Common aliases: {alias -> canonical_field}
        aliases: dict[str, str] = {
            "choice": "action",
            "decision": "action",
            "reasoning": "reason",
            "explanation": "reason",
            "rationale": "reason",
            "target": "target_stage",
            "rollback_target": "target_stage",
        }

        fixed = dict(data)
        for alias, canonical in aliases.items():
            if alias in fixed and canonical not in fixed and canonical in model_fields:
                fixed[canonical] = fixed.pop(alias)

        return fixed

    # --------------------------------------------------------------------- #
    # Call logging
    # --------------------------------------------------------------------- #

    def _log_call(self, record: LLMCallRecord) -> None:
        """Append call record to in-memory list and optionally to JSONL file."""
        self._call_records.append(record)
        if self._log_dir is not None:
            log_path = self._log_dir / "llm_calls.jsonl"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "a") as fh:
                fh.write(record.model_dump_json() + "\n")

    @property
    def call_records(self) -> list[LLMCallRecord]:
        """All call records from this provider instance (defensive copy)."""
        return list(self._call_records)

    def get_log_path(self) -> Optional[Path]:
        """Return path to the JSONL log file, or ``None`` if no *log_dir*."""
        if self._log_dir is None:
            return None
        return self._log_dir / "llm_calls.jsonl"

    # --------------------------------------------------------------------- #
    # Lifecycle
    # --------------------------------------------------------------------- #

    async def close(self) -> None:  # noqa: B027
        """Clean up resources.  Override in subclasses as needed."""
