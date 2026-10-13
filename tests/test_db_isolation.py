"""Database path isolation checks; all state is confined to pytest tmp_path."""

import sqlite3
from pathlib import Path

import pytest


@pytest.fixture
def isolated_database(tmp_path, monkeypatch):
    from trfc.tools import state

    monkeypatch.setattr(state, "DB_PATH", tmp_path / "default-state.db")
    database = tmp_path / "isolated-state.db"
    monkeypatch.setenv(state.DB_PATH_ENV, str(database))
    monkeypatch.setenv(state.REQUIRE_ISOLATED_DB_ENV, "1")
    state.reset(database)
    return database


def test_tool_reads_and_writes_use_only_configured_database(
    isolated_database, monkeypatch
):
    from trfc.tools import impl, state

    opened_paths = []
    sqlite_connect = sqlite3.connect

    def recording_connect(database, *args, **kwargs):
        opened_paths.append(Path(database).resolve())
        return sqlite_connect(database, *args, **kwargs)

    monkeypatch.setattr(state.sqlite3, "connect", recording_connect)

    transactions = impl.get_transactions("ACC001", "2026-10-09", "2026-10-09")
    assert len(transactions) == 4
    status_before = impl.get_account_risk_status("ACC001")
    assert status_before.frozen is False

    freeze_ack = impl.freeze_account_temporarily("ACC001", "isolated test")
    assert freeze_ack.ok is True
    flag_ack = impl.flag_suspicious_tx("TX001", "isolated test")
    assert flag_ack.ok is True

    status_after = impl.get_account_risk_status("ACC001")
    assert status_after.frozen is True
    assert status_after.flagged_tx_ids == ["TX001"]
    assert opened_paths
    assert set(opened_paths) == {isolated_database.resolve()}
    assert isolated_database.resolve() != state.DB_PATH.resolve()


def test_invalid_database_configuration_fails_closed(tmp_path, monkeypatch):
    from trfc.tools import impl, state

    parent_file = tmp_path / "not-a-directory"
    parent_file.write_text("block directory creation", encoding="utf-8")
    invalid_path = parent_file / "state.db"
    monkeypatch.setenv(state.DB_PATH_ENV, str(invalid_path))
    monkeypatch.setenv(state.REQUIRE_ISOLATED_DB_ENV, "1")

    result = impl.get_account_risk_status("ACC001")
    assert isinstance(result, str) and result.startswith("Error:")
    assert state.resolve_db_path() == invalid_path.resolve()


@pytest.mark.parametrize("write_tool", ["freeze", "flag"])
def test_isolation_guard_blocks_writes_to_default_database(write_tool, monkeypatch, tmp_path):
    from trfc.tools import impl, state

    monkeypatch.setattr(state, "DB_PATH", tmp_path / "default-state.db")
    monkeypatch.setenv(state.DB_PATH_ENV, str(state.DB_PATH))
    monkeypatch.setenv(state.REQUIRE_ISOLATED_DB_ENV, "1")

    if write_tool == "freeze":
        result = impl.freeze_account_temporarily("ACC001", "must be blocked")
    else:
        result = impl.flag_suspicious_tx("TX001", "must be blocked")

    assert isinstance(result, str) and result.startswith("Error:")
    assert "blocked" in result.lower()


@pytest.mark.parametrize("flag_value", [None, "0", "false", "no"])
def test_write_guard_requires_explicit_enabled_flag(tmp_path, monkeypatch, flag_value):
    from trfc.tools import state

    monkeypatch.setenv(state.DB_PATH_ENV, str(tmp_path / "isolated.db"))
    if flag_value is None:
        monkeypatch.delenv(state.REQUIRE_ISOLATED_DB_ENV, raising=False)
    else:
        monkeypatch.setenv(state.REQUIRE_ISOLATED_DB_ENV, flag_value)

    with pytest.raises(RuntimeError, match="enable isolated writes"):
        state.require_isolated_database_for_writes()


