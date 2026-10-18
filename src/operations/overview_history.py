"""Bounded, exact-owner/scope observations; not an automatic historical backfill."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore

MAX_OBSERVATIONS = 30
MAX_HISTORY_BYTES = 256 * 1024


class HistoryCapture(BaseModel):
    """Capture only against the reviewed history revision."""

    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: int = Field(ge=0)


class OverviewSource(BaseModel):
    """Allowlisted provenance and extent for one server-composed source read."""

    model_config = ConfigDict(extra="forbid", strict=True)
    id: Literal["situations", "network", "exposure"]
    started_at: str = Field(max_length=40)
    finished_at: str = Field(max_length=40)
    observed_at: list[str] = Field(max_length=20)
    source_tables: list[str] = Field(max_length=20)
    knowledge_version: str = Field(max_length=256)
    loaded: int | None = Field(ge=0)
    total: int | None = Field(ge=0)
    partial: bool
    warning_count: int = Field(ge=0)

    @field_validator("started_at", "finished_at")
    @classmethod
    def collection_timestamp(cls, value: str) -> str:
        """Require actual timezone-aware collection times."""
        if datetime.fromisoformat(value).tzinfo is None:
            raise ValueError("Collection timestamp must be timezone-aware")
        return value


class OverviewObservation(BaseModel):
    """Immutable server observation; raw records and credentials are never retained."""

    model_config = ConfigDict(extra="forbid", strict=True)
    observation_id: str = Field(pattern=r"^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$")
    captured_at: str = Field(max_length=40)
    formula_version: Literal["overview-v1"] = "overview-v1"
    critical_situations: int = Field(ge=0, le=100)
    exposed_findings: int = Field(ge=0, le=9_007_199_254_740_991)
    network_gaps: int = Field(ge=0, le=9_007_199_254_740_991)
    sources: list[OverviewSource] = Field(min_length=3, max_length=3)

    @field_validator("captured_at")
    @classmethod
    def capture_timestamp(cls, value: str) -> str:
        """Require timezone-aware receipt times; never backfill missing history."""
        if datetime.fromisoformat(value).tzinfo is None:
            raise ValueError("Capture timestamp must be timezone-aware")
        return value


class OverviewHistory(BaseModel):
    """One atomic history document per exact principal/effective scope."""

    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[1] = 1
    actor: str
    scope: dict[str, list[str]]
    revision: int = Field(ge=0)
    observations: list[OverviewObservation] = Field(max_length=MAX_OBSERVATIONS)


class OverviewHistoryStore:
    """Retain the latest 30 explicit captures using atomic local/OneLake CAS."""

    def __init__(self, documents: OneLakeDocumentStore):
        self.documents = documents

    @staticmethod
    def _name(actor: str, scope: dict[str, list[str]]) -> str:
        identity = json.dumps([actor, scope], sort_keys=True, separators=(",", ":"))
        return f"state/overview-history/{hashlib.sha256(identity.encode()).hexdigest()}.json"

    def _read(self, actor: str, scope: dict[str, list[str]]):
        name = self._name(actor, scope)
        snapshot = self.documents.read_snapshot(name)
        if (
            snapshot.exists
            and len(
                (json.dumps(snapshot.payload, indent=2, sort_keys=True) + "\n").encode()
            )
            > MAX_HISTORY_BYTES
        ):
            raise RuntimeError("Stored Overview history exceeds its document limit")
        try:
            state = (
                OverviewHistory.model_validate(snapshot.payload)
                if snapshot.exists
                else OverviewHistory(
                    actor=actor,
                    scope=scope,
                    revision=0,
                    observations=[],
                )
            )
        except ValidationError as exc:
            raise RuntimeError("Stored Overview history schema is invalid") from exc
        if state.actor != actor or state.scope != scope:
            raise RuntimeError("Stored Overview history identity is invalid")
        ids = [row.observation_id for row in state.observations]
        if len(set(ids)) != len(ids):
            raise RuntimeError(
                "Stored Overview history contains duplicate observations"
            )
        if len(state.observations) != min(state.revision, MAX_OBSERVATIONS):
            raise RuntimeError("Stored Overview history revision is invalid")
        for row in state.observations:
            if {source.id for source in row.sources} != {
                "situations",
                "network",
                "exposure",
            }:
                raise RuntimeError("Stored Overview observation sources are invalid")
        return name, snapshot, state

    def read(self, actor: str, scope: dict[str, list[str]]) -> dict:
        """Read retained observations without resolving current providers."""
        _, _, state = self._read(actor, scope)
        return state.model_dump()

    def append(
        self,
        actor: str,
        scope: dict[str, list[str]],
        expected_revision: int,
        *,
        critical_situations: int,
        exposed_findings: int,
        network_gaps: int,
        sources: list[OverviewSource],
    ) -> dict:
        """Append once or conflict; failed acquisitions never advance history."""
        name, snapshot, state = self._read(actor, scope)
        if state.revision != expected_revision:
            raise DocumentConflictError(
                "Overview history changed; reload before capturing"
            )
        observation = OverviewObservation(
            observation_id=str(uuid4()),
            captured_at=datetime.now(UTC).isoformat(),
            critical_situations=critical_situations,
            exposed_findings=exposed_findings,
            network_gaps=network_gaps,
            sources=sources,
        )
        if {source.id for source in sources} != {"situations", "network", "exposure"}:
            raise ValueError("All three Overview sources are required")
        state.observations = [*state.observations, observation][-MAX_OBSERVATIONS:]
        state.revision += 1
        payload = state.model_dump()
        if (
            len((json.dumps(payload, indent=2, sort_keys=True) + "\n").encode())
            > MAX_HISTORY_BYTES
        ):
            raise ValueError("Overview history exceeds its 256 KiB document limit")
        if snapshot.exists:
            self.documents.replace_if_match(name, payload, expected_etag=snapshot.etag)
        else:
            self.documents.create_only(name, payload)
        return payload
