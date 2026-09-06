from __future__ import annotations

import base64
import io
import json
from pathlib import Path

import pytest

from api.routers.twin import _composer
from api.runtime import _load_generation_tables
from api.scope import Scope
from fabric.data_agent_manager import build_data_agent_definition
from fabric.semantic_model_manager import build_semantic_model_definition
from ontology_discovery.generation_resolver import (
    COMPATIBILITY_ALIAS_VERSION,
    CONSUMER_INVENTORY,
    GenerationResolver,
    scan_direct_ontology_consumers,
)
from operations.tools import STATUS_OK, call_tool
from semantic.semantic_registry import SemanticRegistry


class _MemoryFs:
    def __init__(self, files: dict[str, str]) -> None:
        self.files = files

    def exists(self, path: str) -> bool:
        prefix = f"{path.rstrip('/')}/"
        return path in self.files or any(name.startswith(prefix) for name in self.files)

    def open(self, path: str, mode: str = "rt") -> io.StringIO:
        assert mode == "rt"
        return io.StringIO(self.files[path])

    def info(self, path: str) -> dict[str, str]:
        return {"etag": "pointer-etag-7"} if path.endswith("current.json") else {}


class _RemoteStore:
    is_remote = True
    root = "lake/ontology"
    generations = "lake/ontology/generations"
    uri_generations = (
        "abfss://workspace@onelake.dfs.fabric.microsoft.com/lake/Files/ontology/generations"
    )
    pointer_path = "lake/ontology/current.json"

    def __init__(self) -> None:
        self.fs = _MemoryFs(
            {
                self.pointer_path: json.dumps(
                    {
                        "generation": "generation-old",
                        "previous_generation": "generation-prior",
                        "source_generation": "inventory-41",
                        "etag": "payload-etag",
                    }
                ),
                f"{self.generations}/generation-old/manifest.json": json.dumps(
                    {"sourceGeneration": "inventory-41"}
                ),
                f"{self.generations}/generation-old/ontology_entities.jsonl": (
                    '{"resource_id":"old"}\n'
                ),
                f"{self.generations}/generation-prior/manifest.json": "{}",
            }
        )

    def current_generation(self) -> str:
        pointer = json.loads(self.fs.files[self.pointer_path])
        return f"{self.generations}/{pointer['generation']}"


def test_resolver_returns_one_immutable_generation_snapshot():
    store = _RemoteStore()
    resolver = GenerationResolver(store)

    selection = resolver.resolve()

    assert selection.active_generation.endswith("/generation-old")
    assert selection.active_generation_uri.endswith("/generation-old")
    assert selection.prior_generation.endswith("/generation-prior")
    assert selection.pointer_etag == "pointer-etag-7"
    assert selection.source_generation == "inventory-41"
    assert selection.compatibility_alias_version == COMPATIBILITY_ALIAS_VERSION
    assert resolver.read_dataset("ontology_entities", selection=selection) == [
        {"resource_id": "old"}
    ]

    store.fs.files[store.pointer_path] = json.dumps(
        {
            "generation": "generation-new",
            "previous_generation": "generation-old",
            "source_generation": "inventory-42",
        }
    )
    store.fs.files[
        f"{store.generations}/generation-new/ontology_entities.jsonl"
    ] = '{"resource_id":"new"}\n'

    # A request keeps using the originally selected immutable generation.
    assert resolver.read_dataset("ontology_entities", selection=selection) == [
        {"resource_id": "old"}
    ]
    assert resolver.resolve().active_generation.endswith("/generation-new")


@pytest.mark.parametrize("unsafe_name", ["../ontology_entities", "/tmp/table", "x//y"])
def test_resolver_rejects_unsafe_dataset_names(unsafe_name: str):
    with pytest.raises(ValueError):
        GenerationResolver(_RemoteStore()).read_dataset(unsafe_name)


def test_inventory_covers_every_consumer_family_and_required_contract_fields():
    required_families = {"api", "fabric", "agent", "export", "semantic"}

    assert {entry.family for entry in CONSUMER_INVENTORY} == required_families
    assert len({entry.consumer_id for entry in CONSUMER_INVENTORY}) == len(
        CONSUMER_INVENTORY
    )
    for entry in CONSUMER_INVENTORY:
        assert entry.path.startswith("src/")
        assert entry.call_site
        assert entry.owner
        assert entry.read_path
        assert entry.disposition in {"resolver", "compatibility-alias", "indirect"}
        assert "rollback" in entry.rollback_assertion.casefold()


