"""Offline tests for the C4 MCP write-isolation verifier helpers."""

import json
import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
import os
import sqlite3
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

from scripts import verify_mcp_write_isolation as verifier


def _drive_without_loop(coroutine):
    """Run a no-I/O coroutine in unit tests without initializing Windows asyncio."""
    try:
        return coroutine.send(None)
    except StopIteration as completed:
        return completed.value
    finally:
        coroutine.close()


def test_database_path_guard_rejects_unapproved_path(tmp_path):
    allowed = tmp_path / "owned" / "state.db"
    other = tmp_path / "outside.db"
    default = tmp_path / "project" / "data" / "state.db"

    with pytest.raises(verifier.VerificationError, match="outside the explicitly allowed"):
        verifier._authorize_database_path(
            other, allowed_database=allowed, default_database=default
        )


def test_verifier_refuses_target_that_normalizes_to_default_database(tmp_path):
    default = tmp_path / "project" / "data" / "state.db"
    alias = tmp_path / "project" / "data" / "nested" / ".." / "state.db"

    with pytest.raises(verifier.VerificationError, match="allowed database resolves"):
        verifier._authorize_database_path(
            alias, allowed_database=alias, default_database=default
        )


def test_verification_stops_before_seed_if_owned_target_is_default(tmp_path, monkeypatch):
    @contextmanager
    def target_workspace():
        yield tmp_path

    monkeypatch.setattr(verifier, "_temporary_workspace", target_workspace)
    monkeypatch.setattr(verifier.state, "DB_PATH", tmp_path / "state.db")
    monkeypatch.setattr(
        verifier.state, "reset",
        lambda *_args, **_kwargs: pytest.fail("reset ran for the project default target"),
    )

    checks = {name: None for name in verifier.REQUIRED_STEPS}
    with pytest.raises(verifier.VerificationError, match="allowed database resolves"):
        verifier._run_verification(checks)

    assert not (tmp_path / "state.db").exists()


def test_database_path_guard_accepts_only_exact_normalized_temporary_target(tmp_path):
    expected = tmp_path / "owned" / "state.db"
    equivalent = tmp_path / "owned" / "nested" / ".." / "state.db"
    default = tmp_path / "project" / "data" / "state.db"

    assert verifier._authorize_database_path(
        equivalent, allowed_database=expected, default_database=default
    ) == expected.resolve()


def test_tool_error_response_is_not_treated_as_success():
    with pytest.raises(verifier.VerificationError, match="returned an error"):
        verifier._tool_payload(
            SimpleNamespace(isError=True, content=[SimpleNamespace(text='{"ok":true}')]),
            "freeze_account_temporarily",
        )

    with pytest.raises(verifier.VerificationError, match="flag_suspicious_tx failed"):
        verifier._tool_payload(
            SimpleNamespace(isError=False, content=[SimpleNamespace(text='"Error: denied"')]),
            "flag_suspicious_tx",
        )


def test_missing_or_unchanged_readbacks_fail_verification():
    with pytest.raises(verifier.VerificationError, match="missing the expected account"):
        verifier._verify_freeze_readback(None, account_id="ACC001", reason="test")
    with pytest.raises(verifier.VerificationError, match="did not confirm frozen state"):
        verifier._verify_freeze_readback(
            {"account_id": "ACC001", "frozen": False, "freeze_reason": None,
             "frozen_at": None},
            account_id="ACC001", reason="test",
        )
    with pytest.raises(verifier.VerificationError, match="did not confirm the transaction"):
        verifier._verify_flag_readback(
            {"flagged_tx_ids": []}, tx_id="TX001"
        )


def test_temporary_cleanup_removes_only_its_owned_directory(tmp_path):
    parent = tmp_path / "temp-parent"
    parent.mkdir()
    sibling = parent / "preserve.txt"
    sibling.write_text("keep", encoding="utf-8")

    with verifier._temporary_workspace(parent) as workspace:
        owned_file = workspace / "owned.txt"
        owned_file.write_text("temporary", encoding="utf-8")
        assert workspace.parent == parent.resolve()
        assert owned_file.is_file()

    assert not workspace.exists()
    assert sibling.read_text(encoding="utf-8") == "keep"


