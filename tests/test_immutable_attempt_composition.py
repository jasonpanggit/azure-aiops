"""Explicit application composition exercised only through the closed transport."""

from datetime import UTC, datetime
from unittest.mock import Mock

import httpx
import pytest

from ontology_discovery.immutable_attempt_composition import (
    compose_local_immutable_attempt_worker,
)
from ontology_discovery.maintenance_materialization import (
    CandidateGenerationMaterializer,
)
from ontology_discovery.publication_broker_client import (
    BrokerClientError,
    PublicationBrokerClient,
)
from ontology_discovery.publisher import PublicationSafetyError
from tests import test_immutable_attempt_worker as lifecycle
from tests.test_immutable_attempt_worker import server_env  # noqa: F401
from tests.test_publication_broker_client import AUDIENCE, ENDPOINT, OWNER

pytest_plugins = (
    "tests.test_publication_broker_transport",
    "tests.test_publication_broker_client",
)


class TrackingTransport(httpx.BaseTransport):
    def __init__(self, delegate):
        self.delegate = delegate
        self.closed = False

    def handle_request(self, request):
        assert not self.closed
        return self.delegate.handle_request(request)

    def close(self):
        self.closed = True


@pytest.fixture
def composed_inputs(tmp_path, monkeypatch, wire):
    constructor = Mock(wraps=CandidateGenerationMaterializer)
    monkeypatch.setattr(lifecycle, "CandidateGenerationMaterializer", constructor)
    _env, _materializer, client, candidate, _restores, clients = lifecycle._compose(
        tmp_path, monkeypatch, wire
    )
    arguments = dict(constructor.call_args.kwargs)
    wire.credential.close = Mock()
    transport = TrackingTransport(client._http._transport)
    options = {
        key: arguments[key]
        for key in (
            "storage",
            "documents",
            "service",
            "authorizer",
            "target_id",
            "expected_target",
            "output_policies",
        )
    }
    options.update(
        endpoint=ENDPOINT,
        audience=AUDIENCE,
        worker_object_id=OWNER,
        credential_owner_object_id=OWNER,
        credential=wire.credential,
        dispatch_id="explicit-local-composition",
        journal_root=tmp_path / "coordinator-journal",
        clock=lambda: datetime.now(UTC),
        transport=transport,
    )
    commit = PublicationBrokerClient.commit

    def authorized_commit(self, session, reference, **kwargs):
        wire.server.boundary.grant(
            session,
            reference,
            operation=kwargs["operation"],
            digest=kwargs["authorization_digest"],
        )
        return commit(self, session, reference, **kwargs)

    monkeypatch.setattr(PublicationBrokerClient, "commit", authorized_commit)
    try:
        yield options, candidate, transport
    finally:
        for value in clients:
            value.close()


def test_composed_actual_lifecycle_and_owned_http_cleanup(composed_inputs, wire):
    options, candidate, transport = composed_inputs
    with compose_local_immutable_attempt_worker(**options) as worker:
        assert wire.requests == []
        assert not transport.closed
        result = worker.publish(candidate)
        assert result.state == "acknowledged"
        assert result.record["target"] == options["expected_target"]
    assert transport.closed
    assert not options["credential"].close.called
    with pytest.raises(BrokerClientError, match="closed"):
        worker._client.control()
    before_restart = len(wire.requests)
    options["transport"] = TrackingTransport(transport.delegate)
    with compose_local_immutable_attempt_worker(**options) as restarted:
        assert restarted.publish(candidate).record == result.record
    assert len(wire.requests) == before_restart
    assert options["transport"].closed


@pytest.mark.parametrize(
    ("invalid", "error"),
    [
        ("target", "output_target_mismatch"),
        ("worker", "uuid"),
        ("owner", "credential_owner_mismatch"),
        ("overlap", "journal_root_overlap"),
        ("remote", "remote_mutation_lock_unqualified"),
    ],
)
def test_refusal_precedes_token_transport_and_journal_creation(
    composed_inputs, wire, invalid, error
):
    options, _candidate, transport = composed_inputs
    original_root = options["journal_root"]
    if invalid == "target":
        options["expected_target"] = {**options["expected_target"], "item_id": "wrong"}
    elif invalid == "worker":
        options["worker_object_id"] = "not-an-object-id"
        options["credential_owner_object_id"] = "not-an-object-id"
    elif invalid == "owner":
        options["credential_owner_object_id"] = "ffffffff-ffff-ffff-ffff-ffffffffffff"
    elif invalid == "overlap":
        options["journal_root"] = options["service"].onelake.local_root
    else:
        options["service"].onelake.local_root = None
    with (
        pytest.raises((PublicationSafetyError, BrokerClientError), match=error),
        compose_local_immutable_attempt_worker(**options),
    ):
        pytest.fail("invalid composition yielded a worker")
    assert wire.requests == []
    assert not wire.credential.get_token.called
    assert not original_root.exists()
    assert not transport.closed


def test_worker_construction_failure_closes_owned_http_only(composed_inputs, wire):
    options, _candidate, transport = composed_inputs
    options["dispatch_id"] = ""
    with (
        pytest.raises(ValueError, match="dispatch"),
        compose_local_immutable_attempt_worker(**options),
    ):
        pytest.fail("invalid dispatch yielded a worker")
    assert transport.closed
    assert not options["credential"].close.called
    assert wire.requests == []


def test_context_exception_closes_owned_http(composed_inputs):
    options, _candidate, transport = composed_inputs
    with (
        pytest.raises(RuntimeError, match="application stopped"),
        compose_local_immutable_attempt_worker(**options),
    ):
        raise RuntimeError("application stopped")
    assert transport.closed
