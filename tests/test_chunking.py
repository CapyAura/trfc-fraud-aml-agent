"""Test chunking — chủ sở hữu: A. Canh RỦI RO #3 của đề tài.

Đây là test quan trọng nhất của A: bảng hạn mức eKYC bị cắt vỡ thì chunk chứa
"hạn mức 500 triệu" mà mất dòng "áp dụng cho tầng eKYC 2" → trả số ĐÚNG nhưng
gán SAI tầng. Lỗi im lặng, không crash, không có stack trace để lần.

Test phải KHẲNG ĐỊNH: không chunk nào chứa nửa bảng.
"""

import pytest

# Bản thu nhỏ đúng hình dạng DOC0007. Bảng phải DÀI HƠN chunk_size để phép cắt
# thật sự có cơ hội rơi vào giữa bảng — fixture ngắn thì test nào cũng xanh.
_DOC0007 = """# Quy định hạn mức giao dịch thanh toán

## Điều 5. Hạn mức giao dịch theo tầng eKYC

Bảng hạn mức dưới đây áp dụng cho giao dịch chuyển khoản trong nước.

| Tầng eKYC | Hạn mức mỗi ngày | Hạn mức mỗi giao dịch |
|---|---|---|
| Tầng 1 | 100.000.000 VND | 20.000.000 VND |
| Tầng 2 | 500.000.000 VND | 100.000.000 VND |
| Tầng 3 | 2.000.000.000 VND | 500.000.000 VND |
| Tầng 4 | 5.000.000.000 VND | 1.000.000.000 VND |
| Tầng 5 | 10.000.000.000 VND | 2.000.000.000 VND |
| Tầng 6 | 20.000.000.000 VND | 5.000.000.000 VND |

## Điều 6. Giao dịch quốc tế

Hạn mức giao dịch thẻ quốc tế là 50.000.000 VND mỗi ngày cho mọi tầng eKYC.
Giao dịch thẻ quốc tế không được cộng dồn vào hạn mức chuyển khoản trong nước.
Mọi giao dịch thẻ quốc tế vượt 50.000.000 VND trong ngày đều phải xác thực
lại bằng OTP gửi tới số điện thoại đã đăng ký của chủ tài khoản. Trường hợp
chủ tài khoản đổi số điện thoại trong vòng 24 giờ trước giao dịch, hệ thống
phải tạm giữ giao dịch để kiểm tra thủ công thay vì xác thực tự động.

## Điều 7. Cách tính hạn mức trong ngày

Hạn mức được tính theo tổng giá trị giao dịch trong ngày dương lịch, từ 00:00
đến 23:59 theo giờ Việt Nam. Giao dịch bị từ chối không được tính vào hạn mức.
Giao dịch hoàn tiền được trừ khỏi tổng đã dùng trong ngày. Với giao dịch ngoại
tệ, giá trị được quy đổi sang VND theo tỷ giá bán ra của ngân hàng tại thời
điểm giao dịch được ghi nhận, không phải theo tỷ giá lúc đối soát.

## Điều 8. Xử lý khi vượt hạn mức

Khi tổng giá trị giao dịch trong ngày vượt hạn mức của tầng eKYC hiện tại,
hệ thống phải từ chối giao dịch vượt và ghi nhận cảnh báo. Tài khoản không bị
khoá tự động; việc khoá do kiểm soát viên quyết định theo quy trình riêng.
Cảnh báo vượt hạn mức phải được lưu tối thiểu 90 ngày để phục vụ tra soát.

## Điều 9. Nâng tầng eKYC

Khách hàng có thể yêu cầu nâng tầng eKYC bất kỳ lúc nào. Hồ sơ nâng tầng được
xử lý trong vòng một ngày làm việc. Hạn mức mới có hiệu lực từ thời điểm hồ sơ
được duyệt, không áp dụng hồi tố cho giao dịch đã thực hiện trước đó.
"""

_HEADER = "| Tầng eKYC | Hạn mức mỗi ngày | Hạn mức mỗi giao dịch |"


