"""Microsoft Agent Framework orchestration boundary for Operations Copilot.

MAF is the default orchestration contract: Operations Copilot coordinates
page-drawer turns and selects specialists from the user's question first, rather
than letting the page own the conversation. Set
``AIOPS_AGENT_ORCHESTRATION_MODE=deterministic`` to use the legacy
page-anchored rollback path.
"""

from __future__ import annotations

import importlib.util
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

ENV_AGENT_ORCHESTRATION_MODE = "AIOPS_AGENT_ORCHESTRATION_MODE"
MODE_DETERMINISTIC = "deterministic"
MODE_MAF = "maf"

_QUESTION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "network": (
        "network",
        "traffic",
        "firewall",
        "nsg",
        "route",
        "blast",
        "hub",
        "vnet",
        "subnet",
        "peering",
        "topology",
        "depend",
        "dependency",
        "dependencies",
    ),
    "vulnerability": ("cve", "vulnerab", "exploit", "exposure", "risk"),
    "patch": ("patch", "kb", "update", "sla"),
    "incident": ("incident", "outage", "alert", "root cause", "timeline"),
    "change": ("change", "changed", "deployment", "configuration"),
    "governance": (
        "owner",
        "owned",
        "approval",
        "approver",
        "governance",
        "policy",
        "scope",
        "exception",
    ),
    "remediation": ("remediat", "fix", "mitigat", "rollback", "plan"),
}


@dataclass(frozen=True)
class OrchestrationDecision:
    """Specialist selection made for one Operations Copilot turn."""

    selected_ids: tuple[str, ...]
    strategy: str
    runtime: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_ids": list(self.selected_ids),
            "strategy": self.strategy,
            "runtime": self.runtime,
            "reason": self.reason,
        }


def maf_mode_enabled() -> bool:
    """Return whether the MAF orchestration route is enabled."""

    return os.environ.get(ENV_AGENT_ORCHESTRATION_MODE, "").strip().casefold() != MODE_DETERMINISTIC


def _maf_runtime_label() -> str:
    return (
        "microsoft-agent-framework"
        if importlib.util.find_spec("agent_framework") is not None
        else "maf-compatible"
    )


def _append_unique(target: list[str], value: str, *, limit: int) -> None:
    if value and value not in target and len(target) < limit:
        target.append(value)


def select_specialists_for_turn(
    *,
    page_kind: str,
    question: str,
    page_specialists: Mapping[str, Sequence[str]],
    catalog: Sequence[Any],
    limit: int,
) -> OrchestrationDecision:
    """Select specialists for a page turn using the MAF pivot contract.

    The old page-anchored selector made a Network drawer behave like a Network
    agent, even when the user asked an ownership, change, or patch question.
    MAF mode inverts that: Operations Copilot owns intent selection, then
    delegates to the matching specialists. The current page is used only as a
    fallback when the question has no specialist signal.
    """

    lowered = question.casefold()
    known_ids = [getattr(agent, "id", "") for agent in catalog]
    selected: list[str] = []
    for agent_id in known_ids:
        if agent_id == "executive_summary":
            continue
        if any(marker in lowered for marker in _QUESTION_KEYWORDS.get(agent_id, ())):
            _append_unique(selected, agent_id, limit=limit)

    if selected:
        return OrchestrationDecision(
            selected_ids=tuple(selected),
            strategy="question_first",
            runtime=_maf_runtime_label(),
            reason="matched specialist intent from the operator question",
        )

    for agent_id in page_specialists.get(page_kind, ()):
        if agent_id != "executive_summary":
            _append_unique(selected, agent_id, limit=limit)

    return OrchestrationDecision(
        selected_ids=tuple(selected),
        strategy="page_fallback",
        runtime=_maf_runtime_label(),
        reason="no specialist intent matched; used the current page as context",
    )
