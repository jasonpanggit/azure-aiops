from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.rbac import Authorizer, Grant, Principal
from api.scope import Scope
from api.telemetry import ApiTelemetry
from intelligence.inventory.exports import EXPORT_COLUMNS, InventoryExportStore
from intelligence.inventory.service import InventoryService
from onboarding.service import SubscriptionOnboardingService
from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore

TOKEN = "inventory-export-reader-token"
OTHER_TOKEN = "inventory-export-other-reader-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
SCOPE = {"subscription": ["sub-a"]}


def _rows(count: int = 501):
    return [
        {
            "family": "os",
            "resource_name": f"vm-{index:05d}",
            "resource_id": f"/subscriptions/sub-a/vm-{index:05d}",
            "subscription_id": "sub-a",
            "properties": {"private": "must-not-leak"},
            "tags": {"secret": "must-not-leak"},
        }
        for index in range(count)
    ]


def _create(store: InventoryExportStore, count: int = 501):
    return store.create(
        "reader",
        SCOPE,
        generation_id="generation-1",
        query_version="query-v1",
        observed_at="2026-10-16T06:00:00Z",
        rows=_rows(count),
    )


def _client(tmp_path: Path, count: int = 501):
    store = InventoryExportStore(OneLakeDocumentStore(tmp_path / "exports"))
    service = InventoryService(
        {
            "generation_id": "generation-1",
            "observations": [
                {
                    "resource_id": f"/subscriptions/{sub}/vm-{index:05d}",
                    "machine_name": f"vm-{index:05d}",
                    "source_type": "arc",
                    "os_name": "Test",
                    "os_version": "1",
                    "subscription_id": sub,
                    "resource_group": "rg",
                    "observed_at": "2026-10-16T06:00:00Z",
                }
                for sub in ("sub-a", "sub-b")
                for index in range(count)
            ],
        }
    )
    context = ApiContext(
        authenticator=StaticTokenAuthenticator(
            {
                TOKEN: Principal(
                    subject="reader",
                    grants=(Grant("reader", Scope.from_mapping(SCOPE)),),
                ),
                OTHER_TOKEN: Principal(
                    subject="other",
                    grants=(Grant("reader", Scope.from_mapping(SCOPE)),),
                ),
            }
        ),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        inventory_export_store=store,
        onboarding=SubscriptionOnboardingService(tmp_path / "onboarding"),
        inventory_provider=lambda: service,
    )
    return TestClient(create_app(context), raise_server_exceptions=False), context


def test_capture_survives_restart_and_active_generation_replacement(tmp_path: Path):
    client, context = _client(tmp_path)
    response = client.post(
        "/api/v1/inventory/exports",
        json={"expected_generation_id": "generation-1"},
        headers=AUTH,
    )
    assert response.status_code == 201, response.text
    manifest = response.json()["data"]["export"]
    assert manifest["total"] == 501
    assert manifest["scope"] == SCOPE
    assert "rows" not in manifest
    context.inventory_provider = lambda: None
    context.inventory_export_store = InventoryExportStore(
        OneLakeDocumentStore(tmp_path / "exports")
    )
    recovered = client.get("/api/v1/inventory/exports/current", headers=AUTH).json()[
        "data"
    ]["export"]
    assert recovered == manifest
    first = client.get(
        f"/api/v1/inventory/exports/{manifest['export_id']}/batches", headers=AUTH
    ).json()["data"]
    last = client.get(
        f"/api/v1/inventory/exports/{manifest['export_id']}/batches?offset=500",
        headers=AUTH,
    ).json()["data"]
    assert len(first["resources"]) == 500
    assert first["next_offset"] == 500
    assert len(last["resources"]) == 1
    assert last["next_offset"] is None
    assert last["manifest"]["sha256"] == manifest["sha256"]
    assert last["manifest"]["generation_id"] == "generation-1"
    assert "sub-b" not in str(first) + str(last)


def test_store_allowlist_integrity_order_and_exact_boundaries(tmp_path: Path):
    store = InventoryExportStore(OneLakeDocumentStore(tmp_path))
    manifest = _create(store)
    first = store.batch("reader", SCOPE, manifest["export_id"], 0)
    assert set(first["resources"][0]) == set(EXPORT_COLUMNS)
    assert "must-not-leak" not in str(first)
    assert first == store.batch("reader", SCOPE, manifest["export_id"], 0)
    with pytest.raises(ValueError, match="500-row batch"):
        store.batch("reader", SCOPE, manifest["export_id"], 1)
    with pytest.raises(ValueError, match="500-row batch"):
        store.batch("reader", SCOPE, manifest["export_id"], 1000)


