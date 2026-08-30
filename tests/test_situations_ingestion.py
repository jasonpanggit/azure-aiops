import json
from pathlib import Path

from onboarding.graph_normalize import normalize_evidence_payloads


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


def test_freshness_uses_persisted_timestamp_age_bands_and_explicit_values() -> None:
    def freshness(row: dict) -> str:
        evidence, _ = normalize_evidence_payloads(
            {"arg": [row]},
            run_id="run",
            ingested_at="2026-08-25T02:00:00Z",
        )
        return evidence[0]["freshness"]

    assert freshness({"id": "fresh", "observed_at": "2026-08-25T01:00:00Z"}) == "fresh"
    assert freshness({"id": "aging", "observed_at": "2026-08-24T02:00:01Z"}) == "aging"
    assert freshness({"id": "stale", "observed_at": "2026-08-24T01:59:59Z"}) == "stale"
    assert freshness({"id": "future", "observed_at": "2026-08-25T03:00:00Z"}) == "fresh"
    assert freshness({"id": "invalid", "observed_at": "not-a-timestamp"}) == "unknown"
    assert freshness({"id": "explicit", "observed_at": "2026-08-25T00:00:00Z", "freshness": "aging"}) == "aging"
