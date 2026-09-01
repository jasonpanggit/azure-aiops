from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from onboarding.graph_normalize import Normalizer, changed_resource_ids

FIXTURE = Path(__file__).parent / "fixtures" / "mock_arg_responses.json"


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text())


def test_row_hashes_are_populated_for_every_resource() -> None:
    payload = _fixture()
    graph = Normalizer().normalize(payload, datetime(2026, 8, 17, tzinfo=UTC))

    resource_ids = {row["id"].lower() for row in payload["resources"]}
    assert set(graph.row_hashes) == resource_ids
    assert all(isinstance(value, str) and value for value in graph.row_hashes.values())


def test_identical_rows_produce_identical_hash() -> None:
    payload = _fixture()
    first = Normalizer().normalize(payload, datetime(2026, 8, 17, tzinfo=UTC))
    second = Normalizer().normalize(json.loads(json.dumps(payload)), datetime(2026, 8, 17, tzinfo=UTC))

    assert first.row_hashes == second.row_hashes


def test_changed_field_produces_different_hash() -> None:
    payload = _fixture()
    baseline = Normalizer().normalize(payload, datetime(2026, 8, 17, tzinfo=UTC))

    changed_payload = json.loads(json.dumps(payload))
    changed_payload["resources"][0]["tags"] = {**changed_payload["resources"][0].get("tags", {}), "env": "prod"}
    changed = Normalizer().normalize(changed_payload, datetime(2026, 8, 17, tzinfo=UTC))

    resource_id = payload["resources"][0]["id"].lower()
    assert baseline.row_hashes[resource_id] != changed.row_hashes[resource_id]
    # Every other resource's hash is untouched.
    other_ids = set(baseline.row_hashes) - {resource_id}
    assert all(baseline.row_hashes[rid] == changed.row_hashes[rid] for rid in other_ids)
    # The row is still fully normalized/present in the graph regardless of
    # whether its hash matched a prior run -- incremental discovery is an
    # opt-in signal for callers, never a silent drop.
    entity_ids = {row["id"].lower() for rows in changed.entities.values() for row in rows}
    assert resource_id in entity_ids


def test_changed_resource_ids_returns_only_added_or_changed() -> None:
    previous = {"a": "hash-a", "b": "hash-b", "c": "hash-c"}
    current = {"a": "hash-a", "b": "hash-b-changed", "d": "hash-d"}

    assert changed_resource_ids(previous, current) == {"b", "d"}


def test_changed_resource_ids_empty_when_nothing_changed() -> None:
    previous = {"a": "hash-a", "b": "hash-b"}
    current = dict(previous)

    assert changed_resource_ids(previous, current) == set()


def test_normalize_accepts_previous_row_hashes_without_behavior_change() -> None:
    payload = _fixture()
    baseline = Normalizer().normalize(payload, datetime(2026, 8, 17, tzinfo=UTC))

    with_previous = Normalizer().normalize(
        json.loads(json.dumps(payload)),
        datetime(2026, 8, 17, tzinfo=UTC),
        previous_row_hashes=baseline.row_hashes,
    )

    assert with_previous.entities == baseline.entities
    assert with_previous.relationships == baseline.relationships
    assert with_previous.row_hashes == baseline.row_hashes
