"""Isolated broker lifecycle coordination; never invokes CLI or legacy worker paths."""

pytest_plugins = ("tests.test_publication_broker_transport",)

import json
from dataclasses import replace
from types import MappingProxyType

import httpx
import pytest
from azure.core.exceptions import ClientAuthenticationError

from fabric.maintenance_output import describe_outputs
from fabric.sync_service import _generation_catalog, ontology_generation_products
from ontology_discovery.immutable_attempt import AttemptReference
from ontology_discovery.immutable_attempt_worker import (
    AttemptLifecycleConflict,
    ImmutableAttemptWorker,
    OneLakeAttemptLifecycleJournal,
)
from ontology_discovery.maintenance_materialization import (
    CandidateGenerationMaterializer,
)
from ontology_discovery.publication_broker_client import (
    BrokerClientError,
    PublicationBrokerClient,
)
from ontology_discovery.publisher import OntologyGenerationCandidate
from storage.onelake_documents import OneLakeDocumentStore
from tests import test_immutable_attempt_protocol as existing
from tests.test_publication_broker_client import (  # noqa: F401
    AUDIENCE,
    ENDPOINT,
    OWNER,
    wire,
)
from tests.test_publication_broker_transport import TENANT


@pytest.fixture
def server_env(env):
    return env


def _candidate(value):
    return OntologyGenerationCandidate(
        generation_id=value.generation_id,
        source_generation=value.source_generation,
        entities=tuple(value.entities),
        relationships=tuple(value.relationships),
        proposal_lineage=(),
        decision_lineage=(),
        policy_version="worker-test",
        schema_version="worker-test",
    )


def _compose(tmp_path, monkeypatch, http_harness):
    clients = []
    http_harness.responses = []

    def construct(**kwargs):
        target = dict(kwargs["expected_target"])
        target["tenant_id"] = TENANT
        kwargs["expected_target"] = target
        http_harness.server.transport._target = MappingProxyType(target)
        http_harness.server.boundary.takeover(OWNER)
        release = kwargs["authorizer"].reader.read("admit")
        release.tenant_id = TENANT
        context = kwargs["output_policies"][0].context
        authorization_digest = existing._hash(
            {
                "release": release.authorization_binding(),
                "target": target,
                "generation_id": context.generation_id,
                "content_hash": context.content_hash,
            }
        )
        context = replace(
            context,
            expected_target=tuple(sorted(target.items())),
            authorization_digest=authorization_digest,
        )
        staged = kwargs["storage"].read_generation(context.generation_id)
        products = ontology_generation_products(
            staged["entities"],
            staged["relationships"],
            generation_id=context.generation_id,
            source_generation=context.source_generation,
            content_hash=context.content_hash,
            authorization_digest=context.authorization_digest,
            attestation_digest=context.attestation_digest,
            validation=staged["validation"],
        )
        catalog = _generation_catalog(
            products,
            {name: {"version": None} for name in products},
            context.generation_id,
            context.content_hash,
        )
        kwargs["output_policies"] = (
            replace(
                kwargs["output_policies"][0],
                context=context,
                manifest=describe_outputs(
                    products,
                    kwargs["service"].onelake,
                    catalog,
                ),
            ),
        )

        def send(request):
            http_harness.requests.append(request)
            response = http_harness.server.transport.handle(
                method=request.method,
                path=request.url.raw_path.decode(),
                headers=list(request.headers.multi_items()),
                body=request.content,
            )
            http_harness.responses.append(response)
            operation = request.url.path.rsplit("/", 1)[-1]
            if operation in http_harness.lost:
                http_harness.lost.remove(operation)
                raise httpx.ReadTimeout("simulated lost response", request=request)
            return httpx.Response(
                response.status,
                content=response.body,
                headers={"content-type": response.content_type},
            )

        client = PublicationBrokerClient(
            endpoint=ENDPOINT,
            audience=AUDIENCE,
            expected_target=target,
            worker_object_id=OWNER,
            credential=http_harness.credential,
            transport=httpx.MockTransport(send),
        )
        kwargs.pop("attempt_boundary")
        kwargs["attempt_protocol"] = client
        clients.append(client)
        return CandidateGenerationMaterializer(**kwargs)

    monkeypatch.setattr(existing, "CandidateGenerationMaterializer", construct)
    env, materializer, _boundary, _control, candidate, restore_calls = (
        existing.materializer_fixture(tmp_path / "materializer", monkeypatch)
    )
    client = clients[0]
    original_commit = client.commit

    def authorized_commit(session, reference, **kwargs):
        http_harness.server.boundary.grant(
            session,
            reference,
            operation=kwargs["operation"],
            digest=kwargs["authorization_digest"],
        )
        return original_commit(session, reference, **kwargs)

    client.commit = authorized_commit
    restore_authorizer = materializer._authorizer.authorize_restore

    def current_restore_authorizer(**kwargs):
        release = restore_authorizer(**kwargs)
        release.attestation_digest = "c" * 64
        return release

    materializer._authorizer.authorize_restore = current_restore_authorizer
    return env, materializer, client, _candidate(candidate), restore_calls, clients


