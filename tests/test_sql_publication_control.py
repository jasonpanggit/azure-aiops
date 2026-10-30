"""Offline driver and source contracts, NOT executed T-SQL semantics."""

import hashlib
import json
import re
import tomllib
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ontology_discovery.sql_publication_control import (
    AzureSqlControlTarget,
    SqlPublicationAuthority,
    SqlPublicationControl,
    SqlPublicationError,
    SqlPublicationSetup,
    SqlPublicationVerifier,
    bootstrap_batches,
    bootstrap_database,
)

pyodbc = pytest.importorskip(
    "pyodbc", reason="Install the existing .[fabric-sql] extra for driver tests"
)
ROOT = Path(__file__).resolve().parents[1]
SQL = ROOT / "src/ontology_discovery/sql_control"
TARGET = AzureSqlControlTarget(
    "publication-test.database.windows.net",
    "publication_test",
    "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/test/"
    "providers/Microsoft.Sql/servers/publication-test/databases/publication_test",
)
UID = str(uuid4())
DIGEST = "a" * 64


class Cursor:
    def __init__(self, rows=(), names=(), *, fail=None, trailing_error=False):
        self.rows, self.description = rows, [(name,) for name in names] or None
        self.calls, self.closed = [], False
        self.fail, self.trailing_error = fail, trailing_error

    def execute(self, query, values=()):
        self.calls.append((query, values))
        if self.fail:
            raise self.fail
        return self

    def fetchall(self):
        return self.rows

    def nextset(self):
        if self.trailing_error:
            raise pyodbc.Error("late THROW with secret query diagnostics")
        return False

    def close(self):
        self.closed = True


class Connection:
    def __init__(self, cursor):
        self._cursor, self.closed = cursor, False
        self.committed = self.rolled_back = False
        self.autocommit = False

    def cursor(self):
        return self._cursor

    def close(self):
        self.closed = True

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def client(
    kind=SqlPublicationControl, *, rows=(), names=(), fail=None, trailing_error=False
):
    cursor = Cursor(rows, names, fail=fail, trailing_error=trailing_error)
    connection = Connection(cursor)
    return kind(TARGET, None, connect=lambda: connection), cursor, connection


def test_closed_calls_bind_parameters_and_do_not_interpolate_candidate():
    ctl, cursor, connection = client(rows=[(UID,)], names=["attempt_id"])
    poison = "'; DROP TABLE publication.Target;--"
    assert ctl.begin_attempt(UID, UID, UID, 1, {"value": poison}, request_id=UID) == UID
    sql, parameters = cursor.calls[0]
    assert sql.startswith("EXEC publication.BeginAttempt ")
    assert poison not in sql
    assert poison in parameters[4]
    assert sql.count("?") == len(parameters) == 6
    assert cursor.closed and connection.closed


@pytest.mark.parametrize("found", [False, True])
def test_read_only_outcome_lookup_is_not_commit_and_needs_exact_pins(found):
    value = {"found": True, "outcome": {"revision": 7}} if found else {"found": False}
    ctl, cursor, _ = client(rows=[(json.dumps(value),)], names=["result_json"])
    result = ctl.recover_outcome(
        UID,
        UID,
        UID,
        3,
        expected_revision=6,
        attempt_id=UID,
        catalog_digest=DIGEST,
        operation="admit",
        authority_digest=DIGEST,
        request_id=UID,
    )
    assert result == ({"revision": 7} if found else None)
    sql, params = cursor.calls[0]
    assert sql.startswith("EXEC publication.RecoverOutcome ")
    assert len(params) == sql.count("?") == 10
    assert params[-1] == UID and params[6] == bytes.fromhex(DIGEST)


