"""Scope-enforced Fabric medallion health and capability routes."""

from __future__ import annotations

import json
import os
from typing import Any

from fastapi import APIRouter

from fabric.auth import build_credential, build_delta_storage_options
from fabric.capacity_health import check_capacity_state
from fabric.config import FabricRuntimeConfig
from fabric.data_access_roles import list_roles
from fabric.lineage import entity_lineage_summary, native_lineage_url
from fabric.medallion_health import _latest_per_scope, dataset_contract, dataset_status
from fabric.table_maintenance import last_maintenance_status
from ontology.publication_state import PublicationAttemptRecord
from operations.gold_grounding_specialist import gold_grounding_configured
from storage.datasets import DatasetStore
from storage.delta_writer import DeltaWriter
from storage.onelake_writer import OneLakeWriter

from ..dependencies import Context, ReadScope
from ..errors import not_found
from ..evidence import CONFIDENCE_HIGH, Evidence, envelope
from ..scope import Scope

router = APIRouter(prefix="/api/v1/fabric-medallion", tags=["fabric-medallion"])

SOURCE_ENGINE = "fabric.medallion_health"
SOURCE_TABLE = "metadata_source_status"
MANIFEST_ENGINE = "ontology.publication_manifest"
MANIFEST_TABLE = "metadata_publication_manifest"
GOVERNANCE_ENGINE = "fabric.data_quality"
GOVERNANCE_TABLE = "metadata_quality_reports"
INGESTION_ENGINE = "onboarding.sync"
INGESTION_TABLE = "metadata_ingestion_state"
CAPABILITIES_ENGINE = "fabric.medallion_capabilities"


def _runtime_config() -> FabricRuntimeConfig | None:
    config_path = os.environ.get("AIOPS_FABRIC_CONFIG", "fabric.config.yaml").strip() or "fabric.config.yaml"
    try:
        return FabricRuntimeConfig.load(config_path)
    except Exception:  # noqa: BLE001 - missing Fabric config degrades to JSON snapshot reads only
        return None


def _evidence(*, source_engine: str, source_table: str, timestamp: str = "", freshness: str | None = None) -> Evidence:
    return Evidence(
        source_engine=source_engine,
        source_table=source_table,
        timestamp="" if freshness == "unknown" else timestamp,
        confidence=CONFIDENCE_HIGH,
        freshness=freshness or "unknown",
    )


def _status_timestamp(row: dict[str, Any]) -> str:
    return str(row.get("ingested_at") or row.get("observed_at") or row.get("timestamp") or "")


def _parse_requested_scope(row: dict[str, Any]) -> dict[str, list[str]]:
    value: Any = row.get("requested_scope")
    if not isinstance(value, dict):
        raw = row.get("requested_scope_json")
        if isinstance(raw, str) and raw:
            try:
                value = json.loads(raw)
            except json.JSONDecodeError:
                value = {}
    if not isinstance(value, dict):
        value = {}
    parsed: dict[str, list[str]] = {}
    for name, values in value.items():
        if isinstance(values, (list, tuple, set)):
            items = [str(item) for item in values if str(item)]
            if items:
                parsed[str(name)] = items
    return parsed


def _scope_attributes(row: dict[str, Any]) -> dict[str, str]:
    scope_payload = _parse_requested_scope(row)
    attributes: dict[str, str] = {}
    for dimension in (
        "business_service",
        "application",
        "environment",
        "subscription",
        "subscription_connection",
        "owner",
        "support_team",
        "region",
        "criticality",
    ):
        values = scope_payload.get(dimension) or []
        if values:
            attributes[dimension] = values[0]
    if row.get("subscription_id"):
        attributes["subscription"] = str(row.get("subscription_id") or "")
    if row.get("subscription_connection"):
        attributes["subscription_connection"] = str(row.get("subscription_connection") or "")
    return attributes


def _row_visible(scope: Scope, row: dict[str, Any]) -> bool:
    if scope.is_unrestricted():
        return True
    attributes = _scope_attributes(row)
    requested = _parse_requested_scope(row)
    for dimension, allowed in scope.to_dict().items():
        values = requested.get(dimension) or []
        if dimension in {"subscription", "subscription_connection"} and (
            row.get("subscription_id" if dimension == "subscription" else "subscription_connection")
        ):
            values = [attributes[dimension]]
        if not values or not {value.strip().casefold() for value in values}.issubset(
            {value.casefold() for value in allowed}
        ):
            return False
    return bool(attributes) and scope.matches(attributes)