def _worker(tmp_path, materializer, client, dispatch_id):
    target = dict(client.expected_target)
    return ImmutableAttemptWorker(
        dispatch_id=dispatch_id,
        expected_target=target,
        client=client,
        materializer=materializer,
        journal=OneLakeAttemptLifecycleJournal(
            OneLakeDocumentStore(tmp_path / "separate-journal-root")
        ),
    )


def _ops(wire_fixture):
    return [request.url.path.rsplit("/", 1)[-1] for request in wire_fixture.requests]


def test_actual_client_lifecycle_isolated_from_legacy_pointer_and_product_sinks(
    tmp_path, monkeypatch, request
):
    http_harness = request.getfixturevalue("wire")
    env, materializer, client, candidate, _restore_calls, clients = _compose(
        tmp_path,
        monkeypatch,
        http_harness,
    )
    try:
        worker = _worker(tmp_path, materializer, client, "dispatch-admit-1")
        result = worker.publish(candidate)
        assert result.state == "acknowledged"
        assert result.record["state"] == "acknowledged"
        assert result.record["request_pins"]["operation"] == "admit"
        assert env.sink.calls == env.catalogs == []
        assert set(_ops(http_harness)) >= {
            "read-control",
            "acquire",
            "allocate",
            "stage",
            "read-catalog",
            "commit",
        }
        operations = _ops(http_harness)
        read_control_index = operations.index("read-control")
        acquire_index = operations.index("acquire")
        control = json.loads(http_harness.responses[read_control_index].body)["result"]
        acquire = json.loads(http_harness.requests[acquire_index].content)
        assert acquire["expected_revision"] == control["revision"]
        assert acquire["lease_seconds"] == 300
        assert "renew" not in operations
        assert "read-table" not in _ops(http_harness)
        journal_path = (
            tmp_path
            / "separate-journal-root"
            / "ontology"
            / "immutable-attempt-lifecycle"
        )
        assert journal_path.is_dir()
        assert not (tmp_path / "materializer" / "ontology").exists()
    finally:
        for item in clients:
            item.close()


def test_dispatch_reuse_with_changed_candidate_is_rejected_before_broker_calls(
    tmp_path, monkeypatch, request
):
    http_harness = request.getfixturevalue("wire")
    _env, materializer, client, candidate, _restore_calls, clients = _compose(
        tmp_path,
        monkeypatch,
        http_harness,
    )
    try:
        journal = OneLakeAttemptLifecycleJournal(
            OneLakeDocumentStore(tmp_path / "separate-journal-root")
        )
        first = ImmutableAttemptWorker(
            dispatch_id="dispatch-bound-candidate",
            expected_target=dict(client.expected_target),
            client=client,
            materializer=materializer,
            journal=journal,
        )
        first_result = first.publish(candidate)
        assert first_result.state == "acknowledged"
        request_count = len(http_harness.requests)
        changed = replace(candidate, policy_version="different-policy")
        replay = ImmutableAttemptWorker(
            dispatch_id="dispatch-bound-candidate",
            expected_target=dict(client.expected_target),
            client=client,
            materializer=materializer,
            journal=OneLakeAttemptLifecycleJournal(
                OneLakeDocumentStore(tmp_path / "separate-journal-root")
            ),
        )
        with pytest.raises(AttemptLifecycleConflict, match="candidate_digest"):
            replay.publish(changed)
        assert len(http_harness.requests) == request_count
    finally:
        for item in clients:
            item.close()


