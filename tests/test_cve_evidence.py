from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from test_exposure_history import AUTH, SCOPE, routes

from api.exposure_query import ExposureQueryPage
from api.scope import SCOPE_DIMENSIONS
from operations.cve_evidence import CaptureCveEvidence, CveEvidenceStore, receipt_digest
from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore

CVE = "CVE-2026-2001"
PATH = f"/api/v1/cves/{CVE}/evidence"


def request(**extra):
    return CaptureCveEvidence(**{
        "expected_revision": 0, "generation": "gen-one", "page_size": 25, "filters": {"weakness_id": CVE}, **extra,
    })


def source():
    page = {
        "scope": SCOPE, "generation": "gen-one", "total_count": 100,
        "items": [{"exposure_id": "one", "target_id": "vm-one", "weakness_id": CVE, "target_kind": "server",
                   "severity": "critical", "completeness": "partial", "secret_payload": "never-retain"}],
        "freshness": {"as_of": "2026-10-17T00:00:00Z"}, "completeness": {"state": "partial"},
    }
    catalog = {
        "scope": SCOPE, "data": {"generation": "gen-one", "catalog_scope": "external_public_metadata", "environment_membership_included": False,
        "item": {"cve_id": CVE, "sources": {
            "nvd": {"source": "nvd", "identifier": CVE, "status": "succeeded", "stale": False, "has_last_known_good": True,
                    "source_at": "2026-10-16T00:00:00Z", "payload": {"cvss": {"base_score": 9.8, "vector": "CVSS:3.1"},
                    "associated_kbs": ["KB600001"], "description": "never-retain"}},
            "kev": {"source": "kev", "identifier": CVE, "status": "failed", "stale": True, "has_last_known_good": True,
                    "payload": {"kev_due_date": "2026-10-16"}},
        }}},
    }
    return page, catalog


def test_explicit_bounded_receipt_restart_identity_integrity_and_allowlist(tmp_path):
    store = CveEvidenceStore(OneLakeDocumentStore(tmp_path))
    saved = store.append("reader", SCOPE, CVE, request(), *source())
    receipt = saved["receipts"][0]
    assert receipt["sha256"] == receipt_digest({key: value for key, value in receipt.items() if key != "sha256"})
    assert receipt["sources"][0]["kev_listed"] is None  # Failed KEV is not a current listing.
    assert receipt["captured_at"] != receipt["source_observed_at"]
    assert receipt["total_count"] == 100 and len(receipt["findings"]) == 1
    assert "never-retain" not in json.dumps(saved)
    assert CveEvidenceStore(OneLakeDocumentStore(tmp_path)).read("reader", SCOPE, CVE) == saved
    assert store.read("other", SCOPE, CVE)["revision"] == 0
    assert store.read("reader", SCOPE, "CVE-2026-9999")["revision"] == 0
    for dimension in SCOPE_DIMENSIONS:
        assert store.read("reader", {**SCOPE, dimension: ["other"]}, CVE)["revision"] == 0


