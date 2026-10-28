"""Pinned normalized-source provenance and exact retained-generation replay."""

import copy
import json
from types import SimpleNamespace

import pytest

from onboarding.activation import publish_combined_snapshot
from storage.datasets import (
    COMBINED_ACTIVATION_QUERY_VERSION,
    DatasetStore,
    _manifest_integrity_hash,
)


def _publish(root, run, marker):
    return DatasetStore(root).publish(
        {
            "entities/Resource": [
                {"id": marker, "entityType": "Resource", "name": marker}
            ],
            "relationships/relationships": [],
            "changes/resource_changes": [],
        },
        {},
        {
            "runId": run,
            "status": "completed",
            "startedAt": "2026-10-28T01:00:00Z",
            "completedAt": "2026-10-28T01:01:00Z",
            "subscriptions": [f"subscription-{marker}"],
            "queryVersion": "discovery-query-v1",
        },
        ontology={},
    )


def _service(roots):
    return SimpleNamespace(
        registry=SimpleNamespace(
            get=lambda name: SimpleNamespace(connection_id=name),
        ),
        sync_coordinator=SimpleNamespace(
            connection_output_dir=lambda connection: roots[connection.connection_id],
        ),
    )


def _combined(tmp_path):
    roots = {"alpha": tmp_path / "alpha", "beta": tmp_path / "beta"}
    _publish(roots["alpha"], "z-source", "alpha-resource")
    _publish(roots["beta"], "a-source", "beta-resource")
    target = tmp_path / "combined"
    manifest = publish_combined_snapshot(_service(roots), ["beta", "alpha"], target)
    return roots, target, manifest


def test_source_pairs_are_explicit_not_zipped_sorted_lists(tmp_path):
    _, target, manifest = _combined(tmp_path)
    assert manifest["sourceConnectionIds"] == ["alpha", "beta"]
    assert manifest["sourceRunIds"] == ["a-source", "z-source"]
    sources = manifest["sourceProvenance"]["sources"]
    assert [(s["connectionId"], s["runId"]) for s in sources] == [
        ("alpha", "z-source"),
        ("beta", "a-source"),
    ]
    assert all(s["representation"] == "normalized_snapshot" for s in sources)
    assert all(
        set(s)
        == {
            "connectionId",
            "runId",
            "manifestIntegrityHash",
            "startedAt",
            "completedAt",
            "subscriptions",
            "queryVersion",
            "representation",
        }
        for s in sources
    )
    assert sources[0]["subscriptions"] == ["subscription-alpha-resource"]
    assert sources[0]["queryVersion"] == "discovery-query-v1"
    assert (
        DatasetStore(target).verify_combined_activation_generation(manifest["runId"])
        == manifest
    )


def test_source_pointer_movement_cannot_mix_verified_rows(tmp_path, monkeypatch):
    root = tmp_path / "source"
    first = _publish(root, "first", "original")
    original = DatasetStore.read_verified_generation

    def moving_current(self, generation_id, **kwargs):
        result = original(self, generation_id, **kwargs)
        if self.root == root:
            _publish(root, "later", "replacement")
        return result

    monkeypatch.setattr(DatasetStore, "read_verified_generation", moving_current)
    target = tmp_path / "combined"
    manifest = publish_combined_snapshot(_service({"demo": root}), ["demo"], target)
    assert manifest["sourceRunIds"] == [first["runId"]]
    assert DatasetStore(target).read_dataset("entities/Resource")[0]["id"] == "original"
    assert (
        DatasetStore(root).read_dataset("entities/Resource")[0]["id"] == "replacement"
    )


@pytest.mark.parametrize("corruption", ["rows", "metadata", "missing", "incomplete"])
def test_corrupt_source_fails_before_combined_publication(tmp_path, corruption):
    root = tmp_path / "source"
    _publish(root, "source-run", "original")
    generation = root / "generations/source-run"
    if corruption == "rows":
        (generation / "entities/Resource.jsonl").write_text('{"id":"altered"}\n')
    elif corruption == "missing":
        (generation / "entities/Resource.jsonl").unlink()
    else:
        path = generation / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest["status" if corruption == "incomplete" else "completedAt"] = (
            "failed" if corruption == "incomplete" else "2026-10-28T02:00:00Z"
        )
        path.write_text(json.dumps(manifest))
    target = tmp_path / "combined"
    with pytest.raises((ValueError, FileNotFoundError)):
        publish_combined_snapshot(_service({"demo": root}), ["demo"], target)
    assert not (target / "current").exists()
    assert not list(target.glob("generations/*/manifest.json"))


