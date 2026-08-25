from situations.models import EvidenceRecord, Situation, stable_id


def test_situation_and_evidence_are_validated_and_deterministic() -> None:
    situation_id = stable_id("situation", "resource_change", "/subscriptions/a/resource")
    situation = Situation(
        situation_id=situation_id,
        resource_id=situation_id,
        title="Resource changed",
        situation_type="resource_change",
        started_at="2026-08-25T00:00:00Z",
        last_observed_at="2026-08-25T00:00:00Z",
        affected_resource_ids=["/subscriptions/a/resource"],
    )
    evidence = EvidenceRecord(
        evidence_id=stable_id("evidence", "arg_activity_log", "change-1", "fingerprint"),
        source_family="arg_activity_log",
        source_object_id="change-1",
        observed_at="2026-08-25T00:00:00Z",
        ingested_at="2026-08-25T00:01:00Z",
        fingerprint="fingerprint",
    )

    assert situation.to_dict()["resource_id"] == situation_id
    assert evidence.to_dict()["source_object_id"] == "change-1"
