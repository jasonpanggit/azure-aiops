"""Opt-in disposable LOCAL SQL Server tests, not Azure/Blob qualification.

Pre-create publication_protocol_test on an explicitly managed local SQL engine.
Set FABRIC_PUBLICATION_SQL_LOCAL_PORT and FABRIC_PUBLICATION_SQL_LOCAL_PASSWORD
to run. No server, daemon, container, image, cloud DB or credentials are created.
Unset port => precise skip; fake/static tests do not stand in for these tests.
Set FABRIC_PUBLICATION_SQL_REQUIRED=1 in qualification CI to fail, not skip,
when its explicitly provisioned disposable engine is unavailable.
"""

import hashlib
import json
import os
import re
from datetime import UTC, timedelta
from uuid import uuid4

import pytest

from ontology_discovery.sql_publication_control import (
    AzureSqlControlTarget,
    SqlPublicationAuthority,
    SqlPublicationControl,
    SqlPublicationError,
    SqlPublicationSetup,
    SqlPublicationVerifier,
    bootstrap_database,
)

pyodbc = pytest.importorskip("pyodbc", reason="Existing .[fabric-sql] extra is required for SQL engine tests")
DRIVER = "ODBC Driver 18 for SQL Server"


@pytest.fixture
def local_sql():
    required = os.environ.get("FABRIC_PUBLICATION_SQL_REQUIRED") == "1"
    port = os.environ.get("FABRIC_PUBLICATION_SQL_LOCAL_PORT")
    if port is None:
        if required:
            pytest.fail("Required local SQL engine is not configured (LOCAL_PORT unset)")
        pytest.skip(
            "SQL engine semantics UNEXECUTED: no local engine configured "
            "(FABRIC_PUBLICATION_SQL_LOCAL_PORT unset). ODBC is a client only; "
            "no daemon, image, container or database is started by this test."
        )
    if not port.isdecimal() or not 1 <= int(port) <= 65535:
        pytest.fail("Invalid explicitly configured LOCAL SQL port")
    password = os.environ.get("FABRIC_PUBLICATION_SQL_LOCAL_PASSWORD")
    if not password:
        pytest.fail("Opt-in local SQL requires FABRIC_PUBLICATION_SQL_LOCAL_PASSWORD")
    if DRIVER not in pyodbc.drivers():
        if required:
            pytest.fail("Required local SQL engine unavailable: ODBC Driver 18 missing")
        pytest.skip("SQL engine integration unavailable: ODBC Driver 18 for SQL Server missing")
    text = (
        f"Driver={{{DRIVER}}};Server=127.0.0.1,{int(port)};"
        "Database=publication_protocol_test;UID=sa;"
        f"PWD={{{password.replace('}', '}}')}}};Encrypt=Yes;TrustServerCertificate=Yes;"
    )

    def connect(*, admin=False):
        return pyodbc.connect(text, autocommit=not admin, timeout=3)

    try:
        admin = connect(admin=True)
    except pyodbc.OperationalError as exc:
        state = str(exc.args[0]) if exc.args else ""
        state = state if re.fullmatch(r"[A-Z0-9]{5}", state) else "unknown"
        if state in {"08001", "HYT00", "HYT01"}:
            if required:
                pytest.fail(f"Required local SQL engine unreachable (SQLSTATE {state})")
            pytest.skip(f"Explicit local SQL engine unreachable (SQLSTATE {state}); nothing started")
        pytest.fail(f"Explicit local SQL integration configuration refused (SQLSTATE {state})")
    try:
        bootstrap_database(admin)
        yield admin, connect
    finally:
        admin.close()


