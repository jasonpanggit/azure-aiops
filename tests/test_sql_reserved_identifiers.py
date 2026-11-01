"""Regression for SQL Server's reserved REVOKE procedure identifier."""

from pathlib import Path

from ontology_discovery.sql_publication_control import SqlPublicationAuthority
from tests.test_sql_publication_control import DIGEST, UID, client

ROOT = Path(__file__).resolve().parents[1]


def test_reserved_revocation_name_is_delimited_in_schema_and_permission():
    sql = ROOT / "src/ontology_discovery/sql_control"
    assert "CREATE OR ALTER PROCEDURE publication.[Revoke]\n" in (sql / "schema.sql").read_text()
    assert (
        "GRANT EXECUTE ON OBJECT::publication.[Revoke] TO publication_authority;"
        in (sql / "permissions.sql").read_text()
    )


def test_authority_revocation_exec_delimits_name_and_preserves_exact_parameters():
    authority, cursor, _ = client(SqlPublicationAuthority)
    authority.revoke(UID, UID, 7, catalog_digest=DIGEST, operation="restore")
    statement, parameters = cursor.calls[0]
    assert statement == (
        "EXEC publication.[Revoke] "
        "@target_id=?,@session_id=?,@epoch=?,@catalog_digest=?,@operation=?"
    )
    assert parameters == (UID, UID, 7, bytes.fromhex(DIGEST), "restore")
