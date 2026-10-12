"""Parse action của LLM — chủ sở hữu: B. Mốc: CP2.

Yêu cầu 2.6: parse AN TOÀN — thiếu dấu ngoặc / JSON hỏng thì trả lỗi parse cho
agent, KHÔNG crash cả run.

ponytail: để trống có chủ đích. Test bắt buộc: 1 chuỗi JSON hỏng phải trả lỗi
chứ không ném exception.
"""

from dataclasses import dataclass
import json
import re


@dataclass
class Action:
    tool: str
    args: dict


def parse_action(text: str) -> Action | str:
    """Trả Action nếu parse được, hoặc chuỗi "Error: ..." nếu không. B cài đặt."""
    if not text or not isinstance(text, str):
        return "Error: Empty or invalid input text."

    # Tìm khối JSON trong code block ```json ... ``` hoặc ``` ... ```
    json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)

    # Nếu không nằm trong code block, tìm chuỗi JSON có cấu trúc chứa "tool"
    if not json_match:
        json_match = re.search(r"(\{.*\"tool\"\s*:\s*\".*?\".*\})", text, re.DOTALL)

    if not json_match:
        return "Error: No valid action JSON block found in output."

    raw_json = json_match.group(1)
    try:
        data = json.loads(raw_json)
        tool = data.get("tool")
        args = data.get("args", {})

        if not tool:
            return "Error: Invalid action schema: missing 'tool' key in JSON object."

        if not isinstance(args, dict):
            return "Error: Invalid action schema: 'args' must be a JSON object."

        return Action(tool=tool, args=args)

    except json.JSONDecodeError as e:
        # Bắt lỗi JSON hỏng / thiếu dấu ngoặc -> Trả chuỗi "Error: ..." cho Agent tự điều chỉnh, KHÔNG raise
        return f"Error: Failed to parse action JSON due to syntax error: {str(e)}"
    except Exception as e:
        return f"Error: Unexpected error while parsing action: {str(e)}"