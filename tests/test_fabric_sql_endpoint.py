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

from pathlib import Path
from types import SimpleNamespace

import pytest

import fabric.runtime as fabric_runtime
from fabric.config import FabricRuntimeConfig
from fabric.sql_endpoint import (
    REQUIRED_EXPOSURE_SCHEMA,
    FabricSqlReader,
    FabricSqlReadinessError,
    SqlEndpoint,
    build_sql_reader,
    probe_exposure_readiness,
    require_exposure_ready,
)

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
                if isinstance(result, Exception):
                    raise result
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


class _Credential:
    def __init__(self, *, available: bool = True):
        self.available = available

    def get_token(self, _scope):
        if not self.available:
            raise RuntimeError("credential details must remain sanitized")
        return SimpleNamespace(token="test-token-never-reported")


class _Pyodbc:
    @staticmethod
    def drivers():
        return ["ODBC Driver 18 for SQL Server"]


def _ready_responses():
    columns = sorted(set().union(*REQUIRED_EXPOSURE_SCHEMA.values()))
    return {
        "SELECT 1 AS probe": (["probe"], [(1,)]),
        "INFORMATION_SCHEMA.TABLES": (["present"], [(1,)]),
        "INFORMATION_SCHEMA.COLUMNS": (
            ["COLUMN_NAME"],
            [(column,) for column in columns],
        ),
        "COUNT_BIG": (["total_count"], [(0,)]),
        "SELECT TOP (1)": (["exposure_id", "priority_score"], []),
    }


def _module_loader(_name):
    return _Pyodbc()


def _missing_module(_name):
    raise ImportError("pyodbc unavailable")


def test_exposure_readiness_reports_every_missing_prerequisite():
    result = probe_exposure_readiness(
        None,
        credential=None,
        module_loader=_missing_module,
    )

    assert result.adapter_id == "fabric_sql"
    assert result.ready is False
    assert result.reason_codes == (
        "fabric_sql_endpoint_metadata_missing_or_invalid",
        "pyodbc_not_importable",
        "odbc_driver_18_not_registered",
        "entra_token_check_blocked_by_local_prerequisite",
        "fabric_sql_connectivity_blocked_by_local_prerequisite",
        "gold_schema_check_blocked_by_connectivity",
        "bound_query_check_blocked_by_schema",
    )
    assert result.to_dict()["sanitized"] is True


@pytest.mark.parametrize(
    ("responses", "credential", "reason_code"),
    [
        (
            {"SELECT 1 AS probe": RuntimeError("provider detail")},
            _Credential(),
            "fabric_sql_connectivity_failed",
        ),
        (
            {
                "SELECT 1 AS probe": (["probe"], [(1,)]),
                "INFORMATION_SCHEMA.TABLES": (["present"], []),
            },
            _Credential(),
            "required_gold_schema_missing",
        ),
        (
            {
                "SELECT 1 AS probe": (["probe"], [(1,)]),
                "INFORMATION_SCHEMA.TABLES": (["present"], [(1,)]),
                "INFORMATION_SCHEMA.COLUMNS": (["COLUMN_NAME"], [("exposure_id",)]),
            },
            _Credential(),
            "required_gold_schema_missing",
        ),
        (
            {
                **_ready_responses(),
                "COUNT_BIG": RuntimeError("provider detail"),
            },
            _Credential(),
            "bound_count_or_page_query_failed",
        ),
    ],
)
def test_exposure_readiness_uses_stable_sanitized_failure_codes(
    responses, credential, reason_code
):
    result = probe_exposure_readiness(
        ENDPOINT,
        credential,
        module_loader=_module_loader,
        connect=_Script(responses),
    )

    assert result.ready is False
    assert reason_code in result.reason_codes
    rendered = str(result.to_dict())
    assert "provider detail" not in rendered
    assert "test-token-never-reported" not in rendered


def test_exposure_readiness_reports_token_failure_without_connecting():
    script = _Script(_ready_responses())

    result = probe_exposure_readiness(
        ENDPOINT,
        _Credential(available=False),
        module_loader=_module_loader,
        connect=script,
    )

    assert result.ready is False
    assert "entra_token_unavailable" in result.reason_codes
    assert script.executed == []


