"""Restart-safe EvaluationSnapshot API projection contracts."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.rbac import Authorizer, Grant, Principal
from api.routers.ontology_discovery import (
    OntologyDiscoveryApi,
    evaluation_scope_key,
)
from api.runtime import build_context
from api.scope import Scope
from api.telemetry import ApiTelemetry
from onboarding.service import SubscriptionOnboardingService
from ontology_discovery.evaluation import (
    ArtifactReference,
    EvaluationLineage,
    EvaluationSnapshot,
    EvaluationThreshold,
    SliceMetric,
    SourceExpiry,
)
from ontology_discovery.evaluation_store import EvaluationSnapshotStore
from ontology_discovery.store import OntologyRunStore

NOW = datetime(2026, 9, 7, 1, 0, tzinfo=UTC)
SUBSCRIPTION = "11111111-1111-1111-1111-111111111111"
TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
CLIENT_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
TOKEN = "evaluation-reader-token"


def _snapshot(connection: dict[str, object], *, expires_at: datetime) -> EvaluationSnapshot:
    return EvaluationSnapshot.create(
        scope_key=evaluation_scope_key(connection),
        observed_at=NOW - timedelta(minutes=5),
        evaluated_at=NOW,
        expires_at=expires_at,
        lineage=EvaluationLineage(
            dataset_version="wave0-v1",
            dataset_hash="1" * 64,
            prompt_version="curator-v3",
            prompt_hash="2" * 64,
            schema_version="proposal-v2",
            schema_hash="3" * 64,
            model_version="gpt-5.4-mini-2026-03-17",
            model_hash="4" * 64,
            agent_version="ontology-curator-v5",
            agent_hash="5" * 64,
            policy_version="ontology-policy-v7",
            policy_hash="6" * 64,
        ),
        source_expiries=(
            SourceExpiry(
                source="azure-resource-graph",
                observed_at=NOW - timedelta(minutes=5),
                expires_at=expires_at,
            ),
        ),
        slice_metrics=(
            SliceMetric(
                metric="precision",
                slice_key="overall",
                numerator=99,
                denominator=100,
                value=0.99,
                critical=True,
            ),
        ),
        thresholds=(
            EvaluationThreshold(
                metric="precision",
                slice_key="overall",
                minimum=0.98,
                critical=True,
            ),
        ),
        release_eligible=True,
        artifact_references=(
            ArtifactReference(
                kind="report",
                reference="artifact:evaluation-report-v1",
                sha256="7" * 64,
            ),
        ),
    )


def _build(
    root: Path,
    *,
    now: datetime,
) -> tuple[TestClient, SubscriptionOnboardingService, EvaluationSnapshotStore]:
    run_store = OntologyRunStore(root / "ontology-runs.json")
    onboarding = SubscriptionOnboardingService(
        root / "aiops",
        ontology_run_store=run_store,
        clock=lambda: now,
    )
    if not onboarding.list():
        onboarding.add(
            connection_id="conn-a",
            name="Connection A",
            tenant_id=TENANT,
            subscription_id=SUBSCRIPTION,
            client_id=CLIENT_ID,
            secret_ref="kv://test/credential",
        )
    evaluation_store = EvaluationSnapshotStore(root / "evaluations")
    provider = OntologyDiscoveryApi(
        onboarding=onboarding,
        run_store=run_store,
        evaluation_store=evaluation_store,
        clock=lambda: now,
    )
    context = ApiContext(
        onboarding=onboarding,
        authenticator=StaticTokenAuthenticator(
            {
                TOKEN: Principal(
                    "reader@example.com",
                    grants=(
                        Grant(
                            "reader",
                            Scope.from_mapping({"subscription": [SUBSCRIPTION]}),
                        ),
                    ),
                )
            }
        ),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        ontology_discovery_provider=lambda: provider,
    )
    return (
        TestClient(create_app(context), raise_server_exceptions=False),
        onboarding,
        evaluation_store,
    )


def test_evaluation_projection_reconstructs_complete_fresh_snapshot_after_restart(
    tmp_path: Path,
) -> None:
    _client, onboarding, store = _build(tmp_path, now=NOW)
    connection = onboarding.detail("conn-a")
    snapshot = _snapshot(connection, expires_at=NOW + timedelta(hours=1))
    store.write(snapshot, expected_revision=0)

    restarted, _onboarding, _store = _build(
        tmp_path,
        now=NOW + timedelta(minutes=1),
    )
    response = restarted.get(
        "/api/v1/ontology-discovery/evaluation",
        params={"connection_id": "conn-a", "subscription": SUBSCRIPTION},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "fresh"
    assert data["reason"] == "evaluation_snapshot_fresh"
    assert data["snapshot"]["contract_version"] == "1.0.0"
    assert data["snapshot"]["snapshot_id"] == snapshot.snapshot_id
    assert data["snapshot"]["lineage"]["prompt_hash"] == "2" * 64
    assert data["snapshot"]["slice_metrics"][0]["metric"] == "precision"
    assert data["snapshot"]["thresholds"][0]["minimum"] == 0.98
    assert data["snapshot"]["artifact_references"] == [
        {
            "kind": "report",
            "reference": "artifact:evaluation-report-v1",
            "sha256": "7" * 64,
        }
    ]
    assert data["release_eligible"] is True
    assert data["release_disabled_reason"] == ""


def test_evaluation_projection_distinguishes_stale_missing_and_invalid(
    tmp_path: Path,
) -> None:
    client, onboarding, store = _build(tmp_path, now=NOW + timedelta(hours=2))
    snapshot = _snapshot(
        onboarding.detail("conn-a"),
        expires_at=NOW + timedelta(hours=1),
    )
    store.write(snapshot, expected_revision=0)

    stale = client.get(
        "/api/v1/ontology-discovery/evaluation",
        params={"connection_id": "conn-a", "subscription": SUBSCRIPTION},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert stale.status_code == 200
    assert stale.json()["data"]["status"] == "stale"
    assert stale.json()["data"]["snapshot"]["snapshot_id"] == snapshot.snapshot_id
    assert stale.json()["data"]["release_eligible"] is False
    assert stale.json()["data"]["release_disabled_reason"] == "evaluation_snapshot_expired"

    other_root = tmp_path / "missing"
    missing_client, _onboarding, _store = _build(
        other_root,
        now=NOW,
    )
    missing = missing_client.get(
        "/api/v1/ontology-discovery/evaluation",
        params={"connection_id": "conn-a", "subscription": SUBSCRIPTION},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert missing.json()["data"] == {
        "status": "missing",
        "reason": "evaluation_pointer_missing",
        "pointer_revision": None,
        "snapshot": None,
        "release_eligible": False,
        "release_disabled_reason": "evaluation_pointer_missing",
    }

    pointer = (
        tmp_path
        / "evaluations"
        / "ontology_evaluations"
        / "latest"
        / f"{snapshot.scope_hash}.json"
    )
    pointer.write_text("{not-json", encoding="utf-8")
    invalid = client.get(
        "/api/v1/ontology-discovery/evaluation",
        params={"connection_id": "conn-a", "subscription": SUBSCRIPTION},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert invalid.json()["data"]["status"] == "invalid"
    assert invalid.json()["data"]["release_eligible"] is False


def test_evaluation_history_is_bounded_and_scope_checked(tmp_path: Path) -> None:
    client, onboarding, store = _build(tmp_path, now=NOW)
    connection = onboarding.detail("conn-a")
    first = _snapshot(connection, expires_at=NOW + timedelta(hours=1))
    second = EvaluationSnapshot.create(
        **{
            **first.creation_values(),
            "evaluated_at": NOW + timedelta(minutes=1),
            "expires_at": NOW + timedelta(hours=2),
            "source_expiries": (
                SourceExpiry(
                    source="azure-resource-graph",
                    observed_at=NOW - timedelta(minutes=5),
                    expires_at=NOW + timedelta(hours=2),
                ),
            ),
        }
    )
    store.write(first, expected_revision=0)
    store.write(second, expected_revision=1)

    response = client.get(
        "/api/v1/ontology-discovery/evaluations",
        params={
            "connection_id": "conn-a",
            "subscription": SUBSCRIPTION,
            "limit": 1,
        },
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert response.status_code == 200
    assert [row["snapshot_id"] for row in response.json()["data"]] == [
        second.snapshot_id
    ]
    assert response.json()["pagination"]["total"] == 2

    denied = client.get(
        "/api/v1/ontology-discovery/evaluation",
        params={"connection_id": "conn-a", "subscription": "not-authorized"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert denied.status_code == 403


def test_default_runtime_reconstructs_evaluation_from_disk_on_each_provider_instance(
    monkeypatch,
    tmp_path: Path,
) -> None:
    home = tmp_path / "runtime"
    monkeypatch.setenv("AIOPS_HOME", str(home))
    monkeypatch.setenv("AIOPS_API_AUTH", "token")
    monkeypatch.setenv(
        "AIOPS_API_TOKENS",
        json.dumps(
            {
                TOKEN: {
                    "subject": "reader@example.com",
                    "grants": [{"role": "reader", "scope": {}}],
                }
            }
        ),
    )
    first_context = build_context()
    first_context.onboarding.add(
        connection_id="conn-a",
        name="Connection A",
        tenant_id=TENANT,
        subscription_id=SUBSCRIPTION,
        client_id=CLIENT_ID,
        secret_ref="kv://test/credential",
    )
    first_provider = first_context.ontology_discovery_provider()
    snapshot = _snapshot(
        first_context.onboarding.detail("conn-a"),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    first_provider.evaluation_store.write(snapshot, expected_revision=0)

    restarted_context = build_context()
    restarted_provider = restarted_context.ontology_discovery_provider()
    result = restarted_provider.evaluation(
        restarted_context.onboarding.detail("conn-a")
    )

    assert restarted_provider is not first_provider
    assert result["status"] == "fresh"
    assert result["snapshot"]["snapshot_id"] == snapshot.snapshot_id
