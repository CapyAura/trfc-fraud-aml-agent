"""ReAct loop tự viết — chủ sở hữu: B. Mốc: CP2 (giả) → CP3 (end-to-end).

Yêu cầu 2.2: vòng lặp do SV viết tay. Được dùng `mcp` SDK, thư viện embedding,
`rank_bm25`, `numpy`, `pandas`, `python-docx`. KHÔNG dùng LangChain/LlamaIndex.

Bắt buộc:
  - MAX_STEPS = 8, đọc từ config.toml
  - tool lỗi trả "Error: ..." không raise → agent tự điều chỉnh
  - prompt nạp từ prompts/*.txt, KHÔNG nhúng trong code (yêu cầu 2.4)
  - client discover động danh sách tool qua MCP, KHÔNG hard-code (yêu cầu 2.8)

Trace mục tiêu (DE_TAI_TRFC_Agent.md §6) — dùng làm demo và report §4:
  search_policy → get_transactions → tính → freeze_account_temporarily
  → get_account_risk_status (VERIFY)

Chạy: python -m trfc.agent.loop "ACC001 hôm nay có vượt hạn mức không?"
"""

import sys


def run(question: str) -> str:
    """Chạy 1 câu hỏi end-to-end, trả câu trả lời cuối. B cài đặt."""
    raise NotImplementedError("B — CP3.")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # console Windows là cp1258
    if len(sys.argv) < 2:
        print('Dùng: python -m trfc.agent.loop "câu hỏi"', file=sys.stderr)
        return 2
    print(run(" ".join(sys.argv[1:])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
