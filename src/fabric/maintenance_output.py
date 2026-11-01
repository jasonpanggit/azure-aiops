"""Opt-in local maintenance output preflight, not execution authority."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

import pyarrow as pa

from fabric.dataset_mapper import (
    ONTOLOGY_ENTITY_TYPES,
    ONTOLOGY_RELATIONSHIP_TYPES,
    ontology_entity_table,
    ontology_relationship_table,
)
from fabric.schema_registry import schema_for
from ontology_discovery.publisher import PublicationSafetyError
from storage.onelake_writer import OneLakeWriter


def canonical_json(value: Any) -> str:
    """Encode exact JSON data without nonfinite or implicit string conversions."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def output_digest(value: Any) -> str:
    """Hash canonical JSON; never derive an expected policy during a write."""
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _reject(field: str) -> None:
    raise PublicationSafetyError(f"output_manifest:{field}")


def _location(uri: str) -> tuple[str, ...]:
    # Conservative aliases: local symlinks resolve; OneLake is case-insensitive.
    if type(uri) is not str or any(ord(char) < 32 for char in uri):
        _reject("location")
    parsed = urlsplit(uri)
    if parsed.scheme:
        if (
            parsed.scheme != "abfss"
            or parsed.query
            or parsed.fragment
            or "%" in uri
            or "\\" in uri
            or not parsed.netloc.endswith("@onelake.dfs.fabric.microsoft.com")
        ):
            _reject("location")
        segments = parsed.path.removeprefix("/").split("/")
        if any(part in {"", ".", ".."} for part in segments):
            _reject("location")
        return ("abfss", parsed.netloc.casefold(), *(s.casefold() for s in segments))
    path = Path(uri)
    if not path.is_absolute() or ".." in path.parts:
        _reject("location")
    return ("local", *(part.casefold() for part in path.resolve().parts))


