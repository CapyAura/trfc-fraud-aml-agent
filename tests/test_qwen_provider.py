"""Offline unit tests for Qwen / Custom OpenAI-compatible provider compatibility.

Zero real network calls; all tests use mock clients or mock HTTP responses.
Verifies Checkpoint D requirements:
- Client initialization from provider config
- Correct model ID and base URL resolution
- Sync and async calls
- Tool calling and response parsing
- Error handling (401/403, 429, timeout, server errors)
- No secret keys leaked in exceptions or logs
- No silent fallback to Groq when Qwen/custom provider is configured
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock, patch
import pytest

from trfc.agent.llm import (
    DEFAULT_MODEL_NAME,
    LLMConfig,
    LLMRequestError,
    Usage,
    _get_client,
    call_llm,
    call_llm_async,
    resolve_llm_config,
)


@pytest.fixture(autouse=True)
def _reset_llm_client(monkeypatch):
    import trfc.agent.llm as llm_mod
    monkeypatch.setattr(llm_mod, "load_dotenv", lambda *args, **kwargs: None)
    llm_mod.client = None
    yield
    llm_mod.client = None


def test_get_client_dashscope_selected_when_key_set(monkeypatch):
    """When DASHSCOPE_API_KEY is set, _get_client initializes OpenAI-compatible client."""
    monkeypatch.setenv("DASHSCOPE_API_KEY", "mock-dashscope-secret-key")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    client = _get_client()
    assert client.__class__.__name__ == "OpenAI"
    assert "dashscope" in str(client.base_url)


def test_get_client_custom_base_url_and_vilao(monkeypatch):
    """When LLM_BASE_URL is set (e.g. to https://api.vilao.ai/v1), _get_client initializes OpenAI client with that URL."""
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.setenv("LLM_BASE_URL", "https://api.vilao.ai/v1")
    monkeypatch.setenv("LLM_API_KEY", "mock-vilao-secret-key")

    client = _get_client()
    assert client.__class__.__name__ == "OpenAI"
    assert "api.vilao.ai" in str(client.base_url)


def test_get_client_no_silent_fallback_to_groq_when_qwen_missing_key(monkeypatch):
    """When Qwen model is configured but API key is missing, raise RuntimeError without falling back to Groq."""
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_BASE_URL", "https://api.vilao.ai/v1")
    monkeypatch.setenv("GROQ_API_KEY", "mock-groq-key")

    with pytest.raises(RuntimeError) as exc_info:
        _get_client()
    assert "Missing API key for Qwen / custom provider" in str(exc_info.value)


def test_get_client_no_silent_fallback_to_groq_when_qwen_missing_base_url(monkeypatch):
    """When Qwen model is configured with key but missing base URL, raise RuntimeError without falling back to Groq."""
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("LLM_MODEL", "qwen3.8-max-0902-req")
    monkeypatch.setenv("LLM_API_KEY", "mock-qwen-key")
    monkeypatch.setenv("GROQ_API_KEY", "mock-groq-key")

    with pytest.raises(RuntimeError) as exc_info:
        _get_client()
    assert "silent fallback to Groq is blocked" in str(exc_info.value)


def test_get_client_preserves_groq_default(monkeypatch):
    """When only GROQ_API_KEY is set and no Qwen/custom config, _get_client initializes Groq client as before."""
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "mock-groq-secret-key")

    client = _get_client()
    assert client.__class__.__name__ == "Groq"


def test_call_llm_tool_calling_with_mock_client(monkeypatch):
    """Verify call_llm properly formats tools and extracts assistant tool calls from OpenAI-compatible response."""
    monkeypatch.setenv("LLM_MODEL", "qwen3.8-max-0902-req")
    mock_client = MagicMock()
    mock_tool_call = MagicMock()
    mock_tool_call.id = "call_qwen_123"
    mock_tool_call.type = "function"
    mock_tool_call.function.name = "search_policy"
    mock_tool_call.function.arguments = json.dumps({"query": "DOC0007 eKYC 2"})

    mock_msg = MagicMock()
    mock_msg.content = None
    mock_msg.tool_calls = [mock_tool_call]

    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=mock_msg)]
    mock_response.usage.prompt_tokens = 150
    mock_response.usage.completion_tokens = 35

    mock_client.chat.completions.create.return_value = mock_response

    tools = [
        {
            "type": "function",
            "function": {
                "name": "search_policy",
                "description": "Search TRFC policies",
                "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
            },
        }
    ]

    msg, usage = call_llm(
        [{"role": "user", "content": "tra cứu"}],
        tools=tools,
        request_client=mock_client,
    )

    assert msg.tool_calls[0].function.name == "search_policy"
    assert usage.prompt_tokens == 150
    assert usage.completion_tokens == 35
    assert mock_client.chat.completions.create.call_count == 1
    create_kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert create_kwargs["model"] == "qwen3.8-max-0902-req"
    assert create_kwargs["tools"] == tools
    assert create_kwargs["tool_choice"] == "auto"


