from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from azure.identity import ClientSecretCredential, ManagedIdentityCredential


@dataclass(frozen=True)
class FabricAuthConfig:
    mode: str
    tenant_id: str = ""
    client_id: str = ""
    client_secret_env: str = "FABRIC_CLIENT_SECRET"
    managed_identity_client_id: str = ""

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> FabricAuthConfig:
        return cls(
            mode=str(value.get("mode") or "managed_identity"),
            tenant_id=str(value.get("tenant_id") or ""),
            client_id=str(value.get("client_id") or ""),
            client_secret_env=str(value.get("client_secret_env") or "FABRIC_CLIENT_SECRET"),
            managed_identity_client_id=str(value.get("managed_identity_client_id") or ""),
        )


def build_credential(
    config: FabricAuthConfig,
    env: Mapping[str, str] | None = None,
):
    environment = env if env is not None else os.environ
    if config.mode == "service_principal":
        if not config.tenant_id or not config.client_id:
            raise ValueError("Service principal authentication requires tenant_id and client_id")
        secret = environment.get(config.client_secret_env)
        if not secret:
            raise ValueError(
                f"Service principal secret environment variable {config.client_secret_env} is not set"
            )
        return ClientSecretCredential(
            tenant_id=config.tenant_id,
            client_id=config.client_id,
            client_secret=secret,
        )
    if config.mode == "managed_identity":
        options = (
            {"client_id": config.managed_identity_client_id}
            if config.managed_identity_client_id
            else {}
        )
        return ManagedIdentityCredential(**options)
    raise ValueError("Fabric authentication mode must be service_principal or managed_identity")


def build_delta_storage_options(credential) -> dict[str, str]:
    """Create short-lived delta-rs options without exposing client secrets."""
    token = credential.get_token("https://storage.azure.com/.default")
    return {
        "azure_storage_token": token.token,
        "azure_use_fabric_endpoint": "true",
    }
