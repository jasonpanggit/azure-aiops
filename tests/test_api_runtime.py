"""Tests for default runtime wiring from the environment."""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import api.runtime as runtime_module
from api.app import create_app
from api.auth import (
    EntraJwtAuthenticator,
    GatewayOrDirectAuthenticator,
    HeaderPrincipalAuthenticator,
    StaticTokenAuthenticator,
)
from api.exposure_query import ExposureQueryUnavailableError
from api.providers import (
    DEFERRED,
    LOADING,
    STALE,
    ProviderRuntime,
    ProviderSpec,
    ProviderValue,
)
from api.runtime import (
    _HYBRID_NETWORK_CACHE_TTL_SECONDS,
    _HYBRID_VULNERABILITY_CACHE_TTL_SECONDS,
    _build_provider_runtime,
    _defender_configuration_adapter,
    _execution_verifier,
    _exposure_generation_window,
    _fabric_change_intelligence,
    _fabric_exposure_query_service,
    _fabric_remediation_catalog,
    _fabric_remediation_planner,
    _governance_snapshot_cache,
    _hybrid_network_cache,
    _hybrid_remediation_cache,
    _hybrid_vulnerability_cache,
    _load_fabric_iq_adapter,
    _load_network_service,
    _patch_execution_adapter,
    _runtime_metadata,
    _traffic_analysis_observations,
    _ttl_cached_value,
    aiops_home,
    build_authenticator,
    build_context,
)
from api.scope import Scope
from fabric.dataset_mapper import InventoryDatasetMapper
from intelligence.inventory.normalization import normalize_os_inventory
from network.service import NetworkIntelligenceService
from onboarding.credentials import (
    CredentialResolver,
    EnvironmentSecretProvider,
    KeyVaultSecretWriter,
)
from onboarding.local_seed import DEFAULT_LOCAL_SUBSCRIPTION_ID, seed_local_environment
from onboarding.registry import ConnectionRegistry
from ontology.subscription_connection import CredentialReference, SubscriptionConnection
from storage.datasets import DatasetStore as NeutralDatasetStore

TOKENS = '{"demo-token-0123456789abcdef": {"subject": "d@e.com", "grants": [{"role": "admin"}]}}'


def test_fabric_temporal_exposure_reads_observation_projection() -> None:
    reads: list[tuple[str, tuple[str, ...] | None]] = []

    class Delta:
        def version(self, _uri: str) -> int:
            return 1

        def read(
            self,
            uri: str,
            *,
            columns: tuple[str, ...] | None = None,
        ) -> list[dict[str, object]]:
            reads.append((uri, columns))
            return []

    service = SimpleNamespace(
        onelake=SimpleNamespace(
            table_uri=lambda layer, name: f"/{layer}/{name}"
        ),
        delta=Delta(),
    )

    runtime_module._fabric_temporal_exposure_tables(
        SimpleNamespace(service=service)
    )

    assert reads == [
        ("/gold/exposure_current", None),
        (
            "/silver/exposure_observations",
            (
                "observation_id",
                "event_time",
                "ingested_at",
                "run_at",
                "published_at",
                "enriched_at",
            ),
        ),
        ("/metadata/source_status", None),
    ]


def test_durable_catalog_records_reuse_short_ttl_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls = 0

    def records() -> tuple[dict[str, object], ...]:
        nonlocal calls
        calls += 1
        return (
            {
                "source": "nvd",
                "identifier": "CVE-2026-59873",
                "payload": {"description": "bounded"},
            },
            {
                "source": "msrc",
                "identifier": "KB6000001",
                "payload": {"cve_ids": ["CVE-2026-59873"]},
            },
        )

    runtime_module._durable_catalog_cache.clear()
    monkeypatch.setattr(runtime_module, "aiops_home", lambda: tmp_path)
    monkeypatch.setattr(runtime_module, "_durable_enrichment_records", records)
    monkeypatch.setattr(runtime_module.time, "monotonic", lambda: 1_000.0)

    first = runtime_module._durable_catalog_records("CVE-2026-59873")
    second = runtime_module._durable_catalog_records("KB6000001")

    assert {record["source"] for record in first} == {"nvd", "msrc"}
    assert {record["source"] for record in second} == {"msrc"}
    assert calls == 1


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


def test_runtime_metadata_never_instantiates_semantic_engine() -> None:
    class _Service:
        def semantic_version(self) -> str:
            return "semantic-generation-7"

        def ontology_health(self) -> dict[str, str]:
            return {"timestamp": "2026-09-10T00:00:00Z"}

    class _Runtime:
        service = _Service()

        def semantic_engine(self) -> object:
            raise AssertionError("metadata must not hydrate the semantic engine")

    onboarding = SimpleNamespace(registry=SimpleNamespace(list=list))

    metadata = _runtime_metadata(onboarding, lambda: _Runtime())

    assert metadata == {
        "ontology_version": "semantic-generation-7",
        "freshness": "2026-09-10T00:00:00Z",
        "last_discovery_run": "",
        "last_ontology_publication": "2026-09-10T00:00:00Z",
    }


