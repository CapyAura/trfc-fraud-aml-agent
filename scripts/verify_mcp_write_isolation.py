"""Verify real MCP Freeze/Flag writes stay inside a disposable SQLite DB.

This verification calls only the local stdio MCP server. It never imports or
calls the agent/LLM. All state is created by this script's TemporaryDirectory
and is removed when the script exits.
"""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack, closing, contextmanager
import faulthandler
import json
import os
import queue
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import threading
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from eval.redaction import redact_for_log
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from trfc.tools import state


_SITE_CUSTOMIZE = r'''
import json
import os
import sqlite3
from pathlib import Path

_real_connect = sqlite3.connect
_expected = Path(os.environ["TRFC_STATE_DB"]).expanduser().resolve(strict=False)
_default = Path(os.environ["TRFC_DEFAULT_STATE_DB"]).expanduser().resolve(strict=False)
_proof = Path(os.environ["TRFC_DB_PROOF_FILE"])

def _guarded_connect(database, *args, **kwargs):
    try:
        actual = Path(os.fsdecode(os.fspath(database))).expanduser().resolve(strict=False)
    except Exception:
        actual = None
    allowed = actual is not None and actual == _expected and actual != _default
    entry = {"path": str(actual) if actual is not None else "<unresolvable>", "allowed": allowed}
    with _proof.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(entry) + "\n")
    if not allowed:
        raise PermissionError("MCP subprocess attempted an unapproved SQLite path")
    return _real_connect(database, *args, **kwargs)

sqlite3.connect = _guarded_connect
'''

_SERVER_LAUNCHER = r'''
import json
import os
import runpy
from pathlib import Path

_status_path = Path(os.environ["TRFC_SERVER_EXIT_FILE"])
def _record(code, error_type=None):
    _status_path.write_text(json.dumps({"exit_code": code, "error_type": error_type}), encoding="utf-8")

try:
    runpy.run_module("trfc.mcp_server.server", run_name="__main__")
except SystemExit as exc:
    code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    _record(code)
    raise SystemExit(code)
except BaseException as exc:
    _record(1, type(exc).__name__)
    raise
else:
    _record(0)
'''

REQUIRED_STEPS = (
    "temporary workspace and database",
    "asyncio event loop initialization",
    "MCP subprocess startup",
    "MCP session setup",
    "MCP initialize handshake",
    "tool discovery and schemas",
    "baseline readback",
    "Freeze tool call",
    "Freeze readback",
    "Flag tool call",
    "Flag readback",
    "MCP server exit status",
    "subprocess SQLite path isolation",
    "post-process SQLite state verification",
)

DIAGNOSTIC_STEPS = (
    "temporary workspace and database",
    "asyncio event loop initialization",
    "MCP subprocess startup",
    "MCP session setup",
    "MCP initialize handshake",
    "tool discovery and schemas",
    "baseline readback",
    "MCP subprocess shutdown",
    "MCP server exit status",
    "subprocess SQLite path isolation",
)

STEP_TIMEOUTS = {
    "MCP subprocess startup": 10.0,
    "MCP session setup": 5.0,
    "MCP initialize handshake": 10.0,
    "tool discovery and schemas": 10.0,
    "baseline readback": 10.0,
    "Freeze tool call": 10.0,
    "Freeze readback": 10.0,
    "Flag tool call": 10.0,
    "Flag readback": 10.0,
    "MCP subprocess shutdown": 10.0,
}
EVENT_LOOP_STARTUP_TIMEOUT = 15.0


class VerificationError(RuntimeError):
    """A safe, user-readable verification failure."""


async def _timed_step(name: str, awaitable: Any, timeout: float | None = None) -> Any:
    """Wait for one MCP stage and report safe timing without payloads/errors."""
    limit = STEP_TIMEOUTS.get(name, 10.0) if timeout is None else timeout
    started = time.monotonic()
    print(f"START {name} timeout={limit:.1f}s", flush=True)
    try:
        result = await asyncio.wait_for(awaitable, timeout=limit)
    except asyncio.TimeoutError:
        elapsed = time.monotonic() - started
        print(f"FAIL {name} elapsed={elapsed:.2f}s error=TimeoutError", flush=True)
        raise VerificationError(f"{name} timed out after {limit:.1f}s") from None
    except Exception as exc:
        elapsed = time.monotonic() - started
        winerror = getattr(exc, "winerror", None)
        suffix = f" winerror={winerror}" if isinstance(winerror, int) else ""
        print(
            f"FAIL {name} elapsed={elapsed:.2f}s error={type(exc).__name__}{suffix}",
            flush=True,
        )
        raise VerificationError(f"{name} failed ({type(exc).__name__}{suffix})") from None
    elapsed = time.monotonic() - started
    print(f"PASS {name} elapsed={elapsed:.2f}s", flush=True)
    return result


