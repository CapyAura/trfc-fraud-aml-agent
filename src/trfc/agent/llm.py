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

DEFAULT_MODEL_NAME = "qwen/qwen3.8-27b"
MODEL_NAME = os.getenv("LLM_MODEL", DEFAULT_MODEL_NAME)

client = None


def _get_client():
    """Load credentials only when a request is actually made."""
    global client
    if client is None:
        load_dotenv()
        api_key = os.getenv("GROQ_API_KEY") or os.getenv("LLM_API_KEY", "")
        if not api_key.strip():
            raise RuntimeError("Missing GROQ_API_KEY (or fallback LLM_API_KEY)")
        client = Groq(api_key=api_key, max_retries=0)
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
    if max_retries < 1:
        raise ValueError("max_retries must be at least 1")
    timeout_seconds = 30.0
    calls = 0
    active_client = request_client or _get_client()
    model_name = os.getenv("LLM_MODEL", DEFAULT_MODEL_NAME) if request_client is None else MODEL_NAME

    for attempt in range(1, max_retries + 1):
        try:
            kwargs = {
                "model": model_name,
                "messages": messages,
                "timeout": timeout_seconds,
                "temperature": 0.0,
            }
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
                raise ValueError("Groq returned no completion choices")
            message = getattr(response.choices[0], "message", None)
            if message is None:
                raise ValueError("Groq returned no assistant message")
            return message, usage_stats

        except GroqError as e:
            # Ghi log lỗi API ra sys.stderr (giữ stdout sạch tuyệt đối cho MCP stdio)
            print(
                f"[LLM GROQ ERROR] Attempt {attempt}/{max_retries} failed: {type(e).__name__}",
                file=sys.stderr,
                flush=True,
            )
            if attempt == max_retries:
                raise LLMRequestError(
                    f"LLM call failed after {max_retries} attempts: {type(e).__name__}", calls
                ) from e

            # Exponential backoff: 2^1 = 2s, 2^2 = 4s, 2^3 = 8s
            time.sleep(retry_delay * (2 ** (attempt - 1)))

        except Exception as e:
            print(
                f"[LLM UNEXPECTED ERROR] Attempt {attempt}/{max_retries} failed: {type(e).__name__}",
                file=sys.stderr,
                flush=True,
            )
            if attempt == max_retries:
                raise LLMRequestError(
                    f"Unexpected LLM call failure: {type(e).__name__}", calls
                ) from e
            time.sleep(retry_delay * (2 ** (attempt - 1)))

    raise LLMRequestError("LLM call failed without a response", calls)


async def call_llm_async(messages: list[dict], tools: list[dict] | None = None):
    """Run the synchronous provider wrapper off the event loop.

    Cancelling the await does not stop the worker thread or an in-flight HTTP
    request; evaluator timeouts therefore bound the async caller, not provider
    work already running in the thread.
    """
    return await asyncio.to_thread(call_llm, messages, tools)