def test_configured_fabric_metadata_failure_never_loads_local_snapshot(
    monkeypatch,
) -> None:
    import api.runtime as runtime_module

    monkeypatch.setattr(
        runtime_module,
        "_load_semantic_snapshot",
        lambda: (_ for _ in ()).throw(
            AssertionError("configured Fabric must not load a local snapshot")
        ),
    )
    onboarding = SimpleNamespace(registry=SimpleNamespace(list=list))

    metadata = _runtime_metadata(
        onboarding,
        lambda: None,
        fabric_configured=True,
    )

    assert metadata == {
        "ontology_version": "",
        "freshness": "",
        "last_discovery_run": "",
        "last_ontology_publication": "",
        "degraded_reason": "Fabric runtime is unavailable",
    }


def test_change_provider_does_not_hydrate_operations_agent() -> None:
    semantic = SimpleNamespace(freshness="2026-09-10T00:00:00+00:00")
    snapshot = {
        "inventory": [],
        "resource_changes": [],
        "policy_deviations": [],
        "security_deviations": [],
        "network_changes": [],
        "identity_changes": [],
        "iac_changes": [],
        "incidents": [],
        "history": [],
        "expected_configurations": {},
        "observed_configurations": {},
    }
    runtime = SimpleNamespace(
        config=SimpleNamespace(
            change_intelligence=SimpleNamespace(
                enabled=True,
                max_changes=100,
                max_output_items=20,
            )
        ),
        service=SimpleNamespace(change_intelligence_snapshot=lambda: snapshot),
        semantic_engine=lambda: semantic,
        operations_agent=lambda: (_ for _ in ()).throw(
            AssertionError("change provider must not hydrate every operations domain")
        ),
    )

    change = _fabric_change_intelligence(runtime)

    assert change is not None
    assert change.freshness == "2026-09-10T00:00:00Z"


def test_resource_health_discovers_container_apps(
    monkeypatch,
    tmp_path,
) -> None:
    home = tmp_path / "aiops-local"
    seed_local_environment(root=home, fixture="tests/fixtures/mock_arg_responses.json")
    monkeypatch.setenv("AIOPS_HOME", str(home))
    monkeypatch.setenv("AIOPS_API_AUTH", "token")
    monkeypatch.setenv("AIOPS_API_TOKENS", TOKENS)
    monkeypatch.setenv("AIOPS_RUNTIME_MODE", "demo")
    captured_queries: dict[str, str] = {}

    def query(_self, spec, *, subscription_ids):
        assert subscription_ids == [DEFAULT_LOCAL_SUBSCRIPTION_ID]
        captured_queries[spec.name] = spec.query
        return type(
            "Observation",
            (),
            {"rows": (), "observed_at": "2026-09-12T00:00:00Z"},
        )()

    context = build_context()
    assert context.hybrid_resource_health_provider is not None
    monkeypatch.setattr(
        runtime_module.ConnectionScopedLiveResourceProvider,
        "query",
        query,
    )

    service = context.hybrid_resource_health_provider(
        [DEFAULT_LOCAL_SUBSCRIPTION_ID]
    )
    service.snapshot(subscription_ids=[DEFAULT_LOCAL_SUBSCRIPTION_ID])

    assert "'microsoft.app/containerapps'" in captured_queries["live_compute_resources"]


def test_hybrid_vulnerability_does_not_require_deferred_semantic_graph(
    monkeypatch,
) -> None:
    monkeypatch.setenv("AIOPS_API_AUTH", "token")
    monkeypatch.setenv("AIOPS_API_TOKENS", TOKENS)
    _hybrid_network_cache.clear()
    _hybrid_vulnerability_cache.clear()
    captured: dict[str, object] = {}
    expected = object()
    clock = [1_000.0]
    build_calls = 0

    def query(_self, _spec, *, subscription_ids):
        assert subscription_ids == [DEFAULT_LOCAL_SUBSCRIPTION_ID]
        return type(
            "Observation",
            (),
            {
                "rows": (),
                "observed_at": "2026-09-08T00:00:00Z",
                "completeness": "complete",
            },
        )()

    def live_vulnerability(_provider, **kwargs):
        nonlocal build_calls
        build_calls += 1
        clock[0] = 1_045.0
        captured["semantic"] = kwargs["semantic"]
        return expected

    context = build_context()
    monkeypatch.setattr(runtime_module.time, "time", lambda: clock[0])
    assert context.hybrid_vulnerability_provider is not None
    monkeypatch.setattr(
        runtime_module.ConnectionScopedLiveResourceProvider,
        "query",
        query,
    )
    monkeypatch.setattr(
        runtime_module,
        "live_vulnerability_service",
        live_vulnerability,
    )

    resolved = context.hybrid_vulnerability_provider(
        [DEFAULT_LOCAL_SUBSCRIPTION_ID]
    )
    clock[0] = 1_050.0
    repeated = context.hybrid_vulnerability_provider(
        [DEFAULT_LOCAL_SUBSCRIPTION_ID]
    )

    assert resolved is repeated is expected
    assert build_calls == 1
    assert len(_hybrid_vulnerability_cache) == 1
    (cache_key, (cached_at, cached_service)), = _hybrid_vulnerability_cache.items()
    assert cache_key[:2] == (
        str(runtime_module.aiops_home()),
        (DEFAULT_LOCAL_SUBSCRIPTION_ID,),
    )
    assert len(cache_key) == 3
    assert cached_at == 1_045.0
    assert cached_service is expected
    assert captured["semantic"] is None