def _lakehouse_delta_rows(table_name: str) -> list[dict[str, Any]]:
    config = _runtime_config()
    if config is None:
        return []
    layer, separator, logical_name = table_name.partition("_")
    if not separator or not layer or not logical_name:
        return []
    workspace_id = config.workspace_id or config.workspace_name
    lakehouse_id = config.lakehouse_id or config.lakehouse_name
    if config.local_onelake_root is not None:
        onelake = OneLakeWriter(
            workspace_id,
            lakehouse_id,
            table_schema=config.table_schema,
            local_root=config.local_onelake_root,
        )
        return DeltaWriter().read(onelake.table_uri(layer, logical_name))
    if not workspace_id or not lakehouse_id:
        return []
    credential = build_credential(config.auth)
    storage_options = build_delta_storage_options(credential)
    onelake = OneLakeWriter(
        workspace_id,
        lakehouse_id,
        table_schema=config.table_schema,
        credential=credential,
        storage_options=storage_options,
    )
    return DeltaWriter(
        storage_options=storage_options,
        storage_options_provider=lambda: build_delta_storage_options(credential),
    ).read(onelake.table_uri(layer, logical_name))


def _connection_rows(context: Context) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
    rows: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    for summary in context.onboarding.list(include_disabled=False):
        detail = context.onboarding.detail(str(summary.get("connection_id") or ""))
        dataset_root = str(detail.get("dataset_root") or "")
        if not dataset_root:
            continue
        status_rows = DatasetStore(dataset_root).read_dataset("metadata_source_status")
        normalized = []
        for row in status_rows:
            current = dict(row)
            # The connection registry is authoritative for scope identity.
            # Published rows can contain stale or missing identity fields after
            # a connection is recreated, so always project the current values.
            current["subscription_id"] = str(detail.get("subscription_id") or "")
            current["subscription_connection"] = str(detail.get("connection_id") or "")
            normalized.append(current)
        rows.append((detail, normalized))
    return rows


def _metadata_source_status_rows(context: Context) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for _detail, status_rows in _connection_rows(context):
        rows.extend(status_rows)
    if not rows:
        rows.extend(_lakehouse_delta_rows("metadata_source_status"))
    return rows


def _manifest_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("subscription_id") or ""),
        str(row.get("subscription_connection") or ""),
        str(row.get("projection_name") or ""),
    )


def _manifest_row_visible(scope: Scope, row: dict[str, Any]) -> bool:
    if scope.is_unrestricted():
        return True
    attributes = _scope_attributes(row)
    if attributes.get("subscription") == "system":
        return True
    return bool(attributes) and scope.matches(attributes)


def _manifest_subscription_id(scope: Scope, row: dict[str, Any]) -> str:
    attributes = _scope_attributes(row)
    subscription = attributes.get("subscription", "")
    if subscription == "system":
        requested_subscriptions = scope.to_dict().get("subscription") or []
        if requested_subscriptions:
            return str(requested_subscriptions[0])
    return subscription


def _metadata_publication_manifest_rows(context: Context) -> list[dict[str, Any]]:
    latest_by_projection: dict[tuple[str, str, str], dict[str, Any]] = {}
    for detail, _status_rows in _connection_rows(context):
        dataset_root = str(detail.get("dataset_root") or "")
        if not dataset_root:
            continue
        for row in DatasetStore(dataset_root).read_dataset("metadata_publication_manifest"):
            projection = str(row.get("projection_name") or "")
            if not projection:
                continue
            current = dict(row)
            if detail.get("subscription_id"):
                current["subscription_id"] = str(detail.get("subscription_id") or "")
            if detail.get("connection_id"):
                current["subscription_connection"] = str(detail.get("connection_id") or "")
            key = _manifest_key(current)
            previous = latest_by_projection.get(key)
            if previous is None or str(current.get("updated_at") or "") >= str(
                previous.get("updated_at") or ""
            ):
                latest_by_projection[key] = current
    if not latest_by_projection:
        for row in _lakehouse_delta_rows("metadata_publication_manifest"):
            projection = str(row.get("projection_name") or "")
            if not projection:
                continue
            current = dict(row)
            key = _manifest_key(current)
            previous = latest_by_projection.get(key)
            if previous is None or str(current.get("updated_at") or "") >= str(
                previous.get("updated_at") or ""
            ):
                latest_by_projection[key] = current
    return sorted(
        latest_by_projection.values(),
        key=lambda row: (
            str(row.get("subscription_id") or "").casefold(),
            str(row.get("subscription_connection") or "").casefold(),
            str(row.get("projection_name") or "").casefold(),
        ),
    )


