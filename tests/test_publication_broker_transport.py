"""Signed offline JWT tests for inert transport; no live identity/provider proof."""

import json
import time
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID, uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from ontology_discovery.immutable_attempt import AttemptSession
from ontology_discovery.publication_broker_transport import (
    BrokerRequestError,
    PublicationBrokerTransport,
    ReviewedWorker,
)
from ontology_discovery.publisher import PublicationSafetyError
from tests.test_immutable_attempt_protocol import BrokerFixture

TENANT = "11111111-1111-1111-1111-111111111111"
APP = "22222222-2222-2222-2222-222222222222"
OWNER = "33333333-3333-3333-3333-333333333333"
OTHER_APP = "44444444-4444-4444-4444-444444444444"
OTHER_OWNER = "55555555-5555-5555-5555-555555555555"
AUDIENCE = "api://66666666-6666-6666-6666-666666666666"
ROLE = "Publication.Worker"
TARGET = {
    "tenant_id": TENANT,
    "subscription_id": "subscription",
    "connection_id": "connection",
    "workspace_id": "workspace",
    "item_id": "item",
    "definition_fingerprint": "fingerprint",
}


@pytest.fixture(scope="module")
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


class Boundary(BrokerFixture):
    """Existing enforcing protocol test fixture with UUID-shaped SQL session pins."""

    def _control(self):
        value = super()._control()
        return replace(
            value,
            session=replace(
                value.session, session_id=str(UUID(int=value.session.epoch))
            ),
        )

    def acquire(self, *, expected_revision, lease_seconds):
        assert 1 <= lease_seconds <= 300
        if self.read_control().revision != expected_revision:
            raise PublicationSafetyError("test:revision")
        return self.takeover(self.authenticated_principal)

    def allocate_attempt(self, session):
        self._owned(session)
        return str(uuid4())


@pytest.fixture
def env(tmp_path, signing_key):
    boundary = Boundary(tmp_path / "broker")
    boundary.authenticated_principal = OWNER
    factory = Mock()
    factory.for_request.return_value = boundary
    transport = PublicationBrokerTransport(
        tenant_id=TENANT,
        audience=AUDIENCE,
        required_role=ROLE,
        expected_target=TARGET,
        workers=[ReviewedWorker(APP, OWNER)],
        request_factory=factory,
    )
    jwks = Mock()
    jwks.get_signing_key_from_jwt.return_value = SimpleNamespace(
        key=signing_key.public_key()
    )
    transport._auth.jwks = jwks

    def token(changes=None, *, remove=(), key=signing_key, algorithm="RS256"):
        claims = {
            "iss": f"https://login.microsoftonline.com/{TENANT}/v2.0",
            "aud": AUDIENCE,
            "tid": TENANT,
            "ver": "2.0",
            "idtyp": "app",
            "azp": APP,
            "oid": OWNER,
            "sub": "not-an-owner",
            "roles": [ROLE],
            "iat": int(time.time()) - 5,
            "exp": int(time.time()) + 300,
        }
        claims.update(changes or {})
        for field in remove:
            claims.pop(field, None)
        return jwt.encode(claims, key, algorithm=algorithm)

    def request(
        operation="read-control",
        payload=None,
        *,
        bearer=None,
        headers=(),
        raw=None,
        **kwargs,
    ):
        authorization = f"Bearer {token() if bearer is None else bearer}"
        return transport.handle(
            method=kwargs.get("method", "POST"),
            path=kwargs.get("path", f"/publication/v1/{operation}"),
            headers=[("Authorization", authorization), *headers],
            body=json.dumps({} if payload is None else payload).encode()
            if raw is None
            else raw,
        )

    return SimpleNamespace(
        boundary=boundary,
        factory=factory,
        transport=transport,
        token=token,
        request=request,
        jwks=jwks,
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"aud": "wrong"},
        {"aud": AUDIENCE.removeprefix("api://")},
        {"aud": [AUDIENCE]},
        {"tid": OTHER_OWNER},
        {"iss": "https://login.microsoftonline.com/evil/v2.0"},
        {"exp": 1},
        {"iat": int(time.time()) + 3600},
        {"nbf": int(time.time()) + 3600},
        {"azp": OTHER_APP},
        {"oid": OTHER_OWNER},
        {"oid": "not-uuid"},
        {"azp": ["not-a-string"]},
        {"oid": None},
        {"idtyp": "user"},
        {"ver": "1.0"},
        {"scp": "Publication.Write"},
        {"scp": ""},
        {"upn": "caller@example.invalid"},
        {"preferred_username": OWNER},
        {"roles": []},
        {"roles": [ROLE.lower()]},
        {"roles": ROLE},
        {"roles": [3]},
        {"appid": OTHER_APP},
        {"org_roles": 5},
        {"org_roles": [None]},
    ],
)
def test_wrong_or_unsupported_signed_claims_reject_before_boundary(env, changes):
    response = env.request(bearer=env.token(changes))
    assert response.status == 401
    assert b"broker_authentication_refused" in response.body
    env.factory.for_request.assert_not_called()


