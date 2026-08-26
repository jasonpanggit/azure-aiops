from __future__ import annotations

import dataclasses
import json
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from onboarding.health import HealthEvaluator
from onboarding.metadata import BusinessMetadata
from onboarding.registry import ConnectionRegistry
from onboarding.runtime import connection_context
from onboarding.store import FileRegistryStore
from onboarding.sync import _record_count
from ontology.subscription_connection import (
    ConnectionHealth,
    CredentialReference,
    SubscriptionConnection,
    SyncState,
)

from .config import ConnectorConfig
from storage.fs import join_root
from .service import IngestionService

DEFAULT_LOCAL_CONNECTION_ID = "local-demo"
DEFAULT_LOCAL_TENANT_ID = "00000000-0000-0000-0000-000000000001"
DEFAULT_LOCAL_SUBSCRIPTION_ID = "00000000-0000-0000-0000-000000000002"
DEFAULT_LOCAL_CLIENT_ID = "00000000-0000-0000-0000-000000000003"
SPN_ENV_VARS = (
    "AZURE_SUBSCRIPTION_ID",
    "AZURE_TENANT_ID",
    "AZURE_CLIENT_ID",
    "AZURE_CLIENT_SECRET",
)


class FixtureAzureResourceGraphSource:
    """Fixture-backed ARG source for offline local testing."""

    def __init__(self, payload: dict[str, list[dict[str, Any]]]) -> None:
        self.payload = payload

    def list_subscriptions(self) -> list[dict[str, str]]:
        return [
            {
                "subscriptionId": DEFAULT_LOCAL_SUBSCRIPTION_ID,
                "tenantId": DEFAULT_LOCAL_TENANT_ID,
                "displayName": "Local Demo Subscription",
            }
        ]

    def fetch(self, specs, subscription_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        return {spec.name: list(self.payload.get(spec.name, [])) for spec in specs}


def seed_local_environment(
    *,
    root: str | Path,
    fixture: str | Path,
    config: ConnectorConfig | None = None,
    connection_id: str = DEFAULT_LOCAL_CONNECTION_ID,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Seed a local API-readable snapshot without contacting Azure services."""

    now = clock or (lambda: datetime.now(UTC))
    root_path = Path(root).expanduser().resolve()
    fixture_path = Path(fixture).expanduser().resolve()
    payload = json.loads(fixture_path.read_text())
    if not isinstance(payload, dict):
        raise TypeError("Local ARG fixture must be a JSON object keyed by query name")

    business = BusinessMetadata(
        business_service="Demo",
        application="AI Ops Demo",
        environment="local",
        project_owner="Local Developer",
        support_team="Local Developer",
        criticality="medium",
        region="local",
        cost_center="local",
    )
    checked_at = _iso(now())
    connection = SubscriptionConnection(
        connection_id=connection_id,
        name="Local Demo Subscription",
        tenant_id=DEFAULT_LOCAL_TENANT_ID,
        subscription_id=DEFAULT_LOCAL_SUBSCRIPTION_ID,
        credential=CredentialReference(
            credential_id=f"{connection_id}-fixture",
            kind="local_fixture",
            client_id=DEFAULT_LOCAL_CLIENT_ID,
            tenant_id=DEFAULT_LOCAL_TENANT_ID,
            secret_ref=f"file://{fixture_path}",
            scope=f"/subscriptions/{DEFAULT_LOCAL_SUBSCRIPTION_ID}",
        ),
        sync_state=SyncState(status="pending"),
        health=ConnectionHealth(
            connection_id=connection_id,
            status="healthy",
            last_checked_at=checked_at,
            last_success_at=checked_at,
            details="local fixture seed",
            healthy=True,
        ),
        metadata={
            "business": business.to_dict(),
            "created_at": checked_at,
            "updated_at": checked_at,
            "local_fixture": str(fixture_path),
        },
    )
    base_config = config or ConnectorConfig(output_dir=root_path)
    scoped = dataclasses.replace(
        base_config,
        output_dir=join_root(str(root_path), "connections", _slug(connection_id)),
        subscriptions=(DEFAULT_LOCAL_SUBSCRIPTION_ID,),
        management_groups=(),
        tenant_id=DEFAULT_LOCAL_TENANT_ID,
        connection_context=connection_context(connection),
    )
    manifest = IngestionService(
        scoped,
        source=FixtureAzureResourceGraphSource(payload),
        clock=now,
    ).run()
    finished = _iso(now())
    state = SyncState(
        status="succeeded",
        last_synced_at=finished,
        last_successful_sync_at=finished,
        run_id=str(manifest.get("lastRunId") or manifest.get("runId") or "local-seed"),
        source_version=str(manifest.get("queryVersion") or "local-fixture"),
        record_count=_record_count(manifest),
        attempts=1,
        message="local fixture seed completed",
    )
    seeded = dataclasses.replace(
        connection,
        sync_state=state,
        health=HealthEvaluator(clock=now).from_sync(connection, state),
        metadata={**connection.metadata, "updated_at": finished},
    )
    registry = ConnectionRegistry(str(root_path), store=FileRegistryStore(str(root_path)))
    if registry.exists(connection_id):
        registry.save(seeded)
    else:
        registry.add(seeded)
    return {
        "status": "seeded",
        "hermes_home": str(root_path),
        "fixture": str(fixture_path),
        "connection": registry.get(connection_id).to_dict(),
        "manifest": manifest,
    }


def inject_local_spn_connection(
    *,
    root: str | Path,
    env: dict[str, str] | None = None,
    connection_id: str = "local-spn",
    name: str = "Local SPN Subscription",
    sync: bool = False,
    config: ConnectorConfig | None = None,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Register a local SPN-backed connection from `.env.local` style env vars."""

    environment = env if env is not None else os.environ
    missing = [name for name in SPN_ENV_VARS if not _usable_env_value(environment.get(name))]
    if missing:
        raise ValueError(
            "Missing local SPN environment variable(s): " + ", ".join(missing)
        )

    now = clock or (lambda: datetime.now(UTC))
    root_path = Path(root).expanduser().resolve()
    timestamp = _iso(now())
    subscription_id = str(environment["AZURE_SUBSCRIPTION_ID"]).strip()
    tenant_id = str(environment["AZURE_TENANT_ID"]).strip()
    client_id = str(environment["AZURE_CLIENT_ID"]).strip()
    business = BusinessMetadata(
        business_service=str(environment.get("HERMES_LOCAL_BUSINESS_SERVICE") or "Local Azure Discovery"),
        application=str(environment.get("HERMES_LOCAL_APPLICATION") or "AI Ops Local"),
        environment=str(environment.get("HERMES_LOCAL_ENVIRONMENT") or "local"),
        project_owner=str(environment.get("HERMES_LOCAL_OWNER") or "Local Developer"),
        support_team=str(environment.get("HERMES_LOCAL_SUPPORT_TEAM") or "Local Developer"),
        criticality=str(environment.get("HERMES_LOCAL_CRITICALITY") or "medium"),
        region=str(environment.get("HERMES_LOCAL_REGION") or "local"),
        cost_center=str(environment.get("HERMES_LOCAL_COST_CENTER") or "local"),
    )
    connection = SubscriptionConnection(
        connection_id=connection_id,
        name=name,
        tenant_id=tenant_id,
        subscription_id=subscription_id,
        credential=CredentialReference(
            credential_id=f"{connection_id}-spn",
            kind="service_principal",
            client_id=client_id,
            tenant_id=tenant_id,
            secret_ref="env://AZURE_CLIENT_SECRET",
            scope=f"/subscriptions/{subscription_id}",
        ),
        sync_state=SyncState(status="pending", message="ready for local Azure discovery"),
        health=ConnectionHealth(
            connection_id=connection_id,
            status="unknown",
            last_checked_at=timestamp,
            details="SPN injected from local environment; run sync to discover resources",
            healthy=False,
        ),
        metadata={
            "business": business.to_dict(),
            "created_at": timestamp,
            "updated_at": timestamp,
            "local_spn": True,
        },
    )
    registry = ConnectionRegistry(str(root_path), store=FileRegistryStore(str(root_path)))
    if registry.exists(connection_id):
        existing = registry.get(connection_id)
        connection = dataclasses.replace(
            connection,
            sync_state=existing.sync_state or connection.sync_state,
            health=existing.health or connection.health,
            metadata={
                **existing.metadata,
                "business": business.to_dict(),
                "updated_at": timestamp,
                "local_spn": True,
            },
        )
        registry.save(connection)
        status = "updated"
    else:
        registry.add(connection)
        status = "created"
    if connection_id != DEFAULT_LOCAL_CONNECTION_ID and registry.exists(DEFAULT_LOCAL_CONNECTION_ID):
        registry.delete(DEFAULT_LOCAL_CONNECTION_ID)
    sync_result = None
    if sync:
        from onboarding.runtime import build_onboarding_service

        service = build_onboarding_service(config or ConnectorConfig(output_dir=root_path))
        sync_result = service.sync(connection_id, mode="initial")
    return {
        "status": status,
        "hermes_home": str(root_path),
        "connection": registry.get(connection_id).to_dict(),
        "sync": sync_result,
    }


def _slug(value: str) -> str:
    return "".join(char if char.isalnum() or char in "-_" else "-" for char in str(value)).strip("-")


def _usable_env_value(value: str | None) -> bool:
    text = str(value or "").strip()
    return bool(text) and not (text.startswith("<") and text.endswith(">"))


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


__all__ = [
    "DEFAULT_LOCAL_CONNECTION_ID",
    "FixtureAzureResourceGraphSource",
    "inject_local_spn_connection",
    "seed_local_environment",
]
