"""Durable, bounded, principal- and scope-bound continuity for investigations.

A continuity record is the only server-side memory of an operator's
investigation, so it is held to the same rules as the evidence it carries: it
belongs to exactly one principal, it is never served wider than the scope in
force right now, it ages out on both idle and absolute clocks, and every turn
it carries is explicitly marked historical until it is observed again.

Durability follows ``InvestigationLedgerStore``: one document per
server-generated thread, write-through persistence, a bounded read-through
cache, and identity revalidation after load. Without a document store the
behaviour degrades to the previous bounded in-memory store, and that
degradation is reported rather than hidden.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable, Iterable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Protocol

from api.scope import Scope

_LOGGER = logging.getLogger(__name__)

MAX_THREADS = 2_000
MAX_TURNS = 12
IDLE_TTL_SECONDS = 60 * 60
ABSOLUTE_TTL_SECONDS = 24 * 60 * 60
MAX_CLEANUP_PER_PASS = 64
THREAD_SCHEMA_VERSION = "1"

OBSERVATION_CURRENT = "current"
OBSERVATION_HISTORICAL = "historical"

DURABILITY_DURABLE = "durable"
DURABILITY_MEMORY_ONLY = "memory_only"

#: Controlled, low-cardinality reasons a thread was withheld. They exist for
#: telemetry and never reach the caller, who always sees "not found".
THREAD_MISS_REASONS = (
    "missing",
    "corrupt",
    "principal_mismatch",
    "scope_widened",
    "expired_idle",
    "expired_absolute",
)


class ThreadNotFound(LookupError):
    """Raised for missing, expired, foreign, corrupt, or out-of-scope threads.

    ``reason`` is a controlled enum for telemetry only. Callers must keep
    projecting every case as an indistinguishable not-found so a probe cannot
    tell a foreign thread from one that never existed.
    """

    def __init__(
        self,
        message: str = "investigation thread not found",
        *,
        reason: str = "missing",
    ) -> None:
        super().__init__(message)
        self.reason = reason if reason in THREAD_MISS_REASONS else "missing"


class ThreadRevisionConflict(RuntimeError):
    """Raised when a turn is appended against a superseded revision."""

    def __init__(self, *, current_revision: int) -> None:
        super().__init__("investigation thread revision conflict")
        self.current_revision = current_revision


class ThreadDocumentStore(Protocol):
    """The subset of ``OneLakeDocumentStore`` continuity needs.

    Declared structurally so tests can substitute a dictionary-backed double
    without importing the storage layer.
    """

    def read(self, name: str) -> dict[str, Any]: ...

    def put(self, name: str, payload: dict[str, Any]) -> None: ...


def thread_document_name(thread_id: str) -> str:
    """Map a thread id to its own document path.

    One document per thread rather than one collection document: threads are
    written on every turn, so a shared document would put every replica in
    compare-and-swap contention over unrelated operators' state. Thread ids are
    server-generated, so two writers can never target the same document.
    """

    return f"threads/{thread_id}.json"


def _scope_within(requested: Scope, allowed: Scope) -> bool:
    if allowed.is_unrestricted():
        return True
    for dimension, allowed_values in allowed.dimensions.items():
        requested_values = requested.values(dimension)
        if not requested_values or not requested_values <= allowed_values:
            return False
    return True


def _scope_fingerprint(scope: Scope) -> str:
    encoded = json.dumps(scope.to_dict(), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _age_payload(payload: dict[str, Any], status: str) -> dict[str, Any]:
    """Stamp a retained turn and each evidence item with observation status.

    Carried evidence is a claim about the past. Marking it explicitly is what
    stops a later turn from silently presenting a stale observation as a
    current one after navigation.
    """

    payload["observation_status"] = status
    for result in payload.get("tool_results") or []:
        if not isinstance(result, dict):
            continue
        result["observation_status"] = status
        for item in result.get("evidence") or []:
            if isinstance(item, dict):
                item["observation_status"] = status
    for citation in payload.get("citations") or []:
        if isinstance(citation, dict):
            citation["observation_status"] = status
    return payload


@dataclass
class InvestigationThreadTurn:
    """One retained result bound to the scope used when it was produced."""

    scope: Scope
    payload: dict[str, Any]
    recorded_at: float = field(default_factory=time.time)
    observation_status: str = OBSERVATION_CURRENT

    @property
    def snapshot_id(self) -> str:
        return str(self.payload.get("snapshot_id") or "")

    def to_document(self) -> dict[str, Any]:
        return {
            "scope": self.scope.to_dict(),
            "payload": deepcopy(self.payload),
            "recorded_at": self.recorded_at,
            "observation_status": self.observation_status,
        }

    @classmethod
    def from_document(cls, document: Mapping[str, Any]) -> InvestigationThreadTurn:
        payload = document.get("payload")
        if not isinstance(payload, dict):
            raise TypeError("thread turn payload is invalid")
        status = str(document.get("observation_status") or OBSERVATION_HISTORICAL)
        return cls(
            scope=Scope.from_mapping(document.get("scope") or {}),
            payload=deepcopy(payload),
            recorded_at=float(document.get("recorded_at") or 0.0),
            observation_status=(
                status
                if status in {OBSERVATION_CURRENT, OBSERVATION_HISTORICAL}
                else OBSERVATION_HISTORICAL
            ),
        )


@dataclass
class InvestigationThread:
    """Internal continuity record; IDs are always issued by the server."""

    thread_id: str
    principal_subject: str
    scope: Scope
    scope_fingerprint: str
    turns: list[InvestigationThreadTurn] = field(default_factory=list)
    revision: int = 0
    created_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    durability: str = DURABILITY_MEMORY_ONLY

    def to_document(self) -> dict[str, Any]:
        return {
            "schema_version": THREAD_SCHEMA_VERSION,
            "thread_id": self.thread_id,
            "principal_subject": self.principal_subject,
            "scope": self.scope.to_dict(),
            "scope_fingerprint": self.scope_fingerprint,
            "revision": self.revision,
            "created_at": self.created_at,
            "last_seen": self.last_seen,
            "turns": [turn.to_document() for turn in self.turns],
        }

    @classmethod
    def from_document(cls, document: Mapping[str, Any]) -> InvestigationThread:
        thread_id = str(document.get("thread_id") or "")
        subject = str(document.get("principal_subject") or "")
        if not thread_id or not subject:
            raise ValueError("thread document identity is incomplete")
        scope = Scope.from_mapping(document.get("scope") or {})
        raw_turns = document.get("turns")
        if raw_turns is not None and not isinstance(raw_turns, list):
            raise ValueError("thread document turns are invalid")
        return cls(
            thread_id=thread_id,
            principal_subject=subject,
            scope=scope,
            scope_fingerprint=str(
                document.get("scope_fingerprint") or _scope_fingerprint(scope)
            ),
            turns=[
                InvestigationThreadTurn.from_document(turn)
                for turn in (raw_turns or [])
                if isinstance(turn, Mapping)
            ],
            revision=int(document.get("revision") or 0),
            created_at=float(document.get("created_at") or 0.0),
            last_seen=float(document.get("last_seen") or 0.0),
            durability=DURABILITY_DURABLE,
        )


class InvestigationThreadStore:
    """Durable, thread-safe store with not-found semantics for access mismatch."""

    def __init__(
        self,
        *,
        max_threads: int = MAX_THREADS,
        max_turns: int = MAX_TURNS,
        idle_ttl_seconds: float = IDLE_TTL_SECONDS,
        absolute_ttl_seconds: float = ABSOLUTE_TTL_SECONDS,
        documents: ThreadDocumentStore | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._max_threads = max_threads
        self._max_turns = max_turns
        self._idle_ttl_seconds = idle_ttl_seconds
        self._absolute_ttl_seconds = absolute_ttl_seconds
        self._clock = clock
        self._lock = threading.RLock()
        self._threads: OrderedDict[str, InvestigationThread] = OrderedDict()
        self.documents = documents

    @property
    def is_durable(self) -> bool:
        return self.documents is not None

    # -- persistence ------------------------------------------------------

    def _persist(self, record: InvestigationThread) -> None:
        """Write the thread through to storage, best-effort.

        A storage outage must not fail the turn the operator is running, so
        the failure downgrades the record's reported durability instead. The
        downgrade is the signal that continuity is process-local again.
        """

        if self.documents is None:
            record.durability = DURABILITY_MEMORY_ONLY
            return
        try:
            self.documents.put(
                thread_document_name(record.thread_id),
                record.to_document(),
            )
        except Exception:  # Degrade, never fail the turn.
            _LOGGER.warning(
                "failed to persist investigation thread; continuity is memory-only",
                exc_info=True,
            )
            record.durability = DURABILITY_MEMORY_ONLY
            return
        record.durability = DURABILITY_DURABLE

    def _forget_document(self, thread_id: str) -> None:
        if self.documents is None:
            return
        delete = getattr(self.documents, "delete", None)
        if not callable(delete):
            return
        try:
            delete(thread_document_name(thread_id))
        except Exception:  # Cleanup is best-effort.
            _LOGGER.warning("failed to remove expired thread document", exc_info=True)

    def _load(self, thread_id: str) -> InvestigationThread | None:
        """Rehydrate an evicted or another replica's thread from storage."""

        if self.documents is None:
            return None
        try:
            payload = self.documents.read(thread_document_name(thread_id))
        except Exception:  # An unreadable thread is simply not found.
            _LOGGER.warning("failed to read investigation thread", exc_info=True)
            return None
        if not payload:
            return None
        # The document store reads a missing *or corrupt* document as {}. For
        # continuity that is not enough: require the identity to match rather
        # than trusting whatever came back.
        if payload.get("thread_id") != thread_id:
            raise ThreadNotFound(reason="corrupt")
        try:
            record = InvestigationThread.from_document(payload)
        except (TypeError, ValueError):
            raise ThreadNotFound(reason="corrupt") from None
        self._threads[thread_id] = record
        self._threads.move_to_end(thread_id)
        while len(self._threads) > self._max_threads:
            self._threads.popitem(last=False)
        return record

    # -- expiry -----------------------------------------------------------

    def _expiry_reason(self, record: InvestigationThread, now: float) -> str:
        if now - record.created_at >= self._absolute_ttl_seconds:
            return "expired_absolute"
        if now - record.last_seen >= self._idle_ttl_seconds:
            return "expired_idle"
        return ""

    def _sweep(self, now: float, *, limit: int = MAX_CLEANUP_PER_PASS) -> int:
        """Remove expired threads, bounded so a sweep can never stall a turn."""

        removed = 0
        for thread_id, record in list(self._threads.items()):
            if removed >= limit:
                break
            if self._expiry_reason(record, now):
                del self._threads[thread_id]
                self._forget_document(thread_id)
                removed += 1
        return removed

    def cleanup(self, *, max_removals: int = MAX_CLEANUP_PER_PASS) -> int:
        """Remove up to ``max_removals`` expired threads and their documents."""

        with self._lock:
            return self._sweep(self._clock(), limit=max(0, max_removals))

    # -- access -----------------------------------------------------------

    def _resolve(
        self,
        thread_id: str,
        principal_subject: str,
        current_scope: Scope,
        now: float,
    ) -> InvestigationThread:
        """Return a thread only after every current-turn gate passes."""

        record = self._threads.get(thread_id) or self._load(thread_id)
        # Sweep after resolving the requested thread so its own expiry is
        # reported as an expiry rather than being flattened into "missing";
        # the reason is what makes an aged-out thread distinguishable in
        # telemetry even though the caller only ever sees not-found.
        expiry = self._expiry_reason(record, now) if record is not None else ""
        self._sweep(now)
        if record is None:
            raise ThreadNotFound(reason="missing")
        if expiry:
            self._threads.pop(thread_id, None)
            self._forget_document(thread_id)
            raise ThreadNotFound(reason=expiry)
        if record.principal_subject != principal_subject:
            raise ThreadNotFound(reason="principal_mismatch")
        if not _scope_within(current_scope, record.scope):
            raise ThreadNotFound(reason="scope_widened")
        return record

    def _age_retained_turns(self, record: InvestigationThread) -> None:
        for turn in record.turns:
            turn.observation_status = OBSERVATION_HISTORICAL
            _age_payload(turn.payload, OBSERVATION_HISTORICAL)

    def create(self, principal_subject: str, scope: Scope) -> InvestigationThread:
        """Create an empty principal-owned thread with an opaque server ID."""

        subject = str(principal_subject or "").strip()
        if not subject:
            raise ValueError("principal subject is required")
        now = self._clock()
        record = InvestigationThread(
            thread_id=f"thr-{uuid.uuid4().hex}",
            principal_subject=subject,
            scope=scope,
            scope_fingerprint=_scope_fingerprint(scope),
            created_at=now,
            last_seen=now,
        )
        with self._lock:
            self._sweep(now)
            self._threads[record.thread_id] = record
            while len(self._threads) > self._max_threads:
                self._threads.popitem(last=False)
            self._persist(record)
        return record

    def authorize(
        self,
        thread_id: str,
        principal_subject: str,
        current_scope: Scope,
    ) -> InvestigationThread:
        """Return an authorized thread without revealing mismatch details.

        Authorizing starts a new turn, so everything already retained becomes
        historical: it was observed before this turn and has not been rechecked.
        """

        with self._lock:
            now = self._clock()
            record = self._resolve(thread_id, principal_subject, current_scope, now)
            self._age_retained_turns(record)
            record.last_seen = now
            self._threads.move_to_end(thread_id)
            self._persist(record)
            return record

    def append(
        self,
        thread_id: str,
        principal_subject: str,
        current_scope: Scope,
        turn: dict[str, Any],
        *,
        expected_revision: int | None = None,
    ) -> InvestigationThread:
        """Append one authorized result and return the updated record."""

        with self._lock:
            now = self._clock()
            record = self._resolve(thread_id, principal_subject, current_scope, now)
            if expected_revision is not None and expected_revision != record.revision:
                raise ThreadRevisionConflict(current_revision=record.revision)
            self._age_retained_turns(record)
            record.scope = current_scope
            record.scope_fingerprint = _scope_fingerprint(current_scope)
            record.turns.append(
                InvestigationThreadTurn(
                    scope=current_scope,
                    payload=_age_payload(deepcopy(turn), OBSERVATION_CURRENT),
                    recorded_at=now,
                    observation_status=OBSERVATION_CURRENT,
                )
            )
            record.turns = record.turns[-self._max_turns :]
            record.revision += 1
            record.last_seen = now
            self._threads.move_to_end(thread_id)
            self._persist(record)
            return record

    def history(
        self,
        thread_id: str,
        principal_subject: str,
        current_scope: Scope,
    ) -> list[dict[str, Any]]:
        """Return retained turns only after current ownership and scope checks."""

        with self._lock:
            now = self._clock()
            record = self._resolve(thread_id, principal_subject, current_scope, now)
            record.last_seen = now
            self._threads.move_to_end(thread_id)
            history: list[dict[str, Any]] = []
            for turn in record.turns:
                if _scope_within(turn.scope, current_scope):
                    payload = deepcopy(turn.payload)
                    payload["observation_status"] = turn.observation_status
                    history.append(payload)
                    continue
                history.append(
                    {
                        "status": "historical_scope_restricted",
                        "observation_status": OBSERVATION_HISTORICAL,
                        "tool_results": [],
                        "citations": [],
                        "uncertainty": [
                            "Historical evidence was withheld after scope narrowing."
                        ],
                    }
                )
            return history

    def import_legacy_turns(
        self,
        principal_subject: str,
        scope: Scope,
        turns: Sequence[Mapping[str, Any]] | Iterable[Mapping[str, Any]],
    ) -> InvestigationThread | None:
        """Adopt an active legacy conversation into one canonical thread.

        The source turns are only read: every retained payload is a deep copy
        stamped as historical, so an imported conversation can never be
        presented as freshly observed and the original ledger is untouched.
        """

        retained = [turn for turn in list(turns) if isinstance(turn, Mapping)]
        if not retained:
            return None
        record = self.create(principal_subject, scope)
        with self._lock:
            now = self._clock()
            for payload in retained[-self._max_turns :]:
                imported = deepcopy(dict(payload))
                imported["imported_from"] = "legacy_conversation"
                record.turns.append(
                    InvestigationThreadTurn(
                        scope=scope,
                        payload=_age_payload(imported, OBSERVATION_HISTORICAL),
                        recorded_at=now,
                        observation_status=OBSERVATION_HISTORICAL,
                    )
                )
            record.turns = record.turns[-self._max_turns :]
            record.revision += 1
            record.last_seen = now
            self._persist(record)
        return record