def test_exposure_generation_window_reports_unavailable_without_a_generation(
    monkeypatch,
) -> None:
    import api.runtime as runtime_module

    class _EmptyDocumentStore:
        def __init__(self, root: str) -> None:
            del root

        def read(self, name: str) -> dict:
            del name
            return {}

    monkeypatch.setattr(runtime_module, "OneLakeDocumentStore", _EmptyDocumentStore)
    monkeypatch.setattr(runtime_module, "_load_exposure_read_port", lambda: None)

    with pytest.raises(
        ExposureQueryUnavailableError,
        match="Exposure readable generation is unavailable",
    ):
        _exposure_generation_window()


def test_exposure_query_provider_requires_validated_sql_reader() -> None:
    runtime = SimpleNamespace(service=SimpleNamespace(sql_reader=None))

    with pytest.raises(
        RuntimeError,
        match="Fabric SQL Exposure reader is unavailable",
    ):
        _fabric_exposure_query_service(runtime, object())


def test_exposure_query_provider_probes_sql_reader_before_publication() -> None:
    class _Reader:
        def query(
            self,
            _sql: str,
            _parameters: tuple[object, ...] = (),
            *,
            max_rows: int | None = None,
        ) -> list[dict[str, object]]:
            assert max_rows == 1
            raise OSError("Fabric SQL unavailable")

    runtime = SimpleNamespace(service=SimpleNamespace(sql_reader=_Reader()))

    with pytest.raises(OSError, match="Fabric SQL unavailable"):
        _fabric_exposure_query_service(runtime, object())

def test_exposure_query_uses_explicit_sql_endpoint_without_fabric_rest(
    monkeypatch,
) -> None:
    import api.runtime as runtime_module

    reader = object()
    service = object()
    captured: dict[str, object] = {}
    monkeypatch.setenv(
        "AIOPS_FABRIC_CONFIG",
        str(Path("fabric.config.deploy.yaml").resolve()),
    )
    monkeypatch.setattr(runtime_module, "build_credential", lambda _auth: object())

    def build_reader(endpoint, _credential, *, endpoint_source):
        assert endpoint_source == "deployment_config"
        captured.update(endpoint)
        return reader

    monkeypatch.setattr(runtime_module, "require_exposure_ready", build_reader)
    monkeypatch.setattr(
        runtime_module,
        "_exposure_query_service_from_reader",
        lambda actual_reader, _onboarding: (
            service if actual_reader is reader else None
        ),
    )

    result = runtime_module._fabric_exposure_query_from_config(
        object(),
        lambda: (_ for _ in ()).throw(
            AssertionError("Fabric REST runtime must not be constructed")
        ),
    )

    assert result is service
    assert captured == {
        "server": (
            "a4y4r76a7qxe3b4y2wbnunsqly-u6gteheqetoerg5g32gb6mzxky"
            ".datawarehouse.fabric.microsoft.com"
        ),
        "database": "b4089445-1001-45a6-a0ea-2b4a0851eace",
        "schema": "dbo",
    }


def test_exposure_query_explicit_endpoint_honors_rollback_mode(
    monkeypatch,
    tmp_path,
) -> None:
    import api.runtime as runtime_module

    config = tmp_path / "fabric.yaml"
    config.write_text(
        """
fabric:
  workspace_name: workspace
  lakehouse_name: lakehouse
  sql_endpoint:
    server: server.datawarehouse.fabric.microsoft.com
    database: database
    schema: dbo
  exposure:
    enabled: true
    adapter: fabric_sql
    rollback_mode: true
"""
    )
    monkeypatch.setenv("AIOPS_FABRIC_CONFIG", str(config))
    monkeypatch.setattr(runtime_module, "_fabric_is_configured", lambda: True)
    monkeypatch.setattr(
        runtime_module,
        "_fabric_runtime_from_environment",
        lambda: (_ for _ in ()).throw(
            AssertionError("disabled rollback provider must not construct Fabric")
        ),
    )

    providers = runtime_module._build_provider_runtime(object())

    assert providers.specs["exposure_query"].configured is False
    assert providers.specs["exposure_query"].required is False
    health = providers.refresh(force=True)
    assert health["providers"]["exposure_query"]["state"] == "disabled"
    assert health["readiness"] == "ready"


