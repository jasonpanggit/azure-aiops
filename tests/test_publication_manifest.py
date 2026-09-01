"""Regression tests for the publication manifest lifecycle-disposition
registry (MED-09).

This is a **distinct concept** from the existing per-connection ingestion
snapshot manifest (`manifest.json`, read by
`src/api/runtime.py::_load_snapshot_tables()` and written by
`src/fabric/dataset_mapper.py`/`src/fabric/sync_service.py`): that manifest
tracks *one connector's raw sync attempt* (`runId`/`startedAt`). The
publication manifest tested here tracks *lifecycle disposition* (active /
dormant / retired) for a generated ontology projection -- an unrelated
concept that must never be conflated with, or extend the schema of, the
snapshot manifest (see RESEARCH.md's Pitfall #4).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ontology.publication_manifest import (
    PublicationManifestEntry,
    PublicationManifestStore,
)


def _clock(now: datetime):
    return lambda: now


# ---------------------------------------------------------------------------
# Test 1: registering a projection as `active` is queryable by name
# ---------------------------------------------------------------------------


def test_register_new_projection_active_is_queryable() -> None:
    """Registering a new ontology projection with disposition `active` is
    queryable by name and returns `active`."""
    store = PublicationManifestStore()

    store.register("application_context", disposition="active")

    entry = store.get("application_context")
    assert entry.disposition == "active"
    assert entry.projection_name == "application_context"


# ---------------------------------------------------------------------------
# Test 2: marking a projection `dormant` never triggers deletion
# ---------------------------------------------------------------------------


def test_set_disposition_dormant_keeps_physical_binding_and_is_queryable() -> None:
    """Marking a projection `dormant` keeps its physical Fabric binding
    intact (the manifest only changes disposition metadata, never triggers
    deletion) and it is queryable as `dormant`."""
    store = PublicationManifestStore()
    store.register("infrastructure_context", disposition="active")

    store.set_disposition("infrastructure_context", "dormant")

    entry = store.get("infrastructure_context")
    assert entry.disposition == "dormant"
    # The registry only ever holds metadata -- there is no delete/drop path.
    assert not hasattr(store, "delete")
    assert not hasattr(store, "drop")


# ---------------------------------------------------------------------------
# Test 3: `retired` requires compatibility_version and retired_reason
# ---------------------------------------------------------------------------


def test_set_disposition_retired_requires_compatibility_version_and_reason() -> None:
    """Marking a projection `retired` requires a `compatibility_version` and
    `retired_reason`; omitting either raises `ValueError`."""
    store = PublicationManifestStore()
    store.register("business_context", disposition="active")

    with pytest.raises(ValueError):
        store.set_disposition("business_context", "retired")

    with pytest.raises(ValueError):
        store.set_disposition(
            "business_context", "retired", compatibility_version="2.0.0"
        )

    with pytest.raises(ValueError):
        store.set_disposition(
            "business_context", "retired", retired_reason="superseded by v2"
        )

    # Supplying both succeeds.
    store.set_disposition(
        "business_context",
        "retired",
        compatibility_version="2.0.0",
        retired_reason="superseded by v2",
    )
    entry = store.get("business_context")
    assert entry.disposition == "retired"
    assert entry.compatibility_version == "2.0.0"
    assert entry.retired_reason == "superseded by v2"


def test_register_retired_also_requires_compatibility_version_and_reason() -> None:
    """The same requirement applies at initial registration time, not just
    `set_disposition`, since a projection could be registered directly as
    `retired`."""
    store = PublicationManifestStore()

    with pytest.raises(ValueError):
        store.register("compliance_context", disposition="retired")


# ---------------------------------------------------------------------------
# Test 4: querying an unregistered projection returns `unknown`, not `active`
# ---------------------------------------------------------------------------


def test_get_unregistered_projection_returns_unknown_disposition() -> None:
    """Querying an unregistered projection name returns a distinct `unknown`
    disposition, never silently defaulting to `active`."""
    store = PublicationManifestStore()

    entry = store.get("never_registered_projection")

    assert entry.disposition == "unknown"
    assert entry.disposition != "active"


# ---------------------------------------------------------------------------
# Test 5: the publication manifest schema/table is structurally distinct
# from the existing per-connection snapshot manifest (`manifest.json`)
# ---------------------------------------------------------------------------


def test_publication_manifest_schema_is_structurally_distinct_from_snapshot_manifest() -> None:
    """The manifest module's own schema/table name never collides with or
    extends the existing snapshot manifest's `manifest.json` structure --
    assert the two are structurally distinct: different table/keys
    entirely."""
    from fabric.schema_registry import schema_for

    publication_schema = schema_for("metadata_publication_manifest")
    publication_fields = set(publication_schema.names)

    # The existing snapshot manifest (manifest.json, written/read by
    # dataset_mapper.py / api/runtime.py::_load_snapshot_tables()) is keyed
    # by `runId`/`startedAt` and is not a registered Delta schema at all --
    # it is a bare JSON sidecar file, never a `SCHEMAS` entry. Confirm no
    # such keys leak into the new publication manifest schema, and that the
    # publication manifest's own identifying fields are present.
    snapshot_manifest_keys = {"runId", "startedAt"}
    assert not (publication_fields & snapshot_manifest_keys)
    assert "projection_name" in publication_fields
    assert "disposition" in publication_fields

    # The publication manifest table name itself must never be "manifest"
    # or collide with the snapshot manifest's file name.
    assert "metadata_publication_manifest" != "manifest.json"


# ---------------------------------------------------------------------------
# Additional coverage: dataclass shape and entry independence
# ---------------------------------------------------------------------------


def test_publication_manifest_entry_tracks_registered_and_updated_timestamps() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    store = PublicationManifestStore(clock=_clock(now))

    store.register("application_context", disposition="active")
    entry = store.get("application_context")

    assert entry.registered_at == now.isoformat()
    assert entry.updated_at == now.isoformat()

    later = datetime(2026, 1, 2, tzinfo=UTC)
    store._clock = _clock(later)  # noqa: SLF001 -- test-only clock swap
    store.set_disposition("application_context", "dormant")
    updated_entry = store.get("application_context")

    assert updated_entry.registered_at == now.isoformat()
    assert updated_entry.updated_at == later.isoformat()


def test_publication_manifest_entry_is_a_dataclass_with_expected_fields() -> None:
    entry = PublicationManifestEntry(
        projection_name="application_context",
        disposition="active",
        compatibility_version=None,
        retired_reason=None,
        registered_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )
    assert entry.projection_name == "application_context"
    assert entry.disposition == "active"
