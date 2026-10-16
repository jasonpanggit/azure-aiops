"""Retained advisory receipts: identity isolation, atomicity and honest comparisons."""

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.rbac import Authorizer, Grant, Principal
from api.scope import Scope
from api.telemetry import ApiTelemetry
from intelligence.predeploy.service import PreDeploymentImpactService
from onboarding.service import SubscriptionOnboardingService
from operations.predeploy_history import (
    AssessmentHistory,
    AssessmentReceipt,
    PredeployHistoryStore,
    assessment_receipt,
    compare_receipts,
)
from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore


def _receipt() -> AssessmentReceipt:
    service = PreDeploymentImpactService()
    assessment = service.assess(
        source="terraform_plan",
        payload={
            "resource_changes": [
                {
                    "address": "example.web",
                    "type": "example",
                    "change": {
                        "actions": ["update"],
                        "before": {"id": "test"},
                        "after": {"id": "test", "port": 443},
                    },
                }
            ]
        },
    )
    return assessment_receipt(assessment)


def test_projection_never_keeps_raw_artifacts_or_property_bags():
    receipt = _receipt()
    serialized = json.dumps(receipt.model_dump())
    assert receipt.changes[0].changed_properties == ["port"]
    assert "before" not in serialized and "after" not in serialized
    assert receipt.confidence == "unknown" and receipt.verdict == "require_review"


def test_restart_recovery_and_explicit_deletion(tmp_path):
    store = PredeployHistoryStore(OneLakeDocumentStore(tmp_path))
    row = _receipt()
    assert store.read("owner", {})["revision"] == 0
    saved = store.append("owner", {}, 0, row)
    assert PredeployHistoryStore(store.documents).read("owner", {}) == saved
    assert store.remove("owner", {}, 1, row.assessment_id)["revision"] == 2
    assert store.read("owner", {})["receipts"] == []


def test_exact_actor_and_scope_identity_and_stale_or_duplicate_writes(tmp_path):
    store = PredeployHistoryStore(OneLakeDocumentStore(tmp_path))
    row = _receipt()
    scope = {"subscription": ["a", "b"], "region": ["eastus"]}
    store.append("owner", scope, 0, row)
    for actor, other_scope in (
        ("other", scope),
        ("owner", {}),
        ("owner", {"subscription": ["a"]}),
    ):
        assert store.read(actor, other_scope)["receipts"] == []
    with pytest.raises(DocumentConflictError):
        store.append("owner", scope, 0, _receipt())
    with pytest.raises(DocumentConflictError):
        store.append("owner", scope, 1, row)
    with pytest.raises(KeyError):
        store.remove("owner", scope, 1, uuid4().hex)
    assert store.read("owner", scope)["revision"] == 1


