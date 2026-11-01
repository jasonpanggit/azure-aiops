"""Offline session-isolation contracts, not actual driver pooling qualification."""

import json
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pyodbc
import pytest

from ontology_discovery.sql_publication_control import (
    SqlPublicationAuthority,
    SqlPublicationControl,
    SqlPublicationError,
)
from tests.test_sql_publication_control import TARGET, UID, Connection, Cursor

READER = str(uuid4())


def session(client=UID, database=TARGET.database, *, trailing_error=False):
    identity = Cursor(
        [(database, client)],
        ["database", "client"],
        trailing_error=trailing_error,
    )
    operation = Cursor([(json.dumps({"revision": 0}),)], ["result_json"])
    connection = Connection(operation)
    cursors = iter((identity, operation))
    connection.cursor = lambda: next(cursors)
    return connection, identity, operation


@pytest.fixture
def driver(monkeypatch):
    monkeypatch.setattr(pyodbc, "pooling", False)
    monkeypatch.setattr(pyodbc, "drivers", lambda: ["ODBC Driver 18 for SQL Server"])
    connections, calls = [], []

    def connect(dsn, **kwargs):
        calls.append((dsn, kwargs))
        return connections.pop(0)

    monkeypatch.setattr(pyodbc, "connect", connect)
    return connections, calls


def credential():
    return SimpleNamespace(get_token=lambda _: SimpleNamespace(token="offline-token"))


def test_native_connection_requires_operator_client_pin_before_token_or_connect(driver):
    _, calls = driver
    with pytest.raises(SqlPublicationError, match="client_identity_required"):
        SqlPublicationControl(TARGET, None).read_control(UID)
    assert not calls


def test_pooling_enabled_refuses_before_token_or_connect(driver, monkeypatch):
    _, calls = driver
    monkeypatch.setattr(pyodbc, "pooling", True)
    with pytest.raises(
        SqlPublicationError, match="pooling_must_be_disabled_at_startup"
    ):
        SqlPublicationControl(TARGET, None, expected_client_id=UID).read_control(UID)
    assert not calls
    assert pyodbc.pooling is True


@pytest.mark.parametrize("kind", [SqlPublicationControl, SqlPublicationAuthority])
def test_cross_identity_pool_reuse_refused_before_any_business_procedure(driver, kind):
    connections, _ = driver
    connection, identity, operation = session(UID)
    connections.append(connection)
    client = kind(TARGET, credential(), expected_client_id=READER)
    with pytest.raises(SqlPublicationError, match="session_identity_mismatch"):
        client._connection()
    assert connection.closed and identity.closed
    assert not operation.calls


def test_same_dsn_distinct_identities_are_verified_on_every_checkout(driver):
    connections, calls = driver
    reader = SqlPublicationControl(TARGET, credential(), expected_client_id=READER)
    authority = SqlPublicationAuthority(TARGET, credential(), expected_client_id=UID)
    for client, sid in (
        (authority, UID),
        (reader, READER),
        (authority, UID),
        (reader, READER),
    ):
        connection, identity, operation = session(sid.upper())
        connections.append(connection)
        checked = client._connection()
        assert checked is connection and identity.closed
        assert not operation.calls
        checked.close()
    assert len(calls) == 4 and len({dsn for dsn, _ in calls}) == 1


def test_late_pooling_flag_change_does_not_bypass_server_identity_check(driver):
    connections, _ = driver
    pooled, identity, operation = session(UID)
    connections.append(pooled)
    with pytest.raises(SqlPublicationError, match="session_identity_mismatch"):
        SqlPublicationControl(
            TARGET, credential(), expected_client_id=READER
        ).read_control(UID)
    assert pooled.closed and identity.closed and not operation.calls


def test_database_mismatch_is_refused(driver):
    connections, _ = driver
    connection, identity, operation = session()
    connections.append(connection)
    with pytest.raises(SqlPublicationError, match="session_identity_mismatch"):
        SqlPublicationControl(
            replace(
                TARGET,
                database="other",
                resource_id=TARGET.resource_id.replace(
                    "/databases/publication_test",
                    "/databases/other",
                ),
            ),
            credential(),
            expected_client_id=UID,
        ).read_control(UID)
    assert connection.closed and identity.closed and not operation.calls


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [(TARGET.database, None)],
        [(TARGET.database, b"wrong")],
        [(TARGET.database, UID)] * 2,
        [(TARGET.database, UID, "extra")],
    ],
)
def test_malformed_identity_result_cannot_reach_operation(driver, rows):
    connections, _ = driver
    connection, identity, operation = session()
    identity.rows = rows
    connections.append(connection)
    with pytest.raises(SqlPublicationError, match="session_identity_mismatch"):
        SqlPublicationControl(
            TARGET, credential(), expected_client_id=UID
        ).read_control(UID)
    assert connection.closed and identity.closed and not operation.calls


def test_deferred_identity_query_error_closes_and_sanitizes(driver):
    connections, _ = driver
    connection, identity, operation = session(trailing_error=True)
    connections.append(connection)
    with pytest.raises(SqlPublicationError, match="procedure_failed"):
        SqlPublicationControl(
            TARGET, credential(), expected_client_id=UID
        ).read_control(UID)
    assert connection.closed and identity.closed and not operation.calls


def test_pinned_injected_connection_also_verifies_identity():
    connection, identity, operation = session(UID)
    with pytest.raises(SqlPublicationError, match="session_identity_mismatch"):
        SqlPublicationControl(
            TARGET,
            None,
            connect=lambda: connection,
            expected_client_id=READER,
        ).read_control(UID)
    assert connection.closed and identity.closed and not operation.calls


def test_success_closes_identity_cursor_then_preserves_procedure_results(driver):
    connections, _ = driver
    connection, identity, operation = session()
    connections.append(connection)
    result = SqlPublicationControl(
        TARGET,
        credential(),
        expected_client_id=UID,
        query_timeout_seconds=7,
    ).read_control(UID)
    assert result == {"revision": 0}
    assert connection.timeout == 7
    assert identity.closed and operation.closed and connection.closed
    assert identity.calls[0][0].startswith("SELECT DB_NAME()")
    assert operation.calls[0][0].startswith("EXEC publication.ReadControl")
