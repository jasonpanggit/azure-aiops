"""Plan 14-06 Task 1: exact staged-generation product materialization (offline).

Real DeltaWriter/OneLakeWriter/DatasetStore/worker composition; only remote
acquisition and identity are fixtures.
"""

# ruff: noqa: F811  (pytest fixture re-import)

from __future__ import annotations

from fabric.data_quality import DataQualityValidator
from fabric.dataset_mapper import ontology_relationship_table
from fabric.sync_service import FabricSyncService
from ontology.ontology_validator import OntologyValidator
from ontology_discovery.dispatch_store import PublisherDispatchStore
from ontology_discovery.maintenance_admission import (
    MaintenanceAuthorizer,
    vocabulary_fingerprint,
)
from ontology_discovery.maintenance_consumers import (
    MaintenanceConsumerCheck,
)
from ontology_discovery.maintenance_materialization import (
    CandidateGenerationMaterializer,
    ProductConsumerPorts,
)
from ontology_discovery.maintenance_relationships import FirstAdmissionLedger
from ontology_discovery.publisher import OntologyGenerationPublisher
from ontology_discovery.publisher_worker import PublisherWorker
from storage.datasets import DatasetStore
from storage.delta_writer import DeltaWriter
from storage.locking import MonotonicFenceAllocator
from storage.onelake_documents import OneLakeDocumentStore
from storage.onelake_writer import OneLakeWriter
from tests.test_ontology_maintenance_admission import (  # noqa: F401
    NOW,
    authority,
)
from tests.test_ontology_maintenance_publication import active, dispatched


class Real:
    """Production-shaped composition over real local stores."""

    def __init__(
        self, tmp_path, env, authority, *, fault=None, worker_now=NOW, product_clock=None
    ):
        self.tmp = tmp_path
        self.env = env
        self.env_authority = authority
        release = authority.envelope["payload"]["release"]
        target = {
            "tenant_id": str(release["tenant_id"]),
            "subscription_id": str(release["subscription_id"]),
            "connection_id": str(release["connection_id"]),
            "workspace_id": str(release["workspace_id"]),
            "item_id": str(release["item_id"]),
            "definition_fingerprint": str(release["definition_fingerprint"]),
        }
        (tmp_path / "src_root").mkdir(exist_ok=True)
        self.delta = DeltaWriter()
        self.service = FabricSyncService(
            source_root=tmp_path / "src_root",
            onelake=OneLakeWriter(
                target["workspace_id"], target["item_id"], local_root=tmp_path / "lake"
            ),
            delta_writer=self.delta,
            validator=DataQualityValidator(),
        )
        dataset = DatasetStore(str(tmp_path / "publication"))
        self.storage = dataset.authoritative_publisher(
            publisher_identity="publisher-uai", approved_publisher_identity="publisher-uai"
        )
        self.authorizer = MaintenanceAuthorizer(
            reader=authority.reader(), store=env.store,
            trusted_records=FirstAdmissionLedger(env.tmp / "ledger.json").reader(),
        )
        self.materializer = CandidateGenerationMaterializer(
            storage=self.storage, documents=OneLakeDocumentStore(str(tmp_path / "publication")),
            service=self.service, authorizer=self.authorizer, target_id="t1",
            clock=product_clock or (lambda: worker_now), fault=fault,
            expected_target=target,
            definition_fingerprint=lambda: vocabulary_fingerprint(),
        )
        self.service.ontology_product_reader = self.materializer.reader
        ports = ProductConsumerPorts(
            storage=self.storage, reader=self.materializer.reader, service=self.service,
            definition_fingerprint=vocabulary_fingerprint, clock=lambda: NOW,
        )
        check = MaintenanceConsumerCheck(
            ports=ports.ports(), definition_fingerprint=vocabulary_fingerprint,
            clock=lambda: NOW,
        )
        publisher = OntologyGenerationPublisher(
            self.storage, validator=OntologyValidator(),
            approved_publisher_identity="publisher-uai",
        )
        self.worker = PublisherWorker(
            dispatches=PublisherDispatchStore(str(env.dispatch_path)).publisher(),
            publisher=publisher, publisher_identity="publisher-uai", owner_id="worker-1",
            fence_allocator=MonotonicFenceAllocator(OneLakeDocumentStore(str(env.dispatch_path))),
            materialize=self.materializer, consumer_check=check, now=lambda: worker_now,
            maintenance_authorizer=self.authorizer,
        )

    def table(self, name):
        return self.delta.read(
            self.service.onelake.table_uri("ontology", name.split("_", 1)[1])
        )