@pytest.mark.parametrize("database_value", [None, "", "   "])
def test_write_guard_requires_nonempty_database_setting(monkeypatch, database_value):
    from trfc.tools import state

    monkeypatch.setenv(state.REQUIRE_ISOLATED_DB_ENV, "1")
    if database_value is None:
        monkeypatch.delenv(state.DB_PATH_ENV, raising=False)
    else:
        monkeypatch.setenv(state.DB_PATH_ENV, database_value)

    with pytest.raises(RuntimeError, match="must name an isolated database"):
        state.require_isolated_database_for_writes()


def test_write_guard_rejects_relative_database_path(monkeypatch):
    from trfc.tools import state

    monkeypatch.setenv(state.REQUIRE_ISOLATED_DB_ENV, "1")
    monkeypatch.setenv(state.DB_PATH_ENV, "relative/state.db")

    with pytest.raises(RuntimeError, match="must be an absolute path"):
        state.require_isolated_database_for_writes()


def test_write_guard_fails_closed_when_path_resolution_raises(monkeypatch, tmp_path):
    from trfc.tools import state

    monkeypatch.setenv(state.REQUIRE_ISOLATED_DB_ENV, "1")
    monkeypatch.setenv(state.DB_PATH_ENV, str(tmp_path / "isolated.db"))

    def fail_resolution(_path=None):
        raise OSError("simulated path resolution failure")

    monkeypatch.setattr(state, "resolve_db_path", fail_resolution)

    with pytest.raises(RuntimeError, match="could not be validated"):
        state.require_isolated_database_for_writes()


def test_write_guard_rejects_conflicting_caller_path(tmp_path, monkeypatch):
    from trfc.tools import state

    configured = tmp_path / "configured.db"
    conflicting = tmp_path / "other.db"
    monkeypatch.setenv(state.REQUIRE_ISOLATED_DB_ENV, "1")
    monkeypatch.setenv(state.DB_PATH_ENV, str(configured))

    with pytest.raises(RuntimeError, match="does not match TRFC_STATE_DB"):
        state.require_isolated_database_for_writes(conflicting)


def test_valid_isolated_write_guard_does_not_open_sqlite(tmp_path, monkeypatch):
    from trfc.tools import state

    database = tmp_path / "isolated.db"
    monkeypatch.setenv(state.REQUIRE_ISOLATED_DB_ENV, "true")
    monkeypatch.setenv(state.DB_PATH_ENV, str(database))
    monkeypatch.setattr(state.sqlite3, "connect", pytest.fail)

    assert state.require_isolated_database_for_writes(database) is None
    assert not database.exists()


@pytest.mark.parametrize("write_tool", ["freeze", "flag"])
@pytest.mark.parametrize(
    "configure",
    ["missing_flag", "disabled_flag", "missing_path", "empty_path", "relative_path", "default_path", "invalid_path"],
)
def test_rejected_write_never_opens_sqlite(write_tool, configure, monkeypatch, tmp_path):
    from trfc.tools import impl, state

    monkeypatch.setattr(state.sqlite3, "connect", pytest.fail)
    monkeypatch.delenv(state.REQUIRE_ISOLATED_DB_ENV, raising=False)
    monkeypatch.delenv(state.DB_PATH_ENV, raising=False)
    if configure == "disabled_flag":
        monkeypatch.setenv(state.REQUIRE_ISOLATED_DB_ENV, "0")
        monkeypatch.setenv(state.DB_PATH_ENV, str(tmp_path / "isolated.db"))
    elif configure == "missing_path":
        monkeypatch.setenv(state.REQUIRE_ISOLATED_DB_ENV, "1")
    elif configure == "empty_path":
        monkeypatch.setenv(state.REQUIRE_ISOLATED_DB_ENV, "1")
        monkeypatch.setenv(state.DB_PATH_ENV, " ")
    elif configure == "relative_path":
        monkeypatch.setenv(state.REQUIRE_ISOLATED_DB_ENV, "1")
        monkeypatch.setenv(state.DB_PATH_ENV, "relative.db")
    elif configure == "default_path":
        monkeypatch.setattr(state, "DB_PATH", tmp_path / "default-state.db")
        monkeypatch.setenv(state.REQUIRE_ISOLATED_DB_ENV, "1")
        monkeypatch.setenv(state.DB_PATH_ENV, str(state.DB_PATH))
    elif configure == "invalid_path":
        monkeypatch.setenv(state.REQUIRE_ISOLATED_DB_ENV, "1")
        monkeypatch.setenv(state.DB_PATH_ENV, str(tmp_path / "isolated.db"))

        def fail_resolution(_path=None):
            raise OSError("simulated path resolution failure")

        monkeypatch.setattr(state, "resolve_db_path", fail_resolution)

    if write_tool == "freeze":
        result = impl.freeze_account_temporarily("ACC001", "guard test")
    else:
        result = impl.flag_suspicious_tx("TX001", "guard test")
    assert isinstance(result, str) and result.startswith("Error:")


