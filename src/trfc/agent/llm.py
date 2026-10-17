"""Wrapper gọi LLM — chủ sở hữu: B. Mọi chỗ gọi model đi qua ĐÂY.

Yêu cầu 2.4: retry + timeout + log lỗi HTTP.
GV đọc đúng 1 hàm này khi vấn đáp — nên nó phải là chỗ duy nhất có `client.chat`.

ponytail: chưa cài đặt. Đừng rải `OpenAI(...)` ra nhiều file; thêm retry bằng
vòng lặp + `time.sleep(2**attempt)`, chưa cần thư viện backoff.
"""

from dataclasses import dataclass
import asyncio
import os
import sys
import time
from dotenv import load_dotenv
from groq import Groq, GroqError

try:
    from openai import OpenAI, APIError as OpenAIAPIError
except ImportError:
    OpenAI = None
    OpenAIAPIError = type("OpenAIAPIError", (Exception,), {})

DEFAULT_MODEL_NAME = "qwen/qwen3.8-27b"
MODEL_NAME = DEFAULT_MODEL_NAME

# Vietnamese is token-heavy (~2.5 tokens/word), so a refusal answer with citations
# runs 700-900 completion tokens. 650 cut answers mid-sentence.
DEFAULT_MAX_TOKENS = 2048

client = None


@dataclass(frozen=True)
class LLMConfig:
    """Resolved configuration for the active LLM provider."""

    provider: str
    model: str
    api_key: str
    base_url: str | None
    timeout_seconds: float = 30.0
    max_retries: int = 3
    max_tokens: int = DEFAULT_MAX_TOKENS


def resolve_llm_config() -> LLMConfig:
    """Resolve provider configuration from environment variables without hardcoded machine defaults."""
    load_dotenv()
    provider_env = (os.getenv("LLM_PROVIDER") or "").strip().lower()
    base_url = (os.getenv("LLM_BASE_URL") or "").strip() or None
    dashscope_key = (os.getenv("DASHSCOPE_API_KEY") or "").strip()
    groq_key = (os.getenv("GROQ_API_KEY") or "").strip()
    llm_api_key = (os.getenv("LLM_API_KEY") or "").strip()
    deepseek_key = (os.getenv("DEEPSEEK_API_KEY") or "").strip()
    openai_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    model_env = (os.getenv("LLM_MODEL") or "").strip()

    # Determine provider
    if provider_env:
        if provider_env in {"groq"}:
            provider = "groq"
        elif provider_env in {"deepseek"}:
            provider = "deepseek"
        elif provider_env in {"dashscope"}:
            provider = "dashscope"
        elif provider_env in {"openai", "custom", "vilao"}:
            provider = "custom"
        else:
            raise RuntimeError(
                f"Unsupported LLM_PROVIDER: {provider_env!r}. "
                "Supported providers: groq, deepseek, custom, openai, dashscope"
            )
    else:
        # Automatic discovery with explicit documented precedence:
        # 1. Custom / OpenAI-compatible gateway (LLM_BASE_URL)
        # 2. DashScope key (DASHSCOPE_API_KEY)
        # 3. DeepSeek key (DEEPSEEK_API_KEY) or DeepSeek model
        # 4. Groq key (GROQ_API_KEY)
        # 5. Qwen non-Groq model
        # 6. Generic LLM_API_KEY fallback
        if base_url:
            if "deepseek.com" in base_url or ("deepseek" in model_env.lower() and "vilao" not in base_url):
                provider = "deepseek"
            else:
                provider = "custom"
        elif dashscope_key:
            provider = "dashscope"
        elif deepseek_key or "deepseek" in model_env.lower():
            provider = "deepseek"
        elif "qwen" in model_env.lower() and not model_env.startswith("qwen/"):
            provider = "custom"
        elif groq_key:
            provider = "groq"
        elif model_env:
            provider = "groq"
        elif llm_api_key:
            provider = "groq"
        else:
            raise RuntimeError(
                "No valid LLM provider configured. Please set GROQ_API_KEY for Groq, "
                "or LLM_BASE_URL and LLM_API_KEY for DeepSeek/custom OpenAI-compatible gateway, "
                "or specify LLM_PROVIDER."
            )

    # Provider-specific credentials and endpoint resolution
    if provider == "groq":
        api_key = groq_key or llm_api_key
        if not api_key:
            raise RuntimeError("Missing GROQ_API_KEY (or fallback LLM_API_KEY) for Groq provider")
        model = model_env or DEFAULT_MODEL_NAME
        resolved_base = None
    elif provider == "deepseek":
        api_key = deepseek_key or llm_api_key or openai_key
        if not api_key:
            raise RuntimeError("Missing API key for DeepSeek provider: set LLM_API_KEY or DEEPSEEK_API_KEY")
        model = model_env or "deepseek-chat"
        resolved_base = base_url or "https://api.deepseek.com/v1"
    elif provider == "dashscope":
        api_key = dashscope_key or llm_api_key or openai_key
        if not api_key:
            raise RuntimeError("Missing API key for DashScope provider: set DASHSCOPE_API_KEY or LLM_API_KEY")
        model = model_env or "qwen-plus"
        resolved_base = base_url or "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    elif provider == "custom":
        api_key = llm_api_key or dashscope_key or openai_key
        if not api_key:
            if not groq_key:
                raise RuntimeError("Missing GROQ_API_KEY (or fallback LLM_API_KEY)")
            raise RuntimeError(
                "Missing API key for Qwen / custom provider: set LLM_API_KEY or DASHSCOPE_API_KEY"
            )
        if not base_url:
            raise RuntimeError("Missing LLM_BASE_URL for custom provider: silent fallback to Groq is blocked")
        model = model_env or DEFAULT_MODEL_NAME
        resolved_base = base_url
    else:
        raise RuntimeError(f"Unknown provider: {provider}")

    # Timeout
    timeout_str = os.getenv("LLM_TIMEOUT_SECONDS", "30.0")
    try:
        timeout_seconds = float(timeout_str)
    except ValueError:
        timeout_seconds = 30.0

    # Max retries
    retries_str = os.getenv("LLM_MAX_RETRIES", "3")
    try:
        max_retries = int(retries_str)
        if max_retries < 1:
            max_retries = 3
    except ValueError:
        max_retries = 3

    # Max tokens
    tokens_str = os.getenv("LLM_MAX_TOKENS", str(DEFAULT_MAX_TOKENS))
    try:
        max_tokens = int(tokens_str)
    except ValueError:
        max_tokens = DEFAULT_MAX_TOKENS

    return LLMConfig(
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=resolved_base,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        max_tokens=max_tokens,
    )