async def _await_task(task: asyncio.Task[Any]) -> Any:
    return await task


def _run_async_bounded(
    coroutine_factory: Any, *, diagnostic_only: bool,
    startup_timeout: float = EVENT_LOOP_STARTUP_TIMEOUT,
    checks: dict[str, bool | None] | None = None,
) -> None:
    """Bound event-loop construction separately from MCP operations.

    Windows Proactor loop construction may block synchronously before
    ``asyncio.run`` starts the coroutine. A daemon worker lets the verifier
    report that phase and return without changing the process-wide loop policy.
    """
    loop_ready = threading.Event()
    abort_before_start = threading.Event()
    outcome: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)
    shared: dict[str, Any] = {}
    started = time.monotonic()

    if diagnostic_only:
        timeout_names = (
            "MCP subprocess startup", "MCP session setup", "MCP initialize handshake",
            "tool discovery and schemas", "baseline readback", "MCP subprocess shutdown",
        )
    else:
        timeout_names = tuple(STEP_TIMEOUTS)
    execution_timeout = sum(STEP_TIMEOUTS[name] for name in timeout_names) + 15.0

    def tracked_loop_factory() -> asyncio.AbstractEventLoop:
        loop = asyncio.new_event_loop()
        shared["loop"] = loop
        loop_ready.set()
        return loop

    def worker() -> None:
        try:
            with asyncio.Runner(loop_factory=tracked_loop_factory) as runner:
                loop = runner.get_loop()

                async def guarded() -> Any:
                    if abort_before_start.is_set():
                        return None
                    return await coroutine_factory()

                task = loop.create_task(guarded())
                shared["task"] = task
                result = runner.run(_await_task(task))
            outcome.put((True, result))
        except BaseException as exc:
            try:
                outcome.put_nowait((False, exc))
            except queue.Full:
                pass

    worker_thread = threading.Thread(
        target=worker, name="c4-mcp-verifier-asyncio", daemon=True
    )
    print(
        f"START asyncio event loop initialization timeout={startup_timeout:.1f}s",
        flush=True,
    )
    worker_thread.start()
    if not loop_ready.wait(startup_timeout):
        abort_before_start.set()
        if checks is not None:
            checks["asyncio event loop initialization"] = False
        elapsed = time.monotonic() - started
        print(
            f"FAIL asyncio event loop initialization elapsed={elapsed:.2f}s "
            "error=TimeoutError MCP_subprocess_not_started",
            flush=True,
        )
        raise VerificationError(
            f"asyncio event loop initialization timed out after "
            f"{startup_timeout:.1f}s; MCP subprocess was not started"
        )

    if checks is not None:
        checks["asyncio event loop initialization"] = True
    print(
        f"PASS asyncio event loop initialization elapsed={time.monotonic() - started:.2f}s",
        flush=True,
    )
    try:
        succeeded, value = outcome.get(timeout=execution_timeout)
    except queue.Empty:
        abort_before_start.set()
        loop = shared.get("loop")
        task = shared.get("task")
        if loop is not None and task is not None and not task.done():
            loop.call_soon_threadsafe(task.cancel)
        worker_thread.join(timeout=5.0)
        raise VerificationError(
            f"MCP async workflow exceeded its {execution_timeout:.1f}s overall bound"
        ) from None
    if not succeeded:
        if isinstance(value, VerificationError):
            raise value
        winerror = getattr(value, "winerror", None)
        suffix = f" winerror={winerror}" if isinstance(winerror, int) else ""
        raise VerificationError(
            f"asyncio/MCP worker failed ({type(value).__name__}{suffix})"
        ) from None


