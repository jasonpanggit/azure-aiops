"""Scope-enforced Fabric medallion health and capability routes."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter

from fabric.medallion_health import dataset_status
from storage.datasets import DatasetStore

from ..dependencies import Context, ReadScope
from ..errors import not_found
from ..evidence import CONFIDENCE_HIGH, Evidence, envelope
from ..scope import Scope

router = APIRouter(prefix="/api/v1/fabric-medallion", tags=["fabric-medallion"])

SOURCE_ENGINE = "fabric.medallion_health"
SOURCE_TABLE = "metadata_source_status"
MANIFEST_ENGINE = "ontology.publication_manifest"
MANIFEST_TABLE = "metadata_publication_manifest"


def _evidence(*, source_engine: str, source_table: str, timestamp: str = "") -> Evidence:
    return Evidence(
        source_engine=source_engine,
        source_table=source_table,
        timestamp=timestamp,
        confidence=CONFIDENCE_HIGH,
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
    if "subscription" not in attributes and row.get("subscription_id"):
        attributes["subscription"] = str(row.get("subscription_id") or "")
    if "subscription_connection" not in attributes and row.get("subscription_connection"):
        attributes["subscription_connection"] = str(row.get("subscription_connection") or "")
    return attributes


def _row_visible(scope: Scope, row: dict[str, Any]) -> bool:
    if scope.is_unrestricted():
        return True
    attributes = _scope_attributes(row)
    return bool(attributes) and scope.matches(attributes)


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
            current.setdefault("subscription_id", str(detail.get("subscription_id") or ""))
            current.setdefault(
                "subscription_connection", str(detail.get("connection_id") or "")
            )
            normalized.append(current)
        rows.append((detail, normalized))
    return rows


def _metadata_source_status_rows(context: Context) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for _detail, status_rows in _connection_rows(context):
        rows.extend(status_rows)
    return rows


def _metadata_publication_manifest_rows(context: Context) -> list[dict[str, Any]]:
    latest_by_projection: dict[str, dict[str, Any]] = {}
    for _detail, _status_rows in _connection_rows(context):
        dataset_root = str(_detail.get("dataset_root") or "")
        if not dataset_root:
            continue
        for row in DatasetStore(dataset_root).read_dataset("metadata_publication_manifest"):
            projection = str(row.get("projection_name") or "")
            if not projection:
                continue
            previous = latest_by_projection.get(projection)
            current = dict(row)
            if previous is None or str(current.get("updated_at") or "") >= str(
                previous.get("updated_at") or ""
            ):
                latest_by_projection[projection] = current
    return sorted(
        latest_by_projection.values(),
        key=lambda row: str(row.get("projection_name") or "").casefold(),
    )


def _scoped_source_rows(context: Context, scope: Scope) -> list[dict[str, Any]]:
    return [row for row in _metadata_source_status_rows(context) if _row_visible(scope, row)]


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
    for table_name in _registered_tables(rows):
        layer = _layer_for_table(table_name)
        if not layer:
            continue
        status = dataset_status(table_name, source_status=rows)
        layers[layer]["total"] += 1
        if str(status.get("availability") or "") in {"healthy", "healthy-empty"}:
            layers[layer]["healthy"] += 1
    return envelope(
        {"layers": layers},
        evidence=_evidence(
            source_engine=SOURCE_ENGINE,
            source_table=SOURCE_TABLE,
            timestamp=max((_status_timestamp(row) for row in rows), default=""),
        ),
        scope=scope.to_dict(),
    )


@router.get("/datasets/{table_name}", summary="Fabric medallion dataset status")
def medallion_dataset(table_name: str, context: Context, scope: ReadScope) -> dict[str, Any]:
    rows = _scoped_source_rows(context, scope)
    table_names = set(_registered_tables(rows))
    if table_name not in table_names:
        raise not_found(table_name, "dataset")
    table_rows = [
        row
        for row in rows
        if str(row.get("source_family") or row.get("table_name") or "") == table_name
    ]
    return envelope(
        dataset_status(table_name, source_status=rows),
        evidence=_evidence(
            source_engine=SOURCE_ENGINE,
            source_table=SOURCE_TABLE,
            timestamp=max((_status_timestamp(row) for row in table_rows), default=""),
        ),
        scope=scope.to_dict(),
    )


@router.get("/manifest", summary="Fabric publication manifest dispositions")
def medallion_manifest(context: Context, scope: ReadScope) -> dict[str, Any]:
    rows = _metadata_publication_manifest_rows(context)
    entries = [
        {
            "projection_name": str(row.get("projection_name") or ""),
            "disposition": str(row.get("disposition") or "unknown"),
            "compatibility_version": row.get("compatibility_version"),
            "retired_reason": row.get("retired_reason"),
            "registered_at": str(row.get("registered_at") or ""),
            "updated_at": str(row.get("updated_at") or ""),
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

