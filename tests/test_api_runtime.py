"""Tests for default runtime wiring from the environment."""

from __future__ import annotations

import json
import threading
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
    _HYBRID_VULNERABILITY_CACHE_TTL_SECONDS,
    _defender_configuration_adapter,
    _execution_verifier,
    _hybrid_remediation_cache,
    _load_fabric_iq_adapter,
    _load_network_service,
    _patch_execution_adapter,
    _traffic_analysis_observations,
    _ttl_cached_value,
    aiops_home,
    build_authenticator,
    build_context,
)
from api.scope import Scope
from fabric.dataset_mapper import InventoryDatasetMapper
from intelligence.inventory.normalization import normalize_os_inventory
from intelligence.remediation.execution_verifier import ExecutionVerifier
from onboarding.credentials import KeyVaultSecretWriter
from onboarding.local_seed import DEFAULT_LOCAL_SUBSCRIPTION_ID, seed_local_environment
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


def test_managed_network_provider_analyzes_ingested_flow_observations(
    monkeypatch,
) -> None:
    import api.runtime as runtime_module
    import fabric.dataset_mapper as dataset_mapper_module
    from network.design import NetworkDesignPolicy

    vnet_id = (
        "/subscriptions/sub-a/resourceGroups/rg/providers/"
        "Microsoft.Network/virtualNetworks/vnet-a"
    )
    subnet_id = f"{vnet_id}/subnets/default"
    flow = dataset_mapper_module._relationship_row(
        {
            "relationshipId": "flow-1",
            "subjectId": vnet_id,
            "objectId": subnet_id,
            "predicate": "trafficObserved",
            "attributes": {"dataSource": "traffic_analytics"},
        },
        {},
        "run-1",
    )

    class _PolicyStore:
        def read_with_revision_or_raise(self):
            return NetworkDesignPolicy(), 3

    monkeypatch.setattr(
        runtime_module,
        "_load_ontology_rows",
        lambda: (
            [
                {
                    "entity_type": "VNet",
                    "resource_id": vnet_id,
                    "name": "vnet-a",
                    "payload_json": "{}",
                },
                {
                    "entity_type": "Subnet",
                    "resource_id": subnet_id,
                    "name": "default",
                    "payload_json": json.dumps({"vnetId": vnet_id}),
                },
            ],
            [flow],
            "2026-09-06T00:00:00Z",
        ),
    )
    monkeypatch.setattr(
        runtime_module,
        "_network_policy_store",
        lambda: _PolicyStore(),
    )

    service = _load_network_service()

    assert service is not None
    assert service.flow_log_provenance == {
        "state": "analyzed",
        "observed_flow_count": 1,
    }
    assert _traffic_analysis_observations([flow]) == (
        {
            **flow,
            "attributes": {"dataSource": "traffic_analytics"},
            "subject_id": vnet_id.casefold(),
            "object_id": subnet_id.casefold(),
        },
    )


def test_managed_network_provider_normalizes_persisted_flow_relationships(
    monkeypatch,
    tmp_path,
) -> None:
    import api.runtime as runtime_module
    from network.design import NetworkDesignPolicy

    snapshot = tmp_path / "current"
    (snapshot / "relationships").mkdir(parents=True)
    (snapshot / "manifest.json").write_text(
        json.dumps({"startedAt": "2026-09-06T00:00:00Z"}),
        encoding="utf-8",
    )
    rule_id = "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Network/networkSecurityGroups/nsg/securityRules/allow-web"
    relationship = {
        "relationshipId": "flow-1",
        "subjectId": "flow:endpoint",
        "objectId": rule_id,
        "predicate": "trafficObserved",
        "attributes": {
            "dataSource": "traffic_analytics",
            "allowedVsObserved": "allowed_and_observed",
        },
    }
    (snapshot / "relationships" / "relationships.jsonl").write_text(
        json.dumps(relationship) + "\n",
        encoding="utf-8",
    )
    persisted = InventoryDatasetMapper().load(
        snapshot,
        "sync-run",
    )["silver_resource_relationships"]

    observations = _traffic_analysis_observations(persisted)

    assert observations is not None
    assert observations[0]["subject_id"] == "flow:endpoint"
    assert observations[0]["object_id"] == rule_id.casefold()
    assert observations[0]["attributes"] == relationship["attributes"]

    class _PolicyStore:
        def read_with_revision_or_raise(self):
            return NetworkDesignPolicy(), 3

    monkeypatch.setattr(
        runtime_module,
        "_load_ontology_rows",
        lambda: (
            [
                {
                    "entity_type": "VNet",
                    "resource_id": "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Network/virtualNetworks/vnet-a",
                    "name": "vnet-a",
                    "payload_json": "{}",
                }
            ],
            persisted,
            "2026-09-06T00:00:00Z",
        ),
    )
    monkeypatch.setattr(
        runtime_module,
        "_network_policy_store",
        lambda: _PolicyStore(),
    )

    service = _load_network_service()

    assert service is not None
    assert service.flow_log_provenance == {
        "state": "analyzed",
        "observed_flow_count": 1,
    }


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


