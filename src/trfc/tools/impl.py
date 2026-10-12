"""5 tool của TRFC — chủ sở hữu: B. Mốc: CP2 (chạy với tool giả) → CP3 (thật).

Bảng tool (DE_TAI_TRFC_Agent.md §5.2):

  search_policy               đọc    uỷ quyền cho A (trfc.rag.search)
  get_transactions            đọc    đọc data/state.db
  get_account_risk_status     đọc    BƯỚC VERIFY BẮT BUỘC
  freeze_account_temporarily  GHI    ghi data/state.db
  flag_suspicious_tx          GHI    ghi data/state.db

QUY TẮC SẮT (yêu cầu 2.6): tool lỗi trả chuỗi `"Error: ..."`, KHÔNG raise.
Agent phải thấy lỗi và tự điều chỉnh, không được làm chết run.

ponytail: để trống có chủ đích. Đây là phần bị vấn đáp nặng nhất ("chứng minh
agent thực sự dùng kết quả tool") nên B phải viết tay.
"""

from datetime import datetime, timezone
import sys


from trfc.tools.schemas import Ack, Chunk, RiskStatus, Transaction
from trfc.tools.state import connect



def get_transactions(account_id: str, date_from: str, date_to: str) -> list[Transaction]:
    """Giao dịch của tài khoản trong khoảng ngày (YYYY-MM-DD). B cài đặt."""

    try:
        conn = connect()

        start_ts = f"{date_from} T00:00:00"

        end_ts = f"{date_to} T23:59:59"

        query = """
            SELECT tx_id, account_id, amount, currency, ts, country, method, location
            FROM transactions
            WHERE account_id = ? AND ts >= ? AND ts <= ?
            ORDER BY ts ASC
        """
        rows = conn.execute(query, (account_id, start_ts, end_ts)).fetchall()

        conn.close()

        res=[]

        for r in rows:
            ts_dt = datetime.fromisoformat(r["ts"])
            if ts_dt.tzinfo is None:
                ts_dt = ts_dt.replace(tzinfo=timezone.utc)
                
            tx = Transaction(
                tx_id=r["tx_id"],
                account_id=r["account_id"],
                amount=float(r["amount"]),
                currency=r["currency"],
                ts=ts_dt,
                country=r["country"],
                method=r["method"],
                location=r["location"]
            )
            res.append(tx)
        return res
    except Exception as e:
        print(f"[ERROR] Get Transaction failed : {e}")
        return f"Error: Failed to fetch transactions for account {account_id}: {str(e)}"

def get_account_risk_status(account_id: str) -> RiskStatus:
    """Đọc trạng thái rủi ro HIỆN TẠI từ state.db. B cài đặt — đây là bước verify."""
    try:
        conn = connect()


        acc_row = conn.execute(
            "SELECT account_id, frozen, freeze_reason, frozen_at FROM accounts WHERE account_id = ?",
            (account_id,)
        ).fetchone()

        if not acc_row:
            conn.close()
            return f"Error: Account {account_id} not found in system."

        flag_rows = conn.execute(
            """
            SELECT f.tx_id 
            FROM flags f
            JOIN transactions t ON f.tx_id = t.tx_id
            WHERE t.account_id = ?
            """,
            (account_id,)
        ).fetchall()
        
        flagged_tx_ids = [r["tx_id"] for r in flag_rows]
        conn.close()

        frozen_at_dt = None
        if acc_row["frozen_at"]:
            frozen_at_dt = datetime.fromisoformat(acc_row["frozen_at"])
            if frozen_at_dt.tzinfo is None:
                frozen_at_dt = frozen_at_dt.replace(tzinfo=timezone.utc)

        return RiskStatus(
            account_id=acc_row["account_id"],
            frozen=bool(acc_row["frozen"]),
            freeze_reason=acc_row["freeze_reason"],
            frozen_at=frozen_at_dt,
            flagged_tx_ids=flagged_tx_ids,
            checked_at=datetime.now(timezone.utc)  # Mốc thời gian VERIFY MỚI NHẤT
        )
    except Exception as e:
        print(f"[ERROR] Get account at risk status failed: {e}", file=sys.stderr)
        return f"Error: Failed to get risk status for account {account_id}: {str(e)}"


def freeze_account_temporarily(account_id: str, reason: str) -> Ack:
    """Ghi: khoá tạm thời tài khoản. B cài đặt."""

    try:
        conn = connect()
        frozen_at = datetime.now(timezone.utc).isoformat()
        
        cursor = conn.execute(
            """
            UPDATE accounts 
            SET frozen = 1, freeze_reason = ?, frozen_at = ? 
            WHERE account_id = ?
            """,
            (reason, frozen_at, account_id)
        )
        conn.commit()
        
        if cursor.rowcount == 0:
            conn.close()
            return f"Error: Account {account_id} does not exist to freeze."
            
        conn.close()
        return Ack(
            ok=True,
            message=f"Account {account_id} successfully frozen temporarily. Reason: {reason}"
        )
    except Exception as e:
        print(f"[TOOL ERROR] freeze_account_temporarily failed: {e}", file=sys.stderr)
        return f"Error: Failed to freeze account {account_id}: {str(e)}"

def flag_suspicious_tx(tx_id: str, reason: str) -> Ack:
    """Ghi: đánh dấu giao dịch đáng ngờ. B cài đặt."""
    try:
        conn = connect()
        flagged_at = datetime.now(timezone.utc).isoformat()
        
        # Cập nhật cột flagged trong bảng transactions
        tx_cursor = conn.execute(
            "UPDATE transactions SET flagged = 1 WHERE tx_id = ?", 
            (tx_id,)
        )
        
        if tx_cursor.rowcount == 0:
            conn.close()
            return f"Error: Transaction {tx_id} not found."

        # Ghi thông tin chi tiết vào bảng flags
        conn.execute(
            """
            INSERT OR REPLACE INTO flags (tx_id, reason, flagged_at)
            VALUES (?, ?, ?)
            """,
            (tx_id, reason, flagged_at)
        )
        conn.commit()
        conn.close()

        return Ack(
            ok=True,
            message=f"Transaction {tx_id} successfully flagged as suspicious.",
            tx_id=tx_id
        )
    except Exception as e:
        print(f"[TOOL ERROR] flag_suspicious_tx failed: {e}", file=sys.stderr)
        return f"Error: Failed to flag transaction {tx_id}: {str(e)}"

def search_policy(query: str, k: int = 5, tier: int | None = None,
                  mode: str = "hybrid") -> list[Chunk]:
    """Uỷ quyền cho A — B không sửa logic ở đây (PHAN_CONG.md §7 quy tắc 3)."""
    try:
        from trfc.rag.search import search_policy as _impl
        return _impl(query=query, k=k, tier=tier, mode=mode)
    except Exception as e:
        print(f"[TOOL ERROR] search_policy failed: {e}", file=sys.stderr)
        return f"Error: Policy search failed: {str(e)}"