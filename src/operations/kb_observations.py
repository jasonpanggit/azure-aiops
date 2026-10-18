"""Explicit retained KB source observations, not verified patch outcomes."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from operations.cve_evidence import receipt_digest
from operations.kb_review import canonical_kb
from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore

MAX_BYTES = 512 * 1024
MAX_INTEGER = 9_007_199_254_740_991


class CaptureKbObservation(BaseModel):
    """Only optimistic revision and displayed source generation are client inputs."""

    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: int = Field(ge=0, le=20)
    generation: str = Field(min_length=1, max_length=256)


class KbStatusCounts(BaseModel):
    """Whole-snapshot source population, never inferred from the bounded sample."""

    model_config = ConfigDict(extra="forbid", strict=True)
    observed_targets: int = Field(ge=0, le=MAX_INTEGER)
    missing: int = Field(ge=0, le=MAX_INTEGER)
    installation_failed: int = Field(ge=0, le=MAX_INTEGER)
    installed: int = Field(ge=0, le=MAX_INTEGER)
    other: int = Field(ge=0, le=MAX_INTEGER)

    @model_validator(mode="after")
    def distribution(self) -> KbStatusCounts:
        """Reject incompatible source distributions."""
        if self.observed_targets != self.missing + self.installation_failed + self.installed + self.other:
            raise ValueError("KB source status distribution is inconsistent")
        return self


class KbTargetObservation(BaseModel):
    """Allowlisted, bounded source target/status/time projection."""

    model_config = ConfigDict(extra="forbid", strict=True)
    target_id: str = Field(min_length=1, max_length=2048)
    status: str = Field(min_length=1, max_length=128)
    observed_at: str = Field(max_length=128)

    @field_validator("target_id", "status")
    @classmethod
    def nonblank(cls, value: str) -> str:
        """Blank observations do not establish source identity or state."""
        if not value.strip():
            raise ValueError("KB target identity and status must be nonblank")
        return value


class KbMsrcObservation(BaseModel):
    """Catalog availability and clock; no raw payload or dependency assertions."""

    model_config = ConfigDict(extra="forbid", strict=True)
    status: str = Field(min_length=1, max_length=128)
    stale: bool
    has_last_known_good: bool
    source_at: str = Field(max_length=128)


class KbObservation(BaseModel):
    """Server capture clock remains separate from independently observed sources."""

    model_config = ConfigDict(extra="forbid", strict=True)
    observation_id: str = Field(pattern=r"^kbo-[a-f0-9]{32}$")
    captured_at: str
    generation: str = Field(min_length=1, max_length=256)
    source_observed_at: str = Field(max_length=128)
    completeness: str = Field(min_length=1, max_length=128)
    freshness: str = Field(min_length=1, max_length=128)
    counts: KbStatusCounts | None
    targets: list[KbTargetObservation] = Field(max_length=100)
    targets_truncated: bool | None
    msrc: KbMsrcObservation | None

    @model_validator(mode="after")
    def coherent(self) -> KbObservation:
        """Validate the retained sample/count boundary before storage and on replay."""
        if datetime.fromisoformat(self.captured_at).utcoffset() is None or self.completeness == "unavailable":
            raise ValueError("KB capture clock or source availability is invalid")
        if len({row.target_id for row in self.targets}) != len(self.targets):
            raise ValueError("KB sample identities are duplicate")
        if self.counts is None:
            if self.targets_truncated is not None:
                raise ValueError("Unknown KB sample extent cannot be promoted")
        else:
            if self.counts.observed_targets < len(self.targets) or self.targets_truncated != (self.counts.observed_targets > len(self.targets)):
                raise ValueError("KB sample extent does not agree with population")
            sample = {"missing": 0, "installation_failed": 0, "installed": 0, "other": 0}
            for row in self.targets:
                key = row.status.lower()
                sample[key if key in sample else "other"] += 1
            if any(value > getattr(self.counts, key) for key, value in sample.items()):
                raise ValueError("KB sample statuses exceed source population")
        return self


class KbObservationHistory(BaseModel):
    """One exact-principal/scope/KB append-only source-observation history."""

    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[1] = 1
    actor: str = Field(min_length=1)
    scope: dict[str, list[str]]
    kb_id: str
    revision: int = Field(ge=0, le=20)
    observations: list[KbObservation] = Field(max_length=20)

    @model_validator(mode="after")
    def chain(self) -> KbObservationHistory:
        """Reject a corrupt identity or revision chain rather than reset history."""
        canonical_kb(self.kb_id)
        if self.revision != len(self.observations) or len({row.observation_id for row in self.observations}) != self.revision:
            raise ValueError("KB observation revision chain is inconsistent")
        return self


class KbObservationStore:
    """CAS-backed bounded receipts from the server's authorized current KB detail."""

    def __init__(self, documents: OneLakeDocumentStore):
        self.documents = documents

    @staticmethod
    def _name(actor: str, scope: dict, kb_id: str) -> str:
        return f"state/kb-observations/{receipt_digest({'actor': actor, 'scope': scope, 'kb_id': canonical_kb(kb_id)})}.json"

    @staticmethod
    def _bounded(payload: dict) -> None:
        if len((json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()) > MAX_BYTES:
            raise ValueError("KB observation history exceeds 512 KiB; no observations were evicted")

    def _read(self, actor: str, scope: dict, kb_id: str):
        name = self._name(actor, scope, kb_id)
        snapshot = self.documents.read_snapshot(name)
        if snapshot.exists:
            self._bounded(snapshot.payload)
            history = KbObservationHistory.model_validate(snapshot.payload)
        else:
            history = KbObservationHistory(actor=actor, scope=scope, kb_id=kb_id, revision=0, observations=[])
        if history.actor != actor or history.scope != scope or history.kb_id != kb_id:
            raise ValueError("KB observation history identity does not agree")
        return name, snapshot, history

    def read(self, actor: str, scope: dict, kb_id: str) -> dict:
        """Read only retained evidence; never query SQL or refresh providers."""
        return self._read(actor, scope, kb_id)[2].model_dump()

    def append(self, actor: str, scope: dict, kb_id: str, request: CaptureKbObservation, source: dict) -> dict:
        """Project an authorized server acquisition; browser evidence is not accepted."""
        name, snapshot, history = self._read(actor, scope, kb_id)
        if history.revision != request.expected_revision or history.revision >= 20:
            raise DocumentConflictError("KB observations changed or reached 20 records; reload. No observations were evicted")
        detail = source["data"]
        if source["scope"] != scope or detail["kb_id"] != kb_id:
            raise ValueError("KB observation acquisition identity does not agree")
        if detail["generation"] != request.generation:
            raise DocumentConflictError("Latest KB snapshot changed; refresh metadata before capture")
        state = detail["snapshot"]
        sources = [row for row in detail.get("enrichment", {}).get("sources", {}).values() if row["source"].lower() == "msrc"]
        if len(sources) > 1 or (sources and sources[0]["identifier"] != kb_id):
            raise ValueError("KB catalog source identity is inconsistent")
        msrc = None if not sources else KbMsrcObservation(**{
            key: sources[0][key] for key in ("status", "stale", "has_last_known_good", "source_at")
        })
        row = KbObservation(
            observation_id=f"kbo-{uuid4().hex}", captured_at=datetime.now(UTC).isoformat(), generation=request.generation,
            source_observed_at=state["as_of"], completeness=state["completeness"], freshness=state["freshness"],
            counts=detail.get("installation_status_counts"), targets=detail.get("target_status_observations", []),
            targets_truncated=detail.get("target_status_observations_truncated"), msrc=msrc,
        )
        stored = KbObservationHistory(
            actor=actor, scope=scope, kb_id=kb_id, revision=history.revision + 1, observations=[*history.observations, row],
        ).model_dump()
        self._bounded(stored)
        if snapshot.exists:
            self.documents.replace_if_match(name, stored, expected_etag=snapshot.etag)
        else:
            self.documents.create_only(name, stored)
        return stored