def _connection_scope_attributes(detail: dict[str, Any]) -> dict[str, str]:
    return {
        "business_service": str(detail.get("business_service") or ""),
        "application": str(detail.get("application") or ""),
        "environment": str(detail.get("environment") or ""),
        "subscription": str(detail.get("subscription_id") or ""),
        "subscription_connection": str(detail.get("connection_id") or ""),
        "owner": str(detail.get("owner") or ""),
        "support_team": str(detail.get("support_team") or ""),
        "region": str(detail.get("region") or ""),
        "criticality": str(detail.get("criticality") or ""),
    }


def _connection_visible(scope: Scope, detail: dict[str, Any]) -> bool:
    if scope.is_unrestricted():
        return True
    attributes = {key: value for key, value in _connection_scope_attributes(detail).items() if value}
    return bool(attributes) and scope.matches(attributes)


def _metadata_quality_report_rows(context: Context, scope: Scope) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for detail, _status_rows in _connection_rows(context):
        if not _connection_visible(scope, detail):
            continue
        dataset_root = str(detail.get("dataset_root") or "")
        if not dataset_root:
            continue
        for row in DatasetStore(dataset_root).read_dataset("metadata_quality_reports"):
            current = dict(row)
            current.setdefault("subscription_id", str(detail.get("subscription_id") or ""))
            current.setdefault("subscription_connection", str(detail.get("connection_id") or ""))
            rows.append(current)
    if not rows:
        rows.extend(
            row
            for row in _lakehouse_delta_rows("metadata_quality_reports")
            if _row_visible(scope, row)
        )
    return rows


def _role_summary(role: dict[str, Any]) -> dict[str, Any]:
    permissions = role.get("permissions")
    if not isinstance(permissions, list):
        permissions = []
    return {
        "name": str(role.get("name") or role.get("role") or ""),
        "permission_count": len(permissions),
    }


def _parse_quality_report(value: Any) -> list[dict[str, Any]]:
    parsed: Any = value
    if isinstance(parsed, str):
        try:
            parsed = json.loads(parsed)
        except json.JSONDecodeError:
            parsed = []
    if isinstance(parsed, dict):
        reports = parsed.get("reports")
        if isinstance(reports, list):
            parsed = reports
    if not isinstance(parsed, list):
        return []
    return [row for row in parsed if isinstance(row, dict)]


def _int_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _publication_attempt_rows(context: Context, scope: Scope) -> list[dict[str, Any]]:
    if not any(_connection_visible(scope, detail) for detail, _rows in _connection_rows(context)):
        return []
    coordinator = getattr(context.onboarding, "sync_coordinator", None)
    store = getattr(coordinator, "publication_state_store", None)
    if store is None:
        return []
    records = store.list()
    mapped: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, PublicationAttemptRecord):
            continue
        outcome = str(record.outcome or "")
        if outcome == "failed":
            status = "failed"
        elif outcome == "rejected":
            status = "unavailable"
        elif outcome == "succeeded":
            status = "succeeded"
        else:
            status = "unknown"
        mapped.append(
            {
                "projection_name": record.ontology_name,
                "status": status,
                "attempted_at": record.attempted_at,
                "attempts": int(record.attempt_count),
                "retry_eligible": bool(record.retryable) if status == "failed" else False,
                "message": str(record.error or ""),
                "source": "publication-state",
            }
        )
    return sorted(mapped, key=lambda row: str(row.get("attempted_at") or ""), reverse=True)


