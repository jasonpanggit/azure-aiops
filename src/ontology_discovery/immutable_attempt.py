"""Default-off immutable attempt publication core, not a OneLake authority adapter.

All mutation methods belong to a trusted enforcing boundary. Implementing this
ABC over raw CAS plus client-side authorization is NOT conformant.
"""

from __future__ import annotations

import hashlib
import json
import re
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

import pyarrow as pa

from fabric.schema_registry import schema_for
from ontology_discovery.publisher import PublicationSafetyError

PROTOCOL = "immutable-attempt/v1"
_SAFE = re.compile(r"[A-Za-z0-9_-]{1,128}")


def _json(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError):
        raise PublicationSafetyError("immutable_attempt:noncanonical_json") from None


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _refuse(reason: str) -> None:
    raise PublicationSafetyError(f"immutable_attempt:{reason}")


def _schema_value_equal(original: Any, converted: Any) -> bool:
    if type(original) is int and type(converted) is float:
        return original == converted
    if type(original) is not type(converted):
        return False
    if type(original) is dict:
        return original.keys() == converted.keys() and all(
            _schema_value_equal(value, converted[key]) for key, value in original.items()
        )
    if type(original) is list:
        return len(original) == len(converted) and all(
            _schema_value_equal(left, right) for left, right in zip(original, converted, strict=True)
        )
    return original == converted


def _validate_product_rows(table: str, rows: list[dict[str, Any]]) -> pa.Schema:
    try:
        schema = schema_for(table)
    except KeyError:
        raise PublicationSafetyError("immutable_attempt:product_schema") from None
    if any(type(row) is not dict or not set(row).issubset(schema.names) for row in rows):
        _refuse("product_schema")
    try:
        converted = pa.Table.from_pylist(rows, schema=schema).to_pylist()
    except (pa.ArrowException, TypeError, OverflowError, UnicodeError):
        raise PublicationSafetyError("immutable_attempt:product_schema") from None
    # Sparse rows retain missing/None values; Arrow must not discard columns or
    # silently coerce supplied values (notably bool -> number or float -> int).
    if any(
        not _schema_value_equal(value, typed[name])
        for row, typed in zip(rows, converted, strict=True) for name, value in row.items()
    ):
        _refuse("product_schema")
    return schema


def _candidate_binding(candidate: Mapping[str, Any]) -> None:
    required = {
        "generation_id", "source_generation", "content_hash",
        "staged_manifest_digest", "validation_digest", "authorization_digest",
        "attestation_digest", "expected_target",
    }
    if set(candidate) != required or any(
        type(candidate[key]) is not str or not candidate[key]
        for key in required - {"expected_target"}
    ):
        _refuse("candidate_binding")
    target = candidate["expected_target"]
    if (
        type(target) is not dict
        or set(target) != {
            "tenant_id", "subscription_id", "connection_id",
            "workspace_id", "item_id", "definition_fingerprint",
        }
        or any(type(value) is not str or not value for value in target.values())
    ):
        _refuse("target_binding")


@dataclass(frozen=True)
class AttemptSession:
    """Opaque boundary-issued ownership session; never a bearer authority receipt."""

    owner: str
    epoch: int
    session_id: str


@dataclass(frozen=True)
class AttemptReference:
    """Exact immutable catalog identity, not a latest-generation lookup."""

    attempt_id: str
    generation_id: str
    catalog_digest: str

    def __post_init__(self) -> None:
        if (
            type(self.attempt_id) is not str or not _SAFE.fullmatch(self.attempt_id)
            or type(self.generation_id) is not str or not _SAFE.fullmatch(self.generation_id)
            or type(self.catalog_digest) is not str
            or not re.fullmatch(r"[a-f0-9]{64}", self.catalog_digest)
        ):
            _refuse("reference")

    def as_dict(self) -> dict[str, str]:
        """Return the exact serializable pointer reference."""
        return {
            "attempt_id": self.attempt_id,
            "generation_id": self.generation_id,
            "catalog_digest": self.catalog_digest,
        }

    @classmethod
    def parse(cls, value: Mapping[str, Any]) -> AttemptReference:
        """Reject missing/extra pointer fields rather than choosing a receipt."""
        if set(value) != {"attempt_id", "generation_id", "catalog_digest"}:
            _refuse("reference")
        if any(type(part) is not str for part in value.values()):
            _refuse("reference")
        return cls(**value)


