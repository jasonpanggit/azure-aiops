"""Personal retained Twin projections, never raw provider payloads or authority."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore

from .operational_twin import _scope_attributes

MAX_CAPTURES = 10
MAX_CAPTURE_BYTES = 2 * 1024 * 1024
MAX_HISTORY_BYTES = 12 * 1024 * 1024
MAX_REVISION = 9_007_199_254_740_991
Identity = Annotated[str, Field(min_length=1, max_length=4096)]
SnapshotId = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Confidence = Literal["high", "medium", "low", "unknown"]
Attribute = Literal[
    "subscription", "subscription_connection", "business_service", "application",
    "environment", "owner", "support_team", "region", "criticality",
    "entity_type", "severity", "status",
]


def _bytes(payload: dict) -> int:
    return len((json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n").encode())


def _digest(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()
    ).hexdigest()


def _aware(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("Twin capture times must be timezone-aware")
    return parsed


class TwinSource(BaseModel):
    """Allowlisted source labels, not citations containing raw provider objects."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    source: str = Field(min_length=1, max_length=128)
    confidence: Confidence


class RetainedEntity(BaseModel):
    """Safe entity declaration; arbitrary semantic attributes and tags are excluded."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    id: Identity
    kind: str = Field(min_length=1, max_length=128)
    name: str = Field(max_length=512)
    state: str = Field(max_length=128)
    confidence: Confidence
    attributes: dict[Attribute, Annotated[str, Field(max_length=512)]]
    provenance: list[TwinSource] = Field(max_length=20)


class RetainedRelationship(BaseModel):
    """A reported relationship whose two endpoints are retained."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    id: Identity
    source: Identity
    target: Identity
    type: str = Field(min_length=1, max_length=256)
    confidence: Confidence
    provenance: list[TwinSource] = Field(max_length=20)


class TwinProjection(BaseModel):
    """Bounded safe composition, not a full graph export or source-time guarantee."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    schema_version: int = Field(ge=1, le=1)
    scope: dict[str, list[str]]
    composed_at: str = Field(max_length=40)
    entities: list[RetainedEntity] = Field(max_length=5000)
    relationships: list[RetainedRelationship] = Field(max_length=20_000)
    provenance: list[TwinSource] = Field(max_length=20)
    warnings: list[Annotated[str, Field(max_length=1024)]] = Field(max_length=50)

    @model_validator(mode="after")
    def coherent_projection(self):
        """Reject duplicate/dangling identities and non-aware composition timestamps."""
        _aware(self.composed_at)
        ids = {row.id for row in self.entities}
        if len(ids) != len(self.entities):
            raise ValueError("Twin entity identities must be unique")
        if len({row.id for row in self.relationships}) != len(self.relationships):
            raise ValueError("Twin relationship identities must be unique")
        if any(row.source not in ids or row.target not in ids for row in self.relationships):
            raise ValueError("Retained Twin relationship endpoints must exist")
        return self


class TwinCapture(BaseModel):
    """Immutable server capture with a checked projection digest, not a signature."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    snapshot_id: SnapshotId
    snapshot_sha256: Digest
    retained_at: str = Field(max_length=40)
    projection: TwinProjection

    @model_validator(mode="after")
    def coherent_capture(self):
        """Validate digest, ordering and the exact serialized byte ceiling."""
        if self.snapshot_sha256 != _digest(self.projection.model_dump()):
            raise ValueError("Twin projection digest does not match")
        if _aware(self.retained_at) < _aware(self.projection.composed_at):
            raise ValueError("Twin retention precedes composition")
        if _bytes(self.model_dump()) > MAX_CAPTURE_BYTES:
            raise ValueError("Twin capture exceeds 2 MiB; narrow the scope")
        return self