def test_successful_exposure_readiness_runs_connectivity_and_bound_probes():
    script = _Script(_ready_responses())

    result = probe_exposure_readiness(
        ENDPOINT,
        _Credential(),
        module_loader=_module_loader,
        connect=script,
    )

    assert result.ready is True
    assert result.adapter_id == "fabric_sql"
    assert result.reason_codes == ()
    assert any(sql == "SELECT 1 AS probe" for sql, _ in script.executed)
    count_sql, count_parameters = next(
        item for item in script.executed if "COUNT_BIG" in item[0]
    )
    page_sql, page_parameters = next(
        item for item in script.executed if "SELECT TOP (1)" in item[0]
    )
    assert "?" in count_sql and len(count_parameters) == 2
    assert "?" in page_sql and len(page_parameters) == 5


def test_require_exposure_ready_returns_reader_or_raises_typed_error():
    reader = require_exposure_ready(
        ENDPOINT,
        _Credential(),
        module_loader=_module_loader,
        connect=_Script(_ready_responses()),
    )
    assert isinstance(reader, FabricSqlReader)

    with pytest.raises(FabricSqlReadinessError) as captured:
        require_exposure_ready(
            None,
            credential=None,
            module_loader=_missing_module,
        )
    assert captured.value.result.adapter_id == "fabric_sql"
    assert "fabric_sql_endpoint_metadata_missing_or_invalid" in str(captured.value)


def _write_fabric_config(path: Path, exposure: str = "") -> FabricRuntimeConfig:
    path.write_text(
        f"""
fabric:
  workspace_name: workspace
  lakehouse_name: lakehouse
{exposure}
"""
    )
    return FabricRuntimeConfig.load(path)


def test_exposure_config_is_default_off_and_strict(tmp_path):
    config = _write_fabric_config(tmp_path / "fabric.yaml")
    assert config.exposure.enabled is False
    assert config.exposure.adapter == "fabric_sql"
    assert config.exposure.rollback_mode is False

    with pytest.raises(TypeError, match="fabric.exposure.enabled must be boolean"):
        _write_fabric_config(
            tmp_path / "invalid.yaml",
            """
  exposure:
    enabled: "true"
""",
        )


def test_deployed_config_requires_fabric_sql_without_delta_rollback():
    config = FabricRuntimeConfig.load(
        Path(__file__).parents[1] / "fabric.config.deploy.yaml"
    )
    assert config.exposure.enabled is True
    assert config.exposure.adapter == "fabric_sql"
    assert config.exposure.rollback_mode is False


def test_runtime_requires_readiness_only_for_enabled_nonrollback_exposure(
    monkeypatch, tmp_path
):
    lakehouse = {
        "displayName": "lakehouse",
        "properties": {
            "sqlEndpointProperties": {
                "connectionString": "server",
                "id": "database",
            }
        },
    }
    optional_reader = object()
    required_reader = object()
    monkeypatch.setattr(
        fabric_runtime, "build_sql_reader", lambda *_args, **_kwargs: optional_reader
    )
    monkeypatch.setattr(
        fabric_runtime,
        "require_exposure_ready",
        lambda *_args, **_kwargs: required_reader,
    )

    default_config = _write_fabric_config(tmp_path / "default.yaml")
    assert (
        fabric_runtime._build_lakehouse_sql_reader(
            lakehouse, object(), default_config
        )
        is optional_reader
    )

    enabled_config = _write_fabric_config(
        tmp_path / "enabled.yaml",
        """
  exposure:
    enabled: true
    adapter: fabric_sql
    rollback_mode: false
""",
    )
    assert (
        fabric_runtime._build_lakehouse_sql_reader(
            lakehouse, object(), enabled_config
        )
        is required_reader
    )

    rollback_config = _write_fabric_config(
        tmp_path / "rollback.yaml",
        """
  exposure:
    enabled: true
    adapter: fabric_sql
    rollback_mode: true
""",
    )
    assert (
        fabric_runtime._build_lakehouse_sql_reader(
            lakehouse, object(), rollback_config
        )
        is None
    )
