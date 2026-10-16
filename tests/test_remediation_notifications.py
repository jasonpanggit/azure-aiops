"""Persisted outcome notifications must not trigger execution or source acquisition."""

import json
from unittest.mock import Mock

import pytest
from pydantic import ValidationError
from test_situation_triage import HEADERS, triage_client

from intelligence.remediation.execution_store import RemediationExecutionStore
from operations.remediation_notifications import verification_notifications

ATTRIBUTES = {
    "subscription": "sub-a", "business_service": "payments", "application": "api",
    "environment": "prod", "subscription_connection": "conn-a", "owner": "finance",
    "support_team": "sre", "region": "eastus", "criticality": "high",
}


def record(**updates):
    return {
        "execution_id": "RME-TEST", "plan_id": "retired-plan", "revision": 1,
        "status": "succeeded", "updated_at": "2026-10-17T02:00:00+02:00",
        "execution_snapshot": {"target_id": "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm"},
        "evidence_reconciliation": {"status": ""}, "scope_attributes": ATTRIBUTES,
        **updates,
    }


@pytest.mark.parametrize("status,reconciliation,failure,kind", [
    ("succeeded", "reconciled_clean", "", "complete"),
    ("succeeded", "reconciled_incomplete", "", "attention"),
    ("succeeded", "unreconciled", "", "attention"),
    ("succeeded", "unreconciled_timed_out", "", "attention"),
    ("succeeded", "unreconciled_manual_resolution", "", "attention"),
    ("succeeded", "", "", "attention"), ("succeeded", "provider-custom", "", "attention"),
    ("failed", "reconciled_clean", "", "attention"),
    ("cancelled", "", "", "cancelled"),
    ("running", "", "submission_ambiguous", "attention"),
])
def test_latest_outcomes_never_conflate_provider_success_and_evidence(status, reconciliation, failure, kind):
    [notification] = verification_notifications([record(
        status=status, evidence_reconciliation={"status": reconciliation}, failure_class=failure,
        message="private provider message", provider_job_id="private URL", failure_details="private details",
    )])
    assert notification["kind"] == kind and notification["authority"] == "none"
    assert notification["recorded_at"] == "2026-10-17T00:00:00+00:00"
    assert "private" not in json.dumps(notification)
    assert notification["execution_status"] == status
    expected = "unknown" if reconciliation == "provider-custom" else reconciliation or "unreported"
    assert notification["reconciliation_status"] == expected


@pytest.mark.parametrize("status", ["queued", "running", "retrying"])
def test_in_progress_is_not_fabricated_completion_or_error(status):
    assert verification_notifications([record(status=status)]) == []


@pytest.mark.parametrize("updates", [
    {"revision": True}, {"revision": -1}, {"execution_id": ""}, {"plan_id": ""},
    {"status": "custom-success"}, {"updated_at": "2026-01-01"}, {"updated_at": "invalid"},
    {"updated_at": "0001-01-01T00:00:00+01:00"}, {"evidence_reconciliation": []},
    {"execution_snapshot": {"target_id": 123}},
])
def test_corrupt_records_do_not_turn_into_clean_notifications(updates):
    with pytest.raises((ValidationError, ValueError)):
        verification_notifications([record(**updates)])


def test_stable_versioned_identity_missing_time_and_deterministic_order():
    first = record(execution_id="a")
    second = record(execution_id="b", updated_at="")
    rows = verification_notifications([second, first])
    assert [row["execution_id"] for row in rows] == ["a", "b"]
    assert rows[1]["recorded_at"] is None
    assert verification_notifications([first])[0]["notification_id"] == rows[0]["notification_id"]
    assert verification_notifications([{**first, "revision": 2}])[0]["notification_id"] != rows[0]["notification_id"]
    with pytest.raises(ValueError, match="unique"):
        verification_notifications([first, first])


def http(tmp_path, records=None):
    client, _ = triage_client(tmp_path)
    context = client.app.state.context
    context.execution_record_reader = Mock(return_value=records or [])
    unavailable = Mock(side_effect=AssertionError("An inbox must not acquire plans or providers"))
    context.execution_provider = unavailable
    context.remediation_provider = unavailable
    context.patching_provider = unavailable
    return client, context, unavailable


