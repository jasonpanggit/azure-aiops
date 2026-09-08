from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import pyarrow.parquet as pq
import pytest

import storage.datasets as datasets_module
from onboarding.graph_normalize import Normalizer
from onboarding.ingestion_storage import DatasetStore
from storage.datasets import DatasetStore as NeutralDatasetStore

FIXTURE = Path(__file__).parent / "fixtures" / "mock_arg_responses.json"


def test_store_writes_jsonl_parquet_and_ontology_metadata(tmp_path: Path) -> None:
    payload = json.loads(FIXTURE.read_text())
    graph = Normalizer().normalize(payload, datetime(2026, 8, 17, tzinfo=UTC))
    store = DatasetStore(tmp_path)

    manifest = store.publish(graph, payload, {"runId": "run-1"})

    assert (tmp_path / "current/entities/VirtualMachine.jsonl").exists()
    parquet = tmp_path / "current/entities/VirtualMachine.parquet"
    assert parquet.exists()
    assert pq.read_table(parquet).num_rows == 1
    ontology = json.loads((tmp_path / "current/ontology/ontology.json").read_text())
    assert "VirtualMachine" in ontology["entityTypes"]
    assert "belongsTo" in ontology["relationshipTypes"]
    assert manifest["datasets"]["entities/VirtualMachine"]["rowCount"] == 1
    assert (tmp_path / "current").is_symlink() or sys.platform == "win32"
    assert not (tmp_path / "current/queries/resources.jsonl").exists()


def test_store_converts_parquet_rows_in_bounded_batches(
    tmp_path: Path,
    monkeypatch,
) -> None:
    batch_size = 8
    rows = [
        {"id": f"resource-{index}", "payload": {"value": "x" * 128}}
        for index in range(batch_size * 2 + 3)
    ]
    observed_batch_sizes: list[int] = []
    original = datasets_module._parquet_table

    def recording_table(rows, *, schema=None):
        observed_batch_sizes.append(len(rows))
        return original(rows, schema=schema)

    monkeypatch.setattr(datasets_module, "_PARQUET_BATCH_SIZE", batch_size)
    monkeypatch.setattr(datasets_module, "_parquet_table", recording_table)

    NeutralDatasetStore(tmp_path).publish(
        {"entities/Resource": rows},
        {},
        {"runId": "bounded-parquet"},
    )

    assert observed_batch_sizes == [
        batch_size,
        batch_size,
        3,
        batch_size,
        batch_size,
        3,
    ]
    assert pq.read_table(
        tmp_path / "current/entities/Resource.parquet"
    ).num_rows == len(rows)


