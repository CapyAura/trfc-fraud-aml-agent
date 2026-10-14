"""Small, explicit provenance registrations for evaluator adapters.

Registrations describe how an adapter is configured; they are not cryptographic
attestations and cannot protect against intentionally dishonest custom code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Callable


_REGISTRATION_KEY = object()
_NON_REAL_MODES = {"mock", "unit_test", "synthetic"}
_PROVIDER_ID = re.compile(r"[a-z][a-z0-9_.-]{0,63}\Z")


@dataclass(frozen=True)
class AdapterProvenance:
    execution_mode: str
    provider_id: str

    def __post_init__(self) -> None:
        if self.execution_mode not in _NON_REAL_MODES | {"real"}:
            raise ValueError("unsupported adapter provenance mode")
        if not isinstance(self.provider_id, str) or not _PROVIDER_ID.fullmatch(self.provider_id):
            raise ValueError("provider_id must be a safe, non-secret identifier")


_BUILTIN_GROQ_PROVENANCE = AdapterProvenance("real", "groq-default")


@dataclass(frozen=True)
class RegisteredAdapter:
    """Callable adapter plus immutable evaluator provenance."""

    handler: Callable[[dict[str, Any]], Any] = field(repr=False, compare=False)
    provenance: AdapterProvenance
    _registration_key: object = field(repr=False, compare=False)

    def __call__(self, case: dict[str, Any]) -> Any:
        return self.handler(case)


def register_adapter(
    handler: Callable[[dict[str, Any]], Any], *, mode: str, provider_id: str
) -> RegisteredAdapter:
    """Register an injected adapter for non-real evaluation only."""
    if not callable(handler):
        raise TypeError("adapter handler must be callable")
    if mode not in _NON_REAL_MODES:
        raise ValueError("injected adapters may only use mock, unit_test, or synthetic mode")
    provenance = AdapterProvenance(mode, provider_id)
    return RegisteredAdapter(handler, provenance, _REGISTRATION_KEY)


def _register_builtin_live_adapter(
    handler: Callable[[dict[str, Any]], Any],
) -> RegisteredAdapter:
    """Register the built-in adapter whose default provider is Groq."""
    if not callable(handler):
        raise TypeError("adapter handler must be callable")
    return RegisteredAdapter(handler, _BUILTIN_GROQ_PROVENANCE, _REGISTRATION_KEY)


def resolve_execution_mode(adapter: Any, requested_mode: str | None) -> str:
    """Resolve event mode from registration and reject caller conflicts."""
    if not isinstance(adapter, RegisteredAdapter) or adapter._registration_key is not _REGISTRATION_KEY:
        raise ValueError("step-event output requires a registered adapter provenance")
    provenance = adapter.provenance
    if provenance.execution_mode == "real" and provenance is not _BUILTIN_GROQ_PROVENANCE:
        raise ValueError("only the built-in default-provider adapter may use real mode")
    if requested_mode is not None and requested_mode != provenance.execution_mode:
        raise ValueError("execution_mode conflicts with registered adapter provenance")
    return provenance.execution_mode
