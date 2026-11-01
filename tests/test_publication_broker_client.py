"""Worker-only HTTP tests; local signed transport is not live broker evidence."""

import hashlib
import json
import time
import traceback
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import httpx
import pytest
from azure.core.credentials import AccessToken, TokenCredential
from azure.core.exceptions import ClientAuthenticationError

from fabric.schema_registry import schema_for
from ontology_discovery.immutable_attempt import AttemptReference, AttemptSession
from ontology_discovery.publication_broker_client import (
    BrokerClientError,
    PublicationBrokerClient,
)
from ontology_discovery.publisher import PublicationSafetyError
from tests.test_publication_broker_transport import (
    AUDIENCE,
    OTHER_OWNER,
    OWNER,
    TARGET,
    candidate,
    signing_key,  # noqa: F401
)
from tests.test_publication_broker_transport import env as server_env  # noqa: F401

pytest_plugins = ("tests.test_sql_blob_broker",)

ENDPOINT = "https://publication-broker.example.invalid"
ACCOUNT = (
    "/subscriptions/11111111-1111-1111-1111-111111111111/resourceGroups/publication-rg"
    "/providers/Microsoft.Storage/storageAccounts/exampleartifacts"
)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


@pytest.fixture
def wire(server_env):  # noqa: F811
    original_reference = server_env.boundary._object_reference

    def reference(attempt, table, body):
        return replace(
            original_reference(attempt, table, body),
            account_resource_id=ACCOUNT,
            endpoint="https://exampleartifacts.blob.core.windows.net",
            container="attempts",
        )

    server_env.boundary._object_reference = reference
    requests = []
    lost = set()

    def send(request):
        requests.append(request)
        assert str(request.url).startswith(f"{ENDPOINT}/publication/v1/")
        result = server_env.transport.handle(
            method=request.method,
            path=request.url.raw_path.decode(),
            headers=list(request.headers.multi_items()),
            body=request.content,
        )
        operation = request.url.path.rsplit("/", 1)[-1]
        if operation in lost:
            lost.remove(operation)
            raise httpx.ReadTimeout(
                "secret provider diagnostics ?sig=not-real", request=request
            )
        return httpx.Response(
            result.status,
            content=result.body,
            headers={"content-type": result.content_type},
        )

    credential = Mock(spec=TokenCredential)
    credential.get_token.side_effect = lambda _scope: AccessToken(
        server_env.token(),
        int(time.time()) + 300,
    )
    client = PublicationBrokerClient(
        endpoint=ENDPOINT,
        audience=AUDIENCE,
        expected_target=TARGET,
        worker_object_id=OWNER,
        credential=credential,
        transport=httpx.MockTransport(send),
    )
    yield SimpleNamespace(
        client=client,
        server=server_env,
        requests=requests,
        credential=credential,
        lost=lost,
    )
    client.close()


def staged(wire, products=None):
    control = wire.client.acquire(expected_revision="0")
    attempt = wire.client.allocate_attempt(control.session)
    reference = wire.client.stage(
        control.session,
        attempt_id=attempt,
        candidate=candidate(),
        products=products
        if products is not None
        else {
            "ontology_test_entities": [{"resource_id": "resource"}],
            "ontology_rel_test": [{"confidence": 0.75}],
        },
    )
    return control, reference


def commit_args(control):
    return {
        "expected_revision": control.revision,
        "operation": "admit",
        "request_id": str(uuid4()),
        "authorization_digest": "a" * 64,
    }