def test_exposure_query_failure_blocks_process_readiness(
    monkeypatch,
) -> None:
    import api.runtime as runtime_module

    monkeypatch.setenv(
        "AIOPS_FABRIC_CONFIG",
        str(Path("fabric.config.deploy.yaml").resolve()),
    )
    monkeypatch.setattr(runtime_module, "_fabric_is_configured", lambda: True)
    monkeypatch.setattr(
        runtime_module,
        "require_exposure_ready",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ConnectionError("Fabric SQL unavailable")
        ),
    )

    providers = runtime_module._build_provider_runtime(object())
    health = providers.refresh(force=True)

    assert providers.specs["exposure_query"].required is True
    assert health["providers"]["exposure_query"]["state"] == "unavailable"
    assert health["readiness"] == "degraded"


def test_exposure_query_provider_defers_readable_generation_to_gold_queries(
    monkeypatch,
) -> None:
    import api.runtime as runtime_module

    monkeypatch.setenv("EXPOSURE_CURSOR_ACTIVE_KID", "test-active")
    monkeypatch.setenv("EXPOSURE_CURSOR_ACTIVE_KEY", "a" * 32)

    class _Reader:
        def query(
            self,
            _sql: str,
            _parameters: tuple[object, ...] = (),
            *,
            max_rows: int | None = None,
        ) -> list[dict[str, int]]:
            assert max_rows == 1
            return [{"probe": 1}]

    monkeypatch.setattr(
        runtime_module,
        "_exposure_generation_window",
        lambda: (_ for _ in ()).throw(
            ExposureQueryUnavailableError(
                "Exposure readable generation is unavailable"
            )
        ),
    )
    runtime = SimpleNamespace(service=SimpleNamespace(sql_reader=_Reader()))

    service = _fabric_exposure_query_service(runtime, object())

    assert service is not None


def test_exposure_generation_window_reads_api_home_pointer(
    monkeypatch,
    tmp_path,
) -> None:
    from fabric_pipelines.vulnerability_pipeline import (
        EXPOSURE_GOLD_POINTER_DOCUMENT,
    )
    from storage.onelake_documents import OneLakeDocumentStore

    monkeypatch.setenv("AIOPS_HOME", str(tmp_path))
    OneLakeDocumentStore(tmp_path).write(
        EXPOSURE_GOLD_POINTER_DOCUMENT,
        {
            "readable_generation_id": "exposure-gold-7",
            "retained_generations": {
                "exposure-gold-6": {
                    "retain_until": "2026-09-15T00:00:00+00:00"
                }
            },
        },
        expected_revision=0,
    )

    window = _exposure_generation_window()

    assert window.active_generation == "exposure-gold-7"
    assert set(window.retained_generations) == {"exposure-gold-6"}


def test_fabric_providers_share_generation_cache_key_without_snapshot_preflight(
    monkeypatch,
) -> None:
    import api.runtime as runtime_module

    class _Service:
        def semantic_version(self) -> str:
            return "semantic-generation-7"

        def semantic_snapshot(self) -> dict:
            raise AssertionError("provider wrapper must not pre-read the full snapshot")

    class _Runtime:
        service = _Service()

        def semantic_engine(self) -> object:
            return type(
                "_Semantic",
                (),
                {
                    "freshness": "2026-09-08T00:00:00Z",
                    "knowledge_version": "semantic-generation-7",
                },
            )()

    class _PolicyStore:
        def revision_or_raise(self) -> int:
            return 11

    monkeypatch.setattr(runtime_module, "_fabric_is_configured", lambda: True)
    monkeypatch.setattr(
        runtime_module,
        "_fabric_runtime_from_environment",
        lambda: _Runtime(),
    )
    monkeypatch.setattr(runtime_module, "_network_policy_store", _PolicyStore)

    providers = _build_provider_runtime(object())
    semantic = providers.specs["semantic"].loader()

    assert isinstance(semantic, ProviderValue)
    assert semantic.ontology_version == "semantic-generation-7"
    assert providers.specs["exposure_query"].required is True
    assert providers.specs["exposure_read_port"].required is False
    assert providers.specs["remediation_catalog"].required is False
    assert providers.specs["remediation"].required is False
    initial_health = providers.health(refresh=False)
    for name in (
        "exposure_query",
        "change",
        "vulnerability",
        "inventory",
        "inventory_read_port",
    ):
        assert initial_health["providers"][name]["state"] == LOADING
        assert providers.specs[name].scheduled is True
    for name in (
        "semantic",
        "semantic_graph",
        "network",
        "incidents",
        "remediation",
        "remediation_catalog",
        "patching",
    ):
        assert initial_health["providers"][name]["state"] == DEFERRED
        assert providers.specs[name].scheduled is False
    assert providers.specs["exposure_query"].cache_key is None
    assert providers.specs["exposure_query"].scheduled is True
    assert providers.specs["exposure_read_port"].scheduled is True
    assert providers.specs["exposure_query"].cache_key is None
    for name in (
        "semantic",
        "semantic_graph",
        "vulnerability",
        "incidents",
        "remediation_catalog",
        "remediation",
        "change",
    ):
        assert providers.specs[name].cache_key is not None
        assert providers.specs[name].cache_key() == (
            "fabric-generation",
            "semantic-generation-7",
        )
    assert providers.specs["network"].cache_key is not None
    assert providers.specs["network"].cache_key() == (
        "fabric-generation",
        "semantic-generation-7",
        "network-policy",
        11,
    )


