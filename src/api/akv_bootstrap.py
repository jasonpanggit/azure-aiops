"""Startup synchronization of explicitly configured values into Key Vault.

This module is intentionally opt-in. Container Apps supplies the values through
secret-backed environment variables, while the user-assigned managed identity
authenticates to Key Vault. Only the ``secret_name -> environment_variable``
mapping in ``AIOPS_AKV_BOOTSTRAP_SECRETS`` is copied; arbitrary environment
variables are never scanned or persisted.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Callable, Mapping
from typing import Any

_LOGGER = logging.getLogger(__name__)
_SECRET_NAME = re.compile(r"^[0-9A-Za-z-]{1,127}$")
_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")


def _client_factory(vault_name: str, managed_identity_client_id: str):
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import SecretClient

    credential = DefaultAzureCredential(
        managed_identity_client_id=managed_identity_client_id or None
    )
    return SecretClient(
        vault_url=f"https://{vault_name}.vault.azure.net",
        credential=credential,
    )


def _load_mapping(raw: str) -> dict[str, str]:
    try:
        payload = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError("AIOPS_AKV_BOOTSTRAP_SECRETS is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise TypeError("AIOPS_AKV_BOOTSTRAP_SECRETS must be a JSON object")

    mapping: dict[str, str] = {}
    for secret_name, environment_name in payload.items():
        if (
            not isinstance(secret_name, str)
            or not _SECRET_NAME.fullmatch(secret_name)
            or not isinstance(environment_name, str)
            or not _ENV_NAME.fullmatch(environment_name)
        ):
            raise RuntimeError(
                "AIOPS_AKV_BOOTSTRAP_SECRETS entries must map a Key Vault-safe "
                "secret name to an uppercase environment variable"
            )
        mapping[secret_name] = environment_name
    return mapping


def sync_secrets(
    *,
    env: Mapping[str, str] | None = None,
    client_factory: Callable[[str, str], Any] | None = None,
) -> int:
    """Copy configured secret-backed environment values into Key Vault.

    Returns the number of secrets created or updated. An enabled sync with a
    missing vault, mapping, or source value raises ``RuntimeError`` so a
    deployment cannot appear healthy while its secret bootstrap failed.
    """

    environment = env if env is not None else os.environ
    enabled = str(environment.get("AIOPS_AKV_BOOTSTRAP_ENABLED", "")).casefold()
    if enabled not in {"1", "true", "yes"}:
        return 0

    vault_name = str(environment.get("AIOPS_CONNECTION_KEY_VAULT", "")).strip()
    if not vault_name:
        raise RuntimeError(
            "AIOPS_AKV_BOOTSTRAP_ENABLED requires AIOPS_CONNECTION_KEY_VAULT"
        )
    mapping = _load_mapping(environment.get("AIOPS_AKV_BOOTSTRAP_SECRETS", "{}"))
    if not mapping:
        raise RuntimeError(
            "AIOPS_AKV_BOOTSTRAP_ENABLED requires at least one configured secret"
        )

    factory = client_factory or _client_factory
    client = factory(vault_name, str(environment.get("AZURE_CLIENT_ID", "")).strip())
    changed = 0
    for secret_name, environment_name in mapping.items():
        value = str(environment.get(environment_name, ""))
        if not value:
            raise RuntimeError(
                f"Configured Key Vault bootstrap source {environment_name} is empty"
            )
        try:
            existing = client.get_secret(secret_name)
            existing_value = str(getattr(existing, "value", existing) or "")
        except Exception as exc:
            if getattr(exc, "status_code", None) == 404 or exc.__class__.__name__ == "ResourceNotFoundError":
                existing_value = ""
            else:
                _LOGGER.warning("key_vault_bootstrap_read_failed secret=%s", secret_name)
                raise RuntimeError(
                    f"Unable to read bootstrap secret {secret_name!r} from Key Vault"
                ) from exc
        if existing_value == value:
            continue
        try:
            client.set_secret(secret_name, value)
        except Exception as exc:
            _LOGGER.warning("key_vault_bootstrap_write_failed secret=%s", secret_name)
            raise RuntimeError(
                f"Unable to write bootstrap secret {secret_name!r} to Key Vault"
            ) from exc
        changed += 1

    _LOGGER.info(
        "key_vault_bootstrap_complete vault=%s configured=%d changed=%d",
        vault_name,
        len(mapping),
        changed,
    )
    return changed


def main() -> None:
    """Run the startup synchronization as a fail-fast process entry point."""

    sync_secrets()


if __name__ == "__main__":  # pragma: no cover - exercised by the container
    main()