@pytest.mark.parametrize("damage", ["scope", "generation", "catalog_cve", "row_cve", "row_generation", "duplicates", "total", "source_count", "source_cve", "payload_cve", "msrc_cve", "nan", "unavailable"])
def test_mixed_invalid_sources_do_not_persist(tmp_path, damage):
    page, catalog = source()
    if damage == "scope":
        catalog["scope"] = {}
    elif damage == "generation":
        catalog["data"]["generation"] = "other"
    elif damage == "catalog_cve":
        catalog["data"]["item"]["cve_id"] = "CVE-2026-9999"
    elif damage == "row_cve":
        page["items"][0]["weakness_id"] = "CVE-2026-9999"
    elif damage == "row_generation":
        page["items"][0]["read_model_generation_id"] = "other"
    elif damage == "duplicates":
        page["items"] *= 2
    elif damage == "total":
        page["total_count"] = 0
    elif damage == "source_count":
        catalog["data"]["item"]["sources"] = {str(index): {**catalog["data"]["item"]["sources"]["nvd"], "identifier": str(index)} for index in range(41)}
    elif damage == "nan":
        catalog["data"]["item"]["sources"]["nvd"]["payload"]["cvss"]["base_score"] = float("nan")
    elif damage == "source_cve":
        catalog["data"]["item"]["sources"]["nvd"]["identifier"] = "CVE-2026-9999"
    elif damage == "payload_cve":
        catalog["data"]["item"]["sources"]["nvd"]["payload"]["cve_id"] = "CVE-2026-9999"
    elif damage == "msrc_cve":
        catalog["data"]["item"]["sources"]["msrc"] = {
            **catalog["data"]["item"]["sources"]["nvd"], "source": "msrc", "identifier": "KB600001",
            "payload": {"kb_id": "KB600001", "cve_ids": ["CVE-2026-9999"]},
        }
    else:
        page["completeness"]["state"] = "unavailable"
    store = CveEvidenceStore(OneLakeDocumentStore(tmp_path))
    with pytest.raises(ValueError):
        store.append("reader", SCOPE, CVE, request(), page, catalog)
    assert store.read("reader", SCOPE, CVE)["revision"] == 0


def test_corrupt_digest_and_document_cannot_be_empty_history(tmp_path):
    store = CveEvidenceStore(OneLakeDocumentStore(tmp_path))
    saved = store.append("reader", SCOPE, CVE, request(), *source())
    saved["receipts"][0]["total_count"] = 101
    store.documents.put(store._name("reader", SCOPE, CVE), saved)
    with pytest.raises(ValueError, match="digest"):
        store.read("reader", SCOPE, CVE)
    store.documents.put(store._name("reader", SCOPE, CVE), {})
    with pytest.raises(ValueError):
        store.read("reader", SCOPE, CVE)


def test_capacity_and_byte_bounds_preserve_history(tmp_path, monkeypatch):
    from operations import cve_evidence
    store = CveEvidenceStore(OneLakeDocumentStore(tmp_path))
    saved = store.append("reader", SCOPE, CVE, request(), *source())
    exact = len((json.dumps(saved, indent=2, sort_keys=True) + "\n").encode())
    monkeypatch.setattr(cve_evidence, "MAX_BYTES", exact)
    assert store.read("reader", SCOPE, CVE) == saved
    with pytest.raises(ValueError, match="512 KiB"):
        store.append("reader", SCOPE, CVE, request(expected_revision=1), *source())
    assert store.read("reader", SCOPE, CVE) == saved
    monkeypatch.setattr(cve_evidence, "MAX_BYTES", 512 * 1024)
    for revision in range(1, 20):
        last = store.append("reader", SCOPE, CVE, request(expected_revision=revision), *source())
    with pytest.raises(DocumentConflictError):
        store.append("reader", SCOPE, CVE, request(expected_revision=20), *source())
    assert last["receipts"][0] == saved["receipts"][0]


def test_atomic_concurrent_append_and_failed_persistence(tmp_path, monkeypatch):
    store = CveEvidenceStore(OneLakeDocumentStore(tmp_path))
    barrier = Barrier(2)

    def append():
        barrier.wait()
        try:
            return store.append("reader", SCOPE, CVE, request(), *source())["revision"]
        except DocumentConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(map(str, pool.map(lambda _: append(), range(2)))) == ["1", "conflict"]
    saved = store.read("reader", SCOPE, CVE)

    def fail(*args, **kwargs):
        raise OSError("write failed")

    monkeypatch.setattr(store.documents, "replace_if_match", fail)
    with pytest.raises(OSError):
        store.append("reader", SCOPE, CVE, request(expected_revision=1), *source())
    assert store.read("reader", SCOPE, CVE) == saved


