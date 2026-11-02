"""Combined explicit remote context using fake DFS and the existing closed HTTP."""

import json
from dataclasses import replace
from unittest.mock import Mock

import pytest

from ontology_discovery.attempt_projection import (
    ImmutableLogicalProjectionPolicy,
    LogicalProduct,
    ReadOnlyAttemptProjector,
)
from ontology_discovery.immutable_attempt import AttemptReference
from ontology_discovery.immutable_attempt_worker import AttemptLifecycleConflict
from ontology_discovery.publication_broker_client import (
    BrokerClientError,
    PublicationBrokerClient,
)
from ontology_discovery.publisher import PublicationSafetyError
from ontology_discovery.remote_attempt_context import remote_immutable_attempt_context
from tests import test_attempt_document_credentials as documents
from tests import test_immutable_attempt_worker as lifecycle
from tests.test_immutable_attempt_composition import TrackingTransport
from tests.test_immutable_attempt_worker import server_env  # noqa: F401
from tests.test_publication_broker_client import AUDIENCE, ENDPOINT, OWNER

pytest_plugins = (
    "tests.test_publication_broker_transport",
    "tests.test_publication_broker_client",
    "tests.test_attempt_document_credentials",
)


@pytest.fixture
def remote_inputs(tmp_path, monkeypatch, wire, sdk):
    env, local, client, candidate, restores, clients = lifecycle._compose(
        tmp_path, monkeypatch, wire
    )
    expected = local._output_policies[0]
    policy = ImmutableLogicalProjectionPolicy(
        expected.context,
        tuple(
            LogicalProduct(
                table.logical_name,
                table.arrow_schema_digest,
                table.row_count,
                table.content_digest,
            )
            for table in expected.manifest.tables
        ),
    )
    # Copy existing qualified staged artifacts, not a second publisher/server.
    staged = local._storage.read_generation(candidate.generation_id)
    for name in (
        "entities",
        "relationships",
        "manifest",
        "validation",
    ):
        payload = staged[name]
        if name in {"entities", "relationships"}:
            payload = {"records": payload}
        path = f"{documents.ITEM}/Files/staged/generations/{candidate.generation_id}/{name}.json"
        sdk.bodies[path] = json.dumps(payload).encode()
    for name in ("lineage", "compatibility"):
        path = f"{documents.ITEM}/Files/staged/generations/{candidate.generation_id}/{name}.json"
        sdk.bodies[path] = b"{}"
    wire.credential.close = Mock()
    target = dict(client.expected_target)
    values = {
        **documents.options(),
        "endpoint": ENDPOINT,
        "audience": AUDIENCE,
        "worker_object_id": OWNER,
        "credential_owner_object_id": OWNER,
        "credential": wire.credential,
        "expected_target": target,
        "dispatch_id": "explicit-remote-context",
        "authorizer": local._authorizer,
        "definition_fingerprint": lambda: target["definition_fingerprint"],
        "policies": (policy,),
        "transport": TrackingTransport(client._http._transport),
    }
    original_commit = PublicationBrokerClient.commit

    def authorized_commit(self, session, reference, **kwargs):
        wire.server.boundary.grant(
            session,
            reference,
            operation=kwargs["operation"],
            digest=kwargs["authorization_digest"],
        )
        return original_commit(self, session, reference, **kwargs)

    monkeypatch.setattr(PublicationBrokerClient, "commit", authorized_commit)
    try:
        yield values, candidate, env, restores
    finally:
        for value in clients:
            value.close()


def new_transport(values):
    values["transport"] = TrackingTransport(values["transport"].delegate)


def assert_borrowed_credentials(values):
    for name in ("credential", "staged_credential", "journal_credential"):
        assert not values[name].close.called