def _capacity_config(context: Context, scope: Scope) -> dict[str, str]:
    config = _runtime_config()
    scope_subscriptions = scope.to_dict().get("subscription") or []
    subscription_id = str(
        getattr(getattr(config, "capacity", None), "subscription_id", "")
        or os.environ.get("AIOPS_FABRIC_CAPACITY_SUBSCRIPTION_ID", "")
        or (scope_subscriptions[0] if scope_subscriptions else "")
    ).strip()
    return {
        "subscription_id": subscription_id,
        "resource_group": str(
            getattr(getattr(config, "capacity", None), "resource_group", "")
            or os.environ.get("AIOPS_FABRIC_CAPACITY_RESOURCE_GROUP", "")
        ).strip(),
        "capacity_name": str(
            getattr(getattr(config, "capacity", None), "capacity_name", "")
            or os.environ.get("AIOPS_FABRIC_CAPACITY_NAME", "")
        ).strip(),
        "workspace_id": str(getattr(config, "workspace_id", "") or os.environ.get("FABRIC_WORKSPACE_ID", "")).strip(),
        "lakehouse_id": str(getattr(config, "lakehouse_id", "")).strip(),
    }


def _semantic_entities(context: Context) -> dict[str, dict[str, Any]]:
    semantic = context.resolve_provider("semantic", optional=True)
    indexes = getattr(semantic, "indexes", None)
    entities = getattr(indexes, "entities", None)
    if not isinstance(entities, dict):
        return {}
    normalized: dict[str, dict[str, Any]] = {}
    for key, value in entities.items():
        if not key:
            continue
        if isinstance(value, dict):
            normalized[str(key).casefold()] = dict(value)
        else:
            dump = getattr(value, "model_dump", None)
            if callable(dump):
                payload = dump(mode="json")
                if isinstance(payload, dict):
                    normalized[str(key).casefold()] = payload
    return normalized


def _semantic_readiness(context: Context, scope: Scope) -> dict[str, str]:
    """Keep model readiness unknown without model-specific deployment evidence.

    Publication attempts describe ontology projections, not semantic-model
    definitions or native Ontology readiness; their outcomes remain in history.
    """
    return {
        "status": "unknown",
        "reason": "no_recorded_semantic_model_deployment_result",
    }


def _scoped_source_rows(context: Context, scope: Scope) -> list[dict[str, Any]]:
    return [row for row in _metadata_source_status_rows(context) if _row_visible(scope, row)]


def _recorded_dataset_evidence(
    rows: list[dict[str, Any]], status: dict[str, Any]
) -> dict[str, Any]:
    """Project source receipts on the same partition selection and freshness as status."""
    sources = []
    for row, budget in zip(rows, status["freshness_budget"]["sources"], strict=True):
        generation = str(row.get("effective_generation") or "") or None
        last_success = str(row.get("last_success_at") or "") or None
        recorded_good = bool(generation and last_success)
        sources.append({
            "scope": budget["scope"],
            "partition_key": budget["partition_key"] or None,
            "observed_at": budget["status_at"] or None,
            "freshness": budget["state"],
            "recorded_status": str(row.get("status") or "unknown"),
            "provider_status": str(row.get("provider_status") or "") or None,
            "last_attempt": {
                "status": str(row.get("status") or "unknown"),
                "generation_id": str(row.get("attempted_generation") or "") or None,
                "attempted_at": str(row.get("attempted_at") or "") or None,
                "reason_code": str(row.get("safe_error_code") or "") or None,
            },
            "last_good": {
                "status": "recorded" if recorded_good else "unknown",
                "generation_id": generation,
                "observed_at": last_success,
                "reason_code": (
                    "source_last_good_recorded" if recorded_good else "no_recorded_source_last_good"
                ),
            },
            "lineage_ref": str(row.get("lineage_ref") or "") or None,
        })
    return {
        "evidence_mode": "recorded_metadata",
        "generation_kind": "source_partition",
        "sources": sources,
    }


