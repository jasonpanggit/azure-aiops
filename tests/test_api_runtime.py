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
    HeaderPrincipalAuthenticator,
    StaticTokenAuthenticator,
)
from api.providers import STALE, ProviderRuntime, ProviderSpec
from api.runtime import aiops_home, build_authenticator, build_context
from intelligence.inventory.normalization import normalize_os_inventory
from onboarding.credentials import KeyVaultSecretWriter
from onboarding.local_seed import seed_local_environment
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
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AIOPS_HOME", str(tmp_path / "aiops"))


def test_home_follows_aiops_home(monkeypatch, tmp_path):
    monkeypatch.setenv("AIOPS_HOME", str(tmp_path / "custom"))
    assert aiops_home() == tmp_path / "custom"


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
    assert isinstance(build_authenticator(), HeaderPrincipalAuthenticator)


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
    monkeypatch.setenv("AIOPS_CONNECTION_KEY_VAULT", "kv-aiops-prod")

    context = build_context()

    assert isinstance(context.onboarding.secret_writer, KeyVaultSecretWriter)
    assert context.onboarding.secret_writer.vault_name == "kv-aiops-prod"


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
