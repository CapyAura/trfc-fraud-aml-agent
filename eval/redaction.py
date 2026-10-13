"""Best-effort redaction for values persisted by the evaluation pipeline.

This works on a copy at the logging boundary. It does not alter tool arguments
or results used by the agent at runtime.
"""

from __future__ import annotations

import json
import re
from typing import Any


REDACTED = "[REDACTED]"

_SECRET_KEYS = {
    "auth", "authorization", "authheader", "bearer", "cookie", "setcookie",
    "credential", "credentials", "password", "passwd", "secret", "token",
    "apikey", "apitoken", "accesstoken", "refreshtoken", "clientsecret",
    "privatekey",
}
_IDENTIFIER_KEYS = {
    "accountid", "accountnumber", "txid", "transactionid", "flaggedtxids",
    "customerid", "customername", "fullname", "cardnumber", "iban", "email",
    "phone", "address", "location", "dateofbirth", "dob", "ssn", "nationalid",
    "amount", "balance", "reason", "freetextreason",
}

_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|api[_-]?token|access[_-]?token|refresh[_-]?token|"
    r"client[_-]?secret|password|passwd|authorization|credential|secret|token|"
    r"account[_-]?(?:id|number)|(?:transaction|tx)[_-]?id|customer[_-]?id|reason)"
    r"\b\s*[:=]\s*(?:Bearer\s+)?(?:\"[^\"]*\"|'[^']*'|[^\s,;\]}]+)"
)
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_KNOWN_TOKEN = re.compile(
    r"\b(?:gsk_[A-Za-z0-9_-]{12,}|sk-[A-Za-z0-9_-]{12,}|"
    r"gh[pousr]_[A-Za-z0-9]{20,})\b"
)
_PRIVATE_KEY = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
    re.DOTALL,
)
_ACCOUNT_OR_TRANSACTION_ID = re.compile(r"\b(?:ACC|TX)\d{2,}\b", re.IGNORECASE)
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_CARD_NUMBER = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
_FORMATTED_PHONE = re.compile(
    r"(?<!\w)(?:\+\d{1,3}[ .()-]?)?\(?\d{2,4}\)?[ .()-]+\d{3,4}[ .-]+\d{3,4}(?!\w)"
)


def _normalized_key(key: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", key.casefold()) if isinstance(key, str) else ""


def _is_sensitive_key(key: Any) -> bool:
    normalized = _normalized_key(key)
    if normalized in _SECRET_KEYS or normalized in _IDENTIFIER_KEYS:
        return True
    return any(
        normalized.endswith(suffix)
        for suffix in ("apikey", "apitoken", "accesstoken", "refreshtoken", "secret", "password")
    )


def _redact_text(value: str) -> str:
    # MCP tool results are often JSON encoded into a text content block. Parse
    # object/array strings so sensitive nested keys receive the same treatment.
    stripped = value.lstrip()
    if stripped.startswith(("{", "[")):
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            parsed = None
        if isinstance(parsed, (dict, list)):
            return json.dumps(redact_for_log(parsed), ensure_ascii=False, separators=(",", ":"))

    value = _PRIVATE_KEY.sub(REDACTED, value)
    value = _SENSITIVE_ASSIGNMENT.sub(lambda match: f"{match.group(1)}={REDACTED}", value)
    value = _BEARER.sub(REDACTED, value)
    value = _KNOWN_TOKEN.sub(REDACTED, value)
    value = _ACCOUNT_OR_TRANSACTION_ID.sub(REDACTED, value)
    value = _EMAIL.sub(REDACTED, value)
    value = _CARD_NUMBER.sub(REDACTED, value)
    value = _FORMATTED_PHONE.sub(REDACTED, value)
    return value


def redact_for_log(value: Any) -> Any:
    """Return a recursively redacted copy suitable for evaluation JSONL.

    Sensitive fields are replaced wholesale. Other strings are scrubbed for
    common credential formats and the project's account/transaction IDs.
    This is a safety filter, not a guarantee that arbitrary unstructured text
    contains no sensitive information.
    """
    if isinstance(value, dict):
        return {
            key: REDACTED if _is_sensitive_key(key) else redact_for_log(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_for_log(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_for_log(item) for item in value)
    if isinstance(value, str):
        return _redact_text(value)
    return value
