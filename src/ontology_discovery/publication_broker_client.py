"""Worker HTTP client with no SQL, Blob or publication-authority credentials."""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections.abc import Callable, Mapping, Sequence
from types import MappingProxyType
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from azure.core.credentials import TokenCredential
from azure.core.exceptions import AzureError

from fabric.schema_registry import schema_for
from ontology_discovery.immutable_attempt import (
    AttemptControl,
    AttemptReference,
    AttemptSession,
    _validate_product_rows,
)
from ontology_discovery.publisher import PublicationSafetyError

_TARGET_FIELDS = frozenset(
    {
        "tenant_id",
        "subscription_id",
        "connection_id",
        "workspace_id",
        "item_id",
        "definition_fingerprint",
    }
)
_REQUEST_LIMIT = 8 * 1024 * 1024
_RESPONSE_LIMIT = 16 * 1024 * 1024


class BrokerClientError(PublicationSafetyError):
    """Sanitized broker refusal, invalid response or ambiguous transport failure."""


def _refuse(reason: str) -> None:
    raise BrokerClientError(f"broker_client:{reason}")


def _uuid(value: Any) -> str:
    if type(value) is not str:
        _refuse("uuid")
    try:
        canonical = str(UUID(value))
    except ValueError:
        raise BrokerClientError("broker_client:uuid") from None
    if canonical != value:
        _refuse("uuid")
    return canonical


