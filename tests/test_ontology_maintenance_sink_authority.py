"""Narrow offline proofs for maintenance sink exclusion and restore authority."""

# ruff: noqa: F401,F811  (imported fixture symbols are discovered by pytest)

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from fabric.auth import FabricAuthConfig
from fabric.config import FabricRuntimeConfig
from fabric.data_quality import DataQualityValidator
from fabric.dataset_mapper import ontology_relationship_table
from fabric.schema_registry import schema_for
from fabric.sync_service import FabricSyncService, ontology_generation_products
from ontology_discovery.maintenance_admission import (
    MaintenanceAuthorizer,
    vocabulary_fingerprint,
)
from ontology_discovery.maintenance_materialization import (
    CandidateGenerationMaterializer,
    MaintenanceOwnershipLost,
)
from ontology_discovery.maintenance_release import MaintenanceDenied
from ontology_discovery.publisher import PublicationSafetyError
from ontology_discovery.publisher_cli import (
    MaintenanceRuntimeBindings,
    PublisherRuntimeConfig,
    build_publisher_runtime,
)
from storage.datasets import DatasetStore, GenerationPointerConditions
from storage.delta_writer import DeltaWriteMode, DeltaWriter
from storage.onelake_documents import OneLakeDocumentStore
from storage.onelake_writer import OneLakeWriter
from tests.test_ontology_maintenance_admission import (
    NOW,
    Authority,
    authority,
    inventory_datasets,
)
from tests.test_ontology_maintenance_materialization import Real
from tests.test_ontology_maintenance_publication import active, dispatched


def _bind_authority_target(authority: Authority, *, workspace="workspace", item="lakehouse"):
    payload = authority.payload()
    payload["release"].update(
        workspace_id=workspace,
        item_id=item,
        definition_fingerprint=vocabulary_fingerprint(),
    )
    authority.envelope = authority.sign(payload)
    return {
        "tenant_id": "tenant-1",
        "subscription_id": "sub-1",
        "connection_id": "offline-connection",
        "workspace_id": workspace,
        "item_id": item,
        "definition_fingerprint": vocabulary_fingerprint(),
    }


def _signed_restore_authorizer(authority, target, *, generation="generation-old", content="sha256:content-old", authorization="sha256:authorized-old"):
    payload = authority.payload()
    release = payload["release"]
    release.update(
        tenant_id=target["tenant_id"],
        subscription_id=target["subscription_id"],
        connection_id=target["connection_id"],
        workspace_id=target["workspace_id"],
        item_id=target["item_id"],
        definition_fingerprint=target["definition_fingerprint"],
        operations=["restore"],
    )
    signed_target = {
        **target,
        "generation_id": generation,
        "content_hash": content,
        "definition_fingerprint": target["definition_fingerprint"],
        "authorization_digest": authorization,
    }
    release["restore_target"] = signed_target
    authority.envelope = authority.sign(payload)
    return (
        MaintenanceAuthorizer(reader=authority.reader(), store=object()),
        signed_target,
    )


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("tenant_id", "tenant-other"),
        ("subscription_id", "subscription-other"),
        ("connection_id", "connection-other"),
        ("workspace_id", "workspace-other"),
        ("item_id", "item-other"),
        ("content_hash", "sha256:other-content"),
        ("generation_id", "generation-other"),
        ("definition_fingerprint", "sha256:other-definition"),
    ],
)
def test_signed_restore_authority_rejects_wrong_target_and_retained_content(
    authority: Authority, field, replacement
):
    target = _bind_authority_target(authority)
    authorizer, signed_target = _signed_restore_authorizer(authority, target)
    expected = dict(signed_target)
    expected[field] = replacement
    with pytest.raises(MaintenanceDenied):
        authorizer.authorize_restore(expected_target=expected)


