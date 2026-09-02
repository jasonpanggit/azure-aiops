"""Subscription onboarding service.

The single entry point for create, update, delete, disable, enable, list,
detail, validate, sync, health, and metadata mapping. Deliberately
transport-agnostic so a future API layer reuses it without duplicating
business logic.
"""

from __future__ import annotations

import dataclasses
import logging
import re
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

from ontology.subscription_connection import (
    BusinessServiceLinkage,
    CredentialReference,
    EnvironmentMapping,
    SubscriptionConnection,
    SyncState,
)
from storage.fs import resolve_root

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

logger = logging.getLogger(__name__)

_CONNECTION_ID = re.compile(r"^[a-z0-9][a-z0-9-_]{1,62}$")
_GUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)


class OnboardingError(RuntimeError):
    """Raised when an onboarding operation cannot be completed."""


class SubscriptionOnboardingService:
    #: Shared across every instance rather than per-service so that repeated
    #: `SubscriptionOnboardingService(...)` construction (e.g. one call per
    #: API request in tests, or hot-reload in dev) doesn't leak a thread pool
    #: per instance. Sync jobs are I/O-bound (Azure ARG calls, Fabric writes),
    #: so a small bounded pool is enough to keep a handful of connections
    #: syncing concurrently without unbounded thread growth.
    _executor: ThreadPoolExecutor | None = None

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
        self._reconcile_orphaned_syncs()

    def _reconcile_orphaned_syncs(self) -> None:
        """Fail any connection left mid-sync by a process that no longer exists.

        Syncs run on an in-process ``ThreadPoolExecutor`` (see
        :meth:`sync_async`); there is nothing durable about that thread. If
        the container is restarted or redeployed while a sync is running --
        a rolling ACA deploy, a crash, an OOM kill -- the thread dies with it,
        but the on-disk ``sync_state.status`` stays "running" forever because
        nothing ever transitions it. Every subsequent poll from the UI then
        reports "running"/"unknown" indefinitely, and every later manual sync
        attempt piles onto the same stuck state (bumping ``attempts`` without
        ever resolving it). Since this constructor runs once per process
        startup, any connection still marked "running" at this point cannot
        actually have a live worker -- this process has none running yet --
        so it's safe to mark it failed here and let the next sync attempt
        start clean.
        """
        try:
            connections = self.registry.list()
        except Exception:
            logger.debug("Unable to load registry for orphaned-sync reconciliation", exc_info=True)
            return
        for connection in connections:
            state = connection.sync_state
            if state is None or state.status != "running":
                continue
            try:
                failed_state = dataclasses.replace(
                    state,
                    status="failed",
                    last_failed_at=_iso(self.clock()),
                    attempts=state.attempts + 1,
                    stage="failed",
                    stage_message="Sync interrupted by a service restart or deployment",
                    message="Sync interrupted by a service restart or deployment",
                )
                self._save_operation_state(connection.connection_id, sync_state=failed_state)
                logger.warning(
                    "Reconciled orphaned sync for connection %s (run_id=%s)",
                    connection.connection_id,
                    state.run_id,
                )
            except Exception:
                logger.debug(
                    "Unable to reconcile orphaned sync for %s", connection.connection_id, exc_info=True
                )

    @classmethod
    def _shared_executor(cls) -> ThreadPoolExecutor:
        if cls._executor is None:
            cls._executor = ThreadPoolExecutor(
                max_workers=4, thread_name_prefix="onboarding-sync"
            )
        return cls._executor

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

    def add_and_initialize(
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
        """Create a connection, validate it, and queue its first sync when safe."""
        detail = self.add(
            connection_id=connection_id,
            name=name,
            tenant_id=tenant_id,
            subscription_id=subscription_id,
            client_id=client_id,
            secret_ref=secret_ref,
            client_secret=client_secret,
            credential_id=credential_id,
            metadata=metadata,
        )
        identifier = detail["connection_id"]
        validation = self.validate(identifier)
        initial_sync: dict[str, Any] = {
            "connection_id": identifier,
            "status": "not_started",
            "reason": "validation_failed",
            "sync_state": self.registry.get(identifier).sync_state.to_dict(),
        }
        if validation["passed"]:
            initial_sync = self.sync_async(identifier, mode="initial")
        return {
            **self.detail(identifier),
            "validation": validation,
            "initial_sync": initial_sync,
        }

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
            "sync_status": (connection.sync_state or SyncState()).status,
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

    def sync_async(
        self, connection_id: str, *, mode: str = "initial", run_id: str | None = None
    ) -> dict[str, Any]:
        """Kick off a connection sync on a background thread and return
        immediately with a "running" ``sync_state`` for the caller to poll
        (via :meth:`health_report`).

        A synchronous ``requests.post(".../sync")`` from a UI can time out
        well before discovery + merge + Fabric publish finishes for a large
        subscription; this lets the API respond in milliseconds while the
        real work continues, with live stage/progress persisted onto the
        connection's ``sync_state`` after every stage transition so a poller
        sees incremental updates rather than only a final result.

        Raises the same validation errors as :meth:`sync` synchronously
        (unknown connection, disabled connection, bad mode) so callers get an
        immediate 4xx instead of a background failure for cases that are
        really request errors, not sync failures.
        """
        connection = self.registry.get(connection_id)
        if mode not in {"initial", "scheduled", "manual"}:
            raise OnboardingError("sync mode must be initial, scheduled, or manual")
        if not connection.is_active:
            raise OnboardingError(
                f"Connection '{connection_id}' is disabled; enable it before syncing"
            )

        identifier = run_id or str(uuid.uuid4())
        previous = connection.sync_state or SyncState()
        running_state = SyncState(
            status="running",
            last_synced_at=previous.last_synced_at,
            last_successful_sync_at=previous.last_successful_sync_at,
            last_failed_at=previous.last_failed_at,
            run_id=identifier,
            source_version=previous.source_version,
            record_count=previous.record_count,
            attempts=previous.attempts,
            message=f"{mode} sync queued",
            stage="queued",
            stage_message=f"{mode} sync queued",
            progress_pct=0,
        )
        saved = self._save_operation_state(connection_id, sync_state=running_state)
        self._shared_executor().submit(self._run_sync_job, connection_id, mode, identifier)
        return {
            "connection_id": connection_id,
            "run_id": identifier,
            "status": "running",
            "sync_state": saved.sync_state.to_dict(),
        }

    def _run_sync_job(self, connection_id: str, mode: str, run_id: str) -> None:
        """Background-thread worker for :meth:`sync_async`.

        Runs on the shared executor, so this must not raise: any failure
        constructing the connection/coordinator inputs is recorded onto
        ``sync_state`` the same way a failed ``run()`` is, rather than being
        lost to an unobserved thread exception.
        """

        def _on_progress(stage: str, message: str, pct: int) -> None:
            try:
                current = self.registry.get(connection_id).sync_state or SyncState()
                state = dataclasses.replace(
                    current,
                    status="running" if stage not in {"succeeded", "failed"} else stage,
                    run_id=run_id,
                    stage=stage,
                    stage_message=message,
                    progress_pct=pct,
                    message=message,
                )
                self._save_operation_state(connection_id, sync_state=state)
            except Exception:
                logger.debug("Unable to persist sync progress for %s", connection_id, exc_info=True)

        try:
            connection = self.registry.get(connection_id)
            _result, state = self.sync_coordinator.run(
                connection,
                mode=mode,
                run_id=run_id,
                progress_callback=_on_progress,
            )
            health = self.health.from_sync(connection, state)
            self._save_operation_state(connection_id, sync_state=state, health=health)
        except Exception as exc:  # noqa: BLE001 - background job: record, don't raise
            message = str(exc).strip() or exc.__class__.__name__
            try:
                current = self.registry.get(connection_id).sync_state or SyncState()
                failed_state = dataclasses.replace(
                    current,
                    status="failed",
                    run_id=run_id,
                    last_failed_at=_iso(self.clock()),
                    attempts=current.attempts + 1,
                    stage="failed",
                    stage_message=message,
                    progress_pct=100,
                    message=message,
                )
                self._save_operation_state(connection_id, sync_state=failed_state)
            except Exception:
                logger.exception("Unable to persist failed sync state for %s", connection_id)

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
                # sync_status is read from the same disk-cached registry as
                # every other field in this summary, so it can lag live state
                # by a few minutes during an in-flight sync — but omitting it
                # entirely left the connections table showing "unknown" for
                # every connection, which is worse than briefly-stale status.
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