def test_actual_signed_transport_roundtrip_uses_only_closed_worker_operations(wire):
    ctl, ref = staged(wire)
    wire.server.boundary.grant(ctl.session, ref, digest="a" * 64)
    accepted = wire.client.commit(ctl.session, ref, **commit_args(ctl))
    assert accepted.active == ref
    assert wire.client.control() == accepted
    assert wire.client.active()[0] == ref
    assert wire.client.read_table(ref, "ontology_rel_test") == [{"confidence": 0.75}]
    assert set(wire.client.read_catalog(ref)["products"]) == {
        "ontology_rel_test",
        "ontology_test_entities",
    }
    allowed = {
        "acquire",
        "allocate",
        "stage",
        "commit",
        "recover",
        "read-control",
        "read-catalog",
        "read-table",
    }
    assert all(r.url.path.rsplit("/", 1)[-1] in allowed for r in wire.requests)
    stages = [r for r in wire.requests if r.url.path.endswith("/stage")]
    assert len(stages) == 1
    assert set(json.loads(stages[0].content)["products"]) == {
        "ontology_rel_test",
        "ontology_test_entities",
    }
    for request in wire.requests:
        body = json.loads(request.content)
        assert "owner" not in body and "target_id" not in body
        if "session" in body:
            assert set(body["session"]) == {"session_id", "epoch"}
        assert request.headers["authorization"].startswith("Bearer ")
    assert {call.args for call in wire.credential.get_token.call_args_list} == {
        (f"{AUDIENCE}/.default",),
    }


def test_explicit_read_only_lost_response_recovery_preserves_original_pins(wire):
    ctl, ref = staged(wire)
    wire.server.boundary.grant(ctl.session, ref, digest="a" * 64)
    pins = commit_args(ctl)
    wire.lost.add("commit")
    with pytest.raises(BrokerClientError, match="transport_failed") as failure:
        wire.client.commit(ctl.session, ref, **pins)
    assert "secret" not in "".join(traceback.format_exception(failure.value))
    assert len([r for r in wire.requests if r.url.path.endswith("/commit")]) == 1
    historical = wire.server.boundary.read_control()
    wire.server.boundary.retention_state = "unlocked"
    wire.server.boundary.now = 100
    wire.server.boundary.takeover(OTHER_OWNER)
    wire.server.boundary.authenticated_principal = OWNER
    before = len(wire.requests)
    assert wire.client.recover_commit(ctl.session, ref, **pins) == historical
    assert len(wire.requests) == before + 1
    assert wire.requests[-1].url.path.endswith("/recover")
    original = json.loads(
        next(r for r in wire.requests if r.url.path.endswith("/commit")).content
    )
    assert json.loads(wire.requests[-1].content) == original
    assert (
        wire.client.recover_commit(
            ctl.session,
            ref,
            **{
                **pins,
                "request_id": str(uuid4()),
            },
        )
        is None
    )
    with pytest.raises(BrokerClientError, match="http_409"):
        wire.client.recover_commit(
            ctl.session,
            ref,
            **{
                **pins,
                "authorization_digest": "b" * 64,
            },
        )


@pytest.mark.parametrize("operation", ["acquire", "allocate", "stage"])
def test_ambiguous_other_mutations_are_not_retried_or_replaced(wire, operation):
    wire.lost.add(operation)
    with pytest.raises(BrokerClientError, match="transport_failed"):
        if operation == "acquire":
            wire.client.acquire(expected_revision="0")
        else:
            ctl = wire.client.acquire(expected_revision="0")
            if operation == "allocate":
                wire.client.allocate_attempt(ctl.session)
            else:
                attempt = wire.client.allocate_attempt(ctl.session)
                wire.client.stage(
                    ctl.session,
                    attempt_id=attempt,
                    candidate=candidate(),
                    products={"ontology_test_entities": []},
                )
    assert len([r for r in wire.requests if r.url.path.endswith(f"/{operation}")]) == 1
    assert not any(r.url.path.endswith("/recover") for r in wire.requests)


@pytest.mark.parametrize("field", sorted(TARGET))
def test_constructor_target_cannot_be_changed_by_stage_body(wire, field):
    value = candidate()
    value["expected_target"][field] = "substitute"
    with pytest.raises(BrokerClientError):
        wire.client.stage(
            AttemptSession(OWNER, 1, str(uuid4())),
            attempt_id=str(uuid4()),
            candidate=value,
            products={"ontology_test_entities": []},
        )
    assert not wire.requests
    wire.credential.get_token.assert_not_called()


