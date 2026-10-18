"""Explicit authorized utilization receipts, not continuous resource availability."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore

MAX_OBSERVATIONS = 30
MAX_HISTORY_BYTES = 256 * 1024
MetricValue = Annotated[float | None, Field(ge=0, allow_inf_nan=False)]


def _aware(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("Health collection times must be timezone-aware")
    return parsed


class RetainedHealthMetrics(BaseModel):
    """Only finite projected measurements; absent values never become zero."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    cpu_percent: MetricValue
    network_in_bytes: MetricValue
    network_out_bytes: MetricValue
    disk_read_bytes: MetricValue
    disk_write_bytes: MetricValue
    os_disk_queue_depth: MetricValue
    memory_percent: MetricValue
    disk_free_percent: MetricValue


class RetainedHealthObservation(BaseModel):
    """One server-acquired provider collection and its independent retention receipt."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    observation_id: str = Field(pattern=r"^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$")
    captured_at: str = Field(max_length=40)
    started_at: str = Field(max_length=40)
    finished_at: str = Field(max_length=40)
    resource_observed_at: str = Field(max_length=40)
    snapshot_observed_at: str = Field(max_length=40)
    classification: Literal["healthy", "warning", "critical", "unknown"]
    cached: bool
    cache_ttl_seconds: int = Field(ge=0, le=9_007_199_254_740_991)
    warning_count: int = Field(ge=0, le=9_007_199_254_740_991)
    unavailable_metric_count: int = Field(ge=0, le=9_007_199_254_740_991)
    metrics: RetainedHealthMetrics

    @model_validator(mode="after")
    def coherent_times(self):
        """Cached source collection times may predate the new capture request."""
        start, finish, receipt = map(
            _aware, (self.started_at, self.finished_at, self.captured_at)
        )
        if not start <= finish <= receipt:
            raise ValueError("Health capture collection time order is invalid")
        if not (
            _aware(self.resource_observed_at)
            <= _aware(self.snapshot_observed_at)
            <= finish
        ):
            raise ValueError("Health provider collection time order is invalid")
        if (self.metrics.cpu_percent is None) != (self.classification == "unknown"):
            raise ValueError(
                "CPU classification does not match reported metric presence"
            )
        return self


class ResourceHealthHistory(BaseModel):
    """Exact principal/scope/resource-address state with bounded chronological receipts."""

    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: int = Field(ge=1, le=1)
    actor: str
    scope: dict[str, list[str]]
    resource_id: str = Field(min_length=1, max_length=4096)
    revision: int = Field(ge=0, le=9_007_199_254_740_991)
    observations: list[RetainedHealthObservation] = Field(max_length=MAX_OBSERVATIONS)

    @model_validator(mode="after")
    def coherent_history(self):
        """Reject corrupt identity, receipt cardinality, duplicates or chronology."""
        if len(self.observations) != min(self.revision, MAX_OBSERVATIONS):
            raise ValueError("Health history revision is invalid")
        ids = [row.observation_id for row in self.observations]
        if len(set(ids)) != len(ids):
            raise ValueError("Health history contains duplicate observations")
        times = [_aware(row.captured_at) for row in self.observations]
        if times != sorted(times):
            raise ValueError("Health capture receipts are not chronological")
        return self


class ResourceHealthHistoryStore:
    """Retain the latest 30 captures using the existing local/OneLake atomic CAS."""

    def __init__(self, documents: OneLakeDocumentStore):
        self.documents = documents

    @staticmethod
    def _name(actor: str, scope: dict[str, list[str]], resource_id: str) -> str:
        identity = json.dumps(
            [actor, scope, resource_id.casefold()],
            sort_keys=True,
            separators=(",", ":"),
        )
        return f"state/resource-health-history/{hashlib.sha256(identity.encode()).hexdigest()}.json"

    @staticmethod
    def _bytes(payload: dict) -> int:
        return len((json.dumps(payload, indent=2, sort_keys=True) + "\n").encode())

    def _read(self, actor: str, scope: dict[str, list[str]], resource_id: str):
        name = self._name(actor, scope, resource_id)
        snapshot = self.documents.read_snapshot(name)
        if snapshot.exists and self._bytes(snapshot.payload) > MAX_HISTORY_BYTES:
            raise RuntimeError("Stored health history exceeds its document limit")
        try:
            state = (
                ResourceHealthHistory.model_validate(snapshot.payload)
                if snapshot.exists
                else ResourceHealthHistory(
                    schema_version=1,
                    actor=actor,
                    scope=scope,
                    resource_id=resource_id.casefold(),
                    revision=0,
                    observations=[],
                )
            )
        except ValidationError as exc:
            raise RuntimeError("Stored health history schema is invalid") from exc
        if (state.actor, state.scope, state.resource_id) != (
            actor,
            scope,
            resource_id.casefold(),
        ):
            raise RuntimeError("Stored health history identity is invalid")
        return name, snapshot, state

    def read(self, actor: str, scope: dict[str, list[str]], resource_id: str) -> dict:
        """Recover only the exact history, without querying current Monitor data."""
        _, _, state = self._read(actor, scope, resource_id)
        return state.model_dump()

    def append(
        self,
        actor: str,
        scope: dict[str, list[str]],
        resource_id: str,
        expected_revision: int,
        observation: RetainedHealthObservation,
    ) -> dict:
        """Append the already validated server acquisition or conflict without a write."""
        name, snapshot, state = self._read(actor, scope, resource_id)
        if state.revision != expected_revision:
            raise DocumentConflictError(
                "Health history changed; reload before capturing"
            )
        updated = ResourceHealthHistory(
            schema_version=1,
            actor=actor,
            scope=scope,
            resource_id=resource_id.casefold(),
            revision=state.revision + 1,
            observations=[*state.observations, observation][-MAX_OBSERVATIONS:],
        ).model_dump()
        if self._bytes(updated) > MAX_HISTORY_BYTES:
            raise ValueError("Health history exceeds its 256 KiB document limit")
        if snapshot.exists:
            self.documents.replace_if_match(name, updated, expected_etag=snapshot.etag)
        else:
            self.documents.create_only(name, updated)
        return updated


def health_observation(payload: dict, resource_id: str, started: str, finished: str):
    """Project exactly one successful authorized provider result, never client metrics."""
    rows = payload.get("resources")
    if (
        not isinstance(rows, list)
        or len(rows) != 1
        or not isinstance(rows[0], dict)
        or not isinstance(rows[0].get("resource_id"), str)
        or rows[0]["resource_id"].casefold() != resource_id.casefold()
        or rows[0].get("error") != ""
    ):
        raise ValueError(
            "Health provider did not return one successful authorized resource"
        )
    for key in ("warnings", "unavailable_metrics"):
        if not isinstance(payload.get(key), list) or any(
            not isinstance(value, str) for value in payload[key]
        ):
            raise ValueError("Health provider metric declarations are invalid")
    row = rows[0]
    return RetainedHealthObservation(
        observation_id=str(uuid4()),
        captured_at=datetime.now(UTC).isoformat(),
        started_at=started,
        finished_at=finished,
        resource_observed_at=row["observed_at"],
        snapshot_observed_at=payload["observed_at"],
        classification=row["status"],
        cached=payload["cached"],
        cache_ttl_seconds=payload["cache_ttl_seconds"],
        warning_count=len(payload["warnings"]),
        unavailable_metric_count=len(payload["unavailable_metrics"]),
        metrics=RetainedHealthMetrics.model_validate(
            {key: row[key] for key in RetainedHealthMetrics.model_fields}
        ),
    )