@pytest.mark.parametrize(
    ("lost_operation", "intent_state", "counted"),
    [
        ("allocate", "held", "allocate"),
        ("stage", "held", "stage"),
    ],
)
def test_ambiguous_allocate_or_stage_is_durably_held_without_retry(
    tmp_path, monkeypatch, request, lost_operation, intent_state, counted
):
    http_harness = request.getfixturevalue("wire")
    _env, materializer, client, candidate, _restore_calls, clients = _compose(
        tmp_path,
        monkeypatch,
        http_harness,
    )
    try:
        journal_root = tmp_path / "separate-journal-root"
        http_harness.lost.add(lost_operation)
        worker = _worker(
            tmp_path, materializer, client, f"dispatch-lost-{lost_operation}"
        )
        with pytest.raises(BrokerClientError, match="transport_failed"):
            worker.publish(candidate)
        operations_before = _ops(http_harness)
        assert operations_before.count(counted) == 1
        restarted = ImmutableAttemptWorker(
            dispatch_id=f"dispatch-lost-{lost_operation}",
            expected_target=dict(client.expected_target),
            client=client,
            materializer=materializer,
            journal=OneLakeAttemptLifecycleJournal(OneLakeDocumentStore(journal_root)),
        )
        result = restarted.publish(candidate)
        assert result.state == intent_state
        assert result.record["hold_reason"] in {
            "allocation_outcome_unconfirmed",
            "stage_outcome_unconfirmed",
        }
        assert _ops(http_harness) == operations_before
    finally:
        for item in clients:
            item.close()


@pytest.mark.parametrize(
    ("stop", "hold_reason"),
    [
        ("cancel", "cancelled_before_mutation"),
        ("deadline", "lease_budget_exhausted"),
    ],
)
def test_worker_guard_stops_after_token_acquisition_before_stage_send(
    tmp_path, monkeypatch, request, stop, hold_reason
):
    http_harness = request.getfixturevalue("wire")
    _env, materializer, client, candidate, _restore_calls, clients = _compose(
        tmp_path,
        monkeypatch,
        http_harness,
    )
    try:
        cancelled = {"value": False}
        clock = {"now": 0.0}
        get_token = http_harness.credential.get_token.side_effect

        def stop_before_stage(scope):
            token = get_token(scope)
            if len(http_harness.requests) == 5:
                if stop == "cancel":
                    cancelled["value"] = True
                else:
                    clock["now"] = 300.0
            return token

        http_harness.credential.get_token.side_effect = stop_before_stage
        worker = ImmutableAttemptWorker(
            dispatch_id="dispatch-cancel-before-stage",
            expected_target=dict(client.expected_target),
            client=client,
            materializer=materializer,
            journal=OneLakeAttemptLifecycleJournal(
                OneLakeDocumentStore(tmp_path / "separate-journal-root")
            ),
            cancelled=lambda: cancelled["value"],
            monotonic=lambda: clock["now"],
        )
        expected_message = (
            "cancelled before mutation"
            if stop == "cancel"
            else "lease budget exhausted"
        )
        with pytest.raises(AttemptLifecycleConflict, match=expected_message):
            worker.publish(candidate)

        operations = _ops(http_harness)
        assert operations.count("allocate") == 1
        assert "stage" not in operations
        record = OneLakeAttemptLifecycleJournal(
            OneLakeDocumentStore(tmp_path / "separate-journal-root")
        ).read("dispatch-cancel-before-stage")
        assert record is not None
        assert record.record["state"] == "held"
        assert record.record["hold_reason"] == hold_reason
    finally:
        for item in clients:
            item.close()


