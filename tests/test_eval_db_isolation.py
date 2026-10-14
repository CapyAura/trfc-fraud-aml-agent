"""Fail-closed evaluation DB configuration checks; no SQLite is opened."""

from pathlib import Path

import pytest

from eval.database_isolation import (
    DATABASE_PATH_ENV,
    REQUIRE_ISOLATED_ENV,
    DatabaseIsolationError,
    require_isolated_database,
)


def _environment(path: Path) -> dict[str, str]:
    return {
        REQUIRE_ISOLATED_ENV: "1",
        DATABASE_PATH_ENV: str(path),
    }


def test_missing_isolation_setting_fails_closed(tmp_path):
    with pytest.raises(DatabaseIsolationError, match="TRFC_REQUIRE_ISOLATED_DB=1"):
        require_isolated_database({}, default_database=tmp_path / "default.db")


@pytest.mark.parametrize("path", [None, "", "   "])
def test_missing_database_path_fails_closed(tmp_path, path):
    env = {REQUIRE_ISOLATED_ENV: "1"}
    if path is not None:
        env[DATABASE_PATH_ENV] = path
    with pytest.raises(DatabaseIsolationError, match="explicit TRFC_STATE_DB"):
        require_isolated_database(env, default_database=tmp_path / "default.db")


def test_relative_database_path_is_rejected(tmp_path):
    with pytest.raises(DatabaseIsolationError, match="absolute path"):
        require_isolated_database(
            _environment(Path("relative-state.db")),
            default_database=tmp_path / "default.db",
        )


def test_default_database_path_is_rejected_without_opening_it(tmp_path):
    default_db = tmp_path / "default.db"
    with pytest.raises(DatabaseIsolationError, match="default data/state.db"):
        require_isolated_database(
            _environment(default_db), default_database=default_db
        )


def test_symlink_resolving_to_default_database_is_rejected(tmp_path):
    default_db = tmp_path / "default.db"
    default_db.touch()
    alias = tmp_path / "isolated-alias.db"
    try:
        alias.symlink_to(default_db)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable on this Windows environment")

    with pytest.raises(DatabaseIsolationError, match="default data/state.db"):
        require_isolated_database(
            _environment(alias), default_database=default_db
        )


def test_directory_is_not_accepted_as_database_path(tmp_path):
    directory = tmp_path / "database-directory"
    directory.mkdir()
    with pytest.raises(DatabaseIsolationError, match="not a directory"):
        require_isolated_database(
            _environment(directory), default_database=tmp_path / "default.db"
        )


def test_explicit_temporary_database_path_is_accepted(tmp_path):
    database = tmp_path / "isolated-state.db"
    resolved = require_isolated_database(
        _environment(database), default_database=tmp_path / "default.db"
    )
    assert resolved == database.resolve()
    assert not database.exists()  # Validation does not create or open SQLite.


def test_evaluate_rejects_missing_isolation_before_adapter_or_output(
    tmp_path, monkeypatch
):
    from eval.run_eval import evaluate

    monkeypatch.delenv(REQUIRE_ISOLATED_ENV, raising=False)
    monkeypatch.delenv(DATABASE_PATH_ENV, raising=False)
    output = tmp_path / "not-written" / "results.jsonl"
    calls = []

    async def adapter(_case):
        calls.append(True)
        return {"answer": "must not run", "actual_outcome": "answer"}

    coroutine = evaluate([], adapter, output)
    with pytest.raises(DatabaseIsolationError):
        coroutine.send(None)
    assert not calls
    assert not output.exists()


def test_cli_rejects_missing_isolation_before_loading_adapter(
    tmp_path, monkeypatch
):
    import sys

    from eval import run_eval

    monkeypatch.delenv(REQUIRE_ISOLATED_ENV, raising=False)
    monkeypatch.delenv(DATABASE_PATH_ENV, raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_eval",
            "--testset",
            str(tmp_path / "testset.jsonl"),
            "--output",
            str(tmp_path / "results.jsonl"),
            "--agent-adapter",
            "module_that_must_not_be_imported:run",
        ],
    )
    monkeypatch.setattr(run_eval, "load_testset", lambda _path: [])
    monkeypatch.setattr(
        run_eval,
        "_load_adapter",
        lambda _spec: pytest.fail("adapter was imported before isolation validation"),
    )

    with pytest.raises(SystemExit) as raised:
        run_eval.main()
    assert raised.value.code == 2
    assert not (tmp_path / "results.jsonl").exists()
