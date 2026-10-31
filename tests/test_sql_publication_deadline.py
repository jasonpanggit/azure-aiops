"""Statement deadline configuration, not actual SQL-engine timeout evidence."""

import json

import pytest

from ontology_discovery.sql_publication_control import (
    SqlPublicationControl,
    SqlPublicationError,
)
from tests.test_sql_publication_control import TARGET, UID, Connection, Cursor, pyodbc


@pytest.mark.parametrize("seconds", [1, 30, 300])
def test_query_timeout_set_before_cursor_creation(seconds):
    cursor = Cursor([(json.dumps({"revision": 0}),)], ["result_json"])

    class CheckedConnection(Connection):
        def cursor(self):
            assert self.timeout == seconds
            return super().cursor()

    connection = CheckedConnection(cursor)
    control = SqlPublicationControl(
        TARGET,
        None,
        connect=lambda: connection,
        query_timeout_seconds=seconds,
    )
    assert control.read_control(UID) == {"revision": 0}
    assert connection.closed and cursor.closed


@pytest.mark.parametrize("seconds", [0, -1, 301, True, 1.5, None])
def test_invalid_deadline_rejected_without_connection(seconds):
    def connect():
        raise AssertionError("Invalid deadline must not open a connection")

    with pytest.raises(SqlPublicationError, match="query_timeout"):
        SqlPublicationControl(
            TARGET,
            None,
            connect=connect,
            query_timeout_seconds=seconds,
        )


def test_odbc_statement_timeout_is_sanitized_and_resources_close():
    cursor = Cursor(fail=pyodbc.Error("HYT00 secret SQL parameters"))
    connection = Connection(cursor)
    control = SqlPublicationControl(TARGET, None, connect=lambda: connection)
    with pytest.raises(SqlPublicationError) as error:
        control.read_control(UID)
    assert str(error.value) == "sql_publication:procedure_failed"
    assert error.value.__suppress_context__
    assert connection.closed and cursor.closed


def test_timeout_configuration_failure_closes_connection_without_execution():
    cursor = Cursor()

    class RejectingConnection(Connection):
        @property
        def timeout(self):
            return 0

        @timeout.setter
        def timeout(self, value):
            raise pyodbc.Error("secret timeout setting failure")

    connection = RejectingConnection(cursor)
    control = SqlPublicationControl(TARGET, None, connect=lambda: connection)
    with pytest.raises(SqlPublicationError, match="procedure_failed"):
        control.read_control(UID)
    assert connection.closed
    assert not cursor.calls
