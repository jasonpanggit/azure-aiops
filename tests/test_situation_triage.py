"""Server-side triage and bounded, reauthorized evidence handoff contracts."""

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.rbac import Authorizer, Grant, Principal
from api.scope import Scope
from api.telemetry import ApiTelemetry
from onboarding.service import SubscriptionOnboardingService
from situations.store import SituationReadProvider

TOKEN = "situation-triage-reader-0123456789"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


def triage_client(tmp_path, *, restricted=True):
    now = datetime.now(UTC)
    rows = [{
        "situation_id": f"situation-{i}", "title": f"Situation {i}",
        "owner": "SRE" if i % 2 == 0 else "Platform", "lifecycle_state": "open",
        "scope": {"subscription": ["sub-a"]}, "priority": "P1",
        "started_at": (now - timedelta(hours=i + 48)).isoformat(),
        "run_id": "run-1", "linked_evidence_ids": ["allowed", "private"],
    } for i in range(40)]
    rows.extend([
        {**rows[0], "situation_id": "private-situation", "scope": {"subscription": ["sub-b"]}},
        {**rows[0], "situation_id": "unknown-start", "started_at": "invalid"},
        {**rows[0], "situation_id": "naive-start", "started_at": "2026-01-01T00:00:00"},
    ])
    provider = SituationReadProvider(None, situations=rows, evidence=[
        {"situation_id": "situation-0", "evidence_id": "allowed", "scope": {"subscription": ["sub-a"]}},
        {"situation_id": "situation-0", "evidence_id": "private", "scope": {"subscription": ["sub-b"]}},
    ])
    context = ApiContext(
        onboarding=SubscriptionOnboardingService(tmp_path / "aiops"),
        authenticator=StaticTokenAuthenticator({TOKEN: Principal(
            subject="reader@example.com",
            grants=(Grant("reader", Scope.from_mapping({"subscription": ["sub-a"]}) if restricted else Scope()),),
        )}),
        authorizer=Authorizer(), telemetry=ApiTelemetry(), situation_provider=lambda: provider,
    )
    return TestClient(create_app(context), raise_server_exceptions=False), rows


def test_filters_and_order_apply_to_authorized_dataset_before_paging(tmp_path):
    client, _ = triage_client(tmp_path)
    result = client.get("/api/v1/situations", params={
        "assigned_owner": "sre", "lifecycle_state": "open", "older_than_hours": 24,
        "sort": "oldest", "limit": 5, "offset": 5,
    }, headers=HEADERS)
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["pagination"]["total"] == 20
    assert [row["situation_id"] for row in body["data"]] == [f"situation-{i}" for i in [28, 26, 24, 22, 20]]
    assert "private-situation" not in result.text


@pytest.mark.parametrize("sort", ["newest", "oldest"])
def test_unknown_or_naive_timestamps_sort_last_and_do_not_claim_age(tmp_path, sort):
    client, _ = triage_client(tmp_path)
    body = client.get("/api/v1/situations", params={"sort": sort, "limit": 100}, headers=HEADERS).json()
    assert {row["situation_id"] for row in body["data"][-2:]} == {"unknown-start", "naive-start"}
    aged = client.get("/api/v1/situations?older_than_hours=0", headers=HEADERS).json()
    assert aged["pagination"]["total"] == 40


@pytest.mark.parametrize("query", ["older_than_hours=-1", "older_than_hours=87601", "sort=unbounded", "assigned_owner=" + "x" * 257])
def test_triage_rejects_invalid_bounds(tmp_path, query):
    client, _ = triage_client(tmp_path)
    assert client.get("/api/v1/situations?" + query, headers=HEADERS).status_code == 400


def export(client, selections):
    return client.post("/api/v1/situations/handoff", json={"selections": selections}, headers=HEADERS)


def test_handoff_pins_only_explicit_rows_and_authorized_evidence_ids(tmp_path):
    client, _ = triage_client(tmp_path)
    result = export(client, [{"situation_id": "situation-0", "run_id": "run-1"}])
    assert result.status_code == 200, result.text
    data = result.json()["data"]
    assert data["count"] == 1
    assert data["artifact"]["situations"][0]["linked_evidence_ids"] == ["allowed"]
    assert "private" not in result.text
    canonical = json.dumps(data["artifact"], sort_keys=True, separators=(",", ":")).encode()
    assert hashlib.sha256(canonical).hexdigest() == data["sha256"]
    assert data["artifact"]["scope"] == {"subscription": ["sub-a"]}
    assert data["artifact"]["situations"][0]["run_id"] == "run-1"


@pytest.mark.parametrize("situation_id", ["private-situation", "missing"])
def test_handoff_fails_atomically_for_invisible_or_missing_selection(tmp_path, situation_id):
    client, _ = triage_client(tmp_path)
    result = export(client, [
        {"situation_id": "situation-0", "run_id": "run-1"},
        {"situation_id": situation_id, "run_id": "run-1"},
    ])
    assert result.status_code == 404
    assert "artifact" not in result.text


def test_changed_evidence_cannot_be_exported_as_reviewed_version(tmp_path):
    client, _ = triage_client(tmp_path)
    assert export(client, [{"situation_id": "situation-0", "run_id": "stale-run"}]).status_code == 409


@pytest.mark.parametrize("selections", [
    [],
    [{"situation_id": "situation-0", "run_id": "run-1"}] * 2,
    [{"situation_id": f"situation-{i}", "run_id": "run-1"} for i in range(26)],
    [{"situation_id": "situation-0", "run_id": ""}],
    [{"situation_id": "situation-0", "run_id": "run-1", "execute": True}],
])
def test_handoff_rejects_unbounded_duplicate_or_execution_payloads(tmp_path, selections):
    client, _ = triage_client(tmp_path)
    assert export(client, selections).status_code == 400


def test_handoff_is_authenticated_and_retains_explicit_payload_limit(tmp_path):
    client, rows = triage_client(tmp_path)
    assert client.post("/api/v1/situations/handoff", json={"selections": []}).status_code == 401
    rows[0]["title"] = "x" * (2 * 1024 * 1024)
    result = export(client, [{"situation_id": "situation-0", "run_id": "run-1"}])
    assert result.status_code == 400
    assert "2 MiB" in result.text