@pytest.mark.parametrize(
    "value",
    [
        {"found": 0},
        {"found": False, "outcome": {}},
        {"found": 1, "outcome": {}},
        {"found": True, "outcome": None},
    ],
)
def test_ambiguous_lookup_shape_is_not_a_not_found_fallback(value):
    ctl, _, _ = client(rows=[(json.dumps(value),)], names=["result_json"])
    with pytest.raises(SqlPublicationError, match="outcome_result"):
        ctl.recover_outcome(
            UID,
            UID,
            UID,
            1,
            expected_revision=1,
            attempt_id=UID,
            catalog_digest=DIGEST,
            operation="admit",
            authority_digest=DIGEST,
            request_id=UID,
        )


@pytest.mark.parametrize("operation", ["admit", "restore"])
def test_commit_restoration_same_closed_transaction_and_exact_retry_identity(operation):
    ctl, cursor, _ = client(rows=[('{"revision":7}',)], names=["result_json"])
    assert ctl.commit_attempt(
        UID,
        UID,
        UID,
        3,
        expected_revision=6,
        attempt_id=UID,
        catalog_digest=DIGEST,
        operation=operation,
        authority_digest=DIGEST,
        request_id=UID,
    ) == {"revision": 7}
    sql, params = cursor.calls[0]
    assert sql.startswith("EXEC publication.CommitAttempt ")
    assert len(params) == sql.count("?") == 10
    assert params[6] == bytes.fromhex(DIGEST)
    assert params[7] == operation and params[-1] == UID


@pytest.mark.parametrize(
    "operation", ["restore; DROP", "restore ", "RESTORE", "sealed", None]
)
def test_invalid_operations_never_reach_sql(operation):
    ctl, cursor, _ = client()
    with pytest.raises(SqlPublicationError, match="operation"):
        ctl.commit_attempt(
            UID,
            UID,
            UID,
            1,
            expected_revision=1,
            attempt_id=UID,
            catalog_digest=DIGEST,
            operation=operation,
            authority_digest=DIGEST,
            request_id=UID,
        )
    assert not cursor.calls


@pytest.mark.parametrize(
    "server",
    [
        "item.datawarehouse.fabric.microsoft.com",
        "server.database.windows.net;TrustServerCertificate=yes",
        "https://server.database.windows.net",
        "server.database.windows.net.evil.test",
    ],
)
def test_non_control_endpoint_and_connection_string_injection_rejected(server):
    with pytest.raises(SqlPublicationError, match="control_database"):
        AzureSqlControlTarget(server, TARGET.database, TARGET.resource_id)


def test_database_resource_must_match_endpoint_and_database():
    with pytest.raises(SqlPublicationError, match="resource_identity"):
        AzureSqlControlTarget(TARGET.server, "wrong_database", TARGET.resource_id)
    with pytest.raises(TypeError):
        AzureSqlControlTarget(qualified=True, execution_enabled=True)


@pytest.mark.parametrize("digest", ["A" * 64, "a" * 63, "g" * 64, "", None])
def test_digest_invalid_never_executes(digest):
    ctl, cursor, _ = client()
    with pytest.raises(SqlPublicationError, match="digest"):
        ctl.read_attempt(UID, UID, digest)
    assert not cursor.calls


def test_uuid_and_acquire_pins_are_validated():
    ctl, cursor, _ = client()
    with pytest.raises(SqlPublicationError, match="uuid"):
        ctl.read_control("';drop database master")
    for rev, lease in [(-1, 5), (True, 5), (1, 301), (1, None)]:
        with pytest.raises(SqlPublicationError, match="acquire"):
            ctl.acquire(UID, UID, expected_revision=rev, lease_seconds=lease)
    assert not cursor.calls


def test_read_and_acquire_result_mapping():
    for method in ("read", "acquire"):
        ctl, cursor, _ = client(rows=[('{"epoch":4}',)], names=["result_json"])
        if method == "read":
            result = ctl.read_control(UID)
        else:
            result = ctl.acquire(UID, UID, expected_revision=2, lease_seconds=30)
        assert result == {"epoch": 4}
        assert len(cursor.calls) == 1


