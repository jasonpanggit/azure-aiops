"""Server-owned persistence for the curated operating-system lifecycle catalog.

The repository deliberately keeps review provenance and pending candidate
evidence outside the lifecycle rows.  A request reads the on-disk state on
every call, while confirmations use a compare-and-swap revision so a stale
operator cannot overwrite a newer review.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from intelligence.lifecycle import EOLCatalog, LifecycleCatalogEntry


class CatalogRevisionConflict(RuntimeError):
    """Raised when a confirmation was based on an older catalog revision."""

    def __init__(self, expected: int, current: int) -> None:
        self.expected = expected
        self.current = current
        super().__init__(
            f"Lifecycle catalog revision conflict: expected {expected}, current {current}"
        )


class DuplicateCatalogConfirmation(RuntimeError):
    """Raised when an already-confirmed key is submitted again."""


@dataclass(frozen=True)
class CatalogSnapshot:
    """The current catalog plus review-only state."""

    catalog: EOLCatalog
    revision: int
    provenance: tuple[dict[str, Any], ...] = ()
    candidates: Mapping[str, tuple[dict[str, Any], ...]] | None = None
    source_failures: Mapping[str, tuple[dict[str, Any], ...]] | None = None
    audit_events: tuple[dict[str, Any], ...] = ()
    updated_at: str = ""


class RevisionedDocumentStore(Protocol):
    """Minimal local/OneLake document contract used by the catalog repository."""

    def read(self, name: str) -> dict[str, Any]: ...

    def write(
        self, name: str, payload: dict[str, Any], *, expected_revision: int
    ) -> None: ...


class EOLCatalogRepository(Protocol):
    """Persistence boundary used by lifecycle lookup and review services."""

    def read(self) -> CatalogSnapshot: ...

    def save_candidates(
        self,
        normalized_os_key: str,
        candidates: list[dict[str, Any]],
        source_failures: list[dict[str, Any]] | None = None,
    ) -> CatalogSnapshot: ...

    def confirm(
        self,
        normalized_os_key: str,
        entry: LifecycleCatalogEntry,
        provenance: dict[str, Any],
        *,
        expected_revision: int,
    ) -> CatalogSnapshot: ...


class LocalEOLCatalogRepository:
    """Atomically persist catalog overrides and review state in one local file.

    ``base_catalog`` is the packaged curated catalog.  The file contains only
    operator-confirmed overrides, pending candidate records, and provenance, so
    upgrading the packaged catalog remains possible without discarding review
    history.
    """

    _SCHEMA_VERSION = "1.0.0"

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        base_catalog: EOLCatalog | None = None,
        document_store: RevisionedDocumentStore | None = None,
        document_name: str = "state/eol_catalog.json",
    ) -> None:
        if document_store is not None and path is not None:
            raise ValueError("Use either path or document_store, not both")
        self.path = (
            Path(path)
            if path
            else Path.home() / ".hermes" / "state" / "eol_catalog.json"
        )
        self.base_catalog = base_catalog or EOLCatalog.default()
        self.document_store = document_store
        self.document_name = document_name
        self._lock = threading.RLock()

    def read(self) -> CatalogSnapshot:
        with self._lock:
            state = self._read_state()
            overrides = state["overrides"]
            catalog = self.base_catalog.update(overrides) if overrides else self.base_catalog
            candidates = {
                key: tuple(dict(item) for item in rows)
                for key, rows in state["candidates"].items()
            }
            source_failures = {
                key: tuple(dict(item) for item in rows)
                for key, rows in state["source_failures"].items()
            }
            return CatalogSnapshot(
                catalog=catalog,
                revision=state["revision"],
                provenance=tuple(dict(item) for item in state["provenance"]),
                candidates=candidates,
                source_failures=source_failures,
                audit_events=tuple(dict(item) for item in state["audit_events"]),
                updated_at=state["updated_at"],
            )

    def save_candidates(
        self,
        normalized_os_key: str,
        candidates: list[dict[str, Any]],
        source_failures: list[dict[str, Any]] | None = None,
    ) -> CatalogSnapshot:
        key = _normalized_key(normalized_os_key)
        if not key:
            raise ValueError("A normalized OS key is required")
        with self._lock:
            state = self._read_state()
            state["candidates"][key] = [dict(item) for item in candidates]
            state["source_failures"][key] = [
                dict(item) for item in (source_failures or [])
            ]
            state["updated_at"] = _now()
            self._write_state(state, expected_revision=state["revision"])
            return self.read()

    def confirm(
        self,
        normalized_os_key: str,
        entry: LifecycleCatalogEntry,
        provenance: dict[str, Any],
        *,
        expected_revision: int,
    ) -> CatalogSnapshot:
        key = _normalized_key(normalized_os_key)
        if not key:
            raise ValueError("A normalized OS key is required")
        if _normalized_key(f"{entry.product}|{entry.version}") != key:
            raise ValueError("Lifecycle entry does not match the normalized OS key")
        with self._lock:
            state = self._read_state()
            current = state["revision"]
            if expected_revision != current:
                raise CatalogRevisionConflict(expected_revision, current)
            if key in {
                _normalized_key(f"{row.get('product', '')}|{row.get('version', '')}")
                for row in state["overrides"]
            }:
                raise DuplicateCatalogConfirmation(
                    f"Lifecycle entry for {key} has already been confirmed"
                )
            state["overrides"].append(entry.to_dict())
            state["provenance"].append(dict(provenance))
            state["candidates"].pop(key, None)
            state["source_failures"].pop(key, None)
            state["revision"] = current + 1
            state["updated_at"] = _now()
            state["audit_events"].append(
                {
                    "event_id": _audit_event_id(key, provenance),
                    "actor": str(provenance.get("reviewer") or "unknown"),
                    "action": "lifecycle.confirmed",
                    "normalized_os_key": key,
                    "timestamp": str(provenance.get("reviewed_at") or state["updated_at"]),
                    "source_references": [str(provenance.get("citation") or "")],
                    "selected_candidate_id": str(
                        provenance.get("selected_candidate_id") or ""
                    ),
                    "catalog_revision": state["revision"],
                }
            )
            self._write_state(state, expected_revision=current)
            return self.read()

    def _read_state(self) -> dict[str, Any]:
        if self.document_store is not None:
            payload = self.document_store.read(self.document_name)
            if not payload:
                return self._initial_state()
        else:
            if not self.path.exists():
                return self._initial_state()
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError("Lifecycle catalog state is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise TypeError("Lifecycle catalog state must be an object")
        return {
            "revision": _nonnegative_int(payload.get("revision", 0), "revision"),
            "overrides": _list_of_mappings(payload.get("overrides", []), "overrides"),
            "provenance": _list_of_mappings(payload.get("provenance", []), "provenance"),
            "audit_events": _list_of_mappings(
                payload.get("audit_events", []), "audit_events"
            ),
            "candidates": _candidate_mapping(payload.get("candidates", {})),
            "source_failures": _candidate_mapping(
                payload.get("source_failures", {})
            ),
            "updated_at": str(payload.get("updated_at") or ""),
        }

    def _initial_state(self) -> dict[str, Any]:
        return {
            "revision": 0,
            "overrides": [],
            "provenance": [],
            "audit_events": [],
            "candidates": {},
            "source_failures": {},
            "updated_at": "",
        }

    def _write_state(
        self, state: dict[str, Any], *, expected_revision: int | None = None
    ) -> None:
        payload = {
            "schema_version": self._SCHEMA_VERSION,
            "catalog_seed": self.base_catalog.rows(),
            "revision": state["revision"],
            "overrides": state["overrides"],
            "provenance": state["provenance"],
            "audit_events": state["audit_events"],
            "candidates": state["candidates"],
            "source_failures": state["source_failures"],
            "updated_at": state["updated_at"],
        }
        if self.document_store is not None:
            self.document_store.write(
                self.document_name,
                payload,
                expected_revision=(
                    state["revision"]
                    if expected_revision is None
                    else expected_revision
                ),
            )
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            dir=self.path.parent,
            prefix=f".{self.path.name}.",
            suffix=".tmp",
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


def _normalized_key(value: str) -> str:
    parts = str(value or "").split("|")
    if len(parts) != 2:
        return ""
    product, version = (" ".join(part.casefold().split()) for part in parts)
    return f"{product}|{version}" if product and version else ""


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _audit_event_id(key: str, provenance: Mapping[str, Any]) -> str:
    material = "|".join(
        (
            key,
            str(provenance.get("reviewer") or ""),
            str(provenance.get("selected_candidate_id") or ""),
            str(provenance.get("manual_date") or ""),
            str(provenance.get("catalog_revision") or ""),
        )
    )
    return f"lifecycle://{hashlib.sha256(material.encode()).hexdigest()[:32]}"


def _nonnegative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"Lifecycle catalog {field_name} must be a non-negative integer")
    return value


def _list_of_mappings(value: Any, field_name: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise TypeError(f"Lifecycle catalog {field_name} must be a list of objects")
    return [dict(item) for item in value]


def _candidate_mapping(value: Any) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(value, dict):
        raise TypeError("Lifecycle catalog candidates must be an object")
    result: dict[str, list[dict[str, Any]]] = {}
    for key, rows in value.items():
        normalized = _normalized_key(str(key))
        if not normalized:
            raise ValueError("Lifecycle catalog candidate key is not normalized")
        result[normalized] = _list_of_mappings(rows, "candidate records")
    return result
