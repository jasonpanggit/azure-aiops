"""Optional broker seal/metadata SQL semantics, unexecuted without local engine."""

import json
from uuid import uuid4

import pytest

from ontology_discovery.immutable_attempt import AttemptSession
from ontology_discovery.sql_blob_broker import (
    SqlBrokerControl,
    SqlBrokerVerifier,
    bootstrap_broker_metadata,
)
from ontology_discovery.sql_publication_control import SqlPublicationError
from tests.test_sql_publication_control_integration import local_sql, publication

__all__ = ["local_sql", "publication"]
pyodbc = pytest.importorskip("pyodbc", reason="Existing fabric-sql extra is required")


def test_engine_owned_seal_exact_retry_and_takeover_refusal(publication):
    admin, control, _authority, _verifier, session, prepare, _grant, _args, _target = publication
    bootstrap_broker_metadata(admin)
    attempt, digest = prepare()
    target_id = session["target_id"]
    verifier = SqlBrokerVerifier(control._target, None, connect=control._connect)
    record = control.read_attempt(target_id, attempt, digest)
    original_session = AttemptSession(
        owner=session["owner_id"],
        epoch=session["epoch"],
        session_id=session["session_id"],
    )
    seal = {
        "catalog": json.loads(record["catalog_json"]), "catalog_digest": digest,
        "inventory": json.loads(record["inventory_json"]), "evidence": json.loads(record["evidence_json"]),
    }
    verifier.seal_owned_attempt(target_id, original_session, attempt, **seal)
    assert control.read_attempt(target_id, attempt, digest) == record
    winner = control.acquire(
        target_id,
        str(uuid4()),
        expected_revision=session["revision"],
        lease_seconds=300,
    )
    with pytest.raises(SqlPublicationError):
        verifier.seal_owned_attempt(target_id, original_session, attempt, **seal)
    assert control.read_attempt(target_id, attempt, digest) == record
    assert control.read_control(target_id) == winner


def test_engine_owned_seal_refuses_ambient_transaction_without_discarding_it(publication):
    admin, control, _authority, _verifier, session, prepare, _grant, _args, _target = publication
    bootstrap_broker_metadata(admin)
    attempt, digest = prepare()
    record = control.read_attempt(session["target_id"], attempt, digest)
    connection = control._connect()
    cursor = connection.cursor()
    try:
        cursor.execute("SET XACT_ABORT ON; BEGIN TRANSACTION; SELECT @@TRANCOUNT")
        assert cursor.fetchone()[0] == 1
        with pytest.raises(pyodbc.Error) as error:
            cursor.execute(
                "EXEC publication.SealOwnedAttempt @target_id=?,@owner_id=?,@session_id=?,"
                "@epoch=?,@attempt_id=?,@catalog_json=?,@catalog_digest=?,"
                "@inventory_json=?,@evidence_json=?",
                session["target_id"], session["owner_id"], session["session_id"], session["epoch"],
                attempt, record["catalog_json"], bytes.fromhex(digest),
                record["inventory_json"], record["evidence_json"],
            )
            while cursor.nextset():
                pass
        assert "publication_seal_ambient_transaction" in str(error.value)
        cursor.execute("SELECT @@TRANCOUNT, XACT_STATE()")
        assert tuple(cursor.fetchone()) == (1, 1)
    finally:
        connection.rollback()  # This test explicitly owns the transaction above.
        cursor.close()
        connection.close()
    assert control.read_attempt(session["target_id"], attempt, digest) == record


def test_engine_metadata_does_not_confuse_historical_outcome_and_readable_artifacts(publication):
    admin, control, _authority, _verifier, session, prepare, grant, args, _target = publication
    bootstrap_broker_metadata(admin)
    broker = SqlBrokerControl(control._target, None, connect=control._connect)
    attempt, digest = prepare()
    grant(session, digest)
    request = args(session, attempt, digest)
    accepted = broker.commit_attempt(**request)
    assert broker.reference_generation(request["target_id"], attempt, digest) == "generation"
    assert broker.readable_generation(request["target_id"], attempt, digest) == "generation"
    cursor = admin.cursor()
    try:
        cursor.execute(
            "UPDATE publication.Attempt SET RetainUntil=DATEADD(second,-1,SYSUTCDATETIME()) WHERE AttemptId=?",
            attempt,
        )
        admin.commit()
        assert broker.reference_generation(request["target_id"], attempt, digest) == "generation"
        with pytest.raises(SqlPublicationError):
            broker.readable_generation(request["target_id"], attempt, digest)
        assert broker.recover_outcome(**request) == accepted
    finally:
        cursor.close()