def test_fabric_inventory_runtime_reuses_one_generation_for_the_read_port(
    monkeypatch,
) -> None:
    generation = {"value": "semantic-generation-7"}

    class _Service:
        def semantic_version(self) -> str:
            return generation["value"]

    class _Runtime:
        service = _Service()

    inventory = SimpleNamespace(
        freshness="2026-09-12T00:00:00Z",
        knowledge_version="inventory-v1",
    )
    load_calls = {"count": 0}

    def load_inventory():
        load_calls["count"] += 1
        return inventory

    monkeypatch.setattr(runtime_module, "_fabric_is_configured", lambda: True)
    monkeypatch.setattr(
        runtime_module,
        "_fabric_runtime_from_environment",
        lambda: _Runtime(),
    )
    monkeypatch.setattr(runtime_module, "_load_inventory_service", load_inventory)

    providers = _build_provider_runtime(object())
    now = datetime(2026, 9, 12, tzinfo=UTC)
    providers._refresh_provider(
        "inventory",
        providers.specs["inventory"],
        now=now,
        now_iso="2026-09-12T00:00:00Z",
        force=True,
    )
    providers._refresh_provider(
        "inventory_read_port",
        providers.specs["inventory_read_port"],
        now=now,
        now_iso="2026-09-12T00:00:00Z",
        force=True,
    )

    assert load_calls["count"] == 1
    assert providers.get("inventory") is inventory
    assert providers.get("inventory_read_port").service is inventory

    providers._refresh_provider(
        "inventory",
        providers.specs["inventory"],
        now=now,
        now_iso="2026-09-12T00:00:30Z",
        force=False,
    )
    assert load_calls["count"] == 1

    generation["value"] = "semantic-generation-8"
    providers._refresh_provider(
        "inventory",
        providers.specs["inventory"],
        now=now,
        now_iso="2026-09-12T00:01:00Z",
        force=False,
    )
    assert load_calls["count"] == 2


def test_fabric_runtime_shares_semantic_engine_with_graph_provider(
) -> None:
    from fabric.runtime import FabricRuntime

    class Service:
        semantic_snapshot_calls = 0
        semantic_graph_snapshot_calls = 0

        def semantic_version(self) -> str:
            return "semantic-generation-7"

        def semantic_snapshot(self) -> dict:
            self.semantic_snapshot_calls += 1
            return {
                "entities": [],
                "relationships": [],
                "inventory": [],
                "compliance": [],
                "security": [],
                "cost": [],
                "knowledge_version": "semantic-generation-7",
                "freshness": "2026-09-10T00:00:00Z",
                "ontology_synchronized_at": "2026-09-10T00:00:00Z",
            }

        def semantic_graph_snapshot(self) -> dict:
            self.semantic_graph_snapshot_calls += 1
            raise AssertionError("graph provider must not rebuild the shared graph")

    service = Service()
    runtime = FabricRuntime(
        config=None,  # type: ignore[arg-type]
        workspace={},
        lakehouse={},
        service=service,  # type: ignore[arg-type]
    )

    semantic = runtime.semantic_engine()
    semantic.indexes.inventory["resource-1"] = {"status": "running"}
    semantic.indexes.compliance["resource-1"] = {"compliant": True}
    semantic.indexes.security["resource-1"].append({"severity": "High"})
    semantic.indexes.cost["resource-1"].append({"cost": 1.0})
    graph = runtime.semantic_graph_engine()

    assert graph is not semantic
    assert graph.indexes.entities is semantic.indexes.entities
    assert graph.indexes.relationships is semantic.indexes.relationships
    assert semantic.indexes.inventory
    assert semantic.indexes.compliance
    assert semantic.indexes.security
    assert semantic.indexes.cost
    assert graph.indexes.inventory == {}
    assert graph.indexes.compliance == {}
    assert dict(graph.indexes.security) == {}
    assert dict(graph.indexes.cost) == {}
    assert runtime.semantic_graph_engine() is graph
    assert service.semantic_snapshot_calls == 1
    assert service.semantic_graph_snapshot_calls == 0


