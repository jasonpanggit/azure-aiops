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
                "cveIds": ["CVE-2026-0001"],
                "description": "Informational context for CVE-2026-9999",
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
    assert graph.entities["AttackPath"][0]["cveIds"] == ["CVE-2026-0001"]
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


def test_defender_assessment_html_is_stripped_to_plain_text() -> None:
    """Verify that HTML markup in Defender assessment fields is stripped, not escaped.

    JSX renders these fields as plain text (auto-escaping on display), so the
    backend must return clean readable text rather than raw or escaped HTML.
    """
    from onboarding.defender_normalize import normalize_assessment
     
    row = {
        "id": "/subscriptions/sub-1/providers/Microsoft.Security/assessments/assessment-1",
        "name": "assessment-1",
        "type": "Microsoft.Security/assessments",
        "properties": {
            "displayName": "Test <b>Assessment</b>",
            "description": "Description with <br> tag",
            "remediation": "Fix with <a href='https://example.com'>link</a>",
            "status": {"code": "Healthy"},
            "resourceDetails": {
                "Source": "Azure",
                "Id": "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm-1",
            },
        },
    }
     
    result = normalize_assessment(row, "2026-08-17T00:00:00Z")
    assert result is not None
    assert result["recommendation"] == "Test Assessment"
    assert result["description"] == "Description with\ntag"
    assert result["remediation"] == "Fix with link"


def test_defender_vulnerability_finding_html_is_stripped_to_plain_text() -> None:
    """Verify that HTML markup in Defender vulnerability finding fields is stripped."""
    from onboarding.defender_normalize import normalize_vulnerability_subassessments
     
    row = {
        "id": "/subscriptions/sub-1/providers/Microsoft.Security/assessments/assessment-1/subAssessments/sub-1",
        "name": "sub-1",
        "type": "Microsoft.Security/assessments/subAssessments",
        "properties": {
            "status": {"code": "Unhealthy"},
            "category": ["Vulnerabilities"],
            "description": "CVE with <code>tag</code>",
            "remediation": "Remediate with <span>HTML</span>",
            "impact": "High",
            "resourceDetails": {
                "Source": "Azure",
                "Id": "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm-1",
            },
            "additionalData": {
                "cveId": "CVE-2026-0001",
                "softwareName": "OpenSSL",
            },
        },
    }
     
    results = normalize_vulnerability_subassessments(row, "2026-08-17T00:00:00Z")
     
    assert len(results) == 1
    # recommendation is mapped from remediation/remediationDescription
    assert results[0]["recommendation"] == "Remediate with HTML"
    # description is mapped from properties.description
    assert results[0]["description"] == "CVE with tag"


def test_security_alert_html_is_stripped_to_plain_text() -> None:
    """Verify that HTML markup in Defender security alert fields is stripped."""
    from onboarding.defender_normalize import normalize_security_alert
     
    row = {
        "id": "/subscriptions/sub-1/providers/Microsoft.Security/securityAlerts/alert-1",
        "name": "alert-1",
        "type": "Microsoft.Security/securityAlerts",
        "properties": {
            "alertDisplayName": "Alert with <b>HTML</b>",
            "description": "Alert description with <br> tags",
            "status": "Active",
            "severity": "High",
            "alertType": "ThreatIntelligence",
            "intent": "Exploitation",
            "productName": "Azure Security Center",
            "vendorName": "Microsoft",
            "remediationSteps": [
                "Step 1 with <a href='#'>link</a>",
                "Step 2 with <code>tag</code>",
            ],
            "resourceIdentifiers": [
                {
                    "type": "AzureResource",
                    "workspaceId": "/subscriptions/sub-1",
                    "workspaceName": "sub-1",
                    "resourceId": "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm-1",
                }
            ],
        },
    }
     
    result = normalize_security_alert(row, "2026-08-17T00:00:00Z")
    assert result is not None
    assert result["title"] == "Alert with HTML"
    assert result["description"] == "Alert description with\ntags"
    assert result["remediationSteps"][0] == "Step 1 with link"
    assert result["remediationSteps"][1] == "Step 2 with tag"


def test_html_entities_are_unescaped_to_readable_text() -> None:
    """Verify that HTML entities from Azure's authored content render as plain text.

    Azure Defender content is authored as HTML, so it uses entities like
    ``&#x27;`` (apostrophe) and ``&amp;`` (ampersand) — these must be decoded
    to their literal characters, not left as raw entity codes.
    """
    from onboarding.defender_normalize import normalize_assessment

    row = {
        "id": "/subscriptions/sub-1/providers/Microsoft.Security/assessments/assessment-1",
        "name": "assessment-1",
        "type": "Microsoft.Security/assessments",
        "properties": {
            "displayName": "It&#x27;s important &amp; urgent",
            "status": {"code": "Healthy"},
            "resourceDetails": {
                "Source": "Azure",
                "Id": "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm-1",
            },
        },
    }

    result = normalize_assessment(row, "2026-08-17T00:00:00Z")
    assert result is not None
    assert result["recommendation"] == "It's important & urgent"
