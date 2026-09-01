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
    canonical = {field: snapshot.get(field) for field in _SNAPSHOT_FIELDS}
    serialized = json.dumps(
        canonical,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def build_execution_snapshot(
    plan: dict[str, Any], patching_service: Any, *, scope: Any = None
) -> dict[str, Any]:
    """Derive the exact patch action represented by the plan's current target."""
    resource = plan.get("resource") or {}
    target_id = str(resource.get("id") or plan.get("resource_key") or "").strip()
    target = patching_service.target(target_id, scope)
    if target is None:
        raise ExecutionSnapshotError(
            "No patch target matches this remediation plan's resource",
            reason="target_not_found",
            details={"plan_id": plan.get("plan_id"), "target_id": target_id},
        )
    patch_ids = sorted(str(item) for item in target.available_patch_ids if str(item))
    if not patch_ids:
        raise ExecutionSnapshotError(
            "No patches are currently available for this remediation target",
            reason="no_patches_available",
            details={"plan_id": plan.get("plan_id"), "target_id": target_id},
        )
    snapshot = {
        "target_id": target.target_id,
        "patch_ids": patch_ids,
        "target_kind": target.inventory_kind,
        "operation": target.operation,
        "action_version": str(plan.get("action_version") or ""),
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

    _SCHEMA_VERSION = "1.0.0"

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
        now: datetime | None = None,
    ) -> dict[str, Any]:
        timestamp = (now or datetime.now(UTC)).isoformat()
        checks = revalidation_checks or [
            "plan_exists",
            "scope_authorized",
            "action_version_current",
            "execution_boundary_read_only",
        ]
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
            "decisions": [dict(item) for item in decisions],
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


def _nonnegative_int(value: Any) -> int:
    number = int(value or 0)
    if number < 0:
        raise ValueError("Remediation decision revision must be non-negative")
    return number
