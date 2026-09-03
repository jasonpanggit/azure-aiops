"""Tests for default runtime wiring from the environment."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import (
    EntraJwtAuthenticator,
    GatewayOrDirectAuthenticator,
    HeaderPrincipalAuthenticator,
    StaticTokenAuthenticator,
)
from api.providers import STALE, ProviderRuntime, ProviderSpec
from api.runtime import (
    _defender_configuration_adapter,
    _execution_verifier,
    _load_fabric_iq_adapter,
    _patch_execution_adapter,
    aiops_home,
    build_authenticator,
    build_context,
)
from api.scope import Scope
from intelligence.inventory.normalization import normalize_os_inventory
from intelligence.remediation.execution_verifier import ExecutionVerifier
from onboarding.credentials import KeyVaultSecretWriter
from onboarding.local_seed import seed_local_environment
from operations.defender_configuration import AzureArmDefenderConfigurationAdapter
from operations.patching.azure_adapter import AzureArmPatchExecutionAdapter
from storage.datasets import DatasetStore as NeutralDatasetStore

TOKENS = '{"demo-token-0123456789abcdef": {"subject": "d@e.com", "grants": [{"role": "admin"}]}}'


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch, tmp_path):
    for name in (
        "AIOPS_API_AUTH",
        "AIOPS_API_TOKENS",
        "AIOPS_API_GATEWAY_GRANTS",
        "AIOPS_CONNECTION_KEY_VAULT",
        "AIOPS_ENTRA_AUDIENCE",
        "AIOPS_ENTRA_TENANT_ID",
        "AIOPS_DEFENDER_CONFIGURATION_EXECUTION",
        "AIOPS_PATCH_EXECUTION",
        "AZURE_TENANT_ID",
        "AZURE_SP_CLIENT_ID",
        "AZURE_SP_CLIENT_SECRET",
        "TENANT_ID",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AIOPS_HOME", str(tmp_path / "aiops"))


def test_home_follows_aiops_home(monkeypatch, tmp_path):
    monkeypatch.setenv("AIOPS_HOME", str(tmp_path / "custom"))
    assert aiops_home() == tmp_path / "custom"


def test_azure_patch_runtime_shares_credential_with_execution_verifier(
    monkeypatch,
) -> None:
    credential = object()
    monkeypatch.setenv("AIOPS_PATCH_EXECUTION", "azure")
    monkeypatch.setattr("api.runtime._azure_patch_credential", lambda: credential)

    adapter = _patch_execution_adapter()
    verifier = _execution_verifier()

    assert isinstance(adapter, AzureArmPatchExecutionAdapter)
    assert isinstance(verifier, ExecutionVerifier)
    assert adapter._credential is credential
    assert verifier._credential is credential


def test_azure_patch_credential_prefers_service_principal_over_managed_identity(
    monkeypatch,
) -> None:
    """A configured subscription-connection SPN should win over DefaultAzureCredential.

    The managed identity may lack RBAC grants (e.g. Arc ``installPatches``)
    that the subscription's onboarding service principal already has, so
    patch execution must prefer the SPN when both are available.
    """
    import api.runtime as runtime_module

    monkeypatch.setattr(runtime_module, "_PATCH_EXECUTION_CREDENTIAL", runtime_module._UNSET)
    monkeypatch.setenv("AIOPS_PATCH_EXECUTION", "azure")
    monkeypatch.setenv("AZURE_TENANT_ID", "tenant-x")
    monkeypatch.setenv("AZURE_SP_CLIENT_ID", "client-x")
    monkeypatch.setenv("AZURE_SP_CLIENT_SECRET", "secret-x")

    def _fail_default_credential():
        raise AssertionError("DefaultAzureCredential should not be used when SPN is configured")

    monkeypatch.setattr(
        "azure.identity.DefaultAzureCredential",
        _fail_default_credential,
    )

    credential = runtime_module._azure_patch_credential()

    from azure.identity import ClientSecretCredential

    assert isinstance(credential, ClientSecretCredential)


def test_azure_patch_credential_falls_back_to_managed_identity_without_spn(
    monkeypatch,
) -> None:
    import api.runtime as runtime_module

    monkeypatch.setattr(runtime_module, "_PATCH_EXECUTION_CREDENTIAL", runtime_module._UNSET)
    monkeypatch.setenv("AIOPS_PATCH_EXECUTION", "azure")
    for name in ("AZURE_TENANT_ID", "AZURE_SP_CLIENT_ID", "AZURE_SP_CLIENT_SECRET", "TENANT_ID"):
        monkeypatch.delenv(name, raising=False)

    sentinel = object()
    monkeypatch.setattr(
        "azure.identity.DefaultAzureCredential",
        lambda: sentinel,
    )

    credential = runtime_module._azure_patch_credential()

    assert credential is sentinel


def test_azure_defender_configuration_runtime_shares_verifier_credential(
    monkeypatch,
) -> None:
    credential = object()
    monkeypatch.setenv("AIOPS_DEFENDER_CONFIGURATION_EXECUTION", "azure")
    monkeypatch.setattr(
        "api.runtime._azure_defender_configuration_credential",
        lambda: credential,
    )

    adapter = _defender_configuration_adapter()
    verifier = _execution_verifier()

    assert isinstance(adapter, AzureArmDefenderConfigurationAdapter)
    assert isinstance(verifier, ExecutionVerifier)
    assert adapter._credential is credential
    assert verifier._credential is credential


def test_default_auth_mode_requires_configured_tokens():
    with pytest.raises(RuntimeError, match="AIOPS_API_TOKENS"):
        build_authenticator()


def test_token_mode_requires_tokens(monkeypatch):
    """Refuse to start an API that cannot authenticate anyone."""
    monkeypatch.setenv("AIOPS_API_AUTH", "token")
    with pytest.raises(RuntimeError, match="AIOPS_API_TOKENS"):
        build_authenticator()


def test_token_mode_rejects_malformed_json(monkeypatch):
    monkeypatch.setenv("AIOPS_API_AUTH", "token")
    monkeypatch.setenv("AIOPS_API_TOKENS", "not json")
    with pytest.raises(RuntimeError, match="valid JSON"):
        build_authenticator()


def test_token_mode_builds_principals(monkeypatch):
    monkeypatch.setenv("AIOPS_API_AUTH", "token")
    monkeypatch.setenv("AIOPS_API_TOKENS", TOKENS)
    assert isinstance(build_authenticator(), StaticTokenAuthenticator)


def test_gateway_mode_requires_explicit_grants(monkeypatch):
    monkeypatch.setenv("AIOPS_API_AUTH", "gateway")
    with pytest.raises(RuntimeError, match="AIOPS_API_GATEWAY_GRANTS"):
        build_authenticator()


def test_gateway_mode_builds_a_resolver(monkeypatch):
    monkeypatch.setenv("AIOPS_API_AUTH", "gateway")
    monkeypatch.setenv(
        "AIOPS_API_GATEWAY_GRANTS",
        '{"d@e.com": [{"role": "reader", "scope": {"subscription": ["sub-1"]}}]}',
    )
    monkeypatch.setenv("AIOPS_ENTRA_TENANT_ID", "tenant-id")
    monkeypatch.setenv("AIOPS_ENTRA_AUDIENCE", "api://aiops")

    # APIM fronts only the MCP route, so gateway mode must still accept the
    # direct Entra tokens the browser sends to every other route.
    authenticator = build_authenticator()
    assert isinstance(authenticator, GatewayOrDirectAuthenticator)
    assert isinstance(authenticator.gateway, HeaderPrincipalAuthenticator)
    assert isinstance(authenticator.direct, EntraJwtAuthenticator)


def test_gateway_mode_refuses_to_start_without_entra_identity(monkeypatch):
    """Gateway mode without Entra config would 401 every browser request.

    That is the misconfiguration that locked the web app out of the whole
    API, so it must fail loudly at startup rather than silently at runtime.
    """
    monkeypatch.setenv("AIOPS_API_AUTH", "gateway")
    monkeypatch.setenv(
        "AIOPS_API_GATEWAY_GRANTS",
        '{"d@e.com": [{"role": "reader"}]}',
    )
    monkeypatch.delenv("AIOPS_ENTRA_TENANT_ID", raising=False)
    monkeypatch.delenv("AIOPS_ENTRA_AUDIENCE", raising=False)

    with pytest.raises(RuntimeError, match="AIOPS_ENTRA_TENANT_ID"):
        build_authenticator()


def test_entra_mode_requires_identity_and_builds_validator(monkeypatch):
    monkeypatch.setenv("AIOPS_API_AUTH", "entra")
    monkeypatch.setenv("AIOPS_ENTRA_TENANT_ID", "tenant-id")
    monkeypatch.setenv("AIOPS_ENTRA_AUDIENCE", "api://aiops")
    monkeypatch.setenv(
        "AIOPS_API_GATEWAY_GRANTS",
        '{"d@e.com": [{"role": "reader"}]}',
    )

    assert isinstance(build_authenticator(), EntraJwtAuthenticator)


def test_unknown_auth_mode_fails_loudly(monkeypatch):
    monkeypatch.setenv("AIOPS_API_AUTH", "anonymous")
    with pytest.raises(RuntimeError, match="Unknown"):
        build_authenticator()


def test_token_context_has_no_semantic_snapshot(monkeypatch):
    """Absent any synced connection data, the provider must say so (return
    None) rather than report an empty estate as if it were real data."""
    monkeypatch.setenv("AIOPS_API_AUTH", "token")
    monkeypatch.setenv("AIOPS_API_TOKENS", TOKENS)
    context = build_context()
    assert context.semantic_provider is not None
    assert context.semantic_provider() is None


def test_context_wires_key_vault_secret_writer(monkeypatch):
    monkeypatch.setenv("AIOPS_API_AUTH", "token")
    monkeypatch.setenv("AIOPS_API_TOKENS", TOKENS)
    monkeypatch.setenv("AIOPS_CONNECTION_KEY_VAULT", "kv-aiops-example")

    context = build_context()

    assert isinstance(context.onboarding.secret_writer, KeyVaultSecretWriter)
    assert context.onboarding.secret_writer.vault_name == "kv-aiops-example"


def test_factory_with_no_context_serves_requests(monkeypatch):
    """`uvicorn --factory api.app:create_app` must work, not 500 on every call."""
    monkeypatch.setenv("AIOPS_API_AUTH", "token")
    monkeypatch.setenv("AIOPS_API_TOKENS", TOKENS)
    client = TestClient(create_app(), raise_server_exceptions=False)

    assert client.get("/health").json()["status"] == "ok"

    unauthenticated = client.get("/api/v1/subscription-connections")
    assert unauthenticated.status_code == 401
    # Regression: the secret scrubber used to redact this prose.
    assert "[REDACTED]" not in unauthenticated.json()["error"]["message"]

    listed = client.get(
        "/api/v1/subscription-connections",
        headers={"Authorization": "Bearer demo-token-0123456789abcdef"},
    )
    assert listed.status_code == 200
    assert listed.json()["data"] == []


def test_context_loads_local_seeded_snapshot(monkeypatch, tmp_path):
    home = tmp_path / "aiops-local"
    seed_local_environment(root=home, fixture="tests/fixtures/mock_arg_responses.json")
    monkeypatch.setenv("AIOPS_HOME", str(home))
    monkeypatch.setenv("AIOPS_API_AUTH", "token")
    monkeypatch.setenv("AIOPS_API_TOKENS", TOKENS)
    monkeypatch.setenv("AIOPS_RUNTIME_MODE", "demo")

    context = build_context()

    assert context.semantic_provider is not None
    assert context.semantic_provider() is not None
    assert context.network_provider is not None
    assert context.network_provider() is not None


def test_configured_fabric_iq_loader_returns_governed_adapter(monkeypatch):
    class FakeService:
        def ontology_query(self, question, *, entity=""):
            return {"answer": question, "entity": entity}

    class FakeRuntime:
        service = FakeService()

    monkeypatch.setenv("AIOPS_ENABLE_FABRIC_IQ", "true")
    monkeypatch.setattr("api.runtime._fabric_runtime_from_environment", lambda: FakeRuntime())
    adapter = _load_fabric_iq_adapter()
    assert adapter is not None
    result = adapter.run("relationships", {"subject": "network"}, Scope.from_mapping({}))
    assert result.status == "ok"
    assert result.data["metadata"]["identity_authority"] is False
    # The runtime answers from the OneLake ontology projection, not from a
    # Fabric IQ query surface, so a citation must not claim Fabric IQ.
    assert result.data["metadata"]["provenance"] == "onelake-ontology-projection"
    assert result.data["metadata"]["source"] == "onelake-ontology-projection"


def test_inventory_runtime_loader_reads_active_generation_metadata(
    monkeypatch, tmp_path
):
    home = tmp_path / "aiops"
    fixture = json.loads(
        Path("tests/fixtures/mock_inventory_arg.json").read_text(encoding="utf-8")
    )
    observations, statuses = normalize_os_inventory(
        {
            "inventory_native_vm_os": fixture["inventory_native_vm_os"][:1],
        },
        "2026-08-25T12:00:00+00:00",
        run_id="runtime-inventory-run",
        requested_scope={"subscription": ["sub-a"]},
    )
    NeutralDatasetStore(home).publish(
        {
            "inventory/os_observations": observations,
            "inventory/source_status": statuses,
        },
        {},
        {
            "runId": "runtime-inventory-run",
            "startedAt": "2026-08-25T12:00:00Z",
            "queryVersion": "inventory-os-v1",
            "status": "completed",
        },
    )
    monkeypatch.setenv("AIOPS_HOME", str(home))

    from api.runtime import _load_inventory_service

    service = _load_inventory_service()
    assert service is not None
    assert service.generation_id == "runtime-inventory-run"
    assert service.observed_at == "2026-08-25T12:00:00Z"


def test_inventory_runtime_marks_old_generation_stale_without_erasing_rows(
    monkeypatch, tmp_path
):
    home = tmp_path / "aiops"
    fixture = json.loads(
        Path("tests/fixtures/mock_inventory_arg.json").read_text(encoding="utf-8")
    )
    observations, statuses = normalize_os_inventory(
        {"inventory_native_vm_os": fixture["inventory_native_vm_os"][:1]},
        "2026-08-20T12:00:00+00:00",
        run_id="stale-inventory-run",
        requested_scope={"subscription": ["sub-a"]},
    )
    NeutralDatasetStore(home).publish(
        {
            "inventory/os_observations": observations,
            "inventory/source_status": statuses,
        },
        {},
        {
            "runId": "stale-inventory-run",
            "startedAt": "2026-08-20T12:00:00Z",
            "queryVersion": "inventory-os-v1",
            "status": "completed",
        },
    )
    monkeypatch.setenv("AIOPS_HOME", str(home))

    from api.runtime import _load_inventory_service

    service = _load_inventory_service()
    assert service is not None
    runtime = ProviderRuntime(
        {"inventory": ProviderSpec(lambda: service)},
        stale_after_hours=24,
        clock=lambda: datetime(2026, 8, 25, 12, 0, tzinfo=UTC),
    )

    health = runtime.refresh(force=True)

    assert health["providers"]["inventory"]["state"] == STALE
    assert runtime.get("inventory").snapshot.observations


def test_attach_live_defender_correlator_wires_planner_when_service_available() -> None:
    from intelligence.remediation.plan_repository import PlanRepository
    from semantic.live_operations import LiveRemediationPlanner

    class _FakeVulnerabilityService:
        freshness = "2026-01-01T00:00:00Z"

        def asset_exposures(self, scope=None):
            return [{"asset_id": "vm-1", "name": "vm-1"}]

        def defender_posture(self, scope=None):
            return []

        def security_alerts(self, scope=None, **kwargs):
            return []

        def defender_attack_paths_for_scope(self, scope=None):
            return []

        def secure_score_controls(self, scope=None):
            return []

        def defender_overview(self, scope=None):
            return {"coverage": {}}

    from api.runtime import _attach_live_defender_correlator

    service = _FakeVulnerabilityService()
    planner = LiveRemediationPlanner(service, repository=PlanRepository())

    result = _attach_live_defender_correlator(planner, service)

    assert result is planner
    assert planner.defender_correlator is not None
    assert planner.defender_correlator.cases() == []


def test_attach_live_defender_correlator_noop_without_service() -> None:
    from api.runtime import _attach_live_defender_correlator
    from intelligence.remediation.plan_repository import PlanRepository
    from semantic.live_operations import LiveRemediationPlanner

    planner = LiveRemediationPlanner(None, repository=PlanRepository())

    result = _attach_live_defender_correlator(planner, None)

    assert result is planner
    assert getattr(planner, "defender_correlator", None) is None


def test_live_planner_maps_patchable_defender_recommendation_to_governed_plan() -> None:
    from intelligence.remediation.plan_repository import PlanRepository
    from semantic.live_operations import LiveRemediationPlanner

    class _Service:
        freshness = "2026-01-01T00:00:00Z"

        def asset_exposures(self, scope=None):
            return [{
                "asset_id": "/subscriptions/s/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm",
                "name": "vm",
                "missing_kbs": ["KB123"],
                "defender_recommendations": ["Update vulnerable package"],
                "defender_patchable": True,
                "priority_score": 90,
                "finding_count": 1,
                "finding_ids": ["assessment-1"],
            }]

    planner = LiveRemediationPlanner(_Service(), repository=PlanRepository())
    plan = planner.generate_plans()["plans"][0]

    assert plan["defender_mapping"]["status"] == "mapped"
    assert plan["defender_mapping"]["missing_kbs"] == ["KB123"]
    assert plan["action_id"] == "controlled-patch-recovery"
    assert plan["execution_authorized"] is False


def test_live_planner_keeps_unmappable_defender_recommendation_manual_review() -> None:
    from intelligence.remediation.plan_repository import PlanRepository
    from semantic.live_operations import LiveRemediationPlanner

    class _Service:
        freshness = "2026-01-01T00:00:00Z"

        def asset_exposures(self, scope=None):
            return [{
                "asset_id": "vm-1",
                "name": "vm-1",
                "missing_kbs": [],
                "defender_recommendations": ["Review configuration"],
                "defender_patchable": False,
                "finding_count": 1,
                "finding_ids": ["assessment-1"],
            }]

    planner = LiveRemediationPlanner(_Service(), repository=PlanRepository())
    plan = planner.generate_plans()["plans"][0]

    assert plan["defender_mapping"]["status"] == "manual_review"
    assert plan["action_id"] == "defender-manual-review"