def _resolved(path: Path | str) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def _authorize_database_path(
    actual: Path | str,
    *,
    allowed_database: Path | str,
    default_database: Path | str,
) -> Path:
    """Require an exact normalized match to the one allowed temp DB."""
    actual_path = _resolved(actual)
    expected_path = _resolved(allowed_database)
    default_path = _resolved(default_database)
    if expected_path == default_path:
        raise VerificationError("The allowed database resolves to the project default")
    if actual_path == default_path:
        raise VerificationError("The project default database is never an allowed target")
    if actual_path != expected_path:
        raise VerificationError("SQLite path is outside the explicitly allowed temporary database")
    return actual_path


@contextmanager
def _temporary_workspace(parent: Path | None = None):
    """Yield a temp path whose cleanup is owned by TemporaryDirectory."""
    # Keep the verifier's workspace in the already-writable project parent on
    # this Windows setup; the system temp directory has denied writes before.
    expected_parent = Path(parent or ROOT.parent).resolve()
    with tempfile.TemporaryDirectory(
        prefix="trfc-mcp-write-isolation-", dir=expected_parent
    ) as temporary:
        root = Path(temporary).resolve()
        if root.parent != expected_parent:
            raise VerificationError("Temporary workspace escaped its requested parent")
        yield root


def _field(value: Any, name: str, fallback: str | None = None, default: Any = None) -> Any:
    if isinstance(value, dict):
        if name in value:
            return value[name]
        return value.get(fallback, default) if fallback else default
    item = getattr(value, name, None)
    if item is not None:
        return item
    return getattr(value, fallback, default) if fallback else default



def _tool_payload(result, tool_name: str):
    content = _field(result, "content", default=[]) or []
    text_blocks = [
        _field(item, "text")
        for item in content
        if isinstance(_field(item, "text"), str)
    ]

    if _field(result, "is_error", "isError", False):
        details = "\n".join(text_blocks).strip()
        raise VerificationError(
            f"MCP tool {tool_name} returned an error: "
            f"{details or 'No error details returned by MCP'}"
        )

    if not text_blocks:
        raise VerificationError(
            f"MCP tool {tool_name} returned no text content"
        )

    try:
        payload = json.loads(text_blocks[0])
    except json.JSONDecodeError as exc:
        raise VerificationError(
            f"MCP tool {tool_name} returned invalid JSON: "
            f"{text_blocks[0][:500]!r}"
        ) from exc

    if isinstance(payload, str) and payload.startswith("Error:"):
        raise VerificationError(
            f"MCP tool {tool_name} failed: {payload}"
        )

    return payload



def _require_discovered_tool(tools: list[Any], name: str, required_args: set[str]) -> None:
    tool = next((item for item in tools if _field(item, "name") == name), None)
    if tool is None:
        raise VerificationError(f"Required MCP tool was not discovered: {name}")
    schema = _field(tool, "input_schema", "inputSchema", {}) or {}
    properties = schema.get("properties") if isinstance(schema, dict) else None
    required = schema.get("required") if isinstance(schema, dict) else None
    if not isinstance(properties, dict) or not isinstance(required, list):
        raise VerificationError(f"MCP tool {name} has no usable input schema")
    if not required_args.issubset(properties) or not required_args.issubset(set(required)):
        raise VerificationError(f"MCP tool {name} schema does not match expected arguments")
    if any(properties.get(arg, {}).get("type") != "string" for arg in required_args):
        raise VerificationError(f"MCP tool {name} schema has unexpected argument types")


def _verify_freeze_readback(payload: Any, *, account_id: str, reason: str) -> None:
    if not isinstance(payload, dict) or payload.get("account_id") != account_id:
        raise VerificationError("Freeze readback is missing the expected account")
    if payload.get("frozen") is not True or payload.get("freeze_reason") != reason:
        raise VerificationError("Freeze readback did not confirm frozen state and reason")
    if not isinstance(payload.get("frozen_at"), str) or not payload["frozen_at"].strip():
        raise VerificationError("Freeze readback is missing frozen_at")


def _verify_flag_readback(payload: Any, *, tx_id: str) -> None:
    if not isinstance(payload, dict):
        raise VerificationError("Flag readback is missing structured risk status")
    flagged_ids = payload.get("flagged_tx_ids")
    if not isinstance(flagged_ids, list) or tx_id not in flagged_ids:
        raise VerificationError("Flag readback did not confirm the transaction")


