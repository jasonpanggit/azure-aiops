from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from hermes_arg_connector.normalize import Normalizer

FIXTURE = Path(__file__).parent / "fixtures" / "mock_arg_responses.json"


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text())


def test_normalizer_creates_required_entities_and_relationships() -> None:
    graph = Normalizer().normalize(_fixture(), datetime(2026, 8, 17, tzinfo=UTC))

    assert len(graph.entities["Subscription"]) == 1
    assert len(graph.entities["ResourceGroup"]) == 1
    assert len(graph.entities["VirtualMachine"]) == 1
    assert len(graph.entities["ArcServer"]) == 1
    assert len(graph.entities["Resource"]) == 1
    assert len(graph.entities["PatchAssessment"]) == 2
    assert len(graph.entities["PatchInstallation"]) == 1
    assert len(graph.entities["AdvisorRecommendation"]) == 1
    assert graph.entities["Subscription"][0]["id"] == "/subscriptions/sub-1"

    predicates = {edge["predicate"] for edge in graph.relationships}
    assert {"belongsTo", "assessedBy", "hasPatchInstallation", "impacts"} <= predicates
    installation = graph.entities["PatchInstallation"][0]
    assert installation["status"] == "Failed"
    assert installation["kbId"] == "KB-CRIT-001"
    assert installation["targetResourceId"].endswith("/virtualmachines/vm-prod-01")
    assert all(edge["source"] and edge["lastObservedTimestamp"] for edge in graph.relationships)
    entity_ids = {row["id"] for rows in graph.entities.values() for row in rows}
    assert all(edge["subjectId"] in entity_ids and edge["objectId"] in entity_ids for edge in graph.relationships)


def test_normalizer_drops_relationships_to_undiscovered_targets() -> None:
    payload = _fixture()
    payload["advisor_recommendations"][0]["properties"]["resourceMetadata"]["resourceId"] = (
        "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/missing"
    )

    graph = Normalizer().normalize(payload, datetime(2026, 8, 17, tzinfo=UTC))

    assert not any(edge["predicate"] == "impacts" for edge in graph.relationships)


def test_normalizer_is_stable_and_deduplicates_entities() -> None:
    payload = _fixture()
    payload["resources"].append(dict(payload["resources"][0]))
    normalizer = Normalizer()
    at = datetime(2026, 8, 17, tzinfo=UTC)

    first = normalizer.normalize(payload, at)
    second = normalizer.normalize(payload, at)

    assert first.entities == second.entities
    assert len(first.entities["VirtualMachine"]) == 1
    assert first.relationships == second.relationships
