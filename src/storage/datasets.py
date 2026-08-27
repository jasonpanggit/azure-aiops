from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sys
import uuid
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from .fs import is_onelake_uri

_VOLATILE_KEYS = {
    "createdTimestamp",
    "lastObservedTimestamp",
    "observedAt",
    "generatedAt",
    "runId",
    "ingested_at",
    "run_id",
    "observed_at",
}

_POINTER_NAME = "current.json"


def _is_remote_root(root: object) -> bool:
    return is_onelake_uri(root)


class DatasetStore:
    """Publishes complete immutable generations and atomically switches `current`.

    Local roots (the default, and the only mode used by existing tests/CLI)
    behave exactly as before: `current` is a real directory symlink swapped
    atomically on publish. OneLake roots (``abfss://...@onelake.dfs.fabric
    .microsoft.com/...``) don't support symlinks, so those are instead backed
    by an ``fsspec`` filesystem and a small atomic JSON pointer file
    (``current.json``) naming the active generation.
    """

    def __init__(self, root: Path | str, retain_raw_queries: bool = False) -> None:
        self.retain_raw_queries = retain_raw_queries
        self.is_remote = _is_remote_root(root)
        if self.is_remote:
            from .fs import resolve_fs

            self.fs, resolved_root = resolve_fs(str(root))
            self.root = resolved_root
            self.generations = f"{resolved_root}/generations"
            # Not created here: constructing a store must stay a local
            # operation (callers build one before any network is reachable,
            # and tests swap `fs` in afterwards). Generation directories are
            # created implicitly by the writes in `_write_generation`.
            self.current = f"{resolved_root}/current"
            self.pointer_path = f"{resolved_root}/{_POINTER_NAME}"
            self.hash_path = f"{resolved_root}/state/dataset_hashes.json"
            return

        self.root = Path(root)
        _secure_mkdir(self.root)
        self.generations = self.root / "generations"
        _secure_mkdir(self.generations)
        self.current = self.root / "current"
        self.hash_path = self.root / "state" / "dataset_hashes.json"

    def publish(
        self,
        datasets: dict[str, list[dict]],
        query_results: dict[str, list[dict]],
        run_metadata: dict[str, Any],
        *,
        ontology: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        datasets = dict(datasets)
        if self.retain_raw_queries:
            datasets.update(
                {f"queries/{name}": _sorted_rows(rows) for name, rows in sorted(query_results.items())}
            )
        _validate_dataset_names(datasets)

        old_hashes = self._load_hashes()
        new_hashes: dict[str, str] = dict(old_hashes)
        changed: list[str] = []
        details: dict[str, dict[str, Any]] = {}
        prepared: dict[str, list[dict]] = self._current_datasets(
            name for name in old_hashes if name != "ontology/ontology"
        )

        for name, rows in sorted(datasets.items()):
            stable_rows = _sorted_rows(rows)
            prepared[name] = stable_rows
            digest = _semantic_hash(stable_rows)
            new_hashes[name] = digest
            details[name] = {"rowCount": len(stable_rows), "contentHash": digest}
            if old_hashes.get(name) != digest:
                changed.append(name)

        active_ontology = self._current_ontology()
        if ontology is None:
            ontology = active_ontology or {}
        ontology_hash = _semantic_hash([ontology])
        new_hashes["ontology/ontology"] = ontology_hash
        details["ontology/ontology"] = {"rowCount": 1, "contentHash": ontology_hash}
        if old_hashes.get("ontology/ontology") != ontology_hash:
            changed.append("ontology/ontology")
        for name, rows in prepared.items():
            details.setdefault(
                name,
                {"rowCount": len(rows), "contentHash": new_hashes.get(name, _semantic_hash(rows))},
            )

        overall = hashlib.sha256(json.dumps(new_hashes, sort_keys=True).encode()).hexdigest()
        manifest = {
            **run_metadata,
            "contentHash": overall,
            "changedDatasets": sorted(set(changed)),
            "datasets": details,
        }

        generation = self._write_generation(prepared, ontology, manifest, str(run_metadata.get("runId") or uuid.uuid4()))
        self._activate_generation(generation)
        if self.is_remote:
            self._write_atomic_remote(self.hash_path, json.dumps(new_hashes, indent=2, sort_keys=True) + "\n")
        else:
            _atomic_text(self.hash_path, json.dumps(new_hashes, indent=2, sort_keys=True) + "\n")
        self._cleanup_generations(keep=3)
        return manifest

    def _current_datasets(self, names: object) -> dict[str, list[dict]]:
        datasets: dict[str, list[dict]] = {}
        for name in sorted(set(names)):
            datasets[name] = self.read_dataset(name)
        return datasets

    def _current_ontology(self) -> dict[str, Any] | None:
        if self.is_remote:
            generation = self.current_generation()
            if generation is None:
                return None
            path = f"{generation}/ontology/ontology.json"
            if not self.fs.exists(path):
                return None
            try:
                with self.fs.open(path, "rt") as handle:
                    payload = json.loads(handle.read())
            except (OSError, json.JSONDecodeError):
                return None
            return payload if isinstance(payload, dict) else None

        path = self.current / "ontology" / "ontology.json"
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def read_dataset(self, name: str) -> list[dict]:
        if self.is_remote:
            generation = self.current_generation()
            if generation is None:
                return []
            path = f"{generation}/{name}.jsonl"
            if not self.fs.exists(path):
                return []
            with self.fs.open(path, "rt") as handle:
                return [json.loads(line) for line in handle.read().splitlines() if line.strip()]

        path = (self.current / name).with_suffix(".jsonl")
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    def current_generation(self) -> str | None:
        """Return the absolute path/URI of the active generation, or ``None``.

        Only meaningful (and only needed) for remote roots; local roots
        should follow ``self.current`` (the symlink) directly.
        """
        if not self.is_remote:
            if not self.current.exists():
                return None
            return str(self.current.resolve())

        if not self.fs.exists(self.pointer_path):
            return None
        try:
            with self.fs.open(self.pointer_path, "rt") as handle:
                pointer = json.loads(handle.read())
        except (OSError, json.JSONDecodeError):
            return None
        name = str(pointer.get("generation") or "").strip()
        if not name:
            return None
        candidate = f"{self.generations}/{name}"
        return candidate if self.fs.exists(candidate) else None

    def _write_generation(
        self,
        datasets: dict[str, list[dict]],
        ontology: dict[str, Any],
        manifest: dict[str, Any],
        run_id: str,
    ) -> Path | str:
        safe_run_id = "".join(character for character in run_id if character.isalnum() or character in "-_")
        final_name = safe_run_id or uuid.uuid4().hex

        if self.is_remote:
            if self.fs.exists(f"{self.generations}/{final_name}"):
                final_name = f"{final_name}-{uuid.uuid4().hex[:8]}"
            final = f"{self.generations}/{final_name}"
            try:
                for name, rows in datasets.items():
                    self._write_dataset(final, name, rows)
                self._write_atomic_remote(
                    f"{final}/ontology/ontology.json", json.dumps(ontology, indent=2, sort_keys=True) + "\n"
                )
                self._write_atomic_remote(
                    f"{final}/manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n"
                )
            except Exception:
                self.fs.rm(final, recursive=True)
                raise
            return final

        final = self.generations / final_name
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

    def _write_dataset(self, generation: Path | str, name: str, rows: list[dict]) -> None:
        jsonl = "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows
        )
        parquet_rows = [{key: _parquet_value(value) for key, value in row.items()} for row in rows]
        table = (
            pa.Table.from_pylist(parquet_rows)
            if parquet_rows
            else pa.table({"_empty": pa.array([], type=pa.string())})
        )

        if self.is_remote:
            base = f"{generation}/{name}"
            self._write_atomic_remote(f"{base}.jsonl", jsonl)
            buffer = io.BytesIO()
            pq.write_table(table, buffer, compression="zstd")
            with self.fs.open(f"{base}.parquet", "wb") as handle:
                handle.write(buffer.getvalue())
            return

        base = generation / name
        _secure_mkdir(base.parent)
        _secure_text(base.with_suffix(".jsonl"), jsonl)

        parquet_path = base.with_suffix(".parquet")
        temporary = parquet_path.with_name(f".{parquet_path.name}.{uuid.uuid4().hex}.tmp")
        pq.write_table(table, temporary, compression="zstd")
        os.chmod(temporary, 0o600)
        temporary.replace(parquet_path)

    def _write_atomic_remote(self, path: str, content: str) -> None:
        """Write ``content`` to OneLake.

        OneLake/fsspec rename operations can fail for hierarchical-namespace
        paths under private-link policy. Remote generations are immutable and
        only become active after ``current.json`` is written, so direct writes
        preserve correctness without relying on server-side rename support.
        """
        parent = path.rsplit("/", 1)[0]
        self.fs.makedirs(parent, exist_ok=True)
        with self.fs.open(path, "wt") as handle:
            handle.write(content)

    def _activate_generation(self, generation: Path | str) -> None:
        if self.is_remote:
            name = str(generation).rsplit("/", 1)[-1]
            self._write_atomic_remote(self.pointer_path, json.dumps({"generation": name}, indent=2) + "\n")
            return

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
        if self.is_remote:
            if not self.fs.exists(self.hash_path):
                return {}
            try:
                with self.fs.open(self.hash_path, "rt") as handle:
                    payload = json.loads(handle.read())
            except (OSError, json.JSONDecodeError):
                return {}
            return payload if isinstance(payload, dict) else {}

        if not self.hash_path.exists():
            return {}
        try:
            payload = json.loads(self.hash_path.read_text())
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _cleanup_generations(self, keep: int) -> None:
        if self.is_remote:
            active = self.current_generation()
            entries = [
                path if path.startswith(self.generations) else f"{self.generations}/{path.rsplit('/', 1)[-1]}"
                for path in self.fs.ls(self.generations, detail=False)
            ]
            generations = [
                path for path in entries
                if self.fs.isdir(path) and not path.rsplit("/", 1)[-1].startswith(".")
            ]
            generations.sort(key=lambda path: self.fs.info(path).get("mtime") or 0, reverse=True)
            for path in generations:
                if path == active or path in generations[:keep]:
                    continue
                self.fs.rm(path, recursive=True)
            return

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


def _atomic_text(path: Path, content: str) -> None:
    _secure_text(Path(path), content)


def _validate_dataset_names(datasets: dict[str, list[dict]]) -> None:
    for name in datasets:
        text = str(name).strip()
        path = PurePosixPath(text)
        if not text or path.is_absolute() or ".." in path.parts:
            raise ValueError(f"Dataset name must be relative and contained: {name}")


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