def _verify_sqlite_state(database: Path, *, account_id: str, freeze_reason: str,
                         tx_id: str, flag_reason: str) -> None:
    # sqlite3.Connection.__exit__ commits/rolls back but does not close the
    # connection. Close explicitly before TemporaryDirectory removes the DB.
    with closing(sqlite3.connect(database)) as connection:
        account = connection.execute(
            "SELECT frozen, freeze_reason, frozen_at FROM accounts WHERE account_id = ?",
            (account_id,),
        ).fetchone()
        transaction = connection.execute(
            "SELECT flagged FROM transactions WHERE tx_id = ?", (tx_id,)
        ).fetchone()
        flag = connection.execute(
            "SELECT reason, flagged_at FROM flags WHERE tx_id = ?", (tx_id,)
        ).fetchone()
    if account is None or account[0] != 1 or account[1] != freeze_reason:
        raise VerificationError("Post-process SQLite check did not confirm Freeze fields")
    if not isinstance(account[2], str) or not account[2].strip():
        raise VerificationError("Post-process SQLite check found no frozen_at")
    if transaction is None or transaction[0] != 1:
        raise VerificationError("Post-process SQLite check did not confirm transaction.flagged")
    if flag is None or flag[0] != flag_reason or not isinstance(flag[1], str) or not flag[1].strip():
        raise VerificationError("Post-process SQLite check did not confirm flags row")


def _read_proof(proof_file: Path, *, database: Path, default_database: Path) -> list[dict[str, Any]]:
    if not proof_file.is_file():
        raise VerificationError("MCP subprocess produced no SQLite connection proof")
    records = []
    for line_number, line in enumerate(proof_file.read_text(encoding="utf-8").splitlines(), 1):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            raise VerificationError(f"MCP SQLite proof is malformed at line {line_number}") from None
        if not isinstance(entry, dict) or entry.get("allowed") is not True:
            raise VerificationError("MCP subprocess attempted an unapproved SQLite path")
        actual = _authorize_database_path(
            entry.get("path", ""), allowed_database=database,
            default_database=default_database,
        )
        records.append({"path": str(actual), "allowed": True})
    if not records:
        raise VerificationError("MCP subprocess made no instrumented SQLite connections")
    return records


def _read_server_exit_status(path: Path) -> dict[str, Any] | None:
    """Return only safe exit metadata; discard any unexpected message fields."""
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise VerificationError("MCP server exit-status record is malformed") from None
    if not isinstance(value, dict):
        raise VerificationError("MCP server exit-status record is malformed")
    code = value.get("exit_code")
    error_type = value.get("error_type")
    if not isinstance(code, int) or isinstance(code, bool):
        raise VerificationError("MCP server exit-status record is malformed")
    safe = {"exit_code": code}
    if isinstance(error_type, str) and error_type.isidentifier():
        safe["error_type"] = error_type
    return safe


def _child_environment(database: Path, proof_file: Path, probe_dir: Path) -> dict[str, str]:
    environment = {
        "PYTHONPATH": os.pathsep.join((str(probe_dir), str(SOURCE))),
        state.DB_PATH_ENV: str(database),
        state.REQUIRE_ISOLATED_DB_ENV: "1",
        "TRFC_DEFAULT_STATE_DB": str(state.DB_PATH.resolve()),
        "TRFC_DB_PROOF_FILE": str(proof_file),
        "TRFC_SERVER_EXIT_FILE": str(proof_file.with_name("server-exit.json")),
    }
    # Preserve only variables needed to launch Python on Windows. No credentials
    # or the caller's full environment are copied into the MCP subprocess.
    for name in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP"):
        if name in os.environ:
            environment[name] = os.environ[name]
    return environment