def test_actual_combined_remote_lifecycle_cleanup_and_restart(remote_inputs, wire, sdk):
    values, candidate, env, _restores = remote_inputs
    with remote_immutable_attempt_context(**values) as worker:
        assert wire.requests == sdk.calls == []
        assert isinstance(worker._materializer, ReadOnlyAttemptProjector)
        assert not hasattr(worker._materializer._storage, "write")
        assert not hasattr(worker._materializer, "_service")
        result = worker.publish(candidate)
        assert result.state == "acknowledged"
    assert values["transport"].closed
    assert len(sdk.clients) == 2
    assert all(value.closed == 1 for value in sdk.clients)
    assert_borrowed_credentials(values)
    assert env.sink.calls == env.catalogs == []
    for operation, path, owner in (call for call in sdk.calls if call[0] != "client"):
        if "/staged/" in path:
            assert operation == "read"
            assert owner is values["staged_credential"]
        else:
            assert "/journal/" in path
            assert owner is values["journal_credential"]
    before = len(wire.requests)
    new_transport(values)
    with remote_immutable_attempt_context(**values) as restarted:
        assert restarted.publish(candidate).record == result.record
        changed = replace(candidate, policy_version="changed")
        with pytest.raises(AttemptLifecycleConflict, match="candidate_digest"):
            restarted.publish(changed)
    assert len(wire.requests) == before
    with pytest.raises(BrokerClientError, match="closed"):
        worker._client.control()
    with pytest.raises(RuntimeError, match="closed"):
        worker._journal.read(values["dispatch_id"])


@pytest.mark.parametrize(
    ("invalid", "error", "owned"),
    [
        ("owner", "credential_owner_mismatch", False),
        ("worker", "uuid", False),
        ("endpoint", "endpoint", False),
        ("audience", "audience", False),
        ("credential", "credential", False),
        ("target", "fields", False),
        ("policy_target", "trusted_binding", True),
        ("overlap", "disjoint", False),
        ("root", "canonical", False),
        ("storage_owner", "distinct", False),
        ("storage_credential", "credential", False),
        ("authority", "trusted_binding", True),
        ("definition", "trusted_binding", True),
        ("dispatch", "dispatch", True),
        ("lease", "lease", True),
    ],
)
def test_invalid_bindings_refuse_pretransport(
    remote_inputs, wire, sdk, invalid, error, owned
):
    values, _candidate, _env, _restores = remote_inputs
    if invalid == "owner":
        values["credential_owner_object_id"] = "different"
    elif invalid == "worker":
        values["worker_object_id"] = values["credential_owner_object_id"] = "invalid"
    elif invalid == "endpoint":
        values["endpoint"] = "http://untrusted.invalid"
    elif invalid == "audience":
        values["audience"] = "invalid"
    elif invalid == "credential":
        values["credential"] = None
    elif invalid == "target":
        values["expected_target"] = {"item_id": "incomplete"}
    elif invalid == "policy_target":
        values["expected_target"] = {**values["expected_target"], "item_id": "changed"}
    elif invalid == "overlap":
        values["journal_root"] = values["staged_root"] + "/child"
    elif invalid == "root":
        values["staged_root"] += "/../alias"
    elif invalid == "storage_owner":
        values["journal_owner_object_id"] = values["staged_owner_object_id"]
    elif invalid == "storage_credential":
        values["journal_credential"] = None
    elif invalid == "authority":
        values["authorizer"] = None
    elif invalid == "definition":
        values["definition_fingerprint"] = None
    elif invalid == "dispatch":
        values["dispatch_id"] = ""
    else:
        values["lease_seconds"] = 301
    with (
        pytest.raises((ValueError, TypeError, PublicationSafetyError), match=error),
        remote_immutable_attempt_context(**values),
    ):
        pytest.fail("invalid inputs yielded a worker")
    assert wire.requests == sdk.calls == []
    assert not wire.credential.get_token.called
    assert values["transport"].closed is owned
    assert not values["staged_credential"].get_token.called


def test_body_failure_after_client_use_closes_resources(remote_inputs, sdk):
    values, candidate, _env, _restores = remote_inputs
    with (
        pytest.raises(RuntimeError, match="application stopped"),
        remote_immutable_attempt_context(**values) as worker,
    ):
        worker.publish(candidate)
        raise RuntimeError("application stopped")
    assert all(value.closed == 1 for value in sdk.clients)
    assert values["transport"].closed
    assert_borrowed_credentials(values)


