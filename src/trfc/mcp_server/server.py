"""MCP server — chủ sở hữu: B. Mốc: CP2 → CP3.

Yêu cầu 2.8: server do SV viết, ≥2 tool (≥1 tool GHI), chạy qua stdio,
STDOUT SẠCH, client discover động.

⚠️ stdout sạch là điều kiện sống còn: stdio transport dùng stdout làm kênh
JSON-RPC. Một `print()` debug là hỏng cả phiên. Log ra stderr — xem pattern
`logging.StreamHandler(sys.stderr)` trong W7/ex2_1_mcp_server.py.

Chạy: python -m trfc.mcp_server.server
"""

from dataclasses import asdict, is_dataclass
import json
import logging
import sys
from typing import Any

from mcp.server.mcpserver import MCPServer
from trfc.tools import impl

_handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]  # KHÔNG dùng stdout
logging.basicConfig(
    level=logging.INFO,
    handlers=_handlers,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger(__name__)


def _to_json_serializable(obj: Any) -> Any:
    """Helper chuyển đổi Dataclass hoặc object sang định dạng JSON-serializable."""
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, list):
        return [_to_json_serializable(item) for item in obj]
    if isinstance(obj, dict):
        return {k: _to_json_serializable(v) for k, v in obj.items()}
    return str(obj) if not isinstance(obj, (int, float, bool, str, type(None))) else obj


def build_server() -> MCPServer:
    """Tạo MCP server + đăng ký 5 tool. B cài đặt."""
    mcp = MCPServer("TRFC Risk & AML Server")

    # 1. search_policy (Đọc)
    @mcp.tool()
    def search_policy(query: str, k: int = 5, tier: int | None = None, mode: str = "hybrid") -> str:
        """Truy vấn quy định/chính sách rủi ro và hạn mức từ tài liệu RAG."""
        log.info(f"Tool search_policy called: query='{query}', k={k}, tier={tier}, mode='{mode}'")
        res = impl.search_policy(query=query, k=k, tier=tier, mode=mode)
        return json.dumps(_to_json_serializable(res), ensure_ascii=False)

    # 2. get_transactions (Đọc)
    @mcp.tool()
    def get_transactions(account_id: str, date_from: str, date_to: str) -> str:
        """Lấy danh sách giao dịch của tài khoản trong khoảng thời gian (YYYY-MM-DD)."""
        log.info(f"Tool get_transactions called: account_id='{account_id}', date_from='{date_from}', date_to='{date_to}'")
        res = impl.get_transactions(account_id=account_id, date_from=date_from, date_to=date_to)
        return json.dumps(_to_json_serializable(res), ensure_ascii=False)

    # 3. get_account_risk_status (Đọc - Bước Verify)
    @mcp.tool()
    def get_account_risk_status(account_id: str) -> str:
        """BƯỚC VERIFY: Đọc trạng thái rủi ro hiện tại và danh sách giao dịch bị gắn cờ từ state.db."""
        log.info(f"Tool get_account_risk_status called: account_id='{account_id}'")
        res = impl.get_account_risk_status(account_id=account_id)
        return json.dumps(_to_json_serializable(res), ensure_ascii=False)

    # 4. freeze_account_temporarily (Ghi - Side Effect)
    @mcp.tool()
    def freeze_account_temporarily(account_id: str, reason: str) -> str:
        """Lệnh ghi Side-Effect: Tạm thời khóa tài khoản và ghi nhận lý do vào state.db."""
        log.info(f"Tool freeze_account_temporarily called: account_id='{account_id}', reason='{reason}'")
        res = impl.freeze_account_temporarily(account_id=account_id, reason=reason)
        return json.dumps(_to_json_serializable(res), ensure_ascii=False)

    # 5. flag_suspicious_tx (Ghi - Side Effect)
    @mcp.tool()
    def flag_suspicious_tx(tx_id: str, reason: str) -> str:
        """Lệnh ghi Side-Effect: Đánh dấu cờ giao dịch nghi vấn vào state.db."""
        log.info(f"Tool flag_suspicious_tx called: tx_id='{tx_id}', reason='{reason}'")
        res = impl.flag_suspicious_tx(tx_id=tx_id, reason=reason)
        return json.dumps(_to_json_serializable(res), ensure_ascii=False)

    return mcp


if __name__ == "__main__":
    server = build_server()
    log.info("Starting TRFC MCP Server via stdio transport...")
    server.run(transport="stdio")
