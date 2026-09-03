"""Governed remediation action families and execution allowlist."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from operations.defender_configuration import (
    ENABLE_DEFENDER_SERVERS_P1,
    ENABLE_DEFENDER_STORAGE_V2,
)

ActionFamily = Literal["patch", "defender", "policy", "configuration", "unsupported"]


@dataclass(frozen=True)
class GovernedRemediationAction:
    """Public metadata for one governed remediation action type."""

    action_id: str
    family: ActionFamily
    executable: bool
    manual_review_reason: str = ""


_MANUAL = "No bounded provider handler is allowlisted for this action."

GOVERNED_REMEDIATION_ACTIONS: dict[str, GovernedRemediationAction] = {
    "controlled-patch-recovery": GovernedRemediationAction(
        "controlled-patch-recovery", "patch", True
    ),
    ENABLE_DEFENDER_SERVERS_P1: GovernedRemediationAction(
        ENABLE_DEFENDER_SERVERS_P1, "defender", True
    ),
    ENABLE_DEFENDER_STORAGE_V2: GovernedRemediationAction(
        ENABLE_DEFENDER_STORAGE_V2, "defender", True
    ),
    "critical-alert-containment": GovernedRemediationAction(
        "critical-alert-containment", "defender", False, _MANUAL
    ),
    "attack-path-segmentation-review": GovernedRemediationAction(
        "attack-path-segmentation-review", "defender", False, _MANUAL
    ),
    "secure-score-control-remediation": GovernedRemediationAction(
        "secure-score-control-remediation", "defender", False, _MANUAL
    ),
    "exploitable-finding-remediation": GovernedRemediationAction(
        "exploitable-finding-remediation", "defender", False, _MANUAL
    ),
    "defender-manual-review": GovernedRemediationAction(
        "defender-manual-review", "defender", False, _MANUAL
    ),
    "policy-assignment-remediation": GovernedRemediationAction(
        "policy-assignment-remediation", "policy", False, _MANUAL
    ),
    "policy-compliance-remediation": GovernedRemediationAction(
        "policy-compliance-remediation", "policy", False, _MANUAL
    ),
    "configuration-baseline-recovery": GovernedRemediationAction(
        "configuration-baseline-recovery", "configuration", False, _MANUAL
    ),
}

EXECUTABLE_ACTION_IDS = frozenset(
    action_id
    for action_id, action in GOVERNED_REMEDIATION_ACTIONS.items()
    if action.executable
)


def governed_action(action_id: object) -> GovernedRemediationAction:
    """Return allowlist metadata or a fail-closed unsupported projection."""
    identity = str(action_id or "").strip()
    action = GOVERNED_REMEDIATION_ACTIONS.get(identity)
    if action is not None:
        return action
    return GovernedRemediationAction(
        identity or "unknown",
        "unsupported",
        False,
        "This action type is not present in the governed remediation catalog.",
    )


__all__ = [
    "EXECUTABLE_ACTION_IDS",
    "GOVERNED_REMEDIATION_ACTIONS",
    "ActionFamily",
    "GovernedRemediationAction",
    "governed_action",
]
