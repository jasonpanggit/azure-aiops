from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from onboarding.credentials import (
    ChainedSecretProvider,
    CredentialResolver,
    EnvironmentSecretProvider,
    KeyVaultSecretProvider,
    KeyVaultSecretWriter,
    SecretNotFoundError,
    default_secret_provider,
    redact_mapping,
)
from onboarding.metadata import BusinessMetadata
from onboarding.registry import ConnectionRegistry, DuplicateConnectionError
from onboarding.runtime import build_connection_ingestion
from onboarding.service import OnboardingError, SubscriptionOnboardingService
from onboarding.sync import ConnectionSyncCoordinator
from onboarding.validation import (
    CONNECTION_CHECKS,
    ArgConnectionProbe,
    ConnectionValidator,
)

TENANT = "11111111-1111-1111-1111-111111111111"
SUBSCRIPTION = "22222222-2222-2222-2222-222222222222"
CLIENT = "33333333-3333-3333-3333-333333333333"


class FakeClock:
    def __init__(self, start: datetime | None = None) -> None:
        self.now = start or datetime(2026, 1, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> None:
        self.now = self.now + timedelta(**kwargs)


class FakeProbe:
    def __init__(self, failures: set[str] | None = None, auth_error: str = "") -> None:
        self.failures = failures or set()
        self.auth_error = auth_error
        self.queries: list[str] = []

    def authenticate(self, connection):
        if self.auth_error:
            raise RuntimeError(self.auth_error)
        return "token acquired"

    def query(self, connection, query: str):
        self.queries.append(query)
        for name in self.failures:
            if _query_marker(name) in query:
                raise RuntimeError(f"AuthorizationFailed for {name}")
        return [{"id": "/subscriptions/x/resource"}]


def _query_marker(check: str) -> str:
    return {
        "subscription_reachability": "microsoft.resources/subscriptions",
        "arg_read": "Resources | project id",
        "network_resource_read": "microsoft.network/",
        "patch_update_read": "patchassessmentresources",
        "advisor_read": "advisorresources",
        "resource_changes_read": "resourcechanges",
    }[check]


class FakeIngestion:
    def __init__(self, manifest=None, error: str = "") -> None:
        self.manifest = manifest or {
            "queryVersion": "1.0.0",
            "datasets": {"entities/resource": {"rowCount": 7}},
        }
        self.error = error
        self.calls = 0

    def run(self):
        self.calls += 1
        if self.error:
            raise RuntimeError(self.error)
        return self.manifest


class FakeSecretWriter:
    def __init__(self) -> None:
        self.stored: list[tuple[str, str]] = []

    def store(self, *, connection_id: str, secret_value: str) -> str:
        self.stored.append((connection_id, secret_value))
        return f"keyvault://kv-test/secrets/hermes-conn-{connection_id}/v1"


def build_service(
    tmp_path: Path,
    *,
    probe: FakeProbe | None = None,
    ingestion: FakeIngestion | None = None,
    clock: FakeClock | None = None,
    env: dict[str, str] | None = None,
    secret_writer: FakeSecretWriter | None = None,
) -> SubscriptionOnboardingService:
    the_clock = clock or FakeClock()
    resolver = CredentialResolver(
        provider=EnvironmentSecretProvider(env=env or {"SPN_SECRET": "s3cret"}),
        credential_factory=lambda **kwargs: object(),
    )
    coordinator = ConnectionSyncCoordinator(
        tmp_path,
        ingestion_factory=lambda connection: ingestion or FakeIngestion(),
        clock=the_clock,
    )
    return SubscriptionOnboardingService(
        tmp_path,
        registry=ConnectionRegistry(tmp_path),
        validator=ConnectionValidator(probe=probe or FakeProbe(), clock=the_clock),
        sync_coordinator=coordinator,
        resolver=resolver,
        secret_writer=secret_writer,
        clock=the_clock,
    )


def onboard(service: SubscriptionOnboardingService, **overrides):
    payload = {
        "connection_id": "prod-core",
        "name": "Production Core",
        "tenant_id": TENANT,
        "subscription_id": SUBSCRIPTION,
        "client_id": CLIENT,
        "secret_ref": "env://SPN_SECRET",
    }
    payload.update(overrides)
    return service.add(**payload)


def test_add_registers_connection_without_persisting_secrets(tmp_path: Path) -> None:
    service = build_service(tmp_path)

    detail = onboard(service)

    assert detail["connection_id"] == "prod-core"
    assert detail["subscription_id"] == SUBSCRIPTION
    assert detail["credential"]["secret_ref"] == "env://SPN_SECRET"
    stored = (tmp_path / "state" / "subscription_connections.json").read_text()
    assert "s3cret" not in stored
    assert "env://SPN_SECRET" in stored


def test_add_stores_submitted_client_secret_in_key_vault(tmp_path: Path) -> None:
    writer = FakeSecretWriter()
    service = build_service(tmp_path, secret_writer=writer)

    detail = onboard(service, secret_ref="", client_secret="client-secret-value")

    assert writer.stored == [("prod-core", "client-secret-value")]
    assert (
        detail["credential"]["secret_ref"]
        == "keyvault://kv-test/secrets/hermes-conn-prod-core/v1"
    )
    stored = (tmp_path / "state" / "subscription_connections.json").read_text()
    assert "client-secret-value" not in stored
    assert "keyvault://kv-test/secrets/hermes-conn-prod-core/v1" in stored


def test_add_rejects_secret_ref_and_client_secret_together(tmp_path: Path) -> None:
    service = build_service(tmp_path, secret_writer=FakeSecretWriter())

    with pytest.raises(OnboardingError, match="either secret_ref or client_secret"):
        onboard(service, client_secret="client-secret-value")


def test_add_rejects_duplicate_subscription(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    onboard(service)

    with pytest.raises(DuplicateConnectionError):
        onboard(service, connection_id="prod-core-2")


def test_add_validates_identifiers(tmp_path: Path) -> None:
    service = build_service(tmp_path)

    with pytest.raises(OnboardingError):
        onboard(service, tenant_id="not-a-guid")
    with pytest.raises(OnboardingError):
        onboard(service, connection_id="Bad Id!")


def test_validate_runs_full_check_suite_and_records_health(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    onboard(service)

    report = service.validate("prod-core")

    assert [check["name"] for check in report["checks"]] == list(CONNECTION_CHECKS)
    assert report["passed"] is True
    assert report["status"] == "healthy"
    assert service.detail("prod-core")["health_status"] == "healthy"


def test_validate_reports_partial_permissions_as_degraded(tmp_path: Path) -> None:
    service = build_service(tmp_path, probe=FakeProbe(failures={"advisor_read"}))
    onboard(service)

    report = service.validate("prod-core")

    assert report["passed"] is True
    assert report["status"] == "degraded"
    assert report["failed_optional"] == ["advisor_read"]
    advisor = next(c for c in report["checks"] if c["name"] == "advisor_read")
    assert advisor["remediation"]


def test_validate_fails_and_skips_when_authentication_fails(tmp_path: Path) -> None:
    service = build_service(tmp_path, probe=FakeProbe(auth_error="invalid client secret"))
    onboard(service)

    report = service.validate("prod-core")

    assert report["passed"] is False
    assert report["status"] == "failed"
    assert report["failed_required"] == [
        "spn_authentication",
        "subscription_reachability",
        "arg_read",
    ]
    skipped = [check["name"] for check in report["checks"] if check["skipped"]]
    assert "advisor_read" in skipped


def test_required_arg_read_failure_blocks_connection(tmp_path: Path) -> None:
    service = build_service(tmp_path, probe=FakeProbe(failures={"arg_read"}))
    onboard(service)

    report = service.validate("prod-core")

    assert report["passed"] is False
    assert "arg_read" in report["failed_required"]


def test_map_metadata_creates_environment_and_business_linkage(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    onboard(service)

    detail = service.map_metadata(
        "prod-core",
        BusinessMetadata(
            business_service="Payments",
            application="checkout-api",
            environment="Production",
            project_owner="alice@example.com",
            support_team="payments-sre",
            criticality="Critical",
            region="eastus",
            cost_center="CC-1001",
        ),
    )

    assert detail["business_metadata"]["business_service"] == "Payments"
    assert detail["business_metadata"]["environment"] == "production"
    assert detail["business_metadata"]["criticality"] == "critical"
    assert detail["missing_metadata"] == []
    assert detail["environment_mappings"][0]["environment_name"] == "production"
    linkage = detail["business_service_linkages"][0]
    assert linkage["business_service_id"] == "Payments"
    assert linkage["application_ids"] == ["checkout-api"]


def test_map_metadata_merges_and_rejects_empty(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    onboard(service)
    service.map_metadata("prod-core", {"business_service": "Payments"})

    detail = service.map_metadata("prod-core", {"region": "westus"})

    assert detail["business_metadata"]["business_service"] == "Payments"
    assert detail["business_metadata"]["region"] == "westus"
    with pytest.raises(OnboardingError):
        service.map_metadata("prod-core", {})

def test_list_exposes_scope_option_metadata_without_credentials(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    onboard(
        service,
        metadata=BusinessMetadata(
            business_service="Payments",
            application="checkout-api",
            environment="Production",
            project_owner="alice@example.com",
            support_team="payments-sre",
            criticality="Critical",
            region="eastus",
        ),
    )

    summary = service.list()[0]

    assert summary["business_service"] == "Payments"
    assert summary["application"] == "checkout-api"
    assert summary["environment"] == "production"
    assert summary["owner"] == "alice@example.com"
    assert summary["support_team"] == "payments-sre"
    assert summary["criticality"] == "critical"
    assert summary["region"] == "eastus"
    assert "credential" not in summary


def test_invalid_criticality_is_rejected() -> None:
    with pytest.raises(ValueError):
        BusinessMetadata(criticality="urgent")


def test_sync_records_run_id_and_success_state(tmp_path: Path) -> None:
    ingestion = FakeIngestion()
    service = build_service(tmp_path, ingestion=ingestion)
    onboard(service)

    result = service.sync("prod-core", mode="initial")

    assert result["status"] == "succeeded"
    assert result["run_id"]
    assert result["record_count"] == 7
    assert ingestion.calls == 1
    state = service.detail("prod-core")
    assert state["sync_status"] == "succeeded"
    assert state["last_successful_sync_at"]


def test_failed_sync_preserves_last_successful_sync(tmp_path: Path) -> None:
    clock = FakeClock()
    service = build_service(tmp_path, ingestion=FakeIngestion(), clock=clock)
    onboard(service)
    service.sync("prod-core")
    good = service.detail("prod-core")["last_successful_sync_at"]

    clock.advance(hours=1)
    failing = build_service(
        tmp_path, ingestion=FakeIngestion(error="ARG throttled"), clock=clock
    )
    result = failing.sync("prod-core", mode="scheduled")

    assert result["status"] == "failed"
    assert result["message"] == "ARG throttled"
    assert result["sync_state"]["last_successful_sync_at"] == good
    assert result["sync_state"]["attempts"] == 2
    assert result["health"]["healthy"] is False


def test_disabled_connection_cannot_sync(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    onboard(service)
    service.disable("prod-core")

    with pytest.raises(ValueError):
        service.sync("prod-core")

    assert service.detail("prod-core")["is_active"] is False
    service.enable("prod-core")
    assert service.detail("prod-core")["is_active"] is True


def test_delete_connection_removes_it_from_registry(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    onboard(service)

    deleted = service.delete("prod-core")

    assert deleted["connection_id"] == "prod-core"
    assert service.list() == []
    with pytest.raises(LookupError):
        service.detail("prod-core")


def test_health_reports_stale_data_after_threshold(tmp_path: Path) -> None:
    clock = FakeClock()
    service = build_service(tmp_path, clock=clock)
    onboard(service)
    service.sync("prod-core")

    assert service.health_report("prod-core")["connections"][0]["overall"] == "healthy"

    clock.advance(hours=48)
    report = service.health_report("prod-core")

    summary = report["connections"][0]
    assert summary["overall"] == "stale"
    assert summary["freshness"]["stale"] is True
    assert summary["freshness"]["age_hours"] == 48.0


def test_health_reports_never_synced_connection(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    onboard(service)

    summary = service.health_report()["connections"][0]

    assert summary["overall"] == "unknown"
    assert summary["freshness"]["status"] == "never_synced"


def test_list_filters_disabled_connections(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    onboard(service)
    service.disable("prod-core")

    assert len(service.list()) == 1
    assert service.list(include_disabled=False) == []


def test_sync_uses_connection_scoped_dataset_root(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    onboard(service)

    detail = service.detail("prod-core")

    assert detail["dataset_root"].endswith("connections/prod-core")


def test_arg_connection_probe_uses_connection_client_factory(tmp_path: Path) -> None:
    class ConnectionClient:
        def __init__(self) -> None:
            self.scopes: list[list[str]] = []

        def query(self, _spec, scopes: list[str]) -> list[dict]:
            self.scopes.append(scopes)
            return [{"id": "resource-1"}]

    client = ConnectionClient()
    resolver = CredentialResolver(
        provider=EnvironmentSecretProvider(env={"SPN_SECRET": "s3cret"}),
        credential_factory=lambda **_kwargs: object(),
    )
    service = SubscriptionOnboardingService(
        tmp_path,
        registry=ConnectionRegistry(tmp_path),
        validator=ConnectionValidator(
            probe=ArgConnectionProbe(
                resolver=resolver,
                arg_client_factory=lambda _connection: client,
            )
        ),
        resolver=resolver,
    )
    onboard(service)

    report = service.validate("prod-core", checks=("arg_read",))

    assert report["status"] == "healthy"
    assert client.scopes == [[SUBSCRIPTION]]


def test_update_rotates_credential_reference(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    onboard(service)

    detail = service.update("prod-core", secret_ref="keyvault://kv-prod/secrets/spn")

    assert detail["credential"]["secret_ref"] == "keyvault://kv-prod/secrets/spn"
    assert detail["credential"]["secret_provider"] == "key_vault"


def test_update_stores_rotated_client_secret(tmp_path: Path) -> None:
    writer = FakeSecretWriter()
    service = build_service(tmp_path, secret_writer=writer)
    onboard(service)

    detail = service.update("prod-core", client_secret="rotated-secret")

    assert writer.stored == [("prod-core", "rotated-secret")]
    assert (
        detail["credential"]["secret_ref"]
        == "keyvault://kv-test/secrets/hermes-conn-prod-core/v1"
    )


def test_key_vault_provider_resolves_reference() -> None:
    class Secret:
        value = "from-vault"

    class Client:
        def __init__(self, vault: str) -> None:
            self.vault = vault

        def get_secret(self, name: str, version: str | None = None):
            assert (self.vault, name) == ("kv-prod", "spn")
            return Secret()

    provider = KeyVaultSecretProvider(client_factory=Client)

    assert provider.supports("keyvault://kv-prod/secrets/spn")
    assert provider.resolve("keyvault://kv-prod/secrets/spn") == "from-vault"


def test_default_provider_resolves_key_vault_reference() -> None:
    class Secret:
        value = "from-default-vault"

    class Client:
        def __init__(self, vault: str) -> None:
            self.vault = vault

        def get_secret(self, name: str, version: str | None = None):
            assert (self.vault, name, version) == ("kv-prod", "spn", "v1")
            return Secret()

    provider = default_secret_provider(key_vault_client_factory=Client)

    assert provider.resolve("keyvault://kv-prod/secrets/spn/v1") == "from-default-vault"


def test_key_vault_writer_returns_versioned_reference() -> None:
    class Properties:
        version = "version-1"

    class Secret:
        properties = Properties()

    class Client:
        def __init__(self, vault: str) -> None:
            self.vault = vault

        def set_secret(self, name: str, value: str):
            assert self.vault == "kv-prod"
            assert name == "hermes-conn-prod-core"
            assert value == "from-user"
            return Secret()

    writer = KeyVaultSecretWriter("kv-prod", client_factory=Client)

    assert (
        writer.store(connection_id="prod-core", secret_value="from-user")
        == "keyvault://kv-prod/secrets/hermes-conn-prod-core/version-1"
    )


def test_chained_provider_falls_back_to_environment() -> None:
    provider = ChainedSecretProvider(
        providers=(
            KeyVaultSecretProvider(client_factory=None),
            EnvironmentSecretProvider(env={"VAR": "value"}),
        )
    )

    assert provider.resolve("env://VAR") == "value"
    with pytest.raises(SecretNotFoundError):
        provider.resolve("env://MISSING")


def test_resolver_never_returns_secret_in_description() -> None:
    resolver = CredentialResolver(
        provider=EnvironmentSecretProvider(env={"SPN_SECRET": "s3cret"}),
        credential_factory=lambda **kwargs: kwargs,
    )
    from ontology.subscription_connection import CredentialReference

    reference = CredentialReference(
        credential_id="c1",
        client_id=CLIENT,
        tenant_id=TENANT,
        secret_ref="env://SPN_SECRET",
    )

    described = resolver.describe(reference)

    assert "s3cret" not in str(described)
    assert described["secret_provider"] == "environment"
    assert resolver.build(reference)["client_secret"] == "s3cret"


def test_inactive_credential_cannot_be_resolved() -> None:
    from ontology.subscription_connection import CredentialReference

    resolver = CredentialResolver(provider=EnvironmentSecretProvider(env={"S": "v"}))
    reference = CredentialReference(
        credential_id="c1",
        client_id=CLIENT,
        tenant_id=TENANT,
        secret_ref="env://S",
        active=False,
    )

    with pytest.raises(SecretNotFoundError):
        resolver.resolve_secret(reference)


def test_redaction_masks_sensitive_keys() -> None:
    payload = {
        "client_id": CLIENT,
        "client_secret": "s3cret",
        "password": "hunter2",
        "secret_ref": "env://SPN_SECRET",
        "nested": [{"api_key": "abc"}],
    }

    redacted = redact_mapping(payload)

    assert redacted["client_id"] == CLIENT
    assert redacted["client_secret"] == "***redacted***"
    assert redacted["password"] == "***redacted***"
    assert redacted["secret_ref"] == "env://SPN_SECRET"
    assert redacted["nested"][0]["api_key"] == "***redacted***"


def test_registry_persists_across_instances(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    onboard(service)

    reloaded = ConnectionRegistry(tmp_path).get("prod-core")

    assert reloaded.subscription_id == SUBSCRIPTION
    assert reloaded.credential.secret_ref == "env://SPN_SECRET"
    assert reloaded.scope_key == f"{TENANT}:{SUBSCRIPTION}:prod-core"


def test_connection_ingestion_still_uses_live_arg_client(tmp_path, monkeypatch) -> None:
    from hermes_arg_connector.config import ConnectorConfig

    service = build_service(tmp_path)
    onboard(service)
    connection = ConnectionRegistry(tmp_path).get("prod-core")
    built = []

    class FakeArgClient:
        pass

    monkeypatch.setattr(
        "onboarding.runtime.build_connection_arg_client",
        lambda config, candidate, resolver=None: built.append((config, candidate)) or FakeArgClient(),
    )

    ingestion = build_connection_ingestion(ConnectorConfig(output_dir=tmp_path), connection)

    assert ingestion.source.arg.__class__ is FakeArgClient
    assert ingestion.source.mcp is None
    assert built[0][1] is connection