def test_exact_scope_and_kind_filter_apply_before_pagination(tmp_path):
    rows = [record(execution_id=f"RME-{index:03}", status="failed" if index % 2 else "cancelled") for index in range(60)]
    client, context, providers = http(tmp_path, rows + [record(execution_id="private", scope_attributes={"subscription": "sub-b"})])
    response = client.get("/api/v1/remediation/verification-inbox?kind=attention&offset=5&limit=5", headers=HEADERS)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["pagination"] == {"offset": 5, "limit": 5, "total": 30, "next_offset": 10}
    assert [item["execution_id"] for item in body["data"]["notifications"]] == [f"RME-{i:03}" for i in [11, 13, 15, 17, 19]]
    assert body["data"]["authorized_execution_count"] == 60
    assert body["data"]["latest_outcome_count"] == 60
    assert "private" not in response.text
    context.execution_record_reader.assert_called_once_with()
    providers.assert_not_called()
    bounded = client.get("/api/v1/remediation/verification-inbox?limit=100", headers=HEADERS).json()
    assert bounded["pagination"]["limit"] == 50
    assert len(bounded["data"]["notifications"]) == 50
    assert bounded["pagination"]["next_offset"] == 50


@pytest.mark.parametrize("dimension", list(ATTRIBUTES))
def test_every_requested_dimension_excludes_mismatched_and_missing_metadata(tmp_path, dimension):
    rows = [
        record(execution_id="allowed"),
        record(execution_id="wrong", scope_attributes={**ATTRIBUTES, dimension: "foreign"}),
        record(execution_id="missing", scope_attributes={key: value for key, value in ATTRIBUTES.items() if key != dimension}),
    ]
    client, _, providers = http(tmp_path, rows)
    response = client.get("/api/v1/remediation/verification-inbox", headers=HEADERS, params={dimension: ATTRIBUTES[dimension]})
    assert response.status_code == 200, response.text
    assert [item["execution_id"] for item in response.json()["data"]["notifications"]] == ["allowed"]
    providers.assert_not_called()


def test_foreign_corruption_never_leaks_and_legacy_scope_uses_only_snapshot_subscription(tmp_path):
    foreign = record(scope_attributes={"subscription": "sub-b"}, revision=False)
    own = record(execution_id="legacy", scope_attributes={})
    client, _, _ = http(tmp_path, [foreign, own])
    assert client.get("/api/v1/remediation/verification-inbox", headers=HEADERS).json()["data"]["authorized_execution_count"] == 1
    assert client.get("/api/v1/remediation/verification-inbox?region=eastus", headers=HEADERS).json()["data"]["authorized_execution_count"] == 0


@pytest.mark.parametrize("failure", ["missing", "storage", "corrupt"])
def test_unavailable_or_invalid_read_never_returns_empty_success(tmp_path, failure):
    client, context, _ = http(tmp_path, [record()])
    if failure == "missing":
        context.execution_record_reader = None
    elif failure == "storage":
        context.execution_record_reader = Mock(side_effect=OSError("private storage detail"))
    else:
        context.execution_record_reader = lambda: [record(revision=True)]
    response = client.get("/api/v1/remediation/verification-inbox", headers=HEADERS)
    assert response.status_code == 503
    assert "private storage detail" not in response.text


def test_real_store_recovery_does_not_advance_or_need_current_plan(tmp_path):
    path = tmp_path / "executions.json"
    store = RemediationExecutionStore(path)
    created, _ = store.create_or_get(
        "retired-plan", requested_by="operator", approved_by="approver",
        execution_snapshot={"target_id": "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm"},
        scope_attributes=ATTRIBUTES,
    )
    store.update(created["execution_id"], status="succeeded", evidence_reconciliation={"status": "reconciled_clean"})
    before = path.read_bytes()
    client, context, providers = http(tmp_path)
    context.execution_record_reader = RemediationExecutionStore(path).list_all
    response = client.get("/api/v1/remediation/verification-inbox", headers=HEADERS)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["notifications"][0]["kind"] == "complete"
    assert path.read_bytes() == before
    providers.assert_not_called()
    assert client.get("/api/v1/remediation/verification-inbox?kind=not-real", headers=HEADERS).status_code == 400
    assert client.get("/api/v1/remediation/verification-inbox").status_code == 401