@pytest.fixture
def publication(local_sql):
    admin, connect = local_sql
    # Resource binding is synthetic in this LOCAL test, never provider evidence.
    target = AzureSqlControlTarget(
        "publication-test.database.windows.net", "publication_test",
        "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/test/"
        "providers/Microsoft.Sql/servers/publication-test/databases/publication_test",
    )
    target_id, owner = str(uuid4()), str(uuid4())
    expected = dict.fromkeys(
        ("tenant_id", "subscription_id", "connection_id", "workspace_id", "item_id", "definition_fingerprint"),
        "synthetic-local-test",
    )
    cursor = admin.cursor()
    try:
        now = cursor.execute("SELECT SYSUTCDATETIME()").fetchone()[0].replace(tzinfo=UTC)
    finally:
        cursor.close()
    admin.commit()
    setup = SqlPublicationSetup(target, None, connect=connect)
    setup.provision_target(
        target_id, expected, account_resource_id="/synthetic/account",
        blob_endpoint="https://synthetic.blob.core.windows.net", container="snapshots",
        retain_until=now + timedelta(days=3),
    )
    ctl = SqlPublicationControl(target, None, connect=connect)
    verifier = SqlPublicationVerifier(target, None, connect=connect)
    authority = SqlPublicationAuthority(target, None, connect=connect)
    session = ctl.acquire(target_id, owner, expected_revision=0, lease_seconds=300)

    def prepare(current=session, *, evidence_change=None, catalog_change=None):
        request = str(uuid4())
        candidate = {
            "generation_id": "generation", "source_generation": "source", "content_hash": "content",
            "staged_manifest_digest": "staged", "validation_digest": "validation",
            "authorization_digest": "auth", "attestation_digest": "attestation",
            "expected_target": expected,
        }
        attempt = ctl.begin_attempt(
            target_id, current["owner_id"], current["session_id"], current["epoch"],
            candidate, request_id=request,
        )
        body = b'{"rows":[]}'
        obj = {
            "account_resource_id": "/synthetic/account", "endpoint": "https://synthetic.blob.core.windows.net",
            "container": "snapshots", "object_name": f"attempts/{attempt}/ontology_entities.json",
            "length": len(body), "content_digest": hashlib.sha256(body).hexdigest(),
            "etag": '"synthetic-etag"', "version_id": None,
        }
        catalog = {
            "protocol": "immutable-attempt/v1", "attempt_id": attempt, "candidate": candidate,
            "products": {"ontology_entities": {
                "rows": 0, "arrow_schema_digest": "a" * 64,
                "content_digest": obj["content_digest"], "artifact": dict(obj),
            }},
        }
        if catalog_change:
            catalog_change(catalog)
        raw = json.dumps(catalog, sort_keys=True, separators=(",", ":"), allow_nan=False)
        digest = hashlib.sha256(raw.encode()).hexdigest()
        evidence = {
            "account_resource_id": obj["account_resource_id"], "endpoint": obj["endpoint"],
            "container": obj["container"], "policy_state": "Locked",
            "versioning_enabled": False, "append_writes": False, "append_blocks": False,
            "effective_until": (now + timedelta(days=5)).isoformat(),
            "provider_readback": {
                "local_test_only": True, "not_live_worm_evidence": True,
                "account": {"kind": "StorageV2", "versioning_enabled": False},
                "policy": {"state": "Locked", "append_writes": False, "append_blocks": False},
                "objects": [{**obj, "created_at": now.isoformat(),
                             "effective_until": (now + timedelta(days=5)).isoformat()}],
            },
        }
        if evidence_change:
            evidence_change(evidence)
        verifier.seal_attempt(
            target_id, attempt, catalog=catalog, catalog_digest=digest,
            inventory=[{**obj, "logical_name": "ontology_entities"}], evidence=evidence,
        )
        return attempt, digest

    def grant(current, digest, *, operation="admit", expired=False):
        authority.record_grant(
            target_id, current["session_id"], current["epoch"], catalog_digest=digest,
            operation=operation, authority_digest="a" * 64, evidence_digest="b" * 64,
            valid_from=now - timedelta(minutes=5),
            valid_until=now - timedelta(minutes=1) if expired else now + timedelta(minutes=5),
        )

    def args(current, attempt, digest, operation="admit", request_id=None):
        return {
            "target_id": target_id, "owner_id": current["owner_id"], "session_id": current["session_id"],
            "epoch": current["epoch"], "expected_revision": current["revision"],
            "attempt_id": attempt, "catalog_digest": digest, "operation": operation,
            "authority_digest": "a" * 64, "request_id": request_id or str(uuid4()),
        }

    return admin, ctl, authority, verifier, session, prepare, grant, args, expected