@pytest.mark.parametrize(
    "rows",
    [
        [{"unknown": "discarded"}],
        [{"confidence": True}],
        [{"confidence": "0.5"}],
        [{"confidence": [0.5]}],
        [{"confidence": float("inf")}],
        [{"confidence": float("nan")}],
    ],
)
def test_invalid_rows_and_nonfinite_data_reject_before_token_or_http(wire, rows):
    with pytest.raises(PublicationSafetyError):
        wire.client.stage(
            AttemptSession(OWNER, 1, str(uuid4())),
            attempt_id=str(uuid4()),
            candidate=candidate(),
            products={"ontology_rel_test": rows},
        )
    assert not wire.requests
    wire.credential.get_token.assert_not_called()


def test_ordinary_finite_numeric_schema_values_and_sparse_rows_preserved(wire):
    _, ref = staged(
        wire,
        {
            "ontology_rel_test": [
                {"confidence": 1},
                {"confidence": 1.25e-2},
                {},
            ]
        },
    )
    assert wire.client.read_table(ref, "ontology_rel_test") == [
        {"confidence": 1},
        {"confidence": 1.25e-2},
        {},
    ]


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://broker.invalid",
        "https://user:secret@broker.invalid",
        "https://broker.invalid/base",
        "https://broker.invalid?sig=secret",
        "https://broker.invalid#fragment",
        "https://broker.invalid:444",
        "https://BROKER.invalid",
        "https://broker.invalid/\n",
        "https://broker.invalid:bad",
        "file:///tmp/broker",
    ],
)
def test_endpoint_is_https_constructor_owned_origin_without_redirect_target(endpoint):
    with pytest.raises(BrokerClientError, match="endpoint"):
        PublicationBrokerClient(
            endpoint=endpoint,
            audience=AUDIENCE,
            expected_target=TARGET,
            worker_object_id=OWNER,
            credential=Mock(spec=TokenCredential),
        )


def static_client(handler):
    credential = Mock(spec=TokenCredential)
    credential.get_token.return_value = AccessToken(
        "signed.worker.token", int(time.time()) + 300
    )
    requests = []

    def send(request):
        requests.append(request)
        return handler(request)

    client = PublicationBrokerClient(
        endpoint=ENDPOINT,
        audience=AUDIENCE,
        expected_target=TARGET,
        worker_object_id=OWNER,
        credential=credential,
        transport=httpx.MockTransport(send),
    )
    return client, credential, requests


@pytest.mark.parametrize(
    "status", [201, 204, 301, 302, 307, 308, 400, 401, 403, 409, 429, 500]
)
def test_non200_and_redirects_never_follow_or_return_success(status):
    def send(_request):
        return httpx.Response(
            status,
            text="secret upstream diagnostics",
            headers={"location": "https://unreviewed.invalid/capture"},
        )

    client, _, requests = static_client(send)
    try:
        with pytest.raises(BrokerClientError, match=f"http_{status}") as failure:
            client.control()
        assert "secret" not in "".join(traceback.format_exception(failure.value))
        assert (
            len(requests) == 1
            and requests[0].url.host == "publication-broker.example.invalid"
        )
    finally:
        client.close()


@pytest.mark.parametrize(
    "body",
    [
        b"null",
        b"[]",
        b'{"error":"secret"}',
        b'{"result":null}',
        b'{"result":{},"extra":true}',
        b'{"result":{},"result":{}}',
        b'{"result":{"revision":1e999}}',
        b'{"result":{"revision":-1e999}}',
        b'{"result":NaN}',
        b"\xff",
        b"malformed",
    ],
)
def test_malformed_envelopes_and_null_control_never_become_success(body):
    client, _, _ = static_client(
        lambda _: httpx.Response(
            200,
            content=body,
            headers={"content-type": "application/json"},
        )
    )
    try:
        with pytest.raises(BrokerClientError):
            client.control()
    finally:
        client.close()


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"content-type": "text/html"},
        {"content-type": "application/json", "content-encoding": "deflate"},
        {"content-type": "application/json", "content-length": "20000000"},
        {"content-type": "application/json", "content-length": "not-a-number"},
    ],
)
def test_encoding_or_declared_size_invalid_rejects(headers):
    client, _, _ = static_client(
        lambda _: httpx.Response(200, content=b"{}", headers=headers)
    )
    try:
        with pytest.raises(BrokerClientError):
            client.control()
    finally:
        client.close()


