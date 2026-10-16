"""Declared component objectives and measured request telemetry, never service uptime."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore

if TYPE_CHECKING:
    from collections.abc import Iterable

    from api.scope import Scope
    from intelligence.inventory.models import ResourceObservation

MAX_OBJECTIVES = 20
MAX_POLICY_BYTES = 128 * 1024
MAX_SAFE_INTEGER = 9_007_199_254_740_991
COMPONENT_ID = re.compile(
    r"^/subscriptions/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    r"/resourcegroups/[^/?#%\\\s]+/providers/microsoft\.insights/components/[^/?#%\\\s]+$",
    re.IGNORECASE,
)
Count = Annotated[int, Field(ge=0, le=MAX_SAFE_INTEGER)]


def component_id(value: str) -> str:
    """Validate one exact App Insights ARM address before URL or query construction."""
    if (
        not isinstance(value, str) or len(value) > 2048 or not COMPONENT_ID.fullmatch(value)
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
        or any(part in {".", ".."} for part in value.split("/"))
    ):
        raise ValueError("Select an exact Application Insights component resource ID")
    return value.casefold()


def authorized_components(observations: Iterable[ResourceObservation], scope: Scope) -> list[dict]:
    """Project declared component mappings with complete fail-closed scope metadata.

    Resource observations preserve tags but the generic Inventory API does not
    project their business metadata. Native subscription identity must override
    any tag alias; missing constrained metadata never establishes membership.
    """
    from api.scope import scope_attributes

    rows = {}
    for observation in observations:
        if observation.resource_type.casefold() != "microsoft.insights/components":
            continue
        attributes = scope_attributes(observation.tags or {})
        attributes["subscription"] = observation.subscription_id.strip().casefold()
        if not scope.matches(attributes):
            continue
        try:
            identity = component_id(observation.resource_id)
        except ValueError as exc:
            raise RuntimeError("Component source resource identity is invalid") from exc
        if identity.split("/")[2] != attributes["subscription"]:
            raise RuntimeError("Component source subscription identity is inconsistent")
        if identity in rows:
            raise RuntimeError("Component source identity is ambiguous")
        rows[identity] = {
            "resource_id": identity, "resource_name": observation.resource_name,
            "business_service": attributes.get("business_service", ""),
            "subscription_id": attributes["subscription"],
            "subscription_connection": attributes.get("subscription_connection", ""),
            "observed_at": observation.observed_at,
        }
    return [rows[key] for key in sorted(rows)]


def _aware(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("Service reliability timestamps must be timezone-aware")
    return parsed


class ObjectiveRequest(BaseModel):
    """A declared target, not a caller-submitted metric or approval."""

    model_config = ConfigDict(strict=True, extra="forbid")
    expected_revision: int = Field(ge=0, lt=MAX_SAFE_INTEGER)
    resource_id: str = Field(min_length=1, max_length=2048)
    success_target_basis_points: int = Field(ge=1, le=10_000)
    window_hours: int

    @model_validator(mode="after")
    def valid_selection(self):
        """Reject unsupported windows and ambiguous resource addresses."""
        component_id(self.resource_id)
        if self.window_hours not in {1, 24, 168}:
            raise ValueError("Select a 1-hour, 24-hour or 7-day objective window")
        return self


class ObjectiveRemoval(BaseModel):
    """Explicit identified deletion, not a submitted replacement policy."""

    model_config = ConfigDict(strict=True, extra="forbid")
    expected_revision: int = Field(ge=0, lt=MAX_SAFE_INTEGER)
    resource_id: str = Field(min_length=1, max_length=2048)

    @model_validator(mode="after")
    def valid_identity(self):
        """Reject ambiguous addresses before a policy mutation."""
        component_id(self.resource_id)
        return self


class ServiceObjective(BaseModel):
    """An explicit administrator declaration bound to a server-resolved mapping."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    resource_id: str = Field(min_length=1, max_length=2048)
    business_service: str = Field(min_length=1, max_length=256)
    success_target_basis_points: int = Field(ge=1, le=10_000)
    window_hours: int

    @model_validator(mode="after")
    def valid_objective(self):
        """Retain canonical identities and supported measured windows only."""
        if self.resource_id != component_id(self.resource_id):
            raise ValueError("Component identity must be canonical")
        if self.business_service != self.business_service.strip():
            raise ValueError("Service mapping must be a confirmed nonempty label")
        if self.window_hours not in {1, 24, 168}:
            raise ValueError("Unsupported objective window")
        return self


