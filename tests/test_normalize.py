from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from onboarding.graph_normalize import Normalizer

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
    assert len(graph.entities["DefenderAssessment"]) == 1
    assert len(graph.entities["DefenderVulnerabilityFinding"]) == 1
    assert graph.entities["DefenderAssessment"][0]["tenantId"] == "tenant-1"
    assert (
        graph.entities["DefenderVulnerabilityFinding"][0]["tenantId"]
        == "tenant-1"
    )
    assert graph.entities["Subscription"][0]["id"] == "/subscriptions/sub-1"

    predicates = {edge["predicate"] for edge in graph.relationships}
    assert {
        "belongsTo",
        "assessedBy",
        "hasPatchInstallation",
        "impacts",
        "hasVulnerability",
        "derivedFrom",
    } <= predicates
def test_defender_source_failures_are_isolated_and_never_reported_healthy() -> None:
    payload = _fixture()
    payload.update(
        {
            "defender_alerts": [],
            "defender_attack_paths": [
                {
                    "status": "failed",
                    "provider_status": "failed",
                    "error": "Defender CSPM is unavailable",
                }
            ],
            "defender_secure_scores": [],
            "defender_secure_score_controls": [],
        }
    )

    graph = Normalizer().normalize(payload, datetime(2026, 8, 17, tzinfo=UTC))
    status = {row["source_family"]: row for row in graph.source_status}

    assert status["defender_alerts"]["availability"] == "available"
    assert status["defender_attack_paths"]["availability"] == "unavailable"
    assert status["defender_attack_paths"]["quality"] == "degraded"
    assert status["defender_secure_scores"]["availability"] == "available"
    installation = graph.entities["PatchInstallation"][0]
    assert installation["status"] == "Failed"
    assert installation["kbId"] == "KB-CRIT-001"
    assert installation["targetResourceId"].endswith("/virtualmachines/vm-prod-01")
    assert all(edge["source"] and edge["lastObservedTimestamp"] for edge in graph.relationships)
    defender = graph.entities["DefenderVulnerabilityFinding"][0]
    assert defender["cveId"] == "CVE-2026-0001"
    assert defender["softwareName"] == "OpenSSL"
    assert defender["targetResourceId"].endswith("/virtualmachines/vm-prod-01")
    entity_ids = {row["id"] for rows in graph.entities.values() for row in rows}
    assert all(edge["subjectId"] in entity_ids and edge["objectId"] in entity_ids for edge in graph.relationships)


def test_normalizer_drops_relationships_to_undiscovered_targets() -> None:
    payload = _fixture()
    payload["advisor_recommendations"][0]["properties"]["resourceMetadata"]["resourceId"] = (
        "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/missing"
    )

    graph = Normalizer().normalize(payload, datetime(2026, 8, 17, tzinfo=UTC))

    assert not any(
        edge["predicate"] == "impacts"
        and edge["subjectId"].endswith("/recommendations/rec-eol-1")
        for edge in graph.relationships
    )


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


def test_normalizer_preserves_defender_threat_path_and_score_semantics() -> None:
    payload = _fixture()
    vm_id = (
        "/subscriptions/sub-1/resourceGroups/rg-prod/providers/"
        "Microsoft.Compute/virtualMachines/vm-prod-01"
    )
    payload["defender_alerts"] = [
        {
            "id": "/subscriptions/sub-1/providers/Microsoft.Security/locations/centralus/alerts/alert-1",
            "name": "alert-1",
            "type": "microsoft.security/locations/alerts",
            "tenantId": "tenant-1",
            "subscriptionId": "sub-1",
            "properties": {
                "alertDisplayName": "Suspicious process",
                "status": "Active",
                "severity": "High",
                "timeGeneratedUtc": "2026-08-17T01:00:00Z",
                "resourceIdentifiers": [{"azureResourceId": vm_id}],
            },
        }
    ]
    payload["defender_attack_paths"] = [
        {
            "id": "/subscriptions/sub-1/providers/Microsoft.Security/attackPaths/path-1",
            "name": "path-1",
            "type": "microsoft.security/attackpaths",
            "tenantId": "tenant-1",
            "subscriptionId": "sub-1",
            "properties": {
                "displayName": "Internet to production VM",
                "entryPointEntityInternalID": "internet",
                "targetEntityInternalID": "vm",
                "assessments": [{"id": "va-machines"}],
                "graphComponent": {
                    "entities": [
                        {
                            "entityInternalId": "internet",
                            "entityType": "IpAddress",
                            "displayName": "Internet",
                        },
                        {
                            "entityInternalId": "vm",
                            "entityType": "AzureResource",
                            "displayName": "vm-prod-01",
                            "resourceId": vm_id,
                        },
                    ],
                    "connections": [
                        {
                            "sourceEntityInternalId": "internet",
                            "targetEntityInternalId": "vm",
                            "type": "CanReach",
                        }
                    ],
                },
            },
        }
    ]
    score_id = "/subscriptions/sub-1/providers/Microsoft.Security/secureScores/ascScore"
    payload["defender_secure_scores"] = [
        {
            "id": score_id,
            "name": "ascScore",
            "type": "microsoft.security/securescores",
            "tenantId": "tenant-1",
            "subscriptionId": "sub-1",
            "properties": {"score": {"current": 40, "max": 80, "percentage": 0.5}},
        }
    ]
    payload["defender_secure_score_controls"] = [
        {
            "id": f"{score_id}/secureScoreControls/control-1",
            "name": "control-1",
            "type": "microsoft.security/securescores/securescorecontrols",
            "tenantId": "tenant-1",
            "subscriptionId": "sub-1",
            "properties": {
                "displayName": "Resolve vulnerabilities",
                "score": {"current": 2, "max": 8, "percentage": 0.25},
                "unhealthyResourceCount": 1,
                "assessmentDefinitions": [
                    "/subscriptions/sub-1/providers/Microsoft.Security/assessments/va-machines"
                ],
            },
        }
    ]

    graph = Normalizer().normalize(payload, datetime(2026, 8, 17, tzinfo=UTC))

    assert len(graph.entities["SecurityAlert"]) == 1
    assert len(graph.entities["AttackPath"]) == 1
    assert len(graph.entities["AttackPathNode"]) == 2
    assert graph.entities["AttackPathNode"][0]["resolved"] is False
    assert len(graph.entities["AttackPathConnection"]) == 1
    assert len(graph.entities["SecureScoreSnapshot"]) == 1
    assert graph.entities["SecureScoreSnapshot"][0]["percentage"] == 0.5
    predicates = {edge["predicate"] for edge in graph.relationships}
    assert {
        "affects",
        "startsAt",
        "targets",
        "traverses",
        "connectsFrom",
        "connectsTo",
        "resolvesTo",
        "hasSecureScore",
        "composedOf",
        "improvedBy",
        "supportedBy",
    } <= predicates
    defender_status = {
        row["source_family"]: row for row in graph.source_status
    }
    assert defender_status["defender_alerts"]["availability"] == "available"
    assert defender_status["defender_attack_paths"]["availability"] == "available"
