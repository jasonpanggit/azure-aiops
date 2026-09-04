"""Bounded principal- and scope-bound continuity for canonical investigations."""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from api.scope import Scope

MAX_THREADS = 2_000
MAX_TURNS = 12
IDLE_TTL_SECONDS = 60 * 60


class ThreadNotFound(LookupError):
    """Raised for missing, expired, foreign, or out-of-scope threads."""


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


@dataclass
class InvestigationThread:
    """Internal continuity record; IDs are always issued by the server."""

    thread_id: str
    principal_subject: str
    scope: Scope
    scope_fingerprint: str
    turns: list[dict[str, Any]] = field(default_factory=list)
    revision: int = 0
    created_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)


class InvestigationThreadStore:
    """Thread-safe bounded store with not-found semantics for access mismatch."""

    def __init__(
        self,
        *,
        max_threads: int = MAX_THREADS,
        max_turns: int = MAX_TURNS,
        idle_ttl_seconds: float = IDLE_TTL_SECONDS,
    ) -> None:
        self._max_threads = max_threads
        self._max_turns = max_turns
        self._idle_ttl_seconds = idle_ttl_seconds
        self._lock = threading.Lock()
        self._threads: OrderedDict[str, InvestigationThread] = OrderedDict()

    def _evict_expired(self, now: float) -> None:
        for thread_id in [
            key
            for key, value in self._threads.items()
            if now - value.last_seen > self._idle_ttl_seconds
        ]:
            del self._threads[thread_id]

    def create(self, principal_subject: str, scope: Scope) -> InvestigationThread:
        """Create an empty principal-owned thread with an opaque server ID."""

        subject = str(principal_subject or "").strip()
        if not subject:
            raise ValueError("principal subject is required")
        now = time.time()
        record = InvestigationThread(
            thread_id=f"thr-{uuid.uuid4().hex}",
            principal_subject=subject,
            scope=scope,
            scope_fingerprint=_scope_fingerprint(scope),
            created_at=now,
            last_seen=now,
        )
        with self._lock:
            self._evict_expired(now)
            self._threads[record.thread_id] = record
            while len(self._threads) > self._max_threads:
                self._threads.popitem(last=False)
        return record

    def authorize(
        self,
        thread_id: str,
        principal_subject: str,
        current_scope: Scope,
    ) -> InvestigationThread:
        """Return an authorized thread without revealing mismatch details."""

        with self._lock:
            now = time.time()
            self._evict_expired(now)
            record = self._threads.get(thread_id)
            if (
                record is None
                or record.principal_subject != principal_subject
                or not _scope_within(current_scope, record.scope)
            ):
                raise ThreadNotFound("investigation thread not found")
            record.last_seen = now
            self._threads.move_to_end(thread_id)
            return record

    def append(
        self,
        thread_id: str,
        principal_subject: str,
        current_scope: Scope,
        turn: dict[str, Any],
    ) -> InvestigationThread:
        """Append one authorized result and return the updated record."""

        with self._lock:
            now = time.time()
            self._evict_expired(now)
            record = self._threads.get(thread_id)
            if (
                record is None
                or record.principal_subject != principal_subject
                or not _scope_within(current_scope, record.scope)
            ):
                raise ThreadNotFound("investigation thread not found")
            record.scope = current_scope
            record.scope_fingerprint = _scope_fingerprint(current_scope)
            record.turns.append(dict(turn))
            record.turns = record.turns[-self._max_turns :]
            record.revision += 1
            record.last_seen = now
            self._threads.move_to_end(thread_id)
            return record

    def history(
        self,
        thread_id: str,
        principal_subject: str,
        current_scope: Scope,
    ) -> list[dict[str, Any]]:
        """Return retained turns only after current ownership and scope checks."""

        with self._lock:
            now = time.time()
            self._evict_expired(now)
            record = self._threads.get(thread_id)
            if (
                record is None
                or record.principal_subject != principal_subject
                or not _scope_within(current_scope, record.scope)
            ):
                raise ThreadNotFound("investigation thread not found")
            record.last_seen = now
            self._threads.move_to_end(thread_id)
            return [dict(turn) for turn in record.turns]


_THREAD_STORE = InvestigationThreadStore()


def investigation_thread_store() -> InvestigationThreadStore:
    """Return the process-wide bounded continuity store."""

    return _THREAD_STORE


__all__ = [
    "InvestigationThreadStore",
    "ThreadNotFound",
    "investigation_thread_store",
]
