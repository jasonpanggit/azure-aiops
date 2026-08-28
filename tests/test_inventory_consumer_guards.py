"""Regression guards for the inventory identity ownership boundary."""

from pathlib import Path


ROOT = Path(__file__).parents[1]
IDENTITY_CONSUMERS = (
    ROOT / "src/api",
    ROOT / "src/onboarding/agent_queries.py",
    ROOT / "src/operations",
    ROOT / "src/semantic",
)
EXCLUDED = {
    ROOT / "src/onboarding/inventory_read_adapter.py",
    ROOT / "src/onboarding/ingestion_storage.py",
    ROOT / "src/semantic/live_provider.py",
}
FORBIDDEN = (
    "read_dataset(\"inventory/",
    "read_dataset('inventory/",
    "ResourceGraph",
    "arg_client.query",
    "query_resources",
)


def test_identity_consumers_use_inventory_port_not_raw_acquisition() -> None:
    offenders: list[str] = []
    paths: list[Path] = []
    for entry in IDENTITY_CONSUMERS:
        paths.extend(entry.rglob("*.py") if entry.is_dir() else [entry])
    for path in paths:
        if path in EXCLUDED or "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for marker in FORBIDDEN:
            if marker in text:
                offenders.append(f"{path.relative_to(ROOT)}: {marker}")
    assert not offenders, "raw identity acquisition in consumer: " + ", ".join(offenders)


def test_inventory_identity_consumers_are_explicitly_enumerated() -> None:
    assert {path.name for path in IDENTITY_CONSUMERS} >= {
        "api",
        "agent_queries.py",
        "operations",
        "semantic",
    }
