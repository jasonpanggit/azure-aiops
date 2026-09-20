"""Integration contracts for scope-first Fabric SQL Exposure reads."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Self

import pytest

from api.exposure_query import (
    MAX_EXTERNAL_CATALOG_EVIDENCE_ROWS,
    ExposureAuthorization,
    ExposureCursorCodec,
    ExposureCursorKeyRing,
    ExposureFilter,
    ExposureKbIdentifierError,
    ExposureQuery,
    ExposureQueryService,
    ExposureQueryUnavailableError,
    ExposureRestartConflict,
    ExposureSort,
)
from fabric.dataset_mapper import (
    _patch_installation_finding_state,
    _patch_snapshot_rows,
)
from fabric.schema_registry import schema_for
from fabric.sql_endpoint import FabricSqlQueryLimitError, FabricSqlReader, SqlEndpoint


class RecordingReader:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def query(
        self,
        sql: str,
        parameters: tuple[Any, ...] = (),
        *,
        max_rows: int | None = None,
    ) -> list[dict[str, Any]]:
        self.calls.append(
            {
                "sql": sql,
                "parameters": tuple(parameters),
                "max_rows": max_rows,
            }
        )
        if "COUNT_BIG" in sql and "GROUP BY" not in sql:
            return [{"total_count": 2}]
        if "dimension_name" in sql:
            return [
                {
                    "dimension_name": "severity",
                    "dimension_value": "critical",
                    "exposure_count": 2,
                }
            ]
        return [
            {
                "exposure_id": "exposure-1",
                "priority_score": 100.0,
                "severity": "critical",
            },
            {
                "exposure_id": "exposure-2",
                "priority_score": 90.0,
                "severity": "critical",
            },
        ]


class SilverPatchReader(RecordingReader):
    def __init__(
        self,
        *,
        tenant_id: str = "tenant-authorized",
        status_completeness: str = "complete",
        status_row_count: int = 10,
        findings_available: bool = True,
        finding_count: int = 1,
    ) -> None:
        super().__init__()
        self.tenant_id = tenant_id
        self.status_generation = "source-generation-17"
        self.status_completeness = status_completeness
        self.status_row_count = status_row_count
        self.findings_available = findings_available
        self.finding_count = finding_count

    def query(
        self,
        sql: str,
        parameters: tuple[Any, ...] = (),
        *,
        max_rows: int | None = None,
    ) -> list[dict[str, Any]]:
        self.calls.append(
            {
                "sql": sql,
                "parameters": tuple(parameters),
                "max_rows": max_rows,
            }
        )
        if "[metadata_patch_snapshot]" in sql:
            if parameters[0] != self.tenant_id:
                return []
            subscriptions = [str(value) for value in parameters[1:]]
            return [
                {
                    "connection_id": "default",
                    "subscription_id": subscription_id,
                    "ingestion_run_id": self.status_generation,
                    "source_generation": "source-effective-17",
                    "status": (
                        "succeeded"
                        if self.status_completeness in {"complete", "healthy-empty"}
                        else "partial"
                    ),
                    "completeness": self.status_completeness,
                    "freshness": "current",
                    "freshness_at": "2026-09-10T02:41:10Z",
                    "freshness_threshold_seconds": 3600,
                    "represented_count": 1,
                    "expected_count": 1,
                }
                for subscription_id in subscriptions
            ]
        if "COUNT_BIG" in sql and "GROUP BY" not in sql:
            if "1 = 0" in sql:
                return [
                    {
                        "total_count": 0,
                        "freshest_at": None,
                        "all_complete": 1,
                    }
                ]
            return [
                {
                    "total_count": self.finding_count,
                    "freshest_at": "2026-09-10T02:41:10Z",
                    "all_complete": 1,
                }
            ]
        if "1 = 0" in sql:
            return []
        return [
            {
                "exposure_id": f"silver-patch:patch-{index}",
                "target_id": "/subscriptions/subscription-a/servers/server-1",
                "target_kind": "server",
                "weakness_id": "KB6000001",
                "weakness_kind": "kb",
                "source_family": "aum",
                "source_state": "missing",
                "current_state": "missing",
                "active": True,
                "severity": "critical",
                "priority_score": 100.0,
                "recommendation": "Install KB6000001",
                "completeness": "complete",
                "timestamp": "2026-09-10T02:41:10Z",
                "ordering_priority_score": 100.0,
                "ordering_severity_rank": 4,
                "ordering_target_id": "/subscriptions/subscription-a/servers/server-1",
            }
            for index in range(self.finding_count)
        ]


class KbSilverReader(SilverPatchReader):
    def query(
        self,
        sql: str,
        parameters: tuple[Any, ...] = (),
        *,
        max_rows: int | None = None,
    ) -> list[dict[str, Any]]:
        if "[metadata_patch_snapshot]" in sql:
            return super().query(sql, parameters, max_rows=max_rows)
        self.calls.append(
            {
                "sql": sql,
                "parameters": tuple(parameters),
                "max_rows": max_rows,
            }
        )
        if "[silver_patch_snapshot_findings]" in sql:
            return [
                {
                    "update_name": "Contoso security update",
                    "severity": "critical",
                    "published_at": "2026-08-01",
                    "target_resource_id": "server-1",
                    "status": "installed",
                    "timestamp": "2026-09-10T02:41:10Z",
                    "affected_server_count": 0,
                }
            ]
        return []


def _authorization() -> ExposureAuthorization:
    return ExposureAuthorization(
        subject="operator@example.com",
        tenant_id="tenant-authorized",
        connection_ids=("connection-b", "connection-a"),
        connection_subscriptions={
            "connection-a": "subscription-a",
            "connection-b": "subscription-b",
        },
        scope={
            "subscription": ("subscription-b", "subscription-a"),
            "subscription_connection": ("connection-b", "connection-a"),
        },
    )


def _patch_status_rows(*, row_count: int = 1) -> list[dict[str, Any]]:
    return [
        {
            "tenant_id": "tenant-a",
            "connection_id": "connection-a",
            "source_family": source_family,
            "requested_scope": {"subscription": ["subscription-a"]},
            "effective_generation": "source-generation-17",
            "completeness": "complete" if row_count else "healthy-empty",
            "freshness": "fresh",
            "last_success_at": "2026-09-10T02:41:10Z",
            "ingested_at": "2026-09-10T02:42:00Z",
            "freshness_threshold_seconds": 3600,
            "represented_count": 1,
            "expected_count": 1,
            "row_count": row_count,
        }
        for source_family in (
            "azure_update_manager_assessment",
            "azure_update_manager_installation",
            "azure_update_manager_missing",
        )
    ]


def test_patch_snapshot_manifest_shares_silver_publication_generation() -> None:
    rows = _patch_snapshot_rows(
        _patch_status_rows(),
        "silver-publication-17",
        "2026-09-10T02:40:00Z",
    )

    assert len(rows) == 1
    assert rows[0]["ingestion_run_id"] == "silver-publication-17"
    assert rows[0]["combined_source_generation"] == "silver-publication-17"
    assert rows[0]["source_generation"] == "source-generation-17"
    assert rows[0]["tenant_id"] == "tenant-a"
    assert rows[0]["connection_id"] == "connection-a"
    assert rows[0]["completeness"] == "complete"
    assert rows[0]["freshness"] == "fresh"
    assert rows[0]["freshness_at"] == "2026-09-10T02:41:10Z"
    assert set(rows[0]) == set(schema_for("metadata_patch_snapshot").names)


def test_patch_snapshot_manifest_preserves_healthy_empty_generation() -> None:
    rows = _patch_snapshot_rows(
        _patch_status_rows(row_count=0),
        "silver-publication-empty",
        "2026-09-10T02:40:00Z",
    )

    assert rows[0]["ingestion_run_id"] == "silver-publication-empty"
    assert rows[0]["completeness"] == "healthy-empty"


def test_patch_snapshot_manifest_preserves_explicit_legacy_replacement() -> None:
    source_status = _patch_status_rows(row_count=0)
    for row in source_status:
        row["replaces_legacy_connection_id"] = "legacy:subscription-a"

    rows = _patch_snapshot_rows(
        source_status,
        "silver-publication-migration",
        "2026-09-10T02:40:00Z",
    )

    assert rows[0]["replaces_legacy_connection_id"] == "legacy:subscription-a"


def test_failed_patch_installation_remains_actionable() -> None:
    assert (
        _patch_installation_finding_state(
            {"canonicalStatus": "installation_failed"}
        )
        == "installation_failed"
    )
    assert (
        _patch_installation_finding_state({"canonicalStatus": "installed"})
        == "installed"
    )


def test_patch_snapshot_manifest_aggregates_all_partitions_order_independently() -> None:
    statuses = _patch_status_rows()
    statuses.extend(
        {
            **row,
            "completeness": "stale",
            "freshness": "stale",
            "last_success_at": "2026-09-10T01:41:10Z",
            "represented_count": 0,
            "row_count": 2,
        }
        for row in _patch_status_rows()
    )

    forward = _patch_snapshot_rows(
        statuses,
        "silver-publication-17",
        "2026-09-10T02:40:00Z",
    )
    reverse = _patch_snapshot_rows(
        list(reversed(statuses)),
        "silver-publication-17",
        "2026-09-10T02:40:00Z",
    )

    assert forward == reverse
    assert forward[0]["completeness"] == "stale"
    assert forward[0]["freshness"] == "stale"
    assert forward[0]["freshness_at"] == "2026-09-10T01:41:10Z"
    assert forward[0]["represented_count"] == 1
    assert forward[0]["expected_count"] == 2


def test_patch_snapshot_manifest_rejects_missing_or_ambiguous_scope_identity() -> None:
    missing_connection = _patch_status_rows()
    for row in missing_connection:
        row.pop("connection_id")
    with pytest.raises(ValueError, match="connection identity is required"):
        _patch_snapshot_rows(
            missing_connection,
            "silver-publication-17",
            "2026-09-10T02:40:00Z",
        )

    ambiguous_connection = _patch_status_rows()
    ambiguous_connection[0]["connectionId"] = "connection-b"
    with pytest.raises(ValueError, match="connection identity is ambiguous"):
        _patch_snapshot_rows(
            ambiguous_connection,
            "silver-publication-17",
            "2026-09-10T02:40:00Z",
        )

    ambiguous_subscription = _patch_status_rows()
    ambiguous_subscription[0]["requested_scope"] = {
        "subscription": ["subscription-a", "subscription-b"]
    }
    with pytest.raises(ValueError, match="exactly one subscription"):
        _patch_snapshot_rows(
            ambiguous_subscription,
            "silver-publication-17",
            "2026-09-10T02:40:00Z",
        )


def test_patch_snapshot_manifest_requires_all_three_aum_families() -> None:
    rows = _patch_snapshot_rows(
        _patch_status_rows()[:-1],
        "silver-publication-17",
        "2026-09-10T02:40:00Z",
    )

    assert rows == []


def test_server_aum_query_reads_bounded_silver_without_gold_generation() -> None:
    reader = SilverPatchReader()
    service = ExposureQueryService(
        reader,
        generation_window=lambda: (_ for _ in ()).throw(
            ExposureQueryUnavailableError("Gold generation unavailable")
        ),
    )

    result = service.list_page(
        _authorization(),
        query=ExposureQuery(
            filters=(
                ExposureFilter("target_kind", "eq", "server"),
                ExposureFilter("source_family", "eq", "aum"),
            ),
            page_size=25,
        ),
    )

    assert result.generation == "silver-patch:source-generation-17"
    assert result.total_count == 1
    assert result.items[0]["weakness_id"] == "KB6000001"
    assert len(reader.calls) == 3
    status_call, count_call, page_call = reader.calls
    assert "[metadata_patch_snapshot]" in status_call["sql"]
    assert status_call["max_rows"] == 3
    assert status_call["parameters"][:3] == (
        "tenant-authorized",
        "subscription-a",
        "subscription-b",
    )
    for call in (count_call, page_call):
        assert "[silver_patch_snapshot_findings]" in call["sql"]
        assert "[gold_exposure_facts]" not in call["sql"]
        assert "[tenant_id] = ?" in call["sql"]
        assert "[subscription_id] IN (?, ?)" in call["sql"]
        assert "[ingestion_run_id] = ?" in call["sql"]
        assert "SELECT *" not in call["sql"].upper()
    assert page_call["max_rows"] == 26
    assert result.items[0]["source_state"] == "missing"


def test_server_aum_query_uses_production_tenant_for_barrier_and_findings() -> None:
    tenant_id = "ffc83107-fcc0-4d2e-8798-d582da36505e"
    subscription_id = "a87a8e64-a52a-4aa8-a760-5e8919d23cd1"
    reader = SilverPatchReader(tenant_id=tenant_id, finding_count=10)
    authorization = ExposureAuthorization(
        subject="operator@example.com",
        tenant_id=tenant_id,
        connection_ids=("demo",),
        connection_subscriptions={"demo": subscription_id},
        scope={
            "subscription": (subscription_id,),
            "subscription_connection": ("demo",),
        },
    )

    result = ExposureQueryService(reader).list_page(
        authorization,
        query=ExposureQuery(
            filters=(
                ExposureFilter("target_kind", "eq", "server"),
                ExposureFilter("source_family", "eq", "aum"),
            ),
            page_size=100,
        ),
    )

    assert result.generation == "silver-patch:source-generation-17"
    assert result.total_count == 10
    assert len(result.items) == 10
    barrier_call, count_call, page_call = reader.calls
    assert barrier_call["parameters"] == (tenant_id, subscription_id)
    assert "[connection_id]" not in barrier_call["sql"]
    assert count_call["parameters"][:2] == (tenant_id, subscription_id)
    assert page_call["parameters"][:2] == (tenant_id, subscription_id)


def test_kb_detail_proves_silver_membership_and_merges_exact_catalog_records() -> None:
    reader = KbSilverReader()
    requested: list[str] = []

    def records(identifier: str):
        requested.append(identifier)
        if identifier == "KB6000001":
            return (
                {
                    "source": "msrc",
                    "identifier": identifier,
                    "status": "succeeded",
                    "stale": False,
                    "payload": {
                        "title": "MSRC security update",
                        "severity": "Critical",
                        "published_at": "2026-08-01",
                        "cve_ids": ["CVE-2026-0001"],
                    },
                    "attempted_at": "2026-09-10T02:40:00Z",
                    "succeeded_at": "2026-09-10T02:40:00Z",
                },
            )
        return (
            {
                "source": "nvd",
                "identifier": identifier,
                "status": "succeeded",
                "stale": False,
                "payload": {
                    "title": "Kernel remote execution",
                    "severity": "Critical",
                    "cvss": {
                        "base_score": 9.8,
                        "vector": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
                        "severity": "Critical",
                    },
                },
            },
            {
                "source": "epss",
                "identifier": identifier,
                "status": "succeeded",
                "stale": False,
                "payload": {
                    "epss_score": 0.73,
                    "epss_percentile": 0.92,
                },
            },
            {
                "source": "kev",
                "identifier": identifier,
                "status": "succeeded",
                "stale": False,
                "payload": {
                    "kev_date_added": "2026-08-01",
                    "kev_due_date": "2026-08-22",
                    "kev_ransomware_use": "Known",
                },
            },
        )

    detail = ExposureQueryService(
        reader,
        catalog_records_resolver=records,
    ).kb_item(
        _authorization(),
        kb_id="KB6000001",
    )

    assert detail is not None
    assert detail["generation"] == "silver-patch:source-generation-17"
    assert detail["snapshot_freshness_at"] == "2026-09-10T02:41:10Z"
    assert detail["kb_id"] == "KB6000001"
    assert detail["title"] == "MSRC security update"
    assert detail["severity"] == "Critical"
    assert detail["published_at"] == "2026-08-01"
    assert detail["cve_ids"] == ["CVE-2026-0001"]
    assert detail["cves"][0]["cvss"]["base_score"] == 9.8
    assert detail["cves"][0]["epss_score"] == pytest.approx(0.73)
    assert detail["cves"][0]["epss_percentile"] == pytest.approx(0.92)
    assert detail["cves"][0]["is_known_exploited"] is True
    assert detail["cves"][0]["kev_due_date"] == "2026-08-22"
    assert detail["affected_servers"] == []
    assert detail["affected_server_count"] == 0
    assert detail["affected_servers_truncated"] is False
    assert detail["enrichment"]["sources"]["msrc:KB6000001"]["status"] == "succeeded"
    assert detail["enrichment"]["sources"]["nvd:CVE-2026-0001"]["status"] == "succeeded"
    assert detail["enrichment"]["sources"]["epss:CVE-2026-0001"]["status"] == "succeeded"
    assert detail["enrichment"]["sources"]["kev:CVE-2026-0001"]["status"] == "succeeded"
    assert detail["enrichment"]["complete"] is True
    assert requested == ["KB6000001", "CVE-2026-0001"]
    assert len(reader.calls) == 2
    membership_call = reader.calls[-1]
    assert "[silver_patch_snapshot_findings]" in membership_call["sql"]
    assert "[tenant_id] = ?" in membership_call["sql"]
    assert "[subscription_id] IN (?, ?)" in membership_call["sql"]
    assert "[ingestion_run_id] = ?" in membership_call["sql"]
    assert membership_call["parameters"][-1] == "KB6000001"
    assert membership_call["max_rows"] == 100
    assert "ROW_NUMBER() OVER" in membership_call["sql"]
    assert "PARTITION BY [subscription_id], [target_resource_id]" in membership_call["sql"]
    assert "NULLIF([last_modified], '')" in membership_call["sql"]
    assert "LOWER([status]) IN ('missing', 'installation_failed')" in membership_call["sql"]
    assert "AS [affected_server_count]" in membership_call["sql"]


def test_kb_detail_rejects_blank_identifier_before_query() -> None:
    reader = KbSilverReader()

    with pytest.raises(
        ExposureKbIdentifierError,
        match="canonical KB identifier",
    ):
        ExposureQueryService(reader).kb_item(_authorization(), kb_id="   ")

    assert reader.calls == []


def test_kb_detail_reports_exact_count_when_affected_server_sample_is_bounded() -> None:
    class LargeKbSilverReader(KbSilverReader):
        def query(
            self,
            sql: str,
            parameters: tuple[Any, ...] = (),
            *,
            max_rows: int | None = None,
        ) -> list[dict[str, Any]]:
            rows = super().query(sql, parameters, max_rows=max_rows)
            if "[silver_patch_snapshot_findings]" not in sql:
                return rows
            return [
                {
                    **row,
                    "status": "missing",
                    "affected_server_count": 137,
                }
                for row in rows
            ]

    detail = ExposureQueryService(LargeKbSilverReader()).kb_item(
        _authorization(),
        kb_id="KB6000001",
    )

    assert detail is not None
    assert detail["affected_servers"] == ["server-1"]
    assert detail["affected_server_count"] == 137
    assert detail["affected_servers_truncated"] is True


def test_kb_detail_marks_missing_nvd_metadata_degraded() -> None:
    detail = ExposureQueryService(
        KbSilverReader(),
        catalog_records_resolver=lambda identifier: (
            (
                {
                    "source": "msrc",
                    "identifier": identifier,
                    "status": "succeeded",
                    "stale": False,
                    "payload": {"cve_ids": ["CVE-2026-0001"]},
                },
            )
            if identifier.startswith("KB")
            else ()
        ),
    ).kb_item(_authorization(), kb_id="KB6000001")

    assert detail is not None
    assert detail["cves"][0]["cvss"] == {
        "base_score": None,
        "vector": "",
        "severity": "Unknown",
    }
    assert detail["enrichment"]["complete"] is False
    assert detail["enrichment"]["status"] == "degraded"
    assert detail["enrichment"]["sources"]["nvd:CVE-2026-0001"][
        "safe_error_code"
    ] == "provider_unavailable"


def test_kb_detail_supports_realistic_large_msrc_association_sets() -> None:
    cve_ids = [f"CVE-2026-{index:04d}" for index in range(126)]
    detail = ExposureQueryService(
        KbSilverReader(),
        catalog_records_resolver=lambda identifier: (
            (
                {
                    "source": "msrc",
                    "identifier": identifier,
                    "status": "succeeded",
                    "stale": False,
                    "payload": {"cve_ids": cve_ids},
                },
            )
            if identifier.startswith("KB")
            else ()
        ),
    ).kb_item(_authorization(), kb_id="KB6000001")

    assert detail is not None
    assert detail["cve_ids"] == cve_ids
    assert len(detail["cves"]) == 126
    assert detail["enrichment"]["sources"]["msrc:KB6000001"]["status"] == "succeeded"


def test_server_aum_query_intersects_subscriptions_with_authorized_connections() -> None:
    reader = SilverPatchReader()
    authorization = ExposureAuthorization(
        subject="operator@example.com",
        tenant_id="tenant-authorized",
        connection_ids=("connection-a",),
        connection_subscriptions={"connection-a": "subscription-a"},
        scope={
            "subscription": ("subscription-a", "subscription-b"),
            "subscription_connection": ("connection-a",),
        },
    )

    ExposureQueryService(reader).list_page(
        authorization,
        query=ExposureQuery(
            filters=(
                ExposureFilter("target_kind", "eq", "server"),
                ExposureFilter("source_family", "eq", "aum"),
            ),
        ),
    )

    for call in reader.calls:
        assert "subscription-b" not in call["parameters"]
        assert "subscription-a" in call["parameters"]


def test_server_aum_query_uses_trusted_connections_for_all_subscriptions() -> None:
    reader = SilverPatchReader()
    authorization = ExposureAuthorization(
        subject="operator@example.com",
        tenant_id="tenant-authorized",
        connection_ids=("connection-a",),
        connection_subscriptions={"connection-a": "subscription-a"},
        scope={},
    )

    result = ExposureQueryService(reader).list_page(
        authorization,
        query=ExposureQuery(
            filters=(
                ExposureFilter("target_kind", "eq", "server"),
                ExposureFilter("source_family", "eq", "aum"),
            ),
        ),
    )

    assert result.generation == "silver-patch:source-generation-17"
    assert result.total_count == 1
    assert all(
        "subscription-a" in call["parameters"]
        for call in reader.calls
    )


def test_server_aum_query_rejects_oversized_subscription_scope_before_sql() -> None:
    connection_subscriptions = {
        f"connection-{index}": f"subscription-{index}"
        for index in range(501)
    }
    reader = SilverPatchReader()
    authorization = ExposureAuthorization(
        subject="operator@example.com",
        tenant_id="tenant-authorized",
        connection_ids=tuple(connection_subscriptions),
        connection_subscriptions=connection_subscriptions,
        scope={"subscription": tuple(connection_subscriptions.values())},
    )

    with pytest.raises(
        ExposureQueryUnavailableError,
        match="subscription scope exceeds its safe bound",
    ):
        ExposureQueryService(reader).list_page(
            authorization,
            query=ExposureQuery(
                filters=(
                    ExposureFilter("target_kind", "eq", "server"),
                    ExposureFilter("source_family", "eq", "aum"),
                ),
            ),
        )

    assert reader.calls == []


def test_server_aum_query_reports_healthy_empty_from_source_status() -> None:
    reader = SilverPatchReader(
        status_completeness="healthy-empty",
        status_row_count=0,
        findings_available=False,
    )

    result = ExposureQueryService(reader).list_page(
        _authorization(),
        query=ExposureQuery(
            filters=(
                ExposureFilter("target_kind", "eq", "server"),
                ExposureFilter("source_family", "eq", "aum"),
            ),
        ),
    )

    assert result.generation == "silver-patch:source-generation-17"
    assert result.total_count == 0
    assert result.items == ()
    assert result.completeness["state"] == "healthy-empty"


def test_server_aum_query_reports_partial_source_status() -> None:
    reader = SilverPatchReader(status_completeness="stale")

    result = ExposureQueryService(reader).list_page(
        _authorization(),
        query=ExposureQuery(
            filters=(
                ExposureFilter("target_kind", "eq", "server"),
                ExposureFilter("source_family", "eq", "aum"),
            ),
        ),
    )

    assert result.completeness["state"] == "stale"


def test_server_aum_cursor_requires_the_same_source_generation() -> None:
    reader = SilverPatchReader(finding_count=2)
    codec = ExposureCursorCodec(
        ExposureCursorKeyRing(
            active_kid="test-active",
            active_key=b"a" * 32,
            loaded_at=datetime(2026, 9, 10, tzinfo=UTC),
        )
    )
    service = ExposureQueryService(reader, cursor_codec=codec)
    authorization = _authorization()
    query = ExposureQuery(
        filters=(
            ExposureFilter("target_kind", "eq", "server"),
            ExposureFilter("source_family", "eq", "aum"),
        ),
        page_size=1,
    )
    first = service.list_page(
        authorization,
        query=query,
        now=datetime(2026, 9, 10, tzinfo=UTC),
    )
    assert first.next_cursor is not None
    reader.status_generation = "source-generation-18"

    with pytest.raises(ExposureRestartConflict) as error:
        service.list_page(
            authorization,
            query=query,
            cursor=first.next_cursor,
            now=datetime(2026, 9, 10, 0, 1, tzinfo=UTC),
        )

    assert error.value.code == "exposure_generation_evicted"


def test_server_aum_decimal_priority_issues_and_decodes_cursor() -> None:
    class DecimalSilverPatchReader(SilverPatchReader):
        def query(
            self,
            sql: str,
            parameters: tuple[Any, ...] = (),
            *,
            max_rows: int | None = None,
        ) -> list[dict[str, Any]]:
            rows = super().query(sql, parameters, max_rows=max_rows)
            if "[metadata_patch_snapshot]" not in sql and "COUNT_BIG" not in sql:
                return [
                    {
                        **row,
                        "priority_score": Decimal("100.00"),
                        "ordering_priority_score": Decimal("100.00"),
                    }
                    for row in rows
                ]
            return rows

    reader = DecimalSilverPatchReader(finding_count=2)
    codec = ExposureCursorCodec(
        ExposureCursorKeyRing(
            active_kid="test-active",
            active_key=b"a" * 32,
            loaded_at=datetime(2026, 9, 10, tzinfo=UTC),
        )
    )
    service = ExposureQueryService(reader, cursor_codec=codec)
    query = ExposureQuery(
        filters=(
            ExposureFilter("target_kind", "eq", "server"),
            ExposureFilter("source_family", "eq", "aum"),
        ),
        page_size=1,
    )

    first = service.list_page(
        _authorization(),
        query=query,
        now=datetime(2026, 9, 10, tzinfo=UTC),
    )
    assert first.next_cursor is not None
    assert codec.decode(
        first.next_cursor,
        authorization=_authorization(),
        query=query,
        expected_generation_id=first.generation,
        now=datetime(2026, 9, 10, 0, 1, tzinfo=UTC),
    ).position == (Decimal(100), "silver-patch:patch-0")

    service.list_page(
        _authorization(),
        query=query,
        cursor=first.next_cursor,
        now=datetime(2026, 9, 10, 0, 1, tzinfo=UTC),
    )
    assert reader.calls[-1]["parameters"][-3:] == (
        Decimal(100),
        Decimal(100),
        "silver-patch:patch-0",
    )


def test_container_query_keeps_gold_generation_path() -> None:
    reader = RecordingReader()

    ExposureQueryService(reader).list_page(
        _authorization(),
        generation_id="generation-17",
        query=ExposureQuery(
            filters=(
                ExposureFilter("target_kind", "eq", "container_image"),
            ),
        ),
    )

    assert reader.calls
    assert all("[gold_exposure_facts]" in call["sql"] for call in reader.calls)


def test_generic_server_query_keeps_gold_generation_path() -> None:
    reader = RecordingReader()

    ExposureQueryService(reader).list_page(
        _authorization(),
        generation_id="generation-17",
        query=ExposureQuery(
            filters=(ExposureFilter("target_kind", "eq", "server"),),
        ),
    )

    assert reader.calls
    assert all("[gold_exposure_facts]" in call["sql"] for call in reader.calls)


class ZeroResultReader(RecordingReader):
    def query(
        self,
        sql: str,
        parameters: tuple[Any, ...] = (),
        *,
        max_rows: int | None = None,
    ) -> list[dict[str, Any]]:
        self.calls.append(
            {
                "sql": sql,
                "parameters": tuple(parameters),
                "max_rows": max_rows,
            }
        )
        if "COUNT_BIG" in sql and "GROUP BY" not in sql:
            return [{"total_count": 0, "freshest_at": None, "all_complete": None}]
        return []


def test_gold_query_reports_healthy_empty_when_filter_matches_no_rows() -> None:
    """A severity filter with no matching Defender image findings is a
    healthy, complete zero-row result -- not a provider outage."""
    reader = ZeroResultReader()

    result = ExposureQueryService(reader).list_page(
        _authorization(),
        generation_id="generation-17",
        query=ExposureQuery(
            filters=(
                ExposureFilter("severity", "eq", "high"),
                ExposureFilter("target_kind", "eq", "container_image"),
                ExposureFilter("source_family", "eq", "defender_image"),
            ),
        ),
    )

    assert result.total_count == 0
    assert result.items == ()
    assert result.completeness["state"] == "healthy-empty"


def test_count_facet_and_page_share_scope_first_bound_predicates() -> None:
    reader = RecordingReader()
    service = ExposureQueryService(reader)

    result = service.list_page(
        _authorization(),
        generation_id="generation-17",
        query=ExposureQuery(
            filters=(ExposureFilter("severity", "eq", "critical"),),
            facets=("severity",),
            sort=ExposureSort("priority_score", "desc"),
            page_size=25,
        ),
    )

    assert result.total_count == 2
    assert [item["exposure_id"] for item in result.items] == [
        "exposure-1",
        "exposure-2",
    ]
    assert result.facets == {
        "severity": [{"value": "critical", "count": 2}]
    }
    assert len(reader.calls) == 3

    expected_prefix = (
        "tenant-authorized",
        "connection-a",
        "connection-b",
        "subscription-a",
        "subscription-b",
        "generation-17",
    )
    for call in reader.calls:
        sql = call["sql"]
        assert sql.index("[tenant_id] = ?") < sql.index("[connection_id] IN (?, ?)")
        assert sql.index("[connection_id] IN (?, ?)") < sql.index(
            "[subscription_id] IN (?, ?)"
        )
        assert sql.index("[subscription_id] IN (?, ?)") < sql.index(
            "[read_model_generation_id] = ?"
        )
        assert sql.index("[read_model_generation_id] = ?") < sql.index(
            "[severity] = ?"
        )
        assert call["parameters"][:6] == expected_prefix
        assert call["parameters"][6] == "critical"
        assert all(value not in sql for value in call["parameters"])
        assert "SELECT *" not in sql.upper()

    assert reader.calls[0]["max_rows"] == 1
    assert reader.calls[1]["max_rows"] is not None
    assert reader.calls[2]["max_rows"] == 26


class CatalogReader(RecordingReader):
    def query(
        self,
        sql: str,
        parameters: tuple[Any, ...] = (),
        *,
        max_rows: int | None = None,
    ) -> list[dict[str, Any]]:
        self.calls.append(
            {
                "sql": sql,
                "parameters": tuple(parameters),
                "max_rows": max_rows,
            }
        )
        if "SELECT TOP (1) [fact_id]" in sql:
            return [{"fact_id": "fact-1"}]
        return [
            {
                "source": "nvd",
                "identifier": "CVE-2026-0001",
                "status": "succeeded",
                "stale": False,
                "lkg_available": True,
                "safe_error_code": "",
                "attempted_at": "2026-09-10T00:00:00Z",
                "succeeded_at": "2026-09-10T00:00:00Z",
                "source_at": "2026-09-09T00:00:00Z",
                "enriched_at": "2026-09-10T00:00:00Z",
                "payload_json": (
                    '{"cve_id":"CVE-2026-0001",'
                    '"description":"Safe NVD detail",'
                    '"target_id":"secret-target",'
                    '"cvss":{"base_score":9.8,"scope_key":"secret-scope"}}'
                ),
            },
            {
                "source": "epss",
                "identifier": "CVE-2026-0001",
                "status": "failed",
                "stale": True,
                "lkg_available": True,
                "safe_error_code": "provider_unavailable",
                "attempted_at": "2026-09-10T00:00:00Z",
                "succeeded_at": "2026-09-09T00:00:00Z",
                "source_at": "2026-09-09T00:00:00Z",
                "enriched_at": "2026-09-09T00:00:00Z",
                "payload_json": '{"epss_score":0.73,"epss_percentile":0.92}',
            },
        ]


def test_external_catalog_is_authorized_generation_pinned_and_bounded() -> None:
    reader = CatalogReader()
    service = ExposureQueryService(reader)

    result = service.catalog_item(
        _authorization(),
        generation_id="generation-17",
        weakness_id="CVE-2026-0001",
    )

    assert len(reader.calls) == 2
    membership_call, call = reader.calls
    assert membership_call["max_rows"] == 1
    assert "[weakness_id] = ?" in membership_call["sql"]
    assert membership_call["parameters"][-1] == "CVE-2026-0001"
    sql = call["sql"]
    assert "[gold_exposure_facts]" in sql
    assert "[gold_exposure_evidence]" in sql
    assert f"TOP ({MAX_EXTERNAL_CATALOG_EVIDENCE_ROWS + 1})" in sql
    assert "ROW_NUMBER() OVER (PARTITION BY [e].[source], [e].[identifier]" in sql
    assert "WHERE [evidence_rank] = 1" in sql
    assert "OPENJSON([e].[payload_json], '$.cve_ids')" in sql
    assert "SELECT *" not in sql.upper()
    assert call["max_rows"] == MAX_EXTERNAL_CATALOG_EVIDENCE_ROWS + 1
    assert call["parameters"] == (
        "tenant-authorized",
        "connection-a",
        "connection-b",
        "subscription-a",
        "subscription-b",
        "generation-17",
        "CVE-2026-0001",
        "CVE-2026-0001",
    )
    assert all(str(value) not in sql for value in call["parameters"])
    assert result["generation"] == "generation-17"
    assert result["item"]["cve_id"] == "CVE-2026-0001"
    assert result["item"]["sources"]["nvd"]["payload"]["description"] == (
        "Safe NVD detail"
    )
    assert result["item"]["sources"]["nvd"]["payload"]["cvss"] == {
        "base_score": 9.8
    }
    assert result["item"]["sources"]["epss"]["has_last_known_good"] is True
    serialized = str(result)
    for forbidden in (
        "target_id",
        "exposure_id",
        "fact_id",
        "scope_key",
        "tenant_id",
        "subscription_id",
        "connection_id",
    ):
        assert forbidden not in serialized


def test_external_catalog_merges_exact_durable_records_after_sql_membership() -> None:
    reader = CatalogReader()
    service = ExposureQueryService(
        reader,
        catalog_records_resolver=lambda identifier: (
            {
                "source": "kev",
                "identifier": identifier,
                "status": "succeeded",
                "stale": False,
                "payload": {
                    "kev_due_date": "2026-10-01",
                    "target_id": "must-not-leak",
                },
                "enriched_at": "2026-09-11T03:06:51Z",
            },
        ),
    )

    result = service.catalog_item(
        _authorization(),
        generation_id="generation-17",
        weakness_id="CVE-2026-0001",
    )

    assert result is not None
    kev = result["item"]["sources"]["kev"]
    assert kev["payload"] == {"kev_due_date": "2026-10-01"}
    assert kev["has_last_known_good"] is True


def test_external_catalog_refreshes_live_records_after_authorized_membership() -> None:
    reader = CatalogReader()
    refreshed: list[str] = []
    service = ExposureQueryService(
        reader,
        catalog_records_resolver=lambda _identifier: pytest.fail(
            "resolver must not run when a live refresher is configured"
        ),
        catalog_records_refresher=lambda identifier: (
            refreshed.append(identifier)
            or (
                {
                    "source": "nvd",
                    "identifier": identifier,
                    "status": "succeeded",
                    "stale": False,
                    "payload": {
                        "description": "Fresh NVD detail",
                        "severity": "Critical",
                    },
                    "enriched_at": "2026-09-14T00:00:00Z",
                },
                {
                    "source": "epss",
                    "identifier": identifier,
                    "status": "succeeded",
                    "stale": False,
                    "payload": {"epss_score": 0.99},
                    "enriched_at": "2026-09-14T00:00:00Z",
                },
                {
                    "source": "kev",
                    "identifier": identifier,
                    "status": "succeeded",
                    "stale": False,
                    "payload": {},
                    "enriched_at": "2026-09-14T00:00:00Z",
                },
            )
        ),
    )

    result = service.catalog_item(
        _authorization(),
        generation_id="generation-17",
        weakness_id="CVE-2026-0001",
    )

    assert refreshed == ["CVE-2026-0001"]
    assert result is not None
    assert result["item"]["sources"]["nvd"]["payload"]["description"] == (
        "Fresh NVD detail"
    )
    assert result["item"]["sources"]["epss"]["payload"]["epss_score"] == 0.99
    assert result["item"]["sources"]["kev"]["status"] == "succeeded"


def test_external_catalog_refreshes_public_metadata_without_membership() -> None:
    reader = CatalogReader()
    reader.query = lambda *_args, **_kwargs: []
    refreshed: list[str] = []

    result = ExposureQueryService(
        reader,
        catalog_records_refresher=lambda identifier: (
            refreshed.append(identifier)
            or (
                {
                    "source": "nvd",
                    "identifier": identifier,
                    "status": "succeeded",
                    "stale": False,
                    "payload": {"description": "Public NVD detail"},
                },
            )
        ),
    ).catalog_item(
        _authorization(),
        generation_id="generation-17",
        weakness_id="CVE-2026-0001",
    )

    assert refreshed == ["CVE-2026-0001"]
    assert result is not None
    assert result["item"]["sources"]["nvd"]["payload"]["description"] == (
        "Public NVD detail"
    )


def test_external_catalog_enforces_one_bound_after_merging_sources() -> None:
    reader = CatalogReader()
    service = ExposureQueryService(
        reader,
        catalog_records_resolver=lambda _identifier: tuple(
            {
                "source": "msrc",
                "identifier": f"KB{index:07d}",
                "status": "succeeded",
                "payload": {"kb_id": f"KB{index:07d}"},
            }
            for index in range(MAX_EXTERNAL_CATALOG_EVIDENCE_ROWS)
        ),
    )

    with pytest.raises(
        ExposureQueryUnavailableError,
        match="exceeded its safe bound",
    ):
        service.catalog_item(
            _authorization(),
            generation_id="generation-17",
            weakness_id="CVE-2026-0001",
        )


def test_external_catalog_rejects_durable_only_source_overflow() -> None:
    reader = CatalogReader()
    reader.query = lambda sql, parameters=(), max_rows=None: (
        [{"fact_id": "fact-1"}]
        if "SELECT TOP (1) [fact_id]" in sql
        else []
    )
    service = ExposureQueryService(
        reader,
        catalog_records_resolver=lambda _identifier: tuple(
            {
                "source": "msrc",
                "identifier": f"KB{index:07d}",
                "status": "succeeded",
                "payload": {"kb_id": f"KB{index:07d}"},
            }
            for index in range(MAX_EXTERNAL_CATALOG_EVIDENCE_ROWS + 1)
        ),
    )

    with pytest.raises(
        ExposureQueryUnavailableError,
        match="exceeded its safe bound",
    ):
        service.catalog_item(
            _authorization(),
            generation_id="generation-17",
            weakness_id="CVE-2026-0001",
        )


@pytest.mark.parametrize(
    ("query", "message"),
    [
        (
            ExposureQuery(
                filters=(ExposureFilter("payload_json", "eq", "secret"),)
            ),
            "Unsupported Exposure filter field",
        ),
        (
            ExposureQuery(sort=ExposureSort("payload_json", "asc")),
            "Unsupported Exposure sort field",
        ),
        (
            ExposureQuery(
                filters=(ExposureFilter("severity", "contains", "critical"),)
            ),
            "Unsupported Exposure filter operator",
        ),
    ],
)
def test_identifiers_and_operators_are_allowlisted_before_sql(
    query: ExposureQuery,
    message: str,
) -> None:
    reader = RecordingReader()

    with pytest.raises(ValueError, match=message):
        ExposureQueryService(reader).list_page(
            _authorization(),
            generation_id="generation-17",
            query=query,
        )

    assert reader.calls == []


def test_missing_production_reader_fails_closed_without_delta_fallback() -> None:
    with pytest.raises(
        ExposureQueryUnavailableError,
        match="Fabric SQL Exposure reader is unavailable",
    ):
        ExposureQueryService(None).list_page(
            _authorization(),
            generation_id="generation-17",
            query=ExposureQuery(),
        )


def test_search_wildcards_are_bound_and_escaped_as_literal_input() -> None:
    reader = RecordingReader()

    ExposureQueryService(reader).list_page(
        _authorization(),
        generation_id="generation-17",
        query=ExposureQuery(
            filters=(ExposureFilter("search", "contains", "CVE_%"),),
        ),
    )

    for call in reader.calls:
        assert "LIKE ? ESCAPE '\\'" in call["sql"]
        assert "CVE_%" not in call["sql"]
        assert call["parameters"][-3:] == (
            "%cve\\_\\%%",
            "%cve\\_\\%%",
            "%cve\\_\\%%",
        )


class _BoundedCursor:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.rows = rows
        self.description = [("value",)]
        self.timeout = 0
        self.executed: tuple[str, tuple[Any, ...]] | None = None
        self.fetchall_called = False

    def execute(self, sql: str, *parameters: Any) -> None:
        self.executed = (sql, tuple(parameters))

    def fetchmany(self, size: int) -> list[tuple[Any, ...]]:
        return self.rows[:size]

    def fetchall(self) -> list[tuple[Any, ...]]:
        self.fetchall_called = True
        return list(self.rows)


class _Connection:
    def __init__(self, cursor: _BoundedCursor) -> None:
        self._cursor = cursor

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def cursor(self) -> _BoundedCursor:
        return self._cursor


def test_fabric_reader_enforces_fetch_bound_and_statement_timeout() -> None:
    cursor = _BoundedCursor([(1,), (2,), (3,)])
    reader = FabricSqlReader(
        SqlEndpoint("server", "database"),
        SimpleNamespace(),
        timeout_seconds=7,
        connect=lambda: _Connection(cursor),
    )

    with pytest.raises(FabricSqlQueryLimitError, match="exceeded the 2-row limit"):
        reader.query("SELECT [value] FROM [dbo].[bounded]", max_rows=2)

    assert cursor.timeout == 7
    assert cursor.fetchall_called is False
