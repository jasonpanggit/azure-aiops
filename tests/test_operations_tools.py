"""Gate G-6 coverage for bounded Operations Copilot tool results."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from api.scope import Scope
from operations.tools import STATUS_OK, call_tool


@dataclass(frozen=True)
class _Item:
    item_id: int

    def to_dict(self) -> dict[str, Any]:
        return {"item_id": self.item_id}


@dataclass(frozen=True)
class _AffectedFinding:
    item_id: int
    affected_resource_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "affected_resource_ids": list(self.affected_resource_ids),
        }


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


def test_cve_detail_prefers_live_durable_external_catalog() -> None:
    requested: list[str] = []

    class QueryService:
        def authorization_for(self, principal, scope):
            assert principal.subject == "operator@example.com"
            assert scope.values("subscription") == frozenset({"sub-a"})
            return "authorized"

        def catalog_item(self, authorization, *, generation_id, weakness_id):
            assert authorization == "authorized"
            assert generation_id is None
            requested.append(weakness_id)
            return {
                "contract_version": "1.0.0",
                "catalog_scope": "external_public_metadata",
                "environment_membership_included": False,
                "generation": "generation-1",
                "item": {
                    "cve_id": weakness_id,
                    "sources": {
                        "nvd": {
                            "status": "succeeded",
                            "payload": {"description": "Live NVD detail"},
                        },
                        "epss": {
                            "status": "succeeded",
                            "payload": {"epss_score": 0.42},
                        },
                        "kev": {
                            "status": "succeeded",
                            "payload": None,
                        },
                    },
                },
            }

    context = SimpleNamespace(
        provider_runtime=None,
        generation_resolver_provider=None,
        exposure_query_provider=lambda: QueryService(),
        resolve_provider=lambda _name: pytest.fail(
            "legacy vulnerability provider must not run"
        ),
    )

    result = call_tool(
        "cve_detail",
        {"cve_id": "CVE-2026-59873"},
        context=context,
        scope=Scope.from_mapping({"subscription": ["sub-a"]}),
        principal=SimpleNamespace(subject="operator@example.com"),
    )

    assert result.status == STATUS_OK
    assert requested == ["CVE-2026-59873"]
    assert result.data["item"]["sources"]["nvd"]["payload"]["description"] == (
        "Live NVD detail"
    )


def test_g6_stays_silent_when_agent_lists_are_complete() -> None:
    _, result = _run(gaps=2, findings=3)

    assert result.status == STATUS_OK
    assert result.warning == ""


def test_nested_finding_ids_are_bounded_to_the_disclosed_count() -> None:
    service = _NetworkService(gaps=0, findings=0)
    service._analysis = SimpleNamespace(
        gaps=(),
        rule_findings=(
            _AffectedFinding(
                1,
                tuple(f"resource-{index}" for index in range(300)),
            ),
            _AffectedFinding(
                2,
                tuple(f"other-resource-{index}" for index in range(40)),
            ),
        ),
    )

    result = call_tool(
        "firewall_nsg_gaps",
        {},
        context=_Context(service),
        scope=Scope.from_mapping({"subscription": ["sub-a"]}),
    )

    first_ids = result.data["rule_findings"][0]["affected_resource_ids"]
    second_ids = result.data["rule_findings"][1]["affected_resource_ids"]
    assert len(first_ids) == 25
    assert len(second_ids) == 25
    assert result.warning == (
        "Agent result bound 25: "
        f"rule_findings.affected_resource_ids showing {len(first_ids)} of 300."
    )
