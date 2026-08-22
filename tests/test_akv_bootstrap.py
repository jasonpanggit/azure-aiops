"""Focused tests for managed-identity Key Vault startup synchronization."""

from __future__ import annotations

import pytest

from api.akv_bootstrap import sync_secrets


class Secret:
    def __init__(self, value: str) -> None:
        self.value = value


class Client:
    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values = values or {}
        self.writes: list[tuple[str, str]] = []

    def get_secret(self, name: str):
        if name not in self.values:
            error = RuntimeError("missing")
            error.status_code = 404
            raise error
        return Secret(self.values[name])

    def set_secret(self, name: str, value: str):
        self.writes.append((name, value))
        self.values[name] = value


def test_disabled_bootstrap_is_a_noop():
    assert sync_secrets(env={"HERMES_AKV_BOOTSTRAP_ENABLED": "false"}) == 0


def test_bootstrap_writes_missing_secrets_and_uses_explicit_mapping():
    client = Client()
    env = {
        "HERMES_AKV_BOOTSTRAP_ENABLED": "true",
        "HERMES_CONNECTION_KEY_VAULT": "ops-kv",
        "HERMES_AKV_BOOTSTRAP_SECRETS": '{"api-tokens":"HERMES_API_TOKENS"}',
        "HERMES_API_TOKENS": "opaque-token",
        "AZURE_CLIENT_ID": "managed-identity-id",
    }

    def factory(vault: str, identity: str):
        assert vault == "ops-kv"
        assert identity == "managed-identity-id"
        return client

    assert sync_secrets(env=env, client_factory=factory) == 1
    assert client.writes == [("api-tokens", "opaque-token")]


def test_bootstrap_does_not_create_a_new_version_when_value_is_unchanged():
    client = Client({"api-tokens": "opaque-token"})
    env = {
        "HERMES_AKV_BOOTSTRAP_ENABLED": "true",
        "HERMES_CONNECTION_KEY_VAULT": "ops-kv",
        "HERMES_AKV_BOOTSTRAP_SECRETS": '{"api-tokens":"HERMES_API_TOKENS"}',
        "HERMES_API_TOKENS": "opaque-token",
    }

    assert sync_secrets(env=env, client_factory=lambda _vault, _identity: client) == 0
    assert client.writes == []


def test_enabled_bootstrap_requires_source_values():
    env = {
        "HERMES_AKV_BOOTSTRAP_ENABLED": "true",
        "HERMES_CONNECTION_KEY_VAULT": "ops-kv",
        "HERMES_AKV_BOOTSTRAP_SECRETS": '{"api-tokens":"HERMES_API_TOKENS"}',
    }
    with pytest.raises(RuntimeError, match="source HERMES_API_TOKENS is empty"):
        sync_secrets(env=env, client_factory=lambda _vault, _identity: Client())


def test_bootstrap_rejects_invalid_or_unsafe_mappings():
    base = {
        "HERMES_AKV_BOOTSTRAP_ENABLED": "true",
        "HERMES_CONNECTION_KEY_VAULT": "ops-kv",
        "HERMES_API_TOKENS": "opaque-token",
    }
    with pytest.raises(TypeError, match="must be a JSON object"):
        sync_secrets(
            env={**base, "HERMES_AKV_BOOTSTRAP_SECRETS": "[]"},
            client_factory=lambda _vault, _identity: Client(),
        )
    with pytest.raises(RuntimeError, match="Key Vault-safe"):
        sync_secrets(
            env={**base, "HERMES_AKV_BOOTSTRAP_SECRETS": '{"bad/name":"HERMES_API_TOKENS"}'},
            client_factory=lambda _vault, _identity: Client(),
        )
