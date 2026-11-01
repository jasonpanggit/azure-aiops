"""Historical outcome recovery cannot revive authority or a legacy pointer."""

import pytest

from ontology_discovery.immutable_attempt import (
    AttemptReference,
    ImmutableAttemptProtocol,
)
from ontology_discovery.publisher import (
    APPROVED_PUBLICATION_CHECKPOINTS,
    OntologyGenerationPublisher,
    PublicationSafetyError,
)
from ontology_discovery.publisher_worker import PublisherWorker
from storage.datasets import GenerationPointerConditions
from tests.test_immutable_attempt_protocol import (
    commit,
    fixture,
    materializer_fixture,
    stage,
)
from tests.test_ontology_generation_publication import _candidate, _publisher


@pytest.mark.parametrize("invalid", ["expired", "revoked", "retention", "takeover"])
def test_core_recovers_only_historical_outcome_after_lost_response(tmp_path, invalid):
    broker, core, control, candidate = fixture(tmp_path)
    reference = stage(core, control, candidate)
    broker.grant(control.session, reference)
    broker.crash = "commit"
    with pytest.raises(TimeoutError):
        commit(core, control, reference)
    historical = broker.read_control()
    if invalid == "takeover":
        newer = broker.takeover("B")
        winner = stage(core, newer, candidate, "B")
        broker.grant(newer.session, winner)
        commit(core, newer, winner, "B")
        broker.authenticated_principal = "A"
    elif invalid == "revoked":
        broker.revoke(control.session, reference)
    elif invalid == "retention":
        broker.retention_state = "unlocked"
    else:
        broker.now = 100
    before = broker.read_control()
    assert commit(core, control, reference) == historical
    assert broker.read_control() == before
    with pytest.raises(PublicationSafetyError):
        commit(core, control, reference, request="uncommitted")
    assert broker.read_control() == before


@pytest.mark.parametrize("field,value", [
    ("expected_revision", "999"), ("authorization_digest", "changed"),
    ("operation", "restore"), ("request_id", "not-recorded"),
])
def test_recovery_compares_all_original_request_fields(tmp_path, field, value):
    broker, core, control, candidate = fixture(tmp_path)
    reference = stage(core, control, candidate)
    broker.grant(control.session, reference)
    accepted = commit(core, control, reference)
    args = {
        "expected_revision": control.revision, "request_id": "request",
        "operation": "admit", "authorization_digest": "auth",
    }
    args[field] = value
    if field == "request_id":
        assert core.recover_commit(control.session, reference, **args) is None
    else:
        with pytest.raises(PublicationSafetyError, match="request_reuse"):
            core.recover_commit(control.session, reference, **args)
    with pytest.raises(PublicationSafetyError, match="request_reuse"):
        core.recover_commit(
            control.session, AttemptReference("different-attempt", reference.generation_id, reference.catalog_digest),
            expected_revision=control.revision, request_id="request", operation="admit", authorization_digest="auth",
        )
    broker.authenticated_principal = "outsider"
    with pytest.raises(PublicationSafetyError, match="stale_session"):
        commit(core, control, reference)
    assert broker.read_control() == accepted


@pytest.mark.parametrize("operation", ["admit", "restore"])
@pytest.mark.parametrize("invalid", ["expired", "revoked", "retention", "takeover"])
def test_actual_materializer_retry_recovers_before_reads_or_authority(
    tmp_path, monkeypatch, operation, invalid,
):
    env, materializer, broker, control, candidate, _ = materializer_fixture(tmp_path, monkeypatch)
    result = materializer(candidate)
    reference = AttemptReference.parse(result["attempt_reference"])
    digest = env.context.authorization_digest if operation == "admit" else "synthetic-attestation"
    broker.grant(control.session, reference, operation=operation, digest=digest)

    def invoke(request_id="publish", **kwargs):
        if operation == "admit":
            return materializer.commit_attempt(expected_revision=control.revision, request_id=request_id, **kwargs)
        return materializer.restore_attempt(reference, expected_revision=control.revision, request_id=request_id, **kwargs)

    broker.crash = "commit"
    with pytest.raises(TimeoutError):
        invoke()
    historical = broker.read_control()
    if invalid == "revoked":
        broker.revoke(control.session, reference, operation)
    elif invalid == "retention":
        broker.retention_state = "unlocked"
    elif invalid == "expired":
        broker.now = 100
    else:
        broker.takeover("B")
        broker.authenticated_principal = "A"
    before = broker.read_control()

    def revoked(*_args, **_kwargs):
        raise PublicationSafetyError("review:revoked")

    monkeypatch.setattr(materializer, "_authorization", revoked)
    monkeypatch.setattr(materializer._authorizer, "authorize_restore", revoked)
    assert invoke() == historical
    assert broker.read_control() == before
    with pytest.raises(PublicationSafetyError):
        invoke("new-unauthorized-operation")
    with pytest.raises(PublicationSafetyError, match="request_reuse"):
        invoke(authorization_digest="different-original-digest")
    materializer._attempt_request_digests.clear()
    materializer._attempt_protocol = ImmutableAttemptProtocol(broker.restart())
    assert materializer.recover_attempt_outcome(
        reference, expected_revision=control.revision, request_id="publish",
        operation=operation, authorization_digest=digest,
    ) == historical
    assert broker.read_control() == before


@pytest.mark.parametrize("callback_form", ["bound", "wrapped"])
def test_real_legacy_publisher_refuses_attempt_callback_result(tmp_path, callback_form):
    _store, adapter, publisher = _publisher(tmp_path)

    class AttemptMaterializer:
        publication_protocol = "immutable-attempt/v1"
        calls = 0

        def __call__(self, _candidate):
            self.calls += 1
            return {"status": "completed", "protocol": self.publication_protocol, "attempt_reference": {}}

    materializer = AttemptMaterializer()
    callback = materializer.__call__ if callback_form == "bound" else lambda candidate: materializer(candidate)
    with pytest.raises(PublicationSafetyError, match="legacy_pointer"):
        publisher.publish(
            _candidate(), publisher_identity="ontology-publisher",
            checkpoint_ids=APPROVED_PUBLICATION_CHECKPOINTS,
            pointer_conditions=GenerationPointerConditions.initial(), owner_id="writer-1", fence=1,
            consumer_compatibility=dict.fromkeys(("api", "fabric", "agent", "export", "semantic"), True),
            cancellation_check=lambda: False, lease_guard=lambda: None, materialize_generation=callback,
        )
    assert adapter.read_pointer().pointer is None
    if callback_form == "bound":
        assert materializer.calls == 0


def test_actual_attempt_materializer_bound_method_rejected_before_use(tmp_path, monkeypatch):
    _env, materializer, _broker, _control, _candidate_value, _ = materializer_fixture(tmp_path, monkeypatch)
    with pytest.raises(PublicationSafetyError, match="legacy_worker_protocol"):
        PublisherWorker(
            dispatches=None, publisher=None, publisher_identity="", owner_id="",
            fence_allocator=None, materialize=materializer.__call__, consumer_check=None, now=lambda: None,
        )
    publisher = object.__new__(OntologyGenerationPublisher)
    with pytest.raises(PublicationSafetyError, match="legacy_pointer"):
        publisher.publish(
            _candidate_value, publisher_identity="", checkpoint_ids=[], pointer_conditions=None,
            owner_id="A", fence=1, consumer_compatibility={}, cancellation_check=lambda: False,
            lease_guard=lambda: None, materialize_generation=materializer.__call__,
        )