def test_cancellation_during_commit_token_acquisition_prevents_commit_send(
    tmp_path, monkeypatch, request
):
    http_harness = request.getfixturevalue("wire")
    _env, materializer, client, candidate, _restore_calls, clients = _compose(
        tmp_path,
        monkeypatch,
        http_harness,
    )
    try:
        cancelled = {"value": False}
        original_get_token = http_harness.credential.get_token.side_effect
        authorized_commit = client.commit

        def cancel_after_commit_token(scope):
            token = original_get_token(scope)
            cancelled["value"] = True
            return token

        def cancel_during_commit(*args, **kwargs):
            http_harness.credential.get_token.side_effect = cancel_after_commit_token
            return authorized_commit(*args, **kwargs)

        client.commit = cancel_during_commit
        worker = ImmutableAttemptWorker(
            dispatch_id="dispatch-cancel-before-commit",
            expected_target=dict(client.expected_target),
            client=client,
            materializer=materializer,
            journal=OneLakeAttemptLifecycleJournal(
                OneLakeDocumentStore(tmp_path / "separate-journal-root")
            ),
            cancelled=lambda: cancelled["value"],
        )
        with pytest.raises(AttemptLifecycleConflict, match="cancelled before mutation"):
            worker.publish(candidate)

        operations = _ops(http_harness)
        assert operations.count("stage") == 1
        assert "commit" not in operations
        assert "recover" not in operations
        saved = OneLakeAttemptLifecycleJournal(
            OneLakeDocumentStore(tmp_path / "separate-journal-root")
        ).read("dispatch-cancel-before-commit")
        assert saved is not None
        assert saved.record["state"] == "held"
        assert saved.record["hold_reason"] == "cancelled_before_mutation"
        assert saved.record["request_pins"]["operation"] == "admit"
    finally:
        for item in clients:
            item.close()


def test_ambiguous_commit_recovers_exact_pins_but_never_claims_active_or_reader_access(
    tmp_path, monkeypatch, request
):
    http_harness = request.getfixturevalue("wire")
    _env, materializer, client, candidate, _restore_calls, clients = _compose(
        tmp_path,
        monkeypatch,
        http_harness,
    )
    try:
        http_harness.lost.add("commit")
        worker = _worker(tmp_path, materializer, client, "dispatch-lost-commit")
        result = worker.publish(candidate)
        assert result.state == "historical_recovery"
        assert (
            result.record["hold_reason"]
            == "historical_outcome_does_not_prove_current_active_or_reader_access"
        )
        pins = result.record["request_pins"]
        assert pins["operation"] == "admit"
        assert pins["expected_revision"] == result.record["broker_revision"]
        operations_before = _ops(http_harness)
        assert operations_before.count("commit") == 1
        assert operations_before.count("recover") == 1
        assert "read-table" not in operations_before

        restarted = ImmutableAttemptWorker(
            dispatch_id="dispatch-lost-commit",
            expected_target=dict(client.expected_target),
            client=client,
            materializer=materializer,
            journal=OneLakeAttemptLifecycleJournal(
                OneLakeDocumentStore(tmp_path / "separate-journal-root")
            ),
        )
        assert restarted.publish(candidate).state == "historical_recovery"
        assert _ops(http_harness) == operations_before
    finally:
        for item in clients:
            item.close()