def _overlap(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    return left[: len(right)] == right or right[: len(left)] == left


@dataclass(frozen=True)
class LocalDestinationSnapshot:
    """Canonical destinations with conservative component-wise symlink refusal."""

    identities: tuple[tuple[str, tuple[str, ...]], ...]
    components: tuple[Path, ...]

    @classmethod
    def freeze(cls, destinations: Sequence[str]) -> LocalDestinationSnapshot:
        """Bind all table/catalog identities before any authority callback."""
        components: set[Path] = set()
        identities = []
        for uri in destinations:
            path = Path(uri)
            if not path.is_absolute():
                _reject("destination")
            components.update((path, *path.parents))
            identities.append((uri, _location(uri)))
        snapshot = cls(
            identities=tuple(identities),
            components=tuple(sorted(components)),
        )
        snapshot.assert_unchanged()
        return snapshot

    def assert_unchanged(self) -> None:
        """Check every table and catalog parent after callbacks, before sinks.

        This is not an atomic no-follow filesystem operation. The supported
        cooperating-writer model excludes concurrent hostile filesystem edits
        between this check and the sink call.
        """
        # With absolute, dot-free paths and every ancestor included, refusing
        # links preserves the frozen canonical identities under this model.
        try:
            redirected = any(path.is_symlink() for path in self.components)
        except OSError:
            raise PublicationSafetyError("output_manifest:destination_unreadable") from None
        if redirected:
            _reject("destination_symlink")


@dataclass(frozen=True)
class GenerationOutputContext:
    """Immutable candidate binding, independently supplied for each operation."""

    operation: Literal["admission", "restoration"]
    generation_id: str
    source_generation: str
    content_hash: str
    authorization_digest: str
    attestation_digest: str
    staged_manifest_digest: str
    validation_digest: str
    expected_target: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if self.operation not in {"admission", "restoration"}:
            _reject("operation")
        fields = (
            "tenant_id", "subscription_id", "connection_id",
            "workspace_id", "item_id", "definition_fingerprint",
        )
        if (
            type(self.expected_target) is not tuple
            or any(type(pair) is not tuple or len(pair) != 2 for pair in self.expected_target)
            or tuple(key for key, _ in self.expected_target) != tuple(sorted(fields))
            or any(type(value) is not str or not value for _, value in self.expected_target)
        ):
            _reject("expected_target")
        for value in (
            self.generation_id, self.source_generation, self.content_hash,
            self.authorization_digest, self.attestation_digest,
            self.staged_manifest_digest, self.validation_digest,
        ):
            if type(value) is not str or not value:
                _reject("candidate_binding")


@dataclass(frozen=True)
class TableOutput:
    """Complete pre-write table identity and payload fingerprint."""

    logical_name: str
    workspace_id: str
    lakehouse_id: str
    table_schema: str
    physical_uri: str
    arrow_schema_digest: str
    row_count: int
    content_digest: str
    mode: Literal["OVERWRITE"] = "OVERWRITE"

    def __post_init__(self) -> None:
        if (
            any(type(value) is not str for value in (
                self.logical_name, self.workspace_id, self.lakehouse_id,
                self.table_schema, self.physical_uri,
                self.arrow_schema_digest, self.content_digest,
            ))
            or type(self.row_count) is not int
            or self.row_count < 0
            or self.mode != "OVERWRITE"
            or not re.fullmatch(r"[a-f0-9]{64}", self.arrow_schema_digest)
            or not re.fullmatch(r"[a-f0-9]{64}", self.content_digest)
        ):
            _reject("table_shape")


@dataclass(frozen=True)
class GenerationOutputManifest:
    """Full local output inventory; catalog versions are not predicted."""

    tables: tuple[TableOutput, ...]
    catalog_uri: str
    catalog_json: str
    target_fingerprint: str
    native_enabled: Literal[False] = False
    native_targets: tuple[str, ...] = ()
    version: Literal["maintenance-output/v1"] = "maintenance-output/v1"

    def __post_init__(self) -> None:
        if (
            type(self.tables) is not tuple
            or any(type(table) is not TableOutput for table in self.tables)
            or any(type(value) is not str for value in (
                self.catalog_uri, self.catalog_json, self.target_fingerprint,
            ))
        ):
            _reject("manifest_shape")


def target_fingerprint(onelake: OneLakeWriter) -> str:
    """Bind the effective local sink, not its environment variable or YAML source."""
    if type(onelake) is not OneLakeWriter or onelake.local_root is None:
        _reject("unsupported_sink")
    return output_digest({
        "workspace_id": onelake.workspace_id,
        "lakehouse_id": onelake.lakehouse_id,
        "workspace_name": onelake.workspace_name,
        "lakehouse_name": onelake.lakehouse_name,
        "table_schema": onelake.table_schema,
        "local_root": str(onelake.local_root.resolve()),
        "storage_options": onelake.storage_options,
    })


def describe_outputs(
    products: Mapping[str, Sequence[Mapping[str, Any]]],
    onelake: OneLakeWriter,
    catalog: Mapping[str, Any],
    *,
    schemas: Mapping[str, pa.Schema] | None = None,
) -> GenerationOutputManifest:
    """Describe outputs for offline policy construction or runtime comparison.

    A runtime description is never used as the expected policy.
    """
    fingerprint = target_fingerprint(onelake)
    tables = []
    for name, rows in sorted(products.items()):
        layer, logical = name.split("_", 1)
        tables.append(TableOutput(
            logical_name=name,
            workspace_id=onelake.workspace_id,
            lakehouse_id=onelake.lakehouse_id,
            table_schema=onelake.table_schema,
            physical_uri=onelake.table_uri(layer, logical),
            arrow_schema_digest=hashlib.sha256(
                (schemas[name] if schemas is not None else schema_for(name)).serialize()
            ).hexdigest(),
            row_count=len(rows),
            content_digest=output_digest(sorted(canonical_json(dict(row)) for row in rows)),
        ))
    return GenerationOutputManifest(
        tables=tuple(tables),
        catalog_uri=str(onelake.local_root / "Files/ontology/metadata/catalog.json"),
        catalog_json=canonical_json(catalog),
        target_fingerprint=fingerprint,
    )


@dataclass(frozen=True)
class GenerationOutputPolicy:
    """Server-owned expected outputs; no loader, CLI switch or live approval.

    Both operation context and full manifest must be independently pinned.
    This local-only interface intentionally cannot instantiate the complete
    isolated acceptance contract or confer authority.
    """

    context: GenerationOutputContext
    manifest: GenerationOutputManifest
    protected_roots: tuple[str, ...]
    entity_types: tuple[str, ...]
    relationship_triples: tuple[tuple[str, str, str], ...]

    def __post_init__(self) -> None:
        if (
            type(self.context) is not GenerationOutputContext
            or type(self.manifest) is not GenerationOutputManifest
            or type(self.manifest.tables) is not tuple
            or any(type(table) is not TableOutput for table in self.manifest.tables)
            or type(self.protected_roots) is not tuple
            or not self.protected_roots
            or self.entity_types != tuple(sorted(ONTOLOGY_ENTITY_TYPES))
            or self.relationship_triples != tuple(sorted(ONTOLOGY_RELATIONSHIP_TYPES))
            or type(self.entity_types) is not tuple
            or type(self.relationship_triples) is not tuple
            or any(type(triple) is not tuple for triple in self.relationship_triples)
        ):
            _reject("policy_shape")
        mapped = [
            *(ontology_entity_table(name) for name in self.entity_types),
            *(ontology_relationship_table(*triple) for triple in self.relationship_triples),
            "ontology_entities", "ontology_relationships",
            "ontology_health", "ontology_quality_report",
        ]
        if len({name.casefold() for name in mapped}) != len(mapped):
            _reject("type_mapping_alias")
        manifest = self.manifest
        if (
            manifest.version != "maintenance-output/v1"
            or manifest.native_enabled is not False
            or manifest.native_targets != ()
            or type(manifest.native_targets) is not tuple
        ):
            _reject("native_or_version")
        names = tuple(table.logical_name for table in manifest.tables)
        if names != tuple(sorted(mapped)):
            _reject("table_membership")
        destinations = [_location(table.physical_uri) for table in manifest.tables]
        destinations.append(_location(manifest.catalog_uri))
        protected = [_location(root) for root in self.protected_roots]
        if any(
            _overlap(left, right)
            for index, left in enumerate(destinations)
            for right in destinations[index + 1:]
        ):
            _reject("destination_alias")
        if any(_overlap(dest, root) for dest in destinations for root in protected):
            _reject("protected_destination")

    def validate_candidate(
        self,
        context: GenerationOutputContext,
        entities: Sequence[Mapping[str, Any]],
        relationships: Sequence[Mapping[str, Any]],
    ) -> None:
        """Reject unknown types, including inactive rows, before product building."""
        if context != self.context:
            _reject("candidate_context")
        entity_types = set(self.entity_types)
        triples = set(self.relationship_triples)
        if any(
            type(row.get("entity_type")) is not str
            or row["entity_type"] not in entity_types
            for row in entities
        ):
            _reject("entity_closure")
        if any(
            any(type(row.get(key)) is not str for key in ("subject_type", "predicate", "object_type"))
            or (row["subject_type"], row["predicate"], row["object_type"]) not in triples
            for row in relationships
        ):
            _reject("relationship_closure")

    def validate_outputs(self, actual: GenerationOutputManifest) -> None:
        """Compare every table, destination, schema, payload and catalog field."""
        if actual != self.manifest:
            _reject("complete_manifest")
