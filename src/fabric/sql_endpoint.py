"""Read path over the Fabric Lakehouse SQL analytics endpoint.

Every Lakehouse automatically exposes a read-only T-SQL endpoint over the same
Delta tables written to ``Tables/``. Reading through it is dramatically
cheaper than the Delta path for the queries the UI actually issues:

- :meth:`DeltaWriter.read` materializes an *entire* table into Python dicts.
  Computing a freshness watermark or a handful of counts therefore downloads
  every Parquet file in the table first.
- The SQL endpoint pushes aggregation and filtering down to the engine, so a
  ``MAX(timestamp)`` transfers a single row.

Generic Fabric callers may use this module as an optional accelerator and
fall back to Delta through :func:`build_sql_reader`. Production Exposure is
different: :func:`require_exposure_ready` proves every prerequisite and fails
closed rather than silently changing adapters.
"""

from __future__ import annotations

import importlib
import logging
import struct
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

_LOGGER = logging.getLogger(__name__)

# Fabric's SQL endpoint authenticates with an Entra token for the Azure SQL
# resource, passed through the ODBC connection attribute below.
SQL_SCOPE = "https://database.windows.net/.default"
FABRIC_SQL_ADAPTER_ID = "fabric_sql"
REQUIRED_ODBC_DRIVER = "ODBC Driver 18 for SQL Server"
REQUIRED_EXPOSURE_SCHEMA: dict[str, frozenset[str]] = {
    "gold_exposure_facts": frozenset(
        {
            "fact_id",
            "scope_key",
            "exposure_id",
            "read_model_generation_id",
            "tenant_id",
            "subscription_id",
            "connection_id",
            "active",
            "completeness",
            "current_state",
            "deployment_state",
            "detail_path",
            "evidence_count",
            "image_digest",
            "image_digest_id",
            "logical_image_id",
            "recommendation",
            "finding_title",
            "registry_id",
            "severity",
            "sla_age_seconds",
            "sla_due_at",
            "sla_overdue",
            "sla_state",
            "sla_target_seconds",
            "source_state",
            "source_status",
            "target_id",
            "target_kind",
            "source_family",
            "priority_score",
            "represented_workload_count",
            "timestamp",
            "total_workload_count",
            "unknown_workload_count",
            "weakness_id",
            "weakness_kind",
            "ordering_priority_score",
            "ordering_severity_rank",
            "ordering_target_id",
        }
    ),
    "gold_exposure_facets": frozenset(
        {
            "read_model_generation_id",
            "tenant_id",
            "subscription_id",
            "scope_key",
            "dimension_name",
            "dimension_value",
            "exposure_count",
        }
    ),
    "gold_exposure_summaries": frozenset(
        {
            "read_model_generation_id",
            "tenant_id",
            "subscription_id",
            "scope_key",
            "connection_id",
            "exposure_count",
        }
    ),
    "metadata_exposure_gold_generations": frozenset(
        {
            "read_model_generation_id",
            "reconciliation_status",
            "published_at",
            "retain_until",
        }
    ),
}
_SQL_COPT_SS_ACCESS_TOKEN = 1256

_IDENTIFIER_ALLOWED = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")


def _quote_identifier(value: str) -> str:
    """Validate and bracket-quote a T-SQL identifier.

    Table and column names reach this module from configuration and from the
    layer/name pairs used by the sync service, never from end users. They are
    still validated against a strict allow-list rather than interpolated
    blindly, so a malformed name fails loudly instead of composing SQL.
    """
    if not value or any(character not in _IDENTIFIER_ALLOWED for character in value):
        raise ValueError(f"Invalid SQL identifier: {value!r}")
    return f"[{value}]"


@dataclass(frozen=True)
class SqlEndpoint:
    """Connection details for a Lakehouse SQL analytics endpoint."""

    server: str
    database: str
    schema: str = "dbo"


@dataclass(frozen=True)
class FabricSqlReadinessCheck:
    """One sanitized prerequisite result for the production Exposure adapter."""

    check_id: str
    status: str
    reason_code: str
    detail: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "status": self.status,
            "reason_code": self.reason_code,
            "detail": dict(self.detail),
        }


