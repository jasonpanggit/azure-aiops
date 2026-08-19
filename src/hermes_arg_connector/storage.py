from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from .normalize import NormalizedGraph
from .ontology import generate_ontology_metadata
from .state import _atomic_text

_VOLATILE_KEYS = {"createdTimestamp", "lastObservedTimestamp", "observedAt", "generatedAt", "runId"}


class DatasetStore:
    """Publishes complete immutable generations and atomically switches `current`."""

    def __init__(self, root: Path, retain_raw_queries: bool = False) -> None:
        self.root = Path(root)
        self.retain_raw_queries = retain_raw_queries
        _secure_mkdir(self.root)
        self.generations = self.root / "generations"
        _secure_mkdir(self.generations)
        self.current = self.root / "current"
        self.hash_path = self.root / "state" / "dataset_hashes.json"

    def publish(
        self,
        graph: NormalizedGraph,
        query_results: dict[str, list[dict]],
        run_metadata: dict[str, Any],
    ) -> dict[str, Any]:
        datasets: dict[str, list[dict]] = {
            **{f"entities/{entity_type}": rows for entity_type, rows in graph.entities.items()},
            "relationships/relationships": graph.relationships,
            "changes/resource_changes": graph.changes,
        }
        if self.retain_raw_queries:
            datasets.update(
                {f"queries/{name}": _sorted_rows(rows) for name, rows in sorted(query_results.items())}
            )

        old_hashes = self._load_hashes()
        new_hashes: dict[str, str] = {}
        changed: list[str] = []
        details: dict[str, dict[str, Any]] = {}
        prepared: dict[str, list[dict]] = {}

        for name, rows in sorted(datasets.items()):
            stable_rows = _sorted_rows(rows)
            prepared[name] = stable_rows
            digest = _semantic_hash(stable_rows)
            new_hashes[name] = digest
            details[name] = {"rowCount": len(stable_rows), "contentHash": digest}
            if old_hashes.get(name) != digest:
                changed.append(name)

        ontology = generate_ontology_metadata(graph.entities)
        ontology_hash = _semantic_hash([ontology])
        new_hashes["ontology/ontology"] = ontology_hash
        details["ontology/ontology"] = {"rowCount": 1, "contentHash": ontology_hash}
        if old_hashes.get("ontology/ontology") != ontology_hash:
            changed.append("ontology/ontology")
        changed.extend(sorted(set(old_hashes) - set(new_hashes)))

        overall = hashlib.sha256(json.dumps(new_hashes, sort_keys=True).encode()).hexdigest()
        manifest = {
            **run_metadata,
            "contentHash": overall,
            "changedDatasets": sorted(set(changed)),
            "datasets": details,
        }

        generation = self._write_generation(prepared, ontology, manifest, str(run_metadata.get("runId") or uuid.uuid4()))
        self._activate_generation(generation)
        _atomic_text(self.hash_path, json.dumps(new_hashes, indent=2, sort_keys=True) + "\n")
        self._cleanup_generations(keep=3)
        return manifest

    def read_dataset(self, name: str) -> list[dict]:
        path = (self.current / name).with_suffix(".jsonl")
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    def _write_generation(
        self,
        datasets: dict[str, list[dict]],
        ontology: dict[str, Any],
        manifest: dict[str, Any],
        run_id: str,
    ) -> Path:
        safe_run_id = "".join(character for character in run_id if character.isalnum() or character in "-_")
        final = self.generations / (safe_run_id or str(uuid.uuid4()))
        if final.exists():
            final = self.generations / f"{final.name}-{uuid.uuid4().hex[:8]}"
        stage = self.generations / f".{final.name}.staging-{uuid.uuid4().hex}"
        _secure_mkdir(stage)
        try:
            for name, rows in datasets.items():
                self._write_dataset(stage, name, rows)
            ontology_path = stage / "ontology" / "ontology.json"
            _secure_mkdir(ontology_path.parent)
            _secure_text(ontology_path, json.dumps(ontology, indent=2, sort_keys=True) + "\n")
            _secure_text(stage / "manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
            stage.replace(final)
        except Exception:
            shutil.rmtree(stage, ignore_errors=True)
            raise
        return final

    def _write_dataset(self, generation: Path, name: str, rows: list[dict]) -> None:
        base = generation / name
        _secure_mkdir(base.parent)
        jsonl = "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows
        )
        _secure_text(base.with_suffix(".jsonl"), jsonl)

        parquet_rows = [{key: _parquet_value(value) for key, value in row.items()} for row in rows]
        table = (
            pa.Table.from_pylist(parquet_rows)
            if parquet_rows
            else pa.table({"_empty": pa.array([], type=pa.string())})
        )
        parquet_path = base.with_suffix(".parquet")
        temporary = parquet_path.with_name(f".{parquet_path.name}.{uuid.uuid4().hex}.tmp")
        pq.write_table(table, temporary, compression="zstd")
        os.chmod(temporary, 0o600)
        temporary.replace(parquet_path)

    def _activate_generation(self, generation: Path) -> None:
        if sys.platform == "win32":
            backup = self.root / f".current-backup-{uuid.uuid4().hex}"
            if self.current.exists():
                self.current.replace(backup)
            generation.replace(self.current)
            shutil.rmtree(backup, ignore_errors=True)
            return

        if self.current.exists() and not self.current.is_symlink():
            legacy = self.generations / f"legacy-{uuid.uuid4().hex}"
            self.current.replace(legacy)
        temporary = self.root / f".current-{uuid.uuid4().hex}"
        temporary.symlink_to(generation.relative_to(self.root), target_is_directory=True)
        os.replace(temporary, self.current)

    def _load_hashes(self) -> dict[str, str]:
        if not self.hash_path.exists():
            return {}
        try:
            payload = json.loads(self.hash_path.read_text())
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _cleanup_generations(self, keep: int) -> None:
        if sys.platform == "win32":
            return
        active = self.current.resolve() if self.current.exists() else None
        generations = sorted(
            (path for path in self.generations.iterdir() if path.is_dir() and not path.name.startswith(".")),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for path in generations:
            if path == active or path in generations[:keep]:
                continue
            shutil.rmtree(path, ignore_errors=True)


def _secure_mkdir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if sys.platform != "win32":
        path.chmod(0o700)


def _secure_text(path: Path, content: str) -> None:
    _secure_mkdir(path.parent)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def _sorted_rows(rows: list[dict]) -> list[dict]:
    return sorted(
        (dict(row) for row in rows),
        key=lambda row: json.dumps(_semantic(row), sort_keys=True, separators=(",", ":")),
    )


def _semantic_hash(rows: list[dict]) -> str:
    payload = json.dumps(_semantic(rows), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def _semantic(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _semantic(item)
            for key, item in sorted(value.items())
            if key not in _VOLATILE_KEYS
        }
    if isinstance(value, list):
        return [_semantic(item) for item in value]
    return value


def _parquet_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return value
