"""Explicit, bounded service-label portfolio observations; never service telemetry."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore

MAX_SERVICES = 250
MAX_OBSERVATIONS = 20
MAX_HISTORY_BYTES = 2 * 1024 * 1024


def _aware(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("Portfolio collection times must be timezone-aware")
    return parsed


def _key(kind: str, name: str) -> str:
    return hashlib.sha256(json.dumps([kind, name]).encode()).hexdigest()


class PortfolioService(BaseModel):
    """Only service-label aggregates; no raw connection/resource identities."""

    model_config = ConfigDict(extra="forbid", strict=True)
    service_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    kind: Literal["service", "unmapped"]
    name: str = Field(max_length=256)
    connection_rows: int = Field(ge=0)
    mapped_rows: int = Field(ge=0)
    missing_owner: int = Field(ge=0)
    missing_support_team: int = Field(ge=0)
    missing_environment: int = Field(ge=0)
    subscription_count: int = Field(ge=0)
    incident_associations: int = Field(ge=0, le=100)
    critical_associations: int = Field(ge=0, le=100)

    @model_validator(mode="after")
    def consistent(self):
        """Reject contradictory aggregate or identity state, including corrupt reads."""
        if self.service_key != _key(self.kind, self.name):
            raise ValueError("Portfolio service identity is invalid")
        if self.name != self.name.strip() or (self.kind == "unmapped") != (
            not self.name
        ):
            raise ValueError("Unmapped portfolio identity requires an empty name")
        if (
            any(
                value > self.connection_rows
                for value in (
                    self.mapped_rows,
                    self.missing_owner,
                    self.missing_support_team,
                    self.missing_environment,
                    self.subscription_count,
                )
            )
            or self.critical_associations > self.incident_associations
        ):
            raise ValueError("Portfolio counts are inconsistent")
        if self.kind == "unmapped" and self.mapped_rows:
            raise ValueError("Unmapped rows cannot count as mapped")
        if any(
            self.mapped_rows + value > self.connection_rows
            for value in (
                self.missing_owner,
                self.missing_support_team,
                self.missing_environment,
            )
        ):
            raise ValueError("Mapped and missing rows overlap")
        return self


class PortfolioSource(BaseModel):
    """Reported source extent and collection provenance, separate from capture time."""

    model_config = ConfigDict(extra="forbid", strict=True)
    id: Literal["connections", "incidents"]
    started_at: str = Field(max_length=40)
    finished_at: str = Field(max_length=40)
    observed_at: list[str] = Field(max_length=20)
    source_tables: list[str] = Field(max_length=20)
    knowledge_version: str = Field(max_length=256)
    reported_freshness: list[Literal["fresh", "aging", "stale", "unknown"]]
    loaded: int = Field(ge=0, le=10_000)
    total: int = Field(ge=0)
    partial: bool
    warning_count: int = Field(ge=0)

    @model_validator(mode="after")
    def consistent(self):
        """A source cannot finish before it starts or hide a partial extent."""
        if _aware(self.finished_at) < _aware(self.started_at):
            raise ValueError("Portfolio collection time order is invalid")
        if self.total < self.loaded or self.partial != (self.loaded < self.total):
            raise ValueError("Portfolio source extent is inconsistent")
        if self.id == "incidents" and self.loaded > 100:
            raise ValueError("Portfolio incident extent exceeds 100 loaded rows")
        return self


class PortfolioObservation(BaseModel):
    """Immutable server acquisition; counts do not express availability or SLOs."""

    model_config = ConfigDict(extra="forbid", strict=True)
    observation_id: str = Field(pattern=r"^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$")
    captured_at: str = Field(max_length=40)
    services: list[PortfolioService] = Field(max_length=MAX_SERVICES)
    sources: list[PortfolioSource] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def consistent(self):
        """Validate the complete observation before either reading or retaining it."""
        receipt = _aware(self.captured_at)
        if {source.id for source in self.sources} != {"connections", "incidents"}:
            raise ValueError("Both portfolio sources are required")
        if any(_aware(source.finished_at) > receipt for source in self.sources):
            raise ValueError("Portfolio source finished after its capture receipt")
        keys = [row.service_key for row in self.services]
        if len(set(keys)) != len(keys):
            raise ValueError("Portfolio contains duplicate service identities")
        source = next(row for row in self.sources if row.id == "connections")
        if (
            source.partial
            or sum(row.connection_rows for row in self.services) != source.loaded
        ):
            raise ValueError("Portfolio registry acquisition is incomplete")
        incident_source = next(row for row in self.sources if row.id == "incidents")
        if (
            any(
                row.incident_associations > incident_source.loaded
                for row in self.services
            )
            or sum(row.incident_associations for row in self.services)
            < incident_source.loaded
        ):
            raise ValueError(
                "Portfolio incident associations contradict the loaded extent"
            )
        return self


class PortfolioHistory(BaseModel):
    """Exact-principal and exact-effective-scope retained state."""

    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[1] = 1
    actor: str
    scope: dict[str, list[str]]
    revision: int = Field(ge=0)
    observations: list[PortfolioObservation] = Field(max_length=MAX_OBSERVATIONS)

    @model_validator(mode="after")
    def consistent(self):
        """Keep receipt cardinality, chronology and observation identity coherent."""
        if len(self.observations) != min(self.revision, MAX_OBSERVATIONS):
            raise ValueError("Portfolio history revision is invalid")
        ids = [row.observation_id for row in self.observations]
        if len(set(ids)) != len(ids):
            raise ValueError("Portfolio history has duplicate observations")
        times = [_aware(row.captured_at) for row in self.observations]
        if times != sorted(times):
            raise ValueError("Portfolio capture receipts are not chronological")
        return self


def build_portfolio(
    connections: list[dict], incidents: list[dict]
) -> list[PortfolioService]:
    """Join actual authorized registry labels and at most 100 incident associations."""
    if len(connections) > 10_000 or len(incidents) > 100:
        raise ValueError("Portfolio acquisition exceeds the registry or incident bound")
    rows: dict[tuple[str, str], dict] = {}
    subscriptions: dict[tuple[str, str], set[str]] = {}

    def text(value) -> str:
        if value is None:
            return ""
        if not isinstance(value, str):
            raise TypeError("Portfolio metadata must be a string or absent")
        return value.strip()

    def row(name: str):
        kind = "service" if name else "unmapped"
        identity = (kind, name)
        if identity not in rows:
            if len(rows) >= MAX_SERVICES:
                raise ValueError("Portfolio capture exceeds 250 service labels")
            rows[identity] = {
                "service_key": _key(kind, name),
                "kind": kind,
                "name": name,
                "connection_rows": 0,
                "mapped_rows": 0,
                "missing_owner": 0,
                "missing_support_team": 0,
                "missing_environment": 0,
                "subscription_count": 0,
                "incident_associations": 0,
                "critical_associations": 0,
            }
            subscriptions[identity] = set()
        return identity, rows[identity]

    for connection in connections:
        name = text(connection.get("business_service"))
        identity, item = row(name)
        item["connection_rows"] += 1
        for field in ("owner", "support_team", "environment"):
            item[f"missing_{field}"] += not text(connection.get(field))
        item["mapped_rows"] += bool(name) and all(
            text(connection.get(field))
            for field in ("owner", "support_team", "environment")
        )
        subscription = text(connection.get("subscription_id"))
        if subscription:
            subscriptions[identity].add(subscription)
        item["subscription_count"] = len(subscriptions[identity])
    for entry in incidents:
        names = entry["blast_radius"].get("business_services") or []
        if not isinstance(names, list) or any(
            not isinstance(name, str) for name in names
        ):
            raise ValueError("Incident service associations must be string labels")
        # One incident may associate with multiple services, not multiple times per label.
        for name in sorted({text(value) for value in names if text(value)} or {""}):
            _, item = row(name)
            item["incident_associations"] += 1
            item["critical_associations"] += text(
                entry["incident"].get("severity")
            ).lower() in {
                "critical",
                "sev0",
                "sev1",
            }
    return [PortfolioService.model_validate(rows[key]) for key in sorted(rows)]


class ServicePortfolioStore:
    """Retain latest 20 explicit observations using existing local/OneLake CAS."""

    def __init__(self, documents: OneLakeDocumentStore):
        self.documents = documents

    @staticmethod
    def _name(actor: str, scope: dict[str, list[str]]) -> str:
        identity = json.dumps([actor, scope], sort_keys=True, separators=(",", ":"))
        return f"state/service-portfolio/{hashlib.sha256(identity.encode()).hexdigest()}.json"

    @staticmethod
    def _bounded(payload: dict):
        if (
            len((json.dumps(payload, indent=2, sort_keys=True) + "\n").encode())
            > MAX_HISTORY_BYTES
        ):
            raise ValueError("Portfolio history exceeds its 2 MiB document limit")

    def _read(self, actor: str, scope: dict[str, list[str]]):
        name = self._name(actor, scope)
        snapshot = self.documents.read_snapshot(name)
        try:
            if snapshot.exists:
                self._bounded(snapshot.payload)
                state = PortfolioHistory.model_validate(snapshot.payload)
            else:
                state = PortfolioHistory(
                    actor=actor, scope=scope, revision=0, observations=[]
                )
        except (ValidationError, ValueError) as exc:
            raise RuntimeError("Stored service portfolio is invalid") from exc
        if state.actor != actor or state.scope != scope:
            raise RuntimeError("Stored service portfolio identity is invalid")
        return name, snapshot, state

    def read(self, actor: str, scope: dict[str, list[str]]) -> dict:
        """Recover retained observations without calling active source providers."""
        return self._read(actor, scope)[2].model_dump()

    def append(
        self,
        actor: str,
        scope: dict[str, list[str]],
        expected_revision: int,
        *,
        services: list[PortfolioService],
        sources: list[PortfolioSource],
    ) -> dict:
        """Validate and atomically append; conflicts or invalid data never replace history."""
        name, snapshot, state = self._read(actor, scope)
        if state.revision != expected_revision:
            raise DocumentConflictError(
                "Service portfolio changed; reload before capturing"
            )
        observation = PortfolioObservation(
            observation_id=str(uuid4()),
            captured_at=datetime.now(UTC).isoformat(),
            services=services,
            sources=sources,
        )
        payload = PortfolioHistory(
            actor=actor,
            scope=scope,
            revision=state.revision + 1,
            observations=[*state.observations, observation][-MAX_OBSERVATIONS:],
        ).model_dump()
        self._bounded(payload)
        if snapshot.exists:
            self.documents.replace_if_match(name, payload, expected_etag=snapshot.etag)
        else:
            self.documents.create_only(name, payload)
        return payload