def test_actual_chunked_response_size_is_bounded():
    class Huge(httpx.SyncByteStream):
        def __iter__(self):
            for _ in range(17):
                yield b" " * (1024 * 1024)

    client, _, _ = static_client(
        lambda _: httpx.Response(
            200,
            stream=Huge(),
            headers={"content-type": "application/json"},
        )
    )
    try:
        with pytest.raises(BrokerClientError, match="response_size"):
            client.control()
    finally:
        client.close()


@pytest.mark.parametrize("mode", ["error", "expired", "newline", "not-string"])
def test_worker_token_failure_is_sanitized_and_sends_no_request(mode):
    client, credential, requests = static_client(
        lambda _: pytest.fail("HTTP forbidden")
    )
    if mode == "error":
        credential.get_token.side_effect = ClientAuthenticationError(
            "secret token diagnostics"
        )
    else:
        credential.get_token.return_value = SimpleNamespace(
            token="worker\r\nsecret"
            if mode == "newline"
            else 7
            if mode == "not-string"
            else "token",
            expires_on=1 if mode == "expired" else int(time.time()) + 300,
        )
    try:
        with pytest.raises(BrokerClientError) as failure:
            client.control()
        assert "secret" not in "".join(traceback.format_exception(failure.value))
        assert not requests
    finally:
        client.close()


def control_result(owner=OWNER):
    return {
        "session": {"owner": owner, "epoch": 1, "session_id": str(uuid4())},
        "active": None,
        "revision": "1",
    }


@pytest.mark.parametrize(
    "change",
    [
        {"revision": "01"},
        {"revision": True},
        {"revision": "0"},
        {"session": {"owner": OWNER, "epoch": True, "session_id": str(uuid4())}},
        {"session": {"owner": "forged", "epoch": 1, "session_id": str(uuid4())}},
        {
            "active": {
                "attempt_id": "../x",
                "generation_id": "g",
                "catalog_digest": "a" * 64,
            }
        },
    ],
)
def test_control_shapes_are_strict_before_exposure(change):
    value = {**control_result(), **change}
    client, _, _ = static_client(lambda _: httpx.Response(200, json={"result": value}))
    try:
        with pytest.raises(BrokerClientError):
            client.control()
    finally:
        client.close()


def test_acquire_response_owner_is_constructor_worker_not_payload():
    client, _, _ = static_client(
        lambda _: httpx.Response(
            200,
            json={"result": control_result(OTHER_OWNER)},
        )
    )
    try:
        with pytest.raises(BrokerClientError, match="session_owner"):
            client.acquire(expected_revision="0")
    finally:
        client.close()


@pytest.mark.parametrize("operation", ["commit", "recover"])
@pytest.mark.parametrize(
    "change", ["owner", "session", "active", "revision", "null", "extra"]
)
def test_transition_response_must_match_exact_original_request(operation, change):
    session = AttemptSession(OWNER, 1, str(uuid4()))
    reference = AttemptReference(str(uuid4()), "generation", "a" * 64)
    result = {
        "session": {"owner": OWNER, "epoch": 1, "session_id": session.session_id},
        "active": reference.as_dict(),
        "revision": "2",
    }
    if change == "owner":
        result["session"]["owner"] = OTHER_OWNER
    elif change == "session":
        result["session"]["session_id"] = str(uuid4())
    elif change == "active":
        result["active"]["catalog_digest"] = "b" * 64
    elif change == "revision":
        result["revision"] = "9"
    elif change == "null":
        result = None
    else:
        result["extra"] = "not-allowed"
    client, _, _ = static_client(lambda _: httpx.Response(200, json={"result": result}))
    try:
        method = client.commit if operation == "commit" else client.recover_commit
        if operation == "recover" and change == "null":
            assert (
                method(
                    session,
                    reference,
                    expected_revision="1",
                    operation="admit",
                    request_id=str(uuid4()),
                    authorization_digest="c" * 64,
                )
                is None
            )
        else:
            with pytest.raises(BrokerClientError):
                method(
                    session,
                    reference,
                    expected_revision="1",
                    operation="admit",
                    request_id=str(uuid4()),
                    authorization_digest="c" * 64,
                )
    finally:
        client.close()


