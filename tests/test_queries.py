from __future__ import annotations

from datetime import UTC, datetime

from onboarding.query_catalog import QueryCatalog


def test_query_catalog_contains_required_arg_tables() -> None:
    specs = QueryCatalog().build(datetime(2026, 8, 1, tzinfo=UTC))
    by_name = {spec.name: spec for spec in specs}

    assert {
        "resources",
        "resource_containers",
        "resource_changes",
        "patch_assessments",
        "patch_installations",
        "advisor_recommendations",
        "defender_assessments",
        "defender_subassessments",
        "defender_alerts",
        "defender_attack_paths",
        "defender_secure_scores",
        "defender_secure_score_controls",
    } <= set(by_name)
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
    assert "microsoft.security/assessments'" in by_name["defender_assessments"].query.lower()
    assert (
        "microsoft.security/assessments/subassessments"
        in by_name["defender_subassessments"].query.lower()
    )
    for name in ("defender_assessments", "defender_subassessments"):
        projection = by_name[name].query.casefold()
        assert "tenantid" in projection
        assert "resourcegroup" in projection
        assert "location" in projection
    expected_defender_types = {
        "defender_alerts": "microsoft.security/locations/alerts",
        "defender_attack_paths": "microsoft.security/attackpaths",
        "defender_secure_scores": "microsoft.security/securescores'",
        "defender_secure_score_controls": "microsoft.security/securescores/securescorecontrols",
    }
    for name, resource_type in expected_defender_types.items():
        assert by_name[name].table == "SecurityResources"
        assert resource_type in by_name[name].query.lower()


def test_query_catalog_includes_every_network_resource_family() -> None:
    specs = QueryCatalog().build(datetime(2026, 8, 1, tzinfo=UTC))
    by_name = {spec.name: spec for spec in specs}

    expected = {
        "network_vnets",
        "network_interfaces",
        "network_security_groups",
        "network_route_tables",
        "network_firewalls",
        "network_private_endpoints",
        "network_private_dns_zones",
        "network_gateways",
        "network_load_balancers",
        "network_firewall_policies",
    }
    assert expected <= set(by_name)
    for name in expected:
        assert by_name[name].table == "Resources"
        assert "microsoft.network/" in by_name[name].query.lower()


def test_network_queries_are_split_so_one_throttle_does_not_blank_topology() -> None:
    """Each family is its own query, so a failure loses one type, not the graph."""
    specs = QueryCatalog().build(datetime(2026, 8, 1, tzinfo=UTC))
    network = [spec for spec in specs if spec.name.startswith("network_")]
    assert len(network) >= 10
    assert len({spec.name for spec in network}) == len(network)


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
