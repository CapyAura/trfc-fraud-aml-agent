"""Fail-closed configuration checks for evaluation runs that may write state."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = ROOT / "data" / "state.db"
DATABASE_PATH_ENV = "TRFC_STATE_DB"
REQUIRE_ISOLATED_ENV = "TRFC_REQUIRE_ISOLATED_DB"
_ENABLED_VALUES = {"1", "true", "yes"}


class DatabaseIsolationError(ValueError):
    """Raised when a real evaluation lacks an explicit isolated DB target."""


def _normalized(path: Path) -> Path:
    """Normalize a path, resolving symlinks without opening the database."""
    return path.expanduser().resolve(strict=False)


def _absolute_normalized(path: Path) -> Path:
    """Normalize spelling without filesystem access."""
    return Path(os.path.normcase(os.path.abspath(os.path.normpath(path))))


def require_isolated_database(
    environ: Mapping[str, str] | None = None,
    *,
    default_database: Path = DEFAULT_DATABASE,
) -> Path:
    """Validate the evaluation DB configuration and return its resolved path.

    This checks configuration only; it does not open or create the SQLite file
    and does not establish that an MCP subprocess used the returned path.
    """
    environment = os.environ if environ is None else environ
    enabled = environment.get(REQUIRE_ISOLATED_ENV, "").strip().lower()
    if enabled not in _ENABLED_VALUES:
        raise DatabaseIsolationError(
            f"Real evaluation requires {REQUIRE_ISOLATED_ENV}=1"
        )

    configured = environment.get(DATABASE_PATH_ENV, "")
    if not isinstance(configured, str) or not configured.strip():
        raise DatabaseIsolationError(
            f"Real evaluation requires an explicit {DATABASE_PATH_ENV} path"
        )

    raw_path = Path(configured).expanduser()
    if not raw_path.is_absolute():
        raise DatabaseIsolationError(
            f"{DATABASE_PATH_ENV} must be an absolute path for real evaluation"
        )

    default_path = _absolute_normalized(default_database)
    if _absolute_normalized(raw_path) == default_path:
        raise DatabaseIsolationError(
            "Real evaluation is blocked because the configured database resolves "
            "to the default data/state.db"
        )
    database_path = _normalized(raw_path)
    if _absolute_normalized(database_path) == default_path:
        raise DatabaseIsolationError(
            "Real evaluation is blocked because the configured database resolves "
            "to the default data/state.db"
        )
    if database_path.exists() and not database_path.is_file():
        raise DatabaseIsolationError(
            f"{DATABASE_PATH_ENV} must identify a SQLite file path, not a directory"
        )
    return database_path