class TwinHistory(BaseModel):
    """One actor/effective-scope CAS collection with explicit deletion only."""

    model_config = ConfigDict(strict=True, extra="forbid")
    schema_version: int = Field(ge=1, le=1)
    actor: str = Field(min_length=1)
    scope: dict[str, list[str]]
    revision: int = Field(ge=0, le=MAX_REVISION)
    updated_at: str = Field(max_length=40)
    captures: list[TwinCapture] = Field(max_length=MAX_CAPTURES)

    @model_validator(mode="after")
    def coherent_history(self):
        """Reject corrupt identities, scope membership, timestamps and collection size."""
        ids = {capture.snapshot_id for capture in self.captures}
        if len(ids) != len(self.captures) or len(ids) > self.revision:
            raise ValueError("Twin snapshot identities are invalid")
        if any(capture.projection.scope != self.scope for capture in self.captures):
            raise ValueError("Twin capture scope does not match its collection")
        if self.revision == 0:
            if self.captures or self.updated_at:
                raise ValueError("Unsaved Twin history must be empty")
        elif not self.updated_at or _aware(self.updated_at) < max(
            (_aware(capture.retained_at) for capture in self.captures),
            default=datetime.min.replace(tzinfo=UTC),
        ):
            raise ValueError("Twin history update time is invalid")
        if _bytes(self.model_dump()) > MAX_HISTORY_BYTES:
            raise ValueError("Twin history exceeds 12 MiB; explicitly delete a capture")
        return self


class TwinCaptureRequest(BaseModel):
    """Request a fresh server composition, never submit an arbitrary graph."""

    model_config = ConfigDict(strict=True, extra="forbid")
    expected_revision: int = Field(ge=0, lt=MAX_REVISION)


class TwinCaptureRemoval(TwinCaptureRequest):
    """Explicitly identify one capture in the reviewed collection revision."""

    snapshot_id: SnapshotId


class TwinHistoryStore:
    """Persist immutable projections on the existing local/OneLake document root."""

    def __init__(self, documents: OneLakeDocumentStore):
        self.documents = documents

    @staticmethod
    def _name(actor: str, scope: dict) -> str:
        identity = json.dumps([actor, scope], sort_keys=True, separators=(",", ":"))
        return f"state/twin-history/{hashlib.sha256(identity.encode()).hexdigest()}.json"

    def _read(self, actor: str, scope: dict):
        name = self._name(actor, scope)
        try:
            snapshot = self.documents.read_snapshot(name)
            if snapshot.exists and _bytes(snapshot.payload) > MAX_HISTORY_BYTES:
                raise ValueError("Twin history exceeds its byte limit")
            history = TwinHistory.model_validate(snapshot.payload) if snapshot.exists else TwinHistory(
                schema_version=1, actor=actor, scope=scope, revision=0, updated_at="", captures=[],
            )
        except (ValidationError, TypeError, ValueError, RecursionError) as exc:
            raise RuntimeError("Stored Twin history is invalid") from exc
        if (history.actor, history.scope) != (actor, scope):
            raise RuntimeError("Stored Twin history identity is invalid")
        return name, snapshot, history

    def read(self, actor: str, scope: dict) -> dict:
        """Read exact personal history without acquiring any current provider."""
        return self._read(actor, scope)[2].model_dump()

    def update(
        self, actor: str, scope: dict, expected_revision: int, *,
        capture: TwinCapture | None = None, remove: str | None = None,
    ) -> dict:
        """Perform one revision/ETag-guarded append or explicit removal, never eviction."""
        if (capture is None) == (remove is None):
            raise ValueError("Select exactly one Twin history mutation")
        name, snapshot, history = self._read(actor, scope)
        if history.revision != expected_revision or history.revision >= MAX_REVISION:
            raise DocumentConflictError("Twin history changed; reload before continuing")
        rows = history.captures
        if capture is not None:
            if any(row.snapshot_id == capture.snapshot_id for row in rows):
                raise DocumentConflictError("Twin snapshot is already retained")
            if len(rows) >= MAX_CAPTURES:
                raise ValueError("Twin history is full; explicitly delete a capture")
            rows = [*rows, capture]
        else:
            if not any(row.snapshot_id == remove for row in rows):
                raise KeyError("Retained Twin snapshot was not found")
            rows = [row for row in rows if row.snapshot_id != remove]
        payload = {
            "schema_version": 1, "actor": actor, "scope": scope,
            "revision": history.revision + 1, "updated_at": datetime.now(UTC).isoformat(),
            "captures": [row.model_dump() for row in rows],
        }
        if _bytes(payload) > MAX_HISTORY_BYTES:
            raise ValueError("Twin history exceeds 12 MiB; explicitly delete a capture")
        updated = TwinHistory.model_validate(payload).model_dump()
        if snapshot.exists:
            self.documents.replace_if_match(name, updated, expected_etag=snapshot.etag)
        else:
            self.documents.create_only(name, updated)
        return updated


