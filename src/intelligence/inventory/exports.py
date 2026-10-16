"""Bounded exact-scope export captures, independent of later active generations."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from storage.onelake_documents import (
    DocumentConflictError,
    DocumentSnapshot,
    OneLakeDocumentStore,
)

EXPORT_COLUMNS = (
    "family",
    "resource_name",
    "resource_type",
    "resource_id",
    "subscription_id",
    "resource_group",
    "environment",
    "location",
    "observed_at",
)
MAX_EXPORT_ROWS = 50_000
MAX_EXPORT_BYTES = 16 * 1024 * 1024
EXPORT_BATCH_SIZE = 500


class ExportCreate(BaseModel):
    """Pin the publication the caller reviewed; never substitute a query version."""

    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    expected_generation_id: str = Field(min_length=1, max_length=256)


class ExportCancel(BaseModel):
    """Cancel only the revision the caller observed."""

    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: int = Field(ge=1)


class ExportCapture(BaseModel):
    """One durable capture per exact principal and effective scope."""

    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[1] = 1
    export_id: str = Field(pattern=r"^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$")
    actor: str = Field(min_length=1)
    scope: dict[str, list[str]]
    revision: int = Field(ge=1)
    status: Literal["ready", "cancelled", "expired"]
    generation_id: str = Field(min_length=1, max_length=256)
    query_version: str
    observed_at: str
    created_at: str
    expires_at: str
    total: int = Field(ge=1, le=MAX_EXPORT_ROWS)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rows: list[dict[str, str]] = Field(max_length=MAX_EXPORT_ROWS)


def _checksum(rows: list[dict[str, str]], generation_id: str) -> str:
    return hashlib.sha256(
        json.dumps(
            {"generation_id": generation_id, "rows": rows},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode()
    ).hexdigest()


class InventoryExportStore:
    """Capture allowlisted rows once, with ETag cancellation and lazy expiry cleanup."""

    def __init__(
        self,
        documents: OneLakeDocumentStore,
        *,
        clock: Callable[[], datetime] | None = None,
    ):
        self.documents = documents
        self.clock = clock or (lambda: datetime.now(UTC))

    @staticmethod
    def _name(actor: str, scope: dict[str, list[str]]) -> str:
        identity = json.dumps(
            [actor, scope], sort_keys=True, separators=(",", ":")
        ).encode()
        return f"state/inventory-exports/{hashlib.sha256(identity).hexdigest()}.json"

    def _read(
        self, actor: str, scope: dict[str, list[str]]
    ) -> tuple[str, DocumentSnapshot, ExportCapture | None]:
        name = self._name(actor, scope)
        snapshot = self.documents.read_snapshot(name)
        if not snapshot.exists:
            return name, snapshot, None
        try:
            state = ExportCapture.model_validate(snapshot.payload)
        except ValidationError as exc:
            raise RuntimeError("Stored inventory export is invalid") from exc
        if state.actor != actor or state.scope != scope:
            raise RuntimeError("Stored inventory export identity is invalid")
        try:
            expiry = datetime.fromisoformat(state.expires_at)
        except ValueError as exc:
            raise RuntimeError("Stored inventory export expiry is invalid") from exc
        if expiry.tzinfo is None:
            raise RuntimeError("Stored inventory export expiry is invalid")
        if state.status == "ready":
            if len(state.rows) != state.total or any(
                set(row) != set(EXPORT_COLUMNS) for row in state.rows
            ):
                raise RuntimeError("Stored inventory export rows are invalid")
            if _checksum(state.rows, state.generation_id) != state.sha256:
                raise RuntimeError("Stored inventory export checksum is invalid")
            if self.clock() >= expiry:
                state.status = "expired"
                state.rows = []
                state.revision += 1
                snapshot = self.documents.replace_if_match(
                    name, state.model_dump(), expected_etag=snapshot.etag
                )
        elif state.rows:
            raise RuntimeError("Inactive inventory export still contains rows")
        return name, snapshot, state

    @staticmethod
    def metadata(state: ExportCapture) -> dict[str, Any]:
        """Return the manifest, never the captured rows."""
        return {
            **state.model_dump(exclude={"rows"}),
            "columns": list(EXPORT_COLUMNS),
            "batch_size": EXPORT_BATCH_SIZE,
            "resume_basis": "captured_rows_not_active_generation",
        }

    def current(self, actor: str, scope: dict[str, list[str]]) -> dict[str, Any] | None:
        """Read only this principal's exact-scope capture; expiry removes its row body."""
        _, _, state = self._read(actor, scope)
        return self.metadata(state) if state else None

    def create(
        self,
        actor: str,
        scope: dict[str, list[str]],
        *,
        generation_id: str,
        query_version: str,
        observed_at: str,
        rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Persist a bounded complete capture; never truncate or replace an active capture."""
        if not generation_id.strip():
            raise ValueError("An immutable inventory generation is required for export")
        if not rows or len(rows) > MAX_EXPORT_ROWS:
            raise ValueError(
                "Inventory capture requires 1–50000 rows; narrow the selected scope"
            )
        safe_rows = [
            {key: str(row.get(key) or "") for key in EXPORT_COLUMNS} for row in rows
        ]
        safe_rows.sort(key=lambda row: (row["family"], row["resource_id"]))
        if len(json.dumps(safe_rows, ensure_ascii=True).encode()) > MAX_EXPORT_BYTES:
            raise ValueError(
                "Inventory capture exceeds 16 MiB; narrow the selected scope"
            )
        name, snapshot, current = self._read(actor, scope)
        if current and current.status == "ready":
            raise DocumentConflictError(
                "An export capture already exists; resume it or cancel it before replacing"
            )
        now = self.clock()
        state = ExportCapture(
            export_id=str(uuid4()),
            actor=actor,
            scope=scope,
            revision=(current.revision + 1) if current else 1,
            status="ready",
            generation_id=generation_id,
            query_version=query_version,
            observed_at=observed_at,
            created_at=now.isoformat(),
            expires_at=(now + timedelta(hours=24)).isoformat(),
            total=len(safe_rows),
            sha256=_checksum(safe_rows, generation_id),
            rows=safe_rows,
        )
        if (
            len(
                (
                    json.dumps(state.model_dump(), indent=2, sort_keys=True) + "\n"
                ).encode()
            )
            > MAX_EXPORT_BYTES
        ):
            raise ValueError(
                "Inventory capture exceeds 16 MiB; narrow the selected scope"
            )
        if snapshot.exists:
            self.documents.replace_if_match(
                name, state.model_dump(), expected_etag=snapshot.etag
            )
        else:
            self.documents.create_only(name, state.model_dump())
        return self.metadata(state)

    def batch(
        self, actor: str, scope: dict[str, list[str]], export_id: str, offset: int
    ) -> dict[str, Any]:
        """Read a repeatable 500-row batch; offsets are explicit, not browser-held authority."""
        _, _, state = self._read(actor, scope)
        if state is None or state.export_id != export_id:
            raise LookupError("Inventory export not found")
        if state.status != "ready":
            raise DocumentConflictError(
                "Inventory export is cancelled or expired; create a new capture"
            )
        if offset < 0 or offset >= state.total or offset % EXPORT_BATCH_SIZE:
            raise ValueError("Export offset must identify an existing 500-row batch")
        end = min(offset + EXPORT_BATCH_SIZE, state.total)
        return {
            "manifest": self.metadata(state),
            "resources": state.rows[offset:end],
            "offset": offset,
            "next_offset": end if end < state.total else None,
        }

    def cancel(
        self, actor: str, scope: dict[str, list[str]], export_id: str, revision: int
    ) -> dict[str, Any]:
        """Revoke future batch reads and remove retained rows atomically."""
        name, snapshot, state = self._read(actor, scope)
        if state is None or state.export_id != export_id:
            raise LookupError("Inventory export not found")
        if state.revision != revision or state.status != "ready":
            raise DocumentConflictError(
                "Inventory capture changed; reload before cancelling"
            )
        state.revision += 1
        state.status = "cancelled"
        state.rows = []
        self.documents.replace_if_match(
            name, state.model_dump(), expected_etag=snapshot.etag
        )
        return self.metadata(state)
