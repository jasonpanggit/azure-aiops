"""Actual SQL Server statement-timeout behavior; not a mocked deadline test."""

import re
from time import monotonic

import pytest

from ontology_discovery.sql_publication_control import (
    SqlPublicationControl,
    SqlPublicationError,
)
from tests.test_sql_publication_control import TARGET
from tests.test_sql_publication_control_integration import local_sql, pyodbc

__all__ = ["local_sql"]


def test_engine_statement_timeout_is_applied_once_and_sanitized(local_sql):
    _admin, connect = local_sql
    observed = {"connections": 0, "executions": 0}

    def tracked_connect():
        observed["connections"] += 1
        connection = connect()

        class TrackedCursor:
            def __init__(self, cursor):
                self._cursor = cursor

            def execute(self, query, values):
                observed["executions"] += 1
                try:
                    return self._cursor.execute(query, values)
                except pyodbc.Error as exc:
                    state = str(exc.args[0]) if exc.args else ""
                    observed["sqlstate"] = (
                        state if re.fullmatch(r"[A-Z0-9]{5}", state) else "unknown"
                    )
                    raise

            def close(self):
                self._cursor.close()
                observed["cursor_closed"] = True

            def __getattr__(self, name):
                return getattr(self._cursor, name)

        class TrackedConnection:
            @property
            def timeout(self):
                return connection.timeout

            @timeout.setter
            def timeout(self, seconds):
                connection.timeout = seconds
                observed["configured_seconds"] = seconds

            def cursor(self):
                assert observed.get("configured_seconds") == 1
                return TrackedCursor(connection.cursor())

            def close(self):
                connection.close()
                observed["connection_closed"] = True

        return TrackedConnection()

    control = SqlPublicationControl(
        TARGET, None, connect=tracked_connect, query_timeout_seconds=1,
    )
    started = monotonic()
    with pytest.raises(SqlPublicationError) as error:
        control._execute("WAITFOR DELAY '00:00:05'; SELECT 1", ())
    elapsed = monotonic() - started

    assert str(error.value) == "sql_publication:procedure_failed"
    assert .5 <= elapsed < 4.5
    assert observed == {
        "connections": 1,
        "executions": 1,
        "configured_seconds": 1,
        "sqlstate": "HYT00",
        "cursor_closed": True,
        "connection_closed": True,
    }
