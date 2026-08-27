"""Unit tests for `fabric.sql_endpoint`.

The SQL analytics endpoint is a read accelerator for the UI: it replaces
downloading whole Delta tables (see `DeltaWriter.read`) with pushed-down
aggregation. Because it depends on an ODBC driver that is not present in every
environment, the contract that matters most is that it stays strictly
optional -- `build_sql_reader` returns None instead of raising, so callers
fall back to the Delta path unchanged.

A fake `connect` callable is injected throughout so these run without pyodbc.
"""

from __future__ import annotations

import pytest

from fabric.sql_endpoint import FabricSqlReader, SqlEndpoint, build_sql_reader

ENDPOINT = SqlEndpoint(server="x.datawarehouse.fabric.microsoft.com", database="lakehouse")


class _FakeCursor:
    def __init__(self, script):
        self._script = script
        self.description = None
        self._rows = []

    def execute(self, sql, *parameters):
        self._script.executed.append((sql, parameters))
        columns, rows = self._script.result_for(sql)
        self.description = [(name,) for name in columns]
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeConnection:
    def __init__(self, script):
        self._script = script

    def cursor(self):
        return _FakeCursor(self._script)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Script:
    """Canned responses keyed by a substring of the SQL."""

    def __init__(self, responses):
        self.responses = responses
        self.executed: list[tuple[str, tuple]] = []

    def result_for(self, sql):
        for marker, result in self.responses.items():
            if marker in sql:
                return result
        return ([], [])

    def __call__(self):
        return _FakeConnection(self)


def _reader(responses):
    return FabricSqlReader(ENDPOINT, credential=None, connect=_Script(responses))


def test_query_returns_dicts():
    reader = _reader({"SELECT a": (["a", "b"], [(1, 2)])})
    assert reader.query("SELECT a, b FROM t") == [{"a": 1, "b": 2}]


def test_table_exists_binds_schema_and_name():
    script = _Script({"INFORMATION_SCHEMA.TABLES": (["c"], [(1,)])})
    reader = FabricSqlReader(ENDPOINT, credential=None, connect=script)

    assert reader.table_exists("bronze_resources") is True
    sql, parameters = script.executed[0]
    # The table name must be a bound parameter, never interpolated.
    assert "bronze_resources" not in sql
    assert parameters == ("dbo", "bronze_resources")


def test_table_exists_false_when_absent():
    assert _reader({}).table_exists("missing") is False


def test_max_timestamp_combines_columns():
    reader = _reader(
        {
            "INFORMATION_SCHEMA.COLUMNS": (["COLUMN_NAME"], [("ingested_at",), ("updated_at",)]),
            "MAX(": (["ingested_at", "updated_at"], [("2024-01-01", "2024-06-01")]),
        }
    )
    assert reader.max_timestamp("bronze_resources", ["ingested_at", "updated_at"]) == "2024-06-01"


def test_max_timestamp_ignores_columns_the_table_lacks():
    script = _Script(
        {
            "INFORMATION_SCHEMA.COLUMNS": (["COLUMN_NAME"], [("ingested_at",)]),
            "MAX(": (["ingested_at"], [("2024-01-01",)]),
        }
    )
    reader = FabricSqlReader(ENDPOINT, credential=None, connect=script)

    assert reader.max_timestamp("bronze_resources", ["ingested_at", "nope"]) == "2024-01-01"
    aggregate = next(sql for sql, _ in script.executed if "MAX(" in sql)
    assert "nope" not in aggregate


def test_max_timestamp_empty_when_no_column_matches():
    """An unpublished table must read as 'no watermark', matching the Delta
    path, rather than raising."""
    reader = _reader({"INFORMATION_SCHEMA.COLUMNS": (["COLUMN_NAME"], [])})
    assert reader.max_timestamp("bronze_resources", ["ingested_at"]) == ""


def test_read_table_projects_and_limits():
    script = _Script({"FROM": (["id"], [("a",)])})
    reader = FabricSqlReader(ENDPOINT, credential=None, connect=script)

    reader.read_table("ontology_entities", columns=["id", "kind"], limit=5)
    sql, _ = script.executed[0]
    assert "TOP (5)" in sql
    assert "[id], [kind]" in sql
    assert "[dbo].[ontology_entities]" in sql


@pytest.mark.parametrize("bad", ["a; DROP TABLE t", "a b", "", "a'b"])
def test_identifiers_are_validated(bad):
    with pytest.raises(ValueError):
        _reader({}).read_table(bad)


def test_build_sql_reader_returns_none_without_an_endpoint():
    assert build_sql_reader(None, credential=None) is None


@pytest.mark.parametrize(
    "endpoint",
    [{}, {"server": "x"}, {"database": "y"}, {"server": "", "database": "y"}],
)
def test_build_sql_reader_returns_none_for_incomplete_endpoints(endpoint):
    """Fabric provisions the SQL endpoint asynchronously, so a freshly created
    lakehouse legitimately reports one that isn't ready yet."""
    assert build_sql_reader(endpoint, credential=None) is None


def test_build_sql_reader_builds_from_mapping():
    reader = build_sql_reader(
        {"server": "x", "database": "y"}, credential=None, connect=_Script({})
    )
    assert isinstance(reader, FabricSqlReader)
    assert reader.endpoint.schema == "dbo"