@pytest.mark.parametrize("failure", ["credential", "transport"])
def test_unavailable_read_only_recovery_is_persisted_as_hold(
    tmp_path, monkeypatch, request, failure
):
    http_harness = request.getfixturevalue("wire")
    _env, materializer, client, candidate, _restore_calls, clients = _compose(
        tmp_path,
        monkeypatch,
        http_harness,
    )
    try:
        http_harness.lost.add("commit")
        if failure == "credential":
            get_token = http_harness.credential.get_token.side_effect

            def unavailable_during_recovery(scope):
                if _ops(http_harness).count("commit"):
                    raise ClientAuthenticationError("simulated credential outage")
                return get_token(scope)

            http_harness.credential.get_token.side_effect = unavailable_during_recovery
        else:
            http_harness.lost.add("recover")

        worker = _worker(tmp_path, materializer, client, f"dispatch-recovery-{failure}")
        result = worker.publish(candidate)
        assert result.state == "held"
        assert result.record["hold_reason"] == "read_only_recovery_unavailable"
        assert _ops(http_harness).count("commit") == 1
        assert _ops(http_harness).count("recover") == (
            1 if failure == "transport" else 0
        )
        assert result.record["state"] == "held"
        assert result.record["request_pins"]["operation"] == "admit"
    finally:
        for item in clients:
            item.close()


def test_target_journal_holds_competing_dispatch_across_restart(
    tmp_path, monkeypatch, request
):
    http_harness = request.getfixturevalue("wire")
    _env, materializer, client, candidate, _restore_calls, clients = _compose(
        tmp_path,
        monkeypatch,
        http_harness,
    )
    try:
        journal_root = tmp_path / "separate-journal-root"
        journal = OneLakeAttemptLifecycleJournal(OneLakeDocumentStore(journal_root))
        http_harness.lost.add("stage")
        first = _worker(tmp_path, materializer, client, "dispatch-target-owner")
        with pytest.raises(BrokerClientError, match="transport_failed"):
            first.publish(candidate)
        before_competitor = _ops(http_harness)
        saved = journal.read("dispatch-target-owner")
        assert saved is not None
        assert saved.record["state"] == "held"

        competing = ImmutableAttemptWorker(
            dispatch_id="dispatch-target-contender",
            expected_target=dict(client.expected_target),
            client=client,
            materializer=materializer,
            journal=journal,
        )
        with pytest.raises(AttemptLifecycleConflict, match="target.*dispatch"):
            competing.publish(candidate)
        assert _ops(http_harness) == before_competitor

        restarted_owner = _worker(
            tmp_path, materializer, client, "dispatch-target-owner"
        )
        assert restarted_owner.publish(candidate).state == "held"
        assert _ops(http_harness) == before_competitor
        assert journal.read("dispatch-target-owner").record == saved.record
        target = journal.read_target(dict(client.expected_target))
        assert target is not None
        assert target.record["dispatch_id"] == "dispatch-target-owner"
        assert target.record["state"] == "held"
    finally:
        for item in clients:
            item.close()


def test_terminal_target_owner_allows_next_dispatch_and_preserves_receipt(
    tmp_path, monkeypatch, request
):
    http_harness = request.getfixturevalue("wire")
    _env, materializer, client, candidate, _restore_calls, clients = _compose(
        tmp_path,
        monkeypatch,
        http_harness,
    )
    try:
        journal_root = tmp_path / "separate-journal-root"
        first = _worker(tmp_path, materializer, client, "dispatch-target-first")
        first_result = first.publish(candidate)
        assert first_result.state == "acknowledged"

        second = _worker(tmp_path, materializer, client, "dispatch-target-second")
        second_result = second.publish(candidate)
        assert second_result.state == "acknowledged"

        journal = OneLakeAttemptLifecycleJournal(OneLakeDocumentStore(journal_root))
        first_receipt = journal.read("dispatch-target-first")
        current_target = journal.read_target(dict(client.expected_target))
        assert first_receipt is not None
        assert first_receipt.record == first_result.record
        assert current_target is not None
        assert current_target.record["dispatch_id"] == "dispatch-target-second"
        assert current_target.record["state"] == "acknowledged"
    finally:
        for item in clients:
            item.close()