_THREAD_STORE = InvestigationThreadStore()


def investigation_thread_store() -> InvestigationThreadStore:
    """Return the process-wide bounded continuity store."""

    return _THREAD_STORE


def configure_thread_store(
    documents: ThreadDocumentStore | None,
) -> InvestigationThreadStore:
    """Attach durable storage to the process-wide continuity store.

    Called once during API startup. Threads already held in memory are flushed
    so a store configured after the first turn does not leave continuity that
    exists on exactly one replica.
    """

    _THREAD_STORE.documents = documents
    if documents is not None:
        for record in list(_THREAD_STORE._threads.values()):
            _THREAD_STORE._persist(record)
    return _THREAD_STORE


__all__ = [
    "ABSOLUTE_TTL_SECONDS",
    "DURABILITY_DURABLE",
    "DURABILITY_MEMORY_ONLY",
    "IDLE_TTL_SECONDS",
    "MAX_CLEANUP_PER_PASS",
    "MAX_TURNS",
    "OBSERVATION_CURRENT",
    "OBSERVATION_HISTORICAL",
    "THREAD_MISS_REASONS",
    "InvestigationThread",
    "InvestigationThreadStore",
    "InvestigationThreadTurn",
    "ThreadDocumentStore",
    "ThreadNotFound",
    "ThreadRevisionConflict",
    "configure_thread_store",
    "investigation_thread_store",
    "thread_document_name",
]
