"""Wrapper gọi LLM — chủ sở hữu: B. Mọi chỗ gọi model đi qua ĐÂY.

Yêu cầu 2.4: retry + timeout + log lỗi HTTP.
GV đọc đúng 1 hàm này khi vấn đáp — nên nó phải là chỗ duy nhất có `client.chat`.

ponytail: chưa cài đặt. Đừng rải `OpenAI(...)` ra nhiều file; thêm retry bằng
vòng lặp + `time.sleep(2**attempt)`, chưa cần thư viện backoff.
"""

from dataclasses import dataclass


@dataclass
class Usage:
    """Số token 1 lần gọi — ghi vào logs/*.jsonl cho report §6."""

    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    max_prompt: int = 0


def call_llm(messages: list[dict], tools: list[dict] | None = None) -> tuple[str, Usage]:
    """Gọi model 1 lần. Trả (nội dung, Usage). B cài đặt."""
    raise NotImplementedError("B — CP2. retry + timeout + log lỗi HTTP.")
