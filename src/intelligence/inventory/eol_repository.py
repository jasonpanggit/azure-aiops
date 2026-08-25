"""Server-owned persistence for the curated operating-system lifecycle catalog.

The repository deliberately keeps review provenance and pending candidate
evidence outside the lifecycle rows.  A request reads the on-disk state on
every call, while confirmations use a compare-and-swap revision so a stale
operator cannot overwrite a newer review.
"""

from __future__ import annotations

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
    updated_at: str = ""


class EOLCatalogRepository(Protocol):
    """Persistence boundary used by lifecycle lookup and review services."""

    def read(self) -> CatalogSnapshot: ...

    def save_candidates(
        self,
        normalized_os_key: str,
        candidates: list[dict[str, Any]],
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
    ) -> None:
        self.path = Path(path) if path else Path.home() / ".hermes" / "state" / "eol_catalog.json"
        self.base_catalog = base_catalog or EOLCatalog.default()
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
            return CatalogSnapshot(
                catalog=catalog,
                revision=state["revision"],
                provenance=tuple(dict(item) for item in state["provenance"]),
                candidates=candidates,
                updated_at=state["updated_at"],
            )

    def save_candidates(
        self,
        normalized_os_key: str,
        candidates: list[dict[str, Any]],
    ) -> CatalogSnapshot:
        key = _normalized_key(normalized_os_key)
        if not key:
            raise ValueError("A normalized OS key is required")
        with self._lock:
            state = self._read_state()
            state["candidates"][key] = [dict(item) for item in candidates]
            state["updated_at"] = _now()
            self._write_state(state)
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
            state["revision"] = current + 1
            state["updated_at"] = _now()
            self._write_state(state)
            return self.read()

    def _read_state(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "revision": 0,
                "overrides": [],
                "provenance": [],
                "candidates": {},
                "updated_at": "",
            }
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
            "candidates": _candidate_mapping(payload.get("candidates", {})),
            "updated_at": str(payload.get("updated_at") or ""),
        }

    def _write_state(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": self._SCHEMA_VERSION,
            "revision": state["revision"],
            "overrides": state["overrides"],
            "provenance": state["provenance"],
            "candidates": state["candidates"],
            "updated_at": state["updated_at"],
        }
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
