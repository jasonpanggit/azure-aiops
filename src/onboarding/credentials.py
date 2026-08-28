"""Secret-provider abstraction for connection credentials.

Secrets are resolved on demand and never persisted, logged, or serialized.
Every persisted or emitted structure carries only a ``secret_ref`` pointer.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from ontology.subscription_connection import CredentialReference

REDACTED = "***redacted***"

_SENSITIVE_KEY_PATTERN = re.compile(
    r"(secret|password|passwd|client_secret|clientsecret|token|credential_value|api_key|apikey|connection_string)",
    re.IGNORECASE,
)

_KEY_VAULT_REF = re.compile(
    r"^(?:keyvault|akv)://(?P<vault>[^/]+)/secrets/(?P<name>[^/]+)(?:/(?P<version>[^/]+))?$",
    re.IGNORECASE,
)
_KEY_VAULT_NAME = re.compile(r"^[0-9A-Za-z-]{1,127}$")


class SecretNotFoundError(LookupError):
    """Raised when a secret reference cannot be resolved by any provider."""


class SecretStorageError(RuntimeError):
    """Raised when a submitted secret cannot be stored in the configured vault."""


class SecretProvider(Protocol):
    """Resolves an opaque secret reference into a secret value."""

    name: str

    def supports(self, secret_ref: str) -> bool: ...

    def resolve(self, secret_ref: str) -> str: ...


class SecretWriter(Protocol):
    """Stores a secret value and returns the durable reference AIOps should keep."""

    def store(self, *, connection_id: str, secret_value: str) -> str: ...


@dataclass(frozen=True)
class EnvironmentSecretProvider:
    """Resolves ``env://VARNAME`` references for local development."""

    env: Mapping[str, str] | None = None
    name: str = "environment"

    def supports(self, secret_ref: str) -> bool:
        return str(secret_ref or "").casefold().startswith("env://")

    def resolve(self, secret_ref: str) -> str:
        variable = str(secret_ref)[len("env://") :].strip()
        if not variable:
            raise SecretNotFoundError("Environment secret reference is missing a variable name")
        environment = self.env if self.env is not None else os.environ
        value = environment.get(variable)
        if not value:
            raise SecretNotFoundError(
                f"Environment variable {variable} referenced by the connection credential is not set"
            )
        return value


@dataclass(frozen=True)
class KeyVaultSecretWriter:
    """Stores one-time client secrets in Azure Key Vault.

    ``client_factory`` receives the vault name and must return an object with a
    ``set_secret(name, value)`` method, matching the Azure Key Vault SDK shape.
    """

    vault_name: str
    client_factory: Any = None

    def store(self, *, connection_id: str, secret_value: str) -> str:
        vault = str(self.vault_name or "").strip()
        if not vault:
            raise SecretStorageError(
                "No Key Vault name is configured for storing client secrets"
            )
        value = str(secret_value or "")
        if not value:
            raise SecretStorageError("client_secret is required")
        factory = self.client_factory or _secret_client
        secret_name = key_vault_secret_name(connection_id)
        try:
            secret = factory(vault).set_secret(secret_name, value)
        except Exception as exc:
            raise SecretStorageError(
                f"Unable to store client secret in Key Vault {vault!r}"
            ) from exc
        version = _secret_version(secret)
        reference = f"keyvault://{vault}/secrets/{secret_name}"
        return f"{reference}/{version}" if version else reference

    def store_named(self, *, secret_name: str, secret_value: str) -> None:
        """Store an explicitly allowlisted application configuration secret."""
        vault = str(self.vault_name or "").strip()
        name = str(secret_name or "").strip()
        value = str(secret_value or "")
        if not vault:
            raise SecretStorageError("No Key Vault name is configured")
        if not _KEY_VAULT_NAME.fullmatch(name):
            raise SecretStorageError("Invalid Key Vault secret name")
        if not value:
            raise SecretStorageError("Secret value is required")
        try:
            self.client_factory_or_default(vault).set_secret(name, value)
        except Exception as exc:
            raise SecretStorageError(
                f"Unable to store secret {name!r} in Key Vault {vault!r}"
            ) from exc

    def client_factory_or_default(self, vault: str) -> Any:
        """Build the SDK client while keeping the writer injectable in tests."""
        return (self.client_factory or _secret_client)(vault)


