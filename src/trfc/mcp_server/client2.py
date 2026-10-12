"""Client MCP thứ hai — chủ sở hữu: C (KHÔNG phải B). Mốc: CP4.

Điểm cộng +1 "MCP server dùng được từ host thứ hai".

Cố ý giao cho C: nếu B vừa viết server vừa viết client thì "chứng minh interop"
thành giả. Client này phải discover tool động rồi gọi được, độc lập với agent.

Chạy: python -m trfc.mcp_server.client2
"""


def main() -> int:
    raise NotImplementedError("C — CP4. Discover động rồi gọi thử 1 tool.")


if __name__ == "__main__":
    raise SystemExit(main())