@pytest.mark.parametrize(
    "field", ["exp", "iat", "iss", "aud", "tid", "oid", "azp", "idtyp", "ver"]
)
def test_required_claim_omission_cannot_reach_dependency(env, field):
    assert env.request(bearer=env.token(remove=[field])).status == 401
    env.factory.for_request.assert_not_called()


def test_signature_failure_and_algorithm_substitution_reject_before_boundary(
    env, signing_key
):
    wrong = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert env.request(bearer=env.token(key=wrong)).status == 401
    assert (
        env.request(
            bearer=env.token(key="not-an-rsa-key" * 4, algorithm="HS256")
        ).status
        == 401
    )
    valid = env.token()
    unsigned = jwt.encode(
        jwt.decode(valid, options={"verify_signature": False}), key="", algorithm="none"
    )
    assert env.request(bearer=unsigned).status == 401
    env.factory.for_request.assert_not_called()


def test_actual_repository_authenticator_is_used_and_never_header_assertion(
    env, monkeypatch
):
    authenticate = Mock(wraps=env.transport._auth.authenticate)
    monkeypatch.setattr(env.transport._auth, "authenticate", authenticate)
    bearer = env.token()
    response = env.request(
        bearer=bearer,
        headers=[
            ("x-ms-client-principal-name", OTHER_OWNER),
            ("x-aiops-gateway-assertion", "forged"),
            ("x-owner-id", OTHER_OWNER),
        ],
    )
    assert response.status == 200
    expected = {"authorization": f"Bearer {bearer}"}
    assert dict(authenticate.call_args.args[0]) == expected
    assert dict(env.factory.for_request.call_args.args[0]) == expected
    with pytest.raises(TypeError):
        env.factory.for_request.call_args.args[0]["authorization"] = "replacement"
    assert env.jwks.get_signing_key_from_jwt.call_count == 2


def test_same_app_and_object_sets_do_not_authorize_unreviewed_cross_pair(env):
    env.transport._workers = frozenset(
        {
            ReviewedWorker(APP, OWNER),
            ReviewedWorker(OTHER_APP, OTHER_OWNER),
        }
    )
    assert env.request(bearer=env.token({"azp": APP, "oid": OTHER_OWNER})).status == 401
    env.factory.for_request.assert_not_called()


@pytest.mark.parametrize(
    "headers",
    [
        [],
        [("x-ms-client-principal-name", OWNER)],
        [("authorization", "Bearer")],
        [("authorization", "Basic secret")],
        [("authorization", "Bearer token\r\ninjected")],
        [("authorization", "Bearer a"), ("Authorization", "Bearer b")],
    ],
)
def test_missing_malformed_duplicate_auth_and_gateway_only_reject(env, headers):
    response = env.transport.handle(
        method="POST", path="/publication/v1/read-control", headers=headers, body=b"{}"
    )
    assert response.status == 401
    env.factory.for_request.assert_not_called()


@pytest.mark.parametrize(
    "operation",
    [
        "seal",
        "grant",
        "revoke",
        "sql",
        "credentials",
        "provision",
        "delete",
        "read-control?target=evil",
        "../read-control",
        "READ-CONTROL",
    ],
)
def test_unknown_operation_cannot_reach_dependency(env, operation):
    assert env.request(operation).status == 404
    env.factory.for_request.assert_not_called()


@pytest.mark.parametrize(
    "raw",
    [
        b"[]",
        b"null",
        b'{"owner":"spoof"}',
        b'{"x":1,"x":2}',
        b'{"x":NaN}',
        b"not-json",
        b"\xff",
        b"",
        b"[" * 1500,
    ],
)
def test_invalid_closed_json_rejects_before_boundary(env, raw):
    assert env.request(raw=raw).status == 400
    env.factory.for_request.assert_not_called()


