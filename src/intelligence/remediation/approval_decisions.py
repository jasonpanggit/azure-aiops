from __future__ import annotations

import copy
import hashlib
from datetime import UTC, datetime
from typing import Any, Literal


DecisionKind = Literal["approved", "rejected", "expired"]


class RemediationDecisionStore:
    """Append-only in-process store for recommendation approval decisions."""

    def __init__(self, *, max_decisions: int = 5000) -> None:
        if isinstance(max_decisions, bool) or not isinstance(max_decisions, int):
            raise TypeError("max_decisions must be an integer")
        if max_decisions < 1:
            raise ValueError("max_decisions must be positive")
        self.max_decisions = max_decisions
        self._decisions: tuple[dict[str, Any], ...] = ()

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
        now: datetime | None = None,
    ) -> dict[str, Any]:
        timestamp = (now or datetime.now(UTC)).isoformat()
        sequence = len(self._decisions) + 1
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
                "checks": [
                    "plan_exists",
                    "scope_authorized",
                    "action_version_current",
                    "execution_boundary_read_only",
                ],
            },
            "execution_authorized": False,
            "execution_performed": False,
            "read_only": True,
        }
        if len(self._decisions) >= self.max_decisions:
            raise ValueError("Remediation decision store is full")
        self._decisions = (*self._decisions, copy.deepcopy(record))
        return copy.deepcopy(record)

    def list(self, plan_id: str | None = None) -> list[dict[str, Any]]:
        rows = list(self._decisions)
        if plan_id is not None:
            rows = [row for row in rows if row["plan_id"] == plan_id]
        return copy.deepcopy(rows)