def capture_projection(snapshot: dict, scope: dict) -> TwinCapture:
    """Project one fresh server composition; reject rather than truncate unsafe input."""
    if snapshot["scope"] != scope:
        raise RuntimeError("Twin composition scope is not confirmed")
    if len(snapshot["entities"]) > 5000 or len(snapshot["relationships"]) > 20_000:
        raise ValueError("Twin capture exceeds 5000 entities or 20000 relationships; narrow the scope")

    def sources(rows: list[dict]) -> list[dict]:
        projected = [
            TwinSource(source=row["source"], confidence=row["confidence"]).model_dump()
            for row in rows
        ]
        return sorted(projected, key=lambda row: (row["source"], row["confidence"]))

    entities = []
    for entity in snapshot["entities"]:
        properties = entity["properties"]
        attributes = {
            **_scope_attributes(properties.get("semantic_attributes", {})),
            **_scope_attributes(properties),
        }
        for key in ("entity_type", "severity", "status"):
            if key in properties:
                attributes[key] = properties[key]
        entities.append(RetainedEntity(
            id=entity["id"], kind=entity["kind"], name=entity["name"],
            state=entity["state"], confidence=entity["confidence"],
            attributes=attributes, provenance=sources(entity["provenance"]),
        ))
    projection = TwinProjection(
        schema_version=1, scope=scope, composed_at=snapshot["observed_at"],
        entities=sorted(entities, key=lambda row: row.id),
        relationships=sorted([
            RetainedRelationship(
                id=row["id"], source=row["source"], target=row["target"],
                type=row["type"], confidence=row["confidence"], provenance=sources(row["provenance"]),
            ) for row in snapshot["relationships"]
        ], key=lambda row: row.id),
        provenance=sources(snapshot["provenance"]), warnings=snapshot["warnings"],
    )
    payload = {
        "snapshot_id": uuid4().hex, "snapshot_sha256": _digest(projection.model_dump()),
        "retained_at": datetime.now(UTC).isoformat(), "projection": projection.model_dump(),
    }
    if _bytes(payload) > MAX_CAPTURE_BYTES:
        raise ValueError("Twin capture exceeds 2 MiB; narrow the scope")
    return TwinCapture.model_validate(payload)


def compare_captures(baseline: TwinCapture, candidate: TwinCapture) -> dict:
    """Compare retained safe declarations, not source changes, lineage or outcomes."""
    if baseline.snapshot_id == candidate.snapshot_id:
        raise ValueError("Select two different retained Twin snapshots")
    if baseline.projection.scope != candidate.projection.scope:
        raise ValueError("Retained Twin scopes must match exactly")

    def delta(before_rows: list, after_rows: list) -> dict:
        before = {row.id: row.model_dump() for row in before_rows}
        after = {row.id: row.model_dump() for row in after_rows}
        common = before.keys() & after.keys()
        return {
            "added": [after[key] for key in sorted(after.keys() - before.keys())],
            "removed": [before[key] for key in sorted(before.keys() - after.keys())],
            "changed": [
                {"id": key, "before": before[key], "after": after[key],
                 "fields": sorted(field for field in before[key] if before[key][field] != after[key][field])}
                for key in sorted(common) if before[key] != after[key]
            ],
        }

    return {
        "baseline_id": baseline.snapshot_id, "candidate_id": candidate.snapshot_id,
        "baseline_sha256": baseline.snapshot_sha256, "candidate_sha256": candidate.snapshot_sha256,
        "baseline_composed_at": baseline.projection.composed_at,
        "candidate_composed_at": candidate.projection.composed_at,
        "entities": delta(baseline.projection.entities, candidate.projection.entities),
        "relationships": delta(baseline.projection.relationships, candidate.projection.relationships),
        "warnings": {"baseline": baseline.projection.warnings, "candidate": candidate.projection.warnings},
        "interpretation": (
            "Historical safe declarations only. Differences may reflect provider availability, scope metadata "
            "or composition time, not applied changes, causal failures, revision lineage or verified outcomes. "
            "Entity observation timestamps and raw properties are not retained or compared."
        ),
    }
