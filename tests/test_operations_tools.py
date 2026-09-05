"""Gate G-6 coverage for bounded Operations Copilot tool results."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from api.scope import Scope
from operations.tools import STATUS_OK, call_tool


@dataclass(frozen=True)
class _Item:
    item_id: int

    def to_dict(self) -> dict[str, Any]:
        return {"item_id": self.item_id}


class _NetworkService:
    def __init__(self, *, gaps: int, findings: int) -> None:
        self.snapshot = SimpleNamespace(observed_at="2026-01-01T00:00:00Z")
        self._analysis = SimpleNamespace(
            gaps=tuple(_Item(index) for index in range(gaps)),
            rule_findings=tuple(_Item(index) for index in range(findings)),
        )
        self.scoped_with = None

    def scoped(self, scope):
        self.scoped_with = scope
        return self

    def analyze(self):
        return self._analysis


class _Context:
    provider_runtime = None
    hybrid_network_provider = None

    def __init__(self, service: _NetworkService) -> None:
        self.service = service

    def resolve_provider(self, name: str):
        return self.service if name == "network" else None


def _run(*, gaps: int, findings: int):
    service = _NetworkService(gaps=gaps, findings=findings)
    result = call_tool(
        "firewall_nsg_gaps",
        {},
        context=_Context(service),
        scope=Scope.from_mapping({"subscription": ["sub-a"]}),
    )
    return service, result


def test_g6_discloses_the_bound_and_true_totals_when_agent_lists_truncate() -> None:
    service, result = _run(gaps=30, findings=40)

    assert result.status == STATUS_OK
    assert len(result.data["gaps"]) == 25
    assert len(result.data["rule_findings"]) == 25
    assert "bound 25" in result.warning
    assert "30" in result.warning
    assert "40" in result.warning
    assert service.scoped_with.subscription_ids == ("sub-a",)


def test_g6_stays_silent_when_agent_lists_are_complete() -> None:
    _, result = _run(gaps=2, findings=3)

    assert result.status == STATUS_OK
    assert result.warning == ""
