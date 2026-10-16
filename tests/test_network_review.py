"""Exact scoped Network evidence handoff, never generated changes or execution grants."""

from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from network_scenario import network_rows

from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.rbac import Authorizer, Grant, Principal
from api.scope import Scope
from api.telemetry import ApiTelemetry
from intelligence.predeploy.service import PreDeploymentImpactService
from network.review import finding_review
from network.service import NetworkIntelligenceService
from onboarding.service import SubscriptionOnboardingService

TOKEN = "network-review-operator-fixture"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
ARTIFACT = {
    "source": "terraform_plan",
    "payload": {
        "resource_changes": [
            {
                "address": "azurerm_network_security_group.example",
                "type": "azurerm_network_security_group",
                "change": {
                    "actions": ["update"],
                    "before": {"name": "example"},
                    "after": {"name": "reviewed-example"},
                },
            }
        ],
    },
}


def _client(tmp_path, *, scoped=False):
    service = NetworkIntelligenceService.from_rows(network_rows())
    calls = []
    scope = Scope.from_mapping({"subscription": ["sub-prod"]}) if scoped else Scope()

    def provider():
        calls.append("network")
        return service

    context = ApiContext(
        onboarding=SubscriptionOnboardingService(tmp_path),
        authenticator=StaticTokenAuthenticator(
            {
                TOKEN: Principal(subject="operator", grants=(Grant("admin", scope),)),
                TOKEN + "-other": Principal(subject="other", grants=(Grant("admin"),)),
                TOKEN + "-reader": Principal(
                    subject="reader", grants=(Grant("reader"),)
                ),
            }
        ),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        network_provider=provider,
    )
    context.predeploy_service = PreDeploymentImpactService()
    return (
        TestClient(create_app(context), raise_server_exceptions=False),
        context,
        service,
        calls,
    )


def _reference(client, kind="gap", params=None):
    response = client.get(
        "/api/v1/network/gaps" if kind == "gap" else "/api/v1/network/rule-findings",
        headers=AUTH,
        params=params,
    )
    assert response.status_code == 200, response.text
    row = response.json()["data"]["gaps" if kind == "gap" else "findings"][0]
    return {
        "kind": kind,
        "finding_id": row["gap_id" if kind == "gap" else "finding_id"],
        "reviewed_digest": row["reviewed_digest"],
    }


@pytest.mark.parametrize("kind", ["gap", "rule"])
def test_server_reference_resolves_exact_safe_current_evidence(tmp_path, kind):
    client, _, _, calls = _client(tmp_path)
    reference = _reference(client, kind)
    response = client.get("/api/v1/network/review", headers=AUTH, params=reference)
    assert response.status_code == 200, response.text
    review = response.json()["data"]
    assert {key: review[key] for key in reference} == reference
    assert len(review["source_finding_digest"]) == len(review["policy_digest"]) == 64
    assert review["title"] and review["recommendation"]
    assert (
        "evidence" not in review
        and "rules" not in review
        and "properties" not in review
    )
    assert calls == ["network", "network"]


def test_reader_can_review_but_cannot_submit_assessment(tmp_path):
    client, context, _, _ = _client(tmp_path)
    reference = _reference(client)
    reader = {"Authorization": f"Bearer {TOKEN}-reader"}
    assert (
        client.get(
            "/api/v1/network/review", headers=reader, params=reference
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/changes/assess",
            headers=reader,
            json={**ARTIFACT, "network_review": reference},
        ).status_code
        == 403
    )
    assert context.predeploy_service.list_assessments() == []


@pytest.mark.parametrize("change", ["source_time", "policy", "finding", "scope"])
def test_changed_evidence_blocks_resolution_and_submission_without_assessment(
    tmp_path, change
):
    client, context, service, _ = _client(tmp_path)
    reference = _reference(client)
    params = reference
    if change == "source_time":
        service.snapshot = replace(service.snapshot, observed_at="2025-01-01T00:00:00Z")
    elif change == "policy":
        service.policy = replace(
            service.policy, description="Changed reviewed policy description"
        )
    elif change == "finding":
        reference = {**reference, "reviewed_digest": "0" * 64}
        params = reference
    else:
        params = {**reference, "subscription": "sub-prod"}
    resolved = client.get("/api/v1/network/review", headers=AUTH, params=params)
    assert resolved.status_code in {404, 409}, resolved.text
    query = {"subscription": "sub-prod"} if change == "scope" else None
    submitted = client.post(
        "/api/v1/changes/assess",
        headers=AUTH,
        params=query,
        json={**ARTIFACT, "network_review": reference},
    )
    assert submitted.status_code in {404, 409}, submitted.text
    assert context.predeploy_service.list_assessments() == []


def test_provider_failure_blocks_linked_review_not_success_shaped_fallback(tmp_path):
    client, context, _, _ = _client(tmp_path)
    reference = _reference(client)
    context.network_provider = lambda: None
    assert (
        client.get("/api/v1/network/review", headers=AUTH, params=reference).status_code
        == 503
    )
    assert (
        client.post(
            "/api/v1/changes/assess",
            headers=AUTH,
            json={**ARTIFACT, "network_review": reference},
        ).status_code
        == 503
    )
    assert context.predeploy_service.list_assessments() == []


