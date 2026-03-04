"""P3.1 LLM Provider + P3.2 Call Logging tests.

Tests for :class:`LLMProvider`, :class:`MockLLMProvider`, structured output
parsing, retry behaviour, batch generation, and JSONL call logging.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import BaseModel, Field

from agenticlane.agents.llm_provider import LLMProvider, hash_content
from agenticlane.agents.mock_llm import MockLLMProvider
from agenticlane.config.models import LLMConfig, StructuredOutputConfig

# ------------------------------------------------------------------ #
# Test response models
# ------------------------------------------------------------------ #


class SimpleResponse(BaseModel):
    answer: str = "hello"
    confidence: float = 0.9


class PatchLikeResponse(BaseModel):
    config_vars: dict[str, float] = Field(default_factory=dict)
    rationale: str = ""


# ------------------------------------------------------------------ #
# hash_content
# ------------------------------------------------------------------ #


class TestHashContent:
    def test_deterministic(self) -> None:
        assert hash_content("hello") == hash_content("hello")

    def test_different_inputs(self) -> None:
        assert hash_content("hello") != hash_content("world")

    def test_sha256_length(self) -> None:
        assert len(hash_content("test")) == 64


# ------------------------------------------------------------------ #
# MockLLMProvider basics
# ------------------------------------------------------------------ #


class TestMockLLMProvider:
    @pytest.fixture()
    def provider(self, tmp_path: Path) -> MockLLMProvider:
        return MockLLMProvider(log_dir=tmp_path)

    async def test_generate_returns_structured_output(
        self, provider: MockLLMProvider
    ) -> None:
        resp = SimpleResponse(answer="test", confidence=0.85)
        provider.set_response(resp)
        result = await provider.generate(
            "prompt", SimpleResponse, stage="SYNTH", attempt=1
        )
        assert result is not None
        assert result.answer == "test"
        assert result.confidence == 0.85

    async def test_generate_returns_none_on_permanent_failure(
        self, provider: MockLLMProvider
    ) -> None:
        provider.set_failure(count=100)
        result = await provider.generate(
            "prompt", SimpleResponse, stage="SYNTH", attempt=1
        )
        assert result is None

    async def test_call_count_incremented(
        self, provider: MockLLMProvider
    ) -> None:
        provider.set_response(SimpleResponse())
        await provider.generate("p1", SimpleResponse)
        await provider.generate("p2", SimpleResponse)
        assert provider.call_count == 2

    async def test_response_queue_ordering(
        self, provider: MockLLMProvider
    ) -> None:
        r1 = SimpleResponse(answer="first", confidence=0.1)
        r2 = SimpleResponse(answer="second", confidence=0.2)
        provider.queue_responses(r1, r2)

        result1 = await provider.generate("p", SimpleResponse)
        result2 = await provider.generate("p", SimpleResponse)
        assert result1 is not None and result1.answer == "first"
        assert result2 is not None and result2.answer == "second"

    async def test_queue_raw_malformed_returns_none(self) -> None:
        cfg = LLMConfig(
            structured_output=StructuredOutputConfig(max_retries=0)
        )
        p = MockLLMProvider(config=cfg)
        p.queue_raw("not valid json {{{")
        result = await p.generate("prompt", SimpleResponse)
        assert result is None

    async def test_queue_depleted_falls_back_to_default(
        self, provider: MockLLMProvider
    ) -> None:
        default = SimpleResponse(answer="default")
        queued = SimpleResponse(answer="queued")
        provider.set_response(default)
        provider.queue_responses(queued)

        r1 = await provider.generate("p", SimpleResponse)
        r2 = await provider.generate("p", SimpleResponse)
        assert r1 is not None and r1.answer == "queued"
        assert r2 is not None and r2.answer == "default"

    async def test_patch_like_response(
        self, provider: MockLLMProvider
    ) -> None:
        resp = PatchLikeResponse(
            config_vars={"FP_CORE_UTIL": 50.0, "PL_TARGET_DENSITY": 0.6},
            rationale="Increase utilization for tighter timing",
        )
        provider.set_response(resp)
        result = await provider.generate("prompt", PatchLikeResponse)
        assert result is not None
        assert result.config_vars["FP_CORE_UTIL"] == 50.0
        assert "utilization" in result.rationale.lower()


# ------------------------------------------------------------------ #
# Call logging
# ------------------------------------------------------------------ #


class TestCallLogging:
    @pytest.fixture()
    def provider(self, tmp_path: Path) -> MockLLMProvider:
        return MockLLMProvider(log_dir=tmp_path)

    async def test_call_logged_to_jsonl(
        self, provider: MockLLMProvider, tmp_path: Path
    ) -> None:
        provider.set_response(SimpleResponse())
        await provider.generate(
            "test prompt",
            SimpleResponse,
            stage="PLACE_GLOBAL",
            attempt=2,
        )
        log_path = tmp_path / "llm_calls.jsonl"
        assert log_path.exists()
        lines = log_path.read_text().strip().split("\n")
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["stage"] == "PLACE_GLOBAL"
        assert record["attempt"] == 2
        assert record["role"] == "worker"

    async def test_log_has_required_fields(
        self, provider: MockLLMProvider, tmp_path: Path
    ) -> None:
        provider.set_response(SimpleResponse())
        await provider.generate(
            "prompt", SimpleResponse, stage="SYNTH", attempt=1
        )
        log_path = tmp_path / "llm_calls.jsonl"
        record = json.loads(log_path.read_text().strip())
        required = [
            "timestamp",
            "call_id",
            "model",
            "provider",
            "role",
            "stage",
            "attempt",
            "branch",
            "prompt_hash",
            "response_hash",
            "latency_ms",
            "tokens_in",
            "tokens_out",
        ]
        for field in required:
            assert field in record, f"Missing field: {field}"

    async def test_prompt_hash_deterministic(
        self, provider: MockLLMProvider, tmp_path: Path
    ) -> None:
        provider.set_response(SimpleResponse())
        await provider.generate("same prompt", SimpleResponse)
        await provider.generate("same prompt", SimpleResponse)
        log_path = tmp_path / "llm_calls.jsonl"
        lines = log_path.read_text().strip().split("\n")
        r1 = json.loads(lines[0])
        r2 = json.loads(lines[1])
        assert r1["prompt_hash"] == r2["prompt_hash"]

    async def test_response_hash_deterministic(
        self, provider: MockLLMProvider, tmp_path: Path
    ) -> None:
        provider.set_response(SimpleResponse(answer="fixed"))
        await provider.generate("p1", SimpleResponse)
        await provider.generate("p2", SimpleResponse)
        log_path = tmp_path / "llm_calls.jsonl"
        lines = log_path.read_text().strip().split("\n")
        r1 = json.loads(lines[0])
        r2 = json.loads(lines[1])
        assert r1["response_hash"] == r2["response_hash"]

    async def test_failure_logged(
        self, provider: MockLLMProvider, tmp_path: Path
    ) -> None:
        provider.set_failure(count=100)
        await provider.generate("prompt", SimpleResponse)
        log_path = tmp_path / "llm_calls.jsonl"
        record = json.loads(log_path.read_text().strip())
        assert record["error"] is not None
        assert record["structured_output_valid"] is False

    async def test_in_memory_records(
        self, provider: MockLLMProvider
    ) -> None:
        provider.set_response(SimpleResponse())
        await provider.generate(
            "prompt", SimpleResponse, stage="X", attempt=1
        )
        records = provider.call_records
        assert len(records) == 1
        assert records[0].stage == "X"

    async def test_latency_recorded(
        self, provider: MockLLMProvider, tmp_path: Path
    ) -> None:
        provider.set_response(SimpleResponse())
        await provider.generate("prompt", SimpleResponse)
        log_path = tmp_path / "llm_calls.jsonl"
        record = json.loads(log_path.read_text().strip())
        assert record["latency_ms"] >= 0

    async def test_token_counts_non_negative(
        self, provider: MockLLMProvider, tmp_path: Path
    ) -> None:
        provider.set_response(SimpleResponse())
        await provider.generate("prompt", SimpleResponse)
        log_path = tmp_path / "llm_calls.jsonl"
        record = json.loads(log_path.read_text().strip())
        assert record["tokens_in"] >= 0
        assert record["tokens_out"] >= 0

    async def test_no_log_dir_means_no_file(self) -> None:
        provider = MockLLMProvider()  # no log_dir
        provider.set_response(SimpleResponse())
        await provider.generate("prompt", SimpleResponse)
        # In-memory records still work
        assert len(provider.call_records) == 1
        assert provider.get_log_path() is None

    async def test_multiple_calls_append_to_same_file(
        self, provider: MockLLMProvider, tmp_path: Path
    ) -> None:
        provider.set_response(SimpleResponse())
        await provider.generate("p1", SimpleResponse)
        await provider.generate("p2", SimpleResponse)
        await provider.generate("p3", SimpleResponse)
        log_path = tmp_path / "llm_calls.jsonl"
        lines = log_path.read_text().strip().split("\n")
        assert len(lines) == 3


# ------------------------------------------------------------------ #
# Batch generate
# ------------------------------------------------------------------ #


class TestBatchGenerate:
    async def test_batch_returns_list(self, tmp_path: Path) -> None:
        provider = MockLLMProvider(log_dir=tmp_path)
        r1 = SimpleResponse(answer="a")
        r2 = SimpleResponse(answer="b")
        r3 = SimpleResponse(answer="c")
        provider.queue_responses(r1, r2, r3)
        results = await provider.batch_generate(
            ["p1", "p2", "p3"],
            SimpleResponse,
            stage="SYNTH",
            attempt=1,
        )
        assert len(results) == 3
        assert all(r is not None for r in results)

    async def test_batch_respects_concurrency(self, tmp_path: Path) -> None:
        provider = MockLLMProvider(log_dir=tmp_path)
        provider.set_response(SimpleResponse())
        results = await provider.batch_generate(
            ["p1", "p2"],
            SimpleResponse,
            max_concurrent=1,
        )
        assert len(results) == 2

    async def test_batch_partial_failures(self, tmp_path: Path) -> None:
        good = SimpleResponse(answer="ok")
        cfg = LLMConfig(
            structured_output=StructuredOutputConfig(max_retries=0)
        )
        p = MockLLMProvider(config=cfg, log_dir=tmp_path)
        p.queue_responses(good)
        p.queue_raw("invalid {{{")
        results = await p.batch_generate(["p1", "p2"], SimpleResponse)
        assert len(results) == 2
        # Order may vary due to asyncio.gather; check exactly one None
        non_none = [r for r in results if r is not None]
        nones = [r for r in results if r is None]
        assert len(non_none) == 1
        assert len(nones) == 1

    async def test_batch_logs_all_calls(self, tmp_path: Path) -> None:
        provider = MockLLMProvider(log_dir=tmp_path)
        provider.set_response(SimpleResponse())
        await provider.batch_generate(
            ["p1", "p2", "p3"],
            SimpleResponse,
            stage="SYNTH",
            attempt=1,
        )
        assert len(provider.call_records) == 3
        log_path = tmp_path / "llm_calls.jsonl"
        lines = log_path.read_text().strip().split("\n")
        assert len(lines) == 3


# ------------------------------------------------------------------ #
# Retry behaviour
# ------------------------------------------------------------------ #


class TestRetryBehavior:
    async def test_retry_on_parse_failure_then_succeed(
        self, tmp_path: Path
    ) -> None:
        provider = MockLLMProvider(log_dir=tmp_path)
        good = SimpleResponse(answer="recovered")
        # First response will fail to parse, second will succeed
        provider.queue_raw("not json")
        provider.queue_responses(good)
        result = await provider.generate("prompt", SimpleResponse)
        assert result is not None
        assert result.answer == "recovered"

    async def test_retry_exhaustion_returns_none(
        self, tmp_path: Path
    ) -> None:
        cfg = LLMConfig(
            structured_output=StructuredOutputConfig(max_retries=1)
        )
        p = MockLLMProvider(config=cfg, log_dir=tmp_path)
        p.queue_raw("bad1", "bad2")
        result = await p.generate("prompt", SimpleResponse)
        assert result is None

    async def test_retries_field_in_log(self, tmp_path: Path) -> None:
        provider = MockLLMProvider(log_dir=tmp_path)
        good = SimpleResponse(answer="ok")
        provider.queue_raw("bad")
        provider.queue_responses(good)
        await provider.generate("prompt", SimpleResponse)
        log_path = tmp_path / "llm_calls.jsonl"
        record = json.loads(log_path.read_text().strip())
        # One retry was used (first attempt failed, second succeeded)
        assert record["retries"] == 1

    async def test_zero_retries_fails_immediately(self) -> None:
        cfg = LLMConfig(
            structured_output=StructuredOutputConfig(max_retries=0)
        )
        p = MockLLMProvider(config=cfg)
        p.queue_raw("bad json")
        result = await p.generate("prompt", SimpleResponse)
        assert result is None
        assert p.call_count == 1

    async def test_connection_error_triggers_retry(
        self, tmp_path: Path
    ) -> None:
        provider = MockLLMProvider(log_dir=tmp_path)
        provider.set_response(SimpleResponse(answer="after_fail"))
        provider.set_failure(count=1, error="Connection refused")
        result = await provider.generate("prompt", SimpleResponse)
        assert result is not None
        assert result.answer == "after_fail"


# ------------------------------------------------------------------ #
# JSON extraction from code blocks
# ------------------------------------------------------------------ #


class TestJSONExtraction:
    async def test_extract_from_json_code_block(
        self, tmp_path: Path
    ) -> None:
        provider = MockLLMProvider(log_dir=tmp_path)
        json_str = SimpleResponse(answer="extracted").model_dump_json()
        wrapped = f"Here is the response:\n```json\n{json_str}\n```"
        provider.queue_raw(wrapped)
        result = await provider.generate("prompt", SimpleResponse)
        assert result is not None
        assert result.answer == "extracted"

    async def test_extract_from_plain_code_block(
        self, tmp_path: Path
    ) -> None:
        provider = MockLLMProvider(log_dir=tmp_path)
        json_str = SimpleResponse(answer="plain").model_dump_json()
        wrapped = f"```\n{json_str}\n```"
        provider.queue_raw(wrapped)
        result = await provider.generate("prompt", SimpleResponse)
        assert result is not None
        assert result.answer == "plain"

    async def test_no_code_block_parses_directly(
        self, tmp_path: Path
    ) -> None:
        provider = MockLLMProvider(log_dir=tmp_path)
        json_str = SimpleResponse(answer="direct").model_dump_json()
        provider.queue_raw(json_str)
        result = await provider.generate("prompt", SimpleResponse)
        assert result is not None
        assert result.answer == "direct"


# ------------------------------------------------------------------ #
# Robust parse response: JSON in markdown, field aliases, bare JSON
# ------------------------------------------------------------------ #


class ActionModel(BaseModel):
    """Model with an 'action' field for alias testing."""

    action: str = "retry"
    reason: str = ""
    confidence: float = 0.0


class TestRobustParseResponse:
    """Test enhanced _parse_response with fallback strategies."""

    async def test_json_embedded_in_markdown_text(self, tmp_path: Path) -> None:
        provider = MockLLMProvider(log_dir=tmp_path)
        raw = 'Here is my answer:\n\n{"answer": "found", "confidence": 0.9}\n\nHope that helps!'
        provider.queue_raw(raw)
        result = await provider.generate("prompt", SimpleResponse)
        assert result is not None
        assert result.answer == "found"

    async def test_field_alias_choice_to_action(self, tmp_path: Path) -> None:
        provider = MockLLMProvider(log_dir=tmp_path)
        raw = '{"choice": "stop", "reason": "done", "confidence": 0.95}'
        provider.queue_raw(raw)
        result = await provider.generate("prompt", ActionModel)
        assert result is not None
        assert result.action == "stop"

    async def test_field_alias_decision_to_action(self, tmp_path: Path) -> None:
        provider = MockLLMProvider(log_dir=tmp_path)
        raw = '{"decision": "rollback", "reasoning": "score plateau", "confidence": 0.8}'
        provider.queue_raw(raw)
        result = await provider.generate("prompt", ActionModel)
        assert result is not None
        assert result.action == "rollback"
        assert result.reason == "score plateau"

    async def test_json_in_markdown_with_surrounding_text(
        self, tmp_path: Path
    ) -> None:
        provider = MockLLMProvider(log_dir=tmp_path)
        raw = (
            "**Decision:** stop\n\n"
            '```json\n{"action": "stop", "reason": "unrecoverable", "confidence": 1.0}\n```\n\n'
            "That is my answer."
        )
        provider.queue_raw(raw)
        result = await provider.generate("prompt", ActionModel)
        assert result is not None
        assert result.action == "stop"

    async def test_bare_json_without_code_block(self, tmp_path: Path) -> None:
        provider = MockLLMProvider(log_dir=tmp_path)
        raw = '{"answer": "bare", "confidence": 0.5}'
        provider.queue_raw(raw)
        result = await provider.generate("prompt", SimpleResponse)
        assert result is not None
        assert result.answer == "bare"

    async def test_json_object_finder_with_nested_braces(
        self, tmp_path: Path
    ) -> None:
        provider = MockLLMProvider(log_dir=tmp_path)
        raw = 'Some text {"config_vars": {"FP_CORE_UTIL": 50.0}, "rationale": "test"} end'
        provider.queue_raw(raw)
        result = await provider.generate("prompt", PatchLikeResponse)
        assert result is not None
        assert result.config_vars["FP_CORE_UTIL"] == 50.0


# ------------------------------------------------------------------ #
# get_log_path
# ------------------------------------------------------------------ #


class TestGetLogPath:
    def test_with_log_dir(self, tmp_path: Path) -> None:
        provider = MockLLMProvider(log_dir=tmp_path)
        assert provider.get_log_path() == tmp_path / "llm_calls.jsonl"

    def test_without_log_dir(self) -> None:
        provider = MockLLMProvider()
        assert provider.get_log_path() is None


# ------------------------------------------------------------------ #
# Provider close
# ------------------------------------------------------------------ #


class TestProviderClose:
    async def test_close_is_noop_for_mock(self) -> None:
        provider = MockLLMProvider()
        await provider.close()  # should not raise


# ------------------------------------------------------------------ #
# Abstract base class
# ------------------------------------------------------------------ #


class TestLLMProviderAbstract:
    def test_cannot_instantiate_abstract(self) -> None:
        with pytest.raises(TypeError):
            LLMProvider(config=LLMConfig())  # type: ignore[abstract]