def _unrecorded_readiness_evidence() -> dict[str, Any]:
    """Expose stage boundaries without inventing scoped publication or model receipts."""
    def unknown(reason: str) -> dict[str, Any]:
        return {
            "status": "unknown",
            "evidence_mode": "not_recorded",
            "reason_code": reason,
            "last_attempt": None,
            "last_good": None,
        }

    return {
        "projection_publication": unknown("no_scoped_publication_recorder"),
        "native_ontology": unknown("no_recorded_native_ontology_receipt"),
        "semantic_model": {
            "definition_validation": unknown("no_recorded_semantic_definition_validation"),
            "publication": unknown("no_recorded_semantic_model_publication"),
            "query_qualification": unknown("no_recorded_semantic_query_qualification"),
        },
    }


def _registered_tables(rows: list[dict[str, Any]]) -> list[str]:
    names = {
        str(row.get("source_family") or row.get("table_name") or "")
        for row in rows
        if str(row.get("source_family") or row.get("table_name") or "")
    }
    return sorted(names, key=str.casefold)


def _layer_for_table(table_name: str) -> str:
    if table_name.startswith("bronze_"):
        return "bronze"
    if table_name.startswith("silver_"):
        return "silver"
    if table_name.startswith("gold_"):
        return "gold"
    return ""


@router.get("/layers", summary="Fabric medallion layer summary")
def medallion_layers(context: Context, scope: ReadScope) -> dict[str, Any]:
    rows = _scoped_source_rows(context, scope)
    layers = {
        "bronze": {"healthy": 0, "total": 0},
        "silver": {"healthy": 0, "total": 0},
        "gold": {"healthy": 0, "total": 0},
    }
    tables: dict[str, list[str]] = {"bronze": [], "silver": [], "gold": []}
    freshness_states: list[str] = []
    for table_name in _registered_tables(rows):
        layer = _layer_for_table(table_name)
        if not layer:
            continue
        tables[layer].append(table_name)
        status = dataset_status(table_name, source_status=rows)
        freshness_states.append(status["freshness"])
        layers[layer]["total"] += 1
        if str(status.get("availability") or "") in {"healthy", "healthy-empty"}:
            layers[layer]["healthy"] += 1
    return envelope(
        {"layers": layers, "tables": tables},
        evidence=_evidence(
            source_engine=SOURCE_ENGINE,
            source_table=SOURCE_TABLE,
            timestamp=max((_status_timestamp(row) for row in rows), default=""),
            freshness="stale" if "stale" in freshness_states else (
                "unknown" if not freshness_states or "unknown" in freshness_states else "fresh"
            ),
        ),
        scope=scope.to_dict(),
    )


@router.get("/datasets/{table_name}", summary="Fabric medallion dataset status")
def medallion_dataset(table_name: str, context: Context, scope: ReadScope) -> dict[str, Any]:
    """Return scoped metadata health and separately recorded source-generation receipts."""
    rows = _scoped_source_rows(context, scope)
    table_names = set(_registered_tables(rows))
    if table_name not in table_names:
        raise not_found(table_name, "dataset")
    table_rows = _latest_per_scope(rows, table_name)
    status = dataset_status(table_name, source_status=table_rows)
    status["recorded_evidence"] = _recorded_dataset_evidence(table_rows, status)
    return envelope(
        status,
        evidence=_evidence(
            source_engine=SOURCE_ENGINE,
            source_table=SOURCE_TABLE,
            timestamp=max((_status_timestamp(row) for row in table_rows), default=""),
            freshness=status["freshness"],
        ),
        scope=scope.to_dict(),
    )


@router.get("/datasets/{table_name}/contract", summary="Declared Fabric dataset contract and source diagnostics")
def medallion_dataset_contract(table_name: str, context: Context, scope: ReadScope) -> dict[str, Any]:
    """Expose registry declarations only for a dataset registered in the effective scope."""
    rows = _scoped_source_rows(context, scope)
    if table_name not in set(_registered_tables(rows)):
        raise not_found(table_name, "dataset")
    return envelope(
        dataset_contract(table_name, source_status=rows),
        evidence=[
            _evidence(source_engine="fabric.schema_registry", source_table=table_name),
            _evidence(source_engine=SOURCE_ENGINE, source_table=SOURCE_TABLE),
        ],
        scope=scope.to_dict(),
    )


