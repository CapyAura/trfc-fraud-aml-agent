"""Chạy testset và in bảng metric — chủ sở hữu: C. Mốc: CP4.

Yêu cầu: `make eval` tái lập MỌI số liệu trong report §6.

Metrics (DE_TAI_TRFC_Agent.md §8):
  - faithfulness        mỗi claim có context hỗ trợ không
  - context precision   chunk retrieve về có liên quan không
  - tỉ lệ từ chối đúng  trên câu no_answer, tách loại (i) vs (ii)

⚠️ Đo CẶP, không đo mỗi faithfulness. Một hệ thống luôn từ chối sẽ đạt
faithfulness cao giả — phải đo kèm tỉ lệ trả lời đúng trên câu trả lời được.

Xuất thêm CSV theo từng câu (điểm cộng +1) và log jsonl vào logs/.
"""


def main() -> int:
    raise NotImplementedError("C — CP4.")


if __name__ == "__main__":
    raise SystemExit(main())