def test_routes_capture_only_explicit_post_then_read_without_reacquisition(tmp_path, monkeypatch):
    from api.routers import vulnerability
    client, _, _ = routes(tmp_path, monkeypatch)
    page, catalog = source()
    catalog["data"]["item"]["sources"]["nvd"]["payload"]["cvss"]["base_score"] = 9
    calls = []

    def acquire(**kwargs):
        calls.append(kwargs)
        return ExposureQueryPage(items=tuple(page["items"]), total_count=100, facets={}, generation="gen-one", applied_scope=SCOPE,
            applied_filters=(), applied_sort={"field": "priority_score", "direction": "desc"}, next_position=None,
            completeness=page["completeness"], freshness=page["freshness"])

    def acquire_catalog(*args, **kwargs):
        calls.append(kwargs)
        return catalog

    monkeypatch.setattr(vulnerability, "_query_exposure_page", acquire)
    monkeypatch.setattr(vulnerability, "exposure_external_catalog", acquire_catalog)
    assert client.get(PATH, headers=AUTH).json()["data"]["revision"] == 0
    assert not calls
    response = client.post(PATH, headers=AUTH, json=request().model_dump())
    assert response.status_code == 201, response.text
    assert calls[0]["weakness_id"] == CVE and calls[0]["generation_id"] == "gen-one"
    assert calls[0]["scope"].to_dict() == SCOPE and calls[1]["generation"] == "gen-one"
    assert client.get(PATH, headers=AUTH).json()["data"] == response.json()["data"]
    receipt = response.json()["data"]["receipts"][0]
    export_path = f"{PATH}/{receipt['receipt_id']}"
    exported = client.get(export_path, headers=AUTH)
    assert exported.status_code == 200, exported.text
    bundle = exported.json()["data"]
    assert '"cvss_score":9.0' in bundle["content"]  # Exact server bytes, not JS number reserialization.
    assert json.loads(bundle["content"]) == receipt
    assert bundle["manifest"]["size_bytes"] == len(bundle["content"].encode("utf-8"))
    assert bundle["manifest"]["receipt_sha256"] == receipt["sha256"]
    import hashlib
    assert bundle["manifest"]["sha256"] == hashlib.sha256(bundle["content"].encode("utf-8")).hexdigest()
    assert client.get(f"{PATH}/cve-{'0' * 32}", headers=AUTH).status_code == 404
    assert client.get(export_path).status_code == 401
    assert client.get(export_path + "?subscription=outside", headers=AUTH).status_code == 403
    assert client.post(PATH, headers=AUTH, json=request().model_dump()).status_code == 409
    assert len(calls) == 2
    assert client.get(PATH).status_code == 401
    assert client.get(PATH + "?subscription=outside", headers=AUTH).status_code == 403
    assert client.get("/api/v1/cves/not-cve/evidence", headers=AUTH).status_code == 400
    assert client.post(PATH, headers=AUTH, json=request(filters={"weakness_id": "CVE-2026-9999"}).model_dump()).status_code == 400
    for extra in ({"actor": "other"}, {"sources": []}, {"expected_revision": True}):
        assert client.post(PATH, headers=AUTH, json={**request().model_dump(), **extra}).status_code == 400


def test_export_reauthorizes_receipt_identity_and_rejects_corrupt_storage(tmp_path, monkeypatch):
    from test_overview_history import OTHER

    client, context, _ = routes(tmp_path, monkeypatch)
    store = CveEvidenceStore(context.exposure_history_store.documents)
    actor = client.get(PATH, headers=AUTH).json()["data"]["actor"]
    saved = store.append(actor, SCOPE, CVE, request(), *source())
    receipt = saved["receipts"][0]
    export_path = f"{PATH}/{receipt['receipt_id']}"
    assert client.get(export_path, headers=AUTH).status_code == 200
    assert client.get(export_path, headers={"Authorization": f"Bearer {OTHER}"}).status_code == 404
    assert client.get(export_path.replace(CVE, "CVE-2026-9999"), headers=AUTH).status_code == 404
    saved["receipts"][0]["total_count"] += 1
    store.documents.put(store._name(actor, SCOPE, CVE), saved)
    assert client.get(export_path, headers=AUTH).status_code == 503