@router.get("/manifest", summary="Fabric publication manifest dispositions")
def medallion_manifest(context: Context, scope: ReadScope) -> dict[str, Any]:
    rows = [
        row
        for row in _metadata_publication_manifest_rows(context)
        if _manifest_row_visible(scope, row)
    ]
    entries = [
        {
            "projection_name": str(row.get("projection_name") or ""),
            "disposition": str(row.get("disposition") or "unknown"),
            "compatibility_version": row.get("compatibility_version"),
            "retired_reason": row.get("retired_reason"),
            "registered_at": str(row.get("registered_at") or ""),
            "updated_at": str(row.get("updated_at") or ""),
            "subscription_id": _manifest_subscription_id(scope, row),
            "subscription_connection": _scope_attributes(row).get("subscription_connection", ""),
        }
        for row in rows
        if str(row.get("projection_name") or "")
    ]
    return envelope(
        {"entries": entries},
        evidence=_evidence(
            source_engine=MANIFEST_ENGINE,
            source_table=MANIFEST_TABLE,
            timestamp=max((str(row.get("updated_at") or "") for row in rows), default=""),
        ),
        scope=scope.to_dict(),
    )


@router.get("/governance", summary="Fabric governance gaps from data-quality reports")
def medallion_governance(context: Context, scope: ReadScope) -> dict[str, Any]:
    rows = _metadata_quality_report_rows(context, scope)
    by_table: dict[str, dict[str, int | str]] = {}
    ownership_gap_count = 0
    tag_gap_count = 0
    referential_blockers = 0

    for row in rows:
        for report in _parse_quality_report(row.get("report_json")):
            table_name = str(report.get("table_name") or "")
            if not table_name:
                continue
            counts = report.get("rule_counts")
            if not isinstance(counts, dict):
                continue
            ownership = _int_value(counts.get("ownership_coverage"))
            tags = _int_value(counts.get("tag_coverage"))
            referential = _int_value(counts.get("orphan_relationships"))
            ownership_gap_count += ownership
            tag_gap_count += tags
            referential_blockers += referential
            current = by_table.setdefault(
                table_name,
                {
                    "table_name": table_name,
                    "ownership_gap_count": 0,
                    "tag_gap_count": 0,
                    "referential_integrity_blockers": 0,
                },
            )
            current["ownership_gap_count"] = _int_value(current["ownership_gap_count"]) + ownership
            current["tag_gap_count"] = _int_value(current["tag_gap_count"]) + tags
            current["referential_integrity_blockers"] = (
                _int_value(current["referential_integrity_blockers"]) + referential
            )

    gaps = sorted(
        by_table.values(),
        key=lambda entry: (
            -_int_value(entry.get("referential_integrity_blockers")),
            -_int_value(entry.get("ownership_gap_count")),
            str(entry.get("table_name") or "").casefold(),
        ),
    )
    return envelope(
        {
            "ownership_gap_count": ownership_gap_count,
            "tag_gap_count": tag_gap_count,
            "referential_integrity_blockers": referential_blockers,
            "gaps": gaps,
        },
        evidence=_evidence(
            source_engine=GOVERNANCE_ENGINE,
            source_table=GOVERNANCE_TABLE,
            timestamp=max((_status_timestamp(row) for row in rows), default=""),
        ),
        scope=scope.to_dict(),
    )


@router.get("/ingestion-history", summary="Fabric ingestion and publication run history")
def medallion_ingestion_history(context: Context, scope: ReadScope) -> dict[str, Any]:
    source_rows = _scoped_source_rows(context, scope)
    runs: list[dict[str, Any]] = []
    for row in source_rows:
        raw_status = str(row.get("status") or "").casefold()
        availability = str(row.get("availability") or "").casefold()
        if availability == "unavailable" or raw_status == "unavailable":
            status = "unavailable"
            retry_eligible = False
        elif raw_status in {"failed", "error", "cancelled", "canceled"}:
            status = "failed"
            retry_eligible = True
        elif raw_status in {"succeeded", "completed", "success"}:
            status = "succeeded"
            retry_eligible = False
        else:
            status = "unknown"
            retry_eligible = False
        runs.append(
            {
                "projection_name": str(row.get("source_family") or row.get("table_name") or ""),
                "status": status,
                "attempted_at": _status_timestamp(row),
                "attempts": _int_value(row.get("attempts") or 1),
                "retry_eligible": retry_eligible,
                "message": str(row.get("error") or ""),
                "source": "source-status",
            }
        )
    runs.extend(_publication_attempt_rows(context, scope))
    ordered = sorted(runs, key=lambda row: str(row.get("attempted_at") or ""), reverse=True)
    return envelope(
        {"runs": ordered},
        evidence=_evidence(
            source_engine=INGESTION_ENGINE,
            source_table=INGESTION_TABLE,
            timestamp=max((str(row.get("attempted_at") or "") for row in ordered), default=""),
        ),
        scope=scope.to_dict(),
    )