def test_restore_authority_is_refreshed_and_revocation_denies_next_physical_write(
    tmp_path, authority: Authority
):
    target = _bind_authority_target(authority)
    authorizer, signed_target = _signed_restore_authorizer(authority, target)
    source = tmp_path / "source"
    source.mkdir()
    delta = DeltaWriter()
    onelake = OneLakeWriter("workspace", "lakehouse", local_root=tmp_path / "lake")
    service = FabricSyncService(
        source_root=source,
        onelake=onelake,
        delta_writer=delta,
        validator=DataQualityValidator(),
    )
    storage = DatasetStore(tmp_path / "publication").authoritative_publisher(
        publisher_identity="publisher-uai",
        approved_publisher_identity="publisher-uai",
    )
    documents = OneLakeDocumentStore(str(tmp_path / "publication"))

    def revoke_second_write(point):
        if point == "before_table_write:2":
            authority.control["kill"] = True

    materializer = CandidateGenerationMaterializer(
        storage=storage,
        documents=documents,
        service=service,
        authorizer=authorizer,
        target_id="local-target",
        clock=lambda: NOW,
        expected_target=target,
        definition_fingerprint=vocabulary_fingerprint,
        fault=revoke_second_write,
    )
    materializer.bind(owner_id="restore-worker", fence=1, predecessor=None, pointer_etag=None)
    materializer._acquire()
    materializer._restore_expected = signed_target
    materializer._restore_pointer = (None, None)
    rows = inventory_datasets()
    expected = ontology_generation_products(
        rows["ontology_entities"],
        rows["ontology_relationships"],
        generation_id=signed_target["generation_id"],
        source_generation="source-old",
        content_hash=signed_target["content_hash"],
        authorization_digest=signed_target["authorization_digest"],
        attestation_digest="sha256:original-attestation",
        validation={"passed": True},
    )
    before = {
        table: delta.version(onelake.table_uri(*table.split("_", 1)))
        for table in expected
    }
    try:
        with pytest.raises(MaintenanceDenied):
            service.materialize_ontology_generation(
                entities=rows["ontology_entities"],
                relationships=rows["ontology_relationships"],
                generation_id=signed_target["generation_id"],
                source_generation="source-old",
                content_hash=signed_target["content_hash"],
                authorization_digest=signed_target["authorization_digest"],
                attestation_digest="sha256:original-attestation",
                validation={"passed": True},
                guard=materializer._guard_write,
            )
    finally:
        materializer.release()
    after = {
        table: delta.version(onelake.table_uri(*table.split("_", 1)))
        for table in expected
    }
    assert sum(before[name] != after[name] for name in expected) == 1
    assert authority.control["kill"] is True


def test_remote_sink_cannot_be_mistaken_for_a_qualified_local_mutation_lock(tmp_path):
    with pytest.raises(PublicationSafetyError, match="remote_mutation_lock_unqualified"):
        CandidateGenerationMaterializer(
            storage=object(),
            documents=object(),
            service=SimpleNamespace(onelake=SimpleNamespace(local_root=None)),
            authorizer=None,
            target_id="remote-target",
            clock=lambda: NOW,
            expected_target={},
        )


def test_local_target_lock_serializes_inflight_delta_write_before_new_winner(
    tmp_path,
):
    """The old sink commit finishes before the new owner can write/promote."""
    root = tmp_path / "local-lake"
    source = tmp_path / "source"
    source.mkdir()
    publication = DatasetStore(tmp_path / "publication").authoritative_publisher(
        publisher_identity="publisher-uai",
        approved_publisher_identity="publisher-uai",
    )
    publication.stage_generation(
        "winner",
        manifest={"generation_id": "winner", "complete": True},
        entities=[],
        relationships=[],
        lineage={},
        validation={},
        compatibility={},
    )
    docs = OneLakeDocumentStore(str(tmp_path / "publication"))
    now = [NOW]
    target = {
        "tenant_id": "tenant-1",
        "subscription_id": "sub-1",
        "connection_id": "offline-connection",
        "workspace_id": "workspace",
        "item_id": "lakehouse",
        "definition_fingerprint": vocabulary_fingerprint(),
    }

    def materializer(owner, fence):
        service = FabricSyncService(
            source_root=source,
            onelake=OneLakeWriter("workspace", "lakehouse", local_root=root),
            delta_writer=DeltaWriter(),
            validator=DataQualityValidator(),
        )
        item = CandidateGenerationMaterializer(
            storage=publication,
            documents=docs,
            service=service,
            authorizer=None,
            target_id="shared-ontology-target",
            clock=lambda: now[0],
            expected_target=target,
            definition_fingerprint=vocabulary_fingerprint,
        )
        item.bind(owner_id=owner, fence=fence, predecessor=None, pointer_etag=None)
        return item

    old, new = materializer("old-holder", 1), materializer("new-holder", 2)
    old._acquire()
    old._mutation_lock.acquire()
    old.lease.assert_held()
    uri = old._service.onelake.table_uri("ontology", "entities")
    stale_row = dict(inventory_datasets()["ontology_entities"][0], name="stale-old")
    winner_row = dict(
        inventory_datasets()["ontology_entities"][0],
        name="new-winner",
        change_version="winner-version",
    )
    paused = threading.Event()
    resume = threading.Event()
    new_started = threading.Event()
    errors = []

    def old_sink_write():
        try:
            old.lease.assert_held()  # the real scheduling gap: guard already passed
            paused.set()
            assert resume.wait(10)
            old._service.delta.write(
                uri, [stale_row], mode=DeltaWriteMode.OVERWRITE,
                schema=schema_for("ontology_entities"),
            )
            with pytest.raises(MaintenanceOwnershipLost):
                old.lease.assert_held()
            old.release()
        except Exception as exc:  # noqa: BLE001 - propagate worker-thread errors
            errors.append(exc)

    def new_owner():
        try:
            new_started.set()
            new._acquire()
            new._mutation_lock.acquire()  # same OS lock blocks until old sink exits
            new.lease.assert_held()
            new._service.delta.write(
                uri, [winner_row], mode=DeltaWriteMode.OVERWRITE,
                schema=schema_for("ontology_entities"),
            )
            pointer = publication.read_pointer()
            publication.conditional_promote(
                generation_id="winner",
                source_generation="source-winner",
                owner_id="new-holder",
                fence=2,
                conditions=GenerationPointerConditions.from_snapshot(pointer),
            )
            new.release()
        except Exception as exc:  # noqa: BLE001 - propagate worker-thread errors
            errors.append(exc)

    old_thread = threading.Thread(target=old_sink_write)
    old_thread.start()
    assert paused.wait(10)
    now[0] += timedelta(minutes=6)
    new_thread = threading.Thread(target=new_owner)
    new_thread.start()
    assert new_started.wait(10)
    # The successor owns a newer lease, but cannot mutate the physical sink
    # until the in-flight predecessor write has completed and released flock.
    resume.set()
    old_thread.join(10)
    new_thread.join(10)
    assert not old_thread.is_alive() and not new_thread.is_alive()
    assert not errors
    assert publication.read_pointer().pointer.active_generation == "winner"
    assert new._service.delta.read(uri)[0]["name"] == "new-winner"


