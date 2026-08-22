"""Administrator-only platform configuration routes."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter
from pydantic import Field, field_validator

from onboarding.credentials import KeyVaultSecretWriter, SecretStorageError

from ..dependencies import Context, WritePrincipal
from ..errors import ApiError, ErrorCode
from ..evidence import Evidence, envelope
from ..models import ApiModel

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

_SECRET_FIELDS = {
    "entra_web_client_id": "hermes-entra-web-client-id",
    "entra_tenant_id": "hermes-entra-tenant-id",
    "entra_api_audience": "hermes-entra-api-audience",
    "entra_api_scope": "hermes-entra-api-scope",
    "entra_grants_json": "hermes-entra-grants-json",
}


class AdminAkvConfigRequest(ApiModel):
    """Entra deployment settings accepted by the administrator form."""

    entra_web_client_id: str = Field(min_length=1, max_length=128)
    entra_tenant_id: str = Field(min_length=1, max_length=128)
    entra_api_audience: str = Field(min_length=1, max_length=512)
    entra_api_scope: str = Field(min_length=1, max_length=512)
    entra_grants_json: str = Field(min_length=2, max_length=32_000)

    @field_validator("entra_web_client_id", "entra_tenant_id")
    @classmethod
    def validate_guid(cls, value: str) -> str:
        import uuid

        try:
            uuid.UUID(value)
        except ValueError as exc:
            raise ValueError("must be a valid UUID") from exc
        return value

    @field_validator("entra_grants_json")
    @classmethod
    def validate_grants(cls, value: str) -> str:
        try:
            payload = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("must be valid JSON") from exc
        if not isinstance(payload, dict) or not payload:
            raise ValueError("must be a non-empty JSON object")
        return value


@router.post("/akv-config", summary="Save Entra configuration to Key Vault")
def save_akv_config(
    payload: AdminAkvConfigRequest,
    context: Context,
    principal: WritePrincipal,
) -> dict[str, Any]:
    """Write deployment settings without ever returning their values."""
    writer = getattr(context.onboarding, "secret_writer", None)
    if not isinstance(writer, KeyVaultSecretWriter):
        raise ApiError(
            ErrorCode.SECRET_UNAVAILABLE,
            "Key Vault configuration writer is not available",
        )

    for field_name, secret_name in _SECRET_FIELDS.items():
        try:
            writer.store_named(
                secret_name=secret_name,
                secret_value=getattr(payload, field_name),
            )
        except SecretStorageError as exc:
            raise ApiError(ErrorCode.SECRET_UNAVAILABLE, str(exc)) from exc

    return envelope(
        {
            "saved": list(_SECRET_FIELDS),
            "secret_names": list(_SECRET_FIELDS.values()),
        },
        evidence=(
            Evidence(
                source_engine="onboarding.credentials.KeyVaultSecretWriter",
                source_table="key_vault",
                confidence="high",
            ),
        ),
        scope={},
    )