def test_restore_is_separate_exact_reference_command_with_new_request_pins(
    tmp_path, monkeypatch, request
):
    http_harness = request.getfixturevalue("wire")
    _env, materializer, client, candidate, _restore_calls, clients = _compose(
        tmp_path,
        monkeypatch,
        http_harness,
    )
    try:
        admitted = _worker(
            tmp_path, materializer, client, "dispatch-before-restore"
        ).publish(candidate)
        assert admitted.state == "acknowledged"
        reference = AttemptReference.parse(admitted.record["reference"])
        restored = ImmutableAttemptWorker(
            dispatch_id="trusted-restore-command-1",
            expected_target=dict(client.expected_target),
            client=client,
            materializer=materializer,
            journal=OneLakeAttemptLifecycleJournal(
                OneLakeDocumentStore(tmp_path / "separate-journal-root")
            ),
        ).restore(reference)
        assert restored.state == "acknowledged"
        assert restored.record["request_pins"]["operation"] == "restore"
        assert (
            restored.record["request_pins"]["request_id"]
            != admitted.record["request_pins"]["request_id"]
        )
        assert _ops(http_harness).count("commit") == 2
        assert _ops(http_harness).count("allocate") == 1
        assert _ops(http_harness).count("stage") == 1
    finally:
        for item in clients:
            item.close()


def test_restore_restart_recovers_exact_pins_without_catalog_read(
    tmp_path, monkeypatch, request
):
    http_harness = request.getfixturevalue("wire")
    _env, materializer, client, candidate, _restore_calls, clients = _compose(
        tmp_path,
        monkeypatch,
        http_harness,
    )
    try:
        admitted = _worker(
            tmp_path, materializer, client, "dispatch-before-restore-restart"
        ).publish(candidate)
        reference = AttemptReference.parse(admitted.record["reference"])
        journal_root = tmp_path / "separate-journal-root"
        worker = _worker(
            tmp_path, materializer, client, "dispatch-crash-during-restore"
        )

        def crash_after_boundary_commit(_control):
            raise SystemExit("simulated worker process stop")

        worker._acknowledge = crash_after_boundary_commit
        with pytest.raises(SystemExit, match="simulated worker process stop"):
            worker.restore(reference)
        saved = OneLakeAttemptLifecycleJournal(OneLakeDocumentStore(journal_root)).read(
            "dispatch-crash-during-restore"
        )
        assert saved is not None
        assert saved.record["state"] == "restoring"
        assert saved.record["request_pins"]["operation"] == "restore"

        operations_before_restart = _ops(http_harness)

        def catalog_unavailable(_reference):
            raise BrokerClientError("simulated catalog unavailable")

        client.read_catalog = catalog_unavailable
        restarted = _worker(
            tmp_path, materializer, client, "dispatch-crash-during-restore"
        )
        result = restarted.restore(reference)
        assert result.state == "historical_recovery"
        assert _ops(http_harness) == [*operations_before_restart, "recover"]
        assert result.record["request_pins"] == saved.record["request_pins"]
    finally:
        for item in clients:
            item.close()


def test_journal_compare_and_set_refuses_stale_revision_and_binding_drift(tmp_path):
    journal = OneLakeAttemptLifecycleJournal(OneLakeDocumentStore(tmp_path / "journal"))
    initial = {
        "dispatch_id": "dispatch-cas",
        "operation": "admit",
        "target": {"item_id": "one"},
        "candidate_digest": "a" * 64,
        "restore_reference": None,
        "revision": 0,
    }
    created = journal.create(initial)
    advanced = {**created.record, "revision": 1, "state": "acquiring"}
    journal.replace(advanced, expected_revision=0)
    with pytest.raises(AttemptLifecycleConflict, match="revision"):
        journal.replace(
            {**advanced, "revision": 1},
            expected_revision=0,
        )
    with pytest.raises(AttemptLifecycleConflict, match="binding changed"):
        journal.replace(
            {**advanced, "revision": 2, "target": {"item_id": "two"}},
            expected_revision=1,
        )
