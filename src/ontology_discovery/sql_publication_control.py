"""Parameterized OLTP publication control procedures; no raw CAS/DML client.

Not a qualified AttemptBoundary or broker transport. Infrastructure flags cannot
enable this module. Authority and verifier clients require separately provisioned
database principals; do not hand them to workers or the broker request surface.
"""

from __future__ import annotations

import json
import re
import struct
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.resources import files
from typing import Any
from uuid import UUID

from azure.core.exceptions import AzureError

from fabric.sql_endpoint import REQUIRED_ODBC_DRIVER, SQL_SCOPE


class SqlPublicationError(RuntimeError):
    """Sanitized database refusal or unavailable provider configuration."""


def _uuid(value: str) -> str:
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise SqlPublicationError("sql_publication:uuid") from None


def _control_uuids(result: dict[str, Any]) -> dict[str, Any]:
    # SQL FOR JSON uppercases uniqueidentifiers; broker identity pins are canonical.
    for name in ("target_id", "owner_id", "session_id", "active_attempt"):
        if name in result and result[name] is not None:
            result[name] = _uuid(result[name])
    return result


def _hash(value: str) -> bytes:
    if type(value) is not str or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise SqlPublicationError("sql_publication:digest")
    return bytes.fromhex(value)


def _json(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (ValueError, TypeError):
        raise SqlPublicationError("sql_publication:json") from None


def _db_time(value: datetime) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise SqlPublicationError("sql_publication:utc_datetime_required")
    return value.astimezone(UTC).replace(tzinfo=None)


@dataclass(frozen=True)
class AzureSqlControlTarget:
    """Exact isolated SQL control DB, not an analytics endpoint or connection string."""

    server: str
    database: str
    resource_id: str

    def __post_init__(self) -> None:
        if (
            any(
                type(value) is not str
                for value in (self.server, self.database, self.resource_id)
            )
            or not re.fullmatch(
                r"[a-z0-9][a-z0-9-]{0,62}\.database\.windows\.net", self.server
            )
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", self.database)
        ):
            raise SqlPublicationError("sql_publication:control_database_required")
        expected = (
            r"/subscriptions/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
            r"/resourceGroups/[^/]+/providers/"
            r"Microsoft\.Sql/servers/"
            + re.escape(self.server.split(".")[0])
            + r"/databases/"
            + re.escape(self.database)
        )
        if not re.fullmatch(expected, self.resource_id, re.IGNORECASE):
            raise SqlPublicationError("sql_publication:database_resource_identity")


@dataclass(frozen=True)
class FabricSqlControlTarget:
    """Reviewed Fabric SQLDatabase OLTP pins, never its analytics endpoint.

    Construct with independently reviewed pins and compare type-specific Fabric
    metadata with ``verify_item`` before deployment. Syntax alone is not proof
    of item existence, effective permissions or endpoint identity.
    """

    workspace_id: str
    item_id: str
    server: str
    database: str

    def __post_init__(self) -> None:
        if (
            any(
                type(value) is not str
                for value in (
                    self.workspace_id,
                    self.item_id,
                    self.server,
                    self.database,
                )
            )
            or _uuid(self.workspace_id) != self.workspace_id
            or _uuid(self.item_id) != self.item_id
            or not re.fullmatch(
                r"[a-z0-9][a-z0-9-]{0,62}\.database\.fabric\.microsoft\.com",
                self.server,
            )
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", self.database)
        ):
            raise SqlPublicationError(
                "sql_publication:fabric_control_database_required"
            )

    def verify_item(self, item: Mapping[str, Any]) -> None:
        """Refuse mismatched metadata returned by the SQLDatabase GET endpoint."""
        properties = item.get("properties")
        if not isinstance(properties, Mapping) or (
            item.get("type") != "SQLDatabase"
            or item.get("id") != self.item_id
            or item.get("workspaceId") != self.workspace_id
            or properties.get("databaseName") != self.database
            or properties.get("serverFqdn") not in (self.server, self.server + ",1433")
        ):
            raise SqlPublicationError("sql_publication:fabric_item_identity")


class _Procedures:
    def __init__(
        self,
        target: AzureSqlControlTarget | FabricSqlControlTarget,
        credential: Any,
        *,
        connect: Callable[[], Any] | None = None,
        query_timeout_seconds: int = 30,
        expected_client_id: str | None = None,
    ) -> None:
        if (
            type(query_timeout_seconds) is not int
            or not 1 <= query_timeout_seconds <= 300
        ):
            raise SqlPublicationError("sql_publication:query_timeout")
        self._target, self._credential, self._connect = target, credential, connect
        self._query_timeout_seconds = query_timeout_seconds
        self._expected_client_id = (
            _uuid(expected_client_id) if expected_client_id is not None else None
        )

    def _connection(self):
        if self._connect is not None:
            connection = self._connect()
            if self._expected_client_id is not None:
                self._verify_identity(connection)
            return connection
        import pyodbc

        if self._expected_client_id is None:
            raise SqlPublicationError("sql_publication:client_identity_required")
        if pyodbc.pooling is not False:
            raise SqlPublicationError(
                "sql_publication:pooling_must_be_disabled_at_startup"
            )
        if REQUIRED_ODBC_DRIVER not in pyodbc.drivers():
            raise SqlPublicationError("sql_publication:odbc_driver_18_missing")
        token = self._credential.get_token(SQL_SCOPE).token.encode("utf-16-le")
        connection = pyodbc.connect(
            f"Driver={{{REQUIRED_ODBC_DRIVER}}};Server={self._target.server},1433;"
            f"Database={self._target.database};Encrypt=Yes;TrustServerCertificate=No;",
            attrs_before={1256: struct.pack("<I", len(token)) + token},
            autocommit=True,
            timeout=30,
        )
        self._verify_identity(connection)
        return connection

    def _verify_identity(self, connection: Any) -> None:
        # A token passed via attrs_before does not identify a pooled SQL session.
        try:
            connection.timeout = self._query_timeout_seconds
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "SELECT DB_NAME(), "
                    "CONVERT(varchar(36),CONVERT(uniqueidentifier,sid)) "
                    "FROM sys.database_principals WHERE principal_id=USER_ID()"
                )
                rows = cursor.fetchall()
                if (
                    len(rows) != 1
                    or len(rows[0]) != 2
                    or rows[0][0] != self._target.database
                    or type(rows[0][1]) is not str
                    or rows[0][1].lower() != self._expected_client_id
                ):
                    raise SqlPublicationError(
                        "sql_publication:session_identity_mismatch"
                    )
                if cursor.nextset():
                    raise SqlPublicationError("sql_publication:session_identity_result")
            finally:
                cursor.close()
        except BaseException:
            connection.close()
            raise

    def _execute(self, sql: str, values: tuple[Any, ...]) -> list[dict[str, Any]]:
        # SQL text comes ONLY from the closed methods below, never caller input.
        import pyodbc

        try:
            connection = self._connection()
            try:
                # ODBC connect(timeout=...) bounds login, not statement execution.
                connection.timeout = self._query_timeout_seconds
                cursor = connection.cursor()
                try:
                    cursor.execute(sql, values)
                    rows = []
                    while True:
                        if cursor.description:
                            names = [column[0] for column in cursor.description]
                            rows.extend(
                                dict(zip(names, row, strict=True))
                                for row in cursor.fetchall()
                            )
                        if not cursor.nextset():
                            break
                    return rows
                finally:
                    cursor.close()
            finally:
                connection.close()
        except (pyodbc.Error, AzureError):
            # SQL and credential diagnostics may echo parameters or provider URLs.
            raise SqlPublicationError("sql_publication:procedure_failed") from None

    def _result(self, sql: str, values: tuple[Any, ...]) -> dict[str, Any]:
        rows = self._execute(sql, values)
        if len(rows) != 1 or set(rows[0]) != {"result_json"}:
            raise SqlPublicationError("sql_publication:result_shape")
        try:
            result = json.loads(rows[0]["result_json"])
        except (ValueError, TypeError):
            raise SqlPublicationError("sql_publication:result_json") from None
        if not isinstance(result, dict):
            raise SqlPublicationError("sql_publication:result_shape")
        return _control_uuids(result)


