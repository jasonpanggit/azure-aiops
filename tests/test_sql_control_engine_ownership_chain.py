"""Separate amendment to the frozen seven-case local SQL engine harness."""

import json
from uuid import UUID, uuid4

import pytest

from tests.test_sql_publication_control_integration import local_sql, publication

__all__ = ["local_sql", "publication"]
pyodbc = pytest.importorskip("pyodbc")


@pytest.mark.parametrize("role", ["publication_reader", "publication_broker"])
def test_engine_procedure_ownership_chain_with_direct_table_denied(publication, role):
    """Procedure EXECUTE must work under the same role denied direct table reads."""
    admin, control, _authority, _verifier, session, _prepare, _grant, _args, _target = publication
    target_id = session["target_id"]
    expected = control.read_control(target_id)
    user = "review_chain_" + uuid4().hex
    cursor = admin.cursor()
    created = False
    try:
        cursor.execute(f"CREATE USER [{user}] WITHOUT LOGIN")
        cursor.execute(f"ALTER ROLE [{role}] ADD MEMBER [{user}]")
        admin.commit()
        created = True
        cursor.execute(f"EXECUTE AS USER = '{user}'")
        try:
            row = cursor.execute(
                "EXEC publication.ReadControl @target_id=?", target_id,
            ).fetchone()
            actual = json.loads(row[0])
            for name in ("target_id", "owner_id", "session_id", "active_attempt"):
                if actual[name] is not None:
                    actual[name] = str(UUID(actual[name]))
            assert actual == expected
            while cursor.nextset():
                pass
            with pytest.raises(pyodbc.Error):
                cursor.execute(
                    "SELECT Revision FROM publication.Target WHERE TargetId=?", target_id,
                ).fetchall()
        finally:
            cursor.execute("REVERT")
            admin.rollback()
    finally:
        try:
            if created:
                cursor.execute(f"DROP USER [{user}]")
                admin.commit()
            else:
                admin.rollback()
        finally:
            cursor.close()