@dataclass(frozen=True)
class KeyVaultSecretProvider:
    """Resolves ``keyvault://<vault>/secrets/<name>[/<version>]`` references.

    ``client_factory`` receives the vault name and must return an object with a
    ``get_secret(name, version)`` method, matching the Azure Key Vault SDK shape.
    Kept injectable so no network dependency is required for tests.
    """

    client_factory: Any = None
    name: str = "key_vault"

    def supports(self, secret_ref: str) -> bool:
        return bool(_KEY_VAULT_REF.match(str(secret_ref or "")))

    def resolve(self, secret_ref: str) -> str:
        match = _KEY_VAULT_REF.match(str(secret_ref or ""))
        if not match:
            raise SecretNotFoundError(f"Not a Key Vault secret reference: {redact_reference(secret_ref)}")
        vault = match.group("vault")
        secret_name = match.group("name")
        version = match.group("version")
        factory = self.client_factory or _secret_client
        client = factory(vault)
        secret = client.get_secret(secret_name, version) if version else client.get_secret(secret_name)
        value = getattr(secret, "value", secret)
        if not value:
            raise SecretNotFoundError(
                f"Key Vault secret {redact_reference(secret_ref)} resolved to an empty value"
            )
        return str(value)


@dataclass(frozen=True)
class ChainedSecretProvider:
    """Tries each provider in order and returns the first successful resolution."""

    providers: tuple[SecretProvider, ...] = ()
    name: str = "chained"

    def supports(self, secret_ref: str) -> bool:
        return any(provider.supports(secret_ref) for provider in self.providers)

    def resolve(self, secret_ref: str) -> str:
        errors: list[str] = []
        for provider in self.providers:
            if not provider.supports(secret_ref):
                continue
            try:
                return provider.resolve(secret_ref)
            except SecretNotFoundError as exc:
                errors.append(f"{provider.name}: {exc}")
        detail = "; ".join(errors) if errors else "no provider supports this reference scheme"
        raise SecretNotFoundError(
            f"Unable to resolve secret reference {redact_reference(secret_ref)} ({detail})"
        )


def default_secret_provider(
    env: Mapping[str, str] | None = None,
    key_vault_client_factory: Any = None,
) -> ChainedSecretProvider:
    client_factory = key_vault_client_factory or _secret_client
    return ChainedSecretProvider(
        providers=(
            KeyVaultSecretProvider(client_factory=client_factory),
            EnvironmentSecretProvider(env=env),
        )
    )


