"""Retained audit bytes, exact owner/scope authorization and provider independence."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from test_governance import ADMIN_TOKEN, READER_TOKEN, _client, _headers, _snapshot

from intelligence.governance.retained_exports import (
    MAX_CAPTURE_BYTES,
    MAX_CAPTURES,
    MAX_COLLECTION_BYTES,
    AuditCaptureRequest,
    RetainedAuditExportStore,
)
from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore

ACTOR = "reader@example.com"
SCOPE = {"subscription": ["sub-a"]}


def document(scope=None):
    return {
        "data": {
            "kind": "identity", "sections": {"summary": {"assignment_count": 1}},
            "provenance": {"scope": SCOPE if scope is None else scope,
                           "generated_at": "2026-10-16T12:00:00+00:00", "observed_at": ""},
        },
        "scope": SCOPE if scope is None else scope,
        "evidence": [{"confidence": "unknown", "timestamp": ""}],
        "warnings": ["Observation time is unknown"],
    }


def store(tmp_path):
    return RetainedAuditExportStore(OneLakeDocumentStore(tmp_path))


def test_capture_recovery_exact_content_redaction_and_explicit_removal(tmp_path):
    first = store(tmp_path)
    assert first.read(ACTOR, SCOPE)["revision"] == 0
    pack = document()
    pack["data"]["sections"]["credential"] = {"client_secret": "private-value", "secret_ref": "opaque-private"}
    result = first.capture(ACTOR, SCOPE, 0, document=pack)
    capture = result["captures"][0]
    assert result["revision"] == 1
    assert "content" not in capture
    detail = store(tmp_path).detail(ACTOR, SCOPE, capture["export_id"])
    encoded = detail["content"].encode()
    assert hashlib.sha256(encoded).hexdigest() == capture["sha256"]
    assert len(encoded) == capture["size_bytes"]
    assert "private-value" not in detail["content"]
    assert "opaque-private" not in detail["content"]
    assert "Observation time is unknown" in detail["content"]
    assert detail["manifest"]["observed_at"] == ""
    assert pack["data"]["sections"]["credential"]["client_secret"] == "private-value"
    with pytest.raises(DocumentConflictError):
        first.remove(ACTOR, SCOPE, 0, capture["export_id"])
    assert first.remove(ACTOR, SCOPE, 1, capture["export_id"])["captures"] == []
    with pytest.raises(LookupError):
        first.detail(ACTOR, SCOPE, capture["export_id"])


def test_owner_and_every_exact_scope_dimension_are_independent(tmp_path):
    first = store(tmp_path)
    metadata = first.capture(ACTOR, SCOPE, 0, document=document())["captures"][0]
    assert first.read("another-reader", SCOPE)["captures"] == []
    with pytest.raises(LookupError):
        first.detail("another-reader", SCOPE, metadata["export_id"])
    for dimension in [
        "subscription", "business_service", "application", "environment",
        "subscription_connection", "owner", "support_team", "region", "criticality",
    ]:
        foreign = {**SCOPE, dimension: ["other"]}
        assert first.read(ACTOR, foreign)["captures"] == []
        with pytest.raises(LookupError):
            first.detail(ACTOR, foreign, metadata["export_id"])


def test_capacity_rejects_without_eviction_and_stale_capture_does_not_append(tmp_path):
    first = store(tmp_path)
    for revision in range(MAX_CAPTURES):
        result = first.capture(ACTOR, SCOPE, revision, document=document())
    original = result["captures"][-1]["export_id"]
    path = tmp_path / first._name(ACTOR, SCOPE)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="full"):
        first.capture(ACTOR, SCOPE, MAX_CAPTURES, document=document())
    with pytest.raises(DocumentConflictError):
        first.capture(ACTOR, SCOPE, 0, document=document())
    assert path.read_bytes() == before
    assert first.detail(ACTOR, SCOPE, original)


def test_exact_content_byte_bound_is_not_silently_truncated(tmp_path):
    first = store(tmp_path)
    pack = document()
    pack["data"]["sections"]["padding"] = ""
    initial = json.dumps(pack, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n"
    pack["data"]["sections"]["padding"] = "x" * (MAX_CAPTURE_BYTES - len(initial.encode()))
    result = first.capture(ACTOR, SCOPE, 0, document=pack)
    assert result["captures"][0]["size_bytes"] == MAX_CAPTURE_BYTES
    before = (tmp_path / first._name(ACTOR, SCOPE)).read_bytes()
    pack["data"]["sections"]["padding"] += "x"
    with pytest.raises(ValueError, match="512 KiB"):
        first.capture(ACTOR, SCOPE, 1, document=pack)
    assert (tmp_path / first._name(ACTOR, SCOPE)).read_bytes() == before


@pytest.mark.parametrize("seed", [False, True])
def test_cas_races_initial_and_existing_documents(tmp_path, seed):
    initial = store(tmp_path)
    if seed:
        initial.capture(ACTOR, SCOPE, 0, document=document())
    barrier = Barrier(2)

    class RacingDocuments(OneLakeDocumentStore):
        def read_snapshot(self, name):
            snapshot = super().read_snapshot(name)
            barrier.wait(timeout=10)
            return snapshot

    def writer(_):
        try:
            RetainedAuditExportStore(RacingDocuments(tmp_path)).capture(
                ACTOR, SCOPE, int(seed), document=document(),
            )
            return "saved"
        except DocumentConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(writer, [1, 2])) == ["conflict", "saved"]
    assert initial.read(ACTOR, SCOPE)["revision"] == int(seed) + 1


@pytest.mark.parametrize("change", [
    lambda value: value.update(actor="foreign"),
    lambda value: value.update(scope={}),
    lambda value: value.update(revision=False),
    lambda value: value["captures"][0].update(content="{}"),
    lambda value: value["captures"][0].update(sha256="f" * 64),
    lambda value: value["captures"][0].update(size_bytes=1),
    lambda value: value["captures"][0].update(captured_at="2026-10-16"),
    lambda value: value["captures"][0].update(observed_at="invented"),
    lambda value: value["captures"].append(value["captures"][0]),
])
def test_corruption_never_becomes_an_empty_collection_or_gets_overwritten(tmp_path, change):
    first = store(tmp_path)
    first.capture(ACTOR, SCOPE, 0, document=document())
    path = tmp_path / first._name(ACTOR, SCOPE)
    payload = json.loads(path.read_text())
    change(payload)
    path.write_text(json.dumps(payload))
    before = path.read_bytes()
    with pytest.raises(RuntimeError):
        first.read(ACTOR, SCOPE)
    with pytest.raises(RuntimeError):
        first.capture(ACTOR, SCOPE, 1, document=document())
    assert path.read_bytes() == before


@pytest.mark.parametrize("extra", [
    {"document": {}}, {"expected_revision": True}, {"expected_revision": -1},
    {"kind": "unknown"}, {"expected_revision": "0"},
])
def test_requests_never_accept_client_documents_or_invalid_revisions(extra):
    with pytest.raises(ValueError):
        AuditCaptureRequest.model_validate({"kind": "identity", "expected_revision": 0, **extra})


def test_api_captures_as_reader_then_recovers_without_current_sources(tmp_path):
    client = _client(tmp_path, snapshot=_snapshot())
    context = client.app.state.context
    context.retained_audit_export_store = store(tmp_path)
    path = "/api/v1/governance/exports/retained"
    response = client.post(
        path + "?subscription=sub-a", headers=_headers(),
        json={"kind": "identity", "expected_revision": 0},
    )
    assert response.status_code == 201, response.text
    capture = response.json()["data"]["captures"][0]
    assert capture["observed_at"] == _snapshot().observed_at
    assert response.json()["evidence"][0]["confidence"] == "unknown"

    def unavailable():
        raise AssertionError("Retained recovery must not resolve current governance")

    context.governance_provider = unavailable
    for suffix in ["", "/" + capture["export_id"]]:
        response = client.get(path + suffix + "?subscription=sub-a", headers=_headers())
        assert response.status_code == 200, response.text
    assert client.get(
        path + "/" + capture["export_id"] + "?subscription=sub-b", headers=_headers(),
    ).status_code == 404
    assert client.get(
        path + "/" + capture["export_id"] + "?subscription=sub-a", headers=_headers(ADMIN_TOKEN),
    ).status_code == 404
    # Stale collection revision is rejected before asking an unavailable source.
    assert client.post(
        path + "?subscription=sub-a", headers=_headers(),
        json={"kind": "identity", "expected_revision": 0},
    ).status_code == 409
    assert client.post(
        path + "/remove?subscription=sub-a", headers=_headers(),
        json={"export_id": capture["export_id"], "expected_revision": 1},
    ).status_code == 200


def test_api_unavailable_storage_never_reports_empty_success(tmp_path):
    client = _client(tmp_path, snapshot=_snapshot())
    path = "/api/v1/governance/exports/retained"
    assert client.get(path, headers=_headers()).status_code == 503
    assert client.post(
        path, headers=_headers(READER_TOKEN), json={"kind": "identity", "expected_revision": 0},
    ).status_code == 503


def test_escaped_content_collection_bound_rejects_without_changing_prior_copies(tmp_path):
    first = store(tmp_path)
    pack = document()
    pack["data"]["sections"]["padding"] = '"' * 250_000
    for revision in range(6):
        first.capture(ACTOR, SCOPE, revision, document=pack)
    path = tmp_path / first._name(ACTOR, SCOPE)
    before = path.read_bytes()
    assert len(before) <= MAX_COLLECTION_BYTES
    with pytest.raises(ValueError, match="6 MiB"):
        first.capture(ACTOR, SCOPE, 6, document=pack)
    assert path.read_bytes() == before
    assert len(first.read(ACTOR, SCOPE)["captures"]) == 6


@pytest.mark.parametrize("operation", ["read_snapshot", "create_only", "replace_if_match"])
def test_storage_failures_never_return_success_or_destroy_prior_content(tmp_path, monkeypatch, operation):
    first = store(tmp_path)
    revision = 0
    if operation == "replace_if_match":
        first.capture(ACTOR, SCOPE, 0, document=document())
        revision = 1
    path = tmp_path / first._name(ACTOR, SCOPE)
    before = path.read_bytes() if path.exists() else None

    def fail(*args, **kwargs):
        raise OSError("private-storage-details")

    monkeypatch.setattr(first.documents, operation, fail)
    with pytest.raises(OSError):
        first.capture(ACTOR, SCOPE, revision, document=document())
    assert (path.read_bytes() if path.exists() else None) == before


def test_runtime_recovery_uses_existing_root_and_no_provider(tmp_path, monkeypatch):
    from api import runtime

    monkeypatch.setattr(runtime, "aiops_home", lambda: tmp_path)
    result = runtime._retained_audit_export_store().capture(ACTOR, SCOPE, 0, document=document())
    assert runtime._retained_audit_export_store().read(ACTOR, SCOPE) == result


@pytest.mark.parametrize("kind", [
    "subscription_onboarding", "network_design", "firewall_nsg",
    "vulnerability_exposure", "identity", "remediation", "executive",
])
def test_api_all_existing_kinds_keep_partial_warnings_and_exact_manifest(tmp_path, kind):
    client = _client(tmp_path, snapshot=_snapshot())
    client.app.state.context.retained_audit_export_store = store(tmp_path)
    path = "/api/v1/governance/exports/retained"
    captured = client.post(path, headers=_headers(), json={"kind": kind, "expected_revision": 0})
    assert captured.status_code == 201, captured.text
    manifest = captured.json()["data"]["captures"][0]
    detail = client.get(path + "/" + manifest["export_id"], headers=_headers()).json()["data"]
    data = json.loads(detail["content"])
    assert detail["manifest"] == manifest
    assert data["data"]["kind"] == kind
    assert len(data.get("warnings", [])) == manifest["warning_count"]
    assert hashlib.sha256(detail["content"].encode()).hexdigest() == manifest["sha256"]


def test_api_exact_combined_nine_dimension_recovery_and_grant_narrowing(tmp_path):
    from api.auth import StaticTokenAuthenticator
    from api.rbac import Grant, Principal
    from api.scope import Scope

    client = _client(tmp_path, snapshot=_snapshot())
    context = client.app.state.context
    context.retained_audit_export_store = store(tmp_path)
    selected = {
        "subscription": ["sub-a"], "business_service": ["payments"], "application": ["checkout"],
        "environment": ["production"], "subscription_connection": ["conn-a"], "owner": ["platform"],
        "support_team": ["sre"], "region": ["eastus"], "criticality": ["high"],
    }
    path = "/api/v1/governance/exports/retained"
    captured = client.post(path, headers=_headers(), params=selected,
                           json={"kind": "subscription_onboarding", "expected_revision": 0})
    assert captured.status_code == 201, captured.text
    export_id = captured.json()["data"]["captures"][0]["export_id"]
    assert captured.json()["scope"] == selected
    assert client.get(path + "/" + export_id, headers=_headers(), params=selected).status_code == 200
    for dimension in selected:
        foreign = {**selected, dimension: ["different"]}
        assert client.get(path + "/" + export_id, headers=_headers(), params=foreign).status_code == 404
    context.authenticator = StaticTokenAuthenticator({
        READER_TOKEN: Principal(subject=ACTOR, grants=(Grant("reader", Scope({"subscription": {"sub-b"}})),)),
    })
    assert client.get(path + "/" + export_id, headers=_headers(), params=selected).status_code == 403


@pytest.mark.parametrize("failure", [KeyError("private-key"), ValueError("private-value")])
def test_api_bad_current_source_is_safe_unavailable_not_missing_or_client_error(tmp_path, monkeypatch, failure):
    from api.routers import governance

    client = _client(tmp_path, snapshot=_snapshot())
    first = store(tmp_path)
    client.app.state.context.retained_audit_export_store = first

    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(governance, "audit_export", fail)
    result = client.post("/api/v1/governance/exports/retained", headers=_headers(),
                         json={"kind": "identity", "expected_revision": 0})
    assert result.status_code == 503
    assert "private-" not in result.text
    assert first.read(ACTOR, {})["revision"] == 0


def test_api_malformed_persisted_json_never_becomes_empty_success(tmp_path):
    client = _client(tmp_path, snapshot=_snapshot())
    first = store(tmp_path)
    client.app.state.context.retained_audit_export_store = first
    first.capture(ACTOR, {}, 0, document=document({}))
    path = tmp_path / first._name(ACTOR, {})
    path.write_text("{invalid private-json")
    result = client.get("/api/v1/governance/exports/retained", headers=_headers())
    assert result.status_code == 503
    assert "private-json" not in result.text
    assert path.read_text() == "{invalid private-json"
