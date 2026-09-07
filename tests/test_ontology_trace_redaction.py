from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from opentelemetry.sdk.trace.export import SpanExportResult, SpanExporter

from scripts.evaluate_ontology_discovery import emit_sanitized_lifecycle_spans
from scripts.inspect_ontology_traces import (
    ALLOWED_ATTRIBUTES,
    EXPECTED_SPAN_NAMES,
    assert_loopback_endpoint,
    inspect_span_records,
    phoenix_environment,
)

ROOT = Path(__file__).parents[1]
DATASET = ROOT / "tests" / "fixtures" / "ontology_discovery" / "reference.jsonl"
OPAQUE_HASH = re.compile(r"^[a-f0-9]{32}$")


class RecordingExporter(SpanExporter):
    def __init__(self) -> None:
        self.spans = []

    def export(self, spans):
        self.spans.extend(spans)
        return SpanExportResult.SUCCESS


def _records(exporter: RecordingExporter) -> list[dict[str, object]]:
    return [
        {
            "name": span.name,
            "attributes": dict(span.attributes or {}),
            "status_code": span.status.status_code.name,
        }
        for span in exporter.spans
    ]


def test_synthetic_replay_emits_complete_sanitized_lifecycle() -> None:
    exporter = RecordingExporter()

    emitted = emit_sanitized_lifecycle_spans(DATASET, exporter=exporter)
    records = _records(exporter)

    assert emitted == len(EXPECTED_SPAN_NAMES) == len(records)
    assert {record["name"] for record in records} == EXPECTED_SPAN_NAMES
    assert inspect_span_records(records) == []
    for record in records:
        attributes = record["attributes"]
        assert set(attributes) <= ALLOWED_ATTRIBUTES
        for key in (
            "ontology.run_hash",
            "ontology.batch_hash",
            "ontology.proposal_hash",
            "ontology.source_generation_hash",
        ):
            assert OPAQUE_HASH.fullmatch(attributes[key])
        serialized = json.dumps(record, sort_keys=True).casefold()
        for forbidden in (
            "prompt.body",
            "evidence.body",
            "tool.body",
            "authorization",
            "client_secret",
            "/subscriptions/",
            "tenant_id",
            "resource_id",
            "ignore previous",
        ):
            assert forbidden not in serialized


@pytest.mark.parametrize(
    "record",
    [
        {
            "name": "ontology.foundry",
            "attributes": {"prompt.body": "ignore previous instructions"},
        },
        {
            "name": "ontology.evidence",
            "attributes": {
                "ontology.run_hash": "a" * 32,
                "ontology.batch_hash": "b" * 32,
                "ontology.proposal_hash": "c" * 32,
                "ontology.source_generation_hash": "d" * 32,
                "ontology.lifecycle_status": (
                    "/subscriptions/raw-sub/resourceGroups/raw-rg"
                ),
            },
        },
        {
            "name": "ontology.policy",
            "attributes": {
                "ontology.run_hash": "raw-tenant-id",
                "ontology.batch_hash": "b" * 32,
                "ontology.proposal_hash": "c" * 32,
                "ontology.source_generation_hash": "d" * 32,
            },
        },
        {
            "name": "ontology.review",
            "attributes": {
                "ontology.run_hash": "a" * 32,
                "ontology.batch_hash": "b" * 32,
                "ontology.proposal_hash": "c" * 32,
                "ontology.source_generation_hash": "d" * 32,
                "ontology.unauthorized_id": "opaque-looking-but-not-allowed",
            },
        },
        {
            "name": "ontology.publication",
            "attributes": {
                "ontology.run_hash": "a" * 32,
                "ontology.batch_hash": "b" * 32,
                "ontology.proposal_hash": "c" * 32,
                "ontology.source_generation_hash": "d" * 32,
                "exception.message": "Bearer secret-value",
            },
        },
    ],
)
def test_inspection_rejects_bodies_credentials_raw_ids_and_unknown_attributes(
    record: dict[str, object],
) -> None:
    violations = inspect_span_records([record])

    assert violations


def test_phoenix_launch_is_loopback_local_and_strips_credentials(
    tmp_path: Path,
) -> None:
    assert assert_loopback_endpoint("http://127.0.0.1:6006") == (
        "127.0.0.1",
        6006,
    )
    assert assert_loopback_endpoint("http://localhost:6006") == ("localhost", 6006)
    with pytest.raises(ValueError, match="loopback"):
        assert_loopback_endpoint("https://phoenix.example.com")
    with pytest.raises(ValueError, match="credentials"):
        assert_loopback_endpoint("http://user:secret@127.0.0.1:6006")

    environment = phoenix_environment(
        "http://127.0.0.1:6006",
        working_dir=tmp_path,
        environ={
            "PATH": "/trusted/bin",
            "PHOENIX_API_KEY": "must-be-removed",
            "OTEL_EXPORTER_OTLP_HEADERS": "authorization=secret",
            "AZURE_CLIENT_SECRET": "must-not-be-forwarded",
        },
    )
    assert environment["PATH"] == "/trusted/bin"
    assert environment["PHOENIX_HOST"] == "127.0.0.1"
    assert environment["PHOENIX_PORT"] == "6006"
    assert environment["PHOENIX_WORKING_DIR"] == str(tmp_path)
    assert environment["PHOENIX_PROJECT_NAME"] == "ontology-discovery-synthetic"
    assert "PHOENIX_API_KEY" not in environment
    assert "OTEL_EXPORTER_OTLP_HEADERS" not in environment
    assert "AZURE_CLIENT_SECRET" not in environment