def catalog_fixture(rows):
    attempt = str(uuid4())
    body = {"rows": rows}
    artifact = {
        "account_resource_id": ACCOUNT,
        "endpoint": "https://exampleartifacts.blob.core.windows.net",
        "container": "attempts",
        "object_name": f"attempts/{attempt}/table.blob",
        "length": len(canonical(body).encode()),
        "content_digest": digest(body),
        "etag": '"pinned-etag"',
        "version_id": None,
    }
    catalog = {
        "protocol": "immutable-attempt/v1",
        "attempt_id": attempt,
        "candidate": candidate(),
        "products": {
            "ontology_rel_test": {
                "rows": len(rows),
                "content_digest": digest(body),
                "arrow_schema_digest": hashlib.sha256(
                    schema_for("ontology_rel_test").serialize()
                ).hexdigest(),
                "artifact": artifact,
            }
        },
    }
    return catalog


@pytest.mark.parametrize(
    "change",
    [
        "target",
        "generation",
        "count",
        "schema",
        "length",
        "content",
        "version",
        "endpoint",
        "account",
        "etag",
        "path",
        "unknown-entry",
        "duplicate-identity",
    ],
)
def test_coherently_hashed_but_invalid_catalogs_or_readbacks_are_rejected(change):
    rows = [{"confidence": 0.5}]
    catalog = catalog_fixture(rows)
    entry = catalog["products"]["ontology_rel_test"]
    if change == "target":
        catalog["candidate"]["expected_target"]["item_id"] = "substitute"
    elif change == "generation":
        catalog["candidate"]["generation_id"] = "other"
    elif change == "count":
        entry["rows"] = 2
    elif change == "schema":
        entry["arrow_schema_digest"] = "b" * 64
    elif change == "length":
        entry["artifact"]["length"] += 1
    elif change == "content":
        rows = [{"confidence": 0.9}]
    elif change == "version":
        entry["artifact"]["version_id"] = "version"
    elif change == "endpoint":
        entry["artifact"]["endpoint"] = "https://exampleevil.blob.core.windows.net"
    elif change == "account":
        entry["artifact"]["account_resource_id"] = "/wrong"
    elif change == "etag":
        entry["artifact"]["etag"] = "unquoted"
    elif change == "path":
        entry["artifact"]["object_name"] = "../production"
    elif change == "unknown-entry":
        entry["extra"] = True
    else:
        catalog["products"]["ontology_rel_duplicate"] = deepcopy(entry)
    ref = AttemptReference(catalog["attempt_id"], "generation", digest(catalog))

    def send(request):
        value = catalog if request.url.path.endswith("/read-catalog") else rows
        return httpx.Response(200, json={"result": value})

    client, _, _ = static_client(send)
    try:
        with pytest.raises(PublicationSafetyError):
            client.read_table(ref, "ontology_rel_test")
    finally:
        client.close()


@pytest.mark.parametrize(
    "rows",
    [
        [{"confidence": "0.5"}],
        [{"confidence": True}],
        [{"confidence": [0.5]}],
        [{"unregistered": "value"}],
    ],
)
def test_core_schema_validation_rejects_coherent_hash_malformed_response_rows(rows):
    catalog = catalog_fixture(rows)
    ref = AttemptReference(catalog["attempt_id"], "generation", digest(catalog))
    client, _, _ = static_client(
        lambda request: httpx.Response(
            200,
            json={
                "result": catalog
                if request.url.path.endswith("/read-catalog")
                else rows
            },
        )
    )
    try:
        with pytest.raises(PublicationSafetyError):
            client.read_table(ref, "ontology_rel_test")
    finally:
        client.close()