async def _verify_mcp(database: Path, proof_file: Path, probe_dir: Path,
                      checks: dict[str, bool | None], *, diagnostic_only: bool = False) -> None:
    child_env = _child_environment(database, proof_file, probe_dir)
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-c", _SERVER_LAUNCHER],
        env=child_env,
        cwd=ROOT,
    )
    stack = AsyncExitStack()
    # MCP's stdio client passes errlog directly as subprocess stderr. Use a real
    # file descriptor; StringIO has no fileno() and fails on Windows.
    stderr_sink = tempfile.TemporaryFile(mode="w+t", encoding="utf-8")
    failure: BaseException | None = None
    try:
        read_stream, write_stream = await _timed_step(
            "MCP subprocess startup",
            stack.enter_async_context(stdio_client(parameters, errlog=stderr_sink)),
        )
        checks["MCP subprocess startup"] = True
        session = await _timed_step(
            "MCP session setup", stack.enter_async_context(ClientSession(read_stream, write_stream))
        )
        checks["MCP session setup"] = True
        await _timed_step("MCP initialize handshake", session.initialize())
        checks["MCP initialize handshake"] = True

        listing = await _timed_step("tool discovery and schemas", session.list_tools())
        discovered = listing.tools
        _require_discovered_tool(discovered, "get_account_risk_status", {"account_id"})
        if not diagnostic_only:
            _require_discovered_tool(
                discovered, "freeze_account_temporarily", {"account_id", "reason"}
            )
            _require_discovered_tool(discovered, "flag_suspicious_tx", {"tx_id", "reason"})
        checks["tool discovery and schemas"] = True

        async def call(name: str, arguments: dict[str, str], step: str) -> Any:
            result = await _timed_step(step, session.call_tool(name, arguments))
            return _tool_payload(result, name)

        baseline = await call(
            "get_account_risk_status", {"account_id": "ACC001"}, "baseline readback"
        )
        if not isinstance(baseline, dict) or baseline.get("frozen") is not False:
            raise VerificationError("Seeded baseline did not show ACC001 unfrozen")
        checks["baseline readback"] = True

        if not diagnostic_only:
            freeze_reason = "isolated MCP write verification"
            freeze_ack = await call(
                "freeze_account_temporarily",
                {"account_id": "ACC001", "reason": freeze_reason},
                "Freeze tool call",
            )
            if not isinstance(freeze_ack, dict) or freeze_ack.get("ok") is not True:
                raise VerificationError("Freeze MCP tool did not return a successful acknowledgement")
            checks["Freeze tool call"] = True

            frozen = await call(
                "get_account_risk_status", {"account_id": "ACC001"}, "Freeze readback"
            )
            _verify_freeze_readback(frozen, account_id="ACC001", reason=freeze_reason)
            checks["Freeze readback"] = True

            flag_reason = "isolated MCP write verification"
            flag_ack = await call(
                "flag_suspicious_tx", {"tx_id": "TX001", "reason": flag_reason},
                "Flag tool call",
            )
            if (not isinstance(flag_ack, dict) or flag_ack.get("ok") is not True
                    or flag_ack.get("tx_id") != "TX001"):
                raise VerificationError("Flag MCP tool did not return a successful acknowledgement")
            checks["Flag tool call"] = True

            flagged = await call(
                "get_account_risk_status", {"account_id": "ACC001"}, "Flag readback"
            )
            _verify_flag_readback(flagged, tx_id="TX001")
            checks["Flag readback"] = True
    except BaseException as exc:
        failure = exc
    try:
        await _timed_step("MCP subprocess shutdown", stack.aclose())
        checks["MCP subprocess shutdown"] = True
    except BaseException as exc:
        if failure is None:
            failure = exc
    stderr_sink.seek(0)
    stderr_output = stderr_sink.read()
    stderr_sink.close()
    if stderr_output:
        print(
            "MCP subprocess stderr:\n" + redact_for_log(stderr_output),
            file=sys.stderr,
        )
    exit_status = _read_server_exit_status(Path(child_env["TRFC_SERVER_EXIT_FILE"]))
    if exit_status is None:
        print("MCP server exit_code=unavailable", flush=True)
        checks["MCP server exit status"] = None
    else:
        code = exit_status["exit_code"]
        error_type = exit_status.get("error_type")
        suffix = f" error_type={error_type}" if error_type else ""
        print(f"MCP server exit_code={code}{suffix}", flush=True)
        checks["MCP server exit status"] = code == 0
        if code != 0:
            if failure is None:
                failure = VerificationError("MCP server subprocess exited with a nonzero status")
    if failure is not None:
        raise failure


