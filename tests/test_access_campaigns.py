"""Frozen advisory campaigns, exact-scope authorization and provider independence."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest
from test_governance import ADMIN_TOKEN, READER_TOKEN, _client, _headers, _snapshot

from api.auth import StaticTokenAuthenticator
from api.rbac import Grant, Principal
from api.scope import Scope
from intelligence.governance import campaigns as module
from intelligence.governance.campaigns import (
    MAX_COLLECTION_BYTES,
    MAX_SOURCE_BYTES,
    AccessCampaignStore,
    CampaignCreate,
    CampaignDecision,
    CampaignRemove,
    CampaignTransition,
)
from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore

ACTOR = "reader@example.com"
SCOPE = {"subscription": ["sub-a"]}


def creation(revision=0, **changes):
    return CampaignCreate(
        **{"title": "Quarterly observed access", "audience": "auditor",
           "reviewer_subject": ACTOR, "due_at": (datetime.now(UTC) + timedelta(days=3)).isoformat(),
           "expected_revision": revision, **changes},
    )


def document(scope=None, count=2):
    selected = SCOPE if scope is None else scope
    return {
        "data": {
            "audience": "auditor",
            "principals": [{
                "principal_id": f"principal-{i}", "principal_type": "User", "roles": ["Contributor"],
                "assignment_count": 1, "privileged": True, "stale": False,
                "widest_scope": "/subscriptions/sub-a", "widest_scope_breadth": "subscription",
                "last_changed": "", "blast_radius": {"subscriptions": 1},
            } for i in range(count)],
            "provenance": {"scope": selected, "observed_at": "",
                           "generated_at": datetime.now(UTC).isoformat()},
        },
        "evidence": [{"confidence": "unknown", "timestamp": ""}],
        "warnings": ["Observed assignments are not full effective access"],
        "scope": selected,
    }


def store(path):
    return AccessCampaignStore(OneLakeDocumentStore(path))


def decision(campaign_id, revision, principal_id="principal-0"):
    return CampaignDecision(
        campaign_id=campaign_id, expected_revision=revision, principal_id=principal_id,
        recommendation="investigate", reason="Confirm this captured assignment with its owner",
    )


def test_source_frozen_decisions_attributed_and_terminal_copy_removal(tmp_path):
    first = store(tmp_path)
    pack = document()
    pack["data"]["credentials"] = {"client_secret": "private-value"}
    row = first.create(SCOPE, creation(), "admin", pack)["campaigns"][0]
    campaign_id = row["campaign_id"]
    assert row["item_count"] == 2 and row["decided_count"] == 0 and not row["overdue"]
    detail = store(tmp_path).detail(SCOPE, campaign_id)
    assert "private-value" not in detail["source_content"]
    assert hashlib.sha256(detail["source_content"].encode()).hexdigest() == row["source_sha256"]
    assert row["observed_at"] == ""
    assert "source_content" not in row
    with pytest.raises(PermissionError):
        first.decide(SCOPE, decision(campaign_id, 1), "admin")
    with pytest.raises(ValueError, match="not in"):
        first.decide(SCOPE, decision(campaign_id, 1, "foreign"), ACTOR)
    first.decide(SCOPE, decision(campaign_id, 1), ACTOR)
    with pytest.raises(ValueError, match="overwritten"):
        first.decide(SCOPE, decision(campaign_id, 2), ACTOR)
    change = CampaignTransition(campaign_id=campaign_id, expected_revision=2, reason="Reviewed all principals")
    with pytest.raises(ValueError, match="every"):
        first.transition(SCOPE, change, "admin", "complete")
    with pytest.raises(ValueError, match="before removing"):
        first.remove(SCOPE, CampaignRemove(campaign_id=campaign_id, expected_revision=2))
    first.decide(SCOPE, decision(campaign_id, 2, "principal-1"), ACTOR)
    result = first.transition(SCOPE, change.model_copy(update={"expected_revision": 3}), "admin", "complete")
    assert result["campaigns"][0]["status"] == "completed"
    assert result["campaigns"][0]["closure"]["actor"] == "admin"
    assert first.detail(SCOPE, campaign_id)["decisions"][0]["actor"] == ACTOR
    with pytest.raises(ValueError, match="open"):
        first.decide(SCOPE, decision(campaign_id, 4), ACTOR)
    assert first.remove(SCOPE, CampaignRemove(campaign_id=campaign_id, expected_revision=4))["campaigns"] == []
    with pytest.raises(LookupError):
        first.detail(SCOPE, campaign_id)


def test_overdue_is_current_clock_not_a_reminder_or_source_refresh(tmp_path, monkeypatch):
    first = store(tmp_path)
    row = first.create(SCOPE, creation(), "admin", document())["campaigns"][0]
    future = datetime.now(UTC) + timedelta(days=4)

    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return future

    monkeypatch.setattr(module, "datetime", Later)
    later = first.read(SCOPE)["campaigns"][0]
    assert later["overdue"]
    assert later["observed_at"] == row["observed_at"]
    assert later["source_sha256"] == row["source_sha256"]


@pytest.mark.parametrize("seed", [False, True])
def test_initial_and_existing_collection_cas_races(tmp_path, seed):
    first = store(tmp_path)
    if seed:
        first.create(SCOPE, creation(), "admin", document())
    barrier = Barrier(2)

    class Racing(OneLakeDocumentStore):
        def read_snapshot(self, name):
            result = super().read_snapshot(name)
            barrier.wait(timeout=10)
            return result

    def writer(_):
        try:
            AccessCampaignStore(Racing(tmp_path)).create(SCOPE, creation(int(seed)), "admin", document())
            return "saved"
        except DocumentConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(writer, [1, 2])) == ["conflict", "saved"]
    assert first.read(SCOPE)["revision"] == int(seed) + 1


@pytest.mark.parametrize("change", [
    lambda value: value.update(scope={}),
    lambda value: value.update(revision=False),
    lambda value: value["campaigns"][0].update(source_content="{}"),
    lambda value: value["campaigns"][0].update(source_sha256="f" * 64),
    lambda value: value["campaigns"][0].update(status="completed"),
    lambda value: value["campaigns"][0].update(created_at="not-a-time"),
    lambda value: value["campaigns"].append(value["campaigns"][0]),
])
def test_corrupt_state_never_resets_or_gets_overwritten(tmp_path, change):
    first = store(tmp_path)
    first.create(SCOPE, creation(), "admin", document())
    path = tmp_path / first._name(SCOPE)
    payload = json.loads(path.read_text())
    change(payload); path.write_text(json.dumps(payload))
    before = path.read_bytes()
    with pytest.raises(RuntimeError):
        first.read(SCOPE)
    with pytest.raises(RuntimeError):
        first.create(SCOPE, creation(1), "admin", document())
    assert path.read_bytes() == before


def test_exact_source_bound_and_capacity_never_truncate_or_evict(tmp_path):
    first = store(tmp_path)
    pack = document()
    pack["data"]["padding"] = ""
    size = len((json.dumps(pack, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode())
    pack["data"]["padding"] = "x" * (MAX_SOURCE_BYTES - size)
    result = first.create(SCOPE, creation(), "admin", pack)
    assert result["campaigns"][0]["source_size_bytes"] == MAX_SOURCE_BYTES
    pack["data"]["padding"] += "x"
    with pytest.raises(ValueError, match="512 KiB"):
        first.create(SCOPE, creation(1), "admin", pack)
    for revision in range(1, 10):
        first.create(SCOPE, creation(revision), "admin", document())
    with pytest.raises(ValueError, match="full"):
        first.create(SCOPE, creation(10), "admin", document())
    assert len(first.read(SCOPE)["campaigns"]) == 10


def test_complete_serialized_collection_bound_includes_string_escaping(tmp_path):
    first = store(tmp_path)
    pack = document()
    pack["data"]["padding"] = '"' * 250_000
    for revision in range(6):
        first.create(SCOPE, creation(revision), "admin", pack)
    path = tmp_path / first._name(SCOPE)
    before = path.read_bytes()
    assert len(before) <= MAX_COLLECTION_BYTES
    with pytest.raises(ValueError, match="6 MiB"):
        first.create(SCOPE, creation(6), "admin", pack)
    assert path.read_bytes() == before


@pytest.mark.parametrize("count", [0, 101])
def test_empty_or_oversized_principal_review_is_not_inferred_or_truncated(tmp_path, count):
    with pytest.raises(ValueError, match="1 to 100"):
        store(tmp_path).create(SCOPE, creation(), "admin", document(count=count))
    assert store(tmp_path).read(SCOPE)["revision"] == 0


def test_api_assigned_reader_recovers_and_reviews_without_current_providers(tmp_path):
    client = _client(tmp_path, snapshot=_snapshot())
    context = client.app.state.context
    context.access_campaign_store = store(tmp_path)
    path = "/api/v1/governance/access-campaigns"
    body = creation().model_dump()
    assert client.post(path, headers=_headers(), params={"subscription": "sub-a"}, json=body).status_code == 403
    response = client.post(path, headers=_headers(ADMIN_TOKEN), params={"subscription": "sub-a"}, json=body)
    assert response.status_code == 201, response.text
    campaign_id = response.json()["data"]["campaigns"][0]["campaign_id"]

    def unavailable():
        raise AssertionError("Historical campaign recovery must not acquire live identity sources")

    context.governance_provider = unavailable
    detail = client.get(path + "/" + campaign_id, headers=_headers(), params={"subscription": "sub-a"})
    assert detail.status_code == 200, detail.text
    assert not detail.json()["data"]["can_manage"]
    revision = detail.json()["data"]["revision"]
    for item in detail.json()["data"]["items"]:
        payload = decision(campaign_id, revision, item["principal_id"]).model_dump()
        denied = client.post(path + "/decisions", headers=_headers(ADMIN_TOKEN),
                             params={"subscription": "sub-a"}, json=payload)
        assert denied.status_code == 403
        response = client.post(path + "/decisions", headers=_headers(),
                               params={"subscription": "sub-a"}, json=payload)
        assert response.status_code == 200, response.text
        revision = response.json()["data"]["revision"]
    response = client.post(path + "/complete", headers=_headers(ADMIN_TOKEN), params={"subscription": "sub-a"},
                           json={"campaign_id": campaign_id, "expected_revision": revision, "reason": "Recommendations recorded, not RBAC approval"})
    assert response.status_code == 200, response.text
    assert response.json()["data"]["campaigns"][0]["status"] == "completed"
    assert client.get(path + "/" + campaign_id, headers=_headers(), params={"subscription": "sub-b"}).status_code == 404
    stale = client.post(path, headers=_headers(ADMIN_TOKEN), params={"subscription": "sub-a"}, json=body)
    assert stale.status_code == 409


def test_mixed_global_reader_and_scoped_admin_cannot_manage_global_workspaces(tmp_path):
    client = _client(tmp_path, snapshot=_snapshot())
    context = client.app.state.context
    context.access_campaign_store = store(tmp_path)
    context.authenticator = StaticTokenAuthenticator({
        ADMIN_TOKEN: Principal(subject="mixed", grants=(Grant("reader"), Grant("admin", Scope({"subscription": {"sub-a"}})))),
    })
    path = "/api/v1/governance/access-campaigns"
    assert client.get(path, headers=_headers(ADMIN_TOKEN)).json()["data"]["can_manage"] is False
    assert client.post(path, headers=_headers(ADMIN_TOKEN), json=creation().model_dump()).status_code == 403
    assert client.get(path, headers=_headers(ADMIN_TOKEN), params={"subscription": "sub-a"}).json()["data"]["can_manage"] is True
    assert client.post(path, headers=_headers(ADMIN_TOKEN), params={"subscription": "sub-a"},
                       json=creation().model_dump()).status_code == 201


def test_api_exact_nine_dimensions_and_current_grant_revocation(tmp_path):
    client = _client(tmp_path, snapshot=_snapshot())
    first = store(tmp_path)
    client.app.state.context.access_campaign_store = first
    selected = {
        "subscription": ["sub-a"], "business_service": ["payments"], "application": ["checkout"],
        "environment": ["production"], "subscription_connection": ["conn-a"], "owner": ["platform"],
        "support_team": ["sre"], "region": ["eastus"], "criticality": ["high"],
    }
    row = first.create(selected, creation(), "admin", document(selected))["campaigns"][0]
    path = "/api/v1/governance/access-campaigns/" + row["campaign_id"]
    assert client.get(path, headers=_headers(), params=selected).status_code == 200
    for dimension in selected:
        assert client.get(path, headers=_headers(), params={**selected, dimension: ["different"]}).status_code == 404
    client.app.state.context.authenticator = StaticTokenAuthenticator({
        READER_TOKEN: Principal(subject=ACTOR, grants=(Grant("reader", Scope({"subscription": {"sub-b"}})),)),
    })
    assert client.get(path, headers=_headers(), params=selected).status_code == 403


def test_api_storage_unavailable_and_corrupt_never_return_empty_success(tmp_path):
    client = _client(tmp_path, snapshot=_snapshot())
    path = "/api/v1/governance/access-campaigns"
    assert client.get(path, headers=_headers()).status_code == 503
    first = store(tmp_path)
    client.app.state.context.access_campaign_store = first
    first.create({}, creation(), "admin", document({}))
    file = tmp_path / first._name({})
    file.write_text("{private corrupt JSON")
    response = client.get(path, headers=_headers())
    assert response.status_code == 503
    assert "private" not in response.text
    assert file.read_text() == "{private corrupt JSON"


@pytest.mark.parametrize("audience,field", [
    ("service_owner", "items"), ("security", "privileged_principals"), ("auditor", "principals"),
])
def test_all_audience_shapes_and_full_hundred_principal_cancellation(tmp_path, audience, field):
    first = store(tmp_path)
    pack = document(count=100)
    items = pack["data"].pop("principals")
    pack["data"].update(audience=audience, **{field: items})
    row = first.create(SCOPE, creation(audience=audience), "admin", pack)["campaigns"][0]
    assert row["item_count"] == 100
    result = first.transition(SCOPE, CampaignTransition(
        campaign_id=row["campaign_id"], expected_revision=1, reason="Repeat with a different declared reviewer",
    ), "admin", "cancel")
    assert result["campaigns"][0]["status"] == "cancelled"
    assert first.detail(SCOPE, row["campaign_id"])["items"] == items


@pytest.mark.parametrize("extra", [
    {"actor": "forged"}, {"document": {}}, {"expected_revision": True},
    {"expected_revision": 9_007_199_254_740_991}, {"due_at": "2026-11-01"},
    {"reviewer_subject": " "}, {"audience": "unknown"},
])
def test_api_rejects_untrusted_documents_attribution_and_invalid_requests(tmp_path, extra):
    client = _client(tmp_path, snapshot=_snapshot())
    client.app.state.context.access_campaign_store = store(tmp_path)
    response = client.post("/api/v1/governance/access-campaigns", headers=_headers(ADMIN_TOKEN),
                           json={**creation().model_dump(), **extra})
    assert response.status_code == 400, response.text


def test_expired_deadline_rejected_before_current_source_and_bad_source_is_safe_unavailable(tmp_path, monkeypatch):
    from api.routers import governance

    client = _client(tmp_path, snapshot=_snapshot())
    first = store(tmp_path)
    client.app.state.context.access_campaign_store = first

    def bad_source(*args, **kwargs):
        raise KeyError("private-current-source")

    monkeypatch.setattr(governance, "access_review", bad_source)
    path = "/api/v1/governance/access-campaigns"
    body = creation().model_dump()
    expired = {**body, "due_at": (datetime.now(UTC) - timedelta(days=1)).isoformat()}
    assert client.post(path, headers=_headers(ADMIN_TOKEN), json=expired).status_code == 400
    response = client.post(path, headers=_headers(ADMIN_TOKEN), json=body)
    assert response.status_code == 503
    assert "private-current-source" not in response.text
    assert first.read({})["revision"] == 0


@pytest.mark.parametrize("operation", ["read_snapshot", "create_only", "replace_if_match"])
def test_storage_failures_never_claim_success_or_erase_prior_work(tmp_path, monkeypatch, operation):
    first = store(tmp_path)
    revision = 0
    if operation == "replace_if_match":
        first.create(SCOPE, creation(), "admin", document()); revision = 1
    path = tmp_path / first._name(SCOPE)
    before = path.read_bytes() if path.exists() else None

    def fail(*args, **kwargs):
        raise OSError("private storage error")

    monkeypatch.setattr(first.documents, operation, fail)
    with pytest.raises(OSError):
        first.create(SCOPE, creation(revision), "admin", document())
    assert (path.read_bytes() if path.exists() else None) == before
