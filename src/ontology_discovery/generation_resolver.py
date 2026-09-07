"""Immutable, request-scoped ontology generation resolution.

``DatasetStore`` owns publication.  This module owns the read boundary: it
captures the active pointer once and makes every table read in an operation use
that captured generation, even if promotion or rollback happens concurrently.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

COMPATIBILITY_ALIAS_VERSION = "ontology-generation-alias/v1"
ONTOLOGY_TABLES = ("ontology_entities", "ontology_relationships")
_SCAN_ROOTS = ("src/api", "src/fabric", "src/operations", "src/semantic")
_DIRECT_MARKERS = ("ontology_entities", "ontology_relationships", "current.json")
_SAFE_DATASET_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*(/[A-Za-z0-9][A-Za-z0-9_.-]*)*$")


@dataclass(frozen=True)
class GenerationSelection:
    """One immutable view of the mutable active-generation pointer."""

    active_generation: str
    active_generation_uri: str
    prior_generation: str | None
    pointer_etag: str
    source_generation: str
    compatibility_alias_version: str = COMPATIBILITY_ALIAS_VERSION

    @property
    def generation_id(self) -> str:
        return self.active_generation.rstrip("/").rsplit("/", 1)[-1]


@dataclass(frozen=True)
class CompatibilityAlias:
    """Stable public table name bound to one immutable physical generation."""

    logical_name: str
    physical_path: str
    generation_id: str
    version: str = COMPATIBILITY_ALIAS_VERSION


@dataclass(frozen=True)
class ConsumerInventoryEntry:
    """Executable metadata for one ontology-reading integration seam."""

    consumer_id: str
    family: str
    path: str
    call_site: str
    owner: str
    read_path: str
    disposition: str
    rollback_assertion: str


def _entry(
    consumer_id: str,
    family: str,
    path: str,
    call_site: str,
    owner: str,
    read_path: str,
    disposition: str,
) -> ConsumerInventoryEntry:
    return ConsumerInventoryEntry(
        consumer_id=consumer_id,
        family=family,
        path=path,
        call_site=call_site,
        owner=owner,
        read_path=read_path,
        disposition=disposition,
        rollback_assertion="Rollback re-resolves the prior immutable generation without mixed rows.",
    )


# This manifest is intentionally code, not an informal checklist.  The contract
# test compares it with a repository scan and the companion document.
CONSUMER_INVENTORY: tuple[ConsumerInventoryEntry, ...] = (
    _entry("api-runtime-snapshot", "api", "src/api/runtime.py", "_load_snapshot_tables", "API runtime", "DatasetStore pointer -> GenerationResolver -> mapper", "resolver"),
    _entry("api-inventory-orchestration", "api", "src/api/inventory_orchestration.py", "combined generation lookup", "API inventory", "combined store active pointer", "indirect"),
    _entry("api-context-router", "api", "src/api/routers/context.py", "semantic context routes", "API context", "request semantic provider", "indirect"),
    _entry("api-copilot-router", "api", "src/api/routers/copilot.py", "copilot context retrieval", "API Copilot", "request provider and evidence alias", "indirect"),
    _entry("api-governance-router", "api", "src/api/routers/governance.py", "governance projection", "API governance", "request provider and evidence alias", "indirect"),
    _entry("api-graph-router", "api", "src/api/routers/graph.py", "graph traversal", "API graph", "request semantic provider", "indirect"),
    _entry("api-network-router", "api", "src/api/routers/network.py", "network projection", "API network", "request network provider", "indirect"),
    _entry("fabric-data-agent", "fabric", "src/fabric/data_agent_manager.py", "build_data_agent_definition", "Fabric Data Agent", "versioned logical table aliases", "compatibility-alias"),
    _entry("fabric-semantic-model", "fabric", "src/fabric/semantic_model_manager.py", "build_semantic_model_definition", "Fabric semantic model", "versioned logical table aliases", "compatibility-alias"),
    _entry("fabric-dataset-mapper", "fabric", "src/fabric/dataset_mapper.py", "InventoryDatasetMapper.load", "Fabric mapping", "resolver-selected generation directory", "resolver"),
    _entry("fabric-sync-reader", "fabric", "src/fabric/sync_service.py", "semantic_snapshot and ontology_query", "Fabric runtime", "compatibility alias over selected generation", "compatibility-alias"),
    _entry("fabric-schema-registry", "fabric", "src/fabric/schema_registry.py", "ontology table schemas", "Fabric schema", "logical schema only", "indirect"),
    _entry("fabric-telemetry", "fabric", "src/fabric/telemetry.py", "ontology metrics", "Fabric telemetry", "post-read aggregate only", "indirect"),
    _entry("operations-tools", "agent", "src/operations/tools.py", "_semantic_result and network tools", "Operations agent", "request provider and evidence alias", "indirect"),
    _entry("twin-export", "export", "src/api/routers/twin.py", "_composer and export", "Operational twin", "one request-selected semantic generation", "resolver"),
    _entry("semantic-registry", "semantic", "src/semantic/semantic_registry.py", "SemanticRegistry.default", "Semantic knowledge layer", "versioned logical source aliases", "compatibility-alias"),
)


class GenerationResolver:
    """Resolve and read one active ``DatasetStore`` generation at a time."""

    def __init__(self, store: Any) -> None:
        self.store = store

    def resolve(self) -> GenerationSelection:
        pointer = self._pointer_payload()
        active = self.store.current_generation()
        if not active:
            raise LookupError("No active ontology generation")
        active = self._validated_generation(str(active))
        manifest = self._read_json(f"{active}/manifest.json", required=False)
        prior_name = str(
            pointer.get("previous_generation")
            or pointer.get("prior_generation")
            or pointer.get("previousGeneration")
            or ""
        ).strip()
        prior = self._generation_path(prior_name) if prior_name else self._prior_local(active)
        source_generation = str(
            pointer.get("source_generation")
            or pointer.get("sourceGeneration")
            or manifest.get("source_generation")
            or manifest.get("sourceGeneration")
            or manifest.get("runId")
            or ""
        )
        return GenerationSelection(
            active_generation=active,
            active_generation_uri=self._generation_uri(active),
            prior_generation=prior,
            pointer_etag=self._pointer_etag(pointer),
            source_generation=source_generation,
        )

    def selection_for(self, generation: str) -> GenerationSelection:
        """Create a read selection for an already captured generation path."""
        active = self._validated_generation(str(generation))
        manifest = self._read_json(f"{active}/manifest.json", required=False)
        return GenerationSelection(
            active_generation=active,
            active_generation_uri=self._generation_uri(active),
            prior_generation=None,
            pointer_etag="",
            source_generation=str(
                manifest.get("source_generation")
                or manifest.get("sourceGeneration")
                or manifest.get("runId")
                or ""
            ),
        )

    def alias(
        self,
        logical_name: str,
        *,
        selection: GenerationSelection | None = None,
    ) -> CompatibilityAlias:
        name = _validated_dataset_name(logical_name)
        selected = selection or self.resolve()
        return CompatibilityAlias(
            logical_name=name,
            physical_path=f"{selected.active_generation}/{name}",
            generation_id=selected.generation_id,
        )

    def compatibility_aliases(
        self,
        selection: GenerationSelection | None = None,
    ) -> dict[str, CompatibilityAlias]:
        """Bind both stable ontology table names to one selected generation."""
        selected = selection or self.resolve()
        return {name: self.alias(name, selection=selected) for name in ONTOLOGY_TABLES}

    def read_dataset(
        self,
        name: str,
        *,
        selection: GenerationSelection | None = None,
    ) -> list[dict[str, Any]]:
        alias = self.alias(name, selection=selection)
        path = f"{alias.physical_path}.jsonl"
        content = self._read_text(path, required=False)
        rows: list[dict[str, Any]] = []
        for line in content.splitlines():
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise TypeError(f"Ontology dataset {name!r} contains a non-object row")
            rows.append(value)
        return rows

    def read_metadata(
        self,
        name: str,
        *,
        selection: GenerationSelection | None = None,
    ) -> dict[str, Any]:
        """Read one safe metadata document from a captured generation."""

        allowed = {
            "manifest.json",
            "validation.json",
            "compatibility.json",
            "lineage.json",
            "audit-intent.json",
            "audit-result.json",
        }
        if name not in allowed:
            raise ValueError("Generation metadata name is not allowed")
        selected = selection or self.resolve()
        return self._read_json(
            f"{selected.active_generation}/{name}",
            required=False,
        )

    def _pointer_payload(self) -> dict[str, Any]:
        if not getattr(self.store, "is_remote", False):
            pointer_path = getattr(self.store, "pointer_path", None)
            if pointer_path is None or not Path(pointer_path).exists():
                # Legacy local DatasetStore generations use only the atomic
                # ``current`` symlink and therefore have no pointer metadata.
                return {}
            return self._read_json(str(pointer_path))
        path = str(self.store.pointer_path)
        if not self.store.fs.exists(path):
            raise LookupError("Ontology generation pointer is missing")
        payload = self._read_json(path)
        return payload

    def _pointer_etag(self, pointer: dict[str, Any]) -> str:
        if getattr(self.store, "is_remote", False):
            try:
                info = self.store.fs.info(str(self.store.pointer_path))
            except (AttributeError, OSError):
                info = {}
            etag = info.get("etag") or info.get("ETag")
            if etag:
                return str(etag).strip('"')
        else:
            pointer_path = getattr(self.store, "pointer_path", None)
            if pointer_path is not None and Path(pointer_path).exists():
                try:
                    body = Path(pointer_path).read_bytes()
                except OSError:
                    return ""
                return hashlib.sha256(body).hexdigest()
        return str(pointer.get("etag") or pointer.get("pointer_etag") or "")

    def _generation_path(self, name: str) -> str:
        if not name or "/" in name or name in {".", ".."}:
            raise ValueError("Generation pointer contains an unsafe generation name")
        return self._validated_generation(f"{self.store.generations}/{name}")

    def _validated_generation(self, generation: str) -> str:
        candidate = generation.rstrip("/")
        configured = getattr(self.store, "generations", None)
        # Several legacy read-port tests use the minimal historical
        # ``current_generation()`` protocol. Treat that returned directory as
        # the only allowed generation rather than weakening containment for a
        # real DatasetStore, which always exposes ``generations``.
        if configured is None:
            return candidate
        base = str(configured).rstrip("/")
        if candidate == base or not candidate.startswith(f"{base}/"):
            raise ValueError("Active generation escapes the immutable generations root")
        return candidate

    def _generation_uri(self, generation: str) -> str:
        if not getattr(self.store, "is_remote", False):
            return generation
        name = generation.rsplit("/", 1)[-1]
        base = str(getattr(self.store, "uri_generations", self.store.generations))
        return f"{base.rstrip('/')}/{name}"

    def _prior_local(self, active: str) -> str | None:
        if getattr(self.store, "is_remote", False) or not hasattr(
            self.store, "generations"
        ):
            return None
        generations = Path(self.store.generations)
        if not generations.exists():
            return None
        candidates = sorted(
            (
                path
                for path in generations.iterdir()
                if path.is_dir() and str(path.resolve()) != active
            ),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )
        return str(candidates[0].resolve()) if candidates else None

    def _read_json(self, path: str, *, required: bool = True) -> dict[str, Any]:
        content = self._read_text(path, required=required)
        if not content:
            return {}
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid generation metadata at {path}") from exc
        if not isinstance(payload, dict):
            raise TypeError(f"Generation metadata at {path} must be an object")
        return payload

    def _read_text(self, path: str, *, required: bool) -> str:
        if getattr(self.store, "is_remote", False):
            if not self.store.fs.exists(path):
                if required:
                    raise LookupError(f"Generation artifact is missing: {path}")
                return ""
            with self.store.fs.open(path, "rt") as handle:
                return handle.read()
        file_path = Path(path)
        if not file_path.exists():
            if required:
                raise LookupError(f"Generation artifact is missing: {path}")
            return ""
        return file_path.read_text()


def _validated_dataset_name(name: str) -> str:
    if (
        not isinstance(name, str)
        or not _SAFE_DATASET_NAME.fullmatch(name)
        or any(part in {".", ".."} for part in PurePosixPath(name).parts)
    ):
        raise ValueError("Dataset name must be a safe relative path")
    return name


class _MarkerVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.found = False

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str) and any(
            marker in node.value for marker in _DIRECT_MARKERS
        ):
            self.found = True

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute) and node.func.attr == "current_generation":
            self.found = True
        self.generic_visit(node)


def scan_direct_ontology_consumers(repo_root: Path) -> set[str]:
    """Return Python files containing a direct ontology read marker.

    The scan intentionally errs toward false positives: writers, schemas, and
    evidence labels are inventoried with an indirect disposition so a new
    occurrence cannot silently become an unreviewed read path.
    """

    discovered: set[str] = set()
    for root_name in _SCAN_ROOTS:
        root = repo_root / root_name
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            try:
                tree = ast.parse(path.read_text())
            except (OSError, SyntaxError):
                continue
            visitor = _MarkerVisitor()
            visitor.visit(tree)
            if visitor.found:
                discovered.add(path.relative_to(repo_root).as_posix())
    return discovered


__all__ = [
    "COMPATIBILITY_ALIAS_VERSION",
    "CONSUMER_INVENTORY",
    "ONTOLOGY_TABLES",
    "CompatibilityAlias",
    "ConsumerInventoryEntry",
    "GenerationResolver",
    "GenerationSelection",
    "scan_direct_ontology_consumers",
]
