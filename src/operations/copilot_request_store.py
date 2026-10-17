"""Durable admission markers prevent redispatch after a lost browser response.

A marker is written before provider execution and is never reclaimed for retry.
An accepted marker is not a liveness, cancellation or successful-result claim.
Only a completed marker points to exact historical continuity; answers are not
cached or replayed as current observations.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from collections.abc import Callable, Mapping
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from api.scope import Scope
from storage.onelake_documents import DocumentConflictError

_LOGGER = logging.getLogger(__name__)
REQUEST_KEY_PATTERN = r"req-[0-9]{13}-[a-f0-9]{32}"
ADMISSION_WINDOW_SECONDS = 15 * 60
RECEIPT_TTL_SECONDS = 24 * 60 * 60


class RequestReceiptUnavailable(RuntimeError):
    """Durable admission or receipt recovery could not be confirmed."""


class RequestAlreadyAccepted(RuntimeError):
    """A key cannot dispatch again, including after an uncertain outcome."""


class RequestKeyExpired(ValueError):
    """A key is too old or too far in the future for first admission."""


class RequestReceiptNotFound(LookupError):
    """Missing, expired, foreign or differently scoped receipt."""


class ReceiptDocuments(Protocol):
    """Fail-closed read and cross-process CAS primitives for admission."""

    def read_or_raise(self, name: str) -> dict[str, Any]: ...

    def create_only(self, name: str, payload: dict[str, Any]) -> object: ...

    def write(self, name: str, payload: dict[str, Any], *, expected_revision: int) -> None: ...


class _Receipt(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    revision: int = Field(ge=1, le=2)
    request_key: str = Field(pattern=f"^{REQUEST_KEY_PATTERN}$")
    principal_subject: str = Field(min_length=1)
    scope: dict[str, list[str]]
    request_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    accepted_at: float
    status: Literal["accepted_outcome_unconfirmed", "completed"]
    thread_id: str = Field(default="", pattern=r"^(?:thr-[a-f0-9]{32})?$")
    thread_revision: int = Field(default=0, ge=0)


def receipt_document_name(principal_subject: str, request_key: str) -> str:
    """Derive a non-identifying caller/key namespace without a shared index."""
    digest = hashlib.sha256(f"{principal_subject}\0{request_key}".encode()).hexdigest()
    return f"copilot-requests/{digest}.json"


class CopilotRequestStore:
    """Reserve one durable dispatch and expose only authorized outcome metadata."""

    def __init__(self, documents: ReceiptDocuments | None, *, clock: Callable[[], float] = time.time):
        self.documents = documents
        self._clock = clock

    def _read(self, principal_subject: str, request_key: str) -> _Receipt | None:
        if self.documents is None:
            raise RequestReceiptUnavailable("Durable request admission is not configured")
        try:
            raw = self.documents.read_or_raise(receipt_document_name(principal_subject, request_key))
            if not raw:
                return None
            record = _Receipt.model_validate(raw)
            if record.principal_subject != principal_subject or record.request_key != request_key:
                raise ValueError("Receipt document identity mismatch")
            Scope.from_mapping(record.scope)
            if record.status == "completed" and (not record.thread_id or record.thread_revision < 1):
                raise ValueError("Completed receipt lacks exact continuity")
            return record
        except Exception as exc:
            _LOGGER.warning("copilot request receipt read unavailable", exc_info=True)
            raise RequestReceiptUnavailable("Request receipt storage is unavailable") from exc

    def accept(self, principal_subject: str, request_key: str, scope: Scope, payload: Mapping[str, Any]) -> None:
        """CAS admission before dispatch; never replace or replay an existing key."""
        if not re.fullmatch(REQUEST_KEY_PATTERN, request_key):
            raise RequestKeyExpired("Invalid request key")
        age = self._clock() - int(request_key.split("-")[1]) / 1000
        if not -60 <= age <= ADMISSION_WINDOW_SECONDS:
            raise RequestKeyExpired("Request key is outside the admission window; inspect the outcome before starting a new request")
        if self._read(principal_subject, request_key) is not None:
            raise RequestAlreadyAccepted("This key was already accepted; inspect its receipt instead of redispatching")
        encoded = json.dumps({"scope": scope.to_dict(), "payload": payload}, sort_keys=True, separators=(",", ":"), allow_nan=False)
        record = _Receipt(
            revision=1, request_key=request_key, principal_subject=principal_subject,
            scope=scope.to_dict(), request_sha256=hashlib.sha256(encoded.encode()).hexdigest(),
            accepted_at=float(self._clock()), status="accepted_outcome_unconfirmed",
        )
        assert self.documents is not None
        try:
            self.documents.create_only(receipt_document_name(principal_subject, request_key), record.model_dump())
        except DocumentConflictError as exc:
            raise RequestAlreadyAccepted("This key was already accepted; inspect its receipt instead of redispatching") from exc
        except Exception as exc:
            _LOGGER.warning("copilot request admission write unavailable", exc_info=True)
            raise RequestReceiptUnavailable("Request admission was not confirmed; retry only with the same key") from exc

    def complete(self, principal_subject: str, request_key: str, scope: Scope, *, thread_id: str, thread_revision: int) -> None:
        """Commit an exact historical result reference, never a provider answer."""
        record = self._read(principal_subject, request_key)
        if record is None or record.scope != scope.to_dict() or record.revision != 1:
            raise RequestReceiptUnavailable("Accepted request marker cannot be confirmed")
        assert self.documents is not None
        try:
            completed = _Receipt.model_validate({
                **record.model_dump(), "revision": 2, "status": "completed",
                "thread_id": thread_id, "thread_revision": thread_revision,
            })
            if not completed.thread_id or completed.thread_revision < 1:
                raise ValueError("No exact completed continuity")
            self.documents.write(receipt_document_name(principal_subject, request_key), completed.model_dump(), expected_revision=1)
        except Exception as exc:
            _LOGGER.warning("copilot request completion write unavailable", exc_info=True)
            raise RequestReceiptUnavailable("Result receipt could not be committed; inspect retained history, never redispatch this key") from exc

    def read(self, principal_subject: str, request_key: str, scope: Scope) -> dict[str, Any]:
        """Read exact caller/scope outcome metadata without renewal or dispatch."""
        if not re.fullmatch(REQUEST_KEY_PATTERN, request_key):
            raise RequestReceiptNotFound()
        record = self._read(principal_subject, request_key)
        if record is None or record.scope != scope.to_dict() or self._clock() - record.accepted_at > RECEIPT_TTL_SECONDS:
            raise RequestReceiptNotFound()
        return {
            "request_key": request_key, "status": record.status,
            "durability": "durable", "thread_id": record.thread_id,
            "thread_revision": record.thread_revision,
        }