def test_engine_atomic_commit_takeover_exact_retry_and_independent_restore(publication):
    admin, ctl, _authority, _verifier, a, prepare, grant, args, _expected = publication
    attempt, digest = prepare()
    grant(a, digest)
    request = args(a, attempt, digest)
    assert ctl.recover_outcome(**request) is None
    assert ctl.read_control(request["target_id"])["active_attempt"] is None
    result_a = ctl.commit_attempt(**request)
    assert ctl.commit_attempt(**request) == ctl.recover_outcome(**request) == result_a
    b = ctl.acquire(request["target_id"], str(uuid4()), expected_revision=result_a["revision"], lease_seconds=300)
    new_attempt, new_digest = prepare(b)
    grant(b, new_digest)
    result_b = ctl.commit_attempt(**args(b, new_attempt, new_digest))
    assert ctl.recover_outcome(**request) == result_a
    assert ctl.read_control(request["target_id"]) == {**b, "revision": result_b["revision"],
                                                    "active_attempt": new_attempt, "active_digest": new_digest}
    with pytest.raises(SqlPublicationError):
        ctl.commit_attempt(**{**request, "request_id": str(uuid4()), "expected_revision": result_b["revision"]})
    for changed in [{"catalog_digest": "f" * 64}, {"operation": "restore"}, {"expected_revision": 999}]:
        with pytest.raises(SqlPublicationError):
            ctl.recover_outcome(**{**request, **changed})
    b["revision"] = result_b["revision"]
    # Restore needs its own grant and can refer to retained A-owned artifacts.
    with pytest.raises(SqlPublicationError):
        ctl.commit_attempt(**args(b, attempt, digest, "restore"))
    grant(b, digest, operation="restore")
    restored = ctl.commit_attempt(**args(b, attempt, digest, "restore"))
    assert restored["active_attempt"] == attempt
    cursor = admin.cursor()
    try:
        assert cursor.execute(
            "SELECT COUNT(*) FROM publication.Receipt WHERE TargetId=?", request["target_id"],
        ).fetchone()[0] == 3
        assert cursor.execute(
            "SELECT COUNT(*) FROM publication.Operation WHERE TargetId=?", request["target_id"],
        ).fetchone()[0] == 3
    finally:
        cursor.close()
        admin.commit()


def test_engine_revocation_tombstone_and_authority_expiry(publication):
    _admin, ctl, authority, _verifier, a, prepare, grant, args, _expected = publication
    attempt, digest = prepare()
    request = args(a, attempt, digest)
    authority.revoke(
        request["target_id"], a["session_id"], a["epoch"], catalog_digest=digest, operation="admit",
    )
    with pytest.raises(SqlPublicationError):
        grant(a, digest)
    with pytest.raises(SqlPublicationError):
        ctl.commit_attempt(**request)
    other, other_digest = prepare()
    grant(a, other_digest, expired=True)
    with pytest.raises(SqlPublicationError):
        ctl.commit_attempt(**args(a, other, other_digest))
    assert ctl.read_control(request["target_id"])["active_attempt"] is None


@pytest.mark.parametrize("change", [
    {"policy_state": "Unlocked"}, {"versioning_enabled": True},
    {"append_writes": True}, {"append_blocks": True}, {"versioning_enabled": "false"},
    {"effective_until": "2000-01-01T00:00:00Z"},
])
def test_engine_invalid_storage_evidence_rejects_before_activation(publication, change):
    _admin, _ctl, _authority, _verifier, _a, prepare, _grant, _args, _expected = publication
    with pytest.raises(SqlPublicationError):
        prepare(evidence_change=lambda evidence: evidence.update(change))


def test_engine_catalog_destination_substitution_and_seal_conflict(publication):
    _admin, _ctl, _authority, _verifier, _a, prepare, _grant, _args, _expected = publication
    with pytest.raises(SqlPublicationError):
        prepare(catalog_change=lambda catalog: catalog["products"]["ontology_entities"]["artifact"].update(
            container="production",
        ))
    prepare()


def test_engine_procedure_only_role_has_no_raw_dml_or_grant_route(local_sql):
    admin, _connect = local_sql
    cursor = admin.cursor()
    try:
        cursor.execute(
            "IF USER_ID('publication_test_broker') IS NULL CREATE USER publication_test_broker WITHOUT LOGIN;"
            "ALTER ROLE publication_broker ADD MEMBER publication_test_broker;"
        )
        admin.commit()
        for forbidden in (
            "SELECT * FROM publication.Target",
            "UPDATE publication.Target SET Epoch=Epoch+1",
            (
                "EXEC publication.RecordGrant @target_id=NULL,@session_id=NULL,@epoch=1,"
                "@catalog_digest=NULL,@operation='admit',@authority_digest=NULL,@evidence_digest=NULL,"
                "@valid_from=NULL,@valid_until=NULL"
            ),
        ):
            cursor.execute("EXECUTE AS USER = 'publication_test_broker'")
            try:
                with pytest.raises(pyodbc.Error):
                    cursor.execute(forbidden)
            finally:
                cursor.execute("REVERT")
                admin.rollback()
    finally:
        cursor.close()