def _fields(value: Any, keys: set[str] | frozenset[str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        _refuse("fields")
    return value


def _revision(value: Any) -> str:
    if (
        type(value) is not str
        or not re.fullmatch(r"0|[1-9][0-9]{0,18}", value)
        or int(value) > 2**63 - 1
    ):
        _refuse("revision")
    return value


def _hash(value: Any) -> str:
    if type(value) is not str or not re.fullmatch(r"[a-f0-9]{64}", value):
        _refuse("digest")
    return value


def _json(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (ValueError, TypeError, RecursionError):
        raise BrokerClientError("broker_client:json") from None


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _refuse("duplicate_response_field")
        result[key] = value
    return result


def _constant(_value: str) -> None:
    _refuse("nonfinite_response")


def _float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        _refuse("nonfinite_response")
    return parsed


def _reference(value: Any) -> AttemptReference:
    value = _fields(value, {"attempt_id", "generation_id", "catalog_digest"})
    _uuid(value["attempt_id"])
    _hash(value["catalog_digest"])
    if type(value["generation_id"]) is not str or not re.fullmatch(
        r"[A-Za-z0-9_-]{1,128}", value["generation_id"]
    ):
        _refuse("generation")
    return AttemptReference(**value)


class PublicationBrokerClient:
    """High-level protocol-shaped worker client; never an enforcing sink boundary.

    The only credential is a scoped worker token credential for one exact broker.
    Explicit caller retries must retain original request pins. This client never
    retries a mutation or substitutes recovery, latest state or a fresh request.
    """

    def __init__(
        self,
        *,
        endpoint: str,
        audience: str,
        expected_target: Mapping[str, str],
        worker_object_id: str,
        credential: TokenCredential,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if type(endpoint) is not str:
            _refuse("endpoint")
        try:
            parsed = urlsplit(endpoint)
            valid = (
                parsed.scheme == "https"
                and parsed.hostname is not None
                and re.fullmatch(
                    r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", parsed.hostname
                )
                and parsed.username is None
                and parsed.password is None
                and parsed.port in (None, 443)
                and parsed.path in ("", "/")
                and not parsed.query
                and not parsed.fragment
                and endpoint
                in (f"https://{parsed.netloc}", f"https://{parsed.netloc}/")
                and parsed.netloc == parsed.netloc.lower()
            )
        except ValueError:
            valid = False
        if not valid:
            _refuse("endpoint")
        if type(audience) is not str or not re.fullmatch(
            r"(?:api://)?[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            audience,
        ):
            _refuse("audience")
        target = _fields(dict(expected_target), _TARGET_FIELDS)
        if any(type(value) is not str or not value for value in target.values()):
            _refuse("target")
        if isinstance(credential, (str, bytes)) or not callable(
            getattr(credential, "get_token", None)
        ):
            _refuse("worker_token_credential_required")
        self._owner = _uuid(worker_object_id)
        self._target = MappingProxyType(target)
        self._endpoint, self._scope = endpoint.rstrip("/"), f"{audience}/.default"
        self._credential = credential
        self._http = httpx.Client(
            transport=transport
            if transport is not None
            else httpx.HTTPTransport(retries=0),
            follow_redirects=False,
            trust_env=False,
            timeout=httpx.Timeout(30, connect=10),
        )
        self._closed = False

    def close(self) -> None:
        """Close the owned HTTP client and its injected transport."""
        self._closed = True
        self._http.close()

    @property
    def expected_target(self) -> Mapping[str, str]:
        """Return a read-only copy of the exact target pinned at construction."""
        return MappingProxyType(dict(self._target))

    def _rpc(
        self,
        operation: str,
        payload: dict[str, Any],
        *,
        before_send: Callable[[], None] | None = None,
    ) -> Any:
        if self._closed:
            _refuse("closed")
        body = _json(payload).encode()
        if len(body) > _REQUEST_LIMIT:
            _refuse("request_size")
        try:
            access = self._credential.get_token(self._scope)
        except (AzureError, ValueError):
            raise BrokerClientError("broker_client:token_failed") from None
        if (
            type(access.token) is not str
            or not re.fullmatch(r"[A-Za-z0-9_.-]{1,16377}", access.token)
            or type(access.expires_on) not in (int, float)
            or not math.isfinite(access.expires_on)
            or access.expires_on <= time.time()
        ):
            _refuse("token_invalid")
        if before_send is not None:
            before_send()
        try:
            with self._http.stream(
                "POST",
                f"{self._endpoint}/publication/v1/{operation}",
                content=body,
                headers={
                    "Authorization": f"Bearer {access.token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Accept-Encoding": "identity",
                },
            ) as response:
                if response.status_code != 200:
                    _refuse(f"http_{response.status_code}")
                if (
                    response.headers.get("content-type", "")
                    .split(";", 1)[0]
                    .strip()
                    .lower()
                    != "application/json"
                    or response.headers.get("content-encoding", "identity").lower()
                    != "identity"
                ):
                    _refuse("response_encoding")
                length = response.headers.get("content-length")
                if length is not None and (
                    len(length) > 9
                    or not length.isascii()
                    or not length.isdecimal()
                    or int(length) > _RESPONSE_LIMIT
                ):
                    _refuse("response_size")
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > _RESPONSE_LIMIT:
                        _refuse("response_size")
                    chunks.append(chunk)
                if length is not None and size != int(length):
                    _refuse("response_size")
        except httpx.HTTPError:
            # Mutations may already have committed: no implicit retry or recovery.
            raise BrokerClientError("broker_client:transport_failed") from None
        try:
            envelope = json.loads(
                b"".join(chunks),
                object_pairs_hook=_object,
                parse_constant=_constant,
                parse_float=_float,
            )
        except (ValueError, RecursionError):
            raise BrokerClientError("broker_client:response_json") from None
        return _fields(envelope, {"result"})["result"]

    def _session(self, session: AttemptSession) -> dict[str, Any]:
        if type(session) is not AttemptSession or session.owner != self._owner:
            _refuse("session_owner")
        if type(session.epoch) is not int or not 1 <= session.epoch <= 2**63 - 1:
            _refuse("epoch")
        return {"session_id": _uuid(session.session_id), "epoch": session.epoch}

    def _control(self, value: Any) -> AttemptControl:
        value = _fields(value, {"session", "active", "revision"})
        if value["session"] is None:
            if value["revision"] != "0" or value["active"] is not None:
                _refuse("pristine_control")
            return AttemptControl(None, None, "0")
        session = _fields(value["session"], {"owner", "session_id", "epoch"})
        if type(session["epoch"]) is not int or not 1 <= session["epoch"] <= 2**63 - 1:
            _refuse("control_epoch")
        result = AttemptControl(
            AttemptSession(
                _uuid(session["owner"]), session["epoch"], _uuid(session["session_id"])
            ),
            _reference(value["active"]) if value["active"] is not None else None,
            _revision(value["revision"]),
        )
        if int(result.revision) < 1:
            _refuse("control_revision")
        return result

    def control(self) -> AttemptControl:
        """Read one current control snapshot; it does not confer ownership."""
        return self._control(self._rpc("read-control", {}))

    def active(self) -> tuple[AttemptReference | None, dict[str, Any] | None]:
        """Resolve exactly one control reference, never latest-by-generation."""
        value = self.control()
        return value.active, self.read_catalog(
            value.active
        ) if value.active is not None else None

    def acquire(
        self,
        *,
        expected_revision: str,
        lease_seconds: int = 300,
        before_send: Callable[[], None] | None = None,
    ) -> AttemptControl:
        """Acquire the server-issued session for the constructor-pinned worker."""
        revision = _revision(expected_revision)
        if type(lease_seconds) is not int or not 1 <= lease_seconds <= 300:
            _refuse("lease")
        result = self._control(
            self._rpc(
                "acquire",
                {
                    "expected_revision": revision,
                    "lease_seconds": lease_seconds,
                },
                before_send=before_send,
            )
        )
        self._session(result.session)
        if int(result.revision) != int(revision) + 1:
            _refuse("acquire_revision")
        return result

    def allocate_attempt(
        self,
        session: AttemptSession,
        *,
        before_send: Callable[[], None] | None = None,
    ) -> str:
        """Allocate one server-owned attempt; do not retry an ambiguous response."""
        result = _fields(
            self._rpc(
                "allocate",
                {"session": self._session(session)},
                before_send=before_send,
            ),
            {"attempt_id"},
        )
        return _uuid(result["attempt_id"])

    def _candidate(self, value: Any) -> dict[str, Any]:
        value = _fields(
            value,
            {
                "generation_id",
                "source_generation",
                "content_hash",
                "staged_manifest_digest",
                "validation_digest",
                "authorization_digest",
                "attestation_digest",
                "expected_target",
            },
        )
        if (
            _fields(value["expected_target"], _TARGET_FIELDS) != dict(self._target)
            or any(
                type(part) is not str or not part
                for key, part in value.items()
                if key != "expected_target"
            )
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value["generation_id"])
        ):
            _refuse("candidate")
        return value

    @staticmethod
    def _table(table: Any) -> None:
        if type(table) is not str or not re.fullmatch(
            r"ontology_[a-z0-9_]{1,120}", table
        ):
            _refuse("table")

    def stage(
        self,
        session: AttemptSession,
        *,
        attempt_id: str,
        candidate: Mapping[str, Any],
        products: Mapping[str, Sequence[Mapping[str, Any]]],
        before_send: Callable[[], None] | None = None,
    ) -> AttemptReference:
        """Batch the complete product set; no per-product write RPC is available."""
        # Snapshot mutable inputs once, before any token or HTTP call.
        if not isinstance(candidate, Mapping) or not isinstance(products, Mapping):
            _refuse("stage_shape")
        for rows in products.values():
            if (
                not isinstance(rows, Sequence)
                or isinstance(rows, (str, bytes))
                or any(not isinstance(row, Mapping) for row in rows)
            ):
                _refuse("rows")
        candidate_snapshot = dict(candidate)
        if isinstance(candidate_snapshot.get("expected_target"), Mapping):
            candidate_snapshot["expected_target"] = dict(
                candidate_snapshot["expected_target"]
            )
        value = json.loads(
            _json(
                {
                    "candidate": candidate_snapshot,
                    "products": {
                        table: [dict(row) for row in rows]
                        for table, rows in products.items()
                    },
                }
            )
        )
        candidate_value = self._candidate(value["candidate"])
        rows_by_table = value["products"]
        if type(rows_by_table) is not dict or not 1 <= len(rows_by_table) <= 1024:
            _refuse("products")
        for table, rows in rows_by_table.items():
            self._table(table)
            if type(rows) is not list or any(type(row) is not dict for row in rows):
                _refuse("rows")
            _validate_product_rows(table, rows)
        attempt = _uuid(attempt_id)
        reference = _reference(
            self._rpc(
                "stage",
                {
                    "session": self._session(session),
                    "attempt_id": attempt,
                    "candidate": candidate_value,
                    "products": rows_by_table,
                },
                before_send=before_send,
            )
        )
        if (
            reference.attempt_id != attempt
            or reference.generation_id != candidate_value["generation_id"]
        ):
            _refuse("stage_reference")
        catalog = self.read_catalog(reference)
        if catalog["candidate"] != candidate_value or set(catalog["products"]) != set(
            rows_by_table
        ):
            _refuse("stage_catalog")
        for table, rows in rows_by_table.items():
            entry = catalog["products"][table]
            if entry["rows"] != len(rows) or entry["content_digest"] != _digest(
                {"rows": rows}
            ):
                _refuse("stage_content")
        return reference

    def _catalog(self, reference: AttemptReference, value: Any) -> dict[str, Any]:
        catalog = _fields(value, {"protocol", "attempt_id", "candidate", "products"})
        if (
            catalog["protocol"] != "immutable-attempt/v1"
            or catalog["attempt_id"] != reference.attempt_id
            or self._candidate(catalog["candidate"])["generation_id"]
            != reference.generation_id
            or _digest(catalog) != reference.catalog_digest
            or type(catalog["products"]) is not dict
            or not 1 <= len(catalog["products"]) <= 1024
        ):
            _refuse("catalog")
        identities: set[tuple[str, str, str, str]] = set()
        for table, entry in catalog["products"].items():
            self._table(table)
            entry = _fields(
                entry, {"rows", "content_digest", "arrow_schema_digest", "artifact"}
            )
            if type(entry["rows"]) is not int or entry["rows"] < 0:
                _refuse("catalog_rows")
            _hash(entry["content_digest"])
            if (
                _hash(entry["arrow_schema_digest"])
                != hashlib.sha256(schema_for(table).serialize()).hexdigest()
            ):
                _refuse("schema_digest")
            artifact = _fields(
                entry["artifact"],
                {
                    "account_resource_id",
                    "endpoint",
                    "container",
                    "object_name",
                    "length",
                    "content_digest",
                    "etag",
                    "version_id",
                },
            )
            if (
                any(
                    type(artifact[key]) is not str or not artifact[key]
                    for key in (
                        "account_resource_id",
                        "endpoint",
                        "container",
                        "object_name",
                        "etag",
                    )
                )
                or type(artifact["length"]) is not int
                or artifact["length"] < 0
                or artifact["version_id"] is not None
                or _hash(artifact["content_digest"]) != entry["content_digest"]
                or not re.fullmatch(
                    r"/subscriptions/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
                    r"/resourceGroups/[A-Za-z0-9_.()-]{1,90}/providers/Microsoft\.Storage/storageAccounts/[a-z0-9]{3,24}",
                    artifact["account_resource_id"],
                )
                or artifact["endpoint"]
                != (
                    f"https://{artifact['account_resource_id'].rsplit('/', 1)[-1]}.blob.core.windows.net"
                )
                or not re.fullmatch(
                    r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", artifact["container"]
                )
                or artifact["object_name"].startswith("/")
                or any(
                    part in {"", ".", ".."}
                    for part in artifact["object_name"].split("/")
                )
                or any(
                    char in artifact["object_name"]
                    for char in ("?", "#", "%", "\\", "\r", "\n")
                )
                or not re.fullmatch(r'"[^"\r\n]+"', artifact["etag"])
            ):
                _refuse("artifact")
            identity = tuple(
                artifact[key]
                for key in (
                    "account_resource_id",
                    "endpoint",
                    "container",
                    "object_name",
                )
            )
            if identity in identities:
                _refuse("duplicate_artifact")
            identities.add(identity)
        return catalog

    def read_catalog(self, reference: AttemptReference) -> dict[str, Any]:
        """Verify broker-validated catalog identity, target and schema descriptors."""
        reference = _reference(reference.as_dict())
        try:
            return self._catalog(
                reference, self._rpc("read-catalog", {"reference": reference.as_dict()})
            )
        except (KeyError, TypeError, ValueError):
            raise BrokerClientError("broker_client:catalog_invalid") from None

    def read_table(
        self, reference: AttemptReference, table: str
    ) -> list[dict[str, Any]]:
        """Verify exact catalog-pinned table bytes/count/schema before returning rows."""
        reference = _reference(reference.as_dict())
        self._table(table)
        try:
            catalog = self.read_catalog(reference)
            if table not in catalog["products"]:
                _refuse("product_missing")
            rows = self._rpc(
                "read-table", {"reference": reference.as_dict(), "table": table}
            )
            if type(rows) is not list or any(type(row) is not dict for row in rows):
                _refuse("rows")
            entry = catalog["products"][table]
            body = _json({"rows": rows}).encode()
            if (
                len(rows) != entry["rows"]
                or hashlib.sha256(body).hexdigest() != entry["content_digest"]
                or len(body) != entry["artifact"]["length"]
            ):
                _refuse("product_content")
            _validate_product_rows(table, rows)
            return rows
        except (KeyError, TypeError, ValueError):
            raise BrokerClientError("broker_client:table_invalid") from None

    def _transition(
        self,
        rpc: Literal["commit", "recover"],
        session: AttemptSession,
        reference: AttemptReference,
        *,
        expected_revision: str,
        operation: Literal["admit", "restore"],
        request_id: str,
        authorization_digest: str,
        before_send: Callable[[], None] | None = None,
    ) -> AttemptControl | None:
        if operation not in {"admit", "restore"}:
            _refuse("operation")
        pinned = _reference(reference.as_dict())
        revision = _revision(expected_revision)
        result = self._rpc(
            rpc,
            {
                "session": self._session(session),
                "reference": pinned.as_dict(),
                "expected_revision": revision,
                "operation": operation,
                "request_id": _uuid(request_id),
                "authorization_digest": _hash(authorization_digest),
            },
            before_send=before_send,
        )
        if result is None and rpc == "recover":
            return None
        control = self._control(result)
        if (
            control.session != session
            or control.active != pinned
            or int(control.revision) != int(revision) + 1
        ):
            _refuse("transition_result")
        return control

    def commit(
        self,
        session: AttemptSession,
        reference: AttemptReference,
        *,
        expected_revision: str,
        operation: Literal["admit", "restore"],
        request_id: str,
        authorization_digest: str,
        before_send: Callable[[], None] | None = None,
    ) -> AttemptControl:
        """Send exactly one mutation with original pins; never automatically retry."""
        value = self._transition(
            "commit",
            session,
            reference,
            expected_revision=expected_revision,
            operation=operation,
            request_id=request_id,
            authorization_digest=authorization_digest,
            before_send=before_send,
        )
        if value is None:
            _refuse("commit_result")
        return value

    def recover_commit(
        self,
        session: AttemptSession,
        reference: AttemptReference,
        *,
        expected_revision: str,
        operation: Literal["admit", "restore"],
        request_id: str,
        authorization_digest: str,
    ) -> AttemptControl | None:
        """Read only the exact original outcome; null means explicitly absent only."""
        return self._transition(
            "recover",
            session,
            reference,
            expected_revision=expected_revision,
            operation=operation,
            request_id=request_id,
            authorization_digest=authorization_digest,
        )
