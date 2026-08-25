import json
from pathlib import Path

from hermes_arg_connector.normalize import normalize_evidence_payloads


def test_representative_families_share_envelope_and_failed_status_does_not_advance_watermark() -> None:
    payloads = json.loads(Path("tests/fixtures/phase1_signal_payloads.json").read_text())
    evidence, _statuses = normalize_evidence_payloads(
        payloads,
        run_id="run-1",
        ingested_at="2026-08-25T02:00:00Z",
        requested_scope={"subscription": ["sub-a"]},
    )

    assert {item["source_family"] for item in evidence} == {
        "arg_activity_log", "monitor", "service_health", "defender", "policy", "vulnerability"
    }
    assert all({"source_object_id", "observed_at", "ingested_at", "watermark", "provenance", "quality"} <= item.keys() for item in evidence)
    failed_evidence, failed_statuses = normalize_evidence_payloads(
        {**payloads, "defender": [{"status": "unavailable", "error": "provider offline", "watermark": "never"}]},
        run_id="run-2",
        ingested_at="2026-08-25T02:00:00Z",
    )
    assert not [item for item in failed_evidence if item["source_family"] == "defender"]
    defender = next(item for item in failed_statuses if item["source_family"] == "defender")
    assert defender["watermark"] == ""
    assert defender["availability"] == "unavailable"


def test_duplicate_fingerprint_is_deduplicated_but_conflicting_assertions_are_retained() -> None:
    evidence, _ = normalize_evidence_payloads(
        {
            "arg": [
                {"id": "same", "resource_id": "/subscriptions/a/r", "assertion": "healthy"},
                {"id": "same", "resource_id": "/subscriptions/a/r", "assertion": "healthy"},
                {"id": "other", "resource_id": "/subscriptions/a/r", "assertion": "degraded"}
            ]
        },
        run_id="run",
        ingested_at="2026-08-25T02:00:00Z",
    )
    assert len(evidence) == 2
    assert {item["quality"] for item in evidence} == {"contradictory"}
