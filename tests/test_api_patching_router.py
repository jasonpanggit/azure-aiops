"""HTTP-level tests for patch inventory and operator-triggered patch runs.

Covers the safety properties that matter: only patches the target actually
offers may be installed, AKS upgrades take exactly one version, an unconfigured
execution adapter refuses loudly (and audibly, as a persisted failed run), and
scope narrowing hides out-of-scope targets rather than 403-ing them.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.rbac import Authorizer, Grant, Principal
from api.scope import Scope
from api.telemetry import ApiTelemetry
from intelligence.vulnerability.service import VulnerabilityIntelligenceService
from onboarding.service import SubscriptionOnboardingService
from operations.patching import InMemoryPatchRunStore, PatchingService
from operations.patching.adapters import RecordingPatchExecutionAdapter

ADMIN_TOKEN = "admin-token-0123456789abcdef"
READER_TOKEN = "reader-token-0123456789abcde"

VM_ID = "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1"
AKS_ID = "/subscriptions/sub-2/resourceGroups/rg/providers/Microsoft.ContainerService/managedClusters/aks1"


class FakeSecretWriter:
    def store(self, *, connection_id: str, secret_value: str) -> str:
        return f"keyvault://kv-test/secrets/aiops-conn-{connection_id}/v1"


def _vulnerability_service() -> VulnerabilityIntelligenceService:
    return VulnerabilityIntelligenceService.from_rows(
        cves=[
            {"id": "CVE-2026-0001", "title": "Snapshot CVE", "severity": "Critical"},
            {"id": "CVE-2026-0002", "title": "Cluster CVE", "severity": "High"},
        ],
        security_updates=[
            {"kb": "KB600001", "cve_ids": ["CVE-2026-0001"]},
            {"kb": "KB600002", "cve_ids": ["CVE-2026-0002"]},
        ],
        findings=[
            {
                "id": "finding-1",
                "cve_id": "CVE-2026-0001",
                "server_id": VM_ID,
                "missing_kb": "KB600001",
                "business_service": "Payments",
                "subscription_id": "sub-1",
            },
            {
                "id": "finding-2",
                "cve_id": "CVE-2026-0002",
                "server_id": AKS_ID,
                "missing_kb": "KB600002",
                "business_service": "Platform",
                "subscription_id": "sub-2",
            },
        ],
        freshness="2026-01-01T00:00:00+00:00",
    )


def _principals() -> dict[str, Principal]:
    return {
        ADMIN_TOKEN: Principal(subject="admin@example.com", grants=(Grant("admin"),)),
        READER_TOKEN: Principal(subject="reader@example.com", grants=(Grant("reader"),)),
    }


@pytest.fixture
def build_client(tmp_path):
    """Builds a TestClient with a chosen execution adapter and principal set."""

    def _build(*, adapter=None, principals=None) -> TestClient:
        store = InMemoryPatchRunStore()
        service = PatchingService(
            _vulnerability_service(),
            adapter=adapter or RecordingPatchExecutionAdapter(),
            store=store,
        )
        context = ApiContext(
            onboarding=SubscriptionOnboardingService(
                tmp_path / "aiops", secret_writer=FakeSecretWriter()
            ),
            authenticator=StaticTokenAuthenticator(principals or _principals()),
            authorizer=Authorizer(),
            telemetry=ApiTelemetry(),
            vulnerability_provider=_vulnerability_service,
            patching_provider=lambda: service,
        )
        client = TestClient(create_app(context), raise_server_exceptions=False)
        client.patch_store = store  # type: ignore[attr-defined]
        return client

    return _build


@pytest.fixture
def client(build_client) -> TestClient:
    return build_client()


def _auth(token: str = ADMIN_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _target(client: TestClient, target_id: str) -> dict:
    response = client.get("/api/v1/patching/targets", headers=_auth())
    assert response.status_code == 200
    rows = response.json()["data"]
    matches = [row for row in rows if row["target_id"] == target_id]
    assert matches, f"{target_id} not in {[row['target_id'] for row in rows]}"
    return matches[0]


def test_targets_expose_inventory_kind_and_operation(client: TestClient) -> None:
    vm = _target(client, VM_ID)
    aks = _target(client, AKS_ID)
    assert vm["inventory_kind"] == "Azure VM"
    assert vm["operation"] == "install_patches"
    assert "KB600001" in [patch["patch_id"] for patch in vm["available_patches"]]
    assert aks["operation"] == "node_image_upgrade"


def test_runs_route_is_not_shadowed_by_the_target_path_converter(client: TestClient) -> None:
    response = client.get("/api/v1/patching/runs", headers=_auth())
    assert response.status_code == 200
    assert response.json()["data"] == []


def test_trigger_installs_only_allowlisted_patches(client: TestClient) -> None:
    response = client.post(
        "/api/v1/patching/runs",
        headers=_auth(),
        json={"target_id": VM_ID, "patch_ids": ["KB600001"], "reason": "Emergency patch"},
    )
    assert response.status_code == 202, response.text
    run = response.json()["data"]
    assert run["state"] == "submitted"
    assert run["patch_ids"] == ["KB600001"]
    assert run["requested_by"] == "admin@example.com"

    listed = client.get("/api/v1/patching/runs", headers=_auth()).json()["data"]
    assert [row["run_id"] for row in listed] == [run["run_id"]]


def test_trigger_rejects_a_patch_the_target_does_not_offer(client: TestClient) -> None:
    response = client.post(
        "/api/v1/patching/runs",
        headers=_auth(),
        json={"target_id": VM_ID, "patch_ids": ["KB999999"], "reason": "Not allowed"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


def test_aks_node_image_upgrade_takes_exactly_one_version(client: TestClient) -> None:
    aks = _target(client, AKS_ID)
    available = [patch["patch_id"] for patch in aks["available_patches"]]
    assert available, "AKS target should offer at least one upgrade option"

    ok = client.post(
        "/api/v1/patching/runs",
        headers=_auth(),
        json={
            "target_id": AKS_ID,
            "patch_ids": available[:1],
            "reason": "Node image refresh",
            "node_pool": "systempool",
        },
    )
    assert ok.status_code == 202, ok.text
    assert ok.json()["data"]["operation"] == "node_image_upgrade"

    too_many = client.post(
        "/api/v1/patching/runs",
        headers=_auth(),
        json={
            "target_id": AKS_ID,
            "patch_ids": available[:1] + ["latest"] if available[0] != "latest" else ["latest", "latest2"],
            "reason": "Two versions",
            "node_pool": "systempool",
        },
    )
    assert too_many.status_code == 400


def test_aks_upgrade_without_a_named_pool_is_refused(client: TestClient) -> None:
    """An unnamed pool would mean upgrading the whole cluster, so it is refused."""
    aks = _target(client, AKS_ID)
    assert aks["requires_node_pool"] is True

    response = client.post(
        "/api/v1/patching/runs",
        headers=_auth(),
        json={"target_id": AKS_ID, "patch_ids": ["latest"], "reason": "No pool named"},
    )
    assert response.status_code == 400
    assert "agent pool" in response.json()["error"]["message"]


def test_dry_run_does_not_reach_the_adapter(build_client) -> None:
    adapter = RecordingPatchExecutionAdapter()
    client = build_client(adapter=adapter)
    response = client.post(
        "/api/v1/patching/runs",
        headers=_auth(),
        json={"target_id": VM_ID, "patch_ids": ["KB600001"], "reason": "Rehearsal", "dry_run": True},
    )
    assert response.status_code == 202
    run = response.json()["data"]
    assert run["dry_run"] is True
    assert run["provider"] == "dry-run"
    assert adapter.submissions == []


def test_unconfigured_adapter_refuses_but_records_the_attempt(build_client) -> None:
    from operations.patching import UnconfiguredPatchExecutionAdapter

    client = build_client(adapter=UnconfiguredPatchExecutionAdapter())

    warnings = client.get("/api/v1/patching/targets", headers=_auth()).json()["warnings"]
    assert any("execution adapter" in warning for warning in warnings)

    response = client.post(
        "/api/v1/patching/runs",
        headers=_auth(),
        json={"target_id": VM_ID, "patch_ids": ["KB600001"], "reason": "No adapter"},
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "provider_unavailable"

    # The refusal is auditable: a failed run was still persisted.
    recorded = client.patch_store.list()  # type: ignore[attr-defined]
    assert len(recorded) == 1
    assert recorded[0].state == "failed"


def test_reader_cannot_trigger_a_run(client: TestClient) -> None:
    response = client.post(
        "/api/v1/patching/runs",
        headers=_auth(READER_TOKEN),
        json={"target_id": VM_ID, "patch_ids": ["KB600001"], "reason": "Nope"},
    )
    assert response.status_code == 403


def test_out_of_scope_target_is_not_found_rather_than_forbidden(build_client) -> None:
    principals = {
        ADMIN_TOKEN: Principal(
            subject="scoped@example.com",
            grants=(Grant("operator", scope=Scope({"subscription": ["sub-1"]})),),
        )
    }
    client = build_client(principals=principals)
    response = client.post(
        "/api/v1/patching/runs",
        headers=_auth(),
        json={"target_id": AKS_ID, "patch_ids": ["latest"], "reason": "Out of scope"},
    )
    assert response.status_code == 404
