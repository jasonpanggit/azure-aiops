"""Read path over the Fabric Lakehouse SQL analytics endpoint.

Every Lakehouse automatically exposes a read-only T-SQL endpoint over the same
Delta tables written to ``Tables/``. Reading through it is dramatically
cheaper than the Delta path for the queries the UI actually issues:

- :meth:`DeltaWriter.read` materializes an *entire* table into Python dicts.
  Computing a freshness watermark or a handful of counts therefore downloads
  every Parquet file in the table first.
- The SQL endpoint pushes aggregation and filtering down to the engine, so a
  ``MAX(timestamp)`` transfers a single row.

This module is an accelerator, not a requirement. It needs an ODBC driver,
which is not present in every environment, so :func:`build_sql_reader`
returns ``None`` when the endpoint or driver is unavailable and callers fall
back to the Delta read path unchanged.
"""

from __future__ import annotations

import logging
import struct
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

_LOGGER = logging.getLogger(__name__)

# Fabric's SQL endpoint authenticates with an Entra token for the Azure SQL
# resource, passed through the ODBC connection attribute below.
SQL_SCOPE = "https://database.windows.net/.default"
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

    def query(self, sql: str, parameters: Iterable[Any] = ()) -> list[dict[str, Any]]:
        """Run ``sql`` and return rows as dicts. Parameters are always bound."""
        with self._connection() as connection:
            cursor = connection.cursor()
            cursor.execute(sql, *parameters)
            columns = [column[0] for column in cursor.description or []]
            return [dict(zip(columns, row, strict=False)) for row in cursor.fetchall()]

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


__all__ = ["SQL_SCOPE", "FabricSqlReader", "SqlEndpoint", "build_sql_reader"]
