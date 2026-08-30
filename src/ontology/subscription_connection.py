from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _coerce_string(value: Any, *, field_name: str) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        raise ValueError(f"SubscriptionConnection {field_name} is required")
    return text


@dataclass(frozen=True)
class CredentialReference:
    credential_id: str
    kind: str = "service_principal"
    client_id: str | None = None
    tenant_id: str | None = None
    secret_ref: str | None = None
    scope: str | None = None
    scopes: tuple[str, ...] = ()
    expires_at: str | None = None
    active: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "credential_id", _coerce_string(self.credential_id, field_name="credential_id"))
        object.__setattr__(self, "kind", str(self.kind or "service_principal").strip() or "service_principal")
        if self.scopes and not isinstance(self.scopes, tuple):
            object.__setattr__(self, "scopes", tuple(self.scopes))
        if self.client_id is not None:
            object.__setattr__(self, "client_id", str(self.client_id).strip() or None)
        if self.tenant_id is not None:
            object.__setattr__(self, "tenant_id", str(self.tenant_id).strip() or None)
        if self.secret_ref is not None:
            object.__setattr__(self, "secret_ref", str(self.secret_ref).strip() or None)
        if self.scope is not None:
            object.__setattr__(self, "scope", str(self.scope).strip() or None)
        if self.expires_at is not None:
            object.__setattr__(self, "expires_at", str(self.expires_at).strip() or None)

    @classmethod
    def from_mapping(cls, value: Any) -> CredentialReference | None:
        if value is None:
            return None
        if isinstance(value, cls):
            return value
        if not isinstance(value, dict):
            raise TypeError("CredentialReference must be a mapping or CredentialReference")
        credential_id = value.get("credential_id") or value.get("id") or value.get("credentialId")
        if not credential_id:
            return None
        return cls(
            credential_id=str(credential_id),
            kind=str(value.get("kind") or value.get("credential_type") or "service_principal"),
            client_id=value.get("client_id") or value.get("clientId"),
            tenant_id=value.get("tenant_id") or value.get("tenantId"),
            secret_ref=value.get("secret_ref") or value.get("secretRef"),
            scope=value.get("scope"),
            scopes=tuple(value.get("scopes") or ()),
            expires_at=value.get("expires_at") or value.get("expiresAt"),
            active=bool(value.get("active", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "credential_id": self.credential_id,
            "kind": self.kind,
            "client_id": self.client_id,
            "tenant_id": self.tenant_id,
            "secret_ref": self.secret_ref,
            "scope": self.scope,
            "scopes": list(self.scopes),
            "expires_at": self.expires_at,
            "active": self.active,
        }


@dataclass(frozen=True)
class SyncState:
    status: str = "pending"
    last_synced_at: str | None = None
    last_successful_sync_at: str | None = None
    last_failed_at: str | None = None
    run_id: str | None = None
    source_version: str | None = None
    record_count: int = 0
    attempts: int = 0
    message: str | None = None
    # Live-progress fields. ``status`` stays the coarse
    # pending/running/succeeded/failed lifecycle used by freshness/health
    # checks; ``stage``/``stage_message``/``progress_pct`` are updated
    # in-place while a run is "running" so a client can poll one connection's
    # sync_state and render a progress UI without a separate job store.
    stage: str | None = None
    stage_message: str | None = None
    progress_pct: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", str(self.status or "pending").strip() or "pending")
        object.__setattr__(self, "last_synced_at", _normalize_optional(self.last_synced_at))
        object.__setattr__(self, "last_successful_sync_at", _normalize_optional(self.last_successful_sync_at))
        object.__setattr__(self, "last_failed_at", _normalize_optional(self.last_failed_at))
        object.__setattr__(self, "run_id", _normalize_optional(self.run_id))
        object.__setattr__(self, "source_version", _normalize_optional(self.source_version))
        object.__setattr__(self, "message", _normalize_optional(self.message))
        object.__setattr__(self, "stage", _normalize_optional(self.stage))
        object.__setattr__(self, "stage_message", _normalize_optional(self.stage_message))
        if isinstance(self.record_count, bool):
            raise TypeError("SyncState record_count must be an integer")
        if int(self.record_count) < 0:
            raise ValueError("SyncState record_count must be non-negative")
        if isinstance(self.attempts, bool):
            raise TypeError("SyncState attempts must be an integer")
        if int(self.attempts) < 0:
            raise ValueError("SyncState attempts must be non-negative")
        if self.progress_pct is not None:
            if isinstance(self.progress_pct, bool):
                raise TypeError("SyncState progress_pct must be an integer")
            pct = int(self.progress_pct)
            if not 0 <= pct <= 100:
                raise ValueError("SyncState progress_pct must be between 0 and 100")
            object.__setattr__(self, "progress_pct", pct)

    @classmethod
    def from_mapping(cls, value: Any) -> SyncState | None:
        if value is None:
            return None
        if isinstance(value, cls):
            return value
        if not isinstance(value, dict):
            raise TypeError("SyncState must be a mapping or SyncState")
        if not any(key in value for key in ("status", "last_synced_at", "last_successful_sync_at", "last_failed_at", "run_id")):
            return None
        return cls(
            status=str(value.get("status") or "pending"),
            last_synced_at=value.get("last_synced_at") or value.get("lastSyncedAt"),
            last_successful_sync_at=value.get("last_successful_sync_at") or value.get("lastSuccessfulSyncAt"),
            last_failed_at=value.get("last_failed_at") or value.get("lastFailedAt"),
            run_id=value.get("run_id") or value.get("runId"),
            source_version=value.get("source_version") or value.get("sourceVersion"),
            record_count=int(value.get("record_count") or value.get("recordCount") or 0),
            attempts=int(value.get("attempts") or 0),
            message=value.get("message"),
            stage=value.get("stage"),
            stage_message=value.get("stage_message") or value.get("stageMessage"),
            progress_pct=(
                int(value["progress_pct"])
                if value.get("progress_pct") is not None
                else (int(value["progressPct"]) if value.get("progressPct") is not None else None)
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "last_synced_at": self.last_synced_at,
            "last_successful_sync_at": self.last_successful_sync_at,
            "last_failed_at": self.last_failed_at,
            "run_id": self.run_id,
            "source_version": self.source_version,
            "record_count": self.record_count,
            "attempts": self.attempts,
            "message": self.message,
            "stage": self.stage,
            "stage_message": self.stage_message,
            "progress_pct": self.progress_pct,
        }


@dataclass(frozen=True)
class ConnectionHealth:
    connection_id: str
    status: str = "unknown"
    last_checked_at: str | None = None
    last_success_at: str | None = None
    last_failure_at: str | None = None
    failure_count: int = 0
    details: str | None = None
    healthy: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "connection_id", _coerce_string(self.connection_id, field_name="connection_id"))
        object.__setattr__(self, "status", str(self.status or "unknown").strip() or "unknown")
        object.__setattr__(self, "last_checked_at", _normalize_optional(self.last_checked_at))
        object.__setattr__(self, "last_success_at", _normalize_optional(self.last_success_at))
        object.__setattr__(self, "last_failure_at", _normalize_optional(self.last_failure_at))
        if isinstance(self.failure_count, bool):
            raise TypeError("ConnectionHealth failure_count must be an integer")
        object.__setattr__(self, "failure_count", max(int(self.failure_count), 0))
        object.__setattr__(self, "details", _normalize_optional(self.details))

    @classmethod
    def from_mapping(cls, value: Any) -> ConnectionHealth | None:
        if value is None:
            return None
        if isinstance(value, cls):
            return value
        if not isinstance(value, dict):
            raise TypeError("ConnectionHealth must be a mapping or ConnectionHealth")
        connection_id = value.get("connection_id") or value.get("connectionId")
        if not connection_id:
            return None
        return cls(
            connection_id=str(connection_id),
            status=str(value.get("status") or "unknown"),
            last_checked_at=value.get("last_checked_at") or value.get("lastCheckedAt"),
            last_success_at=value.get("last_success_at") or value.get("lastSuccessAt"),
            last_failure_at=value.get("last_failure_at") or value.get("lastFailureAt"),
            failure_count=int(value.get("failure_count") or value.get("failureCount") or 0),
            details=value.get("details"),
            healthy=bool(value.get("healthy", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "connection_id": self.connection_id,
            "status": self.status,
            "last_checked_at": self.last_checked_at,
            "last_success_at": self.last_success_at,
            "last_failure_at": self.last_failure_at,
            "failure_count": self.failure_count,
            "details": self.details,
            "healthy": self.healthy,
        }


@dataclass(frozen=True)
class EnvironmentMapping:
    connection_id: str
    environment_name: str
    subscription_id: str
    tenant_id: str
    mapping_type: str = "subscription"
    source: str = "tag"
    confidence: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "connection_id", _coerce_string(self.connection_id, field_name="connection_id"))
        object.__setattr__(self, "environment_name", _coerce_string(self.environment_name, field_name="environment_name"))
        object.__setattr__(self, "subscription_id", _coerce_string(self.subscription_id, field_name="subscription_id"))
        object.__setattr__(self, "tenant_id", _coerce_string(self.tenant_id, field_name="tenant_id"))
        object.__setattr__(self, "mapping_type", str(self.mapping_type or "subscription").strip() or "subscription")
        object.__setattr__(self, "source", str(self.source or "tag").strip() or "tag")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("EnvironmentMapping confidence must be between 0 and 1")
        object.__setattr__(self, "confidence", float(self.confidence))
        if not isinstance(self.metadata, dict):
            raise TypeError("EnvironmentMapping metadata must be a mapping")

    @classmethod
    def from_mapping(cls, value: Any) -> EnvironmentMapping | None:
        if value is None:
            return None
        if isinstance(value, cls):
            return value
        if not isinstance(value, dict):
            raise TypeError("EnvironmentMapping must be a mapping or EnvironmentMapping")
        connection_id = value.get("connection_id") or value.get("connectionId")
        if not connection_id:
            return None
        return cls(
            connection_id=str(connection_id),
            environment_name=str(value.get("environment_name") or value.get("environmentName") or value.get("environment") or "unknown"),
            subscription_id=str(value.get("subscription_id") or value.get("subscriptionId") or value.get("subscription") or ""),
            tenant_id=str(value.get("tenant_id") or value.get("tenantId") or value.get("tenant") or ""),
            mapping_type=str(value.get("mapping_type") or value.get("mappingType") or "subscription"),
            source=str(value.get("source") or "tag"),
            confidence=float(value.get("confidence") or 1.0),
            metadata=dict(value.get("metadata") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "connection_id": self.connection_id,
            "environment_name": self.environment_name,
            "subscription_id": self.subscription_id,
            "tenant_id": self.tenant_id,
            "mapping_type": self.mapping_type,
            "source": self.source,
            "confidence": self.confidence,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class BusinessServiceLinkage:
    connection_id: str
    business_service_id: str
    environment_name: str | None = None
    application_ids: tuple[str, ...] = ()
    confidence: float = 1.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "connection_id", _coerce_string(self.connection_id, field_name="connection_id"))
        object.__setattr__(self, "business_service_id", _coerce_string(self.business_service_id, field_name="business_service_id"))
        object.__setattr__(self, "environment_name", _normalize_optional(self.environment_name))
        object.__setattr__(self, "application_ids", tuple(str(item) for item in self.application_ids))
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("BusinessServiceLinkage confidence must be between 0 and 1")
        object.__setattr__(self, "confidence", float(self.confidence))

    @classmethod
    def from_mapping(cls, value: Any) -> BusinessServiceLinkage | None:
        if value is None:
            return None
        if isinstance(value, cls):
            return value
        if not isinstance(value, dict):
            raise TypeError("BusinessServiceLinkage must be a mapping or BusinessServiceLinkage")
        connection_id = value.get("connection_id") or value.get("connectionId")
        if not connection_id:
            return None
        return cls(
            connection_id=str(connection_id),
            business_service_id=str(value.get("business_service_id") or value.get("businessServiceId") or value.get("business_service") or ""),
            environment_name=value.get("environment_name") or value.get("environmentName") or value.get("environment"),
            application_ids=tuple(str(item) for item in (value.get("application_ids") or value.get("applicationIds") or ())),
            confidence=float(value.get("confidence") or 1.0),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "connection_id": self.connection_id,
            "business_service_id": self.business_service_id,
            "environment_name": self.environment_name,
            "application_ids": list(self.application_ids),
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class SubscriptionConnection:
    connection_id: str
    name: str
    tenant_id: str
    subscription_id: str
    credential: CredentialReference | None = None
    sync_state: SyncState | None = None
    health: ConnectionHealth | None = None
    environment_mappings: tuple[EnvironmentMapping, ...] = ()
    business_service_linkages: tuple[BusinessServiceLinkage, ...] = ()
    is_active: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "connection_id", _coerce_string(self.connection_id, field_name="connection_id"))
        object.__setattr__(self, "name", _coerce_string(self.name, field_name="name"))
        object.__setattr__(self, "tenant_id", _coerce_string(self.tenant_id, field_name="tenant_id"))
        object.__setattr__(self, "subscription_id", _coerce_string(self.subscription_id, field_name="subscription_id"))
        if self.credential is not None and not isinstance(self.credential, CredentialReference):
            object.__setattr__(self, "credential", CredentialReference.from_mapping(self.credential))
        if self.sync_state is not None and not isinstance(self.sync_state, SyncState):
            object.__setattr__(self, "sync_state", SyncState.from_mapping(self.sync_state))
        if self.health is not None and not isinstance(self.health, ConnectionHealth):
            object.__setattr__(self, "health", ConnectionHealth.from_mapping(self.health))
        if self.environment_mappings and not isinstance(self.environment_mappings, tuple):
            object.__setattr__(self, "environment_mappings", tuple(self.environment_mappings))
        if self.business_service_linkages and not isinstance(self.business_service_linkages, tuple):
            object.__setattr__(self, "business_service_linkages", tuple(self.business_service_linkages))
        object.__setattr__(
            self,
            "environment_mappings",
            tuple(EnvironmentMapping.from_mapping(item) for item in self.environment_mappings if item is not None),
        )
        object.__setattr__(
            self,
            "business_service_linkages",
            tuple(BusinessServiceLinkage.from_mapping(item) for item in self.business_service_linkages if item is not None),
        )
        if not isinstance(self.metadata, dict):
            raise TypeError("SubscriptionConnection metadata must be a mapping")

    @classmethod
    def from_mapping(cls, value: Any) -> SubscriptionConnection | None:
        if value is None:
            return None
        if isinstance(value, cls):
            return value
        if not isinstance(value, dict):
            raise TypeError("SubscriptionConnection must be a mapping or SubscriptionConnection")
        connection_id = value.get("connection_id") or value.get("connectionId")
        if not connection_id:
            return None
        environment_mappings = value.get("environment_mappings") or value.get("environmentMappings") or ()
        business_service_linkages = value.get("business_service_linkages") or value.get("businessServiceLinkages") or ()
        if isinstance(environment_mappings, dict):
            environment_mappings = (environment_mappings,)
        if isinstance(business_service_linkages, dict):
            business_service_linkages = (business_service_linkages,)
        return cls(
            connection_id=str(connection_id),
            name=str(value.get("name") or value.get("display_name") or value.get("displayName") or connection_id),
            tenant_id=str(value.get("tenant_id") or value.get("tenantId") or value.get("tenant") or ""),
            subscription_id=str(value.get("subscription_id") or value.get("subscriptionId") or value.get("subscription") or ""),
            credential=CredentialReference.from_mapping(value.get("credential") or value.get("credential_reference") or value.get("credentialReference")),
            sync_state=SyncState.from_mapping(value.get("sync_state") or value.get("syncState")),
            health=ConnectionHealth.from_mapping(value.get("health") or value.get("connection_health") or value.get("connectionHealth")),
            environment_mappings=tuple(EnvironmentMapping.from_mapping(item) for item in environment_mappings if item is not None),
            business_service_linkages=tuple(BusinessServiceLinkage.from_mapping(item) for item in business_service_linkages if item is not None),
            is_active=bool(value.get("is_active", value.get("active", True))),
            metadata=dict(value.get("metadata") or {}),
        )

    @property
    def scope_key(self) -> str:
        return f"{self.tenant_id}:{self.subscription_id}:{self.connection_id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "connection_id": self.connection_id,
            "name": self.name,
            "tenant_id": self.tenant_id,
            "subscription_id": self.subscription_id,
            "credential": self.credential.to_dict() if self.credential else None,
            "sync_state": self.sync_state.to_dict() if self.sync_state else None,
            "health": self.health.to_dict() if self.health else None,
            "environment_mappings": [item.to_dict() for item in self.environment_mappings],
            "business_service_linkages": [item.to_dict() for item in self.business_service_linkages],
            "is_active": self.is_active,
            "metadata": self.metadata,
        }


def _normalize_optional(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


__all__ = [
    "BusinessServiceLinkage",
    "ConnectionHealth",
    "CredentialReference",
    "EnvironmentMapping",
    "SubscriptionConnection",
    "SyncState",
]
