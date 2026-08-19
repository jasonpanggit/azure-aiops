from __future__ import annotations

from typing import Any


class ApprovalEngine:
    """Evaluates configurable approval policy and stage-gate requirements."""

    def __init__(self, policies: list[dict[str, Any]], *, max_policies: int = 100) -> None:
        if len(policies) > max_policies:
            raise ValueError("Approval policies exceed configured bound")
        identities: set[str] = set()
        self.policies = []
        for source in policies:
            policy = dict(source)
            policy_id = str(policy.get("policy_id") or "").strip()
            if not policy_id or policy_id in identities:
                raise ValueError("Approval policies require unique policy_id")
            self._validate_policy(policy)
            identities.add(policy_id)
            self.policies.append(policy)

    @staticmethod
    def _validate_policy(policy: dict[str, Any]) -> None:
        conditions = policy.get("conditions")
        roles = policy.get("roles")
        if not isinstance(conditions, dict):
            raise TypeError("Approval policy conditions must be a mapping")
        unknown = set(conditions) - {
            "environment_in",
            "criticality_in",
            "minimum_execution_risk",
        }
        if unknown:
            raise ValueError("Approval policy contains unsupported conditions")
        for field in ("environment_in", "criticality_in"):
            if field in conditions and (
                not isinstance(conditions[field], list)
                or not conditions[field]
                or any(not str(value).strip() for value in conditions[field])
            ):
                raise ValueError(f"Approval policy {field} must be a non-empty list")
        minimum = conditions.get("minimum_execution_risk")
        if minimum is not None and (
            isinstance(minimum, bool)
            or not isinstance(minimum, int)
            or not 0 <= minimum <= 100
        ):
            raise ValueError(
                "Approval policy minimum_execution_risk must be an integer from 0 to 100"
            )
        if (
            not isinstance(roles, list)
            or not roles
            or any(not str(role).strip() for role in roles)
        ):
            raise ValueError("Approval policy roles must be a non-empty list")

    def requirements(
        self,
        resource: dict[str, Any],
        action: dict[str, Any],
        risk: dict[str, Any],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for stage in action.get("deployment_stages") or []:
            rows.append(self._row("stage-gate", "Stage Gate Approver", str(stage)))
        for policy in self.policies:
            if not self._matches(policy.get("conditions") or {}, resource, risk):
                continue
            for role in policy.get("roles") or []:
                rows.append(
                    self._row(
                        str(policy["policy_id"]),
                        str(role),
                        str((action.get("deployment_stages") or ["Planning"])[-1]),
                    )
                )
        unique = {
            (row["policy_id"], row["role"], row["stage"]): row for row in rows
        }
        return [unique[key] for key in sorted(unique)]

    @staticmethod
    def _matches(conditions, resource, risk) -> bool:
        environment = str(resource.get("environment") or "")
        criticality = str(resource.get("business_criticality") or "")
        if conditions.get("environment_in") and environment not in conditions["environment_in"]:
            return False
        if conditions.get("criticality_in") and criticality not in conditions["criticality_in"]:
            return False
        minimum = conditions.get("minimum_execution_risk")
        return not (
            minimum is not None
            and risk["execution_risk"]["score"] < int(minimum)
        )

    @staticmethod
    def _row(policy_id: str, role: str, stage: str) -> dict[str, Any]:
        return {
            "policy_id": policy_id,
            "role": role[:256],
            "stage": stage[:128],
            "status": "Required - Not Approved",
            "approval_evidence_required": [
                "Plan evidence reviewed",
                "Risk assessment accepted",
                "Rollback readiness verified",
                "Simulation result reviewed",
            ],
            "approval_recorded": False,
        }
