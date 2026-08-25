"""Request and response DTOs for the Operations API.

These are the stable wire contract the UI codes against. They are deliberately
separate from the ontology/semantic internal shapes so the internal model can
evolve without breaking clients.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .evidence import CONFIDENCE_LEVELS, FRESHNESS_UNKNOWN


class ApiModel(BaseModel):
    """Base for all wire models: reject unknown fields on input."""

    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------
# Envelope
# --------------------------------------------------------------------------


class EvidenceModel(ApiModel):
    source_engine: str = Field(description="Engine that produced the data")
    source_table: str = Field("", description="Backing ontology/Fabric table")
    timestamp: str = Field("", description="When the underlying snapshot was taken")
    subscription_connection: str = Field(
        "", description="Connection the data was ingested through"
    )
    resource_id: str = Field("", description="Subject resource, when singular")
    confidence: str = Field(
        "unknown", description=f"One of: {', '.join(CONFIDENCE_LEVELS)}"
    )
    freshness: str = Field(
        FRESHNESS_UNKNOWN, description="fresh | aging | stale | unknown"
    )


class EnvelopeModel(ApiModel):
    """Every successful response body."""

    data: Any = Field(description="The response payload")
    evidence: list[EvidenceModel] = Field(
        default_factory=list, description="Provenance for the payload"
    )
    scope: dict[str, list[str]] = Field(
        default_factory=dict, description="Effective scope the read was performed under"
    )
    knowledge_version: str = Field("", description="Semantic knowledge version")
    warnings: list[str] = Field(default_factory=list)
    pagination: dict[str, int | None] | None = Field(
        None, description="Offset pagination metadata for collection responses"
    )


class ErrorBody(ApiModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorModel(ApiModel):
    error: ErrorBody


# --------------------------------------------------------------------------
# Subscription connections
# --------------------------------------------------------------------------


class BusinessMetadataModel(ApiModel):
    business_service: str = ""
    application: str = ""
    environment: str = ""
    project_owner: str = ""
    support_team: str = ""
    criticality: str = ""
    region: str = ""
    cost_center: str = ""


class CredentialReferenceModel(ApiModel):
    """Credential payload.

    ``client_secret`` is accepted only as one-time input on create/update. The
    API stores it in Key Vault before handing the connection to Hermes, which
    persists only ``secret_ref``.
    """

    credential_id: str = ""
    kind: str = "service_principal"
    client_id: str = ""
    tenant_id: str = ""
    secret_ref: str = Field(
        "", description="Key Vault or env reference, e.g. kv://vault/secret"
    )
    client_secret: str = Field(
        "", description="One-time SPN secret to store in Key Vault before persistence"
    )


class ConnectionCreateRequest(ApiModel):
    connection_id: str = Field(description="Stable lowercase identifier")
    name: str = Field(description="Human-readable display name")
    tenant_id: str
    subscription_id: str
    credential: CredentialReferenceModel
    metadata: BusinessMetadataModel = Field(default_factory=BusinessMetadataModel)


class ConnectionUpdateRequest(ApiModel):
    name: str | None = None
    credential: CredentialReferenceModel | None = None
    expected_revision: int | None = Field(
        None, description="Optimistic concurrency guard from a prior read"
    )


class ConnectionMetadataRequest(ApiModel):
    metadata: BusinessMetadataModel
    expected_revision: int | None = None


class ConnectionSyncRequest(ApiModel):
    mode: str = Field("manual", description="initial | scheduled | manual")


class ConnectionValidateRequest(ApiModel):
    checks: list[str] | None = Field(
        None, description="Subset of checks to run; omit to run all"
    )


# --------------------------------------------------------------------------
# Search and context
# --------------------------------------------------------------------------


class SearchRequest(ApiModel):
    query: str = Field(min_length=1, max_length=512)


class EOLConfirmationRequest(ApiModel):
    """Bounded operator input for one explicit lifecycle confirmation."""

    normalized_os_key: str = Field(min_length=3, max_length=241)
    expected_revision: int = Field(ge=0)
    candidate_id: str | None = Field(default=None, min_length=3, max_length=80)
    manual_date: date | None = None
    support_channel: Literal["mainstream", "extended"] = "mainstream"


class ScopeModel(ApiModel):
    """Cross-subscription scope selector."""

    business_service: list[str] = Field(default_factory=list)
    application: list[str] = Field(default_factory=list)
    environment: list[str] = Field(default_factory=list)
    subscription: list[str] = Field(default_factory=list)
    subscription_connection: list[str] = Field(default_factory=list)
    owner: list[str] = Field(default_factory=list)
    support_team: list[str] = Field(default_factory=list)
    region: list[str] = Field(default_factory=list)
    criticality: list[str] = Field(default_factory=list)


class DependencyGraphRequest(ApiModel):
    subject: str = Field(min_length=1)
    direction: str = Field("downstream", description="upstream | downstream")
    depth: int = Field(2, ge=1, le=8)


# --------------------------------------------------------------------------
# Health
# --------------------------------------------------------------------------


class HealthModel(ApiModel):
    status: str
    knowledge_version: str = ""
    freshness: str = ""
    connections: int = 0


# --------------------------------------------------------------------------
# Vulnerability risk exceptions
# --------------------------------------------------------------------------


class RiskExceptionCreateRequest(ApiModel):
    """Accept risk for a CVE, optionally scoped to a single server.

    Omitting ``server_id`` accepts risk for this CVE everywhere it currently
    appears; this is intentionally broad so a single accepted-risk decision
    (e.g. "no fix available, compensating control in place") doesn't require
    filing one exception per affected server.
    """

    cve_id: str = Field(min_length=1)
    server_id: str = Field("", description="Limit the exception to a single server; omit for all")
    reason: str = Field(min_length=1, description="Justification for accepting this risk")
    approved_by: str = Field("", description="Approver identity/name")
    expires_at: str = Field(
        "", description="ISO-8601 expiry; omit for an exception with no expiry"
    )
