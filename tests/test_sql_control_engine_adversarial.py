"""Opt-in local engine coverage; importing this file starts no infrastructure."""

import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import pytest

from ontology_discovery.sql_publication_control import SqlPublicationError
from tests.test_sql_publication_control_integration import (
    local_sql,
    publication,
)

__all__ = ["local_sql", "publication"]
pyodbc = pytest.importorskip("pyodbc")


@pytest.mark.parametrize(
    "role,allowed,forbidden",
    [
        (
            "publication_broker",
            ("ReadControl", "Acquire", "BeginAttempt", "CommitAttempt", "RecoverOutcome", "ReadAttempt"),
            ("ProvisionTarget", "SealAttempt", "RecordGrant", "Revoke"),
        ),
        (
            "publication_verifier",
            ("SealAttempt",),
            ("ReadControl", "Acquire", "BeginAttempt", "CommitAttempt", "RecordGrant", "Revoke"),
        ),
        (
            "publication_authority",
            ("RecordGrant", "Revoke"),
            ("ReadControl", "Acquire", "BeginAttempt", "SealAttempt", "CommitAttempt", "RecoverOutcome"),
        ),
        (
            "publication_reader",
            ("ReadControl", "ReadAttempt"),
            ("Acquire", "BeginAttempt", "SealAttempt", "CommitAttempt", "RecordGrant", "Revoke"),
        ),
    ],
)
def test_engine_effective_role_permissions(local_sql, role, allowed, forbidden):
    """Verify effective permissions, not just permission-script substrings."""
    admin, connect = local_sql
    user = "review_" + uuid4().hex
    cursor = admin.cursor()
    created = False
    try:
        cursor.execute(f"CREATE USER [{user}] WITHOUT LOGIN")
        cursor.execute(f"ALTER ROLE [{role}] ADD MEMBER [{user}]")
        admin.commit()
        created = True
        connection = connect()
        impersonated = False
        probe = connection.cursor()
        try:
            probe.execute(f"EXECUTE AS USER = '{user}'")
            impersonated = True
            for name in allowed:
                assert probe.execute(
                    "SELECT HAS_PERMS_BY_NAME(?, 'OBJECT', 'EXECUTE')",
                    "publication." + name,
                ).fetchone()[0] == 1
            for name in forbidden:
                assert probe.execute(
                    "SELECT HAS_PERMS_BY_NAME(?, 'OBJECT', 'EXECUTE')",
                    "publication." + name,
                ).fetchone()[0] == 0
            for action in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                assert probe.execute(
                    "SELECT HAS_PERMS_BY_NAME('publication.Target', 'OBJECT', ?)",
                    action,
                ).fetchone()[0] == 0
            with pytest.raises(pyodbc.Error):
                probe.execute("SELECT TOP (1) * FROM publication.Target").fetchall()
            with pytest.raises(pyodbc.Error):
                probe.execute("UPDATE publication.Target SET Revision=Revision WHERE 1=0")
        finally:
            try:
                if impersonated:
                    probe.execute("REVERT")
            finally:
                probe.close()
                connection.close()
    finally:
        try:
            if created:
                cursor.execute(f"DROP USER [{user}]")
                admin.commit()
            else:
                admin.rollback()
        finally:
            cursor.close()


def test_engine_concurrent_identical_commit_has_one_transaction_outcome(publication):
    admin, control, _authority, _verifier, session, prepare, grant, args, _target = publication
    attempt, digest = prepare()
    grant(session, digest)
    request = args(session, attempt, digest)
    barrier = threading.Barrier(2)

    def invoke():
        barrier.wait(timeout=10)
        return control.commit_attempt(**request)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(invoke) for _ in range(2)]
        outcomes = [future.result(timeout=30) for future in futures]
    assert outcomes[0] == outcomes[1]
    assert control.recover_outcome(**request) == outcomes[0]
    cursor = admin.cursor()
    try:
        for table in ("Receipt", "Operation"):
            assert cursor.execute(
                f"SELECT COUNT(*) FROM publication.{table} WHERE TargetId=?",
                request["target_id"],
            ).fetchone()[0] == 1
    finally:
        cursor.close()
        admin.commit()


def test_engine_concurrent_distinct_commits_have_one_revision_winner(publication):
    admin, control, _authority, _verifier, session, prepare, grant, args, _target = publication
    attempts = [prepare(), prepare()]
    for _attempt, digest in attempts:
        grant(session, digest)
    requests = [args(session, attempt, digest) for attempt, digest in attempts]
    barrier = threading.Barrier(2)

    def invoke(request):
        barrier.wait(timeout=10)
        try:
            return control.commit_attempt(**request)
        except SqlPublicationError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(invoke, request) for request in requests]
        outcomes = [future.result(timeout=30) for future in futures]
    winners = [outcome for outcome in outcomes if outcome is not None]
    assert len(winners) == 1
    current = control.read_control(requests[0]["target_id"])
    assert current["active_attempt"] == winners[0]["active_attempt"]
    assert current["revision"] == session["revision"] + 1
    cursor = admin.cursor()
    try:
        for table in ("Receipt", "Operation"):
            assert cursor.execute(
                f"SELECT COUNT(*) FROM publication.{table} WHERE TargetId=?",
                requests[0]["target_id"],
            ).fetchone()[0] == 1
    finally:
        cursor.close()
        admin.commit()


def test_engine_receipt_failure_rolls_back_pointer_and_retry_is_fresh(publication):
    """A failure after the guarded UPDATE must not expose a partial transition."""
    admin, control, _authority, _verifier, session, prepare, grant, args, _target = publication
    attempt, digest = prepare()
    grant(session, digest)
    request = args(session, attempt, digest)
    before = control.read_control(request["target_id"])
    trigger = "review_fail_" + uuid4().hex
    target_id = str(UUID(request["target_id"]))
    cursor = admin.cursor()
    installed = False
    try:
        cursor.execute(
            f"CREATE TRIGGER publication.[{trigger}] ON publication.Receipt "
            "AFTER INSERT AS BEGIN SET NOCOUNT ON; "
            f"IF EXISTS (SELECT 1 FROM inserted WHERE TargetId=CONVERT(uniqueidentifier,'{target_id}')) "
            "THROW 51999, 'review_receipt_failure', 1; END"
        )
        admin.commit()
        installed = True
        with pytest.raises(SqlPublicationError):
            control.commit_attempt(**request)
        assert control.read_control(request["target_id"]) == before
        assert control.recover_outcome(**request) is None
        for table in ("Receipt", "Operation"):
            assert cursor.execute(
                f"SELECT COUNT(*) FROM publication.{table} WHERE TargetId=?",
                request["target_id"],
            ).fetchone()[0] == 0
        assert cursor.execute(
            "SELECT COUNT(*) FROM publication.Audit WHERE TargetId=? AND Kind='admit'",
            request["target_id"],
        ).fetchone()[0] == 0
        admin.commit()
    finally:
        try:
            if installed:
                cursor.execute(f"DROP TRIGGER publication.[{trigger}]")
                admin.commit()
            else:
                admin.rollback()
        finally:
            cursor.close()
    accepted = control.commit_attempt(**request)
    assert accepted["revision"] == before["revision"] + 1
    assert control.recover_outcome(**request) == accepted
