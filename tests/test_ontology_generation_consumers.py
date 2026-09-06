from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from ontology_discovery.generation_resolver import (
    COMPATIBILITY_ALIAS_VERSION,
    CONSUMER_INVENTORY,
    GenerationResolver,
    scan_direct_ontology_consumers,
)


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