def test_store_unifies_parquet_schema_across_batch_boundaries(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(datasets_module, "_PARQUET_BATCH_SIZE", 2)
    rows = [
        {"id": "one", "score": 1},
        {"id": "two", "score": 2},
        {"id": "three", "score": 3.5},
    ]

    NeutralDatasetStore(tmp_path).publish(
        {"entities/Resource": rows},
        {},
        {"runId": "widened-parquet-schema"},
    )

    parquet_rows = pq.read_table(
        tmp_path / "current/entities/Resource.parquet"
    ).to_pylist()
    assert {row["id"]: row["score"] for row in parquet_rows} == {
        "one": 1.0,
        "two": 2.0,
        "three": 3.5,
    }


def test_store_is_idempotent_for_same_content(tmp_path: Path) -> None:
    payload = json.loads(FIXTURE.read_text())
    graph = Normalizer().normalize(payload, datetime(2026, 8, 17, tzinfo=UTC))
    store = DatasetStore(tmp_path)

    first = store.publish(graph, payload, {"runId": "run-1"})
    second = store.publish(graph, payload, {"runId": "run-2"})

    assert first["contentHash"] == second["contentHash"]
    assert second["changedDatasets"] == []


def test_store_can_retain_raw_queries_when_explicitly_enabled(tmp_path: Path) -> None:
    payload = json.loads(FIXTURE.read_text())
    graph = Normalizer().normalize(payload, datetime(2026, 8, 17, tzinfo=UTC))

    DatasetStore(tmp_path, retain_raw_queries=True).publish(graph, payload, {"runId": "raw-run"})

    assert (tmp_path / "current/queries/resources.jsonl").exists()


def test_generation_written_through_aiops_shim_reads_through_neutral_store(tmp_path: Path) -> None:
    payload = json.loads(FIXTURE.read_text())
    graph = Normalizer().normalize(payload, datetime(2026, 8, 17, tzinfo=UTC))

    DatasetStore(tmp_path).publish(graph, payload, {"runId": "compat-run"})

    rows = NeutralDatasetStore(tmp_path).read_dataset("entities/VirtualMachine")
    assert rows[0]["id"].endswith("/virtualmachines/vm-prod-01")


def test_partial_publish_retains_absent_datasets_and_ontology(tmp_path: Path) -> None:
    payload = json.loads(FIXTURE.read_text())
    graph = Normalizer().normalize(payload, datetime(2026, 8, 17, tzinfo=UTC))
    store = DatasetStore(tmp_path)
    store.publish(graph, payload, {"runId": "full-run"})

    partial = NeutralDatasetStore(tmp_path).publish(
        {"inventory/os_observations": [{"resource_id": "inventory-only"}]},
        {},
        {"runId": "partial-run"},
    )

    assert NeutralDatasetStore(tmp_path).read_dataset("entities/VirtualMachine")
    assert NeutralDatasetStore(tmp_path).read_dataset("relationships/relationships")
    assert NeutralDatasetStore(tmp_path).read_dataset("inventory/os_observations") == [
        {"resource_id": "inventory-only"}
    ]
    ontology_files = list((tmp_path / "current/ontology").glob("ontology.json"))
    assert len(ontology_files) == 1
    assert json.loads(ontology_files[0].read_text())["entityTypes"]
    assert "entities/VirtualMachine" not in partial["changedDatasets"]


def test_partial_publish_preserves_hash_baseline_for_next_full_publish(tmp_path: Path) -> None:
    payload = json.loads(FIXTURE.read_text())
    graph = Normalizer().normalize(payload, datetime(2026, 8, 17, tzinfo=UTC))
    store = DatasetStore(tmp_path)
    first = store.publish(graph, payload, {"runId": "full-run-1"})
    NeutralDatasetStore(tmp_path).publish(
        {"inventory/os_observations": [{"resource_id": "inventory-only"}]},
        {},
        {"runId": "partial-run"},
    )

    second = store.publish(graph, payload, {"runId": "full-run-2"})

    assert first["changedDatasets"]
    assert second["changedDatasets"] == []


def test_windows_activation_retains_immutable_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = NeutralDatasetStore(tmp_path)
    monkeypatch.setattr(datasets_module.sys, "platform", "win32")

    store.publish(
        {"inventory/os_observations": [{"resource_id": "vm-1"}]},
        {},
        {"runId": "windows-run", "status": "completed"},
    )
    pinned_generation = store.generation_path("windows-run")

    store.publish(
        {"inventory/os_observations": [{"resource_id": "vm-2"}]},
        {},
        {"runId": "windows-run-2", "status": "completed"},
    )

    assert pinned_generation == store.generations / "windows-run"
    assert store.generation_path("windows-run") == pinned_generation
    assert store.read_datasets(
        ["inventory/os_observations"],
        generation=pinned_generation,
    ) == {"inventory/os_observations": [{"resource_id": "vm-1"}]}
    assert store.read_dataset("inventory/os_observations") == [
        {"resource_id": "vm-2"}
    ]


def test_windows_activation_restores_current_when_pointer_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = NeutralDatasetStore(tmp_path)
    monkeypatch.setattr(datasets_module.sys, "platform", "win32")
    store.publish(
        {"inventory/os_observations": [{"resource_id": "vm-1"}]},
        {},
        {"runId": "windows-run", "status": "completed"},
    )
    pointer_before = Path(store.pointer_path).read_text(encoding="utf-8")

    def fail_pointer_write(path: Path, content: str) -> None:
        raise OSError("simulated pointer failure")

    monkeypatch.setattr(datasets_module, "_atomic_text", fail_pointer_write)

    with pytest.raises(OSError, match="simulated pointer failure"):
        store.publish(
            {"inventory/os_observations": [{"resource_id": "vm-2"}]},
            {},
            {"runId": "windows-run-2", "status": "completed"},
        )

    assert Path(store.pointer_path).read_text(encoding="utf-8") == pointer_before
    assert store.read_dataset("inventory/os_observations") == [
        {"resource_id": "vm-1"}
    ]


def test_windows_generation_cleanup_is_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = NeutralDatasetStore(tmp_path)
    monkeypatch.setattr(datasets_module.sys, "platform", "win32")

    for index in range(5):
        store.publish(
            {"inventory/os_observations": [{"resource_id": f"vm-{index}"}]},
            {},
            {"runId": f"windows-run-{index}", "status": "completed"},
        )

    generations = {
        path.name
        for path in store.generations.iterdir()
        if path.is_dir() and not path.name.startswith(".")
    }
    assert len(generations) == 3
    assert "windows-run-4" in generations
    assert Path(store.current_generation() or "").name == "windows-run-4"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode bits are not enforced on Windows")
def test_store_uses_owner_only_permissions(tmp_path: Path) -> None:
    payload = json.loads(FIXTURE.read_text())
    graph = Normalizer().normalize(payload, datetime(2026, 8, 17, tzinfo=UTC))

    DatasetStore(tmp_path).publish(graph, payload, {"runId": "secure-run"})

    assert os.stat(tmp_path).st_mode & 0o777 == 0o700
    assert os.stat(tmp_path / "current/entities/VirtualMachine.jsonl").st_mode & 0o777 == 0o600
    assert os.stat(tmp_path / "current/entities/VirtualMachine.parquet").st_mode & 0o777 == 0o600


def test_run_lock_rejects_a_concurrent_writer(tmp_path: Path) -> None:
    from storage.locking import RunLock

    with (
        RunLock(tmp_path),
        pytest.raises(RuntimeError, match="already running"),
        RunLock(tmp_path),
    ):
        pass