@pytest.mark.parametrize("operation", ["allocate", "stage"])
def test_unknown_mutation_persists_hold_and_target_owner_across_restart(
    remote_inputs, wire, sdk, operation
):
    values, candidate, _env, _restores = remote_inputs
    wire.lost.add(operation)
    with (
        remote_immutable_attempt_context(**values) as worker,
        pytest.raises(BrokerClientError, match="transport_failed"),
    ):
        worker.publish(candidate)
    before = len(wire.requests)
    new_transport(values)
    with remote_immutable_attempt_context(**values) as restarted:
        assert restarted.publish(candidate).state == "held"
        snapshot = restarted._journal.read_target(values["expected_target"])
        stale = {**snapshot.record, "revision": snapshot.revision + 1}
        with pytest.raises(AttemptLifecycleConflict, match="revision"):
            restarted._journal.replace_target(
                stale, expected_revision=snapshot.revision - 1
            )
    values["dispatch_id"] = "competing-remote-dispatch"
    new_transport(values)
    with (
        remote_immutable_attempt_context(**values) as competitor,
        pytest.raises(AttemptLifecycleConflict, match="target.*dispatch"),
    ):
        competitor.publish(candidate)
    assert len(wire.requests) == before
    assert all(value.closed == 1 for value in sdk.clients)
    assert_borrowed_credentials(values)


def test_exact_recovery_and_independent_restore_authority(remote_inputs, wire):
    values, candidate, _env, restores = remote_inputs
    wire.lost.add("commit")
    with remote_immutable_attempt_context(**values) as worker:
        result = worker.publish(candidate)
        assert result.state == "historical_recovery"
    commits = [
        json.loads(request.content)
        for request in wire.requests
        if request.url.path.endswith("/commit")
    ]
    recoveries = [
        json.loads(request.content)
        for request in wire.requests
        if request.url.path.endswith("/recover")
    ]
    assert recoveries == commits
    reference = AttemptReference.parse(result.record["reference"])
    values["dispatch_id"] = "independent-restore"
    new_transport(values)
    with remote_immutable_attempt_context(**values) as restoring:
        assert restoring.restore(reference).state == "acknowledged"
    assert restores
    before = len(wire.requests)

    def denied(**_kwargs):
        raise PublicationSafetyError("current restore denied")

    values["authorizer"].authorize_restore = denied
    values["dispatch_id"] = "denied-restore"
    new_transport(values)
    with (
        remote_immutable_attempt_context(**values) as restoring,
        pytest.raises(PublicationSafetyError, match="restore denied"),
    ):
        restoring.restore(reference)
    assert "commit" not in lifecycle._ops(wire)[before:]


def test_no_fallback_after_staged_authentication_failure(remote_inputs, wire, sdk):
    from azure.core.exceptions import ClientAuthenticationError

    values, candidate, _env, _restores = remote_inputs
    values["staged_credential"].get_token.side_effect = ClientAuthenticationError(
        "offline denied"
    )
    with (
        remote_immutable_attempt_context(**values) as worker,
        pytest.raises(ClientAuthenticationError, match="offline denied"),
    ):
        worker.publish(candidate)
    assert "stage" not in lifecycle._ops(wire)
    assert all(value.closed == 1 for value in sdk.clients)
    assert_borrowed_credentials(values)


@pytest.mark.parametrize("drift", ["definition", "current_authority"])
def test_current_authority_or_definition_drift_never_stages(
    remote_inputs, wire, sdk, drift
):
    values, candidate, _env, _restores = remote_inputs
    if drift == "definition":
        values["definition_fingerprint"] = lambda: "changed"
    else:
        values["authorizer"].reader.read("admit").attestation_digest = "f" * 64
    with (
        remote_immutable_attempt_context(**values) as worker,
        pytest.raises(PublicationSafetyError),
    ):
        worker.publish(candidate)
    assert "stage" not in lifecycle._ops(wire)
    assert "commit" not in lifecycle._ops(wire)
    assert values["transport"].closed
    assert all(value.closed == 1 for value in sdk.clients)


def test_unused_context_is_inert_and_body_error_closes_http(remote_inputs, wire, sdk):
    values, _candidate, _env, _restores = remote_inputs
    with (
        pytest.raises(RuntimeError, match="stopped before use"),
        remote_immutable_attempt_context(**values),
    ):
        raise RuntimeError("stopped before use")
    assert wire.requests == sdk.calls == []
    assert values["transport"].closed
    assert not wire.credential.get_token.called
    assert_borrowed_credentials(values)
