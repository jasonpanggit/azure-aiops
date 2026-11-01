"""Narrow compatibility with the composition's explicit pristine SQL state."""

import json

import pytest

from ontology_discovery.immutable_attempt import (
    AttemptControl,
    AttemptReference,
    ImmutableAttemptProtocol,
)

pytest_plugins = ("tests.test_publication_broker_transport",)


def test_authenticated_pristine_read_control_never_acquires_or_fabricates_session(env):
    env.boundary.read_control = lambda: AttemptControl(None, None, "0")
    before = env.factory.for_request.call_count
    result = env.request("read-control", {})
    assert result.status == 200
    assert json.loads(result.body) == {
        "result": {"session": None, "active": None, "revision": "0"}
    }
    assert env.factory.for_request.call_count == before + 1


@pytest.mark.parametrize(
    "revision,active",
    [
        ("1", None),
        (0, None),
        ("00", None),
        ("0", AttemptReference("attempt", "generation", "b" * 64)),
    ],
)
def test_null_session_is_not_an_arbitrary_control_state(env, revision, active):
    env.boundary.read_control = lambda: AttemptControl(None, active, revision)
    assert env.request("read-control", {}).status == 409


def test_acquire_must_never_return_pristine_control(env):
    env.boundary.acquire = lambda **_: AttemptControl(None, None, "0")
    assert (
        env.request("acquire", {"expected_revision": "0", "lease_seconds": 300}).status
        == 409
    )


@pytest.mark.parametrize("operation", ["commit", "recover"])
def test_present_outcome_requires_owner_session_even_if_pristine_shaped(
    env, monkeypatch, operation
):
    method = "commit" if operation == "commit" else "recover_commit"
    monkeypatch.setattr(
        ImmutableAttemptProtocol,
        method,
        lambda *_args, **_kwargs: AttemptControl(None, None, "0"),
    )
    payload = {
        "session": {"session_id": "11111111-1111-1111-1111-111111111111", "epoch": 1},
        "reference": {
            "attempt_id": "22222222-2222-2222-2222-222222222222",
            "generation_id": "generation",
            "catalog_digest": "b" * 64,
        },
        "expected_revision": "1",
        "operation": "admit",
        "request_id": "33333333-3333-3333-3333-333333333333",
        "authorization_digest": "a" * 64,
    }
    assert env.request(operation, payload).status == 409


@pytest.mark.parametrize("operation,status", [("commit", 409), ("recover", 200)])
def test_only_absent_recovery_may_have_null_result(env, monkeypatch, operation, status):
    method = "commit" if operation == "commit" else "recover_commit"
    monkeypatch.setattr(
        ImmutableAttemptProtocol, method, lambda *_args, **_kwargs: None
    )
    payload = {
        "session": {"session_id": "11111111-1111-1111-1111-111111111111", "epoch": 1},
        "reference": {
            "attempt_id": "22222222-2222-2222-2222-222222222222",
            "generation_id": "generation",
            "catalog_digest": "b" * 64,
        },
        "expected_revision": "1",
        "operation": "admit",
        "request_id": "33333333-3333-3333-3333-333333333333",
        "authorization_digest": "a" * 64,
    }
    result = env.request(operation, payload)
    assert result.status == status
    if operation == "recover":
        assert json.loads(result.body) == {"result": None}
