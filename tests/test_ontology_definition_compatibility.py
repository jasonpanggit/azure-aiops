"""Definition compatibility: legacy/TMDL classification, preservation, publisher gate.

Fixture provenance: tests/fixtures/ontology_maintenance_definitions.json. The legacy
definition is real OntologyPublisher output; TMDL/unknown/mixed are SYNTHETIC. The
recorded 163-part native capture is not available locally (live gate pending).
"""

from __future__ import annotations

import base64
import json
from copy import deepcopy
from pathlib import Path

import pytest

from ontology.definition_compatibility import (
    DefinitionBoundsError,
    DefinitionFormatMismatch,
    classify_definition,
    compare_definitions,
    decode_parts,
    definition_fingerprint,
    plan_operation,
    stable_ids,
)
from ontology.ontology_publisher import OntologyPublisher

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "ontology_maintenance_definitions.json").read_text()
)


def _fx(name: str) -> dict:
    return deepcopy(FIXTURE[name])


class _Spy:
    def __init__(self, definition: dict) -> None:
        self.definition = definition
        self.updates: list[dict] = []
        self.creates: list = []

    def resolve(self, **_k):
        return {"id": "item-1", "displayName": "X"}

    def get_definition(self, _id):
        return deepcopy(self.definition)

    def update_definition(self, _id, definition):
        self.updates.append(definition)
        return {}


def _publish(manager, **kwargs):
    pub = OntologyPublisher(manager, workspace_id="ws", lakehouse_id="lh")
    return pub.publish(
        ontology_id="item-1",
        ontology_name="X",
        entity_types={"Server": "server_t"},
        relationships={},
        **kwargs,
    )


def test_provenance_is_explicit() -> None:
    text = json.dumps(FIXTURE["_provenance"])
    assert "SYNTHETIC" in text and "NOT available" in text and "unpassed" in text


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("legacy_json", "legacy-json"),
        ("ontology_tmdl", "ontology-tmdl"),
        ("mixed", "mixed"),
        ("unknown", "unknown"),
    ],
)
def test_classification(name: str, expected: str) -> None:
    assert classify_definition(_fx(name)) == expected
    assert classify_definition({"parts": []}) == "empty"


@pytest.mark.parametrize("name", ["ontology_tmdl", "mixed", "unknown"])
def test_legacy_publisher_denies_tmdl_before_update(name: str) -> None:
    spy = _Spy(_fx(name))
    with pytest.raises(DefinitionFormatMismatch):
        _publish(spy)
    assert spy.updates == []


def test_legacy_publisher_denies_wrong_target_before_update() -> None:
    spy = _Spy(_fx("legacy_json"))
    with pytest.raises(DefinitionFormatMismatch) as err:
        _publish(spy, expected_item_id="other-item")
    assert err.value.detected == "wrong-target"
    assert spy.updates == []


def test_legacy_publisher_still_updates_known_legacy_target() -> None:
    spy = _Spy(_fx("legacy_json"))
    result = _publish(spy, expected_item_id="item-1")
    assert result["action"] == "updated" and len(spy.updates) == 1


def test_oversized_or_unsafe_parts_fail_closed() -> None:
    bad = {"parts": [{"path": "../x.json", "payload": "e30=", "payloadType": "InlineBase64"}]}
    with pytest.raises(DefinitionBoundsError):
        decode_parts(bad)
    huge = base64.b64encode(b"a" * (5 * 1024 * 1024 + 1)).decode()
    with pytest.raises(DefinitionBoundsError):
        decode_parts({"parts": [{"path": "a.json", "payload": huge, "payloadType": "InlineBase64"}]})
    spy = _Spy(bad)
    with pytest.raises(DefinitionFormatMismatch):
        _publish(spy)
    assert spy.updates == []


