"""Scope, authority, and CAS contracts for ontology discovery APIs."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.rbac import Authorizer, Grant, Principal
from api.routers.ontology_discovery import OntologyDiscoveryApi
from api.runtime import build_context
from api.scope import Scope
from api.telemetry import ApiTelemetry
from onboarding.service import SubscriptionOnboardingService
from ontology_discovery.store import OntologyRunStore

NOW = datetime(2026, 9, 7, 1, 0, tzinfo=UTC)
SUB_A = "11111111-1111-1111-1111-111111111111"
SUB_B = "22222222-2222-2222-2222-222222222222"
TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
CLIENT = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
TOKENS = {
    "reader": "ontology-reader-token",
    "operator": "ontology-operator-token",
    "approver": "ontology-approver-token",
    "admin": "ontology-admin-token",
}


class _GenerationReader:
    def __init__(self) -> None:
        self.selection = SimpleNamespace(
            active_generation="/safe/generations/generation-2",
            active_generation_uri="abfss://safe/generations/generation-2",
            prior_generation="/safe/generations/generation-1",
            pointer_etag="etag-2",
            source_generation="source-2",
            generation_id="generation-2",
        )

    def resolve(self) -> Any:
        return self.selection

    def read_metadata(self, name: str, *, selection: Any = None) -> dict[str, Any]:
        assert selection is self.selection
        return {
            "manifest.json": {
                "generation_id": "generation-2",
                "source_generation": "source-2",
                "fence": 7,
                "complete": True,
            },
            "validation.json": {
                "passed": True,
                "errors": [],
                "model_derived_relationships": 0,
            },
            "compatibility.json": {"all_consumers_compatible": True},
            "audit-intent.json": {"outcome": "promotion_authorized"},
            "audit-result.json": {"outcome": "promoted", "pointer_etag": "etag-2"},
        }.get(name, {})


@pytest.fixture
def api_fixture(tmp_path: Path) -> dict[str, Any]:
    run_store = OntologyRunStore(tmp_path / "ontology-runs.json")
    onboarding = SubscriptionOnboardingService(
        tmp_path / "aiops",
        ontology_run_store=run_store,
        clock=lambda: NOW,
    )
    for connection_id, subscription_id in (("conn-a", SUB_A), ("conn-b", SUB_B)):
        onboarding.add(
            connection_id=connection_id,
            name=connection_id,
            tenant_id=TENANT,
            subscription_id=subscription_id,
            client_id=CLIENT,
            secret_ref="kv://test/credential",
        )

    run_a, _ = run_store.get_or_create_run(
        connection_id="conn-a",
        source_generation_id="source-a",
        trigger="scheduled",
        requested_by="scheduler-principal",
        now=NOW,
        metadata={"trace_payload": "must-not-cross-api"},
    )
    run_b, _ = run_store.get_or_create_run(
        connection_id="conn-b",
        source_generation_id="source-b",
        trigger="scheduled",
        requested_by="other-principal",
        now=NOW,
    )
    proposal_a, _ = run_store.save_proposal(
        proposal={
            "subject_id": "vm-a",
            "subject_type": "VirtualMachine",
            "predicate": "member_of",
            "object_id": "app-a",
            "object_type": "Application",
            "rationale": "Corroborated relationship",
            "evidence_refs": ["opaque-evidence-1"],
            "raw_evidence": "must-not-cross-api",
        },
        scope=f"{TENANT}/{SUB_A}",
        source_generation_id="source-a",
        schema_version="proposal-v1",
        policy_version="policy-v1",
        now=NOW,
    )
    proposal_b, _ = run_store.save_proposal(
        proposal={
            "subject_id": "vm-b",
            "subject_type": "VirtualMachine",
            "predicate": "member_of",
            "object_id": "app-b",
            "object_type": "Application",
        },
        scope=f"{TENANT}/{SUB_B}",
        source_generation_id="source-b",
        schema_version="proposal-v1",
        policy_version="policy-v1",
        now=NOW,
    )
    rollback_calls: list[dict[str, Any]] = []

    def rollback_action(**kwargs: Any) -> dict[str, Any]:
        rollback_calls.append(kwargs)
        return {
            "active_generation": kwargs["generation_id"],
            "prior_generation": "generation-2",
            "pointer_etag": "etag-3",
            "status": "rolled_back",
        }

    provider = OntologyDiscoveryApi(
        onboarding=onboarding,
        run_store=run_store,
        generation_resolver_factory=lambda connection_id: (
            _GenerationReader() if connection_id == "conn-a" else None
        ),
        rollback_action=rollback_action,
        clock=lambda: NOW,
    )
    scoped_a = Scope.from_mapping({"subscription": [SUB_A]})
    context = ApiContext(
        onboarding=onboarding,
        authenticator=StaticTokenAuthenticator(
            {
                TOKENS["reader"]: Principal(
                    "reader@example.com", grants=(Grant("reader", scoped_a),)
                ),
                TOKENS["operator"]: Principal(
                    "operator@example.com", grants=(Grant("operator", scoped_a),)
                ),
                TOKENS["approver"]: Principal(
                    "steward@example.com",
                    grants=(Grant("approver", scoped_a),),
                    org_roles=("ontology_steward",),
                ),
                TOKENS["admin"]: Principal(
                    "admin@example.com",
                    grants=(Grant("admin"),),
                    org_roles=("ontology_steward",),
                ),
            }
        ),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        ontology_discovery_provider=lambda: provider,
    )
    return {
        "client": TestClient(create_app(context), raise_server_exceptions=False),
        "provider": provider,
        "run_store": run_store,
        "run_a": run_a,
        "run_b": run_b,
        "proposal_a": proposal_a,
        "proposal_b": proposal_b,
        "rollback_calls": rollback_calls,
    }


def _headers(role: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKENS[role]}"}


def _scope(connection_id: str = "conn-a", subscription: str = SUB_A) -> dict[str, str]:
    return {
        "connection_id": connection_id,
        "subscription": subscription,
    }


def test_status_and_history_are_bounded_scoped_and_server_projected(
    api_fixture: dict[str, Any],
) -> None:
    client = api_fixture["client"]
    response = client.get(
        "/api/v1/ontology-discovery/status",
        params=_scope(),
        headers=_headers("reader"),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["scope"] == {"subscription": [SUB_A]}
    assert body["data"]["scheduler"]["owner"] == "external_job"
    assert body["data"]["scheduler"]["api_owned"] is False
    assert body["data"]["current_run"]["run_id"] == api_fixture["run_a"]["run_id"]
    assert body["data"]["current_run"]["can_cancel"] is True
    assert body["data"]["current_run"]["disabled_reasons"]["cancel"] == ""
    assert "requested_by" not in body["data"]["current_run"]
    assert "metadata" not in body["data"]["current_run"]
    assert body["data"]["generation"]["active_generation"] == "generation-2"
    assert body["data"]["generation"]["can_rollback"] is True

    history = client.get(
        "/api/v1/ontology-discovery/runs",
        params={**_scope(), "limit": 1},
        headers=_headers("reader"),
    )
    assert history.status_code == 200
    history_body = history.json()
    assert [row["run_id"] for row in history_body["data"]] == [
        api_fixture["run_a"]["run_id"]
    ]
    assert history_body["pagination"]["total"] == 1


def test_out_of_scope_ids_are_not_found_without_disclosure(
    api_fixture: dict[str, Any],
) -> None:
    client = api_fixture["client"]
    run_response = client.get(
        f"/api/v1/ontology-discovery/runs/{api_fixture['run_b']['run_id']}",
        params=_scope(),
        headers=_headers("reader"),
    )
    proposal_response = client.get(
        f"/api/v1/ontology-discovery/proposals/{api_fixture['proposal_b']['proposal_id']}",
        params=_scope(),
        headers=_headers("reader"),
    )
    connection_response = client.get(
        "/api/v1/ontology-discovery/status",
        params=_scope("conn-b", SUB_A),
        headers=_headers("reader"),
    )

    assert run_response.status_code == 404
    assert proposal_response.status_code == 404
    assert connection_response.status_code == 404
    assert "conn-b" not in connection_response.text


def test_proposal_review_requires_approve_and_enforces_revision(
    api_fixture: dict[str, Any],
) -> None:
    client = api_fixture["client"]
    proposal_id = api_fixture["proposal_a"]["proposal_id"]
    payload = {
        "action": "accept",
        "expected_revision": 0,
        "reason": "Evidence reproduced.",
    }

    assert client.post(
        f"/api/v1/ontology-discovery/proposals/{proposal_id}/review",
        params=_scope(),
        headers=_headers("operator"),
        json=payload,
    ).status_code == 403

    accepted = client.post(
        f"/api/v1/ontology-discovery/proposals/{proposal_id}/review",
        params=_scope(),
        headers=_headers("approver"),
        json=payload,
    )
    assert accepted.status_code == 200
    decision = accepted.json()["data"]
    assert decision["status"] == "accepted"
    assert decision["revision"] == 1
    assert all("actor" not in event for event in decision["events"])

    stale = client.post(
        f"/api/v1/ontology-discovery/proposals/{proposal_id}/review",
        params=_scope(),
        headers=_headers("approver"),
        json={**payload, "action": "reject"},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["details"]["current_revision"] == "1"


def test_run_actions_require_operate_and_use_server_eligibility(
    api_fixture: dict[str, Any],
) -> None:
    client = api_fixture["client"]
    run_id = api_fixture["run_a"]["run_id"]

    denied = client.post(
        f"/api/v1/ontology-discovery/runs/{run_id}/cancel",
        params=_scope(),
        headers=_headers("approver"),
        json={"expected_revision": 0, "reason": "operator requested"},
    )
    assert denied.status_code == 403

    cancelled = client.post(
        f"/api/v1/ontology-discovery/runs/{run_id}/cancel",
        params=_scope(),
        headers=_headers("operator"),
        json={"expected_revision": 0, "reason": "operator requested"},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["data"]["status"] == "cancelled"
    assert cancelled.json()["data"]["can_retry"] is True

    stale = client.post(
        f"/api/v1/ontology-discovery/runs/{run_id}/retry",
        params=_scope(),
        headers=_headers("operator"),
        json={
            "expected_revision": 0,
            "reason": "retry from durable checkpoint",
            "idempotency_key": "retry-1",
        },
    )
    assert stale.status_code == 409

    retried = client.post(
        f"/api/v1/ontology-discovery/runs/{run_id}/retry",
        params=_scope(),
        headers=_headers("operator"),
        json={
            "expected_revision": 1,
            "reason": "retry from durable checkpoint",
            "idempotency_key": "retry-1",
        },
    )
    assert retried.status_code == 200
    assert retried.json()["data"]["status"] == "retrying"
    assert retried.json()["data"]["can_retry"] is False


def test_generation_rollback_requires_operate_and_delegates_etag(
    api_fixture: dict[str, Any],
) -> None:
    client = api_fixture["client"]
    payload = {
        "expected_etag": "etag-2",
        "reason": "Restore known-compatible generation",
        "idempotency_key": "rollback-generation-1",
    }
    denied = client.post(
        "/api/v1/ontology-discovery/generations/generation-1/rollback",
        params=_scope(),
        headers=_headers("approver"),
        json=payload,
    )
    assert denied.status_code == 403

    stale = client.post(
        "/api/v1/ontology-discovery/generations/generation-1/rollback",
        params=_scope(),
        headers=_headers("operator"),
        json={**payload, "expected_etag": "stale-etag"},
    )
    assert stale.status_code == 409

    response = client.post(
        "/api/v1/ontology-discovery/generations/generation-1/rollback",
        params=_scope(),
        headers=_headers("operator"),
        json=payload,
    )
    assert response.status_code == 200
    assert response.json()["data"]["active_generation"] == "generation-1"
    assert api_fixture["rollback_calls"] == [
        {
            "connection_id": "conn-a",
            "generation_id": "generation-1",
            "expected_etag": "etag-2",
            "actor": "operator@example.com",
            "reason": "Restore known-compatible generation",
            "idempotency_key": "rollback-generation-1",
        }
    ]


def test_mutation_payloads_reject_unknown_fields(api_fixture: dict[str, Any]) -> None:
    response = api_fixture["client"].post(
        f"/api/v1/ontology-discovery/runs/{api_fixture['run_a']['run_id']}/cancel",
        params=_scope(),
        headers=_headers("operator"),
        json={"expected_revision": 0, "reason": "stop", "can_cancel": True},
    )
    assert response.status_code == 400


def test_default_runtime_registers_read_action_facade_without_publisher_authority(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    home = tmp_path / "runtime"
    monkeypatch.setenv("AIOPS_HOME", str(home))
    monkeypatch.setenv("AIOPS_API_AUTH", "token")
    monkeypatch.setenv(
        "AIOPS_API_TOKENS",
        json.dumps(
            {
                TOKENS["admin"]: {
                    "subject": "admin@example.com",
                    "grants": [{"role": "admin", "scope": {}}],
                }
            }
        ),
    )
    context = build_context()

    assert context.ontology_discovery_provider is not None
    provider = context.ontology_discovery_provider()
    assert isinstance(provider, OntologyDiscoveryApi)
    assert provider._rollback_action is None
    assert not hasattr(provider, "publisher_identity")
    assert not hasattr(provider, "stage_generation")
    assert not hasattr(provider, "conditional_promote")

    app = create_app(context)
    assert not hasattr(app.state, "ontology_scheduler_thread")
    assert not hasattr(app.state, "ontology_publisher")


def test_default_runtime_degrades_missing_sections_without_hiding_durable_runs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    home = tmp_path / "runtime"
    monkeypatch.setenv("AIOPS_HOME", str(home))
    monkeypatch.setenv("AIOPS_API_AUTH", "token")
    monkeypatch.setenv(
        "AIOPS_API_TOKENS",
        json.dumps(
            {
                TOKENS["admin"]: {
                    "subject": "admin@example.com",
                    "grants": [{"role": "admin", "scope": {}}],
                }
            }
        ),
    )
    context = build_context()
    context.onboarding.add(
        connection_id="conn-a",
        name="Connection A",
        tenant_id=TENANT,
        subscription_id=SUB_A,
        client_id=CLIENT,
        secret_ref="kv://test/credential",
    )
    created = context.onboarding.enqueue_ontology_refresh(
        "conn-a",
        requested_by="admin@example.com",
    )
    client = TestClient(create_app(context), raise_server_exceptions=False)

    response = client.get(
        "/api/v1/ontology-discovery/status",
        params={"connection_id": "conn-a"},
        headers=_headers("admin"),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["current_run"]["run_id"] == created["run_id"]
    assert data["generation"]["status"] == "unavailable"
    assert data["generation"]["rollback_disabled_reason"]
    assert data["evaluation"]["status"] == "missing"
    assert data["evaluation"]["release_eligible"] is False
