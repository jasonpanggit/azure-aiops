"""Truthful history, deterministic review bounds and complete Twin scope."""

from types import SimpleNamespace

import pytest

from api.scope import Scope
from semantic.operational_twin import OperationalTwinComposer

ATTRIBUTES = {
    "subscription_id": "sub-a",
    "subscription_connection_id": "connection-a",
    "environment_name": "production",
    "businessService": "payments",
    "applicationName": "ledger",
    "project_owner": "alice",
    "supportTeam": "operations",
    "location": "eastus",
    "severity_tier": "high",
}
DIMENSIONS = {
    "subscription": "sub-a",
    "subscription_connection": "connection-a",
    "environment": "production",
    "business_service": "payments",
    "application": "ledger",
    "owner": "alice",
    "support_team": "operations",
    "region": "eastus",
    "criticality": "high",
}


@pytest.mark.parametrize("dimension", DIMENSIONS)
def test_semantic_scope_matches_all_nine_dimensions_and_aliases(dimension):
    composer = OperationalTwinComposer(scope={dimension: [DIMENSIONS[dimension].upper()]})
    assert composer._in_scope(ATTRIBUTES)
    assert not composer._in_scope({})
    assert not OperationalTwinComposer(scope={dimension: ["foreign"]})._in_scope(ATTRIBUTES)


def test_combined_scope_preserves_only_confirmed_entities_and_links():
    matching = {**ATTRIBUTES, "entity_type": "Resource", "resource_id": "visible"}
    foreign = {**matching, "resource_id": "foreign", "location": "westus"}
    missing = {key: value for key, value in matching.items() if key != "supportTeam"}
    composer = OperationalTwinComposer(
        scope=Scope.from_mapping({key: [value] for key, value in DIMENSIONS.items()}).to_dict(),
        semantic=SimpleNamespace(indexes=SimpleNamespace(
            entities={"visible": matching, "foreign": foreign, "missing": missing},
            relationships=[{"subject_id": "visible", "object_id": "foreign", "relationship_type": "depends_on"}],
        )),
    )
    snapshot = composer.snapshot()
    assert [entity["id"] for entity in snapshot["entities"]] == ["resource:visible"]
    assert snapshot["relationships"] == []


@pytest.mark.parametrize("dimension", DIMENSIONS)
@pytest.mark.parametrize("source", ["incidents", "remediation"])
def test_operational_contributions_require_every_scope_dimension(dimension, source):
    attributes = dict(ATTRIBUTES)
    incident = {"incident": {"incident_id": "visible", "title": "visible", **attributes}}
    plan = {"plan_id": "visible", "resource": attributes}
    if source == "incidents":
        provider = SimpleNamespace(report=lambda: {"incidents": [
            incident,
            {"incident": {"incident_id": "missing", "title": "missing"}},
            {**incident, dimension: "foreign"},
        ]})
    else:
        provider = SimpleNamespace(generate_plans=lambda: {"plans": [
            plan,
            {"plan_id": "missing"},
            {**plan, dimension: "foreign"},
        ]})
    composer = OperationalTwinComposer(
        scope={dimension: [DIMENSIONS[dimension]]}, **{source: provider},
    )
    assert [entity["id"] for entity in composer.snapshot()["entities"]] == [
        "incident:visible" if source == "incidents" else "remediation:visible"
    ]


def test_grant_narrowing_is_not_widened_by_missing_operational_metadata():
    narrowed = Scope.from_mapping({"subscription": ["sub-a"]}).intersect(
        Scope.from_mapping({"subscription": ["sub-b"]})
    )
    composer = OperationalTwinComposer(
        scope=narrowed.to_dict(),
        incidents=SimpleNamespace(report=lambda: {"incidents": [
            {"incident": {"incident_id": "hidden"}, "subscription": "sub-a"},
        ]}),
    )
    assert composer.snapshot()["entities"] == []


@pytest.mark.parametrize("vulnerabilities,incidents", [
    (None, None), ({}, {"incidents": []}), ({"critical_count": True}, {"incidents": []}),
    ({"critical_count": -1}, {"incidents": []}), ({"critical_count": 0}, None),
    ({"critical_count": "1"}, {"incidents": []}),
    ({"critical_count": 1}, {"incidents": [], "scope_projection_incomplete": True}),
])
def test_missing_or_invalid_inputs_are_not_zero_risk(vulnerabilities, incidents):
    assert OperationalTwinComposer._risk_trend(vulnerabilities, incidents) == []


def test_valid_zero_and_current_heuristic_are_explicit_not_a_measured_trend():
    point = OperationalTwinComposer._risk_trend({"critical_count": 0}, {"incidents": []})[0]
    assert point["risk_score"] == 0
    assert "Heuristic" in point["interpretation"]
    assert "not a measured trend" in point["interpretation"]


def _graph(count=7):
    entities = [
        {"id": f"resource:{index}", "kind": "resource", "name": f"node-{index}"}
        for index in range(count)
    ]
    links = [
        {"source": entities[index]["id"], "target": entities[index + 1]["id"]}
        for index in range(count - 1)
    ]
    return {"entities": entities, "relationships": links}


def test_projection_is_order_independent_bidirectional_and_hop_bounded():
    graph = _graph()
    forward, truncated = OperationalTwinComposer._impacted(graph, "0")
    reverse, reverse_truncated = OperationalTwinComposer._impacted({
        "entities": list(reversed(graph["entities"])),
        "relationships": list(reversed(graph["relationships"])),
    }, "resource:0")
    assert [row["id"] for row in forward] == ["resource:0", "resource:1", "resource:2", "resource:3"]
    assert forward == reverse
    assert truncated is reverse_truncated is True
    middle, _ = OperationalTwinComposer._impacted(graph, "3")
    assert len(middle) == 7


def test_projection_enforces_entity_bound_and_ignores_dangling_links():
    graph = _graph(510)
    graph["relationships"] = [
        {"source": "resource:0", "target": row["id"]} for row in graph["entities"][1:]
    ] + [{"source": "resource:0", "target": "resource:hidden"}]
    result, truncated = OperationalTwinComposer._impacted(graph, "0")
    assert len(result) == 500
    assert truncated is True
    assert not any(row["id"] == "resource:hidden" for row in result)


def test_projection_discloses_display_bound_without_a_measured_risk_delta():
    composer = OperationalTwinComposer()
    graph = _graph(30)
    graph.update(version="fixture", warnings=[])
    graph["relationships"] = [
        {"source": "resource:0", "target": row["id"]} for row in graph["entities"][1:]
    ]
    composer.snapshot = lambda: graph
    review = composer.scenario("patch_deployment", "0")
    assert review["risk_delta"] is None
    assert review["authority"] == "none"
    assert review["impacted_total"] == 30
    assert len(review["impacted_entities"]) == 25
    assert review["truncated"] is True
    assert review["traversal"] == {"direction": "undirected", "max_hops": 3, "max_entities": 500}
