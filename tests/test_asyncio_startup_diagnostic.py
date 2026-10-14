"""Offline tests for bounded Windows asyncio startup diagnostics."""

import os
import sys

from scripts.diagnose_windows_asyncio import (
    _POLICY_CODE,
    _SUBPROCESS_CODE,
    _TCP_LOOPBACK_CODE,
    run_probe,
    safe_child_environment,
)


def test_probe_reports_successful_child():
    result = run_probe("quick-child", 'print("READY", flush=True)', timeout=2.0)

    assert result.status == "passed"
    assert result.return_code == 0
    assert result.stdout.strip() == "READY"


def test_runtime_policy_probe_reports_metadata_without_creating_a_loop():
    result = run_probe("runtime-policy", _POLICY_CODE, timeout=2.0)

    assert result.status == "passed"
    assert "implementation=cpython" in result.stdout
    assert "policy=" in result.stdout


def test_minimal_subprocess_probe_is_bounded_and_succeeds():
    result = run_probe("minimal-subprocess", _SUBPROCESS_CODE, timeout=3.0)

    assert result.status == "passed"
    assert result.stdout.strip() == "CHILD_READY"


def test_loopback_probe_has_explicit_socket_timeouts():
    assert "server.settimeout(1.0)" in _TCP_LOOPBACK_CODE
    assert "client.settimeout(1.0)" in _TCP_LOOPBACK_CODE
    assert '"127.0.0.1"' in _TCP_LOOPBACK_CODE


def test_probe_kills_a_blocked_child_with_bounded_wait():
    result = run_probe("blocked-child", "import time; time.sleep(30)", timeout=0.2)

    assert result.status == "blocked"
    assert result.return_code is not None
    assert result.elapsed_seconds < 5.0


def test_child_environment_excludes_credentials(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "must-not-be-forwarded")
    monkeypatch.setenv("LLM_API_KEY", "must-not-be-forwarded-either")

    child = safe_child_environment()

    assert "GROQ_API_KEY" not in child
    assert "LLM_API_KEY" not in child
    assert set(child).issubset({"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP"})


def test_safe_environment_uses_only_allowlisted_source():
    child = safe_child_environment({
        "PATH": "python-path",
        "TEMP": "temp-path",
        "GROQ_API_KEY": "secret-value",
    })

    assert child == {"PATH": "python-path", "TEMP": "temp-path"}
