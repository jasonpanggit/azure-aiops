"""High-level-only consumer dependency; not a deployed HTTP client qualification."""

from types import SimpleNamespace

import pytest

from ontology_discovery.immutable_attempt import (
    PROTOCOL,
    AttemptPublicationProtocol,
    AttemptReference,
    ImmutableAttemptProtocol,
)
from ontology_discovery.maintenance_materialization import (
    CandidateGenerationMaterializer,
)
from ontology_discovery.publisher import PublicationSafetyError
from tests import test_immutable_attempt_protocol as existing
from tests import test_immutable_attempt_recovery as recovery


class HighLevelClient:
    """Test adapter exposing only complete protocol operations, not sink methods."""

    def __init__(self, protocol):
        self._protocol = protocol

    def control(self):
        return self._protocol.control()

    def active(self):
        return self._protocol.active()

    def stage(self, *args, **kwargs):
        return self._protocol.stage(*args, **kwargs)

    def commit(self, *args, **kwargs):
        return self._protocol.commit(*args, **kwargs)

    def recover_commit(self, *args, **kwargs):
        return self._protocol.recover_commit(*args, **kwargs)

    def read_catalog(self, *args, **kwargs):
        return self._protocol.read_catalog(*args, **kwargs)

    def read_table(self, *args, **kwargs):
        return self._protocol.read_table(*args, **kwargs)


def _inject(monkeypatch, transform=None):
    seen = []

    def construct(**kwargs):
        boundary = kwargs.pop("attempt_boundary")
        client = HighLevelClient(ImmutableAttemptProtocol(boundary))
        assert isinstance(client, AttemptPublicationProtocol)
        assert not any(hasattr(client, name) for name in (
            "begin", "create_product", "create_products", "seal", "artifacts", "verifier",
        ))
        kwargs["attempt_protocol"] = client
        if transform is not None:
            transform(kwargs)
        seen.append((client, kwargs))
        return CandidateGenerationMaterializer(**kwargs)

    monkeypatch.setattr(existing, "CandidateGenerationMaterializer", construct)
    return seen


def test_full_actual_lifecycle_uses_high_level_only_protocol(tmp_path, monkeypatch):
    seen = _inject(monkeypatch)
    existing.test_existing_materializer_stages_commits_reads_and_restores_exact_attempt(
        tmp_path, monkeypatch,
    )
    assert len(seen) == 1


@pytest.mark.parametrize("operation", ["admit", "restore"])
@pytest.mark.parametrize("invalid", ["expired", "revoked", "retention", "takeover"])
def test_injected_client_recovers_without_new_artifact_reads_or_authority(
    tmp_path, monkeypatch, operation, invalid,
):
    _inject(monkeypatch)
    recovery.test_actual_materializer_retry_recovers_before_reads_or_authority(
        tmp_path, monkeypatch, operation, invalid,
    )


@pytest.mark.parametrize("mutation,reason", [
    ("both", "exactly_one"),
    ("neither", "exactly_one"),
    ("missing-method", "high_level_protocol"),
    ("noncallable-method", "high_level_protocol"),
    ("missing-policy", "boundary_and_policy"),
    ("remote-root", "remote_mutation_lock_unqualified"),
    ("native", "native_enabled"),
])
def test_injected_protocol_preserves_constructor_and_output_guards(
    tmp_path, monkeypatch, mutation, reason,
):
    def transform(kwargs):
        if mutation == "both":
            kwargs["attempt_boundary"] = object()
        elif mutation == "neither":
            kwargs["attempt_protocol"] = None
        elif mutation in {"missing-method", "noncallable-method"}:
            client = kwargs["attempt_protocol"]
            values = {
                name: getattr(client, name)
                for name in (
                    "control", "active", "stage", "commit",
                    "recover_commit", "read_catalog",
                )
            }
            if mutation == "noncallable-method":
                values["read_table"] = 42
            kwargs["attempt_protocol"] = SimpleNamespace(**values)
        elif mutation == "missing-policy":
            kwargs["output_policies"] = ()
        elif mutation == "remote-root":
            kwargs["service"].onelake.local_root = None
        elif mutation == "native":
            kwargs["service"].ontology_id = "forbidden-native"

    _inject(monkeypatch, transform)
    with pytest.raises(PublicationSafetyError, match=reason):
        _env, materializer, _broker, _control, candidate, _calls = (
            existing.materializer_fixture(tmp_path, monkeypatch)
        )
        materializer(candidate)


def test_legacy_mode_refuses_high_level_protocol_before_touching_dependencies():
    with pytest.raises(PublicationSafetyError, match="attempt_protocol_requires_protocol"):
        CandidateGenerationMaterializer(
            storage=None, documents=None, service=None, authorizer=None,
            target_id="synthetic", clock=lambda: None, attempt_protocol=object(),
        )


def test_client_transport_failure_does_not_fall_back_to_fixed_table_writes(
    tmp_path, monkeypatch,
):
    seen = _inject(monkeypatch)
    env, materializer, _broker, _control, candidate, _calls = (
        existing.materializer_fixture(tmp_path, monkeypatch)
    )

    def failed(*_args, **_kwargs):
        raise TimeoutError("synthetic transport loss")

    monkeypatch.setattr(seen[0][0], "stage", failed)
    with pytest.raises(TimeoutError, match="transport loss"):
        materializer(candidate)
    assert env.sink.calls == env.catalogs == []
    with pytest.raises(PublicationSafetyError, match="not_materialized"):
        materializer.commit_attempt(expected_revision="0", request_id="not-staged")


def test_injected_reader_remains_pinned_and_legacy_callbacks_refuse(
    tmp_path, monkeypatch,
):
    _inject(monkeypatch)
    env, materializer, broker, control, candidate, _calls = (
        existing.materializer_fixture(tmp_path, monkeypatch)
    )
    result = materializer(candidate)
    reference = AttemptReference.parse(result["attempt_reference"])
    broker.grant(control.session, reference, digest=env.context.authorization_digest)
    materializer.commit_attempt(expected_revision=control.revision, request_id="publish")
    assert materializer.reader.active()[1]["attempt_reference"] == reference.as_dict()
    assert materializer.publication_protocol == PROTOCOL
    with pytest.raises(PublicationSafetyError, match="use_bind_attempt"):
        materializer.bind(owner_id="A", fence=1, predecessor=None, pointer_etag=None)
    recovery.test_actual_attempt_materializer_bound_method_rejected_before_use(
        tmp_path / "legacy", monkeypatch,
    )
    assert env.sink.calls == env.catalogs == []
