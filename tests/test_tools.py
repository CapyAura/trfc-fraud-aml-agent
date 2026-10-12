"""Test tool + agent — chủ sở hữu: B. Canh RỦI RO #2 của đề tài.

Hai điều GV sẽ hỏi trực tiếp:
  1. "Chứng minh agent thực sự dùng kết quả tool" → verify phải đọc lại từ
     state.db, không đọc response của chính lệnh write.
  2. "Tool lỗi thì sao?" → phải trả chuỗi "Error: ...", KHÔNG raise.
"""

import pytest


@pytest.mark.skip(reason="B — CP2: bỏ skip khi impl.py + state.py xong")
def test_verify_doc_lai_tu_db(tmp_path):
    """Sau khi freeze, get_account_risk_status phải thấy frozen=True TỪ DB."""
    from trfc.tools import impl, state

    state.reset(tmp_path / "state.db")
    ack = impl.freeze_account_temporarily("ACC001", "vượt hạn mức 44%")
    assert ack.ok, ack

    status = impl.get_account_risk_status("ACC001")
    assert status.frozen is True
    assert status.freeze_reason == "vượt hạn mức 44%"
    assert status.frozen_at is not None


@pytest.mark.skip(reason="B — CP2")
def test_tool_loi_tra_chuoi_khong_raise():
    """Tài khoản không tồn tại → chuỗi 'Error: ...', không exception (yêu cầu 2.6)."""
    from trfc.tools import impl

    result = impl.get_account_risk_status("KHONG_CO_TAI_KHOAN_NAY")
    assert isinstance(result, str), f"phải trả chuỗi, nhận được {type(result)}"
    assert result.startswith("Error:")


@pytest.mark.skip(reason="B — CP2")
def test_parse_action_khong_crash_voi_json_hong():
    """JSON thiếu dấu ngoặc → lỗi parse, không làm chết run (yêu cầu 2.6)."""
    from trfc.agent.parse import parse_action

    result = parse_action('{"tool": "search_policy", "args": {')
    assert isinstance(result, str)
    assert result.startswith("Error:")


@pytest.mark.skip(reason="B — CP2")
def test_du_lieu_seed_dung_ca_testset():
    """Ca ACC001 phải vượt hạn mức tầng 2 — nếu seed đổi, testset của C vỡ."""
    from trfc.tools import state

    state.reset()
    conn = state.connect()
    total = conn.execute(
        "SELECT SUM(amount) AS s FROM transactions WHERE account_id = 'ACC001'"
    ).fetchone()["s"]
    conn.close()
    assert total == 720_000_000, f"seed đổi rồi: {total:,} — báo C cập nhật testset"