def test_post_process_state_check_closes_sqlite_before_workspace_cleanup(
    tmp_path, monkeypatch
):
    database = tmp_path / "isolated-state.db"
    with verifier.closing(sqlite3.connect(database)) as connection:
        connection.executescript(
            """
            CREATE TABLE accounts (
                account_id TEXT PRIMARY KEY, frozen INTEGER,
                freeze_reason TEXT, frozen_at TEXT
            );
            CREATE TABLE transactions (tx_id TEXT PRIMARY KEY, flagged INTEGER);
            CREATE TABLE flags (tx_id TEXT PRIMARY KEY, reason TEXT, flagged_at TEXT);
            INSERT INTO accounts VALUES
                ('ACC001', 1, 'freeze-check', '2026-10-14T00:00:00+00:00');
            INSERT INTO transactions VALUES ('TX001', 1);
            INSERT INTO flags VALUES
                ('TX001', 'flag-check', '2026-10-14T00:00:00+00:00');
            """
        )

    original_connect = sqlite3.connect
    opened = []

    class TrackingConnection(sqlite3.Connection):
        was_closed = False

        def close(self):
            self.was_closed = True
            super().close()

    def tracked_connect(path):
        connection = original_connect(path, factory=TrackingConnection)
        opened.append(connection)
        return connection

    monkeypatch.setattr(verifier.sqlite3, "connect", tracked_connect)
    verifier._verify_sqlite_state(
        database,
        account_id="ACC001",
        freeze_reason="freeze-check",
        tx_id="TX001",
        flag_reason="flag-check",
    )

    assert len(opened) == 1
    assert opened[0].was_closed is True
    database.unlink()
    assert not database.exists()


def test_freeze_and_flag_readbacks_require_all_persisted_fields():
    verifier._verify_freeze_readback(
        {"account_id": "ACC001", "frozen": True, "freeze_reason": "test",
         "frozen_at": "2026-10-14T00:00:00+00:00"},
        account_id="ACC001", reason="test",
    )
    verifier._verify_flag_readback({"flagged_tx_ids": ["TX001"]}, tx_id="TX001")


def test_proof_rejects_any_denied_or_default_path(tmp_path):
    expected = tmp_path / "owned" / "state.db"
    default = tmp_path / "project" / "data" / "state.db"
    proof = tmp_path / "proof.jsonl"
    proof.write_text(json.dumps({"path": str(default), "allowed": False}) + "\n", encoding="utf-8")

    with pytest.raises(verifier.VerificationError, match="unapproved SQLite path"):
        verifier._read_proof(proof, database=expected, default_database=default)

    proof.write_text(json.dumps({"path": str(expected), "allowed": True}) + "\n", encoding="utf-8")
    records = verifier._read_proof(proof, database=expected, default_database=default)
    assert records == [{"path": str(expected.resolve()), "allowed": True}]


@pytest.mark.parametrize("target_kind", ["outside", "default"])
def test_subprocess_sqlite_instrumentation_blocks_unapproved_paths(tmp_path, target_kind):
    allowed = tmp_path / "owned" / "state.db"
    default = tmp_path / "project" / "data" / "state.db"
    target = tmp_path / "other.db" if target_kind == "outside" else default
    proof = tmp_path / f"proof-{target_kind}.jsonl"
    environment = {
        name: os.environ[name]
        for name in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP")
        if name in os.environ
    }
    environment.update({
        "TRFC_STATE_DB": str(allowed),
        "TRFC_DEFAULT_STATE_DB": str(default),
        "TRFC_DB_PROOF_FILE": str(proof),
        "TEST_CONNECT_TARGET": str(target),
    })
    script = (
        verifier._SITE_CUSTOMIZE
        + "\nimport os, sqlite3\nsqlite3.connect(os.environ['TEST_CONNECT_TARGET'])\n"
    )

    completed = subprocess.run(
        [sys.executable, "-c", script], env=environment,
        capture_output=True, text=True, timeout=10, check=False,
    )

    assert completed.returncode != 0
    assert not target.exists()
    assert json.loads(proof.read_text(encoding="utf-8")) == {
        "path": str(target.resolve()), "allowed": False,
    }


def test_timed_step_reports_context_and_does_not_print_exception_text(capsys, monkeypatch):
    async def fail_wait(_awaitable, timeout):
        assert timeout == 10.0
        raise RuntimeError("account=private-example")

    monkeypatch.setattr(verifier.asyncio, "wait_for", fail_wait)
    with pytest.raises(verifier.VerificationError, match="RuntimeError"):
        _drive_without_loop(verifier._timed_step("tool discovery and schemas", object()))

    output = capsys.readouterr().out
    assert "START tool discovery and schemas timeout=10.0s" in output
    assert "FAIL tool discovery and schemas elapsed=" in output
    assert "error=RuntimeError" in output
    assert "private-example" not in output


def test_timed_step_has_a_bounded_timeout(capsys, monkeypatch):
    async def timeout_wait(_awaitable, timeout):
        assert timeout == 0.001
        raise asyncio.TimeoutError

    monkeypatch.setattr(verifier.asyncio, "wait_for", timeout_wait)
    with pytest.raises(verifier.VerificationError, match="timed out after 0.0s"):
        _drive_without_loop(verifier._timed_step("test stage", object(), timeout=0.001))

    assert "FAIL test stage elapsed=" in capsys.readouterr().out


def test_child_environment_does_not_copy_api_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "must-not-be-copied")
    monkeypatch.setenv("LLM_API_KEY", "must-not-be-copied-either")

    child = verifier._child_environment(tmp_path / "state.db", tmp_path / "proof.jsonl", tmp_path)

    assert "GROQ_API_KEY" not in child
    assert "LLM_API_KEY" not in child


