"""Bounded, offline probes for Windows loopback, socketpair and Proactor startup.

This diagnostic does not import the agent, start MCP, access SQLite, or call an
external service. Each risky initialization runs in a disposable child process
so a blocked socket.accept can be timed out and killed by the parent.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
_INHERITED_ENV = ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP")


@dataclass(frozen=True)
class ProbeResult:
    name: str
    status: str
    elapsed_seconds: float
    return_code: int | None
    stdout: str
    stderr: str


def safe_child_environment(source: dict[str, str] | None = None) -> dict[str, str]:
    """Pass only OS variables needed to launch Python; never copy credentials."""
    parent = os.environ if source is None else source
    return {name: parent[name] for name in _INHERITED_ENV if name in parent}


def run_probe(name: str, code: str, *, timeout: float = 4.0) -> ProbeResult:
    """Run one stdlib-only probe with a hard parent-side process timeout."""
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    started = time.monotonic()
    try:
        process = subprocess.Popen(
            [sys.executable, "-X", "faulthandler", "-c", code],
            cwd=ROOT,
            env=safe_child_environment(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        return ProbeResult(
            name, "failed", time.monotonic() - started, None, "",
            f"child_start_error={type(exc).__name__}",
        )

    try:
        stdout, stderr = process.communicate(timeout=timeout)
        status = "passed" if process.returncode == 0 else "failed"
        return ProbeResult(
            name, status, time.monotonic() - started, process.returncode,
            stdout, stderr,
        )
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate(timeout=5.0)
        return ProbeResult(
            name, "blocked", time.monotonic() - started, process.returncode,
            stdout or "", stderr or "",
        )


_SOCKETPAIR_CODE = r'''import faulthandler, socket, sys
faulthandler.dump_traceback_later(1.0, file=sys.stderr)
left, right = socket.socketpair()
left.close()
right.close()
print("SOCKETPAIR_READY", flush=True)
'''

_PROACTOR_CODE = r'''import asyncio, faulthandler, sys
faulthandler.dump_traceback_later(1.0, file=sys.stderr)
loop = asyncio.ProactorEventLoop()
loop.close()
print("PROACTOR_READY", flush=True)
'''

_TCP_LOOPBACK_CODE = r'''import faulthandler, socket, sys
faulthandler.dump_traceback_later(1.0, file=sys.stderr)
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
    server.settimeout(1.0)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
        client.settimeout(1.0)
        client.connect(server.getsockname())
        peer, _ = server.accept()
        peer.close()
print("TCP_LOOPBACK_ACCEPT_READY", flush=True)
'''

_SUBPROCESS_CODE = r'''import subprocess, sys
child = subprocess.run([sys.executable, "-c", "print('CHILD_READY')"],
                       capture_output=True, text=True, timeout=2.0, check=True)
print(child.stdout.strip(), flush=True)
'''

_POLICY_CODE = r'''import asyncio, platform, sys
policy = type(asyncio.get_event_loop_policy()).__name__
print("implementation=" + sys.implementation.name)
print("version=" + platform.python_version())
print("policy=" + policy)
'''


def main() -> int:
    if sys.platform != "win32":
        print("UNSUPPORTED platform: Windows-only Proactor diagnostic")
        return 2

    policy = run_probe("runtime and event-loop policy", _POLICY_CODE)
    print(
        f"{policy.status.upper()} {policy.name} "
        f"elapsed={policy.elapsed_seconds:.2f}s exit_code={policy.return_code}"
    )
    if policy.stdout.strip():
        print(policy.stdout.rstrip())
    if policy.stderr.strip():
        print(policy.stderr.rstrip(), file=sys.stderr)

    results = [
        run_probe("socket.socketpair", _SOCKETPAIR_CODE),
        run_probe("TCP loopback connect and accept", _TCP_LOOPBACK_CODE),
        run_probe("asyncio.ProactorEventLoop", _PROACTOR_CODE),
        run_probe("minimal child subprocess", _SUBPROCESS_CODE),
    ]
    for result in results:
        print(
            f"{result.status.upper()} {result.name} "
            f"elapsed={result.elapsed_seconds:.2f}s "
            f"exit_code={result.return_code}"
        )
        if result.stdout.strip():
            print(result.stdout.rstrip())
        if result.stderr.strip():
            print(f"--- {result.name} child traceback ---", file=sys.stderr)
            print(result.stderr.rstrip(), file=sys.stderr)
    return 0 if policy.status == "passed" and all(item.status == "passed" for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