def test_repository_inventory_has_no_unlisted_direct_consumer():
    repo_root = Path(__file__).resolve().parents[1]

    discovered = scan_direct_ontology_consumers(repo_root)
    inventoried_paths = {entry.path for entry in CONSUMER_INVENTORY}

    assert not (discovered - inventoried_paths), (
        "Unlisted direct ontology consumer(s): "
        + ", ".join(sorted(discovered - inventoried_paths))
    )


def test_inventory_scan_detects_new_direct_consumer(tmp_path: Path):
    path = tmp_path / "src" / "api" / "new_reader.py"
    path.parent.mkdir(parents=True)
    path.write_text(
        'def read(store):\n    return store.read_dataset("ontology_entities")\n'
    )

    assert scan_direct_ontology_consumers(tmp_path) == {"src/api/new_reader.py"}


def test_documented_inventory_lists_each_executable_entry():
    repo_root = Path(__file__).resolve().parents[1]
    document = (
        repo_root / "docs" / "ontology-generation-consumer-inventory.md"
    ).read_text()

    for entry in CONSUMER_INVENTORY:
        assert entry.consumer_id in document
        assert entry.path in document
        assert entry.owner in document
        assert entry.rollback_assertion in document


def _decode_definition_part(definition: dict, suffix: str) -> dict:
    part = next(part for part in definition["parts"] if part["path"].endswith(suffix))
    return json.loads(base64.b64decode(part["payload"]))


def test_api_generation_loader_pins_one_generation_for_the_mapper():
    store = _RemoteStore()

    class _Mapper:
        def load(self, generation, run_id, *, fs=None):
            rows = GenerationResolver(store).read_dataset(
                "ontology_entities",
                selection=GenerationResolver(store).selection_for(generation),
            )
            return {"ontology_entities": rows, "run_id": run_id, "fs": fs}

    old_tables, old_selection = _load_generation_tables(store, _Mapper(), "run-old")
    store.fs.files[store.pointer_path] = json.dumps(
        {
            "generation": "generation-new",
            "previous_generation": "generation-old",
            "source_generation": "inventory-42",
        }
    )
    store.fs.files[
        f"{store.generations}/generation-new/manifest.json"
    ] = '{"sourceGeneration":"inventory-42"}'
    store.fs.files[
        f"{store.generations}/generation-new/ontology_entities.jsonl"
    ] = '{"resource_id":"new"}\n'
    new_tables, new_selection = _load_generation_tables(store, _Mapper(), "run-new")
    store.fs.files[store.pointer_path] = json.dumps(
        {
            "generation": "generation-old",
            "previous_generation": "generation-new",
            "source_generation": "inventory-41",
        }
    )
    rollback_tables, rollback_selection = _load_generation_tables(
        store, _Mapper(), "run-rollback"
    )

    assert [old_tables["ontology_entities"][0]["resource_id"], old_selection.generation_id] == [
        "old",
        "generation-old",
    ]
    assert [new_tables["ontology_entities"][0]["resource_id"], new_selection.generation_id] == [
        "new",
        "generation-new",
    ]
    assert [
        rollback_tables["ontology_entities"][0]["resource_id"],
        rollback_selection.generation_id,
    ] == ["old", "generation-old"]


def test_fabric_alias_preserves_public_table_names_and_binds_generation():
    selection = GenerationResolver(_RemoteStore()).resolve()
    aliases = GenerationResolver(_RemoteStore()).compatibility_aliases(selection)

    data_agent = build_data_agent_definition(
        lakehouse_id="lake",
        lakehouse_workspace_id="workspace",
        lakehouse_display_name="ontology",
        ai_instructions="Read only.",
        generation=selection,
        table_aliases=aliases,
    )
    datasource = _decode_definition_part(data_agent, "/datasource.json")
    semantic_model = build_semantic_model_definition(
        "ontology-model",
        ["ontology_entities", "ontology_relationships"],
        generation=selection,
        table_aliases=aliases,
    )
    model = _decode_definition_part(semantic_model, "model.bim")

    assert {item["display_name"] for item in datasource["elements"]} == {
        "ontology_entities",
        "ontology_relationships",
    }
    # Existing Fabric Data Agent datasource schema remains unchanged; the
    # versioned alias binding is enforced before the definition is built.
    assert "generationBinding" not in datasource
    assert {table["name"] for table in model["model"]["tables"]} == {
        "ontology_entities",
        "ontology_relationships",
    }
    assert model["model"]["annotations"] == [
        {
            "name": "aiops.ontologyGeneration",
            "value": f"{COMPATIBILITY_ALIAS_VERSION}:generation-old",
        }
    ]