@dataclass(frozen=True)
class AttemptControl:
    """Combined ownership and active reference revision."""

    session: AttemptSession | None
    active: AttemptReference | None
    revision: str


@dataclass(frozen=True)
class ImmutableObjectReference:
    """Trusted verifier's exact block-blob identity; ETag is observation only."""

    account_resource_id: str
    endpoint: str
    container: str
    object_name: str
    length: int
    content_digest: str
    etag: str
    version_id: None = None

    def __post_init__(self) -> None:
        if (
            any(type(value) is not str or not value for value in (
                self.account_resource_id, self.endpoint, self.container,
                self.object_name, self.content_digest, self.etag,
            ))
            or type(self.length) is not int or self.length < 0
            or self.version_id is not None
            or not re.fullmatch(r"[a-f0-9]{64}", self.content_digest)
            or self.object_name.startswith("/")
            or any(part in {"", ".", ".."} for part in self.object_name.split("/"))
        ):
            _refuse("object_reference")

    def as_dict(self) -> dict[str, Any]:
        """Return the closed, exact identity included in the catalog digest."""
        return {
            "account_resource_id": self.account_resource_id, "endpoint": self.endpoint,
            "container": self.container, "object_name": self.object_name,
            "length": self.length, "content_digest": self.content_digest,
            "etag": self.etag, "version_id": None,
        }


class AttemptBoundary(ABC):
    """Trusted write/commit authority and immutable storage capability.

    Required enforcement: no raw backing-store credentials escape to writers;
    attempt creation/write/seal is bound to the issuing session and private
    namespace; objects cannot be overwritten/deleted; seals cannot expose
    partial products. Control CAS changes owner+epoch+active in one document.
    Commit checks session, exact predecessor revision, current expiry/revocation
    and independent admission/restore authority INSIDE the serialized authority
    boundary, not a caller callback. Ambiguous retries are bound to a request
    identity and cannot repeat side effects or revive a stale authorization.

    The storage/authority serialization primitive is adapter-specific.
    OneLakeDocumentStore CAS alone does not implement these conditions.
    Session fields are not bearer authorization: a verified transport principal
    must match the server-owned session even when the caller knows a newer
    owner's exact epoch, revision and session ID.

    Proposed production implementation is a dedicated trusted broker identity
    with Azure SQL procedure-only access (not Lakehouse SQL) and server-verified
    LOCKED Blob WORM retention covering all active/retained references, no append
    exceptions. Workers have no SQL/blob/protected-OneLake mutation credentials.
    SQL authority/revocation is authoritative; copied OneLake flags are not.
    Deadline semantics linearize at the final guarded database transition, not
    network acknowledgement; stronger expiry guarantees remain unsupported.
    """

    @abstractmethod
    def read_control(self) -> AttemptControl:
        """Read one exact combined owner/epoch/active revision."""

    @abstractmethod
    def begin(self, session: AttemptSession, attempt_id: str, candidate_json: str) -> None:
        """Allocate or idempotently reopen this session's private attempt."""

    @abstractmethod
    def create_product(
        self, session: AttemptSession, attempt_id: str, table: str, product_json: str,
    ) -> ImmutableObjectReference:
        """Create/verify exact bytes, identity and retention; conflicting retries fail."""

    def create_products(
        self, session: AttemptSession, attempt_id: str, products: Mapping[str, str],
    ) -> Mapping[str, ImmutableObjectReference]:
        """Create a complete set; providers with immutable manifests override this."""
        return {
            table: self.create_product(session, attempt_id, table, body)
            for table, body in products.items()
        }

    @abstractmethod
    def seal(self, session: AttemptSession, reference: AttemptReference, catalog_json: str) -> None:
        """Validate all referenced bytes and atomically expose the complete seal."""

    @abstractmethod
    def read_catalog(self, reference: AttemptReference) -> str:
        """Read only the exact complete seal, never an in-progress catalog."""

    @abstractmethod
    def read_product(self, reference: AttemptReference, table: str) -> str:
        """Resolve this sealed attempt's product; no arbitrary URI accepted."""

    @abstractmethod
    def recover_commit(
        self, session: AttemptSession, reference: AttemptReference, *,
        expected_revision: str, operation: Literal["admit", "restore"],
        request_id: str, authorization_digest: str,
    ) -> AttemptControl | None:
        """Authenticated exact-request outcome lookup, with NO new mutation.

        Match every original request field and reject request-ID reuse with
        changed fields. Return None only when no outcome exists. Historical
        success is not current pointer state or permission to read artifacts.
        No fresh lease, grant, retained-byte or catalog check applies to this
        already-committed outcome. Storage/transport errors must propagate.
        """

    @abstractmethod
    def commit(
        self, session: AttemptSession, reference: AttemptReference, *,
        expected_revision: str, operation: Literal["admit", "restore"],
        request_id: str, authorization_digest: str,
    ) -> AttemptControl:
        """Enforce fresh operation-specific authority atomically with control CAS."""