def test_reuse_compares_connection_run_pairing_not_only_sets(tmp_path):
    roots, target, first = _combined(tmp_path)
    swapped = {"alpha": roots["beta"], "beta": roots["alpha"]}
    second = publish_combined_snapshot(
        _service(swapped), ["alpha", "beta"], target, reuse_unchanged=True
    )
    assert first["sourceRunIds"] == second["sourceRunIds"]
    assert first["sourceConnectionIds"] == second["sourceConnectionIds"]
    assert first["runId"] != second["runId"]
    assert first["sourceProvenance"] != second["sourceProvenance"]


@pytest.mark.parametrize("corrupt", [False, True])
def test_unchanged_reuse_verifies_retained_combined_artifacts(tmp_path, corrupt):
    roots, target, first = _combined(tmp_path)
    if corrupt:
        path = target / "generations" / first["runId"] / "entities/Resource.jsonl"
        path.write_text('{"id":"corrupted"}\n')
        with pytest.raises(ValueError):
            publish_combined_snapshot(
                _service(roots), ["alpha", "beta"], target, reuse_unchanged=True
            )
    else:
        reused = publish_combined_snapshot(
            _service(roots), ["alpha", "beta"], target, reuse_unchanged=True
        )
        assert reused == first


def test_exact_replay_does_not_need_pruned_upstream_generations(tmp_path):
    roots, target, combined = _combined(tmp_path)
    for index in range(5):
        _publish(roots["alpha"], f"next-{index}", str(index))
    assert not (roots["alpha"] / "generations/z-source").exists()
    assert (
        DatasetStore(target).verify_combined_activation_generation(combined["runId"])
        == combined
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "version",
        "missing_source",
        "duplicate_connection",
        "wrong_run",
        "bad_hash",
        "naive_time",
        "reversed_time",
        "raw_claim",
        "extra_field",
        "scope",
        "query_version",
    ],
)
def test_malformed_provenance_rejected_even_with_recomputed_hash(tmp_path, mutation):
    _, target, combined = _combined(tmp_path)
    path = target / "generations" / combined["runId"] / "manifest.json"
    manifest = copy.deepcopy(combined)
    provenance = manifest["sourceProvenance"]
    source = provenance["sources"][0]
    if mutation == "version":
        provenance["contract"] = "unknown"
    elif mutation == "missing_source":
        provenance["sources"].pop()
    elif mutation == "duplicate_connection":
        provenance["sources"][1]["connectionId"] = source["connectionId"]
    elif mutation == "wrong_run":
        source["runId"] = "different-run"
    elif mutation == "bad_hash":
        source["manifestIntegrityHash"] = "not-a-digest"
    elif mutation == "naive_time":
        source["startedAt"] = "2026-10-28T01:00:00"
    elif mutation == "reversed_time":
        source["completedAt"] = "2026-10-27T01:00:00Z"
    elif mutation == "raw_claim":
        source["representation"] = "pristine_provider_payload"
    elif mutation == "scope":
        source["subscriptions"] = ["sub", "sub"]
    elif mutation == "query_version":
        source["queryVersion"] = False
    else:
        source["credentials"] = "not-permitted"
    manifest["integrityHash"] = _manifest_integrity_hash(manifest)
    path.write_text(json.dumps(manifest))
    with pytest.raises((ValueError, TypeError)):
        DatasetStore(target).verify_combined_activation_generation(combined["runId"])


def test_legacy_manifest_remains_replayable_without_invented_pairing(tmp_path):
    _, target, combined = _combined(tmp_path)
    path = target / "generations" / combined["runId"] / "manifest.json"
    del combined["sourceProvenance"]
    combined["integrityHash"] = _manifest_integrity_hash(combined)
    path.write_text(json.dumps(combined))
    verified = DatasetStore(target).verify_combined_activation_generation(
        combined["runId"]
    )
    assert "sourceProvenance" not in verified
    assert verified["queryVersion"] == COMBINED_ACTIVATION_QUERY_VERSION


def test_missing_legacy_source_timestamp_remains_unknown(tmp_path):
    root = tmp_path / "source"
    _publish(root, "run", "resource")
    path = root / "generations/run/manifest.json"
    manifest = json.loads(path.read_text())
    del manifest["completedAt"]
    manifest["integrityHash"] = _manifest_integrity_hash(manifest)
    path.write_text(json.dumps(manifest))
    target = tmp_path / "combined"
    combined = publish_combined_snapshot(_service({"demo": root}), ["demo"], target)
    assert combined["sourceProvenance"]["sources"][0]["completedAt"] is None


def test_duplicate_connections_rejected_before_target_creation(tmp_path):
    root = tmp_path / "source"
    _publish(root, "run", "resource")
    with pytest.raises(ValueError, match="Duplicate"):
        publish_combined_snapshot(
            _service({"demo": root}), ["demo", "demo"], tmp_path / "combined"
        )