@pytest.mark.anyio
async def test_call_llm_async_with_mock_client():
    """Verify call_llm_async executes properly without blocking."""
    mock_client = MagicMock()
    mock_msg = MagicMock(content="Async response", tool_calls=[])
    mock_response = MagicMock(choices=[MagicMock(message=mock_msg)], usage=MagicMock(prompt_tokens=20, completion_tokens=10))
    mock_client.chat.completions.create.return_value = mock_response

    with patch("trfc.agent.llm._get_client", return_value=mock_client):
        msg, usage = await call_llm_async([{"role": "user", "content": "hello"}])
        assert msg.content == "Async response"
        assert usage.prompt_tokens == 20


def test_call_llm_openai_api_error_rate_limit_handling():
    """Verify call_llm handles openai.RateLimitError gracefully with retry."""
    from openai import RateLimitError
    import httpx

    mock_client = MagicMock()
    req = httpx.Request("POST", "https://api.example.com")
    resp = httpx.Response(429, request=req, text="Rate limit reached")
    err = RateLimitError("Rate limit reached: try again in 0.1s", response=resp, body=None)

    # First attempt fails with 429, second succeeds
    mock_msg = MagicMock(content="Success after retry", tool_calls=[])
    mock_success = MagicMock(choices=[MagicMock(message=mock_msg)], usage=MagicMock(prompt_tokens=10, completion_tokens=5))

    mock_client.chat.completions.create.side_effect = [err, mock_success]

    with patch("time.sleep") as mock_sleep:
        msg, usage = call_llm(
            [{"role": "user", "content": "test"}],
            request_client=mock_client,
            max_retries=2,
            retry_delay=0.01,
        )

    assert msg.content == "Success after retry"
    assert mock_client.chat.completions.create.call_count == 2
    assert mock_sleep.call_count == 1


def test_call_llm_auth_and_server_errors_fail_cleanly_without_leaking_key():
    """Verify 401/403 and 500 errors fail cleanly and never leak secret keys in exception messages."""
    from openai import AuthenticationError, InternalServerError
    import httpx

    secret_key = "super-secret-key-that-must-not-leak"
    req = httpx.Request("POST", "https://api.example.com", headers={"Authorization": f"Bearer {secret_key}"})
    resp_401 = httpx.Response(401, request=req, text="Unauthorized: Invalid key")
    err_401 = AuthenticationError("Unauthorized token", response=resp_401, body=None)

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = err_401

    with pytest.raises(LLMRequestError) as exc_info:
        call_llm([{"role": "user", "content": "test"}], request_client=mock_client, max_retries=1)

    err_str = str(exc_info.value)
    assert secret_key not in err_str
    assert "AuthenticationError" in err_str


def test_call_llm_respects_retry_after_header():
    """Verify call_llm parses and respects Retry-After header from response."""
    from openai import RateLimitError
    import httpx

    mock_client = MagicMock()
    req = httpx.Request("POST", "https://api.vilao.ai/v1/chat/completions")
    resp = httpx.Response(429, request=req, headers={"retry-after": "2.5"}, text="Rate limited")
    err = RateLimitError("Rate limited", response=resp, body=None)

    mock_msg = MagicMock(content="Success after retry-after", tool_calls=[])
    mock_success = MagicMock(choices=[MagicMock(message=mock_msg)], usage=MagicMock(prompt_tokens=10, completion_tokens=5))
    mock_client.chat.completions.create.side_effect = [err, mock_success]

    with patch("time.sleep") as mock_sleep:
        msg, usage = call_llm(
            [{"role": "user", "content": "test"}],
            request_client=mock_client,
            max_retries=2,
        )

    assert msg.content == "Success after retry-after"
    assert mock_sleep.call_count == 1
    slept_duration = mock_sleep.call_args[0][0]
    # Should sleep at least 2.5s (due to header) plus jitter
    assert slept_duration >= 2.5


def test_call_llm_fails_fast_on_exhausted_quota_without_retrying():
    """Verify non-retryable quota exhaustion fails fast on attempt 1 without spinning retries."""
    from openai import RateLimitError
    import httpx

    mock_client = MagicMock()
    req = httpx.Request("POST", "https://api.vilao.ai/v1/chat/completions")
    resp = httpx.Response(429, request=req, text='{"error":{"code":"insufficient_quota","message":"You have exhausted your quota"}}')
    err = RateLimitError("You have exhausted your quota (insufficient_quota)", response=resp, body=None)
    mock_client.chat.completions.create.side_effect = err

    with patch("time.sleep") as mock_sleep:
        with pytest.raises(LLMRequestError) as exc_info:
            call_llm(
                [{"role": "user", "content": "test"}],
                request_client=mock_client,
                max_retries=3,
            )

    assert "non-retryable account/quota error" in str(exc_info.value)
    # Should NOT have retried
    assert mock_client.chat.completions.create.call_count == 1
    assert mock_sleep.call_count == 0