def test_linked_assessment_remembers_exact_context_and_enforces_actor_scope_on_all_reads(
    tmp_path,
):
    client, context, _, _ = _client(tmp_path)
    query = {"subscription": "sub-prod"}
    reference = _reference(client, params=query)
    response = client.post(
        "/api/v1/changes/assess",
        headers=AUTH,
        params=query,
        json={**ARTIFACT, "network_review": reference},
    )
    assert response.status_code == 201, response.text
    record = response.json()["data"]
    identity = record["assessment_id"]
    assert record["scope"] == {"subscription": ["sub-prod"]}
    assert record["network_review_subject"] == "operator"
    assert record["network_review"]["reviewed_digest"] == reference["reviewed_digest"]
    assert record["network_review"]["scope"] == record["scope"]
    assert record["confirmed_cause"] is False
    assert (
        context.predeploy_service.get_assessment(identity)["network_review"]
        == record["network_review"]
    )
    listing = client.get("/api/v1/changes/assessments", headers=AUTH, params=query)
    assert [row["assessment_id"] for row in listing.json()["data"]] == [identity]
    for suffix in ("", "/explain"):
        own = client.get(
            f"/api/v1/changes/assessments/{identity}{suffix}",
            headers=AUTH,
            params=query,
        )
        assert own.status_code == 200, own.text
        assert own.json()["data"]["network_review"] == record["network_review"]
        assert (
            client.get(
                f"/api/v1/changes/assessments/{identity}{suffix}", headers=AUTH
            ).status_code
            == 404
        )
        assert (
            client.get(
                f"/api/v1/changes/assessments/{identity}{suffix}",
                headers={"Authorization": f"Bearer {TOKEN}-other"},
                params=query,
            ).status_code
            == 404
        )
    assert client.get("/api/v1/changes/assessments", headers=AUTH).json()["data"] == []
    assert (
        client.get(
            "/api/v1/changes/assessments",
            headers={"Authorization": f"Bearer {TOKEN}-other"},
            params=query,
        ).json()["data"]
        == []
    )


def test_listing_tolerates_assessment_evicted_before_visibility_lookup(tmp_path, monkeypatch):
    client, context, _, _ = _client(tmp_path)
    reference = _reference(client)
    response = client.post(
        "/api/v1/changes/assess",
        headers=AUTH,
        json={**ARTIFACT, "network_review": reference},
    )
    assert response.status_code == 201, response.text
    monkeypatch.setattr(context.predeploy_service, "get_assessment", lambda _: None)
    listing = client.get("/api/v1/changes/assessments", headers=AUTH)
    assert listing.status_code == 200, listing.text
    assert listing.json()["data"] == []


def test_selected_query_scope_is_preserved_for_unlinked_assessments_too(tmp_path):
    client, _, _, _ = _client(tmp_path)
    response = client.post(
        "/api/v1/changes/assess",
        headers=AUTH,
        params={
            "region": "eastus",
            "support_team": "sre",
            "criticality": "high",
        },
        json=ARTIFACT,
    )
    assert response.status_code == 201
    assert response.json()["data"]["scope"] == {
        "region": ["eastus"],
        "support_team": ["sre"],
        "criticality": ["high"],
    }
    assert "network_review" not in response.json()["data"]


def test_current_grant_plus_query_scope_issue_and_recheck_same_reference(tmp_path):
    client, _, _, _ = _client(tmp_path, scoped=True)
    query = [("subscription", "sub-prod"), ("subscription", "sub-uat")]
    reference = _reference(client, params=query)
    response = client.post(
        "/api/v1/changes/assess",
        headers=AUTH,
        params=query,
        json={**ARTIFACT, "network_review": reference},
    )
    assert response.status_code == 201, response.text
    assert response.json()["data"]["network_review"]["scope"] == {
        "subscription": ["sub-prod"]
    }
    forbidden = client.get(
        "/api/v1/network/review",
        headers=AUTH,
        params={**reference, "subscription": "sub-uat"},
    )
    assert forbidden.status_code == 403


@pytest.mark.parametrize(
    "mutation",
    [
        {"kind": "fix"},
        {"finding_id": ""},
        {"reviewed_digest": "bad"},
        {"evidence": {"approved": True}},
        {"scope": {}},
        {"execute": True},
    ],
)
def test_reference_contract_rejects_evidence_injection(tmp_path, mutation):
    client, context, _, _ = _client(tmp_path)
    reference = _reference(client)
    result = client.post(
        "/api/v1/changes/assess",
        headers=AUTH,
        json={
            **ARTIFACT,
            "network_review": {**reference, **mutation},
        },
    )
    assert result.status_code == 400, result.text
    assert context.predeploy_service.list_assessments() == []


def test_projection_bounds_and_hash_changes_include_full_source_evidence():
    service = NetworkIntelligenceService.from_rows(network_rows())
    gap = service.analyze().gaps[0]
    before = finding_review(gap, "gap", service, {})
    changed = finding_review(
        replace(gap, evidence={**gap.evidence, "new_source_field": "changed"}),
        "gap",
        service,
        {},
    )
    assert before["source_finding_digest"] != changed["source_finding_digest"]
    assert before["reviewed_digest"] != changed["reviewed_digest"]
    with pytest.raises(ValueError, match="64 KiB"):
        finding_review(replace(gap, detail="x" * 65537), "gap", service, {})
