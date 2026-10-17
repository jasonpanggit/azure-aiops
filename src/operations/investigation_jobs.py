"""Durable, single-dispatch investigation jobs with cooperative checkpoints.

Records survive workers, not vice versa. An accepted/running record is never a
liveness or guaranteed-delivery claim and is never reclaimed for execution.
"""
from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
from collections.abc import Callable
from typing import Any, Literal, Protocol

from azure.core.exceptions import AzureError
from pydantic import BaseModel, ConfigDict, Field, model_validator

from api.scope import Scope
from storage.onelake_documents import DocumentConflictError, DocumentSnapshot

_LOGGER = logging.getLogger(__name__)
JOB_ID_PATTERN = r"job-[a-f0-9]{32}"
JOB_TTL_SECONDS = 24 * 60 * 60
_STORAGE_ERRORS = (AzureError, OSError, RuntimeError, TypeError, ValueError)
_TERMINAL = frozenset({"completed", "stopped", "failed"})


class JobNotFound(LookupError):
    """The exact caller/scope job is absent, expired or not visible."""


class JobConflict(RuntimeError):
    """An identity cannot be reused or an execution claim was already taken."""


class JobUnavailable(RuntimeError):
    """Durable state cannot be confirmed; do not redispatch."""


class InvestigationStopped(RuntimeError):
    """A worker acknowledged stop at a safe boundary, not by killing a call."""


class InvestigationBudgetExpired(RuntimeError):
    """The next work item would exceed the admitted wall-clock budget."""


class JobDocuments(Protocol):
    """Cross-process create-only and logical-revision CAS storage."""

    def read_snapshot(self, name: str) -> DocumentSnapshot: ...

    def create_only(self, name: str, payload: dict[str, Any]) -> object: ...

    def write(self, name: str, payload: dict[str, Any], *, expected_revision: int) -> None: ...