def _run_verification(checks: dict[str, bool | None], *, diagnostic_only: bool = False) -> Path:
    with _temporary_workspace() as root:
        database = root / "state.db"
        _authorize_database_path(
            database, allowed_database=database, default_database=state.DB_PATH
        )
        if not root.is_dir():
            raise VerificationError("Temporary workspace path could not be validated")
        probe_dir = root / "probe"
        probe_dir.mkdir()
        proof_file = root / "sqlite-paths.jsonl"

        old_db = os.environ.get(state.DB_PATH_ENV)
        old_require = os.environ.get(state.REQUIRE_ISOLATED_DB_ENV)
        os.environ[state.DB_PATH_ENV] = str(database)
        os.environ[state.REQUIRE_ISOLATED_DB_ENV] = "1"
        try:
            state.reset(database)
        finally:
            if old_db is None:
                os.environ.pop(state.DB_PATH_ENV, None)
            else:
                os.environ[state.DB_PATH_ENV] = old_db
            if old_require is None:
                os.environ.pop(state.REQUIRE_ISOLATED_DB_ENV, None)
            else:
                os.environ[state.REQUIRE_ISOLATED_DB_ENV] = old_require
        checks["temporary workspace and database"] = True

        (probe_dir / "sitecustomize.py").write_text(_SITE_CUSTOMIZE, encoding="utf-8")
        print(f"temporary_database={database}", flush=True)
        if diagnostic_only:
            # The Windows Proactor loop may stall during construction, before
            # the MCP coroutine is scheduled. Dump frames, never local values.
            faulthandler.dump_traceback_later(10.0, file=sys.stderr)
        try:
            _run_async_bounded(
                lambda: _verify_mcp(
                    database, proof_file, probe_dir, checks,
                    diagnostic_only=diagnostic_only,
                ),
                diagnostic_only=diagnostic_only,
                checks=checks,
            )
        finally:
            if diagnostic_only:
                faulthandler.cancel_dump_traceback_later()

        records = _read_proof(proof_file, database=database, default_database=state.DB_PATH)
        checks["subprocess SQLite path isolation"] = all(
            Path(item["path"]) == database.resolve() for item in records
        )
        if not checks["subprocess SQLite path isolation"]:
            raise VerificationError("MCP subprocess SQLite path differed from the temporary DB")

        if not diagnostic_only:
            _verify_sqlite_state(
                database, account_id="ACC001", freeze_reason="isolated MCP write verification",
                tx_id="TX001", flag_reason="isolated MCP write verification",
            )
            checks["post-process SQLite state verification"] = True
        return database


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--diagnostic-only", action="store_true",
        help="run startup, initialize, discovery and read-only status only; never call write tools",
    )
    args = parser.parse_args(argv)
    steps = DIAGNOSTIC_STEPS if args.diagnostic_only else REQUIRED_STEPS
    checks: dict[str, bool | None] = {name: None for name in steps}
    database: Path | None = None
    try:
        database = _run_verification(checks, diagnostic_only=args.diagnostic_only)
    except KeyboardInterrupt:
        if not any(checks[name] is False for name in steps):
            failed_step = next((name for name in steps if checks[name] is None), None)
            if failed_step is not None:
                checks[failed_step] = False
        print("FAIL verification: interrupted while waiting for local MCP/asyncio")
    except Exception as exc:
        # Do not print raw subprocess or tool exception text; it may include
        # arguments. Include only exception type and Windows error number.
        if not any(checks[name] is False for name in steps):
            failed_step = next((name for name in steps if checks[name] is None), None)
            if failed_step is not None:
                checks[failed_step] = False
        winerror = getattr(exc, "winerror", None)
        suffix = f" (winerror={winerror})" if winerror is not None else ""
        if isinstance(exc, VerificationError):
            print(f"FAIL verification: {exc}")
        else:
            print(f"FAIL verification: {type(exc).__name__}{suffix}")

    for step in steps:
        if checks[step] is True:
            print(f"PASS {step}")
        elif checks[step] is False:
            print(f"FAIL {step}")
        else:
            print(f"NOT RUN {step}")
    if database is not None:
        print(f"temporary_database={database}")
    else:
        print("temporary_database=<cleaned after failed verification>")
    return 0 if all(value is True for value in checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