def test_closed_client_cannot_reuse_transport_or_credentials():
    client, credential, requests = static_client(lambda _: pytest.fail("closed"))
    client.close()
    with pytest.raises(BrokerClientError, match="closed"):
        client.control()
    assert not requests
    credential.get_token.assert_not_called()


def test_catalog_is_one_high_level_call_without_recursive_product_rpc(wire):
    _, ref = staged(wire)
    wire.requests.clear()
    wire.client.read_catalog(ref)
    assert [r.url.path.rsplit("/", 1)[-1] for r in wire.requests] == ["read-catalog"]
    wire.requests.clear()
    assert wire.client.read_table(ref, "ontology_rel_test") == [{"confidence": 0.75}]
    assert [r.url.path.rsplit("/", 1)[-1] for r in wire.requests] == [
        "read-catalog",
        "read-table",
    ]


def test_mapping_and_sequence_protocol_inputs_are_snapshotted(wire):
    from types import MappingProxyType

    ctl = wire.client.acquire(expected_revision="0")
    attempt = wire.client.allocate_attempt(ctl.session)
    value = candidate()
    value["expected_target"] = MappingProxyType(value["expected_target"])
    ref = wire.client.stage(
        ctl.session,
        attempt_id=attempt,
        candidate=MappingProxyType(value),
        products=MappingProxyType(
            {"ontology_test_entities": (MappingProxyType({"resource_id": "one"}),)}
        ),
    )
    assert wire.client.read_table(ref, "ontology_test_entities") == [
        {"resource_id": "one"}
    ]


@pytest.mark.parametrize(
    "products", [None, [], {"ontology_rel_test": "rows"}, {"ontology_rel_test": [True]}]
)
def test_malformed_stage_shapes_do_not_request_token_or_http(wire, products):
    with pytest.raises(BrokerClientError):
        wire.client.stage(
            AttemptSession(OWNER, 1, str(uuid4())),
            attempt_id=str(uuid4()),
            candidate=candidate(),
            products=products,
        )
    assert not wire.requests
    wire.credential.get_token.assert_not_called()


@pytest.mark.parametrize("operation", ["allocate", "stage", "commit", "recover"])
def test_other_worker_session_cannot_be_submitted_even_to_broker(wire, operation):
    session = AttemptSession(OTHER_OWNER, 1, str(uuid4()))
    ref = AttemptReference(str(uuid4()), "generation", "b" * 64)
    with pytest.raises(BrokerClientError, match="session_owner"):
        if operation == "allocate":
            wire.client.allocate_attempt(session)
        elif operation == "stage":
            wire.client.stage(
                session,
                attempt_id=ref.attempt_id,
                candidate=candidate(),
                products={"ontology_test_entities": []},
            )
        else:
            method = (
                wire.client.commit
                if operation == "commit"
                else wire.client.recover_commit
            )
            method(
                session,
                ref,
                expected_revision="1",
                operation="admit",
                request_id=str(uuid4()),
                authorization_digest="a" * 64,
            )
    assert not wire.requests
    wire.credential.get_token.assert_not_called()


def test_declared_response_length_must_match_actual_complete_bytes():
    client, _, _ = static_client(
        lambda _: httpx.Response(
            200,
            content=b'{"result":null}',
            headers={"content-type": "application/json", "content-length": "0"},
        )
    )
    try:
        with pytest.raises(BrokerClientError, match="response_size"):
            client.control()
    finally:
        client.close()


def test_pristine_control_is_explicit_null_session_without_auto_acquire():
    client, _, requests = static_client(
        lambda _: httpx.Response(
            200, json={"result": {"session": None, "active": None, "revision": "0"}}
        )
    )
    try:
        control = client.control()
        assert (
            control.session is None
            and control.active is None
            and control.revision == "0"
        )
        assert client.active() == (None, None)
        assert all(r.url.path.endswith("/read-control") for r in requests)
    finally:
        client.close()