def test_size_and_method_bounds_reject_before_dependency(env):
    assert env.request(raw=b" " * (8 * 1024 * 1024 + 1)).status == 400
    assert env.request(method="GET").status == 404
    env.factory.for_request.assert_not_called()


def acquire(env):
    response = env.request("acquire", {"expected_revision": "0", "lease_seconds": 300})
    assert response.status == 200
    control = json.loads(response.body)["result"]
    assert control["session"]["owner"] == OWNER
    assert control["session"]["session_id"] != OWNER
    return {
        "epoch": control["session"]["epoch"],
        "session_id": control["session"]["session_id"],
    }


def candidate():
    return {
        "generation_id": "generation",
        "source_generation": "source",
        "content_hash": "content",
        "staged_manifest_digest": "staged",
        "validation_digest": "validation",
        "authorization_digest": "a" * 64,
        "attestation_digest": "attestation",
        "expected_target": deepcopy(TARGET),
    }


def test_acquire_allocate_stage_commit_read_and_recover_use_closed_core(env):
    session = acquire(env)
    allocated = env.request("allocate", {"session": session})
    attempt = json.loads(allocated.body)["result"]["attempt_id"]
    UUID(attempt)
    staged = env.request(
        "stage",
        {
            "session": session,
            "attempt_id": attempt,
            "candidate": candidate(),
            "products": {"ontology_entities": []},
        },
    )
    assert staged.status == 200
    reference = json.loads(staged.body)["result"]
    from ontology_discovery.immutable_attempt import AttemptReference

    pinned = AttemptReference.parse(reference)
    actual_session = AttemptSession(OWNER, session["epoch"], session["session_id"])
    env.boundary.grant(actual_session, pinned, digest="a" * 64)
    args = {
        "session": session,
        "reference": reference,
        "operation": "admit",
        "expected_revision": "1",
        "request_id": str(uuid4()),
        "authorization_digest": "a" * 64,
    }
    committed = env.request("commit", args)
    assert committed.status == 200
    historical = json.loads(committed.body)["result"]
    assert historical["active"] == reference and historical["revision"] == "2"
    assert env.request("read-catalog", {"reference": reference}).status == 200
    read = env.request(
        "read-table", {"reference": reference, "table": "ontology_entities"}
    )
    assert json.loads(read.body)["result"] == []
    env.boundary.retention_state = "unlocked"
    env.boundary.now = 100
    recovered = env.request("recover", args)
    assert json.loads(recovered.body)["result"] == historical
    assert env.request("commit", args).body == committed.body
    assert env.request("read-catalog", {"reference": reference}).status == 409
    assert json.loads(
        env.request("recover", {**args, "request_id": str(uuid4())}).body
    ) == {"result": None}
    assert env.request("commit", {**args, "request_id": str(uuid4())}).status == 409


@pytest.mark.parametrize(
    "change",
    [
        {"owner": OTHER_OWNER},
        {"target": TARGET},
        {"epoch": True},
        {"epoch": 0},
        {"session_id": "arbitrary"},
    ],
)
def test_session_body_cannot_assert_owner_or_target(env, change):
    session = acquire(env)
    env.factory.reset_mock()
    assert env.request("allocate", {"session": {**session, **change}}).status == 400
    env.factory.for_request.assert_not_called()


@pytest.mark.parametrize("field", sorted(TARGET))
def test_stage_cannot_retarget_any_constructor_owned_target_field(env, field):
    value = candidate()
    value["expected_target"][field] = "substitute"
    response = env.request(
        "stage",
        {
            "session": {"session_id": str(uuid4()), "epoch": 1},
            "attempt_id": str(uuid4()),
            "candidate": value,
            "products": {"ontology_entities": []},
        },
    )
    assert response.status == 400
    env.factory.for_request.assert_not_called()


def test_stale_session_and_wrong_revision_refuse_without_new_owner_pointer(env):
    session = acquire(env)
    assert (
        env.request("acquire", {"expected_revision": "0", "lease_seconds": 30}).status
        == 409
    )
    env.boundary.takeover(OTHER_OWNER)
    env.boundary.authenticated_principal = OWNER
    assert env.request("allocate", {"session": session}).status == 409
    assert env.boundary.read_control().active is None


