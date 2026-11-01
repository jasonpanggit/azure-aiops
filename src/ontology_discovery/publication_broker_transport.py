"""Inert closed HTTP codec for a separately composed authenticated broker.

No route, server, credentials, grant APIs or default factory are installed here.
The injected request factory is trusted server composition, never request data.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

import jwt

from api.auth import EntraJwtAuthenticator
from api.errors import ApiError
from api.rbac import Grant
from ontology_discovery.immutable_attempt import (
    AttemptBoundary,
    AttemptControl,
    AttemptReference,
    AttemptSession,
    ImmutableAttemptProtocol,
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
_PATH = "/publication/v1/"
_OPERATIONS = frozenset(
    {
        "acquire",
        "allocate",
        "stage",
        "commit",
        "recover",
        "read-control",
        "read-catalog",
        "read-table",
    }
)
_MAX_BODY = 8 * 1024 * 1024


class BrokerRequestError(ValueError):
    """Closed request contract violation, without request data in diagnostics."""


def _uuid(value: Any) -> str:
    if type(value) is not str:
        raise BrokerRequestError("broker:uuid")
    try:
        normalized = str(UUID(value))
    except ValueError:
        raise BrokerRequestError("broker:uuid") from None
    if value != normalized:
        raise BrokerRequestError("broker:uuid")
    return normalized


def _fields(value: Any, keys: set[str] | frozenset[str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise BrokerRequestError("broker:request_fields")
    return value


def _revision(value: Any) -> str:
    if type(value) is not str or not re.fullmatch(r"0|[1-9][0-9]{0,18}", value):
        raise BrokerRequestError("broker:revision")
    if int(value) > 2**63 - 1:
        raise BrokerRequestError("broker:revision")
    return value


def _digest(value: Any) -> str:
    if type(value) is not str or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise BrokerRequestError("broker:digest")
    return value


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise BrokerRequestError("broker:duplicate_field")
        result[key] = value
    return result


def _invalid_constant(_value: str) -> None:
    raise BrokerRequestError("broker:nonfinite_json")


def _finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise BrokerRequestError("broker:nonfinite_json")
    return parsed


@dataclass(frozen=True)
class ReviewedWorker:
    """One exact reviewed application/object pair; no independent cross-product."""

    application_id: str
    object_id: str

    def __post_init__(self) -> None:
        _uuid(self.application_id)
        _uuid(self.object_id)


@runtime_checkable
class BrokerSessionOperations(Protocol):
    """Composition interface extension; real implementations authenticate again."""

    def acquire(self, *, expected_revision: str, lease_seconds: int) -> AttemptControl:
        """Issue the authenticated caller's server-owned SQL session."""
        ...

    def allocate_attempt(self, session: AttemptSession) -> str:
        """Allocate a private server-owned attempt for this authenticated session."""
        ...


class BrokerRequestFactory(Protocol):
    """Trusted constructor-injected exact-target composition, not a public factory."""

    def for_request(self, headers: Mapping[str, str]) -> AttemptBoundary:
        """Reverify the ORIGINAL bearer and bind every operation to its caller."""
        ...


@dataclass(frozen=True)
class BrokerHttpResponse:
    """JSON HTTP result; serving/routing is deliberately not implemented."""

    status: int
    body: bytes
    content_type: str = "application/json"


def _response(status: int, value: Any) -> BrokerHttpResponse:
    return BrokerHttpResponse(
        status,
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode(),
    )


def _control(value: AttemptControl, owner: str | None = None) -> dict[str, Any]:
    if type(value) is not AttemptControl:
        raise PublicationSafetyError("broker:control_result")
    if value.session is None:
        if owner is not None or value.revision != "0" or value.active is not None:
            raise PublicationSafetyError("broker:control_result")
        return {"session": None, "active": None, "revision": "0"}
    if type(value.session) is not AttemptSession:
        raise PublicationSafetyError("broker:control_result")
    if owner is not None and value.session.owner != owner:
        raise PublicationSafetyError("broker:control_owner")
    return {
        "session": {
            "owner": value.session.owner,
            "epoch": value.session.epoch,
            "session_id": value.session.session_id,
        },
        "active": value.active.as_dict() if value.active is not None else None,
        "revision": value.revision,
    }