@pytest.mark.parametrize(
    "rows,names",
    [
        ([], ["result_json"]),
        ([("[]",)], ["result_json"]),
        ([("no-json",)], ["result_json"]),
        ([("{}",)], ["wrong"]),
        ([("{}",), ("{}",)], ["result_json"]),
    ],
)
def test_result_shapes_fail_closed(rows, names):
    ctl, _, _ = client(rows=rows, names=names)
    with pytest.raises(SqlPublicationError, match="result"):
        ctl.read_control(UID)


@pytest.mark.parametrize("trailing", [False, True])
def test_database_errors_sanitized_and_late_throw_cannot_return_success(trailing):
    ctl, cursor, connection = client(
        rows=[('{"revision":3}',)],
        names=["result_json"],
        fail=None if trailing else pyodbc.Error("password/token/parameters secret"),
        trailing_error=trailing,
    )
    with pytest.raises(SqlPublicationError, match="procedure_failed") as exc:
        ctl.read_control(UID)
    assert "secret" not in str(exc.value)
    assert cursor.closed and connection.closed


def test_proc_clients_keep_authority_and_verifier_separate_from_broker():
    assert not hasattr(SqlPublicationControl, "record_grant")
    assert not hasattr(SqlPublicationControl, "revoke")
    assert not hasattr(SqlPublicationControl, "seal_attempt")
    assert not hasattr(SqlPublicationControl, "provision_target")
    verifier, cursor, _ = client(SqlPublicationVerifier)
    verifier.seal_attempt(
        UID,
        UID,
        catalog={"protocol": "immutable-attempt/v1"},
        catalog_digest=DIGEST,
        inventory=[],
        evidence={"provider": "readback"},
    )
    assert cursor.calls[0][0].startswith("EXEC publication.SealAttempt ")
    authority, cursor, _ = client(SqlPublicationAuthority)
    authority.record_grant(
        UID,
        UID,
        1,
        catalog_digest=DIGEST,
        operation="restore",
        authority_digest=DIGEST,
        evidence_digest=DIGEST,
        valid_from=datetime(2026, 1, 1, tzinfo=UTC),
        valid_until=datetime(2026, 2, 1, tzinfo=UTC),
    )
    authority.revoke(UID, UID, 1, catalog_digest=DIGEST, operation="restore")
    assert [query.split()[1] for query, _ in cursor.calls] == [
        "publication.RecordGrant",
        "publication.[Revoke]",
    ]


def test_admin_provision_is_closed_and_create_only():
    setup, cursor, _ = client(SqlPublicationSetup)
    setup.provision_target(
        UID,
        {"tenant_id": "expected"},
        account_resource_id="/approved/account",
        blob_endpoint="https://approved.blob.core.windows.net",
        container="snapshot",
        retain_until=datetime(2030, 1, 1, tzinfo=UTC),
    )
    assert cursor.calls[0][0].startswith("EXEC publication.ProvisionTarget ")


def test_authority_times_are_utc_before_odbc_discards_timezone():
    authority, cursor, _ = client(SqlPublicationAuthority)
    start = datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=8)))
    authority.record_grant(
        UID,
        UID,
        1,
        catalog_digest=DIGEST,
        operation="admit",
        authority_digest=DIGEST,
        evidence_digest=DIGEST,
        valid_from=start,
        valid_until=start + timedelta(hours=1),
    )
    params = cursor.calls[0][1]
    assert params[-2].isoformat() == "2025-12-31T16:00:00"
    assert params[-1].isoformat() == "2025-12-31T17:00:00"
    with pytest.raises(SqlPublicationError, match="utc_datetime_required"):
        authority.record_grant(
            UID,
            UID,
            1,
            catalog_digest=DIGEST,
            operation="admit",
            authority_digest=DIGEST,
            evidence_digest=DIGEST,
            valid_from=start.replace(tzinfo=None),
            valid_until=start,
        )
    assert len(cursor.calls) == 1


