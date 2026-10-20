"""Connection scope must be checked before accessing medallion datasets."""

from types import SimpleNamespace

import pytest

from api.routers import fabric_medallion as routes
from api.scope import Scope
from ontology.publication_state import PublicationAttemptRecord


@pytest.fixture
def connection_context(monkeypatch):
    details = {
        "hidden": {
            "connection_id": "hidden", "subscription_id": "sub-hidden",
            "dataset_root": "hidden-root",
        },
        "allowed": {
            "connection_id": "allowed", "subscription_id": "sub-allowed",
            "dataset_root": "allowed-root",
        },
    }
    accesses = []
    datasets = {}

    class Store:
        def __init__(self, root):
            if root == "hidden-root":
                raise AssertionError("Unauthorized root accessed before scope filtering")
            self.root = root

        def read_dataset(self, name):
            accesses.append((self.root, name))
            if name not in datasets:
                raise AssertionError(f"Unexpected metadata read: {name}")
            return datasets[name]

    context = SimpleNamespace(onboarding=SimpleNamespace(
        list=lambda **kwargs: [{"connection_id": name} for name in details],
        detail=lambda name: details[name],
        sync_coordinator=SimpleNamespace(publication_state_store=SimpleNamespace(list=lambda: [
            PublicationAttemptRecord(
                attempt_id="attempt", ontology_name="ontology", outcome="failed",
                retryable=True, error="publication failed", attempted_at="2026-10-19T12:00:00Z",
            ),
        ])),
    ))
    monkeypatch.setattr(routes, "DatasetStore", Store)
    monkeypatch.setattr(routes, "_lakehouse_delta_rows", lambda _name: [])
    return context, details, datasets, accesses


@pytest.mark.parametrize("kind", ["source", "manifest", "quality", "publication"])
def test_scoped_reads_never_open_unauthorized_root(connection_context, monkeypatch, kind):
    context, _, datasets, accesses = connection_context
    scope = Scope({"subscription": {"sub-allowed"}})
    datasets.update({
        "metadata_source_status": [{
            "source_family": "bronze_resources", "subscription_id": "obsolete",
            "subscription_connection": "obsolete", "status": "succeeded",
        }],
        "metadata_publication_manifest": [{
            "projection_name": "projection", "disposition": "active",
            "subscription_id": "obsolete", "subscription_connection": "obsolete",
        }],
        "metadata_quality_reports": [{"report_json": "[]"}],
    })

    def unexpected_fallback(_name):
        pytest.fail("Nonempty authorized data must not trigger Lakehouse fallback")

    monkeypatch.setattr(routes, "_lakehouse_delta_rows", unexpected_fallback)
    if kind == "source":
        rows = routes._scoped_source_rows(context, scope)
        assert rows[0]["subscription_id"] == "sub-allowed"
        assert rows[0]["subscription_connection"] == "allowed"
        assert accesses == [("allowed-root", "metadata_source_status")]
    elif kind == "manifest":
        body = routes.medallion_manifest(context, scope)
        assert body["scope"] == {"subscription": ["sub-allowed"]}
        assert body["data"]["entries"][0]["subscription_id"] == "sub-allowed"
        assert body["data"]["entries"][0]["subscription_connection"] == "allowed"
        assert accesses == [("allowed-root", "metadata_publication_manifest")]
    elif kind == "quality":
        assert routes._metadata_quality_report_rows(context, scope)[0]["report_json"] == "[]"
        assert accesses == [("allowed-root", "metadata_quality_reports")]
    else:
        assert routes._publication_attempt_rows(context, scope) == [{
            "projection_name": "ontology", "status": "failed",
            "attempted_at": "2026-10-19T12:00:00Z", "attempts": 1,
            "retry_eligible": True, "message": "publication failed", "source": "publication-state",
        }]
        assert accesses == []


def test_publication_visibility_does_not_require_source_status_storage(connection_context):
    context, details, _, accesses = connection_context
    del details["hidden"]
    # The fixture reader raises for every dataset because none are registered.
    assert routes._publication_attempt_rows(context, Scope())[0]["status"] == "failed"
    assert accesses == []


