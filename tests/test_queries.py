from __future__ import annotations

from datetime import UTC, datetime

from hermes_arg_connector.queries import QueryCatalog


def test_query_catalog_contains_required_arg_tables() -> None:
    specs = QueryCatalog().build(datetime(2026, 8, 1, tzinfo=UTC))
    by_name = {spec.name: spec for spec in specs}

    assert set(by_name) == {
        "resources",
        "resource_containers",
        "resource_changes",
        "patch_assessments",
        "patch_installations",
        "advisor_recommendations",
    }
    assert by_name["resources"].table == "Resources"
    assert by_name["resource_containers"].table == "ResourceContainers"
    assert by_name["resource_changes"].table == "ResourceChanges"
    assert "datetime(2026-07-31T23:50:00Z)" in by_name["resource_changes"].query
    assert by_name["patch_assessments"].table == "PatchAssessmentResources"
    assert "softwarepatches" in by_name["patch_assessments"].query.lower()
    assert "!endswith" in by_name["patch_assessments"].query.lower()
    assert by_name["patch_installations"].table == "PatchInstallationResources"
    assert "softwarepatches" in by_name["patch_installations"].query.lower()
    assert "advisorresources" in by_name["advisor_recommendations"].query.lower()


def test_query_catalog_adds_management_group_scope_when_configured() -> None:
    specs = QueryCatalog().build(None, include_management_groups=True)
    management = next(spec for spec in specs if spec.name == "management_groups")

    assert management.scope == "management_groups"
    assert "microsoft.management/managementgroups" in management.query


def test_initial_change_query_uses_safe_lookback() -> None:
    spec = next(spec for spec in QueryCatalog().build(None) if spec.name == "resource_changes")
    assert "ago(7d)" in spec.query


def test_incremental_change_query_overlaps_watermark() -> None:
    watermark = datetime(2026, 8, 1, 1, tzinfo=UTC)
    spec = next(
        spec
        for spec in QueryCatalog(overlap_minutes=10).build(watermark)
        if spec.name == "resource_changes"
    )
    assert "datetime(2026-08-01T00:50:00Z)" in spec.query