def test_real_odbc_boundary_uses_entra_token_encrypt_and_autocommit(monkeypatch):
    cursor = Cursor([('{"revision":0}',)], ["result_json"])
    connection = Connection(cursor)
    identity_cursor = Cursor([(TARGET.database, UID)], ["database", "client"])
    cursors = iter((identity_cursor, cursor))
    connection.cursor = lambda: next(cursors)
    calls = []

    def connect(text, **kwargs):
        calls.append((text, kwargs))
        return connection

    monkeypatch.setattr(pyodbc, "drivers", lambda: ["ODBC Driver 18 for SQL Server"])
    monkeypatch.setattr(pyodbc, "connect", connect)
    monkeypatch.setattr(pyodbc, "pooling", False)
    scopes = []

    def token(scope):
        scopes.append(scope)
        return SimpleNamespace(token="not-a-real-token")

    ctl = SqlPublicationControl(
        TARGET, SimpleNamespace(get_token=token), expected_client_id=UID
    )
    assert ctl.read_control(UID) == {"revision": 0}
    text, kwargs = calls[0]
    assert scopes == ["https://database.windows.net/.default"]
    assert "Encrypt=Yes;TrustServerCertificate=No" in text
    assert "not-a-real-token" not in text and "PWD" not in text
    raw = kwargs["attrs_before"][1256]
    assert int.from_bytes(raw[:4], "little") == len(raw[4:])
    assert raw[4:].decode("utf-16-le") == "not-a-real-token"
    assert kwargs["autocommit"] is True


def test_missing_odbc_driver_does_not_connect(monkeypatch):
    monkeypatch.setattr(pyodbc, "drivers", list)
    monkeypatch.setattr(pyodbc, "pooling", False)
    ctl = SqlPublicationControl(TARGET, None, expected_client_id=UID)
    with pytest.raises(SqlPublicationError, match="odbc_driver_18_missing"):
        ctl.read_control(UID)


def procedure(name):
    identifier = f"[{name}]" if name == "Revoke" else name
    return next(
        batch
        for batch in bootstrap_batches()
        if batch.startswith(f"CREATE OR ALTER PROCEDURE publication.{identifier}")
    )


def test_static_sql_guards_and_atomic_records_not_runtime_semantics():
    commit = procedure("CommitAttempt")
    for text in [
        "WITH (UPDLOCK, HOLDLOCK)",
        "t.Epoch = @epoch",
        "t.Revision = @expected_revision",
        "t.OwnerId = @owner_id",
        "t.SessionId = @session_id",
        "t.SessionDeadline > SYSUTCDATETIME()",
        "g.Revoked = 0",
        "g.ValidUntil > SYSUTCDATETIME()",
        "a.SealedAt IS NOT NULL",
        "a.RetainUntil >= t.RequiredRetainUntil",
        "a.RetainUntil > SYSUTCDATETIME()",
        "g.Operation = @operation",
        "@operation = 'restore'",
        "INSERT publication.Receipt",
        "INSERT publication.Operation",
        "INSERT publication.Audit",
    ]:
        assert text in commit
    replay = commit.index("IF @prior IS NOT NULL")
    transition = commit.index("UPDATE t SET")
    assert (
        replay
        < transition
        < commit.index("INSERT publication.Receipt")
        < commit.rindex("COMMIT;")
    )
    assert "publication_request_conflict" in commit
    assert commit.index("IF @recover_only = 1\n        BEGIN") < transition
    assert "@recover_only=1" in procedure("RecoverOutcome")
    for name in ("Acquire", "BeginAttempt", "SealAttempt", "RecordGrant", "Revoke"):
        assert "WITH (UPDLOCK, HOLDLOCK)" in procedure(name)
    assert "publication.Revocation" in procedure("Revoke")
    assert "publication_grant_revoked" in procedure("RecordGrant")