def test_fabric_remediation_provider_rejects_empty_governed_catalog() -> None:
    planner = SimpleNamespace(
        opportunities=SimpleNamespace(catalog=[]),
        generator=SimpleNamespace(
            approvals=SimpleNamespace(policies=[])
        ),
    )
    runtime = SimpleNamespace(
        operations_agent=lambda: SimpleNamespace(remediation_planner=planner)
    )

    with pytest.raises(RuntimeError, match="Governed remediation catalog is empty"):
        _fabric_remediation_planner(runtime)


def test_fabric_remediation_provider_accepts_complete_governed_catalog(
    monkeypatch,
) -> None:
    import api.runtime as runtime_module

    planner = SimpleNamespace(
        opportunities=SimpleNamespace(catalog=[{"action_id": "action"}]),
        generator=SimpleNamespace(
            approvals=SimpleNamespace(policies=[{"policy_id": "policy"}])
        ),
    )
    runtime = SimpleNamespace(
        operations_agent=lambda: SimpleNamespace(remediation_planner=planner)
    )
    monkeypatch.setattr(
        runtime_module,
        "_attach_defender_correlator",
        lambda candidate, _runtime: candidate,
    )

    assert _fabric_remediation_planner(runtime) is planner


def test_fabric_remediation_catalog_readiness_is_lightweight() -> None:
    runtime = SimpleNamespace(
        service=SimpleNamespace(
            remediation_planning_snapshot=lambda: {
                "inventory": [],
                "action_catalog": [{"action_id": "action"}],
                "approval_policies": [{"policy_id": "policy"}],
            }
        )
    )

    assert _fabric_remediation_catalog(runtime) == {
        "action_count": 1,
        "policy_count": 1,
    }


def test_fabric_remediation_catalog_readiness_rejects_empty_tables() -> None:
    runtime = SimpleNamespace(
        service=SimpleNamespace(
            remediation_planning_snapshot=lambda: {
                "inventory": [],
                "action_catalog": [],
                "approval_policies": [],
            }
        )
    )

    with pytest.raises(RuntimeError, match="Governed remediation catalog is empty"):
        _fabric_remediation_catalog(runtime)


def test_disabled_fabric_remediation_is_not_required(
    monkeypatch, tmp_path
) -> None:
    import api.runtime as runtime_module

    config = tmp_path / "fabric.yaml"
    config.write_text(
        """
fabric:
  auth:
    mode: managed_identity
  workspace_id: test-workspace
  lakehouse_id: test-lakehouse
  remediation: false
"""
    )
    monkeypatch.setenv("AIOPS_FABRIC_CONFIG", str(config))
    monkeypatch.setattr(runtime_module, "_fabric_is_configured", lambda: True)

    providers = _build_provider_runtime(object())

    assert providers.specs["remediation"].configured is False
    assert providers.specs["remediation"].required is False
    assert providers.specs["remediation_catalog"].configured is False
    assert providers.specs["remediation_catalog"].required is False


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