@pytest.mark.parametrize("connections", ["none", "hidden", "empty", "no-root"])
@pytest.mark.parametrize("kind", ["source", "manifest", "quality"])
def test_empty_scoped_connections_keep_filtered_lakehouse_fallback(
    connection_context, monkeypatch, connections, kind
):
    context, details, datasets, accesses = connection_context
    if connections == "none":
        details.clear()
    elif connections == "hidden":
        del details["allowed"]
    else:
        del details["hidden"]
        if connections == "no-root":
            details["allowed"]["dataset_root"] = ""
    datasets.update({
        "metadata_source_status": [], "metadata_publication_manifest": [],
        "metadata_quality_reports": [],
    })
    allowed = {
        "source_family": "bronze_resources", "projection_name": "allowed-projection",
        "subscription_id": "sub-allowed", "subscription_connection": "allowed",
    }
    hidden = {**allowed, "subscription_id": "sub-hidden", "projection_name": "hidden-projection"}
    fallback_reads = []

    def fallback(name):
        fallback_reads.append(name)
        return [allowed, hidden]

    monkeypatch.setattr(routes, "_lakehouse_delta_rows", fallback)
    scope = Scope({"subscription": {"sub-allowed"}})
    if kind == "source":
        assert routes._scoped_source_rows(context, scope) == [allowed]
        assert fallback_reads == ["metadata_source_status"]
    elif kind == "manifest":
        entries = routes.medallion_manifest(context, scope)["data"]["entries"]
        assert [row["projection_name"] for row in entries] == ["allowed-projection"]
        assert fallback_reads == ["metadata_publication_manifest"]
    else:
        assert routes._metadata_quality_report_rows(context, scope) == [allowed]
        assert fallback_reads == ["metadata_quality_reports"]
    assert len(accesses) == (1 if connections == "empty" else 0)


def test_no_visible_connection_does_not_read_publication_store(connection_context):
    context, details, _, accesses = connection_context
    del details["allowed"]

    def unexpected():
        pytest.fail("Publication store must not be accessed without a visible connection")

    context.onboarding.sync_coordinator.publication_state_store.list = unexpected
    assert routes._publication_attempt_rows(context, Scope({"subscription": {"sub-allowed"}})) == []
    assert accesses == []


@pytest.mark.parametrize("kind", ["source", "manifest", "quality"])
def test_unrestricted_reads_all_connections_without_unrelated_metadata(
    connection_context, monkeypatch, kind
):
    context, _, _, _ = connection_context
    reads = []

    class Store:
        def __init__(self, root):
            self.root = root

        def read_dataset(self, name):
            reads.append((self.root, name))
            return [{
                "source_family": "bronze_resources", "projection_name": "projection",
                "subscription_id": "obsolete",
            }]

    monkeypatch.setattr(routes, "DatasetStore", Store)
    if kind == "source":
        rows = routes._scoped_source_rows(context, Scope())
        table = "metadata_source_status"
        assert [row["subscription_id"] for row in rows] == ["sub-hidden", "sub-allowed"]
        assert [row["subscription_connection"] for row in rows] == ["hidden", "allowed"]
    elif kind == "manifest":
        rows = routes.medallion_manifest(context, Scope())["data"]["entries"]
        table = "metadata_publication_manifest"
        assert {row["subscription_id"] for row in rows} == {"sub-hidden", "sub-allowed"}
        assert {row["subscription_connection"] for row in rows} == {"hidden", "allowed"}
    else:
        rows = routes._metadata_quality_report_rows(context, Scope())
        table = "metadata_quality_reports"
        assert len(rows) == 2
    assert reads == [
        ("hidden-root", table), ("allowed-root", table),
    ]


@pytest.mark.parametrize("kind", ["source", "manifest", "quality"])
def test_authorized_storage_errors_still_propagate(connection_context, kind):
    context, details, _, _ = connection_context
    del details["hidden"]
    with pytest.raises(AssertionError, match="Unexpected metadata read"):
        scope = Scope({"subscription": {"sub-allowed"}})
        if kind == "source":
            routes._scoped_source_rows(context, scope)
        elif kind == "manifest":
            routes.medallion_manifest(context, scope)
        else:
            routes._metadata_quality_report_rows(context, scope)


@pytest.mark.parametrize("dimension,value", [
    ("subscription_connection", "allowed"),
    ("business_service", "service-allowed"),
    ("environment", "production"),
])
def test_registry_dimensions_are_applied_before_source_storage(
    connection_context, dimension, value
):
    context, details, datasets, accesses = connection_context
    details["allowed"].update({"business_service": "service-allowed", "environment": "production"})
    details["hidden"].update({"business_service": "service-hidden", "environment": "staging"})
    datasets["metadata_source_status"] = []
    assert routes._scoped_source_rows(context, Scope({dimension: {value}})) == []
    assert accesses == [("allowed-root", "metadata_source_status")]