class ObjectivePolicy(BaseModel):
    """Shared only within one exact effective scope; no inherited default objective."""

    model_config = ConfigDict(strict=True, extra="forbid")
    schema_version: int = Field(ge=1, le=1)
    scope: dict[str, list[str]]
    revision: int = Field(ge=0, le=MAX_SAFE_INTEGER)
    updated_at: str = Field(max_length=40)
    updated_by: str = Field(max_length=4096)
    objectives: list[ServiceObjective] = Field(max_length=MAX_OBJECTIVES)

    @model_validator(mode="after")
    def coherent_policy(self):
        """Reject duplicate identities, invalid saved state and actual byte overflow."""
        if len({row.resource_id for row in self.objectives}) != len(self.objectives):
            raise ValueError("Component objective identities must be unique")
        if len(self.objectives) > self.revision:
            raise ValueError("Objective count exceeds the saved revision")
        if self.revision == 0:
            if self.objectives or self.updated_at or self.updated_by:
                raise ValueError("Unsaved objective policy must be empty")
        elif not self.updated_at or not self.updated_by.strip():
            raise ValueError("Saved objective policy requires an editor and timestamp")
        else:
            _aware(self.updated_at)
        if len((json.dumps(self.model_dump(), indent=2, sort_keys=True) + "\n").encode()) > MAX_POLICY_BYTES:
            raise ValueError("Service objective policy exceeds 128 KiB")
        return self


