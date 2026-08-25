"""Server-owned, revisioned persistence for software normalization mappings.

Suggestions are advisory records.  Only an explicit operator approval makes a
mapping authoritative for inventory aggregation.  The repository owns the
revision and audit trail so browser state can never become the source of truth.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

MAPPING_STATUSES = frozenset({"suggested", "approved", "rejected"})
MAPPING_METHODS = frozenset({"deterministic", "ai", "operator"})


class MappingRevisionConflict(RuntimeError):
    def __init__(self, mapping_id: str, expected: int, current: int) -> None:
        self.mapping_id = mapping_id
        self.expected = expected
        self.current = current
        super().__init__(
            f"Software mapping revision conflict for {mapping_id}: "
            f"expected {expected}, current {current}"
        )


class MappingNotFound(LookupError):
    pass


class MappingStatusConflict(RuntimeError):
    pass


@dataclass(frozen=True)
class SoftwareMapping:
    """A single raw software identity and its governed canonical suggestion."""

    mapping_id: str
    raw_name: str
    raw_version: str
    publisher: str
    canonical_name: str
    canonical_version: str
    method: str
    confidence: float
    status: str
    provenance: dict[str, Any]
    source_timestamp: str
    scope_predicate: dict[str, list[str]]
    revision: int = 0
    reason: str = ""
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        text_fields = (
            "mapping_id",
            "raw_name",
            "raw_version",
            "canonical_name",
            "canonical_version",
            "source_timestamp",
        )
        for field_name in text_fields:
            if not str(getattr(self, field_name) or "").strip():
                raise ValueError(f"Software mapping requires {field_name}")
        if self.method not in MAPPING_METHODS:
            raise ValueError("Software mapping method is not supported")
        if self.status not in MAPPING_STATUSES:
            raise ValueError("Software mapping status is not supported")
        if isinstance(self.confidence, bool) or not 0 <= self.confidence <= 1:
            raise ValueError("Software mapping confidence must be between 0 and 1")
        if isinstance(self.revision, bool) or self.revision < 0:
            raise ValueError("Software mapping revision must be non-negative")
        _scope(self.scope_predicate)

    @property
    def raw_identity(self) -> dict[str, str]:
        return {
            "name": self.raw_name,
            "version": self.raw_version,
            "publisher": self.publisher,
        }

    @property
    def canonical_identity(self) -> str:
        return f"{self.canonical_name}|{self.canonical_version}"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["raw_identity"] = self.raw_identity
        payload["canonical_identity"] = self.canonical_identity
        return payload

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> SoftwareMapping:
        raw = payload.get("raw_identity")
        raw = raw if isinstance(raw, Mapping) else {}
        return cls(
            mapping_id=str(payload.get("mapping_id") or ""),
            raw_name=str(payload.get("raw_name") or raw.get("name") or ""),
            raw_version=str(payload.get("raw_version") or raw.get("version") or ""),
            publisher=str(payload.get("publisher") or raw.get("publisher") or ""),
            canonical_name=str(payload.get("canonical_name") or ""),
            canonical_version=str(payload.get("canonical_version") or ""),
            method=str(payload.get("method") or ""),
            confidence=float(payload.get("confidence", 0)),
            status=str(payload.get("status") or ""),
            provenance=dict(payload.get("provenance") or {}),
            source_timestamp=str(payload.get("source_timestamp") or ""),
            scope_predicate=dict(payload.get("scope_predicate") or {}),
            revision=int(payload.get("revision", 0)),
            reason=str(payload.get("reason") or ""),
            created_at=str(payload.get("created_at") or ""),
            updated_at=str(payload.get("updated_at") or ""),
        )


@dataclass(frozen=True)
class MappingSnapshot:
    mappings: tuple[SoftwareMapping, ...] = ()
    repository_revision: int = 0
    audit_events: tuple[dict[str, Any], ...] = ()
    updated_at: str = ""


class RevisionedDocumentStore(Protocol):
    def read(self, name: str) -> dict[str, Any]: ...

    def write(
        self, name: str, payload: dict[str, Any], *, expected_revision: int
    ) -> None: ...


class SoftwareMappingRepository:
    """Atomic local, OneLake, or in-memory persistence for mapping decisions."""

    _SCHEMA_VERSION = "1.0.0"

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        document_store: RevisionedDocumentStore | None = None,
        document_name: str = "state/software_mappings.json",
    ) -> None:
        if path is not None and document_store is not None:
            raise ValueError("Use either path or document_store, not both")
        self.path = Path(path) if path is not None else None
        self.document_store = document_store
        self.document_name = document_name
        self._memory: dict[str, Any] | None = None
        self._lock = threading.RLock()

    def read(self) -> MappingSnapshot:
        with self._lock:
            state = self._read_state()
            return MappingSnapshot(
                mappings=tuple(
                    SoftwareMapping.from_mapping(item) for item in state["mappings"]
                ),
                repository_revision=state["revision"],
                audit_events=tuple(dict(item) for item in state["audit_events"]),
                updated_at=state["updated_at"],
            )

    def suggest(
        self,
        *,
        raw_name: str,
        raw_version: str,
        publisher: str,
        canonical_name: str,
        canonical_version: str,
        method: str = "ai",
        confidence: float = 0,
        provenance: Mapping[str, Any] | None = None,
        source_timestamp: str,
        scope_predicate: Mapping[str, Any] | None = None,
        mapping_id: str | None = None,
        reason: str = "",
    ) -> SoftwareMapping:
        """Persist an idempotent, non-authoritative suggestion."""
        now = _now()
        identity = _mapping_id(
            raw_name, raw_version, publisher,             _scope(scope_predicate)
        )
        item = SoftwareMapping(
            mapping_id=mapping_id or identity,
            raw_name=_bounded(raw_name, "raw_name"),
            raw_version=_bounded(raw_version, "raw_version"),
            publisher=str(publisher or "").strip(),
            canonical_name=_bounded(canonical_name, "canonical_name"),
            canonical_version=_bounded(canonical_version, "canonical_version"),
            method=method,
            confidence=float(confidence),
            status="suggested",
            provenance=dict(provenance or {}),
            source_timestamp=_bounded(source_timestamp, "source_timestamp"),
            scope_predicate=_scope(scope_predicate).to_dict(),
            revision=0,
            reason=str(reason or "").strip(),
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            state = self._read_state()
            for existing_payload in state["mappings"]:
                existing = SoftwareMapping.from_mapping(existing_payload)
                if existing.mapping_id != item.mapping_id:
                    continue
                # A decision is immutable from the suggestion path.  Re-reading
                # the same provider output must not reset an operator decision.
                return existing
            state["mappings"].append(item.to_dict())
            state["revision"] += 1
            state["updated_at"] = now
            self._write_state(state, expected_revision=state["revision"] - 1)
            return item

    def get(self, mapping_id: str) -> SoftwareMapping:
        with self._lock:
            for item in self.read().mappings:
                if item.mapping_id == mapping_id:
                    return item
        raise MappingNotFound(f"Software mapping {mapping_id!r} was not found")

    def decide(
        self,
        mapping_id: str,
        *,
        decision: str,
        expected_revision: int,
        actor: str,
        scope_snapshot: Mapping[str, Any],
        reason: str = "",
        timestamp: str | None = None,
    ) -> SoftwareMapping:
        if decision not in {"approved", "rejected"}:
            raise ValueError("Software mapping decision must be approved or rejected")
        with self._lock:
            state = self._read_state()
            index = next(
                (
                    index
                    for index, payload in enumerate(state["mappings"])
                    if str(payload.get("mapping_id") or "") == mapping_id
                ),
                None,
            )
            if index is None:
                raise MappingNotFound(f"Software mapping {mapping_id!r} was not found")
            current = SoftwareMapping.from_mapping(state["mappings"][index])
            if current.revision != expected_revision:
                raise MappingRevisionConflict(mapping_id, expected_revision, current.revision)
            if current.status != "suggested":
                raise MappingStatusConflict(
                    f"Software mapping {mapping_id!r} is already {current.status}"
                )
            when = timestamp or _now()
            after_provenance = {
                **current.provenance,
                "decision": decision,
                "reviewer": _bounded(actor, "actor"),
                "reason": str(reason or "").strip(),
                "decided_at": when,
                "scope_snapshot": _scope(scope_snapshot).to_dict(),
            }
            updated = SoftwareMapping(
                **{
                    **asdict(current),
                    "status": decision,
                    "provenance": after_provenance,
                    "reason": str(reason or "").strip(),
                    "revision": current.revision + 1,
                    "updated_at": when,
                }
            )
            state["mappings"][index] = updated.to_dict()
            state["revision"] += 1
            state["updated_at"] = when
            state["audit_events"].append(
                {
                    "event_id": _audit_id(mapping_id, updated.revision, actor, decision),
                    "actor": actor,
                    "action": f"software_mapping.{decision}",
                    "mapping_id": mapping_id,
                    "timestamp": when,
                    "revision": updated.revision,
                    "repository_revision": state["revision"],
                    "scope_snapshot": _scope(scope_snapshot).to_dict(),
                    "before_provenance": dict(current.provenance),
                    "after_provenance": dict(after_provenance),
                    "mapping_provenance": {
                        "method": current.method,
                        "confidence": current.confidence,
                        "source_timestamp": current.source_timestamp,
                        "raw_identity": current.raw_identity,
                        "canonical_identity": current.canonical_identity,
                    },
                }
            )
            self._write_state(state, expected_revision=state["revision"] - 1)
            return updated

    def _read_state(self) -> dict[str, Any]:
        if self._memory is not None:
            payload = self._memory
        elif self.document_store is not None:
            payload = self.document_store.read(self.document_name)
            if not payload:
                return _initial_state()
        elif self.path is not None:
            if not self.path.exists():
                return _initial_state()
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError("Software mapping state is not valid JSON") from exc
        else:
            return _initial_state()
        if not isinstance(payload, dict):
            raise TypeError("Software mapping state must be an object")
        mappings = payload.get("mappings", [])
        events = payload.get("audit_events", [])
        if not isinstance(mappings, list) or any(not isinstance(item, dict) for item in mappings):
            raise TypeError("Software mapping mappings must be a list of objects")
        if not isinstance(events, list) or any(not isinstance(item, dict) for item in events):
            raise TypeError("Software mapping audit_events must be a list of objects")
        return {
            "revision": _nonnegative_int(payload.get("revision", 0)),
            "mappings": [dict(item) for item in mappings],
            "audit_events": [dict(item) for item in events],
            "updated_at": str(payload.get("updated_at") or ""),
        }

    def _write_state(self, state: dict[str, Any], *, expected_revision: int) -> None:
        payload = {
            "schema_version": self._SCHEMA_VERSION,
            "revision": state["revision"],
            "mappings": state["mappings"],
            "audit_events": state["audit_events"],
            "updated_at": state["updated_at"],
        }
        if self.document_store is not None:
            self.document_store.write(
                self.document_name, payload, expected_revision=expected_revision
            )
            return
        if self.path is None:
            self._memory = payload
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            dir=self.path.parent, prefix=f".{self.path.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def _initial_state() -> dict[str, Any]:
    return {"revision": 0, "mappings": [], "audit_events": [], "updated_at": ""}


def _mapping_id(raw_name: str, raw_version: str, publisher: str, scope: Any) -> str:
    material = "\x1f".join(
        (str(raw_name).strip(), str(raw_version).strip(), str(publisher).strip(), json.dumps(scope.to_dict(), sort_keys=True))
    )
    return f"software-map://{hashlib.sha256(material.encode()).hexdigest()[:32]}"


def _audit_id(mapping_id: str, revision: int, actor: str, decision: str) -> str:
    material = f"{mapping_id}|{revision}|{actor}|{decision}"
    return f"software-audit://{hashlib.sha256(material.encode()).hexdigest()[:32]}"


def _bounded(value: Any, field_name: str, maximum: int = 512) -> str:
    text = str(value or "").strip()
    if not text or len(text) > maximum:
        raise ValueError(f"Software mapping {field_name} is required and bounded")
    return text


def _nonnegative_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("Software mapping revision must be a non-negative integer")
    return value


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _scope(payload: Mapping[str, Any] | None) -> Any:
    # Import lazily: api.__init__ imports the routers, and mapping routes import
    # this repository.  A top-level api.scope import would create a cycle.
    from api.scope import Scope

    return Scope.from_mapping(payload)