@pytest.mark.parametrize("existing", [False, True])
def test_atomic_concurrent_create_and_replace_preserve_one_winner(tmp_path, existing):
    store = PredeployHistoryStore(OneLakeDocumentStore(tmp_path))
    if existing:
        store.append("owner", {}, 0, _receipt())
    revision = int(existing)
    barrier = Barrier(2)
    original = store.documents.read_snapshot

    def read(name):
        snapshot = original(name)
        barrier.wait(timeout=10)
        return snapshot

    def append(row):
        try:
            return store.append("owner", {}, revision, row)["revision"]
        except DocumentConflictError:
            return "conflict"

    rows = [_receipt(), _receipt()]
    with (
        patch.object(store.documents, "read_snapshot", side_effect=read),
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        results = list(pool.map(append, rows))
    assert sorted(map(str, results)) == [str(revision + 1), "conflict"]
    recovered = store.read("owner", {})
    assert len(recovered["receipts"]) == revision + 1


def test_full_history_fails_without_eviction_but_explicit_removal_allows_capture(
    tmp_path,
):
    store = PredeployHistoryStore(OneLakeDocumentStore(tmp_path))
    for revision in range(20):
        store.append("owner", {}, revision, _receipt())
    before = store.read("owner", {})
    with pytest.raises(ValueError, match="full"):
        store.append("owner", {}, 20, _receipt())
    assert store.read("owner", {}) == before
    store.remove("owner", {}, 20, before["receipts"][0]["assessment_id"])
    assert len(store.append("owner", {}, 21, _receipt())["receipts"]) == 20


@pytest.mark.parametrize(
    "change",
    [
        {"actor": "other"},
        {"scope": {"region": ["other"]}},
        {"schema_version": True},
        {"schema_version": 1.0},
        {"revision": True},
        {"updated_at": "2020-01-01"},
    ],
)
def test_corruption_never_becomes_an_empty_history(tmp_path, change):
    store = PredeployHistoryStore(OneLakeDocumentStore(tmp_path))
    state = store.append("owner", {}, 0, _receipt())
    name = store._name("owner", {})
    snapshot = store.documents.read_snapshot(name)
    store.documents.replace_if_match(
        name, {**state, **change}, expected_etag=snapshot.etag
    )
    with pytest.raises(RuntimeError):
        store.read("owner", {})


def test_comparison_preserves_duplicate_rows_but_ignores_source_index_and_property_order():
    original = _receipt().model_dump()
    original["changes"][0]["changed_properties"] = ["port", "setting"]
    before = AssessmentReceipt.model_validate(original)
    raw = before.model_dump()
    raw["assessment_id"] = uuid4().hex
    raw["changes"][0]["source_ref"] = "resource_changes[9]"
    raw["changes"][0]["changed_properties"].reverse()
    after = AssessmentReceipt.model_validate(raw)
    compared = compare_receipts(before, after)
    assert compared["same_artifact"] is True
    assert compared["added_declared_rows"] == compared["removed_declared_rows"] == []
    raw["changes"].append(raw["changes"][0].copy())
    duplicate = AssessmentReceipt.model_validate(raw)
    compared = compare_receipts(before, duplicate)
    assert len(compared["added_declared_rows"]) == 1
    assert compared["removed_declared_rows"] == []
    with pytest.raises(ValueError, match="different"):
        compare_receipts(before, before)


def test_comparison_rejects_different_formats_and_makes_no_lineage_claim():
    before = _receipt()
    data = before.model_dump()
    data.update(assessment_id=uuid4().hex, source="arm_diff")
    with pytest.raises(ValueError, match="same artifact source"):
        compare_receipts(before, AssessmentReceipt.model_validate(data))
    data.update(source="terraform_plan", artifact_sha256="f" * 64, risk_score=42)
    compared = compare_receipts(before, AssessmentReceipt.model_validate(data))
    assert compared["same_artifact"] is False
    assert compared["risk_score_delta"] == 42 - before.risk_score
    assert "do not prove revision lineage" in compared["interpretation"]


def test_strict_receipt_bounds_and_extra_fields():
    data = _receipt().model_dump()
    for change in (
        {"payload": {}},
        {"risk_score": True},
        {"title": "x" * 513},
        {"retained_at": "2020-01-01"},
        {"impacted_resource_ids": ["same", "same"]},
    ):
        with pytest.raises(ValidationError):
            AssessmentReceipt.model_validate({**data, **change})
    with pytest.raises(ValidationError):
        AssessmentHistory(
            schema_version=1,
            actor="owner",
            scope={},
            revision=0,
            updated_at="",
            receipts=[_receipt()],
        )


def _client(tmp_path):
    store = PredeployHistoryStore(OneLakeDocumentStore(tmp_path / "documents"))
    service = PreDeploymentImpactService()
    context = ApiContext(
        onboarding=SubscriptionOnboardingService(tmp_path / "aiops"),
        authenticator=StaticTokenAuthenticator(
            {
                "history-admin-fixture": Principal(
                    subject="owner", grants=(Grant("admin"),)
                ),
                "history-other-fixture": Principal(
                    subject="other", grants=(Grant("admin"),)
                ),
                "history-reader-fixture": Principal(
                    subject="owner", grants=(Grant("reader"),)
                ),
                "history-scoped-fixture": Principal(
                    subject="owner",
                    grants=(
                        Grant("admin", Scope.from_mapping({"subscription": ["a"]})),
                    ),
                ),
            }
        ),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        predeploy_history_store=store,
    )
    context.predeploy_service = service
    client = TestClient(create_app(context), raise_server_exceptions=False)
    return client, context, service, store


def _auth(token="history-admin"):
    return {"Authorization": "Bearer " + token + "-fixture"}


def _create(client, params=None):
    response = client.post(
        "/api/v1/changes/assess",
        headers=_auth(),
        params=params,
        json={"source": "terraform_plan", "payload": {"resource_changes": []}},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def _retain(client, assessment, revision=0, params=None, token="history-admin"):
    return client.post(
        "/api/v1/changes/retained-assessments",
        headers=_auth(token),
        params=params,
        json={
            "assessment_id": assessment["assessment_id"],
            "artifact_sha256": assessment["artifact"]["sha256"],
            "expected_revision": revision,
        },
    )


def test_api_retention_recovery_comparison_and_explicit_delete(tmp_path):
    client, _, service, store = _client(tmp_path)
    first, second = _create(client), _create(client)
    assert _retain(client, first).status_code == 201
    assert _retain(client, second, 1).status_code == 201
    service._assessments.clear()
    recovered = client.get(
        "/api/v1/changes/retained-assessments", headers=_auth("history-reader")
    )
    assert (
        recovered.status_code == 200 and len(recovered.json()["data"]["receipts"]) == 2
    )
    assert (
        PredeployHistoryStore(store.documents).read("owner", {})
        == recovered.json()["data"]
    )
    compared = client.get(
        "/api/v1/changes/retained-assessments/compare",
        headers=_auth("history-reader"),
        params={
            "baseline_id": first["assessment_id"],
            "candidate_id": second["assessment_id"],
        },
    )
    assert compared.status_code == 200, compared.text
    assert compared.json()["data"]["same_artifact"] is True
    removed = client.post(
        "/api/v1/changes/retained-assessments/remove",
        headers=_auth(),
        json={"assessment_id": first["assessment_id"], "expected_revision": 2},
    )
    assert removed.status_code == 200 and removed.json()["data"]["revision"] == 3
    assert len(removed.json()["data"]["receipts"]) == 1


def test_api_rechecks_owner_exact_scope_digest_and_source_eviction(tmp_path):
    client, _, service, _ = _client(tmp_path)
    query = [("subscription", "a"), ("subscription", "b"), ("region", "eastus")]
    assessment = _create(client, query)
    assert (
        _retain(client, assessment, params=query, token="history-other").status_code
        == 404
    )
    assert _retain(client, assessment).status_code == 404
    assert (
        _retain(
            client, assessment, params={"subscription": "a", "region": "eastus"}
        ).status_code
        == 404
    )
    altered = {**assessment, "artifact": {**assessment["artifact"], "sha256": "f" * 64}}
    assert _retain(client, altered, params=query).status_code == 409
    assert _retain(client, assessment, params=query).status_code == 201
    assert (
        client.get("/api/v1/changes/retained-assessments", headers=_auth()).json()[
            "data"
        ]["receipts"]
        == []
    )
    service._assessments.clear()
    assert _retain(client, assessment, 1, query).status_code == 404
    own = client.get(
        "/api/v1/changes/retained-assessments", headers=_auth(), params=query
    )
    assert len(own.json()["data"]["receipts"]) == 1


def test_api_preserves_reader_admin_boundary_and_intersects_grants(tmp_path):
    client, _, _, _ = _client(tmp_path)
    assessment = _create(client)
    assert _retain(client, assessment, token="history-reader").status_code == 403
    assert client.get("/api/v1/changes/retained-assessments").status_code == 401
    response = client.get(
        "/api/v1/changes/retained-assessments",
        headers=_auth("history-scoped"),
        params=[("subscription", "a"), ("subscription", "b")],
    )
    assert response.status_code == 200 and response.json()["scope"] == {
        "subscription": ["a"]
    }
    assert (
        client.get(
            "/api/v1/changes/retained-assessments",
            headers=_auth("history-scoped"),
            params={"subscription": "b"},
        ).status_code
        == 403
    )


def test_api_storage_failure_and_mutation_conflicts_require_reload(
    tmp_path, monkeypatch
):
    client, context, _, store = _client(tmp_path)
    assessment = _create(client)
    assert _retain(client, assessment).status_code == 201
    assert _retain(client, assessment).status_code == 409
    second = _create(client)
    monkeypatch.setattr(
        store.documents,
        "replace_if_match",
        Mock(side_effect=OSError("Storage unavailable")),
    )
    assert _retain(client, second, 1).status_code == 503
    context.predeploy_history_store = None
    assert (
        client.get("/api/v1/changes/retained-assessments", headers=_auth()).status_code
        == 503
    )


def test_actual_receipt_and_collection_byte_limits_do_not_silently_truncate(tmp_path):
    original = _receipt().model_dump()
    with pytest.raises(ValidationError, match="256 KiB"):
        AssessmentReceipt.model_validate({**original, "unknowns": ["é" * 8192] * 6})
    store = PredeployHistoryStore(OneLakeDocumentStore(tmp_path))
    for revision in range(20):
        receipt = AssessmentReceipt.model_validate(
            {
                **original,
                "assessment_id": uuid4().hex,
                "unknowns": ["é" * 7000] * 5,
            }
        )
        before = store.read("owner", {})
        try:
            updated = store.append("owner", {}, revision, receipt)
        except ValueError as exc:
            assert "4 MiB" in str(exc)
            candidate = {
                **before,
                "revision": revision + 1,
                "receipts": [*before["receipts"], receipt.model_dump()],
            }
            actual_size = len(
                (json.dumps(candidate, indent=2, sort_keys=True) + "\n").encode()
            )
            assert actual_size > 4 * 1024 * 1024
            assert store.read("owner", {}) == before
            break
        assert (
            len((json.dumps(updated, indent=2, sort_keys=True) + "\n").encode())
            <= 4 * 1024 * 1024
        )
    else:
        pytest.fail("Measured collection size never reached its documented byte limit")


@pytest.mark.parametrize(
    "extra",
    [
        {"expected_revision": True},
        {"expected_revision": "0"},
        {"actor": "other"},
        {"scope": {}},
        {"assessment": {}},
        {"payload": {}},
        {"execute": True},
        {"artifact_sha256": "../untrusted"},
    ],
)
def test_api_retention_only_accepts_strict_references(tmp_path, extra):
    client, _, _, store = _client(tmp_path)
    assessment = _create(client)
    response = client.post(
        "/api/v1/changes/retained-assessments",
        headers=_auth(),
        json={
            "assessment_id": assessment["assessment_id"],
            "artifact_sha256": assessment["artifact"]["sha256"],
            "expected_revision": 0,
            **extra,
        },
    )
    assert response.status_code == 400
    assert store.read("owner", {})["revision"] == 0


def test_api_recovery_and_comparison_do_not_acquire_current_providers(tmp_path):
    client, context, service, _ = _client(tmp_path)
    left, right = _create(client), _create(client)
    assert _retain(client, left).status_code == 201
    assert _retain(client, right, 1).status_code == 201
    unavailable = Mock(
        side_effect=AssertionError("Historical reads must not acquire current sources")
    )
    context.semantic_provider = unavailable
    context.network_provider = unavailable
    service._assessments.clear()
    assert (
        client.get("/api/v1/changes/retained-assessments", headers=_auth()).status_code
        == 200
    )
    compared = client.get(
        "/api/v1/changes/retained-assessments/compare",
        headers=_auth(),
        params={
            "baseline_id": left["assessment_id"],
            "candidate_id": right["assessment_id"],
        },
    )
    assert compared.status_code == 200
    assert (
        client.get(
            "/api/v1/changes/retained-assessments/compare",
            headers=_auth("history-other"),
            params={
                "baseline_id": left["assessment_id"],
                "candidate_id": right["assessment_id"],
            },
        ).status_code
        == 404
    )
    unavailable.assert_not_called()


def test_runtime_factory_uses_existing_document_root(tmp_path, monkeypatch):
    from api import runtime

    monkeypatch.setattr(runtime, "aiops_home", lambda: tmp_path)
    store = runtime._predeploy_history_store()
    store.append("owner", {}, 0, _receipt())
    assert runtime._predeploy_history_store().read("owner", {})["revision"] == 1


def test_invalid_current_server_summary_is_not_reported_as_missing_receipt(tmp_path):
    client, _, service, store = _client(tmp_path)
    assessment = _create(client)
    service._assessments[assessment["assessment_id"]].pop("risk")
    assert _retain(client, assessment).status_code == 503
    assert store.read("owner", {})["revision"] == 0