@pytest.mark.parametrize("operation", ["acquire", "commit", "recover"])
def test_pristine_shape_cannot_masquerade_as_acquired_or_committed_outcome(operation):
    client, _, _ = static_client(
        lambda _: httpx.Response(
            200, json={"result": {"session": None, "active": None, "revision": "0"}}
        )
    )
    try:
        with pytest.raises(BrokerClientError):
            if operation == "acquire":
                client.acquire(expected_revision="0")
            else:
                method = (
                    client.commit if operation == "commit" else client.recover_commit
                )
                method(
                    AttemptSession(OWNER, 1, str(uuid4())),
                    AttemptReference(str(uuid4()), "generation", "b" * 64),
                    expected_revision="1",
                    operation="admit",
                    request_id=str(uuid4()),
                    authorization_digest="a" * 64,
                )
    finally:
        client.close()


@pytest.mark.parametrize(
    "revision,active", [("1", None), (0, None), ("00", None), ("0", {})]
)
def test_null_session_rejects_nonpristine_states(revision, active):
    client, _, _ = static_client(
        lambda _: httpx.Response(
            200,
            json={"result": {"session": None, "active": active, "revision": revision}},
        )
    )
    try:
        with pytest.raises(BrokerClientError, match="pristine_control"):
            client.control()
    finally:
        client.close()


def test_worker_client_real_sql_blob_composition_roundtrip_and_lost_commit(wire, fx):
    from api.auth import EntraJwtAuthenticator
    from api.rbac import Grant
    from ontology_discovery.sql_blob_broker import SqlBlobPublicationBroker
    from tests.test_publication_broker_transport import ROLE, TENANT
    from tests.test_sql_blob_broker import AUTH, RESTORE_AUTH

    auth = EntraJwtAuthenticator(
        tenant_id=TENANT,
        audience=AUDIENCE,
        subject_claim="oid",
        grants_resolver=lambda _owner, roles: (
            (Grant("ontology_maintainer"),) if ROLE.casefold() in roles else ()
        ),
    )
    auth.jwks = wire.server.jwks
    original = fx.service
    server = SqlBlobPublicationBroker(
        control=original._control,
        verifier=original._verifier,
        artifacts=original._artifacts,
        authenticator=auth,
        target_id=fx.db.target_id,
        expected_target=TARGET,
        retain_until=original._retain_until,
        allowed_owners=frozenset({OWNER}),
    )
    fx.db.expected_target = dict(TARGET)
    fx.db.control.update(
        owner_id=None,
        session_id=None,
        epoch=0,
        revision=0,
        active_attempt=None,
        active_digest=None,
    )
    wire.server.transport._factory = server
    assert wire.client.control().session is None
    assert wire.client.active() == (None, None)
    ctl, ref = staged(wire)
    fx.grant(ctl, ref)
    pins = {**commit_args(ctl), "authorization_digest": AUTH}
    wire.lost.add("commit")
    with pytest.raises(BrokerClientError, match="transport_failed"):
        wire.client.commit(ctl.session, ref, **pins)
    before = len(wire.requests)
    accepted = wire.client.recover_commit(ctl.session, ref, **pins)
    assert accepted.active == ref
    assert len(wire.requests) == before + 1
    assert wire.requests[-1].url.path.endswith("/recover")
    assert wire.client.read_table(ref, "ontology_test_entities") == [
        {"resource_id": "resource"}
    ]
    assert wire.client.active()[0] == ref
    fx.grant(accepted, ref, operation="restore")
    restored = wire.client.commit(
        accepted.session,
        ref,
        expected_revision=accepted.revision,
        operation="restore",
        request_id=str(uuid4()),
        authorization_digest=RESTORE_AUTH,
    )
    assert (
        restored.active == ref and int(restored.revision) == int(accepted.revision) + 1
    )