def test_server_exit_status_keeps_only_exit_code_and_error_type(tmp_path):
    status_file = tmp_path / "server-exit.json"
    status_file.write_text(
        json.dumps({"exit_code": 7, "error_type": "RuntimeError", "message": "sensitive"}),
        encoding="utf-8",
    )

    assert verifier._read_server_exit_status(status_file) == {
        "exit_code": 7, "error_type": "RuntimeError",
    }
    assert "sensitive" not in repr(verifier._read_server_exit_status(status_file))
    compile(verifier._SERVER_LAUNCHER, "mcp_server_launcher", "exec")


def test_event_loop_initialization_timeout_is_reported_before_mcp_start(monkeypatch, capsys):
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def blocked_loop_creation():
        entered.set()
        try:
            release.wait(timeout=2)
            raise RuntimeError("simulated loop creation failure")
        finally:
            finished.set()

    monkeypatch.setattr(verifier.asyncio, "new_event_loop", blocked_loop_creation)
    checks = {"asyncio event loop initialization": None}
    with pytest.raises(verifier.VerificationError, match="MCP subprocess was not started"):
        verifier._run_async_bounded(
            lambda: pytest.fail("MCP coroutine must not start"),
            diagnostic_only=True,
            startup_timeout=0.01,
            checks=checks,
        )

    assert entered.is_set()
    assert checks["asyncio event loop initialization"] is False
    assert "error=TimeoutError MCP_subprocess_not_started" in capsys.readouterr().out
    release.set()
    assert finished.wait(timeout=1)


def test_diagnostic_mode_calls_only_read_tool_and_captures_sanitized_stderr(
    monkeypatch, tmp_path, capsys
):
    from contextlib import asynccontextmanager

    calls = []

    @asynccontextmanager
    async def fake_stdio(_parameters, errlog=None):
        assert errlog is not None
        assert errlog.fileno() >= 0
        errlog.write("account_id=ACC001 password=local-test-value\n")
        errlog.flush()
        yield object(), object()

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def initialize(self):
            return None

        async def list_tools(self):
            return SimpleNamespace(tools=[SimpleNamespace(
                name="get_account_risk_status",
                input_schema={
                    "properties": {"account_id": {"type": "string"}},
                    "required": ["account_id"],
                },
            )])

        async def call_tool(self, name, arguments):
            calls.append((name, arguments))
            return SimpleNamespace(
                isError=False,
                content=[SimpleNamespace(text='{"account_id":"ACC001","frozen":false}')],
            )

    monkeypatch.setattr(verifier, "stdio_client", fake_stdio)
    monkeypatch.setattr(verifier, "ClientSession", lambda *_args: FakeSession())
    async def complete_immediately(awaitable, timeout):
        assert timeout > 0
        return await awaitable

    monkeypatch.setattr(verifier.asyncio, "wait_for", complete_immediately)
    step_names = verifier.DIAGNOSTIC_STEPS
    checks = {name: None for name in step_names}

    _drive_without_loop(verifier._verify_mcp(
        tmp_path / "state.db", tmp_path / "proof.jsonl", tmp_path / "probe", checks,
        diagnostic_only=True,
    ))

    assert calls == [("get_account_risk_status", {"account_id": "ACC001"})]
    assert checks["MCP initialize handshake"] is True
    assert checks["baseline readback"] is True
    assert checks["MCP subprocess shutdown"] is True
    stderr = capsys.readouterr().err
    assert "MCP subprocess stderr:" in stderr
    assert "local-test-value" not in stderr
    assert "ACC001" not in stderr


def test_risk_status_datetime_fields_serialize_to_iso8601_json():
    from trfc.mcp_server.server import _to_json_serializable
    from trfc.tools.schemas import RiskStatus

    frozen_at = datetime(2026, 10, 14, 1, 2, 3, tzinfo=timezone.utc)
    checked_at = datetime(2026, 10, 14, 1, 2, 4, tzinfo=timezone.utc)
    status = RiskStatus(
        account_id="ACC001",
        frozen=False,
        freeze_reason=None,
        frozen_at=frozen_at,
        checked_at=checked_at,
    )

    payload = _to_json_serializable(status)
    round_tripped = json.loads(json.dumps(payload))

    assert round_tripped["frozen_at"] == frozen_at.isoformat()
    assert round_tripped["checked_at"] == checked_at.isoformat()

    parsed = verifier._tool_payload(
        SimpleNamespace(
            isError=False,
            content=[SimpleNamespace(text=json.dumps(payload))],
        ),
        "get_account_risk_status",
    )
    assert parsed["account_id"] == "ACC001"
    assert parsed["frozen"] is False
    assert parsed["checked_at"] == checked_at.isoformat()
