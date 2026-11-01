"""Default-unwired trusted SQL/Blob composition; no worker sink credentials.

Uses real closed SQL clients and the independently verified Blob uploader.
This server library is NOT a deployed HTTP transport, a permission proof or a
qualified production AttemptBoundary factory. The default core factory refuses.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from collections.abc import Mapping
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from importlib.resources import files
from typing import Any
from uuid import UUID, uuid4

from api.auth import EntraJwtAuthenticator
from api.rbac import ACTION_MAINTAIN_ONTOLOGY
from storage.immutable_blob_artifacts import (
    ImmutableBlobArtifactStore,
    SealedBlobInventory,
    SealedBlobObject,
)

from .immutable_attempt import (
    PROTOCOL,
    AttemptBoundary,
    AttemptControl,
    AttemptReference,
    AttemptSession,
    ImmutableObjectReference,
    _json,
    _validate_product_rows,
)
from .publisher import PublicationSafetyError
from .sql_publication_control import (
    SqlPublicationControl,
    SqlPublicationError,
    SqlPublicationVerifier,
    _hash,
    _uuid,
)


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise PublicationSafetyError(f"sql_blob_broker:{reason}")


def _revision(value: str) -> int:
    _require(
        type(value) is str and bool(re.fullmatch(r"0|[1-9][0-9]{0,18}", value))
        and int(value) <= 9223372036854775807,
        "base_revision",
    )
    return int(value)


def _mapping(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        raise PublicationSafetyError("sql_blob_broker:json_unreadable") from None
    _require(type(value) is dict, "json_object_required")
    return value


def _object(item: SealedBlobObject) -> ImmutableObjectReference:
    return ImmutableObjectReference(
        item.account_id, item.account_url, item.container_name, item.blob_name,
        item.size, item.sha256, item.etag, item.version_id,
    )


def _inventory_json(inventory: SealedBlobInventory) -> dict[str, Any]:
    def encode(value):
        if isinstance(value, datetime):
            return value.isoformat()
        raise TypeError("Unsupported provider evidence value")

    return json.loads(json.dumps(asdict(inventory), default=encode, allow_nan=False))


def _inventory(value: Mapping[str, Any]) -> SealedBlobInventory:
    try:
        _require(
            set(value) == {"attempt_id", "retain_until", "manifest_sha256", "objects"}
            and type(value["objects"]) is list and bool(value["objects"])
            and type(value["manifest_sha256"]) is str
            and bool(re.fullmatch(r"[a-f0-9]{64}", value["manifest_sha256"])),
            "inventory_shape",
        )
        objects = []
        for raw in value["objects"]:
            _require(set(raw) == {field.name for field in fields(SealedBlobObject)}, "object_shape")
            item = dict(raw)
            for name in ("creation_time", "verified_at", "retained_until"):
                item[name] = datetime.fromisoformat(item[name])
                _require(item[name].tzinfo is not None, "evidence_timezone")
            objects.append(SealedBlobObject(**item))
        return SealedBlobInventory(
            value["attempt_id"], datetime.fromisoformat(value["retain_until"]),
            value["manifest_sha256"], tuple(objects),
        )
    except (ValueError, KeyError, TypeError):
        raise PublicationSafetyError("sql_blob_broker:inventory_unreadable") from None


class SqlBrokerVerifier(SqlPublicationVerifier):
    """Trusted provider verifier with transactionally fenced broker seals."""

    def seal_owned_attempt(
        self, target_id: str, session: AttemptSession, attempt_id: str, *,
        catalog: Mapping[str, Any], catalog_digest: str,
        inventory: list[dict[str, Any]], evidence: Mapping[str, Any],
    ) -> None:
        """Persist verified evidence only while its original SQL session owns the target."""
        self._execute(
            "EXEC publication.SealOwnedAttempt @target_id=?,@owner_id=?,@session_id=?,"
            "@epoch=?,@attempt_id=?,@catalog_json=?,@catalog_digest=?,"
            "@inventory_json=?,@evidence_json=?",
            (
                _uuid(target_id), _uuid(session.owner), _uuid(session.session_id),
                session.epoch, _uuid(attempt_id), _json(dict(catalog)),
                _hash(catalog_digest), _json(inventory), _json(dict(evidence)),
            ),
        )


class SqlBrokerControl(SqlPublicationControl):
    """Adds closed immutable-reference metadata reads, never blob authorization."""

    def reference_generation(self, target_id: str, attempt_id: str, digest: str) -> str:
        """Bind historical reference generation without fresh artifact/retention reads."""
        value = self._result(
            "EXEC publication.ReadReferenceMetadata @target_id=?,@attempt_id=?,@catalog_digest=?",
            (_uuid(target_id), _uuid(attempt_id), _hash(digest)),
        )
        _require(
            set(value) == {"generation_id"} and type(value["generation_id"]) is str
            and bool(re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value["generation_id"])),
            "reference_metadata",
        )
        return value["generation_id"]

    def readable_generation(self, target_id: str, attempt_id: str, digest: str) -> str:
        """Check DB-time sealed horizon on cached exact metadata, never latest state."""
        value = self._result(
            "EXEC publication.ReadReadableReferenceMetadata @target_id=?,@attempt_id=?,@catalog_digest=?",
            (_uuid(target_id), _uuid(attempt_id), _hash(digest)),
        )
        _require(
            set(value) == {"generation_id"} and type(value["generation_id"]) is str,
            "readable_metadata",
        )
        return value["generation_id"]


def bootstrap_broker_metadata(connection: Any) -> None:
    """Explicit admin-only optional migration; no resources, users or memberships."""
    if connection.autocommit is not False:
        raise SqlPublicationError("sql_publication:bootstrap_requires_explicit_transaction")
    text = files("ontology_discovery").joinpath("sql_control/broker.sql").read_text()
    cursor = connection.cursor()
    try:
        for batch in re.split(r"(?im)^\s*GO\s*$", text):
            if batch.strip():
                cursor.execute(batch)
                while cursor.nextset():
                    pass
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()


@dataclass
class _Pending:
    session: AttemptSession
    candidate_json: str | None = None
    products: SealedBlobInventory | None = None
    catalog_attempt: str | None = None
    seal_request: dict[str, Any] | None = None


class SqlBlobPublicationBroker:
    """Server-owned fixed target/services; JWT callers never receive these credentials.

    Not wired to API/worker configuration. Provisioning, transport serving and
    effective SQL/worker permissions remain separately unqualified. Header
    authentication uses existing Entra signature/issuer/audience/expiry checks
    with explicit oid subject selection and an exact server-owned allowlist.
    """

    def __init__(
        self, *, control: SqlBrokerControl, verifier: SqlBrokerVerifier,
        artifacts: ImmutableBlobArtifactStore, authenticator: EntraJwtAuthenticator,
        target_id: str, expected_target: Mapping[str, str], retain_until: datetime,
        allowed_owners: frozenset[str],
    ) -> None:
        _require(
            isinstance(authenticator, EntraJwtAuthenticator)
            and authenticator.subject_claim == "oid", "oid_authenticator_required",
        )
        _require(
            isinstance(control, SqlBrokerControl)
            and isinstance(verifier, SqlBrokerVerifier)
            and isinstance(artifacts, ImmutableBlobArtifactStore),
            "provider_clients_required",
        )
        _require(
            set(expected_target) == {
                "tenant_id", "subscription_id", "connection_id",
                "workspace_id", "item_id", "definition_fingerprint",
            } and all(type(value) is str and value for value in expected_target.values()),
            "target_binding",
        )
        _require(
            isinstance(retain_until, datetime) and retain_until.tzinfo is not None
            and retain_until.utcoffset() is not None and bool(allowed_owners),
            "server_configuration",
        )
        self._owners = frozenset(str(UUID(owner)) for owner in allowed_owners)
        self._target_id, self._expected_target = _uuid(target_id), dict(expected_target)
        self._control, self._verifier, self._artifacts = control, verifier, artifacts
        self._auth, self._retain_until = authenticator, retain_until
        # Local bookkeeping only, NOT a distributed fencing primitive.
        self._lock = threading.RLock()
        self._pending: dict[str, _Pending] = {}

    def for_request(self, headers: Mapping[str, str]) -> SqlBlobRequestBoundary:
        """Authenticate a request; bind caller oid separately from every payload."""
        owner = self._authenticate(headers)
        return SqlBlobRequestBoundary(self, dict(headers), owner)

    def _authenticate(self, headers: Mapping[str, str]) -> str:
        principal = self._auth.authenticate(headers)
        try:
            owner = str(UUID(principal.subject))
        except (ValueError, TypeError, AttributeError):
            raise PublicationSafetyError("sql_blob_broker:caller_oid") from None
        _require(owner in self._owners, "caller_not_allowed")
        _require(
            any(
                grant.scope.matches({"subscription": self._expected_target["subscription_id"]})
                for grant in principal.grants_for(ACTION_MAINTAIN_ONTOLOGY)
            ),
            "caller_scope",
        )
        return owner


class SqlBlobRequestBoundary(AttemptBoundary):
    """Authenticated request-scoped real-provider composition, not a feature flag."""

    def __init__(self, server: SqlBlobPublicationBroker, headers: dict[str, str], owner: str) -> None:
        self.__server, self.__headers, self.__owner = server, headers, owner
        self.__catalogs: dict[AttemptReference, tuple[str, dict[str, SealedBlobObject]]] = {}

    def _actor(self, session: AttemptSession | None = None) -> SqlBlobPublicationBroker:
        server = self.__server
        _require(server._authenticate(self.__headers) == self.__owner, "caller_changed")
        if session is not None:
            _require(session.owner == self.__owner, "session_caller_mismatch")
        return server

    def _result(self, value: Mapping[str, Any], reference: AttemptReference | None = None) -> AttemptControl:
        server = self.__server
        _require(value.get("target_id") == server._target_id, "control_target")
        if value["owner_id"] is None or value["session_id"] is None:
            _require(
                value["owner_id"] is None and value["session_id"] is None
                and value["epoch"] == value["revision"] == 0 and value["active_attempt"] is None,
                "unowned_control",
            )
            session = None
        else:
            session = AttemptSession(value["owner_id"], value["epoch"], value["session_id"])
        if value["active_attempt"] is None:
            active = None
        else:
            generation = server._control.reference_generation(
                server._target_id, value["active_attempt"], value["active_digest"],
            )
            active = AttemptReference(value["active_attempt"], generation, value["active_digest"])
        if reference is not None:
            _require(active == reference, "outcome_reference")
        return AttemptControl(session, active, str(value["revision"]))

    def read_control(self) -> AttemptControl:
        """Read current control metadata, not current blob contents."""
        server = self._actor()
        return self._result(server._control.read_control(server._target_id))

    def acquire(self, *, expected_revision: str, lease_seconds: int = 300) -> AttemptControl:
        """Acquire server-issued SQL epoch/session for this authenticated oid."""
        server = self._actor()
        return self._result(server._control.acquire(
            server._target_id, self.__owner, expected_revision=_revision(expected_revision), lease_seconds=lease_seconds,
        ))

    def _owned(self, session: AttemptSession) -> SqlBlobPublicationBroker:
        server = self._actor(session)
        current = server._control.read_control(server._target_id)
        _require(
            (current["owner_id"], current["session_id"], current["epoch"])
            == (session.owner, session.session_id, session.epoch), "stale_session",
        )
        return server

    def allocate_attempt(self, session: AttemptSession) -> str:
        """Issue a process-owned Blob UUID; unfinished handles cannot survive restart."""
        server = self._owned(session)
        attempt = server._artifacts.begin_attempt()
        with server._lock:
            _require(attempt not in server._pending, "attempt_collision")
            server._pending[attempt] = _Pending(session)
        return attempt

    def _pending(self, session: AttemptSession, attempt_id: str) -> tuple[SqlBlobPublicationBroker, _Pending]:
        server = self._owned(session)
        with server._lock:
            pending = server._pending.get(attempt_id)
            _require(pending is not None and pending.session == session, "unfinished_attempt_handle_unavailable")
            return server, pending

    def begin(self, session: AttemptSession, attempt_id: str, candidate_json: str) -> None:
        """Bind the issued namespace to a canonical exact candidate, then persist in SQL."""
        server, pending = self._pending(session, attempt_id)
        candidate = _mapping(candidate_json)
        _require("expected_target" in candidate, "candidate_binding")
        _require(candidate_json == _json(candidate) and candidate["expected_target"] == server._expected_target,
                 "candidate_binding")
        with server._lock:
            _require(pending.candidate_json in (None, candidate_json), "candidate_changed")
            pending.candidate_json = candidate_json
        actual = server._control.begin_attempt(
            server._target_id, session.owner, session.session_id, session.epoch,
            candidate, request_id=attempt_id,
        )
        _require(actual == attempt_id, "sql_attempt_identity")

    def create_product(self, session, attempt_id, table, product_json):
        """Refuse partial-manifest uploads; the core must submit the complete set."""
        raise PublicationSafetyError("sql_blob_broker:complete_product_batch_required")

    def create_products(
        self, session: AttemptSession, attempt_id: str, products: Mapping[str, str],
    ) -> Mapping[str, ImmutableObjectReference]:
        """Upload the complete set once using actual provider create/readback checks."""
        server, pending = self._pending(session, attempt_id)
        _require(pending.candidate_json is not None, "attempt_not_begun")
        inventory = server._artifacts.upload_attempt(
            attempt_id, {name: body.encode() for name, body in products.items()},
            retain_until=server._retain_until,
        )
        _require(
            inventory.attempt_id == attempt_id
            and {item.logical_name for item in inventory.objects} == set(products)
            and len(inventory.objects) == len(products), "product_inventory",
        )
        with server._lock:
            pending.products = inventory
        return {item.logical_name: _object(item) for item in inventory.objects}

    def seal(self, session: AttemptSession, reference: AttemptReference, catalog_json: str) -> None:
        """Upload exact catalog separately; only provider readback reaches verifier SQL."""
        server, pending = self._pending(session, reference.attempt_id)
        _require(pending.products is not None, "products_unverified")
        catalog = _mapping(catalog_json)
        _require(
            catalog_json == _json(catalog)
            and hashlib.sha256(catalog_json.encode()).hexdigest() == reference.catalog_digest
            and set(catalog) == {"protocol", "attempt_id", "candidate", "products"}
            and catalog["protocol"] == PROTOCOL and catalog["attempt_id"] == reference.attempt_id
            and _json(catalog["candidate"]) == pending.candidate_json
            and catalog["candidate"]["generation_id"] == reference.generation_id
            and set(catalog["products"]) == {item.logical_name for item in pending.products.objects},
            "catalog_binding",
        )
        for item in pending.products.objects:
            entry = catalog["products"][item.logical_name]
            body = server._artifacts.read_object(item)
            payload = _mapping(body.decode())
            _require(
                set(payload) == {"rows"} and type(payload["rows"]) is list
                and all(type(row) is dict for row in payload["rows"])
                and _json(payload).encode() == body, "product_payload",
            )
            rows = payload["rows"]
            schema = _validate_product_rows(item.logical_name, rows)
            _require(
                set(entry) == {"rows", "content_digest", "arrow_schema_digest", "artifact"}
                and entry["artifact"] == _object(item).as_dict()
                and entry["content_digest"] == item.sha256
                and type(entry["rows"]) is int and entry["rows"] == len(rows)
                and entry["arrow_schema_digest"] == hashlib.sha256(schema.serialize()).hexdigest(),
                "catalog_product",
            )
        with server._lock:
            if pending.seal_request is None:
                if pending.catalog_attempt is None:
                    pending.catalog_attempt = server._artifacts.begin_attempt()
                inventory = server._artifacts.upload_attempt(
                    pending.catalog_attempt, {"catalog.json": catalog_json.encode()},
                    retain_until=server._retain_until,
                )
                _require(
                    len(inventory.objects) == 1
                    and server._artifacts.read_object(inventory.objects[0]) == catalog_json.encode(),
                    "catalog_readback",
                )
                all_objects = (*pending.products.objects, *inventory.objects)
                target = server._artifacts.target
                pending.seal_request = {
                    "catalog": catalog, "catalog_digest": reference.catalog_digest,
                    "inventory": [{**_object(item).as_dict(), "logical_name": item.logical_name}
                                  for item in pending.products.objects],
                    "evidence": {
                        "account_resource_id": target.account_id, "endpoint": target.account_url,
                        "container": target.container_name, "policy_state": "Locked",
                        "versioning_enabled": False, "append_writes": False, "append_blocks": False,
                        "effective_until": min(item.retained_until for item in all_objects).isoformat(),
                        "provider_readback": {
                            "product_inventory": _inventory_json(pending.products),
                            "catalog_inventory": _inventory_json(inventory),
                        },
                    },
                }
            _require(_json(pending.seal_request["catalog"]) == catalog_json, "seal_changed")
            # Keep original observed evidence across lost SQL responses. A retry
            # may reverify bytes, but cannot rewrite its immutable persisted seal.
            server._verifier.seal_owned_attempt(
                server._target_id, session, reference.attempt_id, **pending.seal_request,
            )

    def _load(self, reference: AttemptReference):
        server = self._actor()
        record = server._control.read_attempt(server._target_id, reference.attempt_id, reference.catalog_digest)
        try:
            catalog = json.loads(record["catalog_json"])
            evidence = json.loads(record["evidence_json"])
            readback = evidence["provider_readback"]
            _require(set(readback) == {"product_inventory", "catalog_inventory"}, "readback_shape")
            products, catalogs = (_inventory(readback[key]) for key in ("product_inventory", "catalog_inventory"))
            _require(
                products.attempt_id == reference.attempt_id
                and catalogs.attempt_id != products.attempt_id and len(catalogs.objects) == 1
                and catalogs.objects[0].logical_name == "catalog.json"
                and catalogs.objects[0].attempt_id == catalogs.attempt_id
                and {item.logical_name for item in products.objects} == set(catalog["products"])
                and len(products.objects) == len(catalog["products"])
                and all(item.attempt_id == products.attempt_id for item in products.objects),
                "persisted_inventory",
            )
            expected_inventory = [
                {**_object(item).as_dict(), "logical_name": item.logical_name} for item in products.objects
            ]
            _require(json.loads(record["inventory_json"]) == expected_inventory, "sql_inventory_substitution")
            for item in products.objects:
                _require(catalog["products"][item.logical_name]["artifact"] == _object(item).as_dict(),
                         "catalog_descriptor_substitution")
            raw = server._artifacts.read_object(catalogs.objects[0])
            _require(
                raw == record["catalog_json"].encode()
                and hashlib.sha256(raw).hexdigest() == reference.catalog_digest
                and catalog["candidate"]["generation_id"] == reference.generation_id,
                "catalog_object_substitution",
            )
            result = record["catalog_json"], {item.logical_name: item for item in products.objects}
            self.__catalogs[reference] = result
            return result
        except (ValueError, KeyError, TypeError):
            raise PublicationSafetyError("sql_blob_broker:persisted_seal_unreadable") from None

    def read_catalog(self, reference: AttemptReference) -> str:
        """Read the exact SQL-pinned physical catalog, with actual Blob reverification."""
        return self._load(reference)[0]

    def read_product(self, reference: AttemptReference, table: str) -> str:
        """Resolve only a member of the exact persisted complete inventory."""
        server = self._actor()
        if reference not in self.__catalogs:
            self._load(reference)
        _require(
            server._control.readable_generation(server._target_id, reference.attempt_id, reference.catalog_digest)
            == reference.generation_id, "readable_generation",
        )
        _, products = self.__catalogs[reference]
        _require(table in products, "product_not_in_seal")
        return server._artifacts.read_object(products[table]).decode()

    def recover_commit(
        self, session, reference, *, expected_revision, operation, request_id, authorization_digest,
    ) -> AttemptControl | None:
        """Recover exact authenticated SQL outcome without artifact/authority rechecks."""
        server = self._actor(session)
        value = server._control.recover_outcome(
            server._target_id, session.owner, session.session_id, session.epoch,
            expected_revision=_revision(expected_revision), attempt_id=reference.attempt_id,
            catalog_digest=reference.catalog_digest, operation=operation,
            authority_digest=authorization_digest, request_id=request_id,
        )
        if value is None:
            return None
        result = self._result(value, reference)
        _require(result.session == session, "outcome_session")
        return result

    def commit(
        self, session, reference, *, expected_revision, operation, request_id, authorization_digest,
    ) -> AttemptControl:
        """Delegate authoritative transition to SQL, never perform client CAS/DML."""
        result = self.recover_commit(
            session, reference, expected_revision=expected_revision, operation=operation,
            request_id=request_id, authorization_digest=authorization_digest,
        )
        if result is not None:
            return result
        server = self._actor(session)
        _require(
            server._control.reference_generation(server._target_id, reference.attempt_id, reference.catalog_digest)
            == reference.generation_id, "reference_generation",
        )
        value = server._control.commit_attempt(
            server._target_id, session.owner, session.session_id, session.epoch,
            expected_revision=_revision(expected_revision), attempt_id=reference.attempt_id,
            catalog_digest=reference.catalog_digest, operation=operation,
            authority_digest=authorization_digest, request_id=request_id,
        )
        result = self._result(value, reference)
        _require(result.session == session, "outcome_session")
        return result

    @staticmethod
    def new_request_id() -> str:
        """Issue a request identity; save exact original pins for ambiguous recovery."""
        return str(uuid4())