def test_operations_agent_uses_one_selected_generation_per_tool_call():
    store = _RemoteStore()
    resolver = GenerationResolver(store)

    class _Semantic:
        def __init__(self, generation_id: str) -> None:
            self.generation_id = generation_id

        def get_service_context(self, name, *, subject_type):
            return {
                "subject": {"name": name, "entity_type": subject_type},
                "generation": self.generation_id,
                "freshness": "2026-01-01T00:00:00+00:00",
            }

    class _GenerationSemantic:
        def for_generation(self, selection):
            return _Semantic(selection.generation_id)

    class _Context:
        generation_resolver_provider = lambda self: resolver

        def resolve_provider(self, name, *, optional=False):
            assert name == "semantic"
            return _GenerationSemantic()

    def invoke() -> str:
        result = call_tool(
            "business_service_context",
            {"name": "Payments"},
            context=_Context(),
            scope=Scope(),
        )
        assert result.status == STATUS_OK
        assert result.evidence[0].source_table == "ontology_entities"
        return result.data["generation"]

    old = invoke()
    store.fs.files[store.pointer_path] = json.dumps(
        {"generation": "generation-new", "previous_generation": "generation-old"}
    )
    store.fs.files[f"{store.generations}/generation-new/manifest.json"] = "{}"
    new = invoke()
    store.fs.files[store.pointer_path] = json.dumps(
        {"generation": "generation-old", "previous_generation": "generation-new"}
    )
    rolled_back = invoke()

    assert (old, new, rolled_back) == (
        "generation-old",
        "generation-new",
        "generation-old",
    )


def test_twin_export_resolves_old_new_then_old_without_mixed_generation():
    store = _RemoteStore()
    resolver = GenerationResolver(store)

    class _Indexes:
        relationships = ()

        def __init__(self, generation_id: str) -> None:
            self.entities = {
                f"entity-{generation_id}": {
                    "resource_id": f"entity-{generation_id}",
                    "entity_type": "Application",
                    "name": generation_id,
                }
            }

    class _Semantic:
        def __init__(self, generation_id: str) -> None:
            self.indexes = _Indexes(generation_id)
            self.ontology_synchronized_at = "2026-01-01T00:00:00+00:00"

    class _GenerationProvider:
        def for_generation(self, selection):
            return _Semantic(selection.generation_id)

    class _Context:
        generation_resolver_provider = lambda self: resolver
        hybrid_network_provider = None
        hybrid_vulnerability_provider = None
        hybrid_incident_provider = None
        hybrid_remediation_provider = None

        def resolve_provider(self, name, *, optional=False):
            return _GenerationProvider() if name == "semantic" else None

    def exported_names() -> list[str]:
        snapshot = _composer(_Context(), Scope()).export()["snapshot"]
        return [entity["name"] for entity in snapshot["entities"]]

    old = exported_names()
    store.fs.files[store.pointer_path] = json.dumps(
        {"generation": "generation-new", "previous_generation": "generation-old"}
    )
    store.fs.files[f"{store.generations}/generation-new/manifest.json"] = "{}"
    new = exported_names()
    store.fs.files[store.pointer_path] = json.dumps(
        {"generation": "generation-old", "previous_generation": "generation-new"}
    )
    rolled_back = exported_names()

    assert old == ["generation-old"]
    assert new == ["generation-new"]
    assert rolled_back == ["generation-old"]


def test_semantic_registry_binds_sources_to_one_generation_and_rolls_back():
    store = _RemoteStore()
    resolver = GenerationResolver(store)

    def registry_generation() -> tuple[str, tuple[str, ...]]:
        selection = resolver.resolve()
        registry = SemanticRegistry.default().for_generation(
            selection,
            resolver.compatibility_aliases(selection),
        )
        model = registry.get("Application")
        return model.generation_id, model.sources

    old = registry_generation()
    store.fs.files[store.pointer_path] = json.dumps(
        {"generation": "generation-new", "previous_generation": "generation-old"}
    )
    store.fs.files[f"{store.generations}/generation-new/manifest.json"] = "{}"
    new = registry_generation()
    store.fs.files[store.pointer_path] = json.dumps(
        {"generation": "generation-old", "previous_generation": "generation-new"}
    )
    rolled_back = registry_generation()

    assert old == (
        "generation-old",
        ("ontology_entities", "ontology_relationships", "inventory", "compliance"),
    )
    assert new[0] == "generation-new"
    assert rolled_back == old