def test_subscription_operations_resolve_each_selected_connection_without_reuse(
    monkeypatch,
) -> None:
    connections = [
        SubscriptionConnection(
            connection_id=f"conn-{suffix}",
            name=f"Connection {suffix}",
            tenant_id=f"tenant-{suffix}",
            subscription_id=f"sub-{suffix}",
            credential=CredentialReference(
                credential_id=f"credential-{suffix}",
                tenant_id=f"tenant-{suffix}",
                client_id=f"client-{suffix}",
                secret_ref=f"env://SECRET_{suffix}",
            ),
        )
        for suffix in ("A", "B")
    ]
    built_credentials: list[object] = []

    def credential_factory(**kwargs):
        credential = SimpleNamespace(client_id=kwargs["client_id"])
        built_credentials.append(credential)
        return credential

    onboarding = SimpleNamespace(
        registry=SimpleNamespace(
            list=lambda *, include_disabled=False: list(connections)
        ),
        resolver=CredentialResolver(
            provider=EnvironmentSecretProvider(
                env={"SECRET_A": "secret-a", "SECRET_B": "secret-b"}
            ),
            credential_factory=credential_factory,
        ),
    )
    observed: dict[str, list[str]] = {
        "patch": [],
        "defender": [],
        "verification": [],
    }

    class PatchAdapter:
        def __init__(self, credential) -> None:
            self.credential = credential

        def submit(self, _run, _target):
            observed["patch"].append(self.credential.client_id)
            return object()

    class DefenderAdapter:
        def __init__(self, credential) -> None:
            self.credential = credential

        def inspect(self, _request):
            observed["defender"].append(self.credential.client_id)
            return {}

        def submit(self, _snapshot):
            observed["defender"].append(self.credential.client_id)
            return object()

    class Verifier:
        def __init__(self, *, credential) -> None:
            self.credential = credential

        def verify(self, _record):
            observed["verification"].append(self.credential.client_id)
            return {"verifiable": True}

    monkeypatch.setenv("AIOPS_PATCH_EXECUTION", "azure")
    monkeypatch.setenv("AIOPS_DEFENDER_CONFIGURATION_EXECUTION", "azure")
    monkeypatch.setattr(
        "operations.patching.azure_adapter.AzureArmPatchExecutionAdapter",
        PatchAdapter,
    )
    monkeypatch.setattr(
        runtime_module, "AzureArmDefenderConfigurationAdapter", DefenderAdapter
    )
    monkeypatch.setattr(runtime_module, "ExecutionVerifier", Verifier)

    patch_adapter = _patch_execution_adapter(onboarding)
    defender_adapter = _defender_configuration_adapter(onboarding)
    verifier = _execution_verifier(onboarding)
    assert verifier is not None

    for suffix in ("A", "B"):
        target = SimpleNamespace(
            subscription_id=f"sub-{suffix}",
            subscription_connection=f"conn-{suffix}",
        )
        patch_adapter.submit(object(), target)
        defender_adapter.inspect(
            {
                "path": (
                    f"/subscriptions/sub-{suffix}/providers/"
                    "Microsoft.Security/pricings/virtualMachines"
                )
            }
        )
        verifier.verify(
            {
                "scope_attributes": {
                    "subscription": f"sub-{suffix}",
                    "subscription_connection": f"conn-{suffix}",
                },
                "provider_job_id": (
                    f"https://management.azure.com/subscriptions/sub-{suffix}/"
                    "providers/Microsoft.Compute/operations/op"
                ),
            }
        )

    assert observed == {
        "patch": ["client-A", "client-B"],
        "defender": ["client-A", "client-B"],
        "verification": ["client-A", "client-B"],
    }
    assert len({id(credential) for credential in built_credentials}) == 6


def test_subscription_operation_credential_resolution_preserves_request_scope(
    monkeypatch,
) -> None:
    connection = SubscriptionConnection(
        connection_id="conn-a",
        name="Connection A",
        tenant_id="tenant-a",
        subscription_id="sub-a",
        credential=CredentialReference(
            credential_id="credential-a",
            tenant_id="tenant-a",
            client_id="client-a",
            secret_ref="env://SECRET_A",
        ),
    )
    credential_builds: list[str] = []
    onboarding = SimpleNamespace(
        registry=SimpleNamespace(
            list=lambda *, include_disabled=False: [connection]
        ),
        resolver=CredentialResolver(
            provider=EnvironmentSecretProvider(env={"SECRET_A": "secret-a"}),
            credential_factory=lambda **kwargs: credential_builds.append(
                kwargs["client_id"]
            )
            or object(),
        ),
    )
    monkeypatch.setenv("AIOPS_PATCH_EXECUTION", "azure")
    adapter = _patch_execution_adapter(
        onboarding,
        Scope.from_mapping({"subscription": ["sub-a"]}),
    )

    with pytest.raises(
        runtime_module.PatchExecutionUnavailable,
        match="outside the authorized scope",
    ):
        adapter.submit(
            object(),
            SimpleNamespace(
                subscription_id="sub-b",
                subscription_connection="conn-b",
            ),
        )

    assert credential_builds == []


def test_network_page_connection_scope_reaches_selected_connection_factory(
    monkeypatch,
    tmp_path,
) -> None:
    home = tmp_path / "aiops"
    registry = ConnectionRegistry(home)
    for suffix in ("a", "b"):
        registry.add(
            SubscriptionConnection(
                connection_id=f"conn-{suffix}",
                name=f"Connection {suffix}",
                tenant_id=f"tenant-{suffix}",
                subscription_id=f"sub-{suffix}",
                credential=CredentialReference(
                    credential_id=f"credential-{suffix}",
                    tenant_id=f"tenant-{suffix}",
                    client_id=f"client-{suffix}",
                    secret_ref=f"env://SECRET_{suffix.upper()}",
                ),
            )
        )
    selected_connections: list[str] = []

    class Reader:
        def query(self, _spec, scope_ids):
            assert scope_ids == ["sub-b"]
            return []

    def build_reader(_config, connection, _resolver):
        selected_connections.append(connection.connection_id)
        return Reader()

    monkeypatch.setenv("AIOPS_HOME", str(home))
    monkeypatch.setenv("AIOPS_API_AUTH", "token")
    monkeypatch.setenv("AIOPS_API_TOKENS", TOKENS)
    monkeypatch.setattr(runtime_module, "build_connection_arg_client", build_reader)
    _hybrid_network_cache.clear()
    client = TestClient(create_app(build_context()), raise_server_exceptions=False)

    response = client.get(
        "/api/v1/network/topology",
        params={
            "detail": "summary",
            "subscription_connection": "conn-b",
        },
        headers={"Authorization": "Bearer demo-token-0123456789abcdef"},
    )

    assert response.status_code == 200, response.text
    assert selected_connections == ["conn-b"]


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
    assert context.provider_runtime is not None
    context.provider_runtime.refresh(force=True)
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