class SqlPublicationControl(_Procedures):
    """Broker/reader procedures; no grants, seals, raw SQL or bootstrap methods."""

    def read_control(self, target_id: str) -> dict[str, Any]:
        """Read exact combined ownership/active revision."""
        return self._result(
            "EXEC publication.ReadControl @target_id=?", (_uuid(target_id),)
        )

    def acquire(
        self,
        target_id: str,
        owner_id: str,
        *,
        expected_revision: int,
        lease_seconds: int,
    ) -> dict[str, Any]:
        """Acquire a new server-issued epoch/session, preserving the active pointer."""
        if (
            type(expected_revision) is not int
            or expected_revision < 0
            or type(lease_seconds) is not int
            or not 1 <= lease_seconds <= 300
        ):
            raise SqlPublicationError("sql_publication:acquire")
        return self._result(
            "EXEC publication.Acquire @target_id=?,@owner_id=?,@expected_revision=?,@lease_seconds=?",
            (_uuid(target_id), _uuid(owner_id), expected_revision, lease_seconds),
        )

    def begin_attempt(
        self,
        target_id: str,
        owner_id: str,
        session_id: str,
        epoch: int,
        candidate: Mapping[str, Any],
        *,
        request_id: str,
    ) -> str:
        """Use a broker-owned stable UUID for a retryable private attempt allocation."""
        rows = self._execute(
            "EXEC publication.BeginAttempt @target_id=?,@owner_id=?,@session_id=?,"
            "@epoch=?,@candidate_json=?,@request_id=?",
            (
                _uuid(target_id),
                _uuid(owner_id),
                _uuid(session_id),
                epoch,
                _json(dict(candidate)),
                _uuid(request_id),
            ),
        )
        if len(rows) != 1 or set(rows[0]) != {"attempt_id"}:
            raise SqlPublicationError("sql_publication:attempt_result")
        return _uuid(rows[0]["attempt_id"])

    def commit_attempt(
        self,
        target_id: str,
        owner_id: str,
        session_id: str,
        epoch: int,
        *,
        expected_revision: int,
        attempt_id: str,
        catalog_digest: str,
        operation: str,
        authority_digest: str,
        request_id: str,
    ) -> dict[str, Any]:
        """Call the one atomic pointer/receipt/audit/idempotency procedure."""
        if operation not in {"admit", "restore"}:
            raise SqlPublicationError("sql_publication:operation")
        return self._result(
            "EXEC publication.CommitAttempt @target_id=?,@owner_id=?,@session_id=?,@epoch=?,"
            "@expected_revision=?,@attempt_id=?,@catalog_digest=?,@operation=?,"
            "@authority_digest=?,@request_id=?",
            (
                _uuid(target_id),
                _uuid(owner_id),
                _uuid(session_id),
                epoch,
                expected_revision,
                _uuid(attempt_id),
                _hash(catalog_digest),
                operation,
                _hash(authority_digest),
                _uuid(request_id),
            ),
        )

    def read_attempt(
        self, target_id: str, attempt_id: str, catalog_digest: str
    ) -> dict[str, Any]:
        """Read an exact sealed attempt, never latest-by-generation."""
        rows = self._execute(
            "EXEC publication.ReadAttempt @target_id=?,@attempt_id=?,@catalog_digest=?",
            (_uuid(target_id), _uuid(attempt_id), _hash(catalog_digest)),
        )
        if len(rows) != 1 or set(rows[0]) != {
            "catalog_json",
            "inventory_json",
            "evidence_json",
        }:
            raise SqlPublicationError("sql_publication:attempt_result")
        return rows[0]

    def recover_outcome(
        self,
        target_id: str,
        owner_id: str,
        session_id: str,
        epoch: int,
        *,
        expected_revision: int,
        attempt_id: str,
        catalog_digest: str,
        operation: str,
        authority_digest: str,
        request_id: str,
    ) -> dict[str, Any] | None:
        """Read an authenticated original request's historical result; never commit.

        A trusted broker must map transport identity to the original owner.
        No expiry/retention reread is required for historical result recovery.
        None means no outcome, NOT fresh authority or current pointer state.
        """
        if operation not in {"admit", "restore"}:
            raise SqlPublicationError("sql_publication:operation")
        result = self._result(
            "EXEC publication.RecoverOutcome @target_id=?,@owner_id=?,@session_id=?,@epoch=?,"
            "@expected_revision=?,@attempt_id=?,@catalog_digest=?,@operation=?,"
            "@authority_digest=?,@request_id=?",
            (
                _uuid(target_id),
                _uuid(owner_id),
                _uuid(session_id),
                epoch,
                expected_revision,
                _uuid(attempt_id),
                _hash(catalog_digest),
                operation,
                _hash(authority_digest),
                _uuid(request_id),
            ),
        )
        if set(result) == {"found"} and result["found"] is False:
            return None
        if (
            set(result) != {"found", "outcome"}
            or result["found"] is not True
            or not isinstance(result["outcome"], dict)
        ):
            raise SqlPublicationError("sql_publication:outcome_result")
        return _control_uuids(result["outcome"])


