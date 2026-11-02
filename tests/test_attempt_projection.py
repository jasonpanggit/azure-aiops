"""Offline logical projection with read-only remote-shaped staged dependencies."""

from copy import deepcopy
from dataclasses import replace

import pytest

from ontology_discovery.attempt_projection import (
    ImmutableLogicalProjectionPolicy,
    LogicalProduct,
    ReadOnlyAttemptProjector,
)
from ontology_discovery.immutable_attempt import AttemptReference
from ontology_discovery.publisher import PublicationSafetyError
from tests import test_immutable_attempt_worker as lifecycle
from tests.test_immutable_attempt_worker import server_env, wire  # noqa: F401

pytest_plugins = ("tests.test_publication_broker_transport",)


class RemoteShapedReads:
    """Only immutable staged reads; no local_root, service, pointer or writes."""

    def __init__(self, source):
        self._source = source

    def read_generation(self, generation_id):
        return deepcopy(self._source.read_generation(generation_id))

    def read_stage_authorization(self, **kwargs):
        return deepcopy(self._source.read_stage_authorization(**kwargs))


@pytest.fixture
def projected(tmp_path, monkeypatch, request):
    harness = request.getfixturevalue("wire")
    env, local, client, candidate, restores, clients = lifecycle._compose(
        tmp_path, monkeypatch, harness
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
    reads = RemoteShapedReads(local._storage)
    target = dict(client.expected_target)
    projector = ReadOnlyAttemptProjector(
        storage=reads,
        authorizer=local._authorizer,
        expected_target=target,
        definition_fingerprint=lambda: target["definition_fingerprint"],
        attempt_protocol=client,
        policies=(policy,),
    )
    try:
        yield harness, env, projector, client, candidate, restores, policy
    finally:
        for value in clients:
            value.close()


def test_remote_shaped_actual_worker_admit_restore_and_historical_recovery(
    tmp_path, projected
):
    harness, env, projector, client, candidate, restores, _policy = projected
    assert not hasattr(projector, "_service")
    assert not hasattr(projector._storage, "local_root")
    assert not hasattr(projector._storage, "write")
    admitted = lifecycle._worker(tmp_path, projector, client, "logical-admit").publish(
        candidate
    )
    assert admitted.state == "acknowledged"
    reference = AttemptReference.parse(admitted.record["reference"])
    harness.lost.add("commit")
    recovered = lifecycle._worker(
        tmp_path, projector, client, "logical-restore"
    ).restore(reference)
    assert recovered.state == "historical_recovery"
    assert recovered.record["request_pins"]["operation"] == "restore"
    assert restores
    assert env.sink.calls == env.catalogs == []
    assert lifecycle._ops(harness).count("stage") == 1
    assert lifecycle._ops(harness).count("commit") == 2
    assert lifecycle._ops(harness).count("recover") == 1


@pytest.mark.parametrize(
    "drift", ["schema", "count", "digest", "context", "missing", "extra"]
)
def test_independent_expected_logical_policy_refuses_before_stage(
    tmp_path, projected, drift
):
    harness, _env, projector, client, candidate, _restores, policy = projected
    products = policy.products
    if drift in {"schema", "count", "digest"}:
        field, value = {
            "schema": ("schema_digest", "0" * 64),
            "count": ("row_count", products[0].row_count + 1),
            "digest": ("content_digest", "0" * 64),
        }[drift]
        changed = replace(products[0], **{field: value})
        policy = replace(policy, products=(changed, *products[1:]))
    elif drift == "context":
        policy = replace(policy, context=replace(policy.context, content_hash="0" * 64))
    else:
        with pytest.raises(PublicationSafetyError, match="policy_shape"):
            replace(
                policy,
                products=products[:-1]
                if drift == "missing"
                else (*products, products[0]),
            )
        assert harness.requests == []
        return
    projector._policies = (policy,)
    with pytest.raises(PublicationSafetyError):
        lifecycle._worker(tmp_path, projector, client, f"logical-{drift}").publish(
            candidate
        )
    assert "stage" not in lifecycle._ops(harness)
    assert "commit" not in lifecycle._ops(harness)


def test_fresh_authority_and_target_drift_refused_before_stage(tmp_path, projected):
    harness, _env, projector, client, candidate, _restores, _policy = projected
    projector._definition_fingerprint = lambda: "changed"
    with pytest.raises(PublicationSafetyError, match="target_changed"):
        lifecycle._worker(tmp_path, projector, client, "logical-drift").publish(
            candidate
        )
    assert "stage" not in lifecycle._ops(harness)


def test_independent_restore_authority_is_required(tmp_path, projected):
    harness, _env, projector, client, candidate, _restores, _policy = projected
    admitted = lifecycle._worker(tmp_path, projector, client, "logical-first").publish(
        candidate
    )

    def denied(**_kwargs):
        raise PublicationSafetyError("current restore denied")

    projector._authorizer.authorize_restore = denied
    before = lifecycle._ops(harness).count("commit")
    with pytest.raises(PublicationSafetyError, match="restore denied"):
        lifecycle._worker(tmp_path, projector, client, "logical-denied").restore(
            AttemptReference.parse(admitted.record["reference"])
        )
    assert lifecycle._ops(harness).count("commit") == before


def test_current_admission_authority_drift_is_refused(tmp_path, projected):
    harness, _env, projector, client, candidate, _restores, _policy = projected
    projector._authorizer.reader.read("admit").attestation_digest = "f" * 64
    with pytest.raises(PublicationSafetyError, match="operation_policy_missing"):
        lifecycle._worker(tmp_path, projector, client, "logical-authority").publish(
            candidate
        )
    assert "stage" not in lifecycle._ops(harness)


@pytest.mark.parametrize("operation", ["allocate", "stage"])
def test_projector_lost_mutation_holds_target_across_restart(
    tmp_path, projected, operation
):
    from ontology_discovery.immutable_attempt_worker import AttemptLifecycleConflict
    from ontology_discovery.publication_broker_client import BrokerClientError

    harness, _env, projector, client, candidate, _restores, _policy = projected
    harness.lost.add(operation)
    with pytest.raises(BrokerClientError, match="transport_failed"):
        lifecycle._worker(tmp_path, projector, client, "logical-lost").publish(
            candidate
        )
    before = len(harness.requests)
    held = lifecycle._worker(tmp_path, projector, client, "logical-lost").publish(
        candidate
    )
    assert held.state == "held"
    with pytest.raises(AttemptLifecycleConflict, match="target.*dispatch"):
        lifecycle._worker(tmp_path, projector, client, "logical-competitor").publish(
            candidate
        )
    assert len(harness.requests) == before


def test_unknown_commit_uses_exact_original_pins(tmp_path, projected):
    harness, _env, projector, client, candidate, _restores, _policy = projected
    harness.lost.add("commit")
    result = lifecycle._worker(tmp_path, projector, client, "logical-unknown").publish(
        candidate
    )
    assert result.state == "historical_recovery"
    import json

    commits = [
        json.loads(request.content)
        for request in harness.requests
        if request.url.path.endswith("/commit")
    ]
    recoveries = [
        json.loads(request.content)
        for request in harness.requests
        if request.url.path.endswith("/recover")
    ]
    assert len(commits) == 1
    assert recoveries == commits
    assert "read-table" not in lifecycle._ops(harness)


@pytest.mark.parametrize("drift", ["missing", "extra", "content", "inactive_type"])
def test_actual_projection_drift_refused_without_stage(
    tmp_path, projected, monkeypatch, drift
):
    harness, _env, projector, client, candidate, _restores, _policy = projected
    project = projector._project_attempt

    def changed(value):
        staged, context, products = project(value)
        if drift == "missing":
            products.pop(next(iter(products)))
        elif drift == "extra":
            products["ontology_unreviewed"] = []
        elif drift == "content":
            table = next(name for name, rows in products.items() if rows)
            products[table] = [{**products[table][0], "unreviewed": True}]
        else:
            staged["entities"].append({"entity_type": "unknown", "active": False})
        return staged, context, products

    monkeypatch.setattr(projector, "_project_attempt", changed)
    with pytest.raises(PublicationSafetyError):
        lifecycle._worker(tmp_path, projector, client, "logical-actual-drift").publish(
            candidate
        )
    assert "stage" not in lifecycle._ops(harness)
    assert "commit" not in lifecycle._ops(harness)
