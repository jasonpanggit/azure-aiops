"""Integration contracts for scope-first Fabric SQL Exposure reads."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Self

import pytest

from api.exposure_query import (
    MAX_EXTERNAL_CATALOG_EVIDENCE_ROWS,
    ExposureAuthorization,
    ExposureFilter,
    ExposureQuery,
    ExposureQueryService,
    ExposureQueryUnavailableError,
    ExposureSort,
)
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


def _authorization() -> ExposureAuthorization:
    return ExposureAuthorization(
        subject="operator@example.com",
        tenant_id="tenant-authorized",
        connection_ids=("connection-b", "connection-a"),
        scope={
            "subscription": ("subscription-b", "subscription-a"),
            "subscription_connection": ("connection-b", "connection-a"),
        },
    )


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

    assert len(reader.calls) == 1
    call = reader.calls[0]
    sql = call["sql"]
    assert "[gold_exposure_facts]" in sql
    assert "[gold_exposure_evidence]" in sql
    assert f"TOP ({MAX_EXTERNAL_CATALOG_EVIDENCE_ROWS + 1})" in sql
    assert "ROW_NUMBER() OVER (PARTITION BY [e].[source], [e].[identifier]" in sql
    assert "WHERE [evidence_rank] = 1" in sql
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
        '%"CVE-2026-0001"%',
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
