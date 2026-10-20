from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from .fs import is_onelake_uri
from .onelake_documents import (
    DocumentConflictError,
    OneLakeDocumentStore,
)

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
_COMPATIBILITY_ALIAS_VERSION = "ontology-generation-alias/v1"
_PARQUET_BATCH_SIZE = 512
COMBINED_ACTIVATION_QUERY_VERSION = "combined-subscription-connections-v1"
_MANIFEST_DERIVED_FIELDS = frozenset(
    {"changedDatasets", "contentHash", "datasets", "integrityHash"}
)


def _is_remote_root(root: object) -> bool:
    return is_onelake_uri(root)


@dataclass(frozen=True)
class GenerationPointer:
    """Authoritative pointer metadata guarded by one storage ETag."""

    active_generation: str
    prior_generation: str | None
    source_generation: str
    owner_id: str
    fence: int
    compatibility_alias_version: str = _COMPATIBILITY_ALIAS_VERSION

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> GenerationPointer:
        active = str(
            payload.get("active_generation") or payload.get("generation") or ""
        ).strip()
        source = str(
            payload.get("source_generation")
            or payload.get("sourceGeneration")
            or ""
        ).strip()
        owner = str(payload.get("owner_id") or "").strip()
        fence = int(payload.get("fence") or 0)
        if not active or not source or not owner or fence < 1:
            raise ValueError("generation pointer is incomplete")
        prior = str(
            payload.get("prior_generation")
            or payload.get("previous_generation")
            or ""
        ).strip()
        alias_version = str(
            payload.get("compatibility_alias_version")
            or _COMPATIBILITY_ALIAS_VERSION
        ).strip()
        if alias_version != _COMPATIBILITY_ALIAS_VERSION:
            raise ValueError("generation pointer compatibility alias is unsupported")
        return cls(
            active_generation=active,
            prior_generation=prior or None,
            source_generation=source,
            owner_id=owner,
            fence=fence,
            compatibility_alias_version=alias_version,
        )

    def to_payload(self) -> dict[str, Any]:
        # ``generation`` and ``previous_generation`` are compatibility aliases
        # consumed by the existing DatasetStore and GenerationResolver paths.
        return {
            "generation": self.active_generation,
            "active_generation": self.active_generation,
            "previous_generation": self.prior_generation,
            "prior_generation": self.prior_generation,
            "source_generation": self.source_generation,
            "owner_id": self.owner_id,
            "fence": self.fence,
            "compatibility_alias_version": self.compatibility_alias_version,
        }


@dataclass(frozen=True)
class GenerationPointerSnapshot:
    pointer: GenerationPointer | None
    etag: str | None


@dataclass(frozen=True)
class GenerationPointerConditions:
    """Every predecessor fact a conditional pointer transition must match."""

    etag: str | None
    owner_id: str | None
    fence: int
    source_generation: str | None
    active_generation: str | None

    @classmethod
    def initial(cls) -> GenerationPointerConditions:
        return cls(
            etag=None,
            owner_id=None,
            fence=0,
            source_generation=None,
            active_generation=None,
        )

    @classmethod
    def from_snapshot(
        cls,
        snapshot: GenerationPointerSnapshot,
    ) -> GenerationPointerConditions:
        if snapshot.pointer is None:
            return cls.initial()
        return cls(
            etag=snapshot.etag,
            owner_id=snapshot.pointer.owner_id,
            fence=snapshot.pointer.fence,
            source_generation=snapshot.pointer.source_generation,
            active_generation=snapshot.pointer.active_generation,
        )


