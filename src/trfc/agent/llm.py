"""Wrapper gọi LLM — chủ sở hữu: B. Mọi chỗ gọi model đi qua ĐÂY.

Yêu cầu 2.4: retry + timeout + log lỗi HTTP.
GV đọc đúng 1 hàm này khi vấn đáp — nên nó phải là chỗ duy nhất có `client.chat`.

ponytail: chưa cài đặt. Đừng rải `OpenAI(...)` ra nhiều file; thêm retry bằng
vòng lặp + `time.sleep(2**attempt)`, chưa cần thư viện backoff.
"""

from dataclasses import dataclass
import os
import sys
import time
from dotenv import load_dotenv
from groq import Groq, GroqError

load_dotenv()

LLM_API_KEY = os.getenv("GROQ_API_KEY") or os.getenv("LLM_API_KEY", "")
MODEL_NAME = os.getenv("LLM_MODEL", "qwen/qwen3.8-27b")

# ĐIỂM DUY NHẤT KHỞI TẠO CLIENT GROQ TRONG TOÀN BỘ PROJECT
client = Groq(api_key=LLM_API_KEY)


@dataclass
class Usage:
    """Số token 1 lần gọi — ghi vào logs/*.jsonl cho report §6."""

    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    max_prompt: int = 0


def call_llm(messages: list[dict], tools: list[dict] | None = None) -> tuple[str, Usage]:
    """Gọi model 1 lần. Trả (nội dung, Usage). B cài đặt."""
    max_retries = 3
    timeout_seconds = 30.0
    usage_stats = Usage()

    for attempt in range(1, max_retries + 1):
        try:
            kwargs = {
                "model": MODEL_NAME,
                "messages": messages,
                "timeout": timeout_seconds,
                "temperature": 0.0,
            }
            if tools:
                kwargs["tools"] = tools

            # ĐIỂM DUY NHẤT GỌI CLIENT.CHAT TRONG TOÀN BỘ PROJECT
            response = client.chat.completions.create(**kwargs)

            # Thu thập token usage để ghi log
            if response.usage:
                usage_stats.calls = 1
                usage_stats.prompt_tokens = response.usage.prompt_tokens or 0
                usage_stats.completion_tokens = response.usage.completion_tokens or 0
                usage_stats.max_prompt = response.usage.prompt_tokens or 0

            content = response.choices[0].message.content or ""
            return content, usage_stats

        except GroqError as e:
            # Ghi log lỗi API ra sys.stderr (giữ stdout sạch tuyệt đối cho MCP stdio)
            print(
                f"[LLM GROQ ERROR] Attempt {attempt}/{max_retries} failed: {str(e)}",
                file=sys.stderr,
                flush=True,
            )
            if attempt == max_retries:
                return f"Error: LLM call failed after {max_retries} attempts: {str(e)}", usage_stats

            # Exponential backoff: 2^1 = 2s, 2^2 = 4s, 2^3 = 8s
            time.sleep(2 ** attempt)

        except Exception as e:
            print(
                f"[LLM UNEXPECTED ERROR] Attempt {attempt}/{max_retries} failed: {str(e)}",
                file=sys.stderr,
                flush=True,
            )
            if attempt == max_retries:
                return f"Error: Unexpected LLM call failure: {str(e)}", usage_stats
            time.sleep(2 ** attempt)

    return "Error: LLM call completely failed.", usage_stats

if __name__ == "__main__":
    # Test gọi thử LLM đơn lẻ
    test_messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Xin chào, hãy giúp tôi viết một đoạn văn ngắn về trí tuệ nhân tạo."},
    ]
    print("--- Testing call_llm() ---", file=sys.stderr)
    response_text, usage_info = call_llm(test_messages)
    
    print(f"Response:\n{response_text}")
    print(f"\nUsage Stats: {usage_info}")