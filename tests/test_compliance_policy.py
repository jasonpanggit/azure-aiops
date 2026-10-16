"""Durability, approval identity, scope isolation and concurrency contracts."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.rbac import Authorizer, Grant, Principal
from api.scope import Scope
from api.telemetry import ApiTelemetry
from intelligence.governance.compliance_policy import (
    CompliancePolicyStore,
    DesignPolicy,
    ExceptionDecision,
    PolicyChange,
)
from onboarding.service import SubscriptionOnboardingService
from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore


def _store(tmp_path):
    return CompliancePolicyStore(OneLakeDocumentStore(tmp_path))


def _accept(revision=0, **overrides):
    return ExceptionDecision(**{
        "expected_revision": revision, "action": "accept", "violationId": "gap-1",
        "owner": "Platform team", "reason": "Time-bound migration",
        "expiresAt": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        **overrides,
    })


def test_policy_survives_store_recreation_and_invalidates_prior_exceptions(tmp_path):
    scope = {"subscription": ["sub-a"]}
    first = _store(tmp_path).update(scope, _accept(), "actual-approver")
    assert first["exceptions"][0]["active"]
    restored = _store(tmp_path).read(scope)
    assert restored["exceptions"][0]["approved_by"] == "actual-approver"
    assert restored["audit"][0]["actor"] == "actual-approver"
    changed = _store(tmp_path).update(scope, PolicyChange(
        expected_revision=1, policy=DesignPolicy(name="Reviewed baseline"), reason="New policy",
    ), "admin")
    assert changed["revision"] == 2
    assert not changed["exceptions"][0]["active"]
    assert len(changed["audit"]) == 2
    assert _store(tmp_path).read({"subscription": ["sub-b"]})["revision"] == 0


def test_revision_conflicts_do_not_overwrite_decisions(tmp_path):
    store = _store(tmp_path)
    store.update({}, _accept(), "admin")
    with pytest.raises(DocumentConflictError):
        store.update({}, _accept(), "other")
    assert len(store.read({})["audit"]) == 1


def test_storage_cas_rejects_a_race_after_revision_check(tmp_path, monkeypatch):
    first = _store(tmp_path)
    concurrent = _store(tmp_path)
    first.update({}, _accept(), "admin")
    replace = first.documents.replace_if_match

    def race(name, payload, *, expected_etag):
        concurrent.update({}, _accept(1, violationId="gap-other"), "other")
        return replace(name, payload, expected_etag=expected_etag)

    monkeypatch.setattr(first.documents, "replace_if_match", race)
    with pytest.raises(DocumentConflictError):
        first.update({}, _accept(1, violationId="gap-lost"), "admin")
    persisted = concurrent.read({})
    assert persisted["revision"] == 2
    assert [item["violationId"] for item in persisted["exceptions"]] == ["gap-1", "gap-other"]
    assert persisted["audit"][-1]["actor"] == "other"


def test_expiry_is_enforced_on_read_and_acceptance(tmp_path):
    store = _store(tmp_path)
    for expiry in ("2020-01-01T00:00:00Z", "2099-01-01", "not-a-date"):
        with pytest.raises(ValueError):
            store.update({}, _accept(expiresAt=expiry), "admin")
    store.update({}, _accept(), "admin")
    name = store._name({})
    snapshot = store.documents.read_snapshot(name)
    snapshot.payload["exceptions"][0]["expiresAt"] = "2020-01-01T00:00:00+00:00"
    store.documents.replace_if_match(name, snapshot.payload, expected_etag=snapshot.etag)
    assert not store.read({})["exceptions"][0]["active"]


def test_revocation_is_durable_and_audited(tmp_path):
    store = _store(tmp_path)
    store.update({}, _accept(), "admin")
    result = store.update({}, _accept(1, action="revoke", expiresAt="", reason="Migration finished"), "revoker")
    assert not result["exceptions"][0]["active"]
    assert result["audit"][-1]["actor"] == "revoker"
    assert result["audit"][-1]["action"] == "revoke"
    assert not _store(tmp_path).read({})["exceptions"][0]["active"]


def test_corrupt_storage_is_not_silently_reset(tmp_path):
    store = _store(tmp_path)
    name = tmp_path / store._name({})
    name.parent.mkdir(parents=True)
    name.write_text("not JSON")
    with pytest.raises(ValueError):
        store.read({})


def _client(tmp_path):
    a = Scope.from_mapping({"subscription": ["sub-a"]})
    principals = {
        "admin": Principal("actual-admin", grants=(Grant("admin"),)),
        "reader": Principal("reader", grants=(Grant("reader", a),)),
        "operator": Principal("operator", grants=(Grant("operator", a),)),
        "approver": Principal("approver", grants=(Grant("approver", a),)),
        "mixed": Principal("mixed", grants=(Grant("reader"), Grant("admin", a))),
    }
    context = ApiContext(
        onboarding=SubscriptionOnboardingService(tmp_path / "onboarding"),
        authenticator=StaticTokenAuthenticator({f"{key}-token-0123456789": value for key, value in principals.items()}), authorizer=Authorizer(),
        telemetry=ApiTelemetry(), compliance_policy_store=_store(tmp_path / "state"),
    )
    return TestClient(create_app(context), raise_server_exceptions=False)


def _headers(token="admin"):
    return {"Authorization": f"Bearer {token}-token-0123456789"}


def test_routes_require_writer_scope_and_record_authenticated_actor(tmp_path):
    client = _client(tmp_path)
    path = "/api/v1/compliance/design-policy/exceptions?subscription=sub-a"
    for token in ("reader", "operator", "approver"):
        assert client.post(path, headers=_headers(token), json=_accept().model_dump()).status_code == 403
    response = client.post(path, headers=_headers(), json=_accept().model_dump())
    assert response.status_code == 200, response.text
    assert response.json()["data"]["exceptions"][0]["approved_by"] == "actual-admin"
    assert client.post(path, headers=_headers(), json=_accept().model_dump()).status_code == 409
    other = client.get("/api/v1/compliance/design-policy?subscription=sub-b", headers=_headers())
    assert other.json()["data"]["exceptions"] == []
    assert client.get("/api/v1/compliance/design-policy?subscription=sub-b", headers=_headers("reader")).status_code == 403
    # A broad read grant must never widen a scoped write grant.
    assert client.post(
        "/api/v1/compliance/design-policy/exceptions",
        headers=_headers("mixed"), json=_accept().model_dump(),
    ).status_code == 403


def test_routes_validate_shape_ports_and_no_spoofed_approver(tmp_path):
    client = _client(tmp_path)
    path = "/api/v1/compliance/design-policy"
    body = {"expected_revision": 0, "policy": DesignPolicy().model_dump(), "reason": "Reviewed"}
    assert client.put(path, headers=_headers(), json=body).status_code == 200
    body["expected_revision"] = 1
    body["policy"]["allowedPorts"] = "0, 99999"
    assert client.put(path, headers=_headers(), json=body).status_code == 400
    payload = {**_accept(1).model_dump(), "approved_by": "forged-admin"}
    assert client.post(f"{path}/exceptions", headers=_headers(), json=payload).status_code == 400


def test_policy_audit_records_exact_before_after_and_only_active_invalidations(tmp_path):
    store = _store(tmp_path)
    accepted = store.update({}, _accept(), "approver")
    exception_id = accepted["exceptions"][0]["exception_id"]
    changed = store.update({}, PolicyChange(
        expected_revision=1, policy=DesignPolicy(name="Metadata-only revision"), reason="Clearer pack name",
    ), "policy-admin")
    audit = changed["audit"][-1]
    assert audit["actor"] == "policy-admin"
    assert audit["previous_policy_revision"] == 0
    assert audit["policy_diff"] == [{"field": "name", "before": DesignPolicy().name, "after": "Metadata-only revision"}]
    assert audit["invalidated_exception_ids"] == [exception_id]
    assert not changed["exceptions"][0]["active"]
    assert _store(tmp_path).read({})["audit"][-1] == audit
    next_change = store.update({}, PolicyChange(
        expected_revision=2, policy=DesignPolicy(name="Metadata-only revision", loggingRequired=False), reason="Review logging intent",
    ), "policy-admin")
    assert next_change["audit"][-1]["invalidated_exception_ids"] == []
    assert next_change["audit"][-1]["policy_diff"] == [{"field": "loggingRequired", "before": True, "after": False}]


def test_noop_after_initial_application_does_not_rotate_policy_or_invalidate_risk(tmp_path):
    store = _store(tmp_path)
    applied = store.update({}, PolicyChange(expected_revision=0, policy=DesignPolicy(), reason="Apply defaults"), "admin")
    assert applied["policy_revision"] == 1
    assert applied["audit"][0]["policy_diff"] == []
    store.update({}, _accept(1), "approver")
    with pytest.raises(ValueError, match="no changes"):
        store.update({}, PolicyChange(expected_revision=2, policy=DesignPolicy(), reason="Accidental duplicate save"), "admin")
    current = store.read({})
    assert current["revision"] == 2
    assert current["policy_revision"] == 1
    assert current["exceptions"][0]["active"]
    assert len(current["audit"]) == 2


def test_historical_audit_is_not_backfilled_with_fabricated_field_differences(tmp_path):
    store = _store(tmp_path)
    store.update({}, PolicyChange(expected_revision=0, policy=DesignPolicy(name="Old stored pack"), reason="Historical save"), "admin")
    name = store._name({})
    snapshot = store.documents.read_snapshot(name)
    for key in ("policy_diff", "invalidated_exception_ids", "previous_policy_revision"):
        snapshot.payload["audit"][0].pop(key)
    store.documents.replace_if_match(name, snapshot.payload, expected_etag=snapshot.etag)
    historical = _store(tmp_path).read({})["audit"][0]
    assert "policy_diff" not in historical
    assert "invalidated_exception_ids" not in historical
    assert historical["reason"] == "Historical save"