def test_builder_composes_qualified_maintenance_worker_to_real_delta(
    tmp_path, monkeypatch, authority: Authority
):
    target = _bind_authority_target(authority)
    env = dispatched(tmp_path, monkeypatch, authority)
    source = tmp_path / "builder-source"
    source.mkdir()
    service = FabricSyncService(
        source_root=source,
        onelake=OneLakeWriter("workspace", "lakehouse", local_root=tmp_path / "builder-lake"),
        delta_writer=DeltaWriter(),
        validator=DataQualityValidator(),
    )

    import ontology_discovery.publisher_cli as cli

    runtime_config = FabricRuntimeConfig(
        auth=FabricAuthConfig(mode="managed_identity", managed_identity_client_id="publisher-uai"),
        source_data_root=source,
        workspace_id="workspace",
        lakehouse_id="lakehouse",
        local_onelake_root=tmp_path / "builder-lake",
    )
    monkeypatch.setattr(
        FabricRuntimeConfig,
        "load",
        classmethod(lambda _cls, _path: runtime_config),
    )
    def build_runtime(_config, *, mode):
        assert mode is cli.FabricRuntimeMode.PUBLISH
        return SimpleNamespace(service=service)

    monkeypatch.setattr(cli, "build_runtime", build_runtime)
    authorizer = MaintenanceAuthorizer(
        reader=authority.reader(),
        store=env.store,
        trusted_records=Real(
            tmp_path,
            env,
            authority,
        ).authorizer._trusted,
    )
    publication_root = tmp_path / "builder-publication"
    roots = {
        "connection": str(tmp_path / "builder-connections"),
        "command": str(tmp_path / "builder-commands"),
        "dispatch": str(env.dispatch_path),
        "publication": str(publication_root),
    }
    bindings = MaintenanceRuntimeBindings(
        authorizer=authorizer,
        definition_fingerprint=vocabulary_fingerprint,
        expected_target=target,
    )
    worker, _intake = build_publisher_runtime(
        PublisherRuntimeConfig(
            roots=roots,
            fabric_config=str(tmp_path / "unused-fabric-config.yaml"),
            publisher_client_id="publisher-uai",
            runtime_mode="local",
            capabilities={},
        ),
        maintenance=bindings,
    )
    result = worker.run_once(now=datetime.now(UTC), limit=1)
    assert result["succeeded"] == 1, result
    storage = DatasetStore(publication_root).authoritative_publisher(
        publisher_identity="publisher-uai",
        approved_publisher_identity="publisher-uai",
    )
    generation = active(storage)
    assert generation
    staged = storage.read_generation(generation)
    model = next(row for row in staged["relationships"] if row["source"] == "model")
    uri = service.onelake.table_uri("ontology", "relationships")
    assert model["resource_id"] in {
        row["resource_id"] for row in service.delta.read(uri)
    }
    typed = ontology_relationship_table(
        model["subject_type"], model["predicate"], model["object_type"]
    )
    typed_uri = service.onelake.table_uri("ontology", typed.removeprefix("ontology_"))
    assert model["resource_id"] in {
        row["resource_id"] for row in service.delta.read(typed_uri)
    }
    product_reader = worker._materialize.reader
    assert product_reader.active()[0] == generation
    assert product_reader.read_ontology()[1]
