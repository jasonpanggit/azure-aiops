from __future__ import annotations

from dataclasses import replace

import pytest
from test_fabric_sql_integration import KbSilverReader, _authorization

from api.exposure_query import ExposureQueryService, ExposureQueryUnavailableError


class KbCountsReader(KbSilverReader):
    def __init__(self, damage=None):
        super().__init__()
        self.damage = damage

    def query(self, sql, parameters=(), *, max_rows=None):
        rows = super().query(sql, parameters, max_rows=max_rows)
        if "[ranked_targets]" not in sql:
            return rows
        rows[0].update({
            "observed_target_count": 1000, "missing_target_count": 100, "failed_target_count": 3,
            "installed_target_count": 800, "other_target_count": 97, "affected_server_count": 103,
        })
        if self.damage == "missing":
            del rows[0]["missing_target_count"]
        elif self.damage == "bool":
            rows[0]["missing_target_count"] = True
        elif self.damage == "float":
            rows[0]["missing_target_count"] = 100.0
        elif self.damage == "negative":
            rows[0]["other_target_count"] = -1
        elif self.damage == "total":
            rows[0]["observed_target_count"] = 1001
        elif self.damage == "affected":
            rows[0]["affected_server_count"] = 102
        elif self.damage == "affected_float":
            rows[0]["affected_server_count"] = 103.0
        elif self.damage == "affected_text":
            rows[0]["affected_server_count"] = "103"
        elif self.damage == "affected_mixed":
            rows.append({**rows[0], "target_resource_id": "other", "affected_server_count": 102})
        elif self.damage == "sample":
            rows[0]["installed_target_count"] = 0
            rows[0]["other_target_count"] = 897
        elif self.damage == "duplicate":
            rows.append(dict(rows[0]))
        elif self.damage == "mixed":
            rows.append({**rows[0], "target_resource_id": "other", "missing_target_count": 101})
        elif self.damage == "unsafe":
            rows[0]["observed_target_count"] = 9_007_199_254_740_992
        return rows


def test_full_deduplicated_status_counts_not_inferred_from_bounded_rows():
    reader = KbCountsReader()
    detail = ExposureQueryService(reader).kb_item(_authorization(), kb_id="KB6000001")
    assert detail["installation_status_counts"] == {
        "observed_targets": 1000, "missing": 100, "installation_failed": 3, "installed": 800, "other": 97,
    }
    assert detail["target_status_observations"] == [{
        "target_id": "server-1", "status": "installed", "observed_at": "2026-09-10T02:41:10Z",
    }]
    assert detail["target_status_observations_truncated"] is True
    sql = reader.calls[-1]["sql"]
    assert "COUNT_BIG(*) OVER () AS [observed_target_count]" in sql
    assert "COUNT_BIG(CASE WHEN LOWER([status]) = 'installed'" in sql
    assert "NOT IN ('missing', 'installation_failed', 'installed')" in sql
    assert "[target_rank] = 1" in sql
    assert "SELECT TOP (100)" in sql
    assert "[tenant_id] = ?" in sql and "[subscription_id] IN (?, ?)" in sql


@pytest.mark.parametrize("damage", ["missing", "bool", "float", "negative", "total", "affected", "affected_float", "affected_text", "affected_mixed", "sample", "duplicate", "mixed", "unsafe"])
def test_invalid_projection_fails_instead_of_showing_plausible_status_counts(damage):
    with pytest.raises(ExposureQueryUnavailableError):
        ExposureQueryService(KbCountsReader(damage)).kb_item(_authorization(), kb_id="KB6000001")


def test_legacy_no_aggregate_projection_remains_unknown():
    detail = ExposureQueryService(KbSilverReader()).kb_item(_authorization(), kb_id="KB6000001")
    assert detail["installation_status_counts"] is None
    assert detail["target_status_observations_truncated"] is None
    assert detail["update_guidance"] == {"source": "msrc", "product_ids": [], "dependency_capability": "not_collected"}


def test_unsupported_scope_cannot_be_dropped_to_acquire_broader_kb_metadata():
    authorization = _authorization()
    with pytest.raises(ValueError, match="Unsupported Exposure scope dimension: environment"):
        replace(authorization, scope={**authorization.scope, "environment": ("production",)})


def test_products_are_identifiers_not_derived_titles_and_unsupported_dependencies_not_promoted():
    def records(identifier):
        return [{
            "source": "msrc", "identifier": identifier, "status": "failed", "stale": True,
            "payload": {"product_ids": ["product-b", "product-a", "product-a"], "title": "Not a product identity",
                        "prerequisites": ["KB6000000"], "superseded_by": "KB9999999", "reboot_required": True},
        }]
    detail = ExposureQueryService(KbCountsReader(), catalog_records_resolver=records).kb_item(_authorization(), kb_id="KB6000001")
    assert detail["update_guidance"]["product_ids"] == ["product-a", "product-b"]
    assert detail["update_guidance"]["dependency_capability"] == "not_collected"
    assert "reboot_required" not in detail["update_guidance"]
    assert detail["enrichment"]["sources"]["msrc:KB6000001"]["status"] == "failed"


@pytest.mark.parametrize("products", ["not-a-list", False, 0, {}])
def test_malformed_provider_product_values_fail(products):
    def records(identifier):
        return [{"source": "msrc", "identifier": identifier, "payload": {"product_ids": products}}]
    with pytest.raises(ExposureQueryUnavailableError, match="product"):
        ExposureQueryService(KbCountsReader(), catalog_records_resolver=records).kb_item(_authorization(), kb_id="KB6000001")
