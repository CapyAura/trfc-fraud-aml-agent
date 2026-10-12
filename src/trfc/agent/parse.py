"""Parse action của LLM — chủ sở hữu: B. Mốc: CP2.

Yêu cầu 2.6: parse AN TOÀN — thiếu dấu ngoặc / JSON hỏng thì trả lỗi parse cho
agent, KHÔNG crash cả run.

ponytail: để trống có chủ đích. Test bắt buộc: 1 chuỗi JSON hỏng phải trả lỗi
chứ không ném exception.
"""

from dataclasses import dataclass


@dataclass
class Action:
    tool: str
    args: dict


def parse_action(text: str) -> Action | str:
    """Trả Action nếu parse được, hoặc chuỗi "Error: ..." nếu không. B cài đặt."""
    raise NotImplementedError("B — CP2. Không được raise.")
