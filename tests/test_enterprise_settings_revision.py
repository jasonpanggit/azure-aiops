"""Reviewed settings CAS, legacy migration and global authorization boundaries."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier

import pytest
from pydantic import ValidationError
from test_governance import ADMIN_TOKEN, _client, _headers

from api import runtime
from api.auth import StaticTokenAuthenticator
from api.rbac import Grant, Principal
from api.scope import Scope
from intelligence.governance import settings as settings_module
from intelligence.governance.settings import (
    MAX_SETTINGS_BYTES,
    MAX_SETTINGS_REVISION,
    SETTINGS_DOCUMENT,
    EnterpriseSettingsStore,
    SettingsChange,
    SettingsValidationError,
)
from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore


def _write(store, changes=None, revision=0):
    return store.update(
        changes or {"retention_policy": {"audit_log_days": 30}},
        expected_revision=revision, reason="Reviewed retention", actor="admin@example.com",
    )


def test_persisted_settings_survive_a_new_store_and_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "aiops_home", lambda: tmp_path)
    first = runtime._settings_store()
    assert first.read_versioned()["revision"] == 0
    result = _write(first)
    assert result["revision"] == 1
    assert result["persistent"] is True
    assert result["last_change"]["actor"] == "admin@example.com"
    assert result["last_change"]["reason"] == "Reviewed retention"
    assert runtime._settings_store().read_versioned() == result
    assert "revision" not in runtime._settings_store().read()


def test_legacy_partial_settings_keep_defaults_and_revision(tmp_path):
    documents = OneLakeDocumentStore(tmp_path)
    documents.create_only(SETTINGS_DOCUMENT, {
        "revision": 7, "settings": {"retention_policy": {"audit_log_days": 50}},
    })
    store = EnterpriseSettingsStore(documents)
    assert store.read_versioned()["last_change"] is None
    assert store.read()["retention_policy"]["estate_snapshot_days"] == 365
    assert _write(store, revision=7)["revision"] == 8


@pytest.mark.parametrize("revision", [True, -1, 1.5, "0", MAX_SETTINGS_REVISION])
def test_revision_and_reason_are_strict(revision):
    with pytest.raises(ValidationError):
        SettingsChange(expected_revision=revision, changes={"roles": []}, reason="Review")


@pytest.mark.parametrize("reason", ["", "  ", "a" * 1201])
def test_change_reason_required(reason):
    with pytest.raises(ValidationError):
        SettingsChange(expected_revision=0, changes={"roles": []}, reason=reason)


def test_stale_revision_and_merged_policy_bypass_cannot_write(tmp_path):
    store = EnterpriseSettingsStore(OneLakeDocumentStore(tmp_path))
    _write(store, {"agent_policy": {"allow_autonomous_remediation": True}})
    with pytest.raises(DocumentConflictError):
        _write(store)
    before = (tmp_path / SETTINGS_DOCUMENT).read_bytes()
    with pytest.raises(SettingsValidationError, match="human approval"):
        _write(store, {"agent_policy": {"require_human_approval": False}}, revision=1)
    assert (tmp_path / SETTINGS_DOCUMENT).read_bytes() == before


@pytest.mark.parametrize("payload", [
    {}, {"settings": {}, "revision": True}, {"settings": [], "revision": 0},
    {"settings": {}, "revision": -1}, {"settings": {}, "revision": "0"},
    {"settings": {"agent_policy": None}, "revision": 1},
    {"settings": {"agent_policy": {"require_human_approval": "false"}}, "revision": 1},
    {"settings": {}, "revision": 1, "last_change": {"actor": "someone"}},
    {"settings": {}, "revision": MAX_SETTINGS_REVISION + 1},
])
def test_corruption_never_reads_as_defaults_or_gets_overwritten(tmp_path, payload):
    documents = OneLakeDocumentStore(tmp_path)
    documents.create_only(SETTINGS_DOCUMENT, payload)
    before = (tmp_path / SETTINGS_DOCUMENT).read_bytes()
    store = EnterpriseSettingsStore(documents)
    with pytest.raises(RuntimeError):
        store.read()
    with pytest.raises(RuntimeError):
        _write(store)
    assert (tmp_path / SETTINGS_DOCUMENT).read_bytes() == before


@pytest.mark.parametrize("seed", [False, True])
def test_two_readers_only_one_writes_same_revision(tmp_path, seed):
    initial = EnterpriseSettingsStore(OneLakeDocumentStore(tmp_path))
    if seed:
        _write(initial)
    barrier = Barrier(2)

    class RacingDocuments(OneLakeDocumentStore):
        def read_snapshot(self, name):
            snapshot = super().read_snapshot(name)
            barrier.wait(timeout=10)
            return snapshot

    def writer(days):
        try:
            _write(
                EnterpriseSettingsStore(RacingDocuments(tmp_path)),
                {"retention_policy": {"audit_log_days": days}}, revision=int(seed),
            )
            return "saved"
        except DocumentConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(writer, [30, 60])) == ["conflict", "saved"]
    assert initial.read_versioned()["revision"] == int(seed) + 1


def test_nonfinite_and_oversize_writes_are_rejected_without_persistence(tmp_path):
    store = EnterpriseSettingsStore(OneLakeDocumentStore(tmp_path))
    for value in [float("nan"), float("inf"), "x" * MAX_SETTINGS_BYTES]:
        with pytest.raises(SettingsValidationError):
            _write(store, {"agent_policy": {"extension": value}})
    assert not (tmp_path / SETTINGS_DOCUMENT).exists()


def test_exact_serialized_document_limit_including_escaped_unicode(tmp_path, monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 16, 12, tzinfo=UTC)

    monkeypatch.setattr(settings_module, "datetime", Clock)
    store = EnterpriseSettingsStore(OneLakeDocumentStore(tmp_path))
    _write(store, {"report_templates": ["\u4e2d"]})
    path = tmp_path / SETTINGS_DOCUMENT
    payload = json.loads(path.read_text())
    # Revision 1/2/3 and frozen attribution have equal serialized lengths.
    available = MAX_SETTINGS_BYTES - len(path.read_bytes())
    value = "\u4e2d" + "x" * available
    _write(store, {"report_templates": [value]}, revision=1)
    before = path.read_bytes()
    assert len(before) == MAX_SETTINGS_BYTES
    with pytest.raises(SettingsValidationError, match="512 KiB"):
        _write(store, {"report_templates": [value + "x"]}, revision=2)
    assert path.read_bytes() == before
    assert payload["revision"] == 1


def test_etag_guards_against_out_of_band_same_revision_replacement(tmp_path):
    documents = OneLakeDocumentStore(tmp_path)
    _write(EnterpriseSettingsStore(documents))
    original = documents.read_snapshot

    def changed(name):
        snapshot = original(name)
        payload = json.loads(json.dumps(snapshot.payload))
        payload["settings"]["retention_policy"]["audit_log_days"] = 99
        documents.replace_if_match(name, payload, expected_etag=snapshot.etag)
        return snapshot

    documents.read_snapshot = changed
    with pytest.raises(DocumentConflictError):
        _write(EnterpriseSettingsStore(documents), revision=1)
    assert original(SETTINGS_DOCUMENT).payload["settings"]["retention_policy"]["audit_log_days"] == 99


@pytest.mark.parametrize("operation", ["read_snapshot", "create_only", "replace_if_match"])
def test_storage_failures_are_safe_and_never_reset_the_policy(tmp_path, operation):
    documents = OneLakeDocumentStore(tmp_path)
    seeded = operation == "replace_if_match"
    if seeded:
        _write(EnterpriseSettingsStore(documents))
    path = tmp_path / SETTINGS_DOCUMENT
    before = path.read_bytes() if seeded else None

    def failure(*args, **kwargs):
        raise OSError("Private storage diagnostics")

    setattr(documents, operation, failure)
    client = _client(tmp_path)
    client.app.state.context.settings_store = EnterpriseSettingsStore(documents)
    if operation == "read_snapshot":
        response = client.get("/api/v1/governance/settings", headers=_headers())
        assert response.status_code == 503
        assert "Private" not in response.text
    response = client.patch(
        "/api/v1/governance/settings", headers=_headers(ADMIN_TOKEN),
        json={"expected_revision": int(seeded), "reason": "Review",
              "changes": {"retention_policy": {"audit_log_days": 30}}},
    )
    assert response.status_code == 503
    assert "Private" not in response.text
    assert (path.read_bytes() if path.exists() else None) == before


def test_api_requires_review_and_global_write_grant(tmp_path):
    client = _client(tmp_path)
    body = SettingsChange(
        expected_revision=0, reason="Review", changes={"retention_policy": {"audit_log_days": 30}},
    ).model_dump()
    assert client.patch(
        "/api/v1/governance/settings", headers=_headers(ADMIN_TOKEN),
        json=body["changes"],
    ).status_code == 400
    principal = Principal(subject="scoped", grants=(
        Grant("reader"), Grant("admin", Scope.from_mapping({"subscription": ["sub-a"]})),
    ))
    client.app.state.context.authenticator = StaticTokenAuthenticator({ADMIN_TOKEN: principal})
    client.app.state.context.settings_store = EnterpriseSettingsStore(OneLakeDocumentStore(tmp_path))
    assert client.get(
        "/api/v1/governance/settings", headers=_headers(ADMIN_TOKEN),
    ).json()["data"]["can_write"] is False
    response = client.patch(
        "/api/v1/governance/settings?subscription=sub-a",
        headers=_headers(ADMIN_TOKEN), json=body,
    )
    assert response.status_code == 403
    client.app.state.context.authenticator = StaticTokenAuthenticator({
        ADMIN_TOKEN: Principal(subject="global", grants=(Grant("admin"),)),
    })
    assert client.get(
        "/api/v1/governance/settings", headers=_headers(ADMIN_TOKEN),
    ).json()["data"]["can_write"] is True
    response = client.patch(
        "/api/v1/governance/settings?subscription=sub-a", headers=_headers(ADMIN_TOKEN), json=body,
    )
    assert response.status_code == 200
    assert response.json()["data"]["last_change"]["actor"] == "global"
    assert client.patch(
        "/api/v1/governance/settings", headers=_headers(ADMIN_TOKEN), json=body,
    ).status_code == 409


def test_api_corrupt_or_unavailable_storage_is_safe_503(tmp_path):
    client = _client(tmp_path)
    path = tmp_path / "settings" / SETTINGS_DOCUMENT
    path.parent.mkdir(parents=True)
    path.write_text("bad document with private details")
    client.app.state.context.settings_store = EnterpriseSettingsStore(
        OneLakeDocumentStore(tmp_path / "settings"),
    )
    response = client.get("/api/v1/governance/settings", headers=_headers())
    assert response.status_code == 503
    assert "private" not in response.text
    before = path.read_bytes()
    response = client.patch(
        "/api/v1/governance/settings", headers=_headers(ADMIN_TOKEN),
        json={"expected_revision": 0, "reason": "Review",
              "changes": {"retention_policy": {"audit_log_days": 30}}},
    )
    assert response.status_code == 503
    assert path.read_bytes() == before


def test_missing_settings_store_reads_explicit_nonpersistent_defaults(tmp_path):
    client = _client(tmp_path)
    client.app.state.context.settings_store = None
    response = client.get("/api/v1/governance/settings", headers=_headers())
    assert response.status_code == 200
    assert response.json()["data"]["persistent"] is False
    assert response.json()["warnings"]


def test_exhausted_revision_is_readable_but_not_writable(tmp_path):
    documents = OneLakeDocumentStore(tmp_path)
    documents.create_only(SETTINGS_DOCUMENT, {"settings": {}, "revision": MAX_SETTINGS_REVISION})
    client = _client(tmp_path)
    client.app.state.context.settings_store = EnterpriseSettingsStore(documents)
    response = client.get("/api/v1/governance/settings", headers=_headers(ADMIN_TOKEN))
    assert response.status_code == 200
    assert response.json()["data"]["can_write"] is False
