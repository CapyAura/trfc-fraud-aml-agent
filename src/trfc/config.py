"""Đọc config.toml (stdlib tomllib — không cần PyYAML).

    from trfc.config import CONFIG
    CONFIG["chunking"]["chunk_size"]

ponytail: đọc 1 lần lúc import, cache ở CONFIG. Cần reload khi đang chạy thì
thêm hàm load() — chưa cần bây giờ.
"""

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config.toml"


def load(path: Path = CONFIG_PATH) -> dict:
    """Đọc config.toml. Thiếu file → lỗi rõ ràng, không im lặng dùng default."""
    if not path.exists():
        raise FileNotFoundError(f"Thiếu {path} — file này bắt buộc có trong repo.")
    with path.open("rb") as f:
        return tomllib.load(f)


CONFIG = load()