def test_ttl_cached_value_reuses_within_ttl_and_rebuilds_after_expiry():
    cache: dict[tuple[str, tuple[str, ...]], tuple[float, object]] = {}
    key = ("root", ("sub-1",))
    build_calls = {"count": 0}

    def build() -> object:
        build_calls["count"] += 1
        return object()

    first = _ttl_cached_value(cache, key, ttl_seconds=30, now=1_000.0, build=build)
    second = _ttl_cached_value(cache, key, ttl_seconds=30, now=1_010.0, build=build)

    assert first is second
    assert build_calls["count"] == 1

    third = _ttl_cached_value(cache, key, ttl_seconds=30, now=1_031.0, build=build)

    assert third is not first
    assert build_calls["count"] == 2


def test_ttl_cached_value_starts_ttl_after_slow_build_completes():
    cache: dict[tuple[str, tuple[str, ...]], tuple[float, object]] = {}
    key = ("root", ("sub-1",))
    build_calls = {"count": 0}

    def build() -> object:
        build_calls["count"] += 1
        return object()

    first = _ttl_cached_value(
        cache,
        key,
        ttl_seconds=30,
        now=1_000.0,
        build=build,
        completion_clock=lambda: 1_045.0,
    )
    second = _ttl_cached_value(
        cache,
        key,
        ttl_seconds=30,
        now=1_050.0,
        build=build,
    )

    assert first is second
    assert build_calls["count"] == 1
    assert cache[key][0] == 1_045.0


def test_ttl_cached_value_serializes_concurrent_builds_for_same_key():
    """WR-05 regression: `_ttl_cached_value` had no locking at all, so two
    genuinely concurrent callers racing the same cache key (exactly how
    Starlette's worker thread pool dispatches two in-flight requests for
    `hybrid_remediation`) could each miss the cache, each build their own
    value, and each overwrite the other's write -- so a caller later in the
    *same* request could observe a different object than an earlier caller
    in that request resolved moments before. This proves same-key concurrent
    callers now serialize on one build and all observe the identical cached
    object, deterministically -- via an Event gate, not a sleep/timing race.
    """
    cache: dict[tuple[str, tuple[str, ...]], tuple[float, object]] = {}
    key = ("root", ("sub-1",))
    build_calls = {"count": 0}
    build_entered = threading.Event()
    release_build = threading.Event()

    def build() -> object:
        build_calls["count"] += 1
        # Signal that this call is genuinely inside the critical section
        # (holding the per-key lock) before the second caller is started,
        # then hold the lock open until the test explicitly releases it --
        # giving a broken (unlocked) implementation every opportunity to
        # let the second caller build its own competing value concurrently.
        build_entered.set()
        assert release_build.wait(timeout=5), "build() was never released"
        return object()

    def call() -> object:
        return _ttl_cached_value(cache, key, ttl_seconds=30, now=1_000.0, build=build)

    first_result: list[object] = []
    first_thread = threading.Thread(target=lambda: first_result.append(call()))
    first_thread.start()

    assert build_entered.wait(timeout=5), "first caller never entered build()"

    second_result: list[object] = []
    second_thread = threading.Thread(target=lambda: second_result.append(call()))
    second_thread.start()

    # The second caller must block behind the first caller's in-flight
    # build rather than starting a competing build of its own -- proving
    # the two calls serialize on the same per-key lock instead of racing.
    second_thread.join(timeout=0.2)
    assert second_thread.is_alive(), (
        "second caller did not block behind the in-flight build for the same key"
    )

    release_build.set()
    first_thread.join(timeout=5)
    second_thread.join(timeout=5)
    assert not first_thread.is_alive()
    assert not second_thread.is_alive()

    # Exactly one build happened for the racing key, and every concurrent
    # caller -- plus the cache entry itself -- observed that identical
    # object, not two competing values with one silently clobbering the
    # other.
    assert build_calls["count"] == 1
    assert first_result and second_result
    assert first_result[0] is second_result[0]
    assert cache[key][1] is first_result[0]


