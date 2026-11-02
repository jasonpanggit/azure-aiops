"""Real provider composition through high-level injection, offline transports only."""

from ontology_discovery.immutable_attempt import ImmutableAttemptProtocol
from ontology_discovery.maintenance_materialization import (
    CandidateGenerationMaterializer,
)
from tests import test_sql_blob_broker as existing
from tests.test_attempt_consumer_injection import HighLevelClient
from tests.test_sql_blob_broker import fx

__all__ = ["fx"]


def test_actual_composition_high_level_materializer_reader_restore_and_recovery(
    fx, tmp_path, monkeypatch,
):
    injected = []

    def protocol(boundary):
        return HighLevelClient(ImmutableAttemptProtocol(boundary))

    def construct(**kwargs):
        client = protocol(kwargs.pop("attempt_boundary"))
        injected.append(client)
        return CandidateGenerationMaterializer(**kwargs, attempt_protocol=client)

    monkeypatch.setattr(existing, "CandidateGenerationMaterializer", construct)
    monkeypatch.setattr(existing, "ImmutableAttemptProtocol", protocol)
    existing.test_actual_materializer_batch_provider_commit_reader_and_independent_restore(
        fx, tmp_path, monkeypatch,
    )
    assert len(injected) == 1