def _get_client():
    """Load credentials only when a request is actually made."""
    global client
    if client is None:
        config = resolve_llm_config()
        if config.provider == "groq":
            client = Groq(api_key=config.api_key, max_retries=0)
        else:
            if OpenAI is None:
                raise RuntimeError("openai package is required for OpenAI-compatible / custom base URL provider")
            client = OpenAI(api_key=config.api_key, base_url=config.base_url, max_retries=0)
    return client


@dataclass
class Usage:
    """Provider usage for one model turn; unknown token counts remain None."""

    calls: int = 0
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    max_prompt: int | None = None


class LLMRequestError(RuntimeError):
    """Request failure with the number of calls attempted by this wrapper."""

    def __init__(self, message: str, calls: int):
        super().__init__(message)
        self.calls = calls


def call_llm(
    messages: list[dict],
    tools: list[dict] | None = None,
    *,
    request_client=None,
    max_retries: int = 3,
    retry_delay: float = 2.0,
):
    """Return Groq's structured assistant message and provider usage.

    The request client can be injected for deterministic tests. SDK-level
    retries are disabled for the default client so ``Usage.calls`` reflects
    requests issued by this wrapper rather than hidden SDK retries.
    """
    env_retries = os.getenv("LLM_MAX_RETRIES")
    if env_retries and env_retries.isdigit():
        max_retries = int(env_retries)
    if max_retries < 1:
        raise ValueError("max_retries must be at least 1")
    timeout_seconds = 30.0
    env_timeout = os.getenv("LLM_TIMEOUT_SECONDS")
    if env_timeout:
        try:
            timeout_seconds = float(env_timeout)
        except ValueError:
            pass
    calls = 0
    active_client = request_client or _get_client()
    model_name = os.getenv("LLM_MODEL") or MODEL_NAME

    base_url_hint = os.getenv("LLM_BASE_URL", "")
    provider_env = os.getenv("LLM_PROVIDER", "").lower()
    if "vilao.ai" in base_url_hint or provider_env == "vilao":
        provider_tag = "VILAO"
    elif "dashscope" in base_url_hint or "aliyun" in base_url_hint or provider_env == "dashscope":
        provider_tag = "DASHSCOPE"
    elif "deepseek" in base_url_hint or "deepseek" in model_name.lower() or provider_env == "deepseek":
        provider_tag = "DEEPSEEK"
    elif OpenAI is not None and isinstance(active_client, OpenAI):
        provider_tag = "OPENAI/CUSTOM"
    else:
        provider_tag = "GROQ"

    for attempt in range(1, max_retries + 1):
        try:
            kwargs = {
                "model": model_name,
                "messages": messages,
                "timeout": timeout_seconds,
                "temperature": 0.0,
            }
            max_tokens_env = os.getenv("LLM_MAX_TOKENS")
            if max_tokens_env and max_tokens_env.isdigit():
                kwargs["max_tokens"] = int(max_tokens_env)
            else:
                kwargs["max_tokens"] = DEFAULT_MAX_TOKENS

            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"

            # ĐIỂM DUY NHẤT GỌI CLIENT.CHAT TRONG TOÀN BỘ PROJECT
            calls += 1
            response = active_client.chat.completions.create(**kwargs)

            provider_usage = getattr(response, "usage", None)
            prompt_tokens = getattr(provider_usage, "prompt_tokens", None)
            completion_tokens = getattr(provider_usage, "completion_tokens", None)
            usage_stats = Usage(
                calls=calls,
                prompt_tokens=prompt_tokens if type(prompt_tokens) is int and prompt_tokens >= 0 else None,
                completion_tokens=(completion_tokens if type(completion_tokens) is int
                                   and completion_tokens >= 0 else None),
                max_prompt=prompt_tokens if type(prompt_tokens) is int and prompt_tokens >= 0 else None,
            )
            if calls > 1:
                # Failed retries may have reached the provider but returned no
                # usage record, so the request-level token totals are incomplete.
                usage_stats.prompt_tokens = None
                usage_stats.completion_tokens = None
                usage_stats.max_prompt = None
            if not getattr(response, "choices", None):
                raise ValueError(f"{provider_tag} returned no completion choices")
            message = getattr(response.choices[0], "message", None)
            if message is None:
                raise ValueError(f"{provider_tag} returned no assistant message")
            if getattr(response.choices[0], "finish_reason", None) == "length":
                print(
                    f"[LLM {provider_tag} WARN] output hit max_tokens={kwargs['max_tokens']}; "
                    "answer is truncated. Raise LLM_MAX_TOKENS.",
                    file=sys.stderr,
                    flush=True,
                )
            return message, usage_stats

        except (GroqError, OpenAIAPIError) as e:
            provider_tag = "OPENAI/CUSTOM" if isinstance(e, OpenAIAPIError) else "GROQ"
            base_url_hint = os.getenv("LLM_BASE_URL", "")
            provider_env = os.getenv("LLM_PROVIDER", "").lower()
            if "vilao.ai" in base_url_hint or provider_env == "vilao":
                provider_tag = "VILAO"
            elif "dashscope" in base_url_hint or "aliyun" in base_url_hint or provider_env == "dashscope":
                provider_tag = "DASHSCOPE"
            elif "deepseek" in base_url_hint or provider_env == "deepseek":
                provider_tag = "DEEPSEEK"

            print(
                f"[LLM {provider_tag} ERROR] Attempt {attempt}/{max_retries} failed: {type(e).__name__}",
                file=sys.stderr,
                flush=True,
            )
            status_code = getattr(e, "status_code", None)
            is_rate_limit = (type(e).__name__ == "RateLimitError") or (status_code == 429)

            # Check for non-retryable 4xx errors (e.g. 401 unauthorized, 403 forbidden, quota exhausted, 413 payload too large)
            err_str = str(e)
            is_413 = (status_code == 413) or ("413" in err_str) or ("payload too large" in err_str.lower()) or ("entity too large" in err_str.lower())
            if is_413 and not is_rate_limit:
                raise LLMRequestError(
                    f"LLM call failed with 413 Payload Too Large (no retry): {type(e).__name__}: {e}", calls
                ) from e

            # Check for permanent quota exhaustion or unrecoverable account credits in 429/403/402
            is_quota_exhausted = (
                "insufficient_quota" in err_str.lower()
                or "quota_exhausted" in err_str.lower()
                or "credit exhausted" in err_str.lower()
                or "billing" in err_str.lower()
                or "account deactivated" in err_str.lower()
                or "access denied" in err_str.lower()
            )
            if is_quota_exhausted:
                raise LLMRequestError(
                    f"LLM call failed with non-retryable account/quota error: {type(e).__name__}: {e}", calls
                ) from e

            # Non-retryable auth / permission errors (401, 403 when not rate-limited)
            is_auth_error = (status_code in {401, 403} or type(e).__name__ in {"AuthenticationError", "PermissionDeniedError"}) and not is_rate_limit
            if is_auth_error:
                raise LLMRequestError(
                    f"LLM call failed with non-retryable authentication/permission error: {type(e).__name__}", calls
                ) from e

            if attempt == max_retries:
                raise LLMRequestError(
                    f"LLM call failed after {max_retries} attempts: {type(e).__name__}: {e}", calls
                ) from e

            # Bounded exponential backoff with jitter
            import random
            jitter = random.uniform(0.1, 1.0)
            base_backoff = retry_delay * (2 ** (attempt - 1)) + jitter

            sleep_time = min(base_backoff, 60.0)
            if is_rate_limit:
                # 1. Check Retry-After or ratelimit-reset headers if present on HTTP response
                resp = getattr(e, "response", None)
                header_retry = None
                if resp is not None and getattr(resp, "headers", None):
                    headers = resp.headers
                    for h in ("retry-after", "Retry-After", "ratelimit-reset", "x-ratelimit-reset"):
                        if h in headers:
                            val = headers[h]
                            try:
                                header_retry = float(val)
                                break
                            except (ValueError, TypeError):
                                pass

                if header_retry is not None and header_retry > 0:
                    sleep_time = header_retry + jitter
                else:
                    # 2. Check text message patterns (e.g. Groq "try again in 1m23.4s")
                    import re
                    match = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", err_str, re.IGNORECASE)
                    if match:
                        minutes = float(match.group(1)) if match.group(1) else 0.0
                        seconds = float(match.group(2))
                        raw_sleep = minutes * 60 + seconds + jitter
                        sleep_time = raw_sleep
                    elif "otpm" in err_str.lower() or "output tokens per minute" in err_str.lower():
                        sleep_time = max(base_backoff, 35.0) + jitter
                    else:
                        sleep_time = max(base_backoff, 15.0) + jitter

                if sleep_time > 90.0:
                    raise LLMRequestError(
                        f"Rate limit cooldown too long ({sleep_time:.1f}s > 90s): {err_str}", calls
                    ) from e

                print(
                    f"[LLM {provider_tag} RATE LIMIT] Pausing {sleep_time:.1f}s for rate limit window...",
                    file=sys.stderr,
                    flush=True,
                )
            time.sleep(sleep_time)

        except Exception as e:
            provider_tag = "CUSTOM" if os.getenv("LLM_BASE_URL") else "GROQ"
            print(
                f"[LLM {provider_tag} UNEXPECTED ERROR] Attempt {attempt}/{max_retries} failed: {type(e).__name__}",
                file=sys.stderr,
                flush=True,
            )
            if attempt == max_retries:
                raise LLMRequestError(
                    f"Unexpected LLM call failure: {type(e).__name__}", calls
                ) from e
            import random
            time.sleep(retry_delay * (2 ** (attempt - 1)) + random.uniform(0.1, 0.5))

    raise LLMRequestError("LLM call failed without a response", calls)


async def call_llm_async(messages: list[dict], tools: list[dict] | None = None):
    """Run the synchronous provider wrapper off the event loop.

    Cancelling the await does not stop the worker thread or an in-flight HTTP
    request; evaluator timeouts therefore bound the async caller, not provider
    work already running in the thread.
    """
    return await asyncio.to_thread(call_llm, messages, tools)