@dataclass(frozen=True)
class FabricSqlReadinessResult:
    """Complete, secret-free readiness evidence for production Exposure."""

    checks: tuple[FabricSqlReadinessCheck, ...]
    adapter_id: str = FABRIC_SQL_ADAPTER_ID

    @property
    def ready(self) -> bool:
        return bool(self.checks) and all(check.status == "ready" for check in self.checks)

    @property
    def reason_codes(self) -> tuple[str, ...]:
        return tuple(
            check.reason_code for check in self.checks if check.status != "ready"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0.0",
            "probe": "production_exposure_adapter",
            "selected_production_adapter": self.adapter_id,
            "ready": self.ready,
            "status": "ready" if self.ready else "not_ready",
            "fallback": {
                "adapter_id": "delta",
                "selected": False,
                "production_scale_certified": False,
            },
            "checks": [check.to_dict() for check in self.checks],
            "reason_codes": list(self.reason_codes),
            "sanitized": True,
        }


class FabricSqlReadinessError(RuntimeError):
    """Raised when production Exposure cannot prove its SQL prerequisites."""

    def __init__(self, result: FabricSqlReadinessResult) -> None:
        self.result = result
        reasons = ", ".join(result.reason_codes) or "unknown"
        super().__init__(
            f"Production Exposure adapter {result.adapter_id!r} is not ready: {reasons}"
        )


class FabricSqlQueryLimitError(RuntimeError):
    """Raised before a query can materialize more rows than its contract."""