def test_ttl_cached_value_does_not_serialize_unrelated_keys():
    """WR-05 design guard: locking must be scoped per `(cache, key)`, not a
    single module-wide lock, so a slow build in flight for one key (e.g. one
    subscription scope) never blocks a concurrent caller resolving a
    *different* key (a different subscription scope, or a different
    TTL-cache family dict entirely) that has nothing to do with it."""
    cache: dict[tuple[str, tuple[str, ...]], tuple[float, object]] = {}
    key_a = ("root", ("sub-a",))
    key_b = ("root", ("sub-b",))

    entered_a = threading.Event()
    entered_b = threading.Event()
    release = threading.Event()

    def build_a() -> object:
        entered_a.set()
        assert release.wait(timeout=5), "build_a() was never released"
        return object()

    def build_b() -> object:
        entered_b.set()
        assert release.wait(timeout=5), "build_b() was never released"
        return object()

    thread_a = threading.Thread(
        target=lambda: _ttl_cached_value(
            cache, key_a, ttl_seconds=30, now=1_000.0, build=build_a
        )
    )
    thread_b = threading.Thread(
        target=lambda: _ttl_cached_value(
            cache, key_b, ttl_seconds=30, now=1_000.0, build=build_b
        )
    )
    thread_a.start()
    thread_b.start()

    # If both keys serialized on one shared lock, the second thread would
    # never reach its own build() until the first released -- which would
    # deadlock this assertion (and, in production, would mean one slow
    # subscription scope's cache miss stalls every unrelated scope's
    # request). Both entering proves the two keys did not contend.
    assert entered_a.wait(timeout=5), "build_a() never entered while build_b() was pending"
    assert entered_b.wait(timeout=5), "build_b() never entered while build_a() was pending"

    release.set()
    thread_a.join(timeout=5)
    thread_b.join(timeout=5)
    assert not thread_a.is_alive()
    assert not thread_b.is_alive()


def test_hybrid_remediation_provider_resolves_one_generation_per_request_window(
    monkeypatch, tmp_path,
):
    """D-03/WR-07: scope validation and execution construction both resolve
    ``hybrid_remediation`` -- caching it here is sufficient for both paths
    (operations.py::_require's remediation branch and
    runtime.py::_execution_service_for_scope's _planner_for_scope) to observe
    the same LiveRemediationPlanner/PlanRepository generation."""
    # WR-02: isolate AIOPS_HOME like every other build_context()-based test in
    # this file (e.g. test_context_loads_local_seeded_snapshot above). The
    # module-level _hybrid_remediation_cache is a process-wide singleton keyed
    # on (str(aiops_home()), subscription_ids) that outlives this test; without
    # a unique root, this test's fake, empty-exposure planner would be written
    # into the shared cache under the real default root key and could leak
    # into any other test resolving hybrid_remediation for the same default
    # root within the shared 30s TTL window.
    monkeypatch.setenv("AIOPS_HOME", str(tmp_path / "aiops"))
    monkeypatch.setenv("AIOPS_API_AUTH", "token")
    monkeypatch.setenv("AIOPS_API_TOKENS", TOKENS)

    # No live ARG round trip: the object identity under test is the planner
    # hybrid_remediation resolves and caches, not the vulnerability data it
    # wraps, so the vulnerability builder is faked out entirely.
    class _FakeVulnerabilityService:
        freshness = "2026-01-01T00:00:00Z"

        def asset_exposures(self, scope=None):
            return []

    monkeypatch.setattr(
        "api.runtime.live_vulnerability_service",
        lambda *args, **kwargs: _FakeVulnerabilityService(),
    )

    context = build_context()
    assert context.hybrid_remediation_provider is not None

    subscription_ids = [DEFAULT_LOCAL_SUBSCRIPTION_ID]
    first = context.hybrid_remediation_provider(subscription_ids)
    second = context.hybrid_remediation_provider(subscription_ids)

    assert first is second

    # Rewrite the cached timestamp to simulate the TTL having elapsed --
    # equivalent to monkeypatching time.time() but touches only this one
    # cache entry rather than every other TTL-cached provider in the module.
    cache_key = (str(aiops_home()), tuple(subscription_ids))
    cached_at, cached_value = _hybrid_remediation_cache[cache_key]
    _hybrid_remediation_cache[cache_key] = (
        cached_at - _HYBRID_VULNERABILITY_CACHE_TTL_SECONDS - 1,
        cached_value,
    )

    third = context.hybrid_remediation_provider(subscription_ids)

    assert third is not first