class PublicationBrokerTransport:
    """Authenticate and dispatch only fixed operations for one reviewed target.

    This is not an ASGI route or operational broker. Factory credentials and
    effective SQL/Blob permissions must remain outside workers and payloads.
    """

    def __init__(
        self,
        *,
        tenant_id: str,
        audience: str,
        required_role: str,
        expected_target: Mapping[str, str],
        workers: Sequence[ReviewedWorker],
        request_factory: BrokerRequestFactory,
    ) -> None:
        tenant_id = _uuid(tenant_id)
        target = _fields(dict(expected_target), _TARGET_FIELDS)
        if (
            target["tenant_id"] != tenant_id
            or any(type(value) is not str or not value for value in target.values())
            or type(audience) is not str
            or not audience
            or audience != audience.strip()
            or type(required_role) is not str
            or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,127}", required_role)
            or not workers
            or any(type(worker) is not ReviewedWorker for worker in workers)
            or len(set(workers)) != len(workers)
        ):
            raise BrokerRequestError("broker:configuration")
        self._tenant, self._audience, self._role = tenant_id, audience, required_role
        self._target = MappingProxyType(target)
        self._workers = frozenset(workers)
        self._factory = request_factory
        self._auth = EntraJwtAuthenticator(
            tenant_id=tenant_id,
            audience=audience,
            # The legacy verifier requires a Principal grant. This internal
            # compatibility grant is never exposed or used as broker authority.
            grants_resolver=lambda _subject, _roles: (Grant("reader"),),
        )

    def _authenticate(
        self, headers: Sequence[tuple[str, str]]
    ) -> tuple[str, Mapping[str, str]]:
        if not isinstance(headers, (tuple, list)) or len(headers) > 64:
            raise BrokerRequestError("broker:headers")
        folded: dict[str, str] = {}
        for pair in headers:
            if not isinstance(pair, (tuple, list)) or len(pair) != 2:
                raise BrokerRequestError("broker:headers")
            key, value = pair
            if (
                type(key) is not str
                or type(value) is not str
                or not re.fullmatch(r"[A-Za-z0-9!#$%&'*+.^_`|~-]{1,128}", key)
                or len(value) > 16 * 1024
                or "\r" in value
                or "\n" in value
                or key.casefold() in folded
            ):
                raise BrokerRequestError("broker:headers")
            folded[key.casefold()] = value
        authorization = folded.get("authorization", "")
        if len(authorization) > 16 * 1024 or not re.fullmatch(
            r"Bearer [A-Za-z0-9_.-]+", authorization
        ):
            raise BrokerRequestError("broker:bearer")
        original = MappingProxyType({"authorization": authorization})
        token = authorization[len("Bearer ") :]
        # The existing verifier returns Principal, not claims. Verify signed
        # policy claims, then run that verifier on the exact same bearer.
        key = self._auth.jwks.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            key.key,
            algorithms=["RS256"],
            audience=self._audience,
            issuer=self._auth.issuer,
            options={
                "require": [
                    "exp",
                    "iat",
                    "iss",
                    "aud",
                    "tid",
                    "oid",
                    "azp",
                    "idtyp",
                    "ver",
                ]
            },
        )
        roles = claims.get("roles")
        if (
            claims["aud"] != self._audience
            or claims["tid"] != self._tenant
            or claims["idtyp"] != "app"
            or claims["ver"] != "2.0"
            or any(field in claims for field in ("scp", "upn", "preferred_username"))
            or type(roles) is not list
            or any(type(role) is not str for role in roles)
            or self._role not in roles
            or ("appid" in claims and claims["appid"] != claims["azp"])
            or (
                "org_roles" in claims
                and (
                    type(claims["org_roles"]) is not list
                    or any(type(role) is not str for role in claims["org_roles"])
                )
            )
        ):
            raise BrokerRequestError("broker:worker_claims")
        worker = ReviewedWorker(_uuid(claims["azp"]), _uuid(claims["oid"]))
        if worker not in self._workers:
            raise BrokerRequestError("broker:worker_not_reviewed")
        self._auth.authenticate(original)
        return worker.object_id, original

    def handle(
        self,
        *,
        method: str,
        path: str,
        headers: Sequence[tuple[str, str]],
        body: bytes,
    ) -> BrokerHttpResponse:
        """Return a closed JSON response; authentication precedes dependency use."""
        try:
            owner, original = self._authenticate(headers)
        except (ApiError, jwt.PyJWTError, BrokerRequestError):
            return _response(401, {"error": "broker_authentication_refused"})
        if (
            method != "POST"
            or not path.startswith(_PATH)
            or path[len(_PATH) :] not in _OPERATIONS
        ):
            return _response(404, {"error": "broker_operation_not_found"})
        try:
            if type(body) is not bytes or not 0 < len(body) <= _MAX_BODY:
                raise BrokerRequestError("broker:body_size")
            payload = json.loads(
                body,
                object_pairs_hook=_object,
                parse_constant=_invalid_constant,
                parse_float=_finite_float,
            )
            operation = path[len(_PATH) :]
            self._validate(operation, payload, owner)
        except (BrokerRequestError, ValueError, RecursionError):
            return _response(400, {"error": "broker_request_invalid"})
        try:
            boundary = self._factory.for_request(original)
            protocol = ImmutableAttemptProtocol(boundary)
            result = self._dispatch(operation, payload, owner, boundary, protocol)
        except ApiError:
            return _response(401, {"error": "broker_authentication_refused"})
        except PublicationSafetyError:
            return _response(409, {"error": "broker_operation_refused"})
        return _response(200, {"result": result})

    def _session(self, value: Any, owner: str) -> AttemptSession:
        value = _fields(value, {"session_id", "epoch"})
        if type(value["epoch"]) is not int or not 1 <= value["epoch"] <= 2**63 - 1:
            raise BrokerRequestError("broker:epoch")
        return AttemptSession(owner, value["epoch"], _uuid(value["session_id"]))

    def _validate(self, operation: str, payload: Any, owner: str) -> None:
        shapes = {
            "acquire": {"expected_revision", "lease_seconds"},
            "allocate": {"session"},
            "stage": {"session", "attempt_id", "candidate", "products"},
            "commit": {
                "session",
                "reference",
                "expected_revision",
                "operation",
                "request_id",
                "authorization_digest",
            },
            "recover": {
                "session",
                "reference",
                "expected_revision",
                "operation",
                "request_id",
                "authorization_digest",
            },
            "read-control": set(),
            "read-catalog": {"reference"},
            "read-table": {"reference", "table"},
        }
        _fields(payload, shapes[operation])
        if "session" in payload:
            self._session(payload["session"], owner)
        if "expected_revision" in payload:
            _revision(payload["expected_revision"])
        if operation == "acquire":
            lease = payload["lease_seconds"]
            if type(lease) is not int or not 1 <= lease <= 300:
                raise BrokerRequestError("broker:lease")
        if "reference" in payload:
            reference = _fields(
                payload["reference"], {"attempt_id", "generation_id", "catalog_digest"}
            )
            _uuid(reference["attempt_id"])
            _digest(reference["catalog_digest"])
            if type(reference["generation_id"]) is not str or not re.fullmatch(
                r"[A-Za-z0-9_-]{1,128}", reference["generation_id"]
            ):
                raise BrokerRequestError("broker:generation")
        if operation in {"commit", "recover"}:
            if payload["operation"] not in ("admit", "restore"):
                raise BrokerRequestError("broker:operation")
            _uuid(payload["request_id"])
            _digest(payload["authorization_digest"])
        if operation == "read-table" and (
            type(payload["table"]) is not str
            or not re.fullmatch(r"ontology_[a-z0-9_]{1,120}", payload["table"])
        ):
            raise BrokerRequestError("broker:table")
        if operation == "stage":
            _uuid(payload["attempt_id"])
            candidate = _fields(
                payload["candidate"],
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
            if _fields(candidate["expected_target"], _TARGET_FIELDS) != dict(
                self._target
            ):
                raise BrokerRequestError("broker:target")
            if any(
                type(value) is not str or not value
                for key, value in candidate.items()
                if key != "expected_target"
            ):
                raise BrokerRequestError("broker:candidate")
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", candidate["generation_id"]):
                raise BrokerRequestError("broker:generation")
            products = payload["products"]
            if type(products) is not dict or not 1 <= len(products) <= 1024:
                raise BrokerRequestError("broker:products")
            for table, rows in products.items():
                if (
                    not re.fullmatch(r"ontology_[a-z0-9_]{1,120}", table)
                    or type(rows) is not list
                    or any(type(row) is not dict for row in rows)
                ):
                    raise BrokerRequestError("broker:products")

    def _dispatch(
        self,
        operation: str,
        payload: dict[str, Any],
        owner: str,
        boundary: AttemptBoundary,
        protocol: ImmutableAttemptProtocol,
    ) -> Any:
        if operation == "acquire":
            if not isinstance(boundary, BrokerSessionOperations):
                raise PublicationSafetyError("broker:session_operations_unavailable")
            return _control(
                boundary.acquire(
                    expected_revision=payload["expected_revision"],
                    lease_seconds=payload["lease_seconds"],
                ),
                owner,
            )
        if operation == "allocate":
            if not isinstance(boundary, BrokerSessionOperations):
                raise PublicationSafetyError("broker:session_operations_unavailable")
            return {
                "attempt_id": _uuid(
                    boundary.allocate_attempt(self._session(payload["session"], owner))
                )
            }
        if operation == "stage":
            return protocol.stage(
                self._session(payload["session"], owner),
                attempt_id=payload["attempt_id"],
                candidate=payload["candidate"],
                products=payload["products"],
            ).as_dict()
        if operation in {"commit", "recover"}:
            method = (
                protocol.commit if operation == "commit" else protocol.recover_commit
            )
            result = method(
                self._session(payload["session"], owner),
                AttemptReference.parse(payload["reference"]),
                expected_revision=payload["expected_revision"],
                operation=payload["operation"],
                request_id=payload["request_id"],
                authorization_digest=payload["authorization_digest"],
            )
            if result is None:
                if operation != "recover":
                    raise PublicationSafetyError("broker:control_result")
                return None
            return _control(result, owner)
        if operation == "read-control":
            return _control(boundary.read_control())
        reference = AttemptReference.parse(payload["reference"])
        if operation == "read-catalog":
            return protocol.read_catalog(reference)
        return protocol.read_table(reference, payload["table"])