def test_reused_run_id_selects_exact_writer_suffixed_generation(tmp_path):
    root = tmp_path / "source"
    _publish(root, "same-run", "original")
    _publish(root, "same-run", "replacement")
    target = tmp_path / "combined"
    combined = publish_combined_snapshot(_service({"demo": root}), ["demo"], target)
    assert combined["sourceRunIds"] == ["same-run"]
    assert DatasetStore(target).read_dataset("entities/Resource")[0]["id"] == "replacement"


def test_source_run_ids_are_namespaced_by_connection(tmp_path):
    roots = {"alpha": tmp_path / "alpha", "beta": tmp_path / "beta"}
    for connection, root in roots.items():
        _publish(root, "same-run", connection)
    target = tmp_path / "combined"
    combined = publish_combined_snapshot(_service(roots), ["alpha", "beta"], target)
    assert combined["sourceRunIds"] == ["same-run", "same-run"]
    assert len(combined["sourceProvenance"]["sources"]) == 2
    assert DatasetStore(target).verify_combined_activation_generation(
        combined["runId"]
    ) == combined


def test_writer_sanitized_source_id_round_trips_without_current_reread(tmp_path):
    root = tmp_path / "source"
    source = _publish(root, "run-2026-10-28T01:00:00Z", "original")
    target = tmp_path / "combined"
    combined = publish_combined_snapshot(_service({"demo": root}), ["demo"], target)
    assert combined["sourceRunIds"] == [source["runId"]]
    assert DatasetStore(target).read_dataset("entities/Resource")[0]["id"] == "original"
    selected = DatasetStore(root).current_generation()
    with pytest.raises(ValueError, match="does not match"):
        DatasetStore(root).read_verified_generation(
            str(selected).split("/")[-1], expected_run_id="wrong-run",
        )


@pytest.mark.parametrize("corrupt", [False, True])
def test_remote_source_uses_same_integrity_contract(tmp_path, monkeypatch, corrupt):
    from fsspec.implementations.memory import MemoryFileSystem

    import storage.fs

    root = tmp_path / "local"
    original = _publish(root, "remote-run", "resource")
    fs = MemoryFileSystem()
    remote_root = f"/f04-{tmp_path.name}"
    generation = root / "generations/remote-run"
    for path in generation.rglob("*"):
        if path.is_file():
            destination = (
                f"{remote_root}/generations/remote-run/{path.relative_to(generation)}"
            )
            fs.pipe(destination, path.read_bytes())
    fs.pipe(
        f"{remote_root}/current.json",
        json.dumps({"generation": "remote-run"}).encode(),
    )
    if corrupt:
        fs.pipe(
            f"{remote_root}/generations/remote-run/entities/Resource.jsonl",
            b'{"id":"corrupted"}\n',
        )
    monkeypatch.setattr(storage.fs, "resolve_fs", lambda uri: (fs, remote_root))
    uri = "abfss://workspace@onelake.dfs.fabric.microsoft.com/lakehouse/Files/source"
    target = tmp_path / "combined"
    if corrupt:
        with pytest.raises(ValueError, match="integrity"):
            publish_combined_snapshot(_service({"demo": uri}), ["demo"], target)
        assert not (target / "current").exists()
    else:
        manifest = publish_combined_snapshot(_service({"demo": uri}), ["demo"], target)
        assert (
            manifest["sourceProvenance"]["sources"][0]["manifestIntegrityHash"]
            == (original["integrityHash"])
        )
        assert (
            DatasetStore(target).read_dataset("entities/Resource")[0]["id"]
            == "resource"
        )


def test_local_source_generation_cannot_escape_store(tmp_path):
    root = tmp_path / "source"
    outside = tmp_path / "outside"
    _publish(outside, "run", "resource")
    store = DatasetStore(root)
    (root / "generations/run").symlink_to(
        outside / "generations/run", target_is_directory=True
    )
    with pytest.raises(ValueError):
        store.verify_generation("run")


def test_declared_metadata_unknowns_are_preserved_not_invented(tmp_path):
    root = tmp_path / "source"
    _publish(root, "run", "resource")
    path = root / "generations/run/manifest.json"
    manifest = json.loads(path.read_text())
    del manifest["subscriptions"]
    del manifest["queryVersion"]
    manifest["integrityHash"] = _manifest_integrity_hash(manifest)
    path.write_text(json.dumps(manifest))
    combined = publish_combined_snapshot(
        _service({"demo": root}), ["demo"], tmp_path / "combined"
    )
    source = combined["sourceProvenance"]["sources"][0]
    assert source["subscriptions"] is None
    assert source["queryVersion"] is None
