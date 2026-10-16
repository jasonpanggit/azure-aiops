"""Immutable rollout terms and conservative, explicit submission admission."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .approval_decisions import execution_snapshot_hash

MAX_ROLLOUTS = 100


class RolloutError(ValueError):
    """A stored rollout or requested admission is not safe."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


class RolloutMember(BaseModel):
    """One exact server-resolved action assigned to an ordered target wave."""

    model_config = ConfigDict(extra="forbid", strict=True, revalidate_instances="always")
    plan_id: str = Field(min_length=1, max_length=200)
    target_id: str = Field(min_length=1, max_length=2048)
    action_version: str = Field(min_length=1, max_length=200)
    snapshot_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    patch_ids: list[Annotated[str, Field(min_length=1, max_length=256)]] = Field(default_factory=list, max_length=256)
    wave: int = Field(ge=1, le=5)
    scope_attributes: dict[str, str]

    @field_validator("scope_attributes")
    @classmethod
    def bounded_source_scope(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > 9 or any(len(key) > 64 or len(item) > 512 for key, item in value.items()):
            raise ValueError("Rollout source scope metadata exceeds supported bounds")
        return value


class RolloutTerms(BaseModel):
    """The complete terms incorporated into each member's approval hash."""

    model_config = ConfigDict(extra="forbid", strict=True)
    title: str = Field(min_length=1, max_length=120)
    window_start: str = Field(min_length=1, max_length=64)
    window_end: str = Field(min_length=1, max_length=64)
    require_reconciled_evidence: bool = True
    members: list[RolloutMember] = Field(min_length=1, max_length=20)

    @field_validator("window_start", "window_end")
    @classmethod
    def aware_timestamp(cls, value: str) -> str:
        parsed = datetime.fromisoformat(value)
        if parsed.utcoffset() is None:
            raise ValueError("Maintenance timestamps require an explicit timezone")
        return parsed.isoformat()

    @model_validator(mode="after")
    def validate_targets_and_window(self) -> RolloutTerms:
        start, end = datetime.fromisoformat(self.window_start), datetime.fromisoformat(self.window_end)
        if not 0 < (end - start).total_seconds() <= 86400:
            raise ValueError("A submission window must be positive and at most 24 hours")
        if len({member.plan_id for member in self.members}) != len(self.members):
            raise ValueError("A plan may appear only once in a rollout")
        if len({member.target_id.casefold() for member in self.members}) != len(self.members):
            raise ValueError("A target may appear only once in a rollout")
        waves = {member.wave for member in self.members}
        if waves != set(range(1, max(waves) + 1)):
            raise ValueError("Target waves must be contiguous and start at one")
        return self

    def digest(self) -> str:
        """Hash all approved terms, not mutable wave-open/pause state."""
        return hashlib.sha256(json.dumps(
            self.model_dump(), ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode()).hexdigest()


class RolloutRecord(BaseModel):
    """Durable immutable terms with revisioned operator admission controls."""

    model_config = ConfigDict(extra="forbid", strict=True)
    rollout_id: str = Field(pattern=r"^RMO-[a-f0-9]{32}$")
    terms: RolloutTerms
    terms_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    revision: int = Field(ge=0)
    opened_wave: int = Field(ge=0, le=5)
    paused: bool
    retired: bool = False
    created_by: str = Field(min_length=1)
    created_at: str
    updated_by: str = Field(min_length=1)
    updated_at: str

    @model_validator(mode="after")
    def validate_integrity(self) -> RolloutRecord:
        if self.terms_hash != self.terms.digest():
            raise ValueError("Stored rollout terms do not match their digest")
        if self.opened_wave > max(member.wave for member in self.terms.members):
            raise ValueError("Stored rollout references an absent wave")
        return self

    def binding(self, member: RolloutMember) -> dict[str, Any]:
        """Return the immutable terms identity for a member's approval."""
        return {"rollout_id": self.rollout_id, "terms_hash": self.terms_hash, "wave": member.wave}


def member_for_plan(
    records: list[dict[str, Any]], plan_id: str, *, include_retired: bool = True,
) -> tuple[RolloutRecord, RolloutMember] | None:
    """Resolve the sole immutable rollout binding, failing on corrupt duplicates."""
    found = None
    retired = None
    for value in records:
        record = RolloutRecord.model_validate(value)
        for member in record.terms.members:
            if member.plan_id == plan_id:
                if record.retired:
                    retired = record, member
                    continue
                if found is not None:
                    raise RolloutError("rollout_state_invalid", "A plan has multiple rollout bindings")
                found = record, member
    return found or (retired if include_retired else None)


def bind_snapshot(
    records: list[dict[str, Any]], plan_id: str, snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Bind a freshly resolved snapshot without substituting a retained action."""
    found = member_for_plan(records, plan_id)
    if found is None:
        return snapshot
    record, member = found
    if record.retired:
        return snapshot
    if execution_snapshot_hash(snapshot) != member.snapshot_hash:
        raise RolloutError("rollout_snapshot_changed", "Current action differs from the immutable rollout; review a newly generated plan")
    bound = {**snapshot, "rollout": record.binding(member)}
    bound["snapshot_hash"] = execution_snapshot_hash(bound)
    return bound


def assert_binding(
    records: list[dict[str, Any]], plan_id: str, snapshot: dict[str, Any],
) -> tuple[RolloutRecord, RolloutMember] | None:
    """Reject pre-rollout approvals, removed terms and altered member actions."""
    found = member_for_plan(records, plan_id)
    if found is None:
        if "rollout" in snapshot:
            raise RolloutError("rollout_binding_missing", "The approved rollout is not present in durable state")
        return None
    record, member = found
    if record.retired:
        raise RolloutError("rollout_retired", "Declare and approve replacement rollout terms before running this reserved plan")
    base = {key: value for key, value in snapshot.items() if key != "rollout"}
    if snapshot.get("rollout") != record.binding(member) or execution_snapshot_hash(base) != member.snapshot_hash:
        raise RolloutError("rollout_approval_stale", "Approval does not bind the exact rollout terms and target")
    return found


def _member_execution(
    record: RolloutRecord, member: RolloutMember, executions: list[dict[str, Any]],
) -> dict[str, Any] | None:
    matches = [
        row for row in executions
        if row.get("plan_id") == member.plan_id
        and (row.get("execution_snapshot") or {}).get("rollout") == record.binding(member)
    ]
    if len(matches) > 1:
        raise RolloutError("rollout_state_invalid", "A rollout target has multiple execution identities")
    return matches[0] if matches else None


def assert_admission(
    record: RolloutRecord,
    wave: int,
    executions: list[dict[str, Any]],
    now: datetime,
    *,
    recovery: bool = False,
) -> None:
    """Enforce submission-time gates; never cancel an already running provider."""
    if record.retired:
        raise RolloutError("rollout_retired", "These retained rollout terms are retired")
    if not datetime.fromisoformat(record.terms.window_start) <= now < datetime.fromisoformat(record.terms.window_end):
        raise RolloutError("rollout_window_closed", "The approved submission window is not open")
    if record.paused:
        raise RolloutError("rollout_paused", "The operator paused new rollout submissions")
    if record.opened_wave != wave:
        raise RolloutError("rollout_wave_not_open", "An operator must explicitly open this target wave")
    for member in record.terms.members:
        execution = _member_execution(record, member, executions)
        if member.wave < wave:
            if execution is None or execution.get("status") != "succeeded":
                raise RolloutError("rollout_prior_wave_unverified", "Every prior-wave target needs recorded provider success")
            if record.terms.require_reconciled_evidence and (
                execution.get("evidence_reconciliation") or {}
            ).get("status") != "reconciled_clean":
                raise RolloutError("rollout_prior_evidence_unverified", "Prior-wave targets need confirmed refreshed evidence")
        if not recovery and execution is not None and execution.get("status") != "succeeded":
            previous_failure = any(
                event.get("status") in {"failed", "cancelled"}
                for event in execution.get("history", [])
            )
            if execution.get("status") in {"failed", "cancelled"} or previous_failure:
                raise RolloutError("rollout_stopped", "A target failed or was cancelled; explicit bounded recovery must verify before new work")


def progress(record: RolloutRecord, executions: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    """Expose stored progress and admission reasons without provider acquisition."""
    rows = []
    for member in record.terms.members:
        execution = _member_execution(record, member, executions)
        reason = ""
        try:
            assert_admission(record, member.wave, executions, now)
        except RolloutError as exc:
            reason = exc.reason
        rows.append({
            **member.model_dump(),
            "execution_id": execution.get("execution_id", "") if execution else "",
            "status": execution.get("status", "not_started") if execution else "not_started",
            "admission_reason": reason,
        })
    return {**record.model_dump(), "targets": rows}