class AuthoritativeDatasetPublisher:
    """Publisher-identity-only access to consequential generation primitives."""

    def __init__(
        self,
        store: DatasetStore,
        documents: OneLakeDocumentStore,
        *,
        publisher_identity: str,
    ) -> None:
        self._store = store
        self._documents = documents
        self.publisher_identity = publisher_identity

    def read_pointer(self) -> GenerationPointerSnapshot:
        snapshot = self._documents.read_snapshot(_POINTER_NAME)
        pointer = (
            GenerationPointer.from_payload(snapshot.payload)
            if snapshot.etag is not None
            else None
        )
        return GenerationPointerSnapshot(pointer=pointer, etag=snapshot.etag)

    def assert_pointer_conditions(
        self,
        conditions: GenerationPointerConditions,
    ) -> GenerationPointerSnapshot:
        current = self.read_pointer()
        if not _pointer_matches(current, conditions):
            raise DocumentConflictError(
                "active pointer owner, fence, source, generation, or ETag changed"
            )
        return current

    def generation_exists(self, generation_id: str) -> bool:
        generation = _safe_generation_id(generation_id)
        return self._documents.read_snapshot(
            f"generations/{generation}/manifest.json"
        ).exists

    def stage_generation(
        self,
        generation_id: str,
        *,
        manifest: dict[str, Any],
        entities: list[dict[str, Any]],
        relationships: list[dict[str, Any]],
        lineage: dict[str, Any],
        validation: dict[str, Any],
        compatibility: dict[str, Any],
    ) -> None:
        """Create one complete immutable generation, publishing its manifest last."""

        generation = _safe_generation_id(generation_id)
        if self.generation_exists(generation):
            raise DocumentConflictError(
                f"generation {generation} is immutable and already exists"
            )
        base = f"generations/{generation}"
        artifacts = (
            ("entities.json", {"records": entities}),
            ("relationships.json", {"records": relationships}),
            ("lineage.json", lineage),
            ("validation.json", validation),
            ("compatibility.json", compatibility),
        )
        for name, payload in artifacts:
            self._documents.create_only(f"{base}/{name}", payload)
        self._documents.create_text_only(
            f"{base}/ontology_entities.jsonl",
            _json_lines(entities),
        )
        self._documents.create_text_only(
            f"{base}/ontology_relationships.jsonl",
            _json_lines(relationships),
        )
        # The manifest is the completeness marker and is deliberately last.
        self._documents.create_only(f"{base}/manifest.json", manifest)

    def persist_generation_audit(
        self,
        generation_id: str,
        audit: dict[str, Any],
    ) -> None:
        generation = _safe_generation_id(generation_id)
        if not self.generation_exists(generation):
            raise FileNotFoundError(f"generation {generation} is not complete")
        self._documents.create_only(
            f"generations/{generation}/audit-intent.json",
            audit,
        )

    def persist_generation_receipt(
        self,
        generation_id: str,
        receipt: dict[str, Any],
    ) -> None:
        generation = _safe_generation_id(generation_id)
        self._documents.create_only(
            f"generations/{generation}/audit-result.json",
            receipt,
        )

    def persist_stage_authorization(
        self,
        *,
        target_generation_id: str,
        owner_id: str,
        fence: int,
        audit: dict[str, Any],
    ) -> None:
        """Create an immutable authorization record distinct from recovery audits."""
        generation = _safe_generation_id(target_generation_id)
        if not self.generation_exists(generation):
            raise FileNotFoundError(f"generation {generation} is not complete")
        owner_hash = hashlib.sha256(owner_id.encode()).hexdigest()[:16]
        self._documents.create_only(
            f"generations/{generation}/stage-authorization-{fence}-{owner_hash}.json",
            audit,
        )

    def read_stage_authorization(
        self,
        *,
        target_generation_id: str,
        owner_id: str,
        fence: int,
    ) -> dict[str, Any]:
        """Read the exact immutable authorization for one fenced stage attempt."""
        generation = _safe_generation_id(target_generation_id)
        owner_hash = hashlib.sha256(owner_id.encode()).hexdigest()[:16]
        snapshot = self._documents.read_snapshot(
            f"generations/{generation}/stage-authorization-{fence}-{owner_hash}.json"
        )
        if not snapshot.exists:
            raise FileNotFoundError(f"generation {generation} has no stage authorization")
        return snapshot.payload

    def persist_rollback_audit(
        self,
        *,
        target_generation_id: str,
        owner_id: str,
        fence: int,
        audit: dict[str, Any],
    ) -> None:
        generation = _safe_generation_id(target_generation_id)
        owner_hash = hashlib.sha256(owner_id.encode()).hexdigest()[:16]
        self._documents.create_only(
            f"publication-audits/rollback-{fence}-{owner_hash}-{generation}.json",
            audit,
        )

    def read_generation(self, generation_id: str) -> dict[str, Any]:
        generation = _safe_generation_id(generation_id)
        base = f"generations/{generation}"

        def required(name: str) -> dict[str, Any]:
            snapshot = self._documents.read_snapshot(f"{base}/{name}.json")
            if not snapshot.exists:
                raise FileNotFoundError(
                    f"generation {generation} missing {name}.json"
                )
            return snapshot.payload

        entities = required("entities").get("records")
        relationships = required("relationships").get("records")
        if not isinstance(entities, list) or not isinstance(relationships, list):
            raise TypeError(f"generation {generation} record artifacts are invalid")
        receipt = self._documents.read_snapshot(f"{base}/audit-result.json")
        intent = self._documents.read_snapshot(f"{base}/audit-intent.json")
        return {
            "manifest": required("manifest"),
            "entities": entities,
            "relationships": relationships,
            "lineage": required("lineage"),
            "validation": required("validation"),
            "compatibility": required("compatibility"),
            "audit": (
                receipt.payload
                if receipt.exists
                else intent.payload if intent.exists else None
            ),
        }

    def conditional_promote(
        self,
        *,
        generation_id: str,
        source_generation: str,
        owner_id: str,
        fence: int,
        conditions: GenerationPointerConditions,
    ) -> GenerationPointerSnapshot:
        generation = _safe_generation_id(generation_id)
        source = str(source_generation).strip()
        owner = str(owner_id).strip()
        if not source or not owner or fence < 1:
            raise ValueError("source generation, owner, and positive fence are required")

        current = self.assert_pointer_conditions(conditions)
        if current.pointer is not None and fence <= current.pointer.fence:
            raise DocumentConflictError("promotion fence is not monotonic")

        pointer = GenerationPointer(
            active_generation=generation,
            prior_generation=(
                current.pointer.active_generation if current.pointer else None
            ),
            source_generation=source,
            owner_id=owner,
            fence=fence,
        )
        if current.etag is None:
            written = self._documents.create_only(_POINTER_NAME, pointer.to_payload())
        else:
            written = self._documents.replace_if_match(
                _POINTER_NAME,
                pointer.to_payload(),
                expected_etag=current.etag,
            )
        return GenerationPointerSnapshot(pointer=pointer, etag=written.etag)


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
        self._document_root = root
        self.is_remote = _is_remote_root(root)
        if self.is_remote:
            from .fs import resolve_fs

            self.uri_root = str(root).rstrip("/")
            self.fs, resolved_root = resolve_fs(str(root))
            self.root = resolved_root
            self.generations = f"{resolved_root}/generations"
            self.uri_generations = f"{self.uri_root}/generations"
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
        self.pointer_path = self.root / _POINTER_NAME
        self.hash_path = self.root / "state" / "dataset_hashes.json"

    def authoritative_publisher(
        self,
        *,
        publisher_identity: str,
        approved_publisher_identity: str,
    ) -> AuthoritativeDatasetPublisher:
        """Open ontology publication controls for the approved identity only."""

        identity = str(publisher_identity).strip()
        approved = str(approved_publisher_identity).strip()
        if not identity or not approved or identity != approved:
            raise PermissionError("only the approved publisher identity may publish")
        return AuthoritativeDatasetPublisher(
            self,
            OneLakeDocumentStore(self._document_root),
            publisher_identity=identity,
        )

    def publish(
        self,
        datasets: dict[str, list[dict]],
        query_results: dict[str, list[dict]],
        run_metadata: dict[str, Any],
        *,
        ontology: dict[str, Any] | None = None,
        assert_lock_held: Callable[[], None] | None = None,
    ) -> dict[str, Any]:
        """Stage a source generation, checking any caller lease before active writes."""
        if assert_lock_held is not None:
            assert_lock_held()
        datasets = dict(datasets)
        if self.retain_raw_queries:
            datasets.update(
                {f"queries/{name}": _sorted_rows(rows) for name, rows in sorted(query_results.items())}
            )
        _validate_dataset_names(datasets)
        _validate_source_partitions(datasets)

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
            details[name] = {
                "rowCount": len(stable_rows),
                "contentHash": digest,
                "integrityHash": _canonical_hash(stable_rows),
            }
            if old_hashes.get(name) != digest:
                changed.append(name)

        active_ontology = self._current_ontology()
        if ontology is None:
            ontology = active_ontology or {}
        ontology_hash = _semantic_hash([ontology])
        new_hashes["ontology/ontology"] = ontology_hash
        details["ontology/ontology"] = {
            "rowCount": 1,
            "contentHash": ontology_hash,
            "integrityHash": _canonical_hash([ontology]),
        }
        if old_hashes.get("ontology/ontology") != ontology_hash:
            changed.append("ontology/ontology")
        for name, rows in prepared.items():
            details.setdefault(
                name,
                {
                    "rowCount": len(rows),
                    "contentHash": new_hashes.get(name, _semantic_hash(rows)),
                    "integrityHash": _canonical_hash(rows),
                },
            )

        overall = hashlib.sha256(json.dumps(new_hashes, sort_keys=True).encode()).hexdigest()
        manifest = {
            **run_metadata,
            "contentHash": overall,
            "changedDatasets": sorted(set(changed)),
            "datasets": details,
        }
        manifest["integrityHash"] = _manifest_integrity_hash(manifest)

        generation = self._write_generation(prepared, ontology, manifest, str(run_metadata.get("runId") or uuid.uuid4()))
        if assert_lock_held is not None:
            assert_lock_held()
        self._activate_generation(generation)
        if assert_lock_held is not None:
            assert_lock_held()
        if self.is_remote:
            self._write_atomic_remote(self.hash_path, json.dumps(new_hashes, indent=2, sort_keys=True) + "\n")
        else:
            _atomic_text(self.hash_path, json.dumps(new_hashes, indent=2, sort_keys=True) + "\n")
        if assert_lock_held is not None:
            assert_lock_held()
        self._cleanup_generations(keep=3)
        return manifest

    def _current_datasets(self, names: Iterable[str]) -> dict[str, list[dict]]:
        return self.read_datasets(names)

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
        """Read one dataset from the active immutable generation."""
        return self.read_datasets((name,))[name]

    def read_datasets(
        self,
        names: Iterable[str],
        *,
        generation: Path | str | None = None,
    ) -> dict[str, list[dict]]:
        """Read datasets from one pinned immutable generation.

        Resolving ``current.json`` once prevents a concurrent publisher from
        mixing rows from different generations during a multi-dataset read.
        Callers that already own an immutable generation may pass it directly.
        """
        selected = sorted(set(names))
        resolved_generation = generation or self.current_generation()
        return {
            name: self._read_dataset_from_generation(name, resolved_generation)
            for name in selected
        }

    def _read_dataset_from_generation(
        self,
        name: str,
        generation: Path | str | None,
    ) -> list[dict]:
        if generation is None:
            return []
        if self.is_remote:
            path = f"{generation}/{name}.jsonl"
            if not self.fs.exists(path):
                return []
            with self.fs.open(path, "rt") as handle:
                return [json.loads(line) for line in handle.read().splitlines() if line.strip()]

        path = (Path(generation) / name).with_suffix(".jsonl")
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    def generation_path(self, generation_id: str) -> Path | str | None:
        """Resolve an immutable generation ID without consulting `current`."""
        name = _safe_generation_id(generation_id)
        candidate: Path | str
        if self.is_remote:
            candidate = f"{self.generations}/{name}"
            return candidate if self.fs.exists(candidate) else None
        candidate = self.generations / name
        if candidate.exists():
            return candidate
        if sys.platform != "win32":
            return None

        # Windows activation moves the selected directory to ``current``
        # instead of creating a symlink. Match by the immutable manifest run
        # ID, including prior generations renamed to ``legacy-*``.
        candidates = [self.current]
        if self.generations.exists():
            candidates.extend(
                path for path in self.generations.iterdir() if path.is_dir()
            )
        for path in candidates:
            manifest_path = path / "manifest.json"
            if not manifest_path.is_file():
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(manifest, dict) and str(manifest.get("runId") or "") == name:
                return path
        return None

    def verify_combined_activation_generation(
        self,
        generation_id: str,
    ) -> dict[str, Any]:
        """Verify one immutable combined activation generation.

        Activation replay callers use this before constructing any publication
        runtime. The activation-specific name prevents unrelated DatasetStore
        generations from inheriting the combined-snapshot provenance contract.
        Resolution is pinned to ``generations/<generation_id>`` and never
        consults the mutable current pointer.
        """
        name = _safe_generation_id(generation_id)
        generation = self.generation_path(name)
        if generation is None:
            raise FileNotFoundError(
                f"Requested dataset generation does not exist: {name}"
            )

        manifest = self._read_required_json_object(
            generation,
            "manifest.json",
        )
        if manifest.get("status") != "completed":
            raise ValueError("Dataset generation is not completed")
        if manifest.get("runId") != name:
            raise ValueError("Dataset generation manifest does not match requested ID")

        if manifest.get("queryVersion") != COMBINED_ACTIVATION_QUERY_VERSION:
            raise ValueError("Dataset generation query version is invalid")
        source_ids = _required_unique_nonempty_strings(
            manifest,
            "sourceConnectionIds",
        )
        source_run_ids = _required_unique_nonempty_strings(
            manifest,
            "sourceRunIds",
        )
        if len(source_run_ids) != len(source_ids):
            raise ValueError(
                "Dataset generation source provenance cardinality is invalid"
            )

        declared = manifest.get("datasets")
        if not isinstance(declared, Mapping) or not declared:
            raise TypeError("Dataset generation manifest datasets are invalid")
        _validate_dataset_names({str(dataset_name): [] for dataset_name in declared})
        if "ontology/ontology" not in declared:
            raise ValueError("Dataset generation ontology declaration is missing")

        declared_hashes: dict[str, str] = {}
        for dataset_name, details in sorted(declared.items()):
            if not isinstance(dataset_name, str) or not isinstance(details, Mapping):
                raise TypeError("Dataset generation declaration is invalid")
            expected_count, expected_hash, expected_integrity_hash = (
                _declared_artifact_integrity(
                details,
                artifact_name=dataset_name,
            )
            )
            if dataset_name == "ontology/ontology":
                ontology = self._read_required_json_object(
                    generation,
                    "ontology/ontology.json",
                )
                rows = [ontology]
            else:
                rows = self._read_required_jsonl(
                    generation,
                    f"{dataset_name}.jsonl",
                )
            if len(rows) != expected_count:
                raise ValueError(
                    f"Dataset generation artifact row count mismatch: {dataset_name}"
                )
            actual_integrity_hash = _canonical_hash(rows)
            if actual_integrity_hash != expected_integrity_hash:
                raise ValueError(
                    "Dataset generation artifact integrity hash mismatch: "
                    f"{dataset_name}"
                )
            actual_hash = _semantic_hash(_sorted_rows(rows))
            if actual_hash != expected_hash:
                raise ValueError(
                    f"Dataset generation artifact hash mismatch: {dataset_name}"
                )
            declared_hashes[dataset_name] = expected_hash

        expected_overall = hashlib.sha256(
            json.dumps(declared_hashes, sort_keys=True).encode()
        ).hexdigest()
        if manifest.get("contentHash") != expected_overall:
            raise ValueError("Dataset generation overall hash mismatch")
        expected_integrity_hash = _required_sha256(
            manifest.get("integrityHash"),
            field="Dataset generation overall integrity hash",
        )
        if _manifest_integrity_hash(manifest) != expected_integrity_hash:
            raise ValueError("Dataset generation overall integrity hash mismatch")
        return manifest

    def _read_required_text(
        self,
        generation: Path | str,
        relative_path: str,
    ) -> str:
        if self.is_remote:
            path = f"{generation}/{relative_path}"
            if not self.fs.exists(path):
                raise FileNotFoundError(
                    f"Dataset generation artifact is missing: {relative_path}"
                )
            with self.fs.open(path, "rt") as handle:
                return handle.read()

        path = Path(generation) / relative_path
        if not path.is_file():
            raise FileNotFoundError(
                f"Dataset generation artifact is missing: {relative_path}"
            )
        return path.read_text(encoding="utf-8")

    def _read_required_json_object(
        self,
        generation: Path | str,
        relative_path: str,
    ) -> dict[str, Any]:
        try:
            payload = json.loads(
                self._read_required_text(generation, relative_path)
            )
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Dataset generation artifact is invalid JSON: {relative_path}"
            ) from exc
        if not isinstance(payload, dict):
            raise TypeError(
                f"Dataset generation artifact is not an object: {relative_path}"
            )
        return payload

    def _read_required_jsonl(
        self,
        generation: Path | str,
        relative_path: str,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for line_number, line in enumerate(
            self._read_required_text(generation, relative_path).splitlines(),
            start=1,
        ):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    "Dataset generation artifact contains invalid JSONL: "
                    f"{relative_path}:{line_number}"
                ) from exc
            if not isinstance(row, dict):
                raise TypeError(
                    "Dataset generation artifact row is not an object: "
                    f"{relative_path}:{line_number}"
                )
            rows.append(row)
        return rows

    def current_generation(self) -> str | None:
        """Return the absolute path/URI of the active generation, or ``None``.

        Only meaningful (and only needed) for remote roots; local roots
        should follow ``self.current`` (the symlink) directly.
        """
        if not self.is_remote:
            pointer = Path(self.pointer_path)
            if pointer.exists():
                try:
                    payload = json.loads(pointer.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    return None
                name = str(
                    payload.get("active_generation")
                    or payload.get("generation")
                    or ""
                ).strip()
                if not name:
                    return None
                candidate = self.generations / _safe_generation_id(name)
                return str(candidate) if candidate.exists() else None
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
        return self.generation_path(name)

    def current_generation_uri(self) -> str | None:
        """Return the active generation as a URI suitable for external callers."""
        generation = self.current_generation()
        if generation is None:
            return None
        if not self.is_remote:
            return generation
        name = str(generation).rsplit("/", 1)[-1]
        return f"{self.uri_generations}/{name}"

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
        if self.is_remote:
            base = f"{generation}/{name}"
            self.fs.makedirs(base.rsplit("/", 1)[0], exist_ok=True)
            with self.fs.open(f"{base}.jsonl", "wt", streaming=True) as handle:
                _write_jsonl_rows(handle, rows)
            with self.fs.open(f"{base}.parquet", "wb", streaming=True) as handle:
                _write_parquet_rows(handle, rows)
            return

        base = generation / name
        _secure_mkdir(base.parent)
        _secure_jsonl(base.with_suffix(".jsonl"), rows)

        parquet_path = base.with_suffix(".parquet")
        temporary = parquet_path.with_name(f".{parquet_path.name}.{uuid.uuid4().hex}.tmp")
        _write_parquet_rows(temporary, rows)
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
            name = Path(generation).name
            temporary = self.root / f".current-{uuid.uuid4().hex}"
            backup = self.root / f".current-backup-{uuid.uuid4().hex}"
            shutil.copytree(generation, temporary)
            previous_current_moved = False
            try:
                if self.current.exists():
                    self.current.replace(backup)
                    previous_current_moved = True
                temporary.replace(self.current)
                _atomic_text(
                    Path(self.pointer_path),
                    json.dumps({"generation": name}, indent=2) + "\n",
                )
            except Exception:
                if self.current.exists():
                    shutil.rmtree(self.current)
                if previous_current_moved and backup.exists():
                    backup.replace(self.current)
                raise
            finally:
                shutil.rmtree(temporary, ignore_errors=True)
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
            # Remote generations are durable exact-replay inputs. Automatic
            # age/count cleanup races readers that have already verified and
            # pinned a generation, so retention is intentionally unbounded
            # until a separately governed retention operation is introduced.
            return

        if sys.platform == "win32":
            current_generation = self.current_generation()
            active = Path(current_generation) if current_generation else None
        else:
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


def _secure_jsonl(path: Path, rows: list[dict]) -> None:
    _secure_mkdir(path.parent)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            _write_jsonl_rows(handle, rows)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _write_jsonl_rows(handle: Any, rows: list[dict]) -> None:
    for row in rows:
        json.dump(row, handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")


def _write_parquet_rows(destination: Any, rows: list[dict]) -> None:
    if not rows:
        pq.write_table(
            pa.table({"_empty": pa.array([], type=pa.string())}),
            destination,
            compression="zstd",
        )
        return

    schemas = [
        _parquet_table(rows[offset : offset + _PARQUET_BATCH_SIZE]).schema
        for offset in range(0, len(rows), _PARQUET_BATCH_SIZE)
    ]
    schema = pa.unify_schemas(schemas, promote_options="permissive")
    with pq.ParquetWriter(destination, schema, compression="zstd") as writer:
        for offset in range(0, len(rows), _PARQUET_BATCH_SIZE):
            writer.write_table(
                _parquet_table(
                    rows[offset : offset + _PARQUET_BATCH_SIZE],
                    schema=schema,
                )
            )


def _parquet_table(
    rows: list[dict],
    *,
    schema: pa.Schema | None = None,
) -> pa.Table:
    parquet_rows = [
        {key: _parquet_value(value) for key, value in row.items()}
        for row in rows
    ]
    return pa.Table.from_pylist(parquet_rows, schema=schema)


def _atomic_text(path: Path, content: str) -> None:
    _secure_text(Path(path), content)


def atomic_text(path: Path, content: str) -> None:
    """Write text atomically with restrictive file permissions."""
    _secure_text(Path(path), content)


def _safe_generation_id(value: object) -> str:
    text = str(value).strip()
    path = PurePosixPath(text)
    if (
        not text
        or path.is_absolute()
        or len(path.parts) != 1
        or path.name in {".", ".."}
        or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for character in text)
    ):
        raise ValueError("generation ID must be one safe path segment")
    return text


def _json_lines(rows: list[dict[str, Any]]) -> str:
    return "".join(
        json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
        for row in rows
    )


def _pointer_matches(
    snapshot: GenerationPointerSnapshot,
    conditions: GenerationPointerConditions,
) -> bool:
    pointer = snapshot.pointer
    if pointer is None:
        return conditions == GenerationPointerConditions.initial()
    return (
        snapshot.etag == conditions.etag
        and pointer.owner_id == conditions.owner_id
        and pointer.fence == conditions.fence
        and pointer.source_generation == conditions.source_generation
        and pointer.active_generation == conditions.active_generation
    )


def _validate_dataset_names(datasets: dict[str, list[dict]]) -> None:
    for name in datasets:
        if not isinstance(name, str):
            raise TypeError("Dataset name must be a string")
        text = str(name).strip()
        path = PurePosixPath(text)
        if (
            not text
            or text != name
            or path.is_absolute()
            or not path.parts
            or any(part in {".", ".."} for part in path.parts)
            or path.as_posix() != text
            or "\\" in text
        ):
            raise ValueError(f"Dataset name must be relative and contained: {name}")


def _declared_artifact_integrity(
    details: Mapping[str, Any],
    *,
    artifact_name: str,
) -> tuple[int, str, str]:
    row_count = details.get("rowCount")
    content_hash = details.get("contentHash")
    if (
        isinstance(row_count, bool)
        or not isinstance(row_count, int)
        or row_count < 0
    ):
        raise TypeError(
            f"Dataset generation row count is invalid: {artifact_name}"
        )
    content_hash = _required_sha256(
        content_hash,
        field=f"Dataset generation content hash: {artifact_name}",
    )
    integrity_hash = _required_sha256(
        details.get("integrityHash"),
        field=f"Dataset generation integrity hash: {artifact_name}",
    )
    return row_count, content_hash, integrity_hash


def _required_sha256(value: Any, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise TypeError(f"{field} is invalid")
    return value


def _required_unique_nonempty_strings(
    manifest: Mapping[str, Any],
    field: str,
) -> list[str]:
    values = manifest.get(field)
    if (
        not isinstance(values, list)
        or not values
        or not all(isinstance(value, str) and bool(value.strip()) for value in values)
    ):
        raise TypeError(f"Dataset generation {field} are invalid")
    if len(values) != len(set(values)):
        raise ValueError(f"Dataset generation {field} contain duplicates")
    return values


def _validate_source_partitions(datasets: dict[str, list[dict]]) -> None:
    """Validate staged Exposure partitions before any generation write."""

    partition_rows = datasets.get("exposure/source_partition_rows", [])
    status_rows = [
        row
        for row in datasets.get("situations/source_status", [])
        if row.get("partition_key")
    ]
    if not partition_rows and not status_rows:
        return

    required_status = {
        "partition_key",
        "connection_id",
        "source_family",
        "attempted_generation",
        "effective_generation",
        "attempted_at",
        "last_success_at",
        "row_count",
        "represented_count",
        "expected_count",
        "completeness",
        "safe_error_code",
        "safe_error_summary",
    }
    statuses: dict[str, dict[str, Any]] = {}
    for row in status_rows:
        missing = sorted(
            field
            for field in required_status
            if field not in row or row[field] is None
        )
        if missing:
            raise ValueError(
                "Invalid source partition status contract: " + ",".join(missing)
            )
        partition_key = str(row["partition_key"])
        if partition_key in statuses:
            raise ValueError("Duplicate source partition status")
        if row["completeness"] not in {
            "complete",
            "healthy-empty",
            "stale",
            "unavailable",
        }:
            raise ValueError("Invalid source partition completeness")
        expected = int(row["expected_count"])
        represented = int(row["represented_count"])
        row_count = int(row["row_count"])
        if expected < 1 or represented not in {0, 1} or row_count < 0:
            raise ValueError("Invalid source partition count")
        if row["completeness"] == "unavailable":
            if represented or row["effective_generation"]:
                raise ValueError("Invalid unavailable source partition")
        elif not represented or not row["effective_generation"]:
            raise ValueError("Invalid usable source partition")
        statuses[partition_key] = row

    actual_counts = {key: 0 for key in statuses}
    seen_rows: set[tuple[str, str, str]] = set()
    for row in partition_rows:
        required_row = {
            "partition_key",
            "query_name",
            "row_key",
            "payload_json",
            "effective_generation",
        }
        if any(field not in row or row[field] is None for field in required_row):
            raise ValueError("Invalid source partition row contract")
        partition_key = str(row["partition_key"])
        status = statuses.get(partition_key)
        if status is None:
            raise ValueError("Invalid source partition reference")
        identity = (
            partition_key,
            str(row["query_name"]),
            str(row["row_key"]),
        )
        if identity in seen_rows:
            raise ValueError("Duplicate source partition row")
        seen_rows.add(identity)
        if row["effective_generation"] != status["effective_generation"]:
            raise ValueError("Invalid source partition generation reference")
        try:
            payload = json.loads(str(row["payload_json"]))
        except json.JSONDecodeError as exc:
            raise ValueError("Invalid source partition payload") from exc
        if not isinstance(payload, dict):
            raise TypeError("Invalid source partition payload")
        actual_counts[partition_key] += 1

    for partition_key, status in statuses.items():
        if actual_counts[partition_key] != int(status["row_count"]):
            raise ValueError("Invalid source partition row count")
        if status["completeness"] == "healthy-empty" and actual_counts[partition_key]:
            raise ValueError("Invalid healthy-empty source partition")


def _sorted_rows(rows: list[dict]) -> list[dict]:
    return sorted(
        (dict(row) for row in rows),
        key=lambda row: (
            json.dumps(_semantic(row), sort_keys=True, separators=(",", ":")),
            json.dumps(
                row,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ),
        ),
    )


def _semantic_hash(rows: list[dict]) -> str:
    digest = hashlib.sha256()
    encoder = json.JSONEncoder(
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    digest.update(b"[")
    for index, row in enumerate(rows):
        if index:
            digest.update(b",")
        for chunk in encoder.iterencode(_semantic(row)):
            digest.update(chunk.encode())
    digest.update(b"]")
    return digest.hexdigest()


def _canonical_hash(value: Any) -> str:
    """Hash canonical JSON incrementally without materializing one large string."""
    digest = hashlib.sha256()
    encoder = json.JSONEncoder(
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    for chunk in encoder.iterencode(value):
        digest.update(chunk.encode())
    return digest.hexdigest()


def _manifest_integrity_hash(manifest: Mapping[str, Any]) -> str:
    """Authenticate artifact declarations and all immutable run metadata."""
    datasets = manifest.get("datasets")
    if not isinstance(datasets, Mapping):
        raise TypeError("Dataset generation manifest datasets are invalid")
    metadata = {
        key: value
        for key, value in manifest.items()
        if key not in _MANIFEST_DERIVED_FIELDS
    }
    artifacts = {
        key: dict(value) if isinstance(value, Mapping) else value
        for key, value in datasets.items()
    }
    return _canonical_hash(
        {
            "artifacts": artifacts,
            "metadata": metadata,
        }
    )


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