class ServiceObjectiveStore:
    """Revision/ETag-guarded exact-scope declarations on the existing durable root."""

    def __init__(self, documents: OneLakeDocumentStore):
        self.documents = documents

    @staticmethod
    def _name(scope: dict) -> str:
        key = hashlib.sha256(json.dumps(scope, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return f"state/service-objectives/{key}.json"

    def _read(self, scope: dict):
        name = self._name(scope)
        try:
            snapshot = self.documents.read_snapshot(name)
            policy = ObjectivePolicy.model_validate(snapshot.payload) if snapshot.exists else ObjectivePolicy(
                schema_version=1, scope=scope, revision=0, updated_at="", updated_by="", objectives=[],
            )
        except (ValidationError, ValueError, TypeError, RecursionError) as exc:
            raise RuntimeError("Stored service objectives could not be confirmed") from exc
        if policy.scope != scope:
            raise RuntimeError("Stored service objective scope is invalid")
        return name, snapshot, policy

    def read(self, scope: dict) -> dict:
        """Recover declarations without telemetry acquisition or invented defaults."""
        return self._read(scope)[2].model_dump()

    def update(
        self, scope: dict, actor: str, expected_revision: int, *,
        objective: ServiceObjective | None = None, remove: str | None = None,
    ) -> dict:
        """Explicitly upsert or remove one objective against the reviewed revision."""
        if (objective is None) == (remove is None):
            raise ValueError("Select exactly one objective mutation")
        name, snapshot, policy = self._read(scope)
        if policy.revision != expected_revision or policy.revision >= MAX_SAFE_INTEGER:
            raise DocumentConflictError("Service objectives changed; reload before continuing")
        wanted = objective.resource_id if objective else component_id(remove)
        if remove is not None and not any(row.resource_id == wanted for row in policy.objectives):
            raise KeyError("Service objective was not found")
        rows = [row for row in policy.objectives if row.resource_id != wanted]
        if objective:
            rows.append(objective)
        if len(rows) > MAX_OBJECTIVES:
            raise ValueError("At most 20 component objectives; explicitly remove an objective")
        updated = ObjectivePolicy(
            schema_version=1, scope=scope, revision=policy.revision + 1,
            updated_at=datetime.now(UTC).isoformat(), updated_by=actor,
            objectives=sorted(rows, key=lambda row: row.resource_id),
        ).model_dump()
        if snapshot.exists:
            self.documents.replace_if_match(name, updated, expected_etag=snapshot.etag)
        else:
            self.documents.create_only(name, updated)
        return updated


class RequestAggregate(BaseModel):
    """One fixed AppRequests aggregate; weighted sampling remains an estimate."""

    model_config = ConfigDict(strict=True, extra="forbid")
    record_count: Count
    represented_count: Count
    failed_count: Count
    unknown_success_records: Count
    invalid_weight_records: Count
    sampled_records: Count
    invalid_duration_records: Count
    p95_duration_ms: float | None
    first_observed_at: str | None
    last_observed_at: str | None

    @model_validator(mode="after")
    def coherent_aggregate(self):
        """Validate exact count relationships, finite duration and actual observation order."""
        if any(value > self.record_count for value in (
            self.unknown_success_records, self.invalid_weight_records,
            self.sampled_records, self.invalid_duration_records,
        )):
            raise ValueError("Request quality counts exceed observed records")
        if (
            self.failed_count > self.represented_count
            or self.sampled_records + self.invalid_weight_records > self.record_count
            or self.represented_count < self.record_count - self.invalid_weight_records + self.sampled_records
        ):
            raise ValueError("Represented request counts are inconsistent")
        if self.p95_duration_ms is not None and (
            not math.isfinite(self.p95_duration_ms) or self.p95_duration_ms < 0
        ):
            raise ValueError("Request duration must be finite and nonnegative")
        if self.record_count:
            if not self.first_observed_at or not self.last_observed_at:
                raise ValueError("Observed request records need source timestamps")
            if _aware(self.first_observed_at) > _aware(self.last_observed_at):
                raise ValueError("Request observation order is invalid")
            if self.p95_duration_ms is None and not self.invalid_duration_records:
                raise ValueError("Valid request durations need a percentile")
        elif any((
            self.represented_count, self.failed_count, self.unknown_success_records,
            self.invalid_weight_records, self.sampled_records, self.invalid_duration_records,
            self.first_observed_at is not None, self.last_observed_at is not None,
            self.p95_duration_ms is not None,
        )):
            raise ValueError("Empty request telemetry cannot contain measurements")
        return self


def evaluate_requests(
    aggregate: RequestAggregate, objective: ServiceObjective, *,
    started_at: str, finished_at: str,
) -> dict:
    """Compare measured request telemetry with a declared target, not verified uptime."""
    start, end = _aware(started_at), _aware(finished_at)
    if (end - start).total_seconds() != objective.window_hours * 3600:
        raise ValueError("Query window does not match the declared objective")
    if aggregate.record_count and not (
        start <= _aware(aggregate.first_observed_at) <= _aware(aggregate.last_observed_at) < end
    ):
        raise ValueError("Request observations fall outside the queried window")
    known = aggregate.represented_count > 0 and not (
        aggregate.unknown_success_records or aggregate.invalid_weight_records
    )
    success = (
        100 * (aggregate.represented_count - aggregate.failed_count) / aggregate.represented_count
        if known else None
    )
    allowed = aggregate.represented_count * (10_000 - objective.success_target_basis_points) / 10_000 if known else None
    return {
        "resource_id": objective.resource_id, "business_service": objective.business_service,
        "objective": objective.model_dump(), "window_started_at": started_at, "window_finished_at": finished_at,
        "source": "Azure Monitor Logs AppRequests", "aggregate": aggregate.model_dump(),
        "request_success_percent": success,
        "p95_observed_record_duration_ms": aggregate.p95_duration_ms if not aggregate.invalid_duration_records else None,
        "allowed_failed_requests": allowed,
        "remaining_failed_request_budget": allowed - aggregate.failed_count if allowed is not None else None,
        "consumed_budget_percent": 100 * aggregate.failed_count / allowed if allowed else None,
        "sampling_estimated": aggregate.sampled_records > 0,
        "authority": "none",
        "interpretation": (
            "One mapped component's accessible request telemetry and an administrator-declared objective. "
            "Sample-weighted counts may be estimates; p95 is approximate and unweighted across observed records. "
            "Missing telemetry/access, instrumentation gaps and ingestion delay remain unknown. "
            "Not whole-service uptime, complete traffic coverage, contractual certification or execution approval."
        ),
    }