class FabricSqlReader:
    """Executes read-only queries against the Lakehouse SQL endpoint."""

    def __init__(
        self,
        endpoint: SqlEndpoint,
        credential: Any,
        *,
        driver: str = "ODBC Driver 18 for SQL Server",
        timeout_seconds: int = 30,
        connect: Any | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.credential = credential
        self.driver = driver
        self.timeout_seconds = timeout_seconds
        self._connect = connect

    def _connection(self):
        if self._connect is not None:
            return self._connect()
        import pyodbc

        connection_string = (
            f"Driver={{{self.driver}}};"
            f"Server={self.endpoint.server},1433;"
            f"Database={self.endpoint.database};"
            "Encrypt=Yes;TrustServerCertificate=No;"
        )
        token = self.credential.get_token(SQL_SCOPE).token.encode("utf-16-le")
        # The ODBC access-token attribute expects a length-prefixed UTF-16
        # buffer rather than a plain string.
        packed = struct.pack("<I", len(token)) + token
        return pyodbc.connect(
            connection_string,
            timeout=self.timeout_seconds,
            attrs_before={_SQL_COPT_SS_ACCESS_TOKEN: packed},
        )

    def query(
        self,
        sql: str,
        parameters: Iterable[Any] = (),
        *,
        max_rows: int | None = None,
    ) -> list[dict[str, Any]]:
        """Run ``sql`` and return rows as dicts.

        Values are always bound.  Production query paths additionally provide
        ``max_rows`` so an accidentally broadened SQL statement cannot
        materialize the full table in the API process.
        """
        if max_rows is not None and (
            isinstance(max_rows, bool)
            or not isinstance(max_rows, int)
            or max_rows < 1
        ):
            raise ValueError("max_rows must be a positive integer")
        with self._connection() as connection:
            cursor = connection.cursor()
            if hasattr(cursor, "timeout"):
                cursor.timeout = self.timeout_seconds
            cursor.execute(sql, *parameters)
            columns = [column[0] for column in cursor.description or []]
            if max_rows is None:
                rows = cursor.fetchall()
            else:
                rows = cursor.fetchmany(max_rows + 1)
                if len(rows) > max_rows:
                    raise FabricSqlQueryLimitError(
                        f"Fabric SQL query exceeded the {max_rows}-row limit"
                    )
            return [dict(zip(columns, row, strict=False)) for row in rows]

    def table_exists(self, table: str) -> bool:
        rows = self.query(
            "SELECT 1 FROM INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?",
            (self.endpoint.schema, table),
        )
        return bool(rows)

    def max_timestamp(self, table: str, columns: Iterable[str]) -> str:
        """Return the greatest value across ``columns`` in ``table``.

        This is the SQL replacement for downloading a whole table to compute
        a freshness watermark. Each column is aggregated with its own
        ``MAX()`` and combined in Python rather than with ``GREATEST``, which
        is not available across all Fabric SQL surface versions. Missing
        tables and columns yield ``""`` so the caller can treat an
        unpublished table as "no watermark", matching the Delta path.
        """
        present = self.column_names(table)
        selected = [column for column in columns if column in present]
        if not selected:
            return ""
        projection = ", ".join(
            f"MAX({_quote_identifier(name)}) AS {_quote_identifier(name)}"
            for name in selected
        )
        sql = (
            f"SELECT {projection} FROM "
            f"{_quote_identifier(self.endpoint.schema)}.{_quote_identifier(table)}"
        )
        rows = self.query(sql)
        if not rows:
            return ""
        return max((str(value or "") for value in rows[0].values()), default="")

    def column_names(self, table: str) -> set[str]:
        rows = self.query(
            "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?",
            (self.endpoint.schema, table),
        )
        return {str(row["COLUMN_NAME"]) for row in rows}

    def read_table(
        self,
        table: str,
        *,
        columns: Iterable[str] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Read ``table``, optionally projecting columns and capping rows.

        Projection matters for the UI: the ontology entity table is wide, and
        most views need a handful of columns.
        """
        projection = (
            ", ".join(_quote_identifier(name) for name in columns) if columns else "*"
        )
        top = f"TOP ({int(limit)}) " if limit else ""
        sql = (
            f"SELECT {top}{projection} FROM "
            f"{_quote_identifier(self.endpoint.schema)}.{_quote_identifier(table)}"
        )
        return self.query(sql)


def build_sql_reader(
    endpoint: Mapping[str, str] | SqlEndpoint | None,
    credential: Any,
    **options: Any,
) -> FabricSqlReader | None:
    """Build a reader, or ``None`` when the endpoint/driver is unavailable.

    Returning ``None`` rather than raising keeps the SQL endpoint strictly
    optional: a deployment without an ODBC driver silently continues to use
    the Delta read path.
    """
    if endpoint is None:
        return None
    if isinstance(endpoint, Mapping):
        server = str(endpoint.get("server") or "").strip()
        database = str(endpoint.get("database") or "").strip()
        if not server or not database:
            return None
        endpoint = SqlEndpoint(
            server=server,
            database=database,
            schema=str(endpoint.get("schema") or "dbo"),
        )
    if options.get("connect") is None:
        try:
            import pyodbc  # noqa: F401
        except ImportError:
            _LOGGER.info(
                "pyodbc is not installed; Fabric SQL endpoint reads are disabled "
                "and Delta reads will be used instead"
            )
            return None
    return FabricSqlReader(endpoint, credential, **options)


def _readiness_check(
    check_id: str,
    status: str,
    reason_code: str,
    **detail: Any,
) -> FabricSqlReadinessCheck:
    return FabricSqlReadinessCheck(
        check_id=check_id,
        status=status,
        reason_code=reason_code,
        detail=detail,
    )


def _validated_endpoint(
    endpoint: Mapping[str, str] | SqlEndpoint | None,
) -> SqlEndpoint | None:
    if endpoint is None:
        return None
    if isinstance(endpoint, SqlEndpoint):
        candidate = endpoint
    else:
        candidate = SqlEndpoint(
            server=str(endpoint.get("server") or "").strip(),
            database=str(endpoint.get("database") or "").strip(),
            schema=str(endpoint.get("schema") or "dbo").strip(),
        )
    if not candidate.server or not candidate.database or not candidate.schema:
        return None
    try:
        _quote_identifier(candidate.schema)
    except ValueError:
        return None
    return candidate


def _evaluate_exposure_readiness(
    endpoint: Mapping[str, str] | SqlEndpoint | None,
    credential: Any,
    *,
    driver: str,
    connect: Any | None,
    module_loader: Any,
    endpoint_source: str,
) -> tuple[FabricSqlReadinessResult, FabricSqlReader | None]:
    checks: list[FabricSqlReadinessCheck] = []
    validated_endpoint = _validated_endpoint(endpoint)
    endpoint_ready = validated_endpoint is not None
    checks.append(
        _readiness_check(
            "lakehouse_sql_endpoint_metadata",
            "ready" if endpoint_ready else "not_ready",
            "ready" if endpoint_ready else "fabric_sql_endpoint_metadata_missing_or_invalid",
            configured=endpoint_ready,
            source=endpoint_source if endpoint_ready else "none",
        )
    )

    pyodbc_module: Any | None
    try:
        pyodbc_module = module_loader("pyodbc")
    except Exception:  # noqa: BLE001 - readiness output must stay sanitized.
        pyodbc_module = None
    module_ready = pyodbc_module is not None
    checks.append(
        _readiness_check(
            "pyodbc_import",
            "ready" if module_ready else "not_ready",
            "ready" if module_ready else "pyodbc_not_importable",
            importable=module_ready,
        )
    )

    registered_drivers: list[str] = []
    if pyodbc_module is not None:
        try:
            registered_drivers = [str(item) for item in pyodbc_module.drivers()]
        except Exception:  # noqa: BLE001 - readiness output must stay sanitized.
            registered_drivers = []
    driver_ready = driver in registered_drivers
    checks.append(
        _readiness_check(
            "microsoft_odbc_driver_18",
            "ready" if driver_ready else "not_ready",
            "ready" if driver_ready else "odbc_driver_18_not_registered",
            registered=driver_ready,
            registered_driver_count=len(registered_drivers),
        )
    )

    token_ready = False
    token_blocked = not endpoint_ready or not module_ready or not driver_ready
    if not token_blocked:
        try:
            token = credential.get_token(SQL_SCOPE)
            token_ready = bool(getattr(token, "token", ""))
        except Exception:  # noqa: BLE001 - never expose credential/provider details.
            token_ready = False
    checks.append(
        _readiness_check(
            "entra_token",
            "ready" if token_ready else ("blocked" if token_blocked else "not_ready"),
            (
                "ready"
                if token_ready
                else (
                    "entra_token_check_blocked_by_local_prerequisite"
                    if token_blocked
                    else "entra_token_unavailable"
                )
            ),
            acquired=token_ready,
        )
    )

    reader: FabricSqlReader | None = None
    connectivity_ready = False
    connectivity_blocked = not (
        endpoint_ready and module_ready and driver_ready and token_ready
    )
    if not connectivity_blocked and validated_endpoint is not None:
        try:
            reader = FabricSqlReader(
                validated_endpoint,
                credential,
                driver=driver,
                connect=connect,
            )
            connectivity_ready = bool(reader.query("SELECT 1 AS probe"))
        except Exception:  # noqa: BLE001 - readiness output must stay sanitized.
            reader = None
            connectivity_ready = False
    checks.append(
        _readiness_check(
            "token_connectivity",
            (
                "ready"
                if connectivity_ready
                else ("blocked" if connectivity_blocked else "not_ready")
            ),
            (
                "ready"
                if connectivity_ready
                else (
                    "fabric_sql_connectivity_blocked_by_local_prerequisite"
                    if connectivity_blocked
                    else "fabric_sql_connectivity_failed"
                )
            ),
            connected=connectivity_ready,
        )
    )

    schema_ready = False
    missing_tables: list[str] = []
    missing_columns: dict[str, list[str]] = {}
    if connectivity_ready and reader is not None:
        try:
            for table, required_columns in REQUIRED_EXPOSURE_SCHEMA.items():
                if not reader.table_exists(table):
                    missing_tables.append(table)
                    continue
                absent = sorted(required_columns - reader.column_names(table))
                if absent:
                    missing_columns[table] = absent
            schema_ready = not missing_tables and not missing_columns
        except Exception:  # noqa: BLE001 - readiness output must stay sanitized.
            schema_ready = False
    checks.append(
        _readiness_check(
            "required_gold_schema",
            "ready" if schema_ready else ("blocked" if not connectivity_ready else "not_ready"),
            (
                "ready"
                if schema_ready
                else (
                    "gold_schema_check_blocked_by_connectivity"
                    if not connectivity_ready
                    else "required_gold_schema_missing"
                )
            ),
            missing_tables=missing_tables,
            missing_columns=missing_columns,
            required_tables=sorted(REQUIRED_EXPOSURE_SCHEMA),
            required_columns={
                table: sorted(columns)
                for table, columns in sorted(REQUIRED_EXPOSURE_SCHEMA.items())
            },
        )
    )

    bounded_query_ready = False
    if schema_ready and reader is not None and validated_endpoint is not None:
        try:
            qualified = (
                f"{_quote_identifier(validated_endpoint.schema)}."
                f"{_quote_identifier('gold_exposure_facts')}"
            )
            probe_generation = "__readiness_probe__"
            probe_subscription = "00000000-0000-0000-0000-000000000000"
            reader.query(
                f"SELECT COUNT_BIG(1) AS total_count FROM {qualified} "
                "WHERE [read_model_generation_id] = ? AND [subscription_id] = ?",
                (probe_generation, probe_subscription),
            )
            reader.query(
                "SELECT TOP (1) [exposure_id], [ordering_priority_score] "
                f"FROM {qualified} "
                "WHERE [read_model_generation_id] = ? AND [subscription_id] = ? "
                "AND ([ordering_priority_score] < ? OR "
                "([ordering_priority_score] = ? AND [exposure_id] > ?)) "
                "ORDER BY [ordering_priority_score] DESC, [exposure_id] ASC",
                (probe_generation, probe_subscription, 0, 0, ""),
            )
            bounded_query_ready = True
        except Exception:  # noqa: BLE001 - readiness output must stay sanitized.
            bounded_query_ready = False
    checks.append(
        _readiness_check(
            "bound_count_and_page_query",
            "ready" if bounded_query_ready else ("blocked" if not schema_ready else "not_ready"),
            (
                "ready"
                if bounded_query_ready
                else (
                    "bound_query_check_blocked_by_schema"
                    if not schema_ready
                    else "bound_count_or_page_query_failed"
                )
            ),
            parameters_bound=True,
            page_bounded=True,
        )
    )
    return FabricSqlReadinessResult(tuple(checks)), reader


def probe_exposure_readiness(
    endpoint: Mapping[str, str] | SqlEndpoint | None,
    credential: Any,
    *,
    driver: str = REQUIRED_ODBC_DRIVER,
    connect: Any | None = None,
    module_loader: Any = importlib.import_module,
    endpoint_source: str = "runtime",
) -> FabricSqlReadinessResult:
    """Probe every production Exposure SQL prerequisite without leaking details."""
    result, _reader = _evaluate_exposure_readiness(
        endpoint,
        credential,
        driver=driver,
        connect=connect,
        module_loader=module_loader,
        endpoint_source=endpoint_source,
    )
    return result


def require_exposure_ready(
    endpoint: Mapping[str, str] | SqlEndpoint | None,
    credential: Any,
    *,
    driver: str = REQUIRED_ODBC_DRIVER,
    connect: Any | None = None,
    module_loader: Any = importlib.import_module,
    endpoint_source: str = "runtime",
) -> FabricSqlReader:
    """Return the selected production reader or raise a sanitized typed error."""
    result, reader = _evaluate_exposure_readiness(
        endpoint,
        credential,
        driver=driver,
        connect=connect,
        module_loader=module_loader,
        endpoint_source=endpoint_source,
    )
    if not result.ready or reader is None:
        raise FabricSqlReadinessError(result)
    return reader


__all__ = [
    "FABRIC_SQL_ADAPTER_ID",
    "REQUIRED_EXPOSURE_SCHEMA",
    "REQUIRED_ODBC_DRIVER",
    "SQL_SCOPE",
    "FabricSqlQueryLimitError",
    "FabricSqlReader",
    "FabricSqlReadinessCheck",
    "FabricSqlReadinessError",
    "FabricSqlReadinessResult",
    "SqlEndpoint",
    "build_sql_reader",
    "probe_exposure_readiness",
    "require_exposure_ready",
]