class OneLakeAttemptBoundary:
    """Unavailable provider adapter: do not substitute a renewable lease."""

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        _refuse("provider_fenced_authority_and_immutable_namespace_unavailable")


class AzureSqlBlobAttemptBoundary:
    """Reserved backend composition; no configured resources or qualified adapter.

    Never accept caller booleans, shared publisher identities, unlocked WORM,
    append exceptions, raw SQL DML or a Lakehouse analytics endpoint as proof.
    No SQL procedures, Blob SDK upload or broker endpoint are implemented here.
    """

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        _refuse("sql_broker_locked_worm_adapter_not_implemented_or_qualified")


class ImmutableAttemptProtocol:
    """Real product projection/pinned-reader/commit core behind explicit opt-in."""

    def __init__(self, boundary: AttemptBoundary) -> None:
        if not isinstance(boundary, AttemptBoundary):
            _refuse("enforcing_boundary_required")
        self._boundary = boundary

    def control(self) -> AttemptControl:
        """Return the enforcing boundary's current combined control revision."""
        return self._boundary.read_control()

    def stage(
        self, session: AttemptSession, *, attempt_id: str,
        candidate: Mapping[str, Any],
        products: Mapping[str, Sequence[Mapping[str, Any]]],
    ) -> AttemptReference:
        """Seal complete candidate-derived products in one private attempt.

        Resume uses the identical attempt ID and exact bytes. A new attempt
        is mandatory after ownership takeover; no active/retained overwrite.
        """
        if type(attempt_id) is not str or not _SAFE.fullmatch(attempt_id):
            _refuse("attempt_id")
        _candidate_binding(candidate)
        generation = candidate["generation_id"]
        if type(generation) is not str or not _SAFE.fullmatch(generation) or not products:
            _refuse("candidate_binding")
        candidate_json = _json(dict(candidate))
        products = json.loads(_json({
            name: [dict(row) for row in rows] for name, rows in products.items()
        }))
        bodies = {}
        schemas = {}
        for table, rows in sorted(products.items()):
            if type(table) is not str or not re.fullmatch(r"ontology_[a-z0-9_]+", table):
                _refuse("product_name")
            schemas[table] = _validate_product_rows(table, rows)
            bodies[table] = _json({"rows": [dict(row) for row in rows]})
        self._boundary.begin(session, attempt_id, candidate_json)
        artifacts = self._boundary.create_products(session, attempt_id, bodies)
        if set(artifacts) != set(bodies):
            _refuse("artifact_membership")
        entries = {}
        for table, rows in sorted(products.items()):
            schema = schemas[table]
            body = bodies[table]
            artifact = artifacts[table]
            if (
                type(artifact) is not ImmutableObjectReference
                or artifact.content_digest != hashlib.sha256(body.encode()).hexdigest()
                or artifact.length != len(body.encode())
            ):
                _refuse("artifact_verification")
            entries[table] = {
                "rows": len(rows),
                "content_digest": hashlib.sha256(body.encode()).hexdigest(),
                "arrow_schema_digest": hashlib.sha256(schema.serialize()).hexdigest(),
                "artifact": artifact.as_dict(),
            }
        catalog = {
            "protocol": PROTOCOL, "attempt_id": attempt_id,
            "candidate": json.loads(candidate_json), "products": entries,
        }
        reference = AttemptReference(attempt_id, generation, _digest(catalog))
        self._boundary.seal(session, reference, _json(catalog))
        self.read_catalog(reference)
        return reference

    def read_catalog(self, reference: AttemptReference) -> dict[str, Any]:
        """Validate exact sealed catalog and every product before returning it."""
        try:
            raw = self._boundary.read_catalog(reference)
            catalog = json.loads(raw)
            _candidate_binding(catalog["candidate"])
            if (
                raw != _json(catalog)
                or _digest(catalog) != reference.catalog_digest
                or set(catalog) != {"protocol", "attempt_id", "candidate", "products"}
                or catalog["protocol"] != PROTOCOL
                or catalog["attempt_id"] != reference.attempt_id
                or catalog["candidate"]["generation_id"] != reference.generation_id
                or not catalog["products"]
            ):
                _refuse("catalog")
            for table, entry in catalog["products"].items():
                self._read_product(reference, table, entry)
            return catalog
        except (KeyError, TypeError, ValueError):
            raise PublicationSafetyError("immutable_attempt:catalog_unreadable") from None

    def _read_product(
        self, reference: AttemptReference, table: str, entry: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        raw = self._boundary.read_product(reference, table)
        value = json.loads(raw)
        if (
            set(entry) != {"rows", "content_digest", "arrow_schema_digest", "artifact"}
            or type(entry["rows"]) is not int
            or raw != _json(value)
            or hashlib.sha256(raw.encode()).hexdigest() != entry["content_digest"]
            or hashlib.sha256(schema_for(table).serialize()).hexdigest()
            != entry["arrow_schema_digest"]
            or set(value) != {"rows"}
            or not isinstance(value["rows"], list)
            or len(value["rows"]) != entry["rows"]
            or any(not isinstance(row, dict) for row in value["rows"])
        ):
            _refuse("product")
        artifact = ImmutableObjectReference(**entry["artifact"])
        if artifact.length != len(raw.encode()) or artifact.content_digest != entry["content_digest"]:
            _refuse("product_identity")
        _validate_product_rows(table, value["rows"])
        return value["rows"]

    def read_table(self, reference: AttemptReference, table: str) -> list[dict[str, Any]]:
        """Read from an exact catalog, never latest receipt or fixed Delta head."""
        catalog = self.read_catalog(reference)
        if table not in catalog["products"]:
            _refuse("product_missing")
        return self._read_product(reference, table, catalog["products"][table])

    def active(self) -> tuple[AttemptReference | None, dict[str, Any] | None]:
        """Resolve one accepted pointer revision and its immutable catalog."""
        control = self._boundary.read_control()
        return control.active, self.read_catalog(control.active) if control.active else None

    def commit(
        self, session: AttemptSession, reference: AttemptReference, *,
        expected_revision: str, operation: Literal["admit", "restore"],
        request_id: str, authorization_digest: str,
    ) -> AttemptControl:
        """Ask the enforcing boundary to commit, never implement a raw CAS fallback."""
        recovered = self.recover_commit(
            session, reference, expected_revision=expected_revision, operation=operation,
            request_id=request_id, authorization_digest=authorization_digest,
        )
        if recovered is not None:
            return recovered
        self.read_catalog(reference)
        return self._boundary.commit(
            session, reference, expected_revision=expected_revision,
            operation=operation, request_id=request_id,
            authorization_digest=authorization_digest,
        )

    def recover_commit(
        self, session: AttemptSession, reference: AttemptReference, *,
        expected_revision: str, operation: Literal["admit", "restore"],
        request_id: str, authorization_digest: str,
    ) -> AttemptControl | None:
        """Recover only an authenticated exact historical outcome, never publish."""
        if (
            operation not in {"admit", "restore"}
            or type(request_id) is not str or not _SAFE.fullmatch(request_id)
            or type(authorization_digest) is not str or not authorization_digest
        ):
            _refuse("commit_request")
        return self._boundary.recover_commit(
            session, reference, expected_revision=expected_revision,
            operation=operation, request_id=request_id,
            authorization_digest=authorization_digest,
        )