@router.get("/capabilities", summary="Fabric medallion platform capabilities snapshot")
def medallion_capabilities(context: Context, scope: ReadScope) -> dict[str, Any]:
    """Return scoped capability signals without treating settings as live proof."""
    config = _capacity_config(context, scope)
    source_rows = _scoped_source_rows(context, scope)
    runtime_config = _runtime_config()
    capacity_credential = (
        build_credential(runtime_config.auth)
        if runtime_config is not None and runtime_config.auth.mode == "managed_identity"
        else None
    )

    raw_capacity = check_capacity_state(
        subscription_id=str(config.get("subscription_id") or ""),
        resource_group=str(config.get("resource_group") or ""),
        capacity_name=str(config.get("capacity_name") or ""),
        credential=capacity_credential,
    )
    capacity = dict(raw_capacity)
    capacity.setdefault("status", str(raw_capacity.get("state") or "unknown"))

    workspace_id = str(config.get("workspace_id") or "")
    lakehouse_id = str(config.get("lakehouse_id") or "")
    try:
        roles = list_roles(workspace_id, lakehouse_id)
        role_state = {
            "status": "available",
            "total_roles": len(roles),
            "roles": [_role_summary(role) for role in roles if isinstance(role, dict)],
        }
    except Exception:  # noqa: BLE001 - role summary is best-effort and read-only
        role_state = {"status": "unavailable", "total_roles": 0, "roles": []}

    try:
        maintenance = last_maintenance_status(workspace_id, lakehouse_id)
    except Exception:  # noqa: BLE001 - maintenance read degrades to unknown
        maintenance = {"status": "unknown", "last_run_at": "", "activity_name": ""}

    entities = _semantic_entities(context)
    lineage_rows: list[dict[str, Any]] = []
    for table_name in _registered_tables(source_rows):
        table_rows = [
            row
            for row in source_rows
            if str(row.get("source_family") or row.get("table_name") or "") == table_name
        ]
        lineage_ref = next(
            (
                str(row.get("lineage_ref") or "")
                for row in table_rows
                if str(row.get("lineage_ref") or "")
            ),
            "",
        )
        lineage_rows.append(
            {
                "table_name": table_name,
                "status": str(dataset_status(table_name, source_status=source_rows).get("availability") or "unknown"),
                "lineage_ref": lineage_ref,
                "lineage": entity_lineage_summary(lineage_ref, entities),
            }
        )
    try:
        workspace_lineage_url = native_lineage_url(workspace_id)
    except Exception:  # noqa: BLE001 - no workspace configured
        workspace_lineage_url = ""

    data_agent_configured = bool(gold_grounding_configured(scope))
    capabilities = {
        "capacity": capacity,
        "data_access_roles": role_state,
        "maintenance": maintenance,
        "semantic_readiness": _semantic_readiness(context, scope),
        "readiness_evidence": _unrecorded_readiness_evidence(),
        "data_agent_readiness": {
            "status": "unknown" if data_agent_configured else "disabled",
            "configured": data_agent_configured,
            "reason": "reachability_not_verified" if data_agent_configured else "not_configured",
        },
        "lineage": {
            "native_lineage_url": workspace_lineage_url,
            "datasets": lineage_rows,
        },
    }
    return envelope(
        capabilities,
        evidence=_evidence(
            source_engine=CAPABILITIES_ENGINE,
            source_table=SOURCE_TABLE,
            timestamp=max((_status_timestamp(row) for row in source_rows), default=""),
        ),
        scope=scope.to_dict(),
    )