def test_reset_guard_blocks_default_path_before_database_access(monkeypatch, tmp_path):
    from trfc.tools import state

    monkeypatch.setattr(state, "DB_PATH", tmp_path / "default-state.db")
    monkeypatch.setenv(state.DB_PATH_ENV, str(state.DB_PATH))
    monkeypatch.setenv(state.REQUIRE_ISOLATED_DB_ENV, "1")
    with pytest.raises(RuntimeError, match="blocked"):
        state.reset()


def test_empty_database_override_is_rejected(monkeypatch):
    from trfc.tools import state

    monkeypatch.setenv(state.DB_PATH_ENV, "  ")
    with pytest.raises(ValueError, match="must not be empty"):
        state.resolve_db_path()


def test_default_database_path_is_preserved_when_no_override_is_set(monkeypatch, tmp_path):
    from trfc.tools import state

    monkeypatch.setattr(state, "DB_PATH", tmp_path / "default-state.db")
    monkeypatch.delenv(state.DB_PATH_ENV, raising=False)
    assert state.resolve_db_path() == state.DB_PATH.resolve()


def test_mcp_child_receives_the_same_isolated_database_configuration(
    tmp_path, monkeypatch
):
    from trfc.agent.loop import mcp_server_environment
    from trfc.tools import state

    database = tmp_path / "mcp-state.db"
    monkeypatch.setenv(state.DB_PATH_ENV, str(database))
    monkeypatch.setenv(state.REQUIRE_ISOLATED_DB_ENV, "1")

    environment = mcp_server_environment()
    assert environment[state.DB_PATH_ENV] == str(database.resolve())
    assert environment[state.REQUIRE_ISOLATED_DB_ENV] == "1"
    assert environment["PYTHONPATH"].endswith("src")


def test_mcp_child_preserves_invalid_empty_override_for_fail_closed_behavior(monkeypatch):
    from trfc.agent.loop import mcp_server_environment
    from trfc.tools import state

    monkeypatch.setenv(state.DB_PATH_ENV, " ")
    environment = mcp_server_environment()
    assert environment[state.DB_PATH_ENV] == " "


def test_independent_mcp_client_passes_resolved_isolation_settings(monkeypatch, tmp_path):
    from trfc.mcp_server.client2 import _server_parameters
    from trfc.tools import state

    database = tmp_path / "client-state.db"
    monkeypatch.setenv(state.DB_PATH_ENV, str(database))
    monkeypatch.setenv(state.REQUIRE_ISOLATED_DB_ENV, "1")
    parameters = _server_parameters("python", None)

    assert parameters.env[state.DB_PATH_ENV] == str(database.resolve())
    assert parameters.env[state.REQUIRE_ISOLATED_DB_ENV] == "1"
    assert parameters.env["PYTHONPATH"].startswith(str(Path.cwd() / "src"))


def test_independent_mcp_client_keeps_default_behavior_without_overrides(monkeypatch):
    from trfc.mcp_server.client2 import _server_parameters
    from trfc.tools import state

    monkeypatch.delenv(state.DB_PATH_ENV, raising=False)
    monkeypatch.delenv(state.REQUIRE_ISOLATED_DB_ENV, raising=False)
    parameters = _server_parameters("python", None)
    assert state.DB_PATH_ENV not in parameters.env
    assert state.REQUIRE_ISOLATED_DB_ENV not in parameters.env
