from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import pyarrow.parquet as pq
import pytest

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
