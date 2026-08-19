from __future__ import annotations

from typing import Any


class RollbackPlanner:
    """Builds mandatory reversible rollback contracts from governed action metadata."""

    def build(self, action: dict[str, Any]) -> dict[str, Any]:
        required = (
            "preconditions",
            "rollback_actions",
            "success_criteria",
            "failure_criteria",
        )
        for field in required:
            if not action.get(field):
                raise ValueError(f"Remediation action requires {field}")
        return {
            "preconditions": self._bounded(action["preconditions"]),
            "rollback_actions": self._bounded(action["rollback_actions"]),
            "validation_steps": self._bounded(
                [
                    "Validate application health and service-level indicators",
                    "Validate upstream and downstream dependency transactions",
                    "Confirm the governed posture returned to the expected state",
                ]
            ),
            "success_criteria": self._bounded(action["success_criteria"]),
            "failure_criteria": self._bounded(action["failure_criteria"]),
            "reversible": True,
            "automatic_rollback": False,
            "execution_status": "Not Executed",
        }

    @staticmethod
    def _bounded(values: list[Any]) -> list[str]:
        return [str(value).strip()[:1024] for value in values[:50] if str(value).strip()]