def test_definition_roundtrip_preserves_unknown_parts_and_stable_ids() -> None:
    legacy = _fx("legacy_json")
    assert compare_definitions(legacy, deepcopy(legacy)).ok
    assert len(stable_ids(legacy)) > 10
    tmdl = _fx("ontology_tmdl")
    paths = " ".join(decode_parts(tmdl))
    for needle in ("entities/", "entityRelationships/", "relationships.tmdl", "rules/",
                   "namespaces", "metrics/", "bindings/", "ext/vendor"):
        assert needle in paths  # ontology relationships distinct from tabular ones
    result = compare_definitions(tmdl, deepcopy(tmdl))
    assert result.ok and result.semantically_equal
    assert len(result.byte_identical_parts) == len(tmdl["parts"])
    assert len(stable_ids(tmdl)) == 8


def test_default_elision_equal_but_not_byte_equal() -> None:
    base, other = _fx("ontology_tmdl"), _fx("ontology_tmdl_default_elided")
    result = compare_definitions(base, other)
    assert result.ok and result.semantically_equal
    assert definition_fingerprint(base) != definition_fingerprint(other)
    assert "definition/entities/Server.tmdl" not in result.byte_identical_parts


def test_fail_closed_on_drop_id_binding_and_unmodeled_edit() -> None:
    base = _fx("legacy_json")
    dropped = deepcopy(base)
    dropped["parts"].pop()
    assert any(v.startswith("dropped_part") for v in compare_definitions(base, dropped).violations)

    def edit(path_sub: str, mutate) -> dict:
        cand = deepcopy(base)
        for p in cand["parts"]:
            if path_sub in p["path"]:
                body = json.loads(base64.b64decode(p["payload"]))
                mutate(body)
                p["payload"] = base64.b64encode(json.dumps(body).encode()).decode()
                break
        return cand

    changed_id = edit("EntityTypes/", lambda b: b.update(id="999") if "id" in b else None)
    # first EntityTypes part is an entity definition whose id changed
    res = compare_definitions(base, changed_id)
    assert not res.ok and any(v.startswith("changed_stable_id") for v in res.violations)

    binding = edit("DataBindings/", lambda b: b["dataBindingConfiguration"]["sourceTableProperties"].update(sourceTableName="evil"))
    assert any(v.startswith("unexpected_binding_change") for v in compare_definitions(base, binding).violations)

    semantic = edit("RelationshipTypes/", lambda b: b.update(name="renamed"))
    assert any(v.startswith("unmodeled_semantic_edit") for v in compare_definitions(base, semantic).violations)

    extra = deepcopy(base)
    extra["parts"].append(deepcopy(_fx("unknown")["parts"][0]))
    assert any(v.startswith("unexpected_part") for v in compare_definitions(base, extra).violations)


def test_materialization_plan_preserves_untouched_parts_and_never_executes() -> None:
    base = _fx("legacy_json")
    binding_path = next(
        p["path"]
        for p in base["parts"]
        if "/DataBindings/" in p["path"]
        and b"server_t" in base64.b64decode(p["payload"])
    )
    plan = plan_operation(
        base,
        {"op": "binding_change", "binding_path": binding_path, "before": "server_t", "after": "server_v2"},
    )
    assert plan.status == "approval_required"
    assert plan.replaced_paths == (binding_path,)
    assert len(plan.retained_paths) == len(base["parts"]) - 1
    assert plan.restore_definition == base
    assert definition_fingerprint(plan.restore_definition) == plan.base_fingerprint
    assert plan.requires_exclusive_writer and plan.requires_pre_write_base_recheck
    assert plan.requires_post_readback_comparison
    assert not plan.native_cas_claimed and not plan.migration_approved and not plan.executed
    assert plan.format_migration_requires_separate_approval
    assert compare_definitions(base, plan.candidate, allowed_changed_paths=[binding_path]).ok


@pytest.mark.parametrize(
    "operation",
    [
        {"op": "description_change"},
        {"op": "declare_entity"},
        {"op": "binding_change", "binding_path": "nope.json", "before": "a", "after": "b"},
    ],
)
def test_unmodeled_operations_deny_rather_than_replace(operation: dict) -> None:
    assert plan_operation(_fx("legacy_json"), operation).status == "denied"
    assert plan_operation(_fx("ontology_tmdl"), {"op": "binding_change", "binding_path": "x", "before": "a", "after": "b"}).status == "denied"
