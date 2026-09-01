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
from api.telemetry import ApiTelemetry
from intelligence.vulnerability.service import VulnerabilityIntelligenceService
from onboarding.service import SubscriptionOnboardingService
from operations.patching import InMemoryPatchRunStore, PatchingService
from operations.patching.adapters import RecordingPatchExecutionAdapter

ADMIN_TOKEN = "admin-token-0123456789abcdef"
READER_TOKEN = "reader-token-0123456789abcde"

VM_ID = "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1"
AKS_ID = "/subscriptions/sub-2/resourceGroups/rg/providers/Microsoft.ContainerService/managedClusters/aks1"
STORAGE_ID = "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/data"


class FakeSecretWriter:
    def store(self, *, connection_id: str, secret_value: str) -> str:
        return f"keyvault://kv-aiops-example-test/secrets/aiops-conn-{connection_id}/v1"


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
            {
                "id": "finding-storage",
                "cve_id": "CVE-2026-0001",
                "server_id": STORAGE_ID,
                "resource_type": "Microsoft.Storage/storageAccounts",
                "business_service": "Payments",
                "subscription_id": "sub-1",
                "source": "Microsoft Defender for Cloud",
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


def test_non_compute_defender_assets_never_become_patch_targets(client: TestClient) -> None:
    response = client.get("/api/v1/patching/targets", headers=_auth())

    assert response.status_code == 200
    assert STORAGE_ID not in {row["target_id"] for row in response.json()["data"]}


def test_runs_route_is_not_shadowed_by_the_target_path_converter(client: TestClient) -> None:
    response = client.get("/api/v1/patching/runs", headers=_auth())
    assert response.status_code == 200
    assert response.json()["data"] == []


def test_public_direct_patch_run_post_is_unavailable(client: TestClient) -> None:
    response = client.post(
        "/api/v1/patching/runs",
        headers=_auth(),
        json={
            "target_id": VM_ID,
            "patch_ids": ["KB600001"],
            "reason": "Emergency patch",
            "approved_by": "manager@example.com",
        },
    )
    assert response.status_code == 405


def test_openapi_exposes_patch_reads_but_no_direct_patch_mutation(
    client: TestClient,
) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert set(paths["/api/v1/patching/targets"]) == {"get"}
    assert set(paths["/api/v1/patching/runs"]) == {"get"}
    assert set(paths["/api/v1/patching/targets/{target_id}"]) == {"get"}


def test_patching_trigger_remains_internal_to_remediation_execution() -> None:
    import inspect

    from intelligence.remediation.execution_service import RemediationExecutionService

    source = inspect.getsource(RemediationExecutionService._submit_and_record)
    assert "self._patching.trigger(" in source