class SqlPublicationVerifier(_Procedures):
    """Trusted verifier principal only; worker/broker request bodies cannot call this."""

    def seal_attempt(
        self,
        target_id: str,
        attempt_id: str,
        *,
        catalog: Mapping[str, Any],
        catalog_digest: str,
        inventory: list[dict[str, Any]],
        evidence: Mapping[str, Any],
    ) -> None:
        """Persist actual readback evidence via verifier-only procedure.

        Caller must be the independently trusted provider verifier. This method
        is not itself a WORM verifier and must not be exposed as an HTTP body.
        """
        self._execute(
            "EXEC publication.SealAttempt @target_id=?,@attempt_id=?,@catalog_json=?,"
            "@catalog_digest=?,@inventory_json=?,@evidence_json=?",
            (
                _uuid(target_id),
                _uuid(attempt_id),
                _json(dict(catalog)),
                _hash(catalog_digest),
                _json(inventory),
                _json(dict(evidence)),
            ),
        )


class SqlPublicationAuthority(_Procedures):
    """Separate authoritative review/revocation principal, never broker credentials."""

    def record_grant(
        self,
        target_id: str,
        session_id: str,
        epoch: int,
        *,
        catalog_digest: str,
        operation: str,
        authority_digest: str,
        evidence_digest: str,
        valid_from: datetime,
        valid_until: datetime,
    ) -> None:
        """Record a separately validated exact grant, not an observed hash."""
        if operation not in {"admit", "restore"}:
            raise SqlPublicationError("sql_publication:operation")
        self._execute(
            "EXEC publication.RecordGrant @target_id=?,@session_id=?,@epoch=?,@catalog_digest=?,"
            "@operation=?,@authority_digest=?,@evidence_digest=?,@valid_from=?,@valid_until=?",
            (
                _uuid(target_id),
                _uuid(session_id),
                epoch,
                _hash(catalog_digest),
                operation,
                _hash(authority_digest),
                _hash(evidence_digest),
                _db_time(valid_from),
                _db_time(valid_until),
            ),
        )

    def revoke(
        self,
        target_id: str,
        session_id: str,
        epoch: int,
        *,
        catalog_digest: str,
        operation: str,
    ) -> None:
        """Serialize revocation with target acquisition and commit."""
        if operation not in {"admit", "restore"}:
            raise SqlPublicationError("sql_publication:operation")
        self._execute(
            "EXEC publication.[Revoke] @target_id=?,@session_id=?,@epoch=?,@catalog_digest=?,@operation=?",
            (
                _uuid(target_id),
                _uuid(session_id),
                epoch,
                _hash(catalog_digest),
                operation,
            ),
        )


