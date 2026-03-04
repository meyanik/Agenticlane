"""Tests for the LiteLLM provider (agenticlane/agents/litellm_provider.py).

All tests monkeypatch litellm.acompletion so no real API calls are made.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import BaseModel

from agenticlane.agents.litellm_provider import LiteLLMProvider, _strip_think_tags
from agenticlane.config.models import LLMConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _SampleResponse(BaseModel):
    """Tiny structured-output model for tests."""

    action: str
    value: int


def _make_llm_config(**overrides: Any) -> LLMConfig:
    """Build an LLMConfig with sensible test defaults."""
    defaults: dict[str, Any] = {
        "provider": "litellm",
        "temperature": 0.0,
        "seed": 42,
    }
    defaults.update(overrides)
    return LLMConfig(**defaults)


def _fake_response(text: str, prompt_tokens: int = 10, completion_tokens: int = 20):
    """Build a fake litellm response object."""
    message = SimpleNamespace(content=text)
    choice = SimpleNamespace(message=message)
    usage = SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )
    return SimpleNamespace(choices=[choice], usage=usage)


# ---------------------------------------------------------------------------
# Tests: basic _call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_returns_text_and_tokens():
    """_call should return (text, prompt_tokens, completion_tokens)."""
    config = _make_llm_config()
    provider = LiteLLMProvider(config=config)

    fake_resp = _fake_response("hello", prompt_tokens=5, completion_tokens=15)

    with patch("agenticlane.agents.litellm_provider.litellm") as mock_litellm:
        mock_litellm.acompletion = AsyncMock(return_value=fake_resp)
        text, pin, pout = await provider._call(
            prompt="test", model="anthropic/claude-sonnet-4-20250514",
            temperature=0.0, seed=42,
        )

    assert text == "hello"
    assert pin == 5
    assert pout == 15


@pytest.mark.asyncio
async def test_call_passes_correct_params():
    """Verify model, temperature, seed are forwarded to litellm."""
    config = _make_llm_config()
    provider = LiteLLMProvider(config=config)

    fake_resp = _fake_response("ok")

    with patch("agenticlane.agents.litellm_provider.litellm") as mock_litellm:
        mock_litellm.acompletion = AsyncMock(return_value=fake_resp)
        await provider._call(
            prompt="my prompt",
            model="anthropic/claude-sonnet-4-20250514",
            temperature=0.7,
            seed=123,
        )

        call_kwargs = mock_litellm.acompletion.call_args
        assert call_kwargs.kwargs["model"] == "anthropic/claude-sonnet-4-20250514"
        assert call_kwargs.kwargs["temperature"] == 0.7
        assert call_kwargs.kwargs["seed"] == 123
        messages = call_kwargs.kwargs["messages"]
        # System message + user message
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1] == {"role": "user", "content": "my prompt"}
        # JSON output mode enforced
        assert call_kwargs.kwargs["response_format"] == {"type": "json_object"}


# ---------------------------------------------------------------------------
# Tests: model prefix routing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_model_prefix_routing_bare_name():
    """Bare model name gets 'anthropic/' prefix."""
    config = _make_llm_config()
    provider = LiteLLMProvider(config=config)
    assert provider._resolve_model("claude-sonnet-4-20250514") == "anthropic/claude-sonnet-4-20250514"


@pytest.mark.asyncio
async def test_model_prefix_routing_already_prefixed():
    """Model with provider prefix is unchanged."""
    config = _make_llm_config()
    provider = LiteLLMProvider(config=config)
    assert provider._resolve_model("openai/gpt-4o") == "openai/gpt-4o"


@pytest.mark.asyncio
async def test_model_prefix_routing_placeholder():
    """Placeholder model names get replaced with default."""
    config = _make_llm_config()
    provider = LiteLLMProvider(config=config)
    resolved = provider._resolve_model("model_worker")
    assert resolved == "gemini/gemini-2.5-pro"


@pytest.mark.asyncio
async def test_model_prefix_routing_custom_default():
    """Custom default_model is used for placeholders."""
    config = _make_llm_config()
    provider = LiteLLMProvider(config=config, default_model="openai/gpt-4o")
    resolved = provider._resolve_model("model_master")
    assert resolved == "openai/gpt-4o"


# ---------------------------------------------------------------------------
# Tests: token counting
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_token_counting_zero_usage():
    """Handle responses with no usage data gracefully."""
    config = _make_llm_config()
    provider = LiteLLMProvider(config=config)

    message = SimpleNamespace(content="test")
    choice = SimpleNamespace(message=message)
    fake_resp = SimpleNamespace(choices=[choice], usage=None)

    with patch("agenticlane.agents.litellm_provider.litellm") as mock_litellm:
        mock_litellm.acompletion = AsyncMock(return_value=fake_resp)
        text, pin, pout = await provider._call(
            prompt="test", model="anthropic/x", temperature=0.0, seed=42,
        )

    assert text == "test"
    assert pin == 0
    assert pout == 0


# ---------------------------------------------------------------------------
# Tests: structured output (via base class generate())
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_structured_output_json():
    """generate() should parse structured JSON responses into Pydantic models."""
    config = _make_llm_config()
    provider = LiteLLMProvider(config=config)

    payload = json.dumps({"action": "increase", "value": 42})
    fake_resp = _fake_response(payload)

    with patch("agenticlane.agents.litellm_provider.litellm") as mock_litellm:
        mock_litellm.acompletion = AsyncMock(return_value=fake_resp)
        result = await provider.generate(
            prompt="test",
            response_model=_SampleResponse,
            stage="synth",
        )

    assert result is not None
    assert result.action == "increase"
    assert result.value == 42


@pytest.mark.asyncio
async def test_structured_output_json_in_code_block():
    """generate() should extract JSON from markdown code blocks."""
    config = _make_llm_config()
    provider = LiteLLMProvider(config=config)

    payload = '```json\n{"action": "decrease", "value": 10}\n```'
    fake_resp = _fake_response(payload)

    with patch("agenticlane.agents.litellm_provider.litellm") as mock_litellm:
        mock_litellm.acompletion = AsyncMock(return_value=fake_resp)
        result = await provider.generate(
            prompt="test",
            response_model=_SampleResponse,
        )

    assert result is not None
    assert result.action == "decrease"
    assert result.value == 10


@pytest.mark.asyncio
async def test_structured_output_retry_on_bad_json():
    """generate() retries on malformed JSON before succeeding."""
    config = _make_llm_config()
    provider = LiteLLMProvider(config=config)

    bad_resp = _fake_response("not json at all")
    good_resp = _fake_response(json.dumps({"action": "fix", "value": 1}))

    with patch("agenticlane.agents.litellm_provider.litellm") as mock_litellm:
        mock_litellm.acompletion = AsyncMock(side_effect=[bad_resp, good_resp])
        result = await provider.generate(
            prompt="test",
            response_model=_SampleResponse,
        )

    assert result is not None
    assert result.action == "fix"


@pytest.mark.asyncio
async def test_structured_output_all_retries_exhausted():
    """generate() returns None when all retries produce bad JSON."""
    config = _make_llm_config()
    provider = LiteLLMProvider(config=config)

    bad_resp = _fake_response("bad json")

    with patch("agenticlane.agents.litellm_provider.litellm") as mock_litellm:
        mock_litellm.acompletion = AsyncMock(return_value=bad_resp)
        result = await provider.generate(
            prompt="test",
            response_model=_SampleResponse,
        )

    assert result is None


# ---------------------------------------------------------------------------
# Tests: retry on transient API errors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retry_on_transient_api_error():
    """generate() retries on transient exceptions."""
    config = _make_llm_config()
    provider = LiteLLMProvider(config=config)

    good_resp = _fake_response(json.dumps({"action": "ok", "value": 99}))

    with patch("agenticlane.agents.litellm_provider.litellm") as mock_litellm:
        mock_litellm.acompletion = AsyncMock(
            side_effect=[ConnectionError("transient"), good_resp]
        )
        result = await provider.generate(
            prompt="test",
            response_model=_SampleResponse,
        )

    assert result is not None
    assert result.value == 99


# ---------------------------------------------------------------------------
# Tests: call logging
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_records_logged(tmp_path):
    """generate() logs call records to in-memory list."""
    config = _make_llm_config()
    provider = LiteLLMProvider(config=config, log_dir=tmp_path)

    payload = json.dumps({"action": "log_test", "value": 7})
    fake_resp = _fake_response(payload, prompt_tokens=3, completion_tokens=8)

    with patch("agenticlane.agents.litellm_provider.litellm") as mock_litellm:
        mock_litellm.acompletion = AsyncMock(return_value=fake_resp)
        await provider.generate(
            prompt="test prompt",
            response_model=_SampleResponse,
            stage="floorplan",
            branch="B1",
            role="worker",
        )

    assert len(provider.call_records) == 1
    rec = provider.call_records[0]
    assert rec.stage == "floorplan"
    assert rec.branch == "B1"
    assert rec.role == "worker"
    assert rec.tokens_in == 3
    assert rec.tokens_out == 8
    assert rec.structured_output_valid is True

    # Check JSONL file was written
    log_path = tmp_path / "llm_calls.jsonl"
    assert log_path.exists()


@pytest.mark.asyncio
async def test_empty_content_returns_empty_string():
    """Handle None content from LLM response."""
    config = _make_llm_config()
    provider = LiteLLMProvider(config=config)

    message = SimpleNamespace(content=None)
    choice = SimpleNamespace(message=message)
    usage = SimpleNamespace(prompt_tokens=1, completion_tokens=0)
    fake_resp = SimpleNamespace(choices=[choice], usage=usage)

    with patch("agenticlane.agents.litellm_provider.litellm") as mock_litellm:
        mock_litellm.acompletion = AsyncMock(return_value=fake_resp)
        text, _, _ = await provider._call(
            prompt="test", model="anthropic/x", temperature=0.0, seed=42,
        )

    assert text == ""


# ---------------------------------------------------------------------------
# Tests: local LLM support (LM Studio / Ollama / vLLM)
# ---------------------------------------------------------------------------


def _make_local_config(**overrides: Any) -> LLMConfig:
    """Build an LLMConfig pointing to a local server."""
    defaults: dict[str, Any] = {
        "provider": "litellm",
        "temperature": 0.0,
        "seed": 42,
        "api_base": "http://127.0.0.1:1234/v1",
    }
    defaults.update(overrides)
    return LLMConfig(**defaults)


@pytest.mark.asyncio
async def test_local_call_passes_api_base():
    """Local mode passes api_base and api_key to litellm."""
    config = _make_local_config()
    provider = LiteLLMProvider(config=config)

    fake_resp = _fake_response('{"ok": true}')

    with patch("agenticlane.agents.litellm_provider.litellm") as mock_litellm:
        mock_litellm.acompletion = AsyncMock(return_value=fake_resp)
        await provider._call(
            prompt="test", model="qwen/qwen3-32b",
            temperature=0.0, seed=42,
        )

        call_kwargs = mock_litellm.acompletion.call_args.kwargs
        assert call_kwargs["api_base"] == "http://127.0.0.1:1234/v1"
        assert call_kwargs["api_key"] == "lm-studio"
        # Local mode should NOT include response_format (LM Studio rejects it)
        assert "response_format" not in call_kwargs


@pytest.mark.asyncio
async def test_local_call_no_response_format():
    """Local mode omits response_format (cloud mode includes it)."""
    config = _make_local_config()
    provider = LiteLLMProvider(config=config)

    fake_resp = _fake_response('{"action": "test", "value": 1}')

    with patch("agenticlane.agents.litellm_provider.litellm") as mock_litellm:
        mock_litellm.acompletion = AsyncMock(return_value=fake_resp)
        await provider._call(
            prompt="test", model="qwen/qwen3-32b",
            temperature=0.0, seed=42,
        )
        call_kwargs = mock_litellm.acompletion.call_args.kwargs
        assert "response_format" not in call_kwargs

    # Cloud mode DOES include response_format
    cloud_config = _make_llm_config()
    cloud_provider = LiteLLMProvider(config=cloud_config)

    with patch("agenticlane.agents.litellm_provider.litellm") as mock_litellm:
        mock_litellm.acompletion = AsyncMock(return_value=fake_resp)
        await cloud_provider._call(
            prompt="test", model="anthropic/claude-sonnet-4-20250514",
            temperature=0.0, seed=42,
        )
        call_kwargs = mock_litellm.acompletion.call_args.kwargs
        assert call_kwargs["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_local_strips_think_tags():
    """Local mode strips <think>...</think> from responses."""
    config = _make_local_config()
    provider = LiteLLMProvider(config=config)

    think_response = (
        '<think>\nOkay, the user wants JSON.\n'
        'Let me output that.\n</think>\n\n'
        '{"action": "fix", "value": 42}'
    )
    fake_resp = _fake_response(think_response)

    with patch("agenticlane.agents.litellm_provider.litellm") as mock_litellm:
        mock_litellm.acompletion = AsyncMock(return_value=fake_resp)
        text, _, _ = await provider._call(
            prompt="test", model="qwen/qwen3-32b",
            temperature=0.0, seed=42,
        )

    assert text == '{"action": "fix", "value": 42}'


@pytest.mark.asyncio
async def test_local_model_gets_openai_prefix():
    """Local mode prefixes model names with openai/ for litellm routing."""
    config = _make_local_config(
        models={"master": "qwen/qwen3-32b", "worker": "qwen/qwen3-32b",
                "judge": ["qwen/qwen3-32b"]},
    )
    provider = LiteLLMProvider(config=config)

    # Model without prefix gets openai/ prepended
    assert provider._resolve_model("qwen/qwen3-32b") == "openai/qwen/qwen3-32b"
    # Model already with openai/ stays the same
    assert provider._resolve_model("openai/gpt-4o") == "openai/gpt-4o"
    # Placeholder resolves to default model, which gets openai/ prefix in local mode
    assert provider._resolve_model("model_worker") == "openai/qwen/qwen3-32b"
    # Empty string also resolves to default
    assert provider._resolve_model("") == "openai/qwen/qwen3-32b"


@pytest.mark.asyncio
async def test_local_model_with_custom_default():
    """Local mode with custom default_model resolves correctly."""
    config = _make_local_config()
    provider = LiteLLMProvider(
        config=config, default_model="openai/qwen/qwen3-32b"
    )

    assert provider._resolve_model("model_worker") == "openai/qwen/qwen3-32b"
    assert provider._resolve_model("pentagoniac-semikong-70b") == \
        "openai/pentagoniac-semikong-70b"


# ---------------------------------------------------------------------------
# Tests: _strip_think_tags
# ---------------------------------------------------------------------------


def test_strip_think_tags_basic():
    """Strips simple think tags."""
    text = "<think>reasoning here</think>\n{\"a\": 1}"
    assert _strip_think_tags(text) == '{"a": 1}'


def test_strip_think_tags_multiline():
    """Strips multiline think blocks."""
    text = (
        "<think>\nStep 1: analyze\n"
        "Step 2: decide\n</think>\n\n"
        '{"result": "done"}'
    )
    assert _strip_think_tags(text) == '{"result": "done"}'


def test_strip_think_tags_no_tags():
    """No-op when there are no think tags."""
    text = '{"clean": true}'
    assert _strip_think_tags(text) == '{"clean": true}'


def test_strip_think_tags_empty():
    """Handles empty string."""
    assert _strip_think_tags("") == ""


def test_strip_think_tags_only_tags():
    """Returns empty when input is only think tags."""
    assert _strip_think_tags("<think>just thinking</think>") == ""