def test_every_export_read_is_principal_and_current_scope_exact(tmp_path: Path):
    client, _ = _client(tmp_path, 1)
    manifest = client.post(
        "/api/v1/inventory/exports",
        json={"expected_generation_id": "generation-1"},
        headers=AUTH,
    ).json()["data"]["export"]
    url = f"/api/v1/inventory/exports/{manifest['export_id']}"
    other = {"Authorization": f"Bearer {OTHER_TOKEN}"}
    assert client.get(f"{url}/batches", headers=other).status_code == 404
    assert (
        client.post(
            f"{url}/cancel", json={"expected_revision": 1}, headers=other
        ).status_code
        == 404
    )
    assert (
        client.get("/api/v1/inventory/exports/current", headers=other).json()["data"][
            "export"
        ]
        is None
    )
    assert client.get(
        f"{url}/batches?subscription=sub-b", headers=AUTH
    ).status_code in {403, 404}
    assert client.get(f"{url}/batches").status_code == 401
    assert (
        client.post(
            "/api/v1/inventory/exports", json={"expected_generation_id": "generation-1"}
        ).status_code
        == 401
    )
    store = InventoryExportStore(OneLakeDocumentStore(tmp_path / "exports"))
    with pytest.raises(LookupError):
        store.batch(
            "reader",
            {"subscription": ["sub-a"], "environment": ["prod"]},
            manifest["export_id"],
            0,
        )


def test_cancel_requires_revision_removes_rows_and_old_identity_never_reads_replacement(
    tmp_path: Path,
):
    client, context = _client(tmp_path, 1)
    manifest = client.post(
        "/api/v1/inventory/exports",
        json={"expected_generation_id": "generation-1"},
        headers=AUTH,
    ).json()["data"]["export"]
    url = f"/api/v1/inventory/exports/{manifest['export_id']}"
    assert (
        client.post(
            "/api/v1/inventory/exports",
            json={"expected_generation_id": "generation-1"},
            headers=AUTH,
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"{url}/cancel", json={"expected_revision": 2}, headers=AUTH
        ).status_code
        == 409
    )
    cancelled = client.post(
        f"{url}/cancel", json={"expected_revision": 1}, headers=AUTH
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["data"]["export"]["status"] == "cancelled"
    assert client.get(f"{url}/batches", headers=AUTH).status_code == 409
    payload = context.inventory_export_store.documents.read(
        context.inventory_export_store._name("reader", SCOPE)
    )
    assert payload["rows"] == []
    new = client.post(
        "/api/v1/inventory/exports",
        json={"expected_generation_id": "generation-1"},
        headers=AUTH,
    ).json()["data"]["export"]
    assert new["export_id"] != manifest["export_id"]
    assert new["revision"] == 3
    assert client.get(f"{url}/batches", headers=AUTH).status_code == 404


def test_expiry_withholds_rows_and_lazily_removes_body(tmp_path: Path):
    now = datetime(2026, 10, 16, tzinfo=UTC)
    store = InventoryExportStore(OneLakeDocumentStore(tmp_path), clock=lambda: now)
    manifest = _create(store, 1)
    now += timedelta(hours=24)
    with pytest.raises(DocumentConflictError, match="expired"):
        store.batch("reader", SCOPE, manifest["export_id"], 0)
    assert store.current("reader", SCOPE)["status"] == "expired"
    assert store.documents.read(store._name("reader", SCOPE))["rows"] == []
    assert _create(store, 1)["export_id"] != manifest["export_id"]


@pytest.mark.parametrize("count", [0, 50_001])
def test_row_bounds_reject_without_partial_capture(tmp_path: Path, count: int):
    store = InventoryExportStore(OneLakeDocumentStore(tmp_path))
    with pytest.raises(ValueError, match="1–50000"):
        _create(store, count)
    assert store.current("reader", SCOPE) is None


def test_exact_max_row_count_is_not_truncated(tmp_path: Path):
    store = InventoryExportStore(OneLakeDocumentStore(tmp_path))
    manifest = store.create(
        "reader",
        SCOPE,
        generation_id="generation-1",
        query_version="v1",
        observed_at="",
        rows=[{"resource_id": str(index)} for index in range(50_000)],
    )
    batch = store.batch("reader", SCOPE, manifest["export_id"], 49_500)
    assert len(batch["resources"]) == 500
    assert batch["next_offset"] is None


def test_byte_bound_and_missing_generation_reject_without_persistence(tmp_path: Path):
    store = InventoryExportStore(OneLakeDocumentStore(tmp_path))
    with pytest.raises(ValueError, match="16 MiB"):
        store.create(
            "reader",
            SCOPE,
            generation_id="g1",
            query_version="v1",
            observed_at="",
            rows=[{"resource_name": "x" * (16 * 1024 * 1024)}],
        )
    with pytest.raises(ValueError, match="immutable"):
        store.create(
            "reader",
            SCOPE,
            generation_id="",
            query_version="v1",
            observed_at="",
            rows=_rows(1),
        )
    assert store.current("reader", SCOPE) is None


def test_generation_drift_and_unconfigured_storage_fail_explicitly(tmp_path: Path):
    client, context = _client(tmp_path, 1)
    assert (
        client.post(
            "/api/v1/inventory/exports",
            json={"expected_generation_id": "query-v1"},
            headers=AUTH,
        ).status_code
        == 409
    )
    context.inventory_export_store = None
    assert (
        client.post(
            "/api/v1/inventory/exports",
            json={"expected_generation_id": "generation-1"},
            headers=AUTH,
        ).status_code
        == 503
    )
    assert (
        client.get("/api/v1/inventory/exports/current", headers=AUTH).status_code == 503
    )


def test_corrupt_capture_is_not_reset_or_returned_as_caller_error(tmp_path: Path):
    client, context = _client(tmp_path, 1)
    store = context.inventory_export_store
    _create(store, 1)
    name = store._name("reader", SCOPE)
    snapshot = store.documents.read_snapshot(name)
    payload = snapshot.payload
    payload["rows"][0]["resource_id"] = "tampered"
    store.documents.replace_if_match(name, payload, expected_etag=snapshot.etag)
    assert (
        client.get("/api/v1/inventory/exports/current", headers=AUTH).status_code == 500
    )
    assert store.documents.read(name)["rows"][0]["resource_id"] == "tampered"


def test_concurrent_first_capture_has_one_winner(tmp_path: Path, monkeypatch):
    store = InventoryExportStore(OneLakeDocumentStore(tmp_path))
    create = store.documents.create_only
    barrier = Barrier(2)

    def simultaneous_create(*args, **kwargs):
        barrier.wait(timeout=5)
        return create(*args, **kwargs)

    monkeypatch.setattr(store.documents, "create_only", simultaneous_create)

    def capture():
        try:
            return _create(store, 1)["export_id"]
        except DocumentConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: capture(), range(2)))
    assert results.count("conflict") == 1
    assert store.current("reader", SCOPE)["export_id"] in results


