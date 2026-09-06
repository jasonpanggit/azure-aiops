"""Integration contracts for scope-first Fabric SQL Exposure reads."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Self

import pytest

from api.exposure_query import (
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