def test_transport_does_not_convert_dependency_infrastructure_error_to_success(env):
    env.factory.for_request.side_effect = TimeoutError("test-only transport timeout")
    with pytest.raises(TimeoutError):
        env.request()


@pytest.mark.parametrize(
    "headers",
    [
        "Authorization: Bearer forged",
        {"Authorization": "Bearer forged"},
        [("only-one",)],
        [("authorization", "Bearer a", "extra")],
        [(1, "Bearer a")],
        [("invalid header", "value")],
        [("x-identity", "value\nowner")],
    ],
)
def test_malformed_header_container_cannot_escape_auth_refusal(env, headers):
    response = env.transport.handle(
        method="POST",
        path="/publication/v1/read-control",
        headers=headers,
        body=b"{}",
    )
    assert response.status == 401
    env.factory.for_request.assert_not_called()


@pytest.mark.parametrize(
    "revision,lease",
    [
        ("-1", 10),
        ("01", 10),
        ("9223372036854775808", 10),
        (1, 10),
        ("0", 0),
        ("0", 301),
        ("0", True),
    ],
)
def test_invalid_revision_or_lease_rejects_before_boundary(env, revision, lease):
    assert (
        env.request(
            "acquire", {"expected_revision": revision, "lease_seconds": lease}
        ).status
        == 400
    )
    env.factory.for_request.assert_not_called()


def test_dependency_cannot_return_another_workers_session_as_this_callers_result(env):
    value = env.boundary.takeover(OTHER_OWNER)
    env.boundary.acquire = Mock(return_value=value)
    response = env.request("acquire", {"expected_revision": "1", "lease_seconds": 30})
    assert response.status == 409
    assert OTHER_OWNER.encode() not in response.body


def test_read_only_request_cannot_smuggle_session_or_sql_arguments(env):
    for payload in [
        {"owner": OWNER},
        {"target_id": str(uuid4())},
        {"sql": "SELECT 1"},
        {"grant": True},
        {"session": {"session_id": str(uuid4()), "epoch": 1}},
    ]:
        assert env.request("read-control", payload).status == 400
    env.factory.for_request.assert_not_called()


@pytest.mark.parametrize("number", ["1e999", "-1e999"])
@pytest.mark.parametrize("nested", [False, True])
def test_exponent_overflow_rejected_before_composition(env, number, nested):
    session = acquire(env)
    env.factory.reset_mock()
    value = {"confidence": "NUMBER"}
    row = {"payload_json": {"nested": [value]}} if nested else value
    raw = (
        json.dumps(
            {
                "session": session,
                "attempt_id": str(uuid4()),
                "candidate": candidate(),
                "products": {"ontology_rel_test": [row]},
            }
        )
        .replace('"NUMBER"', number)
        .encode()
    )
    assert env.request("stage", raw=raw).status == 400
    env.factory.for_request.assert_not_called()


@pytest.mark.parametrize("number", ["1e2", "-1e2", "1.25e-2", "1e308"])
def test_finite_exponents_remain_valid_json_numbers(env, number):
    session = acquire(env)
    env.factory.reset_mock()
    raw = (
        json.dumps(
            {
                "session": session,
                "attempt_id": str(uuid4()),
                "candidate": candidate(),
                "products": {"ontology_rel_test": [{"confidence": "NUMBER"}]},
            }
        )
        .replace('"NUMBER"', number)
        .encode()
    )
    assert env.request("stage", raw=raw).status == 200
    env.factory.for_request.assert_called_once()


def test_request_validation_and_auth_cannot_mutate_original_config(env):
    assert env.transport._target == TARGET
    with pytest.raises(TypeError):
        env.transport._target["tenant_id"] = OTHER_OWNER
    with pytest.raises(BrokerRequestError):
        ReviewedWorker("bad-app", OWNER)


def test_no_serving_route_default_factory_or_privileged_surface():
    import inspect

    import ontology_discovery.publication_broker_transport as module

    source = inspect.getsource(module)
    for forbidden in (
        "FastAPI",
        "APIRouter",
        "add_api_route",
        "uvicorn",
        "SqlPublicationVerifier",
        "SqlPublicationAuthority",
        "pyodbc",
        "DefaultAzureCredential",
    ):
        assert forbidden not in source
    assert not hasattr(PublicationBrokerTransport, "record_grant")
    assert not hasattr(PublicationBrokerTransport, "seal_attempt")