def test_hybrid_remediation_provider_serializes_concurrent_callers_for_same_key(
    monkeypatch, tmp_path,
):
    """WR-05, exercised at the production integration point the review cited
    ("two threads racing hybrid_remediation on the same key"): two
    genuinely concurrent callers -- exactly how Starlette's worker thread
    pool would dispatch operations.py::_require's remediation branch and
    runtime.py::_execution_service_for_scope's _planner_for_scope for two
    in-flight requests -- must resolve to the exact same
    LiveRemediationPlanner object for the same (root, subscription-set) key,
    with the underlying vulnerability builder invoked exactly once, not
    twice with one silently clobbering the other's cache write.
    """
    monkeypatch.setenv("AIOPS_HOME", str(tmp_path / "aiops"))
    monkeypatch.setenv("AIOPS_API_AUTH", "token")
    monkeypatch.setenv("AIOPS_API_TOKENS", TOKENS)

    build_calls = {"count": 0}
    build_entered = threading.Event()
    release_build = threading.Event()

    class _FakeVulnerabilityService:
        freshness = "2026-01-01T00:00:00Z"

        def asset_exposures(self, scope=None):
            return []

    def _fake_live_vulnerability_service(*args, **kwargs):
        build_calls["count"] += 1
        # Signal (and then hold open) the in-flight build window so the
        # second concurrent caller is started while the first is still
        # inside the build -- deterministically forcing the overlap a
        # broken (unlocked) implementation would mishandle, rather than
        # hoping a timing race exposes it.
        build_entered.set()
        assert release_build.wait(timeout=5), "vulnerability builder was never released"
        return _FakeVulnerabilityService()

    monkeypatch.setattr(
        "api.runtime.live_vulnerability_service",
        _fake_live_vulnerability_service,
    )

    context = build_context()
    subscription_ids = [DEFAULT_LOCAL_SUBSCRIPTION_ID]

    first_result: list[object] = []
    first_thread = threading.Thread(
        target=lambda: first_result.append(
            context.hybrid_remediation_provider(subscription_ids)
        )
    )
    first_thread.start()
    assert build_entered.wait(timeout=5), "first caller never entered the builder"

    second_result: list[object] = []
    second_thread = threading.Thread(
        target=lambda: second_result.append(
            context.hybrid_remediation_provider(subscription_ids)
        )
    )
    second_thread.start()

    # The second concurrent caller must block behind the first caller's
    # in-flight build instead of resolving its own competing
    # LiveRemediationPlanner -- proving the two same-key callers serialize
    # on the fix's per-key lock rather than racing the shared cache dict.
    second_thread.join(timeout=0.2)
    assert second_thread.is_alive(), (
        "second concurrent hybrid_remediation caller did not block behind "
        "the in-flight build for the same key"
    )

    release_build.set()
    first_thread.join(timeout=5)
    second_thread.join(timeout=5)
    assert not first_thread.is_alive()
    assert not second_thread.is_alive()

    # Exactly one build happened for the racing key, and both concurrent
    # callers resolved the identical LiveRemediationPlanner object.
    assert build_calls["count"] == 1
    assert first_result and second_result
    assert first_result[0] is second_result[0]


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
