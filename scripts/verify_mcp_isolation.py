"""Manually verify one read-only MCP call against a disposable SQLite DB.

Run from the repository root with the project environment. The script creates
and removes only its own temporary directory; it never calls Groq or a write
tool. Do not run it where MCP stdio/asyncio process startup is restricted.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys
import tempfile

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = Path(__file__).resolve().parents[1]


_SITE_CUSTOMIZE = '''
import os
import sqlite3
from pathlib import Path

_connect = sqlite3.connect
_expected = Path(os.environ["TRFC_STATE_DB"]).resolve()
_default = Path(os.environ["TRFC_DEFAULT_STATE_DB"]).resolve()
_proof = Path(os.environ["TRFC_DB_PROOF_FILE"])

def _guarded_connect(database, *args, **kwargs):
    actual = Path(database).expanduser().resolve()
    if actual == _default or actual != _expected:
        raise RuntimeError("MCP database path failed isolation check")
    _proof.write_text(str(actual), encoding="utf-8")
    return _connect(database, *args, **kwargs)

sqlite3.connect = _guarded_connect
'''


async def _verify(database: Path, proof_file: Path, probe_dir: Path) -> None:
    from trfc.tools import state

    os.environ[state.DB_PATH_ENV] = str(database)
    os.environ[state.REQUIRE_ISOLATED_DB_ENV] = "1"
    state.reset(database)

    (probe_dir / "sitecustomize.py").write_text(_SITE_CUSTOMIZE, encoding="utf-8")
    child_env = {
        "PYTHONPATH": os.pathsep.join((str(probe_dir), str(ROOT / "src"))),
        state.DB_PATH_ENV: str(database.resolve()),
        state.REQUIRE_ISOLATED_DB_ENV: "1",
        "TRFC_DEFAULT_STATE_DB": str(state.DB_PATH.resolve()),
        "TRFC_DB_PROOF_FILE": str(proof_file),
    }
    for name in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP"):
        if name in os.environ:
            child_env[name] = os.environ[name]

    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "trfc.mcp_server.server"],
        env=child_env,
        cwd=ROOT,
    )
    async with stdio_client(parameters) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            discovered = (await session.list_tools()).tools
            if not any(tool.name == "get_account_risk_status" for tool in discovered):
                raise RuntimeError("Expected read-only MCP tool was not discovered")
            result = await session.call_tool(
                "get_account_risk_status", {"account_id": "ACC001"}
            )
            if getattr(result, "isError", False):
                raise RuntimeError("Read-only MCP call failed")

    if not proof_file.exists():
        raise RuntimeError("MCP process did not produce database-path proof")
    effective_path = Path(proof_file.read_text(encoding="utf-8")).resolve()
    if effective_path != database.resolve() or effective_path == state.DB_PATH.resolve():
        raise RuntimeError("MCP process used an unexpected database path")
    print(f"tool=get_account_risk_status status=completed database={effective_path}")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="trfc-mcp-isolation-") as temporary:
        root = Path(temporary).resolve()
        database = root / "state.db"
        if database == (ROOT / "data" / "state.db").resolve():
            raise RuntimeError("Temporary path unexpectedly resolved to project default")
        probe_dir = root / "probe"
        probe_dir.mkdir()
        asyncio.run(_verify(database, root / "db-path.txt", probe_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