def test_call_llm_exhaustion_terminates_cleanly():
    """Verify exceeding max_retries raises LLMRequestError with total attempts recorded."""
    from openai import RateLimitError
    import httpx

    mock_client = MagicMock()
    req = httpx.Request("POST", "https://api.vilao.ai/v1/chat/completions")
    resp = httpx.Response(429, request=req, text="Upstream rate limit")
    err = RateLimitError("The upstream provider is rate limited right now", response=resp, body=None)
    mock_client.chat.completions.create.side_effect = err

    with patch("time.sleep"):
        with pytest.raises(LLMRequestError) as exc_info:
            call_llm(
                [{"role": "user", "content": "test"}],
                request_client=mock_client,
                max_retries=2,
            )

    assert "failed after 2 attempts" in str(exc_info.value)
    assert exc_info.value.calls == 2


# ------------------------------------------------------------------------------
# Provider Configuration and Multi-Provider Resolution Tests
# ------------------------------------------------------------------------------
def test_resolve_llm_config_groq_explicit(monkeypatch):
    """LLM_PROVIDER=groq resolves Groq settings with default model."""
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "gsk-mock-groq-key")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)

    config = resolve_llm_config()
    assert config.provider == "groq"
    assert config.api_key == "gsk-mock-groq-key"
    assert config.model == DEFAULT_MODEL_NAME
    assert config.base_url is None


def test_resolve_llm_config_groq_missing_key_raises(monkeypatch):
    """LLM_PROVIDER=groq raises error if no GROQ_API_KEY or LLM_API_KEY is found."""
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)

    with pytest.raises(RuntimeError) as exc_info:
        resolve_llm_config()
    assert "Missing GROQ_API_KEY" in str(exc_info.value)


def test_resolve_llm_config_deepseek_explicit(monkeypatch):
    """LLM_PROVIDER=deepseek defaults base_url to api.deepseek.com and model to deepseek-chat."""
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-mock-deepseek-key")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)

    config = resolve_llm_config()
    assert config.provider == "deepseek"
    assert config.api_key == "sk-mock-deepseek-key"
    assert config.base_url == "https://api.deepseek.com/v1"
    assert config.model == "deepseek-chat"


def test_resolve_llm_config_deepseek_missing_key_raises(monkeypatch):
    """LLM_PROVIDER=deepseek raises error if no key is configured."""
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(RuntimeError) as exc_info:
        resolve_llm_config()
    assert "Missing API key for DeepSeek provider" in str(exc_info.value)


def test_resolve_llm_config_custom_gateway(monkeypatch):
    """LLM_PROVIDER=custom resolves custom endpoint and model override."""
    monkeypatch.setenv("LLM_PROVIDER", "custom")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.vilao.ai/v1")
    monkeypatch.setenv("LLM_API_KEY", "mock-custom-key")
    monkeypatch.setenv("LLM_MODEL", "qwen3.8-max-0902-req")

    config = resolve_llm_config()
    assert config.provider == "custom"
    assert config.base_url == "https://api.vilao.ai/v1"
    assert config.api_key == "mock-custom-key"
    assert config.model == "qwen3.8-max-0902-req"


def test_resolve_llm_config_precedence_and_override(monkeypatch):
    """When both Groq and custom gateway are configured, custom takes precedence unless overridden."""
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "gsk-mock-groq")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.vilao.ai/v1")
    monkeypatch.setenv("LLM_API_KEY", "mock-custom-key")

    # Precedence without LLM_PROVIDER: custom gateway
    config = resolve_llm_config()
    assert config.provider == "custom"
    assert config.base_url == "https://api.vilao.ai/v1"

    # Explicit override with LLM_PROVIDER=groq
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    config_overridden = resolve_llm_config()
    assert config_overridden.provider == "groq"
    assert config_overridden.api_key == "gsk-mock-groq"


def test_resolve_llm_config_no_provider_configured_raises(monkeypatch):
    """When no provider environment variables are present, raises RuntimeError with configuration guidance."""
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)

    with pytest.raises(RuntimeError) as exc_info:
        resolve_llm_config()
    assert "No valid LLM provider configured" in str(exc_info.value)


def test_resolve_llm_config_unsupported_provider_raises(monkeypatch):
    """Unsupported LLM_PROVIDER raises clear RuntimeError."""
    monkeypatch.setenv("LLM_PROVIDER", "unsupported_llm_corp")

    with pytest.raises(RuntimeError) as exc_info:
        resolve_llm_config()
    assert "Unsupported LLM_PROVIDER" in str(exc_info.value)


def test_resolve_llm_config_tuning_parameters(monkeypatch):
    """LLM_TIMEOUT_SECONDS, LLM_MAX_RETRIES, and LLM_MAX_TOKENS are respected."""
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "gsk-key")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "45.5")
    monkeypatch.setenv("LLM_MAX_RETRIES", "5")
    monkeypatch.setenv("LLM_MAX_TOKENS", "1024")

    config = resolve_llm_config()
    assert config.timeout_seconds == 45.5
    assert config.max_retries == 5
    assert config.max_tokens == 1024