def test_materializes_exact_candidate_products(tmp_path, monkeypatch, authority):
    env = dispatched(tmp_path, monkeypatch, authority)
    real = Real(tmp_path, env, authority)
    result = real.worker.run_once(now=NOW, limit=1)
    assert result["succeeded"] == 1, result
    gen = active(real.storage)
    assert gen
    staged = real.storage.read_generation(gen)
    model = [r for r in staged["relationships"] if r["source"] == "model"]
    assert model
    generation, receipt = real.materializer.reader.active()
    assert generation == gen and receipt["generation_id"] == gen
    me = model[0]
    key = lambda r: (r["subject_id"], r["predicate"], r["object_id"])
    canonical = real.table("ontology_relationships")
    assert key(me) in {key(r) for r in canonical}
    # Inverse membership edges from deterministic admission survive.
    assert any(r["predicate"] == "member_of" for r in canonical)
    typed_name = ontology_relationship_table(
        me["subject_type"], me["predicate"], me["object_type"]
    )
    assert typed_name in receipt["products"]
    assert key(me) in {key(r) for r in real.table(typed_name)}
    assert real.materializer.reader.verify(receipt)
    _, relationships = real.materializer.reader.read_ontology()
    assert key(me) in {key(r) for r in relationships}
    assert len(receipt["products"]) > 50


def _boom_at(point):
    def fault(name):
        if name == point:
            raise RuntimeError(f"injected:{point}")

    return fault


def test_partial_write_never_promotes_and_reader_stays_empty(tmp_path, monkeypatch, authority):
    env = dispatched(tmp_path, monkeypatch, authority)
    real = Real(tmp_path, env, authority, fault=_boom_at("before_table_write:5"))
    result = real.worker.run_once(now=NOW, limit=1)
    assert result["succeeded"] == 0 and result["failed"] == 1
    assert active(real.storage) is None
    # No receipt => pinned reader exposes nothing; deterministic default intact.
    assert real.materializer.reader.read_ontology() == ([], [])


def test_tampered_product_write_is_rejected_by_readback(tmp_path, monkeypatch, authority):
    env = dispatched(tmp_path, monkeypatch, authority)
    real = Real(tmp_path, env, authority)
    original = real.service.materialize_ontology_generation

    def tampered(*, entities, relationships, **kw):
        rels = [r for r in relationships if r.get("source") != "model"]
        return original(entities=entities, relationships=rels, **kw)

    real.service.materialize_ontology_generation = tampered
    result = real.worker.run_once(now=NOW, limit=1)
    assert result["succeeded"] == 0
    assert active(real.storage) is None
    assert real.materializer.reader.read_ontology() == ([], [])


def test_completed_only_callback_is_not_success_without_bound_materializer(
    tmp_path, monkeypatch, authority
):
    env = dispatched(tmp_path, monkeypatch, authority)
    real = Real(tmp_path, env, authority)
    real.worker._materialize = lambda candidate: {"status": "completed"}
    result = real.worker.run_once(now=NOW, limit=1)
    assert result["succeeded"] == 0 and active(real.storage) is None


def test_runtime_selection_fails_closed_without_bindings():
    import pytest

    from ontology_discovery.maintenance_release import MaintenanceConfigError
    from ontology_discovery.publisher_cli import (
        MaintenanceRuntimeBindings,
        PublisherRuntimeConfig,
        build_publisher_runtime,
    )

    def config(mode):
        return PublisherRuntimeConfig(
            roots={}, fabric_config="", publisher_client_id="x",
            runtime_mode=mode, capabilities={},
        )

    bad = MaintenanceRuntimeBindings(authorizer=object(), definition_fingerprint=lambda: "x")
    with pytest.raises(MaintenanceConfigError):
        build_publisher_runtime(config("local"), maintenance=bad)

    class Good:
        def authorize(self, *a, **k): ...
        def authorize_restore(self, *a, **k): ...

    live = MaintenanceRuntimeBindings(authorizer=Good(), definition_fingerprint=lambda: "x")
    with pytest.raises(MaintenanceConfigError, match="live_bindings_unapproved"):
        build_publisher_runtime(config("production"), maintenance=live)
