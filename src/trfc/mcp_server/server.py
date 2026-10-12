"""MCP server — chủ sở hữu: B. Mốc: CP2 → CP3.

Yêu cầu 2.8: server do SV viết, ≥2 tool (≥1 tool GHI), chạy qua stdio,
STDOUT SẠCH, client discover động.

⚠️ stdout sạch là điều kiện sống còn: stdio transport dùng stdout làm kênh
JSON-RPC. Một `print()` debug là hỏng cả phiên. Log ra stderr — xem pattern
`logging.StreamHandler(sys.stderr)` trong W7/ex2_1_mcp_server.py.

Kiểm tra API thật của `mcp` SDK trước khi viết: bản trong W7 dùng
`from mcp.server.mcpserver import MCPServer`. Xác nhận lại với bản `mcp`
trong pyproject.toml rồi mới code — API đã đổi giữa các phiên bản.

Chạy: python -m trfc.mcp_server.server
"""

import logging
import sys

_handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]  # KHÔNG dùng stdout
logging.basicConfig(
    level=logging.INFO,
    handlers=_handlers,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger(__name__)


def build_server():
    """Tạo MCP server + đăng ký 5 tool. B cài đặt."""
    raise NotImplementedError("B — CP2.")


if __name__ == "__main__":
    build_server().run()
