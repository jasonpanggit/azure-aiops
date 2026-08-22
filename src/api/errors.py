"""Stable, HTTP-mappable error contract for the Operations API.

The semantic, ontology and onboarding layers raise plain Python exceptions
(``LookupError``, ``ValueError``, ``PermissionError``). An HTTP surface needs a
stable machine-readable contract instead, so every error crossing the API
boundary is normalized into an :class:`ApiError` carrying a stable ``code``, an
HTTP status, and a safe message. Clients switch on ``code``; the string message
is for humans only and may change.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from onboarding.credentials import (
    SecretNotFoundError,
    SecretStorageError,
    redact_reference,
)
from onboarding.registry import (
    ConnectionNotFoundError,
    DuplicateConnectionError,
    RegistryConflictError,
)
from onboarding.service import OnboardingError

_SECRET_PATTERNS = (
    # Key/value secret assignments, e.g. client_secret=abc, "password": "abc"
    re.compile(
        r"(?i)\b(client_secret|secret|password|passwd|pwd|token|api[_-]?key|"
        r"authorization|bearer|sas|connectionstring|connection_string)\b"
        r"\s*[=:]\s*\"?'?[^\s\"',;)}]+"
    ),
    # Bare bearer tokens / JWTs. The length floor keeps prose such as
    # "a bearer token is required" intact while still catching real tokens,
    # which are far longer than 16 characters.
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{16,}"),
    re.compile(r"\beyJ[A-Za-z0-9._\-]{10,}"),
)

REDACTED = "[REDACTED]"


def scrub(message: Any) -> str:
    """Strip anything secret-looking out of a human-readable error message.

    ``onboarding.credentials.redact`` only walks mappings and sequences; error
    messages are free-form strings, so they need their own pass before they can
    cross the API boundary.
    """
    text = str(message or "")
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


class ErrorCode:
    """Stable error codes. Values are part of the public API contract."""

    NOT_FOUND = "not_found"
    AMBIGUOUS = "ambiguous_subject"
    INVALID_REQUEST = "invalid_request"
    CONFLICT = "conflict"
    ALREADY_EXISTS = "already_exists"
    UNAUTHENTICATED = "unauthenticated"
    FORBIDDEN = "forbidden"
    SECRET_UNAVAILABLE = "secret_unavailable"
    NOT_IMPLEMENTED = "not_implemented"
    UPSTREAM_UNAVAILABLE = "upstream_unavailable"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    INTERNAL = "internal_error"


_STATUS_BY_CODE = {
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.AMBIGUOUS: 409,
    ErrorCode.INVALID_REQUEST: 400,
    ErrorCode.CONFLICT: 409,
    ErrorCode.ALREADY_EXISTS: 409,
    ErrorCode.UNAUTHENTICATED: 401,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.SECRET_UNAVAILABLE: 503,
    ErrorCode.NOT_IMPLEMENTED: 501,
    ErrorCode.UPSTREAM_UNAVAILABLE: 502,
    ErrorCode.PROVIDER_UNAVAILABLE: 503,
    ErrorCode.INTERNAL: 500,
}


@dataclass
class ApiError(Exception):
    """An error with a stable code, HTTP status and redacted message."""

    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.code not in _STATUS_BY_CODE:
            raise ValueError(f"Unknown API error code {self.code!r}")
        self.message = scrub(self.message) or "Request failed"
        super().__init__(self.message)

    @property
    def status_code(self) -> int:
        return _STATUS_BY_CODE[self.code]

    def to_dict(self, *, correlation_id: str = "") -> dict[str, Any]:
        body: dict[str, Any] = {"error": {"code": self.code, "message": self.message}}
        if self.details:
            body["error"]["details"] = {
                key: redact_reference(value) if key == "secret_ref" else scrub(value)
                for key, value in self.details.items()
            }
        if correlation_id:
            body["error"].setdefault("details", {})["correlation_id"] = correlation_id
        return body


def not_found(subject: str, kind: str = "entity") -> ApiError:
    return ApiError(ErrorCode.NOT_FOUND, f"No {kind} matches {subject!r}")


def forbidden(reason: str) -> ApiError:
    return ApiError(ErrorCode.FORBIDDEN, reason)


def not_implemented(capability: str, *, roadmap: str = "") -> ApiError:
    """A capability that is deliberately not yet built.

    Returned instead of a fabricated empty payload so the UI can distinguish
    "no data" from "this endpoint is not implemented yet".
    """
    details = {"capability": capability}
    if roadmap:
        details["roadmap"] = roadmap
    return ApiError(
        ErrorCode.NOT_IMPLEMENTED,
        f"{capability} is not implemented in this build",
        details,
    )


_AMBIGUOUS_MARKERS = ("ambiguous",)


def translate(exc: Exception) -> ApiError:
    """Normalize any domain exception into the API error contract."""
    if isinstance(exc, ApiError):
        return exc
    if isinstance(exc, ConnectionNotFoundError):
        return ApiError(ErrorCode.NOT_FOUND, str(exc))
    if isinstance(exc, DuplicateConnectionError):
        return ApiError(ErrorCode.ALREADY_EXISTS, str(exc))
    if isinstance(exc, RegistryConflictError):
        return ApiError(ErrorCode.CONFLICT, str(exc))
    if isinstance(exc, (SecretNotFoundError, SecretStorageError)):
        return ApiError(ErrorCode.SECRET_UNAVAILABLE, str(exc))
    if isinstance(exc, OnboardingError):
        return ApiError(ErrorCode.INVALID_REQUEST, str(exc))
    if isinstance(exc, PermissionError):
        return ApiError(ErrorCode.FORBIDDEN, str(exc))
    if isinstance(exc, LookupError):
        return ApiError(ErrorCode.NOT_FOUND, str(exc))
    if isinstance(exc, NotImplementedError):
        return ApiError(ErrorCode.NOT_IMPLEMENTED, str(exc))
    if isinstance(exc, ValueError):
        message = str(exc)
        if any(marker in message.casefold() for marker in _AMBIGUOUS_MARKERS):
            return ApiError(ErrorCode.AMBIGUOUS, message)
        return ApiError(ErrorCode.INVALID_REQUEST, message)
    if isinstance(exc, TypeError):
        return ApiError(ErrorCode.INVALID_REQUEST, str(exc))
    # Anything unrecognized is an internal fault. Never leak the raw text,
    # which may embed connection strings or credentials.
    return ApiError(ErrorCode.INTERNAL, "Internal server error")