def test_runtime_uses_the_existing_durable_root(tmp_path: Path, monkeypatch):
    from api import runtime

    monkeypatch.setattr(runtime, "aiops_home", lambda: tmp_path)
    assert runtime._inventory_export_store().documents.root == str(tmp_path)


def test_serialized_document_byte_limit_is_inclusive_and_covers_metadata(
    tmp_path: Path, monkeypatch
):
    from intelligence.inventory import exports

    monkeypatch.setattr(
        exports, "uuid4", lambda: "11111111-1111-4111-8111-111111111111"
    )
    clock = lambda: datetime(2026, 10, 16, tzinfo=UTC)
    baseline = InventoryExportStore(
        OneLakeDocumentStore(tmp_path / "baseline"), clock=clock
    )
    _create(baseline, 1)
    body = baseline.documents.read(baseline._name("reader", SCOPE))
    exact_size = len((json.dumps(body, indent=2, sort_keys=True) + "\n").encode())
    monkeypatch.setattr(exports, "MAX_EXPORT_BYTES", exact_size)
    exact = InventoryExportStore(OneLakeDocumentStore(tmp_path / "exact"), clock=clock)
    assert _create(exact, 1)["total"] == 1
    monkeypatch.setattr(exports, "MAX_EXPORT_BYTES", exact_size - 1)
    over = InventoryExportStore(OneLakeDocumentStore(tmp_path / "over"), clock=clock)
    with pytest.raises(ValueError, match="16 MiB"):
        _create(over, 1)
    assert over.current("reader", SCOPE) is None


def test_missing_publication_pin_never_uses_query_version(tmp_path: Path):
    client, context = _client(tmp_path, 1)
    context.inventory_provider = lambda: InventoryService({"query_version": "generation-1"})
    assert (
        client.post(
            "/api/v1/inventory/exports",
            json={"expected_generation_id": "generation-1"},
            headers=AUTH,
        ).status_code
        == 409
    )
    assert context.inventory_export_store.current("reader", SCOPE) is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("expires_at", "bad-date"),
        ("expires_at", "2026-10-16T00:00:00"),
        ("sha256", "bad"),
        ("revision", "1"),
    ],
)
def test_corrupt_manifest_fails_closed_without_reset(tmp_path: Path, field: str, value):
    store = InventoryExportStore(OneLakeDocumentStore(tmp_path))
    _create(store, 1)
    name = store._name("reader", SCOPE)
    snapshot = store.documents.read_snapshot(name)
    body = snapshot.payload
    body[field] = value
    store.documents.replace_if_match(name, body, expected_etag=snapshot.etag)
    with pytest.raises(RuntimeError, match="Stored inventory export"):
        store.current("reader", SCOPE)
    assert store.documents.read(name)[field] == value
