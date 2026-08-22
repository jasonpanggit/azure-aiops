"""Subscription onboarding service.

The single entry point for create, update, delete, disable, enable, list,
detail, validate, sync, health, and metadata mapping. Deliberately
transport-agnostic so a future API layer reuses it without duplicating
business logic.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from hermes_arg_connector.fs import resolve_root
from ontology.subscription_connection import (
    BusinessServiceLinkage,
    CredentialReference,
    EnvironmentMapping,
    SubscriptionConnection,
    SyncState,
)

from .credentials import (
    CredentialResolver,
    SecretStorageError,
    SecretWriter,
    redact_mapping,
)
from .health import HealthEvaluator
from .metadata import BusinessMetadata
from .registry import (
    ConnectionRegistry,
    DuplicateConnectionError,
    RegistryConflictError,
)
from .sync import ConnectionSyncCoordinator, SyncResult
from .validation import ConnectionValidator, ValidationReport

_CONNECTION_ID = re.compile(r"^[a-z0-9][a-z0-9-_]{1,62}$")
_GUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)


class OnboardingError(RuntimeError):
    """Raised when an onboarding operation cannot be completed."""


class SubscriptionOnboardingService:
    def __init__(
        self,
        output_dir: str,
        registry: ConnectionRegistry | None = None,
        validator: ConnectionValidator | None = None,
        sync_coordinator: ConnectionSyncCoordinator | None = None,
        resolver: CredentialResolver | None = None,
        secret_writer: SecretWriter | None = None,
        health_evaluator: HealthEvaluator | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.output_dir = resolve_root(str(output_dir))
        self.registry = registry or ConnectionRegistry(self.output_dir)
        self.validator = validator or ConnectionValidator(clock=clock)
        self.sync_coordinator = sync_coordinator or ConnectionSyncCoordinator(
            self.output_dir, clock=clock
        )
        self.resolver = resolver or CredentialResolver()
        self.secret_writer = secret_writer
        self.health = health_evaluator or HealthEvaluator(clock=clock)
        self.clock = clock or (lambda: datetime.now(UTC))

    def _credential_secret_ref(
        self,
        *,
        connection_id: str,
        secret_ref: str | None = None,
        client_secret: str | None = None,
    ) -> str | None:
        if str(secret_ref or "").strip() and str(client_secret or ""):
            raise OnboardingError("Provide either secret_ref or client_secret, not both")
        if not str(client_secret or ""):
            return secret_ref
        if self.secret_writer is None:
            raise SecretStorageError(
                "No Key Vault writer is configured for storing submitted client secrets"
            )
        return self.secret_writer.store(
            connection_id=connection_id, secret_value=str(client_secret)
        )

    def add(
        self,
        *,
        connection_id: str,
        name: str | None = None,
        tenant_id: str,
        subscription_id: str,
        client_id: str,
        secret_ref: str | None = None,
        client_secret: str | None = None,
        credential_id: str | None = None,
        metadata: BusinessMetadata | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        identifier = _validate_connection_id(connection_id)
        _validate_guid(tenant_id, "tenant_id")
        _validate_guid(subscription_id, "subscription_id")
        _validate_guid(client_id, "client_id")
        _ensure_addable(self.registry, identifier, tenant_id, subscription_id)
        stored_secret_ref = self._credential_secret_ref(
            connection_id=identifier,
            secret_ref=secret_ref,
            client_secret=client_secret,
        )
        if not str(stored_secret_ref or "").strip():
            raise OnboardingError(
                "secret_ref is required; submit a client_secret only when "
                "Key Vault storage is configured"
            )

        business = BusinessMetadata.from_mapping(metadata)
        credential = CredentialReference(
            credential_id=credential_id or f"{identifier}-spn",
            kind="service_principal",
            client_id=client_id,
            tenant_id=tenant_id,
            secret_ref=str(stored_secret_ref).strip(),
            scope=f"/subscriptions/{subscription_id}",
        )
        connection = SubscriptionConnection(
            connection_id=identifier,
            name=str(name or identifier).strip(),
            tenant_id=tenant_id,
            subscription_id=subscription_id,
            credential=credential,
            sync_state=SyncState(status="pending"),
            environment_mappings=_environment_mappings(
                identifier, tenant_id, subscription_id, business
            ),
            business_service_linkages=_business_linkages(identifier, business),
            is_active=True,
            metadata={
                "business": business.to_dict(),
                "created_at": _iso(self.clock()),
                "updated_at": _iso(self.clock()),
            },
        )
        self.registry.add(connection)
        return self.detail(identifier)

    def update(
        self,
        connection_id: str,
        *,
        name: str | None = None,
        client_id: str | None = None,
        secret_ref: str | None = None,
        client_secret: str | None = None,
        credential_id: str | None = None,
    ) -> dict[str, Any]:
        connection = self.registry.get(connection_id)
        credential = connection.credential
        if client_id is not None:
            _validate_guid(client_id, "client_id")
        stored_secret_ref = self._credential_secret_ref(
            connection_id=connection.connection_id,
            secret_ref=secret_ref,
            client_secret=client_secret,
        )
        if any(value is not None for value in (client_id, stored_secret_ref, credential_id)):
            base = credential or CredentialReference(
                credential_id=f"{connection.connection_id}-spn",
                tenant_id=connection.tenant_id,
            )
            credential = CredentialReference(
                credential_id=credential_id or base.credential_id,
                kind=base.kind,
                client_id=client_id or base.client_id,
                tenant_id=connection.tenant_id,
                secret_ref=(
                    stored_secret_ref.strip() if stored_secret_ref else base.secret_ref
                ),
                scope=base.scope or f"/subscriptions/{connection.subscription_id}",
                scopes=base.scopes,
                expires_at=base.expires_at,
                active=base.active,
            )
        updated = _replace(
            connection,
            name=str(name).strip() if name else connection.name,
            credential=credential,
            metadata={**connection.metadata, "updated_at": _iso(self.clock())},
        )
        self.registry.save(updated)
        return self.detail(connection.connection_id)

    def map_metadata(
        self,
        connection_id: str,
        metadata: BusinessMetadata | dict[str, Any],
    ) -> dict[str, Any]:
        connection = self.registry.get(connection_id)
        incoming = BusinessMetadata.from_mapping(metadata)
        if incoming.is_empty:
            raise OnboardingError("At least one business metadata field must be provided")
        merged = self.registry.metadata_for(connection).merge(incoming)
        updated = _replace(
            connection,
            environment_mappings=_environment_mappings(
                connection.connection_id, connection.tenant_id, connection.subscription_id, merged
            ),
            business_service_linkages=_business_linkages(connection.connection_id, merged),
            metadata={
                **connection.metadata,
                "business": merged.to_dict(),
                "updated_at": _iso(self.clock()),
            },
        )
        self.registry.save(updated)
        return self.detail(connection.connection_id)

    def disable(self, connection_id: str) -> dict[str, Any]:
        return self._set_active(connection_id, False)

    def enable(self, connection_id: str) -> dict[str, Any]:
        return self._set_active(connection_id, True)

    def delete(self, connection_id: str) -> dict[str, Any]:
        connection = self.registry.delete(connection_id)
        return self._summary(connection)

    def list(self, *, include_disabled: bool = True) -> list[dict[str, Any]]:
        return [
            self._summary(connection)
            for connection in self.registry.list(include_disabled=include_disabled)
        ]

    def detail(self, connection_id: str) -> dict[str, Any]:
        connection = self.registry.get(connection_id)
        business = self.registry.metadata_for(connection)
        freshness = self.sync_coordinator.freshness(connection.sync_state)
        return {
            **self._summary(connection),
            "credential": self.resolver.describe(connection.credential),
            "business_metadata": business.to_dict(),
            "missing_metadata": business.missing_fields(),
            "environment_mappings": [item.to_dict() for item in connection.environment_mappings],
            "business_service_linkages": [
                item.to_dict() for item in connection.business_service_linkages
            ],
            "freshness": freshness,
            "dataset_root": str(self.sync_coordinator.connection_output_dir(connection)),
        }

    def validate(
        self, connection_id: str, *, checks: tuple[str, ...] | None = None
    ) -> dict[str, Any]:
        connection = self.registry.get(connection_id)
        report: ValidationReport = self.validator.validate(connection, checks=checks)
        if checks is None:
            health = self.health.from_validation(connection, report)
            health = self._save_operation_state(
                connection_id, health=health
            ).health
        else:
            health = self.registry.get(connection_id).health or self.health.from_validation(
                connection, report
            )
        return {**report.to_dict(), "health": health.to_dict()}

    def sync(
        self, connection_id: str, *, mode: str = "initial", run_id: str | None = None
    ) -> dict[str, Any]:
        connection = self.registry.get(connection_id)
        result: SyncResult
        state: SyncState
        result, state = self.sync_coordinator.run(connection, mode=mode, run_id=run_id)
        health = self.health.from_sync(connection, state)
        saved = self._save_operation_state(
            connection_id, sync_state=state, health=health
        )
        state = saved.sync_state
        health = saved.health
        return {**result.to_dict(), "sync_state": state.to_dict(), "health": health.to_dict()}

    def _save_operation_state(
        self,
        connection_id: str,
        *,
        sync_state: SyncState | None = None,
        health: Any = None,
    ) -> SubscriptionConnection:
        for _ in range(3):
            current, revision = self.registry.get_with_revision(connection_id)
            updated = _replace(
                current,
                sync_state=sync_state or current.sync_state,
                health=health or current.health,
            )
            try:
                return self.registry.save(updated, expected_revision=revision)
            except RegistryConflictError:
                continue
        raise RegistryConflictError(
            f"Connection '{connection_id}' changed repeatedly while saving operation state"
        )

    def health_report(self, connection_id: str | None = None) -> dict[str, Any]:
        connections = (
            [self.registry.get(connection_id)] if connection_id else self.registry.list()
        )
        summaries = [
            self.health.summarize(
                connection, self.sync_coordinator.freshness(connection.sync_state)
            )
            for connection in connections
        ]
        counts: dict[str, int] = {}
        for summary in summaries:
            counts[summary["overall"]] = counts.get(summary["overall"], 0) + 1
        return {
            "generated_at": _iso(self.clock()),
            "total": len(summaries),
            "status_counts": counts,
            "connections": summaries,
        }

    def _set_active(self, connection_id: str, active: bool) -> dict[str, Any]:
        connection = self.registry.get(connection_id)
        updated = _replace(
            connection,
            is_active=active,
            metadata={
                **connection.metadata,
                "updated_at": _iso(self.clock()),
                "disabled_at": None if active else _iso(self.clock()),
            },
        )
        self.registry.save(updated)
        return self.detail(connection.connection_id)

    def _summary(self, connection: SubscriptionConnection) -> dict[str, Any]:
        business = self.registry.metadata_for(connection)
        sync_state = connection.sync_state or SyncState()
        return redact_mapping(
            {
                "connection_id": connection.connection_id,
                "name": connection.name,
                "tenant_id": connection.tenant_id,
                "subscription_id": connection.subscription_id,
                "scope_key": connection.scope_key,
                "is_active": connection.is_active,
                "business_service": business.business_service,
                "application": business.application,
                "environment": business.environment,
                "owner": business.project_owner,
                "support_team": business.support_team,
                "criticality": business.criticality,
                "region": business.region,
                "sync_status": sync_state.status,
                "sync_record_count": sync_state.record_count,
                "last_synced_at": sync_state.last_synced_at,
                "last_successful_sync_at": sync_state.last_successful_sync_at,
                "health_status": connection.health.status if connection.health else "unknown",
            }
        )


def _environment_mappings(
    connection_id: str, tenant_id: str, subscription_id: str, metadata: BusinessMetadata
) -> tuple[EnvironmentMapping, ...]:
    if not metadata.environment:
        return ()
    return (
        EnvironmentMapping(
            connection_id=connection_id,
            environment_name=metadata.environment,
            subscription_id=subscription_id,
            tenant_id=tenant_id,
            mapping_type="subscription",
            source="onboarding",
            confidence=1.0,
            metadata={"assigned_by": "subscription_onboarding"},
        ),
    )


def _business_linkages(
    connection_id: str, metadata: BusinessMetadata
) -> tuple[BusinessServiceLinkage, ...]:
    if not metadata.business_service:
        return ()
    return (
        BusinessServiceLinkage(
            connection_id=connection_id,
            business_service_id=metadata.business_service,
            environment_name=metadata.environment,
            application_ids=(metadata.application,) if metadata.application else (),
            confidence=1.0,
        ),
    )


def _replace(connection: SubscriptionConnection, **changes: Any) -> SubscriptionConnection:
    fields = {
        "connection_id": connection.connection_id,
        "name": connection.name,
        "tenant_id": connection.tenant_id,
        "subscription_id": connection.subscription_id,
        "credential": connection.credential,
        "sync_state": connection.sync_state,
        "health": connection.health,
        "environment_mappings": connection.environment_mappings,
        "business_service_linkages": connection.business_service_linkages,
        "is_active": connection.is_active,
        "metadata": connection.metadata,
    }
    fields.update(changes)
    return SubscriptionConnection(**fields)


def _validate_connection_id(value: str) -> str:
    identifier = str(value or "").strip().casefold()
    if not _CONNECTION_ID.match(identifier):
        raise OnboardingError(
            "connection_id must be 2-63 characters of lowercase letters, digits, hyphen, or underscore"
        )
    return identifier


def _validate_guid(value: str, field_name: str) -> str:
    text = str(value or "").strip()
    if not _GUID.match(text):
        raise OnboardingError(f"{field_name} must be a GUID")
    return text


def _ensure_addable(
    registry: ConnectionRegistry,
    connection_id: str,
    tenant_id: str,
    subscription_id: str,
) -> None:
    if registry.exists(connection_id):
        raise DuplicateConnectionError(
            f"Subscription connection '{connection_id}' already exists"
        )
    for existing in registry.list():
        if (
            existing.subscription_id.casefold() == subscription_id.casefold()
            and existing.tenant_id.casefold() == tenant_id.casefold()
            and existing.is_active
        ):
            raise DuplicateConnectionError(
                f"Subscription {subscription_id} is already onboarded as "
                f"'{existing.connection_id}'"
            )


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


__all__ = ["OnboardingError", "SubscriptionOnboardingService"]