class CredentialResolver:
    """Turns a :class:`CredentialReference` into an Azure credential.

    The resolved secret is handed straight to the credential factory and is
    never returned to callers, stored on the resolver, or included in results.
    """

    def __init__(
        self,
        provider: SecretProvider | None = None,
        credential_factory: Any = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self.provider = provider or default_secret_provider(env=env)
        self.credential_factory = credential_factory

    def describe(self, credential: CredentialReference | None) -> dict[str, Any]:
        """Safe, log-ready description of a credential reference."""
        if credential is None:
            return {"configured": False}
        return {
            "configured": True,
            "credential_id": credential.credential_id,
            "kind": credential.kind,
            "client_id": credential.client_id,
            "tenant_id": credential.tenant_id,
            "secret_ref": redact_reference(credential.secret_ref),
            "secret_provider": self._provider_for(credential.secret_ref),
            "expires_at": credential.expires_at,
            "active": credential.active,
        }

    def resolve_secret(self, credential: CredentialReference) -> str:
        if not credential.secret_ref:
            raise SecretNotFoundError(
                f"Credential {credential.credential_id} has no secret_ref configured"
            )
        if not credential.active:
            raise SecretNotFoundError(
                f"Credential {credential.credential_id} is marked inactive"
            )
        return self.provider.resolve(credential.secret_ref)

    def build(self, credential: CredentialReference | None):
        if credential is None:
            raise SecretNotFoundError("Connection has no credential reference configured")
        if credential.kind != "service_principal":
            raise SecretNotFoundError(
                f"Unsupported credential kind '{credential.kind}'; expected service_principal"
            )
        if not credential.tenant_id or not credential.client_id:
            raise SecretNotFoundError(
                f"Credential {credential.credential_id} requires tenant_id and client_id"
            )
        secret = self.resolve_secret(credential)
        factory = self.credential_factory or _client_secret_credential
        return factory(
            tenant_id=credential.tenant_id,
            client_id=credential.client_id,
            client_secret=secret,
        )

    def _provider_for(self, secret_ref: str | None) -> str:
        if not secret_ref:
            return "none"
        if _KEY_VAULT_REF.match(secret_ref):
            return "key_vault"
        if secret_ref.casefold().startswith("env://"):
            return "environment"
        return "unknown"


def _client_secret_credential(*, tenant_id: str, client_id: str, client_secret: str):
    from azure.identity import ClientSecretCredential

    return ClientSecretCredential(
        tenant_id=tenant_id,
        client_id=client_id,
        client_secret=client_secret,
    )


def _secret_client(vault_name: str):
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import SecretClient

    return SecretClient(
        vault_url=f"https://{vault_name}.vault.azure.net",
        credential=DefaultAzureCredential(),
    )


def key_vault_secret_name(connection_id: str) -> str:
    """Build a Key Vault-safe deterministic secret name for a connection."""
    suffix = re.sub(r"[^0-9A-Za-z-]+", "-", str(connection_id or "").strip()).strip("-")
    if not suffix:
        raise SecretStorageError("connection_id is required to name the Key Vault secret")
    return f"aiops-conn-{suffix}"[:127]


def _secret_version(secret: Any) -> str:
    properties = getattr(secret, "properties", None)
    version = getattr(properties, "version", None) if properties is not None else None
    return str(version or getattr(secret, "version", "") or "").strip()


def redact_reference(secret_ref: str | None) -> str | None:
    """Key Vault/env references are pointers, not secrets, so they stay readable."""
    if not secret_ref:
        return None
    text = str(secret_ref).strip()
    if _KEY_VAULT_REF.match(text) or text.casefold().startswith("env://"):
        return text
    return REDACTED


def redact(value: Any) -> Any:
    """Recursively redact any secret-looking value for logs, telemetry, and CLI output."""
    if isinstance(value, Mapping):
        return redact_mapping(value)
    if isinstance(value, (list, tuple)):
        redacted = [redact(item) for item in value]
        return type(value)(redacted) if isinstance(value, tuple) else redacted
    return value


def redact_mapping(payload: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in payload.items():
        if key == "secret_ref":
            result[key] = redact_reference(value if isinstance(value, str) else None)
            continue
        if isinstance(key, str) and _SENSITIVE_KEY_PATTERN.search(key):
            result[key] = REDACTED if value not in (None, "") else value
            continue
        result[key] = redact(value)
    return result


__all__ = [
    "REDACTED",
    "ChainedSecretProvider",
    "CredentialResolver",
    "EnvironmentSecretProvider",
    "KeyVaultSecretProvider",
    "KeyVaultSecretWriter",
    "SecretNotFoundError",
    "SecretProvider",
    "SecretStorageError",
    "SecretWriter",
    "default_secret_provider",
    "key_vault_secret_name",
    "redact",
    "redact_mapping",
    "redact_reference",
]