class _Job(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    revision: int = Field(ge=1, le=1000)
    job_id: str = Field(pattern=f"^{JOB_ID_PATTERN}$")
    principal_subject: str = Field(min_length=1)
    scope: dict[str, list[str]]
    objective: str = Field(min_length=1, max_length=1024)
    timeout_seconds: float = Field(ge=1, le=30)
    created_at: float
    updated_at: float
    status: Literal["accepted_outcome_unconfirmed", "running", "completed", "stopped", "failed"]
    stage: str = Field(min_length=1, max_length=160)
    stop_requested: bool = False
    worker_id: str = Field(default="", pattern=r"^(?:[a-f0-9]{32})?$")
    ledger_id: str = Field(default="", pattern=r"^(?:mai-[A-Za-z0-9_-]{1,100})?$")

    @model_validator(mode="after")
    def coherent(self) -> _Job:
        if self.scope != Scope.from_mapping(self.scope).to_dict():
            raise ValueError("Noncanonical job scope")
        if self.updated_at < self.created_at:
            raise ValueError("Job clock moved backwards")
        if (self.status == "completed") != bool(self.ledger_id):
            raise ValueError("Only completed jobs have an exact ledger")
        if (self.status == "accepted_outcome_unconfirmed") != (not self.worker_id):
            raise ValueError("Job worker claim is inconsistent")
        if self.status == "stopped" and not self.stop_requested:
            raise ValueError("Stop was not requested")
        return self

    def public(self) -> dict[str, Any]:
        """Return outcome metadata, never a worker token or provider evidence."""
        return self.model_dump(exclude={"principal_subject", "worker_id"}) | {
            "durability": "durable",
            "liveness": "not_established",
            "cancellation": "scheduling_only",
        }


def job_document_name(subject: str, job_id: str) -> str:
    """Namespace caller-known IDs without exposing subjects in storage paths."""
    digest = hashlib.sha256(f"{subject}\0{job_id}".encode()).hexdigest()
    return f"investigation-jobs/{digest}.json"


class InvestigationJobStore:
    """Persist exact caller/scope job state without automatic retry or renewal."""

    def __init__(self, documents: JobDocuments | None, *, clock: Callable[[], float] = time.time):
        self.documents = documents
        self.clock = clock

    def _read(self, subject: str, job_id: str) -> _Job | None:
        if not re.fullmatch(JOB_ID_PATTERN, job_id):
            raise JobNotFound()
        if self.documents is None:
            raise JobUnavailable("Durable investigation jobs are not configured")
        try:
            snapshot = self.documents.read_snapshot(job_document_name(subject, job_id))
            if not snapshot.exists:
                return None
            job = _Job.model_validate(snapshot.payload)
            if job.principal_subject != subject or job.job_id != job_id:
                raise ValueError("Job identity mismatch")
            if job.updated_at > self.clock() + 60:
                raise ValueError("Job timestamp is in the future")
            return job
        except _STORAGE_ERRORS as exc:
            _LOGGER.warning("investigation job read unavailable", exc_info=True)
            raise JobUnavailable("Job storage is unavailable or corrupt") from exc

    def _authorized(self, subject: str, job_id: str, scope: Scope) -> _Job:
        job = self._read(subject, job_id)
        if job is None or job.scope != scope.to_dict() or self.clock() - job.created_at > JOB_TTL_SECONDS:
            raise JobNotFound()
        return job

    def read(self, subject: str, job_id: str, scope: Scope) -> dict[str, Any]:
        """Read under exact current caller/scope authorization without dispatch."""
        return self._authorized(subject, job_id, scope).public()

    def accept(
        self, subject: str, job_id: str, scope: Scope, *, objective: str, timeout_seconds: float,
    ) -> tuple[dict[str, Any], bool]:
        """Create one dispatch marker; identical retries only read that marker."""
        existing = self._read(subject, job_id)
        if existing is not None:
            if (
                existing.scope != scope.to_dict() or existing.objective != objective
                or existing.timeout_seconds != timeout_seconds
                or self.clock() - existing.created_at > JOB_TTL_SECONDS
            ):
                raise JobConflict("This job identity cannot be reused; inspect its exact original outcome")
            return existing.public(), False
        now = float(self.clock())
        record = _Job(
            revision=1, job_id=job_id, principal_subject=subject, scope=scope.to_dict(),
            objective=objective, timeout_seconds=timeout_seconds, created_at=now,
            updated_at=now, status="accepted_outcome_unconfirmed", stage="admitted",
        )
        assert self.documents is not None
        try:
            self.documents.create_only(job_document_name(subject, job_id), record.model_dump())
        except DocumentConflictError as exc:
            raise JobConflict("Admission raced; read this exact job instead of redispatching") from exc
        except _STORAGE_ERRORS as exc:
            _LOGGER.warning("investigation job admission unavailable", exc_info=True)
            raise JobUnavailable("Admission is unconfirmed; recover only this exact job identity") from exc
        return record.public(), True

    def _change(
        self, subject: str, job_id: str, scope: Scope, change: Callable[[_Job], dict[str, Any]],
    ) -> dict[str, Any]:
        for _ in range(3):
            job = self._authorized(subject, job_id, scope)
            fields = change(job)
            if not fields:
                return job.public()
            updated = _Job.model_validate({
                **job.model_dump(), **fields, "revision": job.revision + 1,
                "updated_at": max(job.updated_at, float(self.clock())),
            })
            assert self.documents is not None
            try:
                self.documents.write(
                    job_document_name(subject, job_id), updated.model_dump(),
                    expected_revision=job.revision,
                )
                return updated.public()
            except DocumentConflictError:
                continue
            except _STORAGE_ERRORS as exc:
                _LOGGER.warning("investigation job update unavailable", exc_info=True)
                raise JobUnavailable("Job outcome update could not be confirmed") from exc
        raise JobUnavailable("Concurrent job updates prevented confirmation; inspect the exact job")

    def request_stop(self, subject: str, job_id: str, scope: Scope) -> dict[str, Any]:
        """Request a safe-boundary stop without claiming provider cancellation."""
        return self._change(
            subject, job_id, scope,
            lambda job: {} if job.status in _TERMINAL or job.stop_requested else {"stop_requested": True},
        )

    def claim(self, subject: str, job_id: str, scope: Scope, worker_id: str) -> dict[str, Any]:
        """Claim a dispatch exactly once, even after an earlier worker vanished."""
        def change(job: _Job) -> dict[str, Any]:
            if job.worker_id or job.status != "accepted_outcome_unconfirmed":
                raise JobConflict("This job already has an execution claim; it cannot be replayed")
            return {"worker_id": worker_id, "status": "running", "stage": "starting"}
        return self._change(subject, job_id, scope, change)

    def checkpoint(self, subject: str, job_id: str, scope: Scope, worker_id: str, stage: str) -> None:
        """Record a work boundary or propagate stop before another provider call."""
        def change(job: _Job) -> dict[str, Any]:
            self._worker(job, worker_id)
            if job.stop_requested:
                raise InvestigationStopped()
            return {"stage": stage}
        self._change(subject, job_id, scope, change)

    @staticmethod
    def _worker(job: _Job, worker_id: str) -> None:
        if job.worker_id != worker_id or job.status != "running":
            raise JobConflict("Worker no longer owns a running investigation")

    def finish(
        self, subject: str, job_id: str, scope: Scope, worker_id: str, *,
        status: Literal["completed", "stopped", "failed"], ledger_id: str = "",
        stage: str,
    ) -> None:
        """Record a known outcome; completion may win a late stop-request race."""
        def change(job: _Job) -> dict[str, Any]:
            self._worker(job, worker_id)
            return {"status": status, "stage": stage, "ledger_id": ledger_id}
        self._change(subject, job_id, scope, change)


class InvestigationExecutionControl:
    """Stop new work at call boundaries, never attest remote-provider shutdown."""

    def __init__(self, store: InvestigationJobStore, subject: str, job_id: str, scope: Scope, worker_id: str, timeout_seconds: float):
        self.store, self.subject, self.job_id, self.scope = store, subject, job_id, scope
        self.worker_id = worker_id
        self.deadline = time.monotonic() + timeout_seconds
        self._lock = threading.Lock()

    def checkpoint(self, stage: str) -> None:
        """Check stop first, then budget; nested/remote work may still be running."""
        with self._lock:
            self.store.checkpoint(self.subject, self.job_id, self.scope, self.worker_id, stage)
            if time.monotonic() >= self.deadline:
                raise InvestigationBudgetExpired("Wall-clock budget exhausted at a safe boundary")
