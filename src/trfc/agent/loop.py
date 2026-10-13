"""ReAct loop tự viết kết nối MCP Server — chủ sở hữu: B. Mốc: CP3 (end-to-end).

Chạy qua MCP stdio transport kết nối tới mcp_server.server (Async MCP v2.x).
"""

import asyncio
import json
import logging
from pathlib import Path
import sys
from typing import Any, Dict, List

import tomllib

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from trfc.agent.llm import call_llm
from trfc.agent.parse import parse_action

# Đường dẫn thư mục gốc dự án
ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
CONFIG_PATH = ROOT_DIR / "config.toml"
PROMPT_PATH = ROOT_DIR / "prompts" / "system.txt"

logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="[REACT ENGINE] %(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("react_loop")


def load_max_steps() -> int:
    """Đọc MAX_STEPS từ config.toml (mặc định 8)."""
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "rb") as f:
                config = tomllib.load(f)
                return config.get("agent", {}).get("max_steps", 8)
        except Exception as e:
            logger.warning(f"Không đọc được config.toml, dùng MAX_STEPS=8: {e}")
    return 8


def load_system_prompt() -> str:
    """Nạp system prompt từ file prompts/system.txt (Yêu cầu 2.4)."""
    if PROMPT_PATH.exists():
        return PROMPT_PATH.read_text(encoding="utf-8")
    raise FileNotFoundError(f"Không tìm thấy file prompt bắt buộc tại {PROMPT_PATH}")


async def run(question: str) -> str:
    """Chạy 1 câu hỏi end-to-end qua MCP Server stdio, trả câu trả lời cuối (Async MCP v2.x)."""
    max_steps = load_max_steps()
    system_prompt = load_system_prompt()

    # Cấu hình Stdio Transport khởi chạy mcp_server/server.py
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "trfc.mcp_server.server"],
        env={"PYTHONPATH": str(ROOT_DIR / "src")},
    )

    logger.info("Đang kết nối tới MCP Server qua stdio...")

    # Mở kết nối stdio với MCP Server bằng async context manager
    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            # Dynamic Discovery: Lấy danh sách tools động trực tiếp từ MCP Server
            mcp_tools_res = await session.list_tools()
            available_tools = mcp_tools_res.tools
            logger.info(f"Đã phát hiện {len(available_tools)} tools từ MCP Server.")

            # Chuyển đổi tool schema cho LLM
            mcp_tools_schema = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.input_schema,
                    },
                }
                for tool in available_tools
            ]

            messages: List[Dict[str, Any]] = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question},
            ]

            for step in range(1, max_steps + 1):
                print(f"\n--- [BƯỚC {step}/{max_steps}] ---", file=sys.stderr)

                # 1. Gọi LLM
                llm_response, _usage = call_llm(messages, tools=mcp_tools_schema)
                if llm_response.startswith("Error:"):
                    return llm_response

                print(f"[LLM OUTPUT]:\n{llm_response}\n", file=sys.stderr)
                messages.append({"role": "assistant", "content": llm_response})

                # 2. Parse Action
                parsed = parse_action(llm_response)
                if isinstance(parsed, str) and parsed.startswith("Error:"):
                    messages.append({"role": "user", "content": f"Observation: {parsed}"})
                    continue

                tool_name, tool_args = parsed.tool, parsed.args

                # 3. Đã có câu trả lời cuối cùng
                if tool_name is None:
                    logger.info("Hoàn thành ReAct loop.")
                    return llm_response

                # 4. Gọi Tool qua MCP Session
                print(f"[CALL MCP TOOL]: {tool_name}({tool_args})", file=sys.stderr)
                try:
                    tool_result = await session.call_tool(tool_name, tool_args)
                    content_str = "\n".join(
                        item.text for item in tool_result.content if hasattr(item, "text")
                    )
                    observation = f"Observation: {content_str}"
                except Exception as e:
                    observation = f"Observation: Error: Gọi tool '{tool_name}' qua MCP thất bại: {str(e)}"
                    logger.error(f"Lỗi MCP Tool: {e}")

                print(f"[MCP RESULT]: {observation}\n", file=sys.stderr)
                messages.append({"role": "user", "content": observation})

            return f"Error: ReAct loop vượt quá giới hạn MAX_STEPS ({max_steps})."


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # console Windows là cp1258
    if len(sys.argv) < 2:
        print('Dùng: python -m trfc.agent.loop "câu hỏi"', file=sys.stderr)
        return 2
    print(asyncio.run(run(" ".join(sys.argv[1:]))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())