def test_governance_snapshot_reuses_one_projection_within_snapshot_ttl(
    monkeypatch,
) -> None:
    _governance_snapshot_cache.clear()
    build_calls = 0
    expected = runtime_module.GovernanceSnapshot(
        [],
        generation_available=False,
    )

    def build(_scope):
        nonlocal build_calls
        build_calls += 1
        return expected

    monkeypatch.setattr(
        runtime_module,
        "_build_governance_generation_snapshot",
        build,
    )
    monkeypatch.setattr(runtime_module, "_governance_connections", list)
    monkeypatch.setattr(runtime_module.time, "time", lambda: 1_000.0)

    first = runtime_module._load_governance_generation_snapshot(
        Scope.unrestricted()
    )
    second = runtime_module._load_governance_generation_snapshot(
        Scope.unrestricted()
    )

    assert first is second is expected
    assert build_calls == 1


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


def test_hybrid_network_cache_starts_ttl_after_slow_arg_query(
    monkeypatch,
) -> None:
    import api.runtime as runtime_module

    monkeypatch.setenv("AIOPS_API_AUTH", "token")
    monkeypatch.setenv("AIOPS_API_TOKENS", TOKENS)
    _hybrid_network_cache.clear()
    clock = [1_000.0]
    query_calls = 0

    def query(_self, _spec, *, subscription_ids):
        nonlocal query_calls
        query_calls += 1
        assert subscription_ids == [DEFAULT_LOCAL_SUBSCRIPTION_ID]
        clock[0] = 1_045.0
        return type(
            "Observation",
            (),
            {
                "rows": (),
                "observed_at": "2026-09-08T00:00:00Z",
                "completeness": "healthy-empty",
            },
        )()

    context = build_context()
    assert context.hybrid_network_provider is not None

    monkeypatch.setattr(runtime_module.time, "time", lambda: clock[0])
    monkeypatch.setattr(
        runtime_module.ConnectionScopedLiveResourceProvider,
        "query",
        query,
    )

    context.hybrid_network_provider([DEFAULT_LOCAL_SUBSCRIPTION_ID])
    clock[0] = 1_200.0
    context.hybrid_network_provider([DEFAULT_LOCAL_SUBSCRIPTION_ID])

    assert _HYBRID_NETWORK_CACHE_TTL_SECONDS >= 300
    assert query_calls == 1


@pytest.mark.parametrize("completeness", ["partial", "unavailable"])
def test_hybrid_network_rejects_incomplete_live_observations(
    monkeypatch,
    completeness,
) -> None:
    import api.runtime as runtime_module

    monkeypatch.setenv("AIOPS_API_AUTH", "token")
    monkeypatch.setenv("AIOPS_API_TOKENS", TOKENS)
    _hybrid_network_cache.clear()
    context = build_context()
    assert context.hybrid_network_provider is not None

    monkeypatch.setattr(
        runtime_module.ConnectionScopedLiveResourceProvider,
        "query",
        lambda *_args, **_kwargs: type(
            "Observation",
            (),
            {"rows": (), "observed_at": "", "completeness": completeness},
        )(),
    )

    with pytest.raises(RuntimeError, match="observations are incomplete"):
        context.hybrid_network_provider([DEFAULT_LOCAL_SUBSCRIPTION_ID])


def test_live_network_rows_receive_subscription_business_context() -> None:
    subscription_id = "11111111-1111-1111-1111-111111111111"
    resource_id = (
        f"/subscriptions/{subscription_id}/resourceGroups/rg/providers/"
        "Microsoft.Network/virtualNetworks/prod"
    )

    service = NetworkIntelligenceService.from_arg_rows(
        [
            {
                "id": resource_id,
                "name": "prod",
                "type": "microsoft.network/virtualnetworks",
                "subscriptionId": subscription_id,
                "resourceGroup": "rg",
                "properties": {},
            }
        ],
        observed_at="2026-09-12T00:00:00Z",
        connection_context={
            subscription_id: {
                "subscription_connection": "prod-core",
                "environment": "production",
                "business_service": "payments",
                "application": "checkout",
                "owner": "platform",
            }
        },
    )

    vnet = service.snapshot.vnets[0]
    assert vnet.connection_id == "prod-core"
    assert vnet.environment == "production"
    assert vnet.business_service == "payments"
    assert vnet.application == "checkout"
    assert vnet.owner == "platform"


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
    cache_key = next(
        key
        for key in _hybrid_remediation_cache
        if key[:2] == (str(aiops_home()), tuple(subscription_ids))
    )
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
