from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from storage.onelake_documents import DocumentConflictError

DecisionKind = Literal["approved", "rejected", "expired"]
CONTROLLED_PATCH_RECOVERY = "controlled-patch-recovery"
_SNAPSHOT_FIELDS = (
    "target_id",
    "patch_ids",
    "target_kind",
    "operation",
    "action_version",
)


class ExecutionSnapshotError(RuntimeError):
    """A server-owned execution snapshot could not be derived safely."""

    def __init__(
        self, message: str, *, reason: str, details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.details = details or {}


def execution_snapshot_hash(snapshot: dict[str, Any]) -> str:
    """Hash the canonical, executable fields of an approval snapshot."""
    if snapshot.get("snapshot_kind") == "defender_configuration":
        from operations.defender_configuration import configuration_snapshot_hash

        return configuration_snapshot_hash(snapshot)
    canonical = {field: snapshot.get(field) for field in _SNAPSHOT_FIELDS}
    serialized = json.dumps(
        canonical,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def build_execution_snapshot(
    plan: dict[str, Any],
    patching_service: Any = None,
    *,
    configuration_adapter: Any = None,
    scope: Any = None,
    selected_patch_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Derive the exact server-owned action represented by the current plan.

    ``selected_patch_ids``, when given, narrows the snapshot to an operator
    -chosen subset of the target's observed available patches -- every id
    must already appear in ``target.available_patch_ids`` (an unknown id is
    rejected rather than silently widening or narrowing the blast radius).
    Omitting it keeps the prior all-available-patches behavior.
    """
    from operations.defender_configuration import (
        DEFENDER_CONFIGURATION_ACTION_IDS,
        DefenderConfigurationUnavailable,
        build_defender_configuration_snapshot,
    )

    action_id = str(plan.get("action_id") or plan.get("opportunity_type") or "")
    if action_id in DEFENDER_CONFIGURATION_ACTION_IDS:
        if configuration_adapter is None:
            raise ExecutionSnapshotError(
                "Defender configuration execution is not configured",
                reason="configuration_execution_unavailable",
                details={"plan_id": plan.get("plan_id"), "action_id": action_id},
            )
        try:
            snapshot = build_defender_configuration_snapshot(
                plan, configuration_adapter, scope=scope
            )
        except DefenderConfigurationUnavailable as exc:
            raise ExecutionSnapshotError(
                str(exc),
                reason=exc.reason,
                details={"plan_id": plan.get("plan_id"), "action_id": action_id},
            ) from exc
        snapshot["snapshot_hash"] = execution_snapshot_hash(snapshot)
        return snapshot
    if action_id != CONTROLLED_PATCH_RECOVERY:
        raise ExecutionSnapshotError(
            "This recommendation has no supported direct execution action",
            reason="action_not_executable",
            details={"plan_id": plan.get("plan_id"), "action_id": action_id},
        )
    if patching_service is None:
        raise ExecutionSnapshotError(
            "Patch execution is not configured",
            reason="patch_execution_unavailable",
            details={"plan_id": plan.get("plan_id")},
        )
    resource = plan.get("resource") or {}
    target_id = str(resource.get("id") or plan.get("resource_key") or "").strip()
    target = patching_service.target(target_id, scope)
    if target is None:
        raise ExecutionSnapshotError(
            "No patch target matches this remediation plan's resource",
            reason="target_not_found",
            details={"plan_id": plan.get("plan_id"), "target_id": target_id},
        )
    available_patch_ids = target.available_patch_ids
    patch_ids = sorted(str(item) for item in available_patch_ids if str(item))
    if not patch_ids:
        raise ExecutionSnapshotError(
            "No patches are currently available for this remediation target",
            reason="no_patches_available",
            details={"plan_id": plan.get("plan_id"), "target_id": target_id},
        )
    if selected_patch_ids is not None:
        requested = sorted({str(item).strip() for item in selected_patch_ids if str(item).strip()})
        unknown = [item for item in requested if item not in available_patch_ids]
        if unknown:
            raise ExecutionSnapshotError(
                "Selected patch ids are not in this target's observed available list",
                reason="patch_ids_not_available",
                details={
                    "plan_id": plan.get("plan_id"),
                    "target_id": target_id,
                    "unknown_patch_ids": unknown,
                },
            )
        if not requested:
            raise ExecutionSnapshotError(
                "At least one patch must be selected",
                reason="no_patches_selected",
                details={"plan_id": plan.get("plan_id"), "target_id": target_id},
            )
        patch_ids = requested
    available_patches = [
        patch.to_dict()
        for patch in sorted(target.available_patches, key=lambda item: item.patch_id)
    ]
    snapshot = {
        "target_id": target.target_id,
        "patch_ids": patch_ids,
        "target_kind": target.inventory_kind,
        "operation": target.operation,
        "action_version": str(plan.get("action_version") or ""),
        "available_patches": available_patches,
    }
    snapshot["snapshot_hash"] = execution_snapshot_hash(snapshot)
    return snapshot


class RevisionedDocumentStore(Protocol):
    def read(self, name: str) -> dict[str, Any]: ...

    def write(
        self, name: str, payload: dict[str, Any], *, expected_revision: int
    ) -> None: ...


class RemediationDecisionStore:
    """Append-only durable store for recommendation approval decisions."""

    # 1.2.0 (Phase 03.5 CR-05 fix): adds approval_role_id/admin_override
    # (written only by append(), only on approved decisions -- same WR-04
    # precedent as approver_roles). Legacy 1.1.0/1.0.0 documents read back
    # with both fields defaulted, never rewritten in place -- same
    # precedent as RemediationExecutionStore's 2.2.0 bump in Phase 03.4.
    _SCHEMA_VERSION = "1.2.0"

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        document_store: RevisionedDocumentStore | None = None,
        document_name: str = "state/remediation_decisions.json",
        max_decisions: int = 5000,
    ) -> None:
        if path is not None and document_store is not None:
            raise ValueError("Use either path or document_store, not both")
        if isinstance(max_decisions, bool) or not isinstance(max_decisions, int):
            raise TypeError("max_decisions must be an integer")
        if max_decisions < 1:
            raise ValueError("max_decisions must be positive")
        self.path = Path(path) if path is not None else None
        self.document_store = document_store
        self.document_name = document_name
        self.max_decisions = max_decisions
        self._memory: dict[str, Any] | None = None
        self._lock = threading.RLock()

    def append(
        self,
        *,
        plan: dict[str, Any],
        decision: DecisionKind,
        approver: str,
        reason: str,
        scope: dict[str, list[str]],
        action_version: str,
        expires_at: str = "",
        revalidation_checks: list[str] | None = None,
        execution_snapshot: dict[str, Any] | None = None,
        approver_roles: list[str] = (),
        approval_policy_version: str = "",
        approval_role_id: str = "",
        admin_override: bool = False,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        timestamp = (now or datetime.now(UTC)).isoformat()
        checks = revalidation_checks or [
            "plan_exists",
            "scope_authorized",
            "action_version_current",
            "execution_boundary_read_only",
        ]
        # WR-04: approver_roles is only ever meaningful on an approved
        # decision -- requirement_satisfaction() filters to
        # decision.get("decision") == "approved" before ever consulting it
        # (approval_gate.py). Storing it for rejected/expired decisions too
        # is dead data that could mislead a future direct-storage reader
        # (e.g. an audit report) into assuming it is significant there;
        # omit it for non-approved decisions instead. approval_role_id/
        # admin_override (CR-05 fix) follow the identical rule.
        normalized_roles = (
            sorted(
                {
                    str(role).strip().casefold()
                    for role in (approver_roles or ())
                    if str(role).strip()
                }
            )
            if decision == "approved"
            else []
        )
        normalized_role_id = (
            str(approval_role_id or "").strip().casefold()
            if decision == "approved"
            else ""
        )
        recorded_admin_override = bool(admin_override) if decision == "approved" else False
        with self._lock:
            for _ in range(3):
                state = self._read_state()
                decisions = state["decisions"]
                if len(decisions) >= self.max_decisions:
                    raise ValueError("Remediation decision store is full")
                sequence = len(decisions) + 1
                decision_id = "RMD-" + hashlib.sha256(
                    f"{plan['plan_id']}|{decision}|{approver}|{timestamp}|{sequence}".encode()
                ).hexdigest()[:16].upper()
                record = {
                    "decision_id": decision_id,
                    "plan_id": str(plan["plan_id"]),
                    "decision": decision,
                    "approver": approver,
                    "decided_at": timestamp,
                    "reason": reason,
                    "scope": copy.deepcopy(scope),
                    "action_version": action_version,
                    "expires_at": expires_at,
                    "revalidation": {
                        "status": "passed",
                        "checks": checks,
                    },
                    "execution_authorized": False,
                    "execution_performed": False,
                    "read_only": True,
                    "execution_snapshot": (
                        copy.deepcopy(execution_snapshot)
                        if decision == "approved" and execution_snapshot is not None
                        else None
                    ),
                    "approver_roles": normalized_roles,
                    "approval_policy_version": str(approval_policy_version or ""),
                    "approval_role_id": normalized_role_id,
                    "admin_override": recorded_admin_override,
                    "self_approved": False,
                    "self_approval_policy_id": "",
                }
                decisions.append(copy.deepcopy(record))
                state["revision"] += 1
                state["updated_at"] = timestamp
                try:
                    self._write_state(state, expected_revision=state["revision"] - 1)
                except DocumentConflictError:
                    continue
                return copy.deepcopy(record)
        raise DocumentConflictError("Remediation decision store changed during update")

    def record_self_approval(
        self, decision_id: str, *, policy_id: str, now: datetime | None = None
    ) -> dict[str, Any]:
        """Durably mark exactly one decision as a recorded self-approval exception.

        This is the sole write path for ``self_approved``/
        ``self_approval_policy_id`` (Phase 03.5, D-02) -- ``append()`` never
        accepts either field. CAS-guarded (same read/mutate/write/retry-3x
        shape as ``append()``); idempotent -- calling this twice with the
        same ``policy_id`` on an already-``self_approved=True`` record is a
        no-op that returns the existing record without bumping the
        revision a second time. Raises ``ValueError`` if ``decision_id`` is
        not found.
        """
        with self._lock:
            for _ in range(3):
                state = self._read_state()
                decisions = state["decisions"]
                match = None
                for candidate in decisions:
                    if candidate["decision_id"] == decision_id:
                        match = candidate
                        break
                if match is None:
                    raise ValueError(f"Remediation decision {decision_id!r} was not found")
                if match.get("self_approved") is True and match.get(
                    "self_approval_policy_id"
                ) == str(policy_id):
                    return copy.deepcopy(match)
                match["self_approved"] = True
                match["self_approval_policy_id"] = str(policy_id)
                state["revision"] += 1
                state["updated_at"] = (now or datetime.now(UTC)).isoformat()
                try:
                    self._write_state(state, expected_revision=state["revision"] - 1)
                except DocumentConflictError:
                    continue
                return copy.deepcopy(match)
        raise DocumentConflictError("Remediation decision store changed during update")

    def list(self, plan_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            rows = list(self._read_state()["decisions"])
        if plan_id is not None:
            rows = [row for row in rows if row["plan_id"] == plan_id]
        return copy.deepcopy(rows)

    def _read_state(self) -> dict[str, Any]:
        if self._memory is not None:
            payload = self._memory
        elif self.document_store is not None:
            payload = self.document_store.read(self.document_name)
            if not payload:
                return _initial_state()
        elif self.path is not None:
            if not self.path.exists():
                return _initial_state()
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError("Remediation decision state is not valid JSON") from exc
        else:
            return _initial_state()
        if not isinstance(payload, dict):
            raise TypeError("Remediation decision state must be an object")
        decisions = payload.get("decisions", [])
        if not isinstance(decisions, list) or any(
            not isinstance(item, dict) for item in decisions
        ):
            raise TypeError("Remediation decision decisions must be a list of objects")
        return {
            "revision": _nonnegative_int(payload.get("revision", 0)),
            "decisions": [_with_v1_2_defaults(item) for item in decisions],
            "updated_at": str(payload.get("updated_at") or ""),
        }

    def _write_state(self, state: dict[str, Any], *, expected_revision: int) -> None:
        payload = {
            "schema_version": self._SCHEMA_VERSION,
            "revision": state["revision"],
            "decisions": state["decisions"],
            "updated_at": state["updated_at"],
        }
        if self.document_store is not None:
            self.document_store.write(
                self.document_name, payload, expected_revision=expected_revision
            )
            return
        if self.path is None:
            self._memory = payload
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            dir=self.path.parent, prefix=f".{self.path.name}.", suffix=".tmp"
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


def _initial_state() -> dict[str, Any]:
    return {"revision": 0, "decisions": [], "updated_at": ""}


def _with_v1_2_defaults(item: dict[str, Any]) -> dict[str, Any]:
    """Backfill the six Phase 03.5 fields on a possibly-legacy decision.

    A pre-existing decision document (schema 1.0.0/1.1.0, missing the
    newer keys) reads back with safe defaults instead of raising -- never
    a KeyError for any caller of ``list()``. ``approval_role_id``/
    ``admin_override`` (CR-05 fix) default to ``""``/``False``, which
    ``approval_gate._decision_matches_role`` treats as "this is a legacy
    decision -- fall back to unambiguous ``approver_roles`` membership
    matching only", never as an implicit wildcard match.
    """
    record = dict(item)
    record.setdefault("approver_roles", [])
    record.setdefault("approval_policy_version", "")
    record.setdefault("approval_role_id", "")
    record.setdefault("admin_override", False)
    record.setdefault("self_approved", False)
    record.setdefault("self_approval_policy_id", "")
    return record


def _nonnegative_int(value: Any) -> int:
    number = int(value or 0)
    if number < 0:
        raise ValueError("Remediation decision revision must be non-negative")
    return number