def test_khong_chunk_nao_chua_nua_bang_han_muc():
    """Mọi chunk chứa dòng hạn mức phải chứa luôn dòng tầng eKYC đi kèm."""
    from trfc.rag.chunking import chunk_document

    chunks = chunk_document(
        doc_id="DOC0007",
        title="Hạn mức giao dịch theo tầng eKYC",
        version="2026.1",
        text=_DOC0007,
    )
    for c in chunks:
        if "hạn mức" in c.text.lower():
            assert "eKYC" in c.text, f"chunk {c.chunk_index} có hạn mức mà mất tầng:\n{c.text}"


def test_dong_bang_khong_tach_khoi_tieu_de_cot():
    """Chunk chứa dòng bảng PHẢI chứa dòng tiêu đề cột.

    Đây mới là lỗi im lặng thật: chunk có '| Tầng 3 | 2.000.000.000 VND | 500.000.000 VND |'
    mà mất tiêu đề thì không biết số nào là hạn mức/ngày, số nào là /giao dịch.
    Trả số ĐÚNG, gán nhãn SAI, không crash.
    """
    from trfc.rag.chunking import chunk_document

    chunks = chunk_document("DOC0007", "Hạn mức eKYC", "2026.1", _DOC0007)
    assert len(chunks) > 1, "phải cắt ra nhiều chunk, nếu không test này vô nghĩa"

    for c in chunks:
        if any(line.lstrip().startswith("|") for line in c.text.splitlines()):
            assert _HEADER in c.text, (
                f"chunk {c.chunk_index} có dòng bảng nhưng mất tiêu đề cột:\n{c.text}"
            )


def test_bang_dai_hon_chunk_size_van_khong_bi_cat():
    """Bảng dài hơn chunk_size phải ở nguyên một chunk — atomic thắng kích thước.

    Đây là ca thật của DOC0007: bảng hạn mức đủ dài để vượt chunk_size, nên mọi
    chunker cắt theo kích thước sẽ xé nó. Hệ quả: chunk toàn dòng số
    "| Tầng 32 | 3200.000.000 VND | 640.000.000 VND |" mà mất tiêu đề cột —
    trả số ĐÚNG, gán nhãn SAI, không crash.
    """
    from trfc.config import CONFIG
    from trfc.rag.chunking import _count_tokens, chunk_document

    rows = "\n".join(
        f"| Tầng {i} | {i * 100}.000.000 VND | {i * 20}.000.000 VND |" for i in range(1, 40)
    )
    doc = (
        "# Quy định hạn mức giao dịch\n\n"
        "## Điều 5. Hạn mức giao dịch theo tầng eKYC\n\n"
        "Bảng hạn mức dưới đây áp dụng cho giao dịch chuyển khoản trong nước.\n\n"
        "| Tầng eKYC | Hạn mức mỗi ngày | Hạn mức mỗi giao dịch |\n|---|---|---|\n"
        f"{rows}\n\n"
        "## Điều 6. Giao dịch quốc tế\n\n"
        "Hạn mức giao dịch thẻ quốc tế là 50.000.000 VND mỗi ngày cho mọi tầng eKYC.\n"
    )
    assert _count_tokens(doc) > CONFIG["chunking"]["chunk_size"], "bảng phải vượt chunk_size"

    chunks = chunk_document("DOC0007", "Hạn mức eKYC", "2026.1", doc)
    holders = [c for c in chunks if "Tầng 39" in c.text]
    assert len(holders) == 1
    assert _HEADER in holders[0].text, "bảng bị xé khỏi tiêu đề cột"
    assert "Tầng 1 |" in holders[0].text, "nửa đầu bảng nằm ở chunk khác"


def test_chunk_size_lay_tu_config():
    """chunk_size/overlap phải đến từ config.toml, không hard-code (yêu cầu 2.5)."""
    from trfc.config import CONFIG

    assert CONFIG["chunking"]["chunk_size"] > 0
    assert CONFIG["chunking"]["overlap"] < CONFIG["chunking"]["chunk_size"]


@pytest.mark.skip(reason="A — CP2")
def test_khong_tim_thay_tra_ve_list_rong():
    """Hợp đồng với B: không có kết quả → [] , KHÔNG được trả None."""
    from trfc.rag.search import search_policy

    assert search_policy("zzz khong ton tai trong corpus") == []
