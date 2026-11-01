"""Verify actual JSON rows, not just a declared Arrow-schema fingerprint."""

import hashlib
import json

import pytest

from ontology_discovery.immutable_attempt import AttemptReference, _digest, _json
from ontology_discovery.publisher import PublicationSafetyError
from tests.test_immutable_attempt_protocol import fixture, stage

INVALID_ROWS = [
    {"confidence": "not-a-number"},
    {"confidence": []},
    {"confidence": True},
    {"undeclared_product_field": "not in registry schema"},
]


@pytest.mark.parametrize("row", INVALID_ROWS)
def test_invalid_product_schema_rejected_before_boundary_mutation(tmp_path, monkeypatch, row):
    broker, core, control, candidate = fixture(tmp_path)
    calls = []

    def forbidden(*_args, **_kwargs):
        calls.append("begin")
        pytest.fail("Malformed rows reached namespace allocation")

    monkeypatch.setattr(broker, "begin", forbidden)
    with pytest.raises(PublicationSafetyError, match="product_schema"):
        core.stage(
            control.session, attempt_id="invalid-row", candidate=candidate,
            products={"ontology_relationships": [row]},
        )
    assert calls == []


def test_late_product_schema_failure_rejects_complete_set_before_begin(tmp_path, monkeypatch):
    broker, core, control, candidate = fixture(tmp_path)
    calls = []

    def forbidden(*_args, **_kwargs):
        calls.append("begin")
        pytest.fail("Malformed complete product set reached namespace allocation")

    monkeypatch.setattr(broker, "begin", forbidden)
    with pytest.raises(PublicationSafetyError, match="product_schema"):
        core.stage(
            control.session, attempt_id="invalid-late-product", candidate=candidate,
            products={
                "ontology_entities": [],
                "ontology_relationships": [{"confidence": "not-a-number"}],
            },
        )
    assert calls == []


@pytest.mark.parametrize("row", INVALID_ROWS)
def test_reader_rejects_malformed_rows_even_with_coherent_hashes(tmp_path, row):
    broker, core, control, candidate = fixture(tmp_path)
    reference = stage(core, control, candidate)
    objects = broker._BrokerFixture__objects
    table = "ontology_relationships"
    body = _json({"rows": [row]})
    objects[(reference.attempt_id, table)] = body
    catalog = json.loads(objects[(reference.attempt_id, "catalog")])
    entry = catalog["products"][table]
    entry["rows"] = 1
    entry["content_digest"] = hashlib.sha256(body.encode()).hexdigest()
    entry["artifact"] = broker._object_reference(reference.attempt_id, table, body).as_dict()
    objects[(reference.attempt_id, "catalog")] = _json(catalog)
    damaged = AttemptReference(
        reference.attempt_id, reference.generation_id, _digest(catalog),
    )
    with pytest.raises(PublicationSafetyError, match="product_schema"):
        core.read_table(damaged, table)


@pytest.mark.parametrize("confidence", [None, 0, 1, 0.75])
def test_schema_validation_preserves_supported_sparse_numeric_rows(tmp_path, confidence):
    _broker, core, control, candidate = fixture(tmp_path)
    row = {"confidence": confidence}
    reference = core.stage(
        control.session, attempt_id="valid-sparse-numeric", candidate=candidate,
        products={"ontology_relationships": [row]},
    )
    actual = core.read_table(reference, "ontology_relationships")
    assert actual == [row]
    assert type(actual[0]["confidence"]) is type(confidence)


@pytest.mark.parametrize(
    "table,row",
    [
        ("ontology_entities", {"resource_id": 12}),
        ("ontology_entities", {"resource_id": "\ud800"}),
        ("ontology_health", {"entity_count": 1.5}),
        ("ontology_health", {"entity_count": True}),
        ("ontology_health", {"entity_count": 2**64}),
        ("ontology_quality_report", {"passed": 1}),
    ],
)
def test_other_primitive_coercions_and_overflow_rejected(tmp_path, table, row):
    _broker, core, control, candidate = fixture(tmp_path)
    with pytest.raises(PublicationSafetyError, match="product_schema"):
        core.stage(
            control.session, attempt_id="coercion", candidate=candidate,
            products={table: [row]},
        )
