"""Explicit private Exposure aggregate receipts, not finding identity history."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore

FACETS = ("severity", "target_kind", "source_family", "sla_state", "completeness", "current_state")
MAX_OBSERVATIONS = 30
MAX_BYTES = 256 * 1024
MAX_COUNT = 9_007_199_254_740_991


class CaptureExposureObservation(BaseModel):
    """Only a reviewed revision and source generation may be submitted."""

    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: int = Field(ge=0, le=MAX_OBSERVATIONS)
    generation: str | None = Field(default=None, min_length=1, max_length=256, pattern=r"^[A-Za-z0-9._:-]+$")


class FacetCount(BaseModel):
    """One bounded source classification, never a resource or provider payload."""

    model_config = ConfigDict(extra="forbid", strict=True)
    value: str = Field(min_length=1, max_length=128)
    count: int = Field(ge=0, le=MAX_COUNT)


class ExposureObservation(BaseModel):
    """Immutable aggregate receipt with separate collection/source timestamps."""

    model_config = ConfigDict(extra="forbid", strict=True)
    observation_id: str = Field(pattern=r"^exo-[a-f0-9]{32}$")
    captured_at: str = Field(max_length=40)
    generation: str = Field(min_length=1, max_length=256)
    total_count: int = Field(ge=0, le=MAX_COUNT)
    facets: dict[str, list[FacetCount]]
    completeness_state: str = Field(min_length=1, max_length=40)
    represented_connections: int | None = Field(default=None, ge=0, le=MAX_COUNT)
    expected_connections: int | None = Field(default=None, ge=0, le=MAX_COUNT)
    excluded_count: int | None = Field(default=None, ge=0, le=MAX_COUNT)
    coverage_total_count: int | None = Field(default=None, ge=0, le=MAX_COUNT)
    freshness_state: str = Field(min_length=1, max_length=40)
    source_observed_at: str = Field(max_length=80)
    source_table: Literal["gold_exposure_facts", "silver_patch_snapshot_findings"]

    @model_validator(mode="after")
    def coherent(self) -> ExposureObservation:
        """Reject invalid clocks, unbounded or inconsistent classification groups."""
        if datetime.fromisoformat(self.captured_at).tzinfo is None:
            raise ValueError("Capture time requires a timezone")
        if self.source_observed_at and datetime.fromisoformat(self.source_observed_at).tzinfo is None:
            raise ValueError("Source observation time requires a timezone")
        if not self.facets or not set(self.facets).issubset(FACETS):
            raise ValueError("Unexpected or missing facet vocabulary")
        for rows in self.facets.values():
            if len(rows) > 40 or len({row.value.casefold() for row in rows}) != len(rows):
                raise ValueError("Facet group is duplicate or exceeds 40 classifications")
            if sum(row.count for row in rows) > self.total_count:
                raise ValueError("Facet classifications exceed the finding total")
        return self


class ExposureHistory(BaseModel):
    """One exact-subject/effective-scope document with no silent eviction."""

    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[1] = 1
    actor: str = Field(min_length=1)
    scope: dict[str, list[str]]
    revision: int = Field(ge=0, le=MAX_OBSERVATIONS)
    observations: list[ExposureObservation] = Field(max_length=MAX_OBSERVATIONS)

    @model_validator(mode="after")
    def coherent(self) -> ExposureHistory:
        """Every successful revision adds exactly one unique immutable receipt."""
        ids = [row.observation_id for row in self.observations]
        if len(ids) != len(set(ids)) or len(ids) != self.revision:
            raise ValueError("History revision/identities do not agree")
        return self


class ExposureHistoryStore:
    """Retain server-acquired aggregates using atomic create-only/ETag writes."""

    def __init__(self, documents: OneLakeDocumentStore):
        self.documents = documents

    @staticmethod
    def _name(actor: str, scope: dict[str, list[str]]) -> str:
        identity = json.dumps([actor, scope], sort_keys=True, separators=(",", ":"))
        return f"state/exposure-history/{hashlib.sha256(identity.encode()).hexdigest()}.json"

    @staticmethod
    def _bounded(payload: dict) -> None:
        if len((json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()) > MAX_BYTES:
            raise ValueError("Exposure history exceeds its 256 KiB limit")

    def _read(self, actor: str, scope: dict[str, list[str]]):
        name = self._name(actor, scope)
        snapshot = self.documents.read_snapshot(name)
        if snapshot.exists:
            self._bounded(snapshot.payload)
            state = ExposureHistory.model_validate(snapshot.payload)
        else:
            state = ExposureHistory(actor=actor, scope=scope, revision=0, observations=[])
        if state.actor != actor or state.scope != scope:
            raise ValueError("Exposure history identity does not agree")
        return name, snapshot, state

    def read(self, actor: str, scope: dict[str, list[str]]) -> dict:
        """Read retained state without acquiring current provider evidence."""
        return self._read(actor, scope)[2].model_dump()

    def append(self, actor: str, scope: dict[str, list[str]], expected_revision: int, source: dict) -> dict:
        """Retain allowlisted server response fields once; never accept browser counts."""
        name, snapshot, state = self._read(actor, scope)
        if state.revision != expected_revision:
            raise DocumentConflictError("Exposure history changed; reload before capturing")
        if state.revision >= MAX_OBSERVATIONS:
            raise DocumentConflictError("Exposure history holds 30 observations; no records were evicted")
        data = source["data"]
        if source["scope"] != scope or data["contract"]["query"]["scope"] != scope:
            raise ValueError("Acquired exposure scope does not agree")
        if data["contract"]["query"]["generation"] != data["generation"]:
            raise ValueError("Acquired generation does not agree")
        if (
            data["contract"].get("safe_error") is not None
            or data["completeness"]["state"] == "unavailable"
            or data["contract"]["completeness"]["state"] == "unavailable"
        ):
            raise ValueError("Unavailable exposure aggregates cannot be captured")
        completeness, freshness = data["contract"]["completeness"], data["contract"]["freshness"]
        observation = ExposureObservation(
            observation_id=f"exo-{uuid4().hex}", captured_at=datetime.now(UTC).isoformat(),
            generation=data["generation"], total_count=data["total_count"],
            facets={key: data["facets"][key] for key in FACETS if key in data["facets"]},
            completeness_state=completeness["state"],
            represented_connections=completeness.get("represented_connections"),
            expected_connections=completeness.get("expected_connections"),
            excluded_count=completeness.get("excluded", completeness.get("excluded_count")),
            coverage_total_count=completeness.get("total", completeness.get("total_count")),
            freshness_state=freshness["state"], source_observed_at=freshness.get("as_of") or "",
            source_table="silver_patch_snapshot_findings" if data["generation"].startswith("silver-patch:") else "gold_exposure_facts",
        )
        updated = ExposureHistory(
            actor=actor, scope=scope, revision=state.revision + 1,
            observations=[*state.observations, observation],
        ).model_dump()
        self._bounded(updated)
        if snapshot.exists:
            self.documents.replace_if_match(name, updated, expected_etag=snapshot.etag)
        else:
            self.documents.create_only(name, updated)
        return updated