def test_static_seal_requires_complete_persisted_identity_horizon_and_locked_policy():
    seal = procedure("SealAttempt")
    for text in [
        "N'Locked'",
        "@until < @required",
        "@until <= SYSUTCDATETIME()",
        "'versioning_enabled','append_writes','append_blocks'",
        "[type] = 3",
        "publication_seal_immutable",
        "InventoryDigest = HASHBYTES",
        "EvidenceJson = @evidence_json",
        "publication_inventory_membership",
        "publication_inventory_identity",
        "FULL JOIN",
        "'$.version_id'",
        "[key] = 'version_id' AND [type] <> 0",
        "Latin1_General_100_BIN2_UTF8",
        "DATALENGTH(CatalogJson)",
        "publication_provider_readback_missing",
        "EvidenceDigest = HASHBYTES",
        "VerifierPrincipal = USER_NAME()",
        "TRY_CONVERT(datetimeoffset(7)",
        "SWITCHOFFSET(",
    ]:
        assert text in seal
    assert "ISNULL(JSON_QUERY(@candidate_json" in procedure("BeginAttempt")
    assert "publication_candidate_target" in procedure("BeginAttempt")


def test_static_permissions_exist_after_objects_and_no_runtime_dml_or_memberships():
    batches = bootstrap_batches()
    definitions = {}
    for i, batch in enumerate(batches):
        for name in re.findall(r"CREATE OR ALTER PROCEDURE publication\.(\w+)", batch):
            definitions[name] = i
        for name in re.findall(r"GRANT EXECUTE ON OBJECT::publication\.(\w+)", batch):
            assert name in definitions and definitions[name] < i
    permissions = (SQL / "permissions.sql").read_text()
    for role in ["broker", "verifier", "authority", "reader"]:
        assert (
            f"DENY SELECT, INSERT, UPDATE, DELETE ON SCHEMA::publication TO publication_{role}"
            in permissions
        )
    assert "publication.RecordGrant TO publication_authority" in permissions
    assert "publication.SealAttempt TO publication_verifier" in permissions
    assert "publication.RecoverOutcome TO publication_broker" in permissions
    assert "publication.RecordGrant TO publication_broker" not in permissions
    assert not re.search(r"GRANT\s+(INSERT|UPDATE|DELETE|ALTER|CONTROL)", permissions)
    assert "ADD MEMBER" not in permissions and "CREATE USER" not in permissions


def test_admin_bootstrap_is_explicit_ordered_and_rolls_back_errors():
    cursor = Cursor()
    connection = Connection(cursor)
    bootstrap_database(connection)
    assert [sql for sql, _ in cursor.calls] == list(bootstrap_batches())
    assert connection.committed and cursor.closed and not connection.rolled_back
    cursor = Cursor(fail=pyodbc.Error("administrator failure"))
    connection = Connection(cursor)
    with pytest.raises(pyodbc.Error, match="administrator failure"):
        bootstrap_database(connection)
    assert connection.rolled_back and cursor.closed
    assert not connection.committed
    connection = Connection(Cursor())
    connection.autocommit = True
    with pytest.raises(SqlPublicationError, match="explicit_transaction"):
        bootstrap_database(connection)
    assert not connection._cursor.calls


def test_migration_resources_forced_into_installed_wheel():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    includes = config["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    for name in ("schema.sql", "permissions.sql"):
        assert (
            includes[f"src/ontology_discovery/sql_control/{name}"]
            == f"ontology_discovery/sql_control/{name}"
        )


def test_catalog_digest_matches_core_canonical_serialization():
    value = {"candidate": {"generation_id": "unicode-\u00e9"}, "products": {}}
    ctl, cursor, _ = client(SqlPublicationVerifier)
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    digest = hashlib.sha256(text.encode()).hexdigest()
    ctl.seal_attempt(
        UID, UID, catalog=value, catalog_digest=digest, inventory=[], evidence={}
    )
    params = cursor.calls[0][1]
    assert (
        params[2] == text and params[3] == hashlib.sha256(params[2].encode()).digest()
    )
