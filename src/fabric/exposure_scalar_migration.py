"""Finite, explicitly planned migration of the existing exposure typed table.

This composition has no cloud entrypoint or authority-discovery defaults.
The caller must supply independently reviewed authority/head-consumption proof
and observe its fingerprint while the existing publication lease is held.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from deltalake import Schema

from fabric.data_quality import DataQualityValidator
from fabric.dataset_mapper import container_exposure_ontology_rows
from fabric.schema_registry import schema_for
from storage.delta_writer import DeltaWriter
from storage.onelake_writer import OneLakeWriter

TABLE = "ontology_container_image_exposure_entities"
_TABLES = {
    "target": ("ontology", "container_image_exposure_entities"),
    "canonical": ("ontology", "entities"),
    "silver": ("silver", "container_image_exposure"),
    "registry": ("ontology", "container_registry_entities"),
}


def migration_rows_hash(rows: Sequence[Mapping[str, Any]]) -> str:
    """Hash full records independent of row order, without collapsing duplicates."""
    encoded = sorted(
        json.dumps(dict(row), sort_keys=True, separators=(",", ":"), allow_nan=False)
        for row in rows
    )
    return hashlib.sha256(
        json.dumps(encoded, separators=(",", ":")).encode()
    ).hexdigest()


@dataclass(frozen=True)
class ExposureScalarMigrationPlan:
    """Reviewed exact target, pinned inputs and external authority proof digest."""

    workspace_id: str
    lakehouse_id: str
    table_schema: str
    target_version: int
    canonical_version: int
    silver_version: int
    registry_version: int
    authority_fingerprint: str
    projected_rows_hash: str
    transaction_id: str


def migrate_exposure_scalars(
    onelake: OneLakeWriter,
    delta: DeltaWriter,
    plan: ExposureScalarMigrationPlan,
    *,
    observe_authority: Callable[[], str],
) -> dict[str, Any]:
    """Upgrade only the planned existing table under lease, CAS and readback.

    ``observe_authority`` must re-read the independently approved source/product
    pointers, definition and mutable-head consumption proof. A constant supplied
    by an operator is NOT live authority qualification. This module does not
    implement that observer, authorize execution, or advance any pointer.
    """
    if (
        onelake.workspace_id != plan.workspace_id
        or onelake.lakehouse_id != plan.lakehouse_id
        or onelake.table_schema != plan.table_schema
        or not plan.workspace_id
        or not plan.lakehouse_id
    ):
        raise ValueError("Migration target does not match reviewed plan")
    versions = {
        name: getattr(plan, f"{name}_version") for name in _TABLES
    }
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in versions.values()
    ):
        raise ValueError("Migration requires existing pinned Delta versions")
    for digest in (
        plan.authority_fingerprint, plan.projected_rows_hash, plan.transaction_id,
    ):
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("Migration requires reviewed SHA256 digests")
    uris = {name: onelake.table_uri(*parts) for name, parts in _TABLES.items()}
    target = uris["target"]
    digest = hashlib.sha256(json.dumps(
        {**vars(plan), "table_uri": target}, sort_keys=True,
    ).encode()).hexdigest()
    rollback_id = hashlib.sha256((plan.transaction_id + "-rollback").encode()).hexdigest()

    with onelake.sync_lock() as lock:
        def guard(*, target_version: int) -> None:
            lock.assert_held()
            if observe_authority() != plan.authority_fingerprint:
                raise RuntimeError("Migration authority or head-consumption proof changed")
            for name, uri in uris.items():
                expected = target_version if name == "target" else versions[name]
                if delta.version(uri) != expected:
                    raise RuntimeError(f"Migration pinned {name} version changed")
            lock.assert_held()

        lock.assert_held()
        if delta.committed_transaction(
            target, transaction_id=rollback_id, transaction_digest=digest,
        ) is not None:
            raise RuntimeError("Migration transaction was rolled back; new review required")
        committed = delta.committed_transaction(
            target, transaction_id=plan.transaction_id, transaction_digest=digest,
        )
        current = committed.version if committed is not None else plan.target_version
        if current is None:
            raise RuntimeError("Migration commit has no Delta version")
        guard(target_version=current)
        previous = delta.read(target, version=plan.target_version)
        before_description = delta.describe(target, version=plan.target_version)
        expected = _project(
            previous,
            delta.read(uris["canonical"], version=plan.canonical_version),
            delta.read(uris["silver"], version=plan.silver_version),
            delta.read(uris["registry"], version=plan.registry_version),
        )
        if migration_rows_hash(expected) != plan.projected_rows_hash:
            raise ValueError("Migration projected full records differ from reviewed hash")
        generic_schema = json.loads(Schema.from_arrow(schema_for("ontology_entities")).to_json())
        expected_schema = json.loads(Schema.from_arrow(schema_for(TABLE)).to_json())
        if before_description["schema"] not in (generic_schema, expected_schema):
            raise ValueError("Migration found an unexpected existing typed schema")

        def verify(version: int) -> None:
            guard(target_version=version)
            if delta.describe(target, version=version)["schema"] != expected_schema:
                raise RuntimeError("Migration readback schema mismatch")
            if migration_rows_hash(delta.read(target, version=version)) != plan.projected_rows_hash:
                raise RuntimeError("Migration readback full-record mismatch")
            guard(target_version=version)

        if committed is not None:
            verify(current)
            return _receipt("replayed", plan, digest, current, len(expected))
        if (
            migration_rows_hash(previous) == plan.projected_rows_hash
            and before_description["schema"] == expected_schema
        ):
            verify(current)
            return _receipt("unchanged", plan, digest, current, len(expected))
        guard(target_version=plan.target_version)
        try:
            delta.write(
                target, expected, mode="overwrite", schema=schema_for(TABLE),
                key_columns=("resource_id",), expected_version=plan.target_version,
                transaction_id=plan.transaction_id, transaction_digest=digest,
            )
        except Exception as error:
            # A timeout after commit must be reconciled, never blindly replayed.
            committed = delta.committed_transaction(
                target, transaction_id=plan.transaction_id, transaction_digest=digest,
            )
            if committed is None:
                raise RuntimeError(
                    "Migration write failed without proven commit; no automatic retry"
                ) from error
        else:
            committed = delta.committed_transaction(
                target, transaction_id=plan.transaction_id, transaction_digest=digest,
            )
        if committed is None or committed.version is None:
            raise RuntimeError("Migration write outcome unproved; manual reconciliation required")
        try:
            verify(committed.version)
        except Exception as error:
            # Never restore over an intervening writer or after losing the lease.
            lock.assert_held()
            if delta.version(target) != committed.version:
                raise RuntimeError(
                    "Migration failed; intervening writer prevents rollback"
                ) from error
            try:
                restored = delta.restore(
                    target, plan.target_version, expected_version=committed.version,
                    transaction_id=rollback_id, transaction_digest=digest,
                )
            except Exception as rollback_error:
                raise RuntimeError(
                    "Migration rollback failed; manual reconciliation required"
                ) from rollback_error
            lock.assert_held()
            rollback = delta.committed_transaction(
                target, transaction_id=rollback_id, transaction_digest=digest,
            )
            if (
                rollback is None or rollback.version != restored
                or delta.version(target) != restored
                or delta.describe(target, version=restored)["schema"] != before_description["schema"]
                or migration_rows_hash(delta.read(target, version=restored))
                != migration_rows_hash(previous)
            ):
                raise RuntimeError("Migration rollback readback failed") from error
            raise RuntimeError("Migration qualification failed; original table restored") from error
        return _receipt("completed", plan, digest, committed.version, len(expected))


def _index(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    result = {}
    for row in rows:
        key = row["resource_id"]
        if not isinstance(key, str) or not key or key in result:
            raise ValueError("Migration duplicate or missing resource key")
        result[key] = dict(row)
    return result


def _connection(row: Mapping[str, Any]) -> str:
    payload = json.loads(row["payload_json"])
    if not isinstance(payload, dict):
        raise TypeError("Migration payload must be a JSON object")
    for key, field in (("tenantId", "tenant_id"), ("subscriptionId", "subscription_id")):
        if key in payload and payload[key] != row[field]:
            raise ValueError("Migration authority payload scope mismatch")
    if "id" in payload:
        if not isinstance(payload["id"], str):
            raise TypeError("Migration authority payload ID must be a string")
        if payload["id"].casefold() != row["resource_id"].casefold():
            raise ValueError("Migration authority payload key mismatch")
    values = [
        payload[name] for name in (
            "connection_id", "connectionId",
            "subscription_connection_id", "subscriptionConnectionId",
        ) if payload.get(name) not in (None, "")
    ]
    if not values or any(not isinstance(value, str) or not value for value in values):
        raise ValueError("Migration requires explicit connection scope")
    if len(set(values)) != 1:
        raise ValueError("Migration connection scopes conflict")
    return values[0]


def _project(previous, canonical, silver, registries):
    active = _index([
        row for row in canonical
        if row["entity_type"] == "ContainerImageExposure"
        and row["lifecycle_status"] == "active"
    ])
    typed = _index(previous)
    if set(active) != set(typed):
        raise ValueError("Migration all-scope typed membership differs from authority")
    names = schema_for("ontology_entities").names
    for key, row in typed.items():
        if set(row) not in (set(names), set(schema_for(TABLE).names)):
            raise ValueError("Migration unexpected typed record shape")
        if {name: row[name] for name in names} != active[key]:
            raise ValueError("Migration original fields differ from canonical authority")
    rows = container_exposure_ontology_rows(list(active.values()))
    projected = _index(rows)
    for key, row in typed.items():
        if "registry_resource_id" in row and row != projected[key]:
            raise ValueError("Migration existing scalars conflict with authority")
    silver_by_id = _index(silver)
    registry_by_id = _index([
        row for row in registries if row["lifecycle_status"] == "active"
    ])
    for row in rows:
        key = row["resource_id"]
        source = silver_by_id.get(key)
        registry = registry_by_id.get(row["registry_resource_id"])
        if source is None or registry is None or not row["registry_resource_id"]:
            raise ValueError("Migration missing explicit Silver or registry authority")
        scope = (row["tenant_id"], row["subscription_id"], row["connection_id"])
        for authority in (source, registry):
            if scope != (
                authority["tenant_id"], authority["subscription_id"],
                _connection(authority),
            ):
                raise ValueError("Migration cross-scope endpoint or Silver mapping")
        if source["registry_resource_id"] != row["registry_resource_id"]:
            raise ValueError("Migration explicit Silver registry key mismatch")
    if not DataQualityValidator().validate_table(TABLE, rows).passed:
        raise ValueError("Migration typed records failed data quality")
    return rows


def _receipt(status, plan, digest, version, count):
    return {
        "status": status, "table": TABLE, "transaction_id": plan.transaction_id,
        "transaction_digest": digest, "before_version": plan.target_version,
        "version": version, "rows": count,
        "projected_rows_hash": plan.projected_rows_hash,
        "authority_fingerprint": plan.authority_fingerprint,
        "native_apply": False, "endpoint_quality_qualified": False,
    }