class SqlPublicationSetup(_Procedures):
    """Create-only target binding using a separately approved setup principal."""

    def provision_target(
        self,
        target_id: str,
        expected_target: Mapping[str, str],
        *,
        account_resource_id: str,
        blob_endpoint: str,
        container: str,
        retain_until: datetime,
    ) -> None:
        """Bind exact reviewed target/backend/horizon; does not qualify WORM or identities."""
        self._execute(
            "EXEC publication.ProvisionTarget @target_id=?,@target_json=?,@account_resource_id=?,"
            "@blob_endpoint=?,@container_name=?,@retain_until=?",
            (
                _uuid(target_id),
                _json(dict(expected_target)),
                account_resource_id,
                blob_endpoint,
                container,
                _db_time(retain_until),
            ),
        )


def bootstrap_batches() -> tuple[str, ...]:
    """Return packaged administrator SQL in order; this function never executes it."""
    root = files("ontology_discovery").joinpath("sql_control")
    batches = []
    for name in ("schema.sql", "permissions.sql"):
        batches.extend(
            chunk.strip()
            for chunk in re.split(r"(?im)^\s*GO\s*$", root.joinpath(name).read_text())
            if chunk.strip()
        )
    return tuple(batches)


def bootstrap_database(connection: Any) -> None:
    """Explicit admin-only bootstrap for a reviewed isolated control database.

    No users/identity memberships or cloud resources are provisioned. The caller
    supplies an admin connection; runtime driver classes cannot invoke this.
    """
    if connection.autocommit is not False:
        raise SqlPublicationError(
            "sql_publication:bootstrap_requires_explicit_transaction"
        )
    cursor = connection.cursor()
    try:
        for batch in bootstrap_batches():
            cursor.execute(batch)
            while cursor.nextset():
                pass
        connection.commit()
    except Exception:
        # Rollback failed DDL/control setup; retain original error for admin tools.
        connection.rollback()
        raise
    finally:
        cursor.close()
