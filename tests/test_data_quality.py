from __future__ import annotations

import json
import math

from fabric.data_quality import DataQualityValidator

BASE = {
    "tenant_id": "tenant-1",
    "subscription_id": "sub-1",
    "resource_id": "/subscriptions/sub-1/resources/r1",
    "timestamp": "2026-08-17T00:00:00Z",
    "change_version": "v1",
    "ingestion_run_id": "run-1",
    "entity_type": "Resource",
    "name": "resource",
    "resource_type": "microsoft.test/resources",
    "location": "eastus",
    # Populated owner/tags so this fixture represents a fully governed
    # resource by default -- ownership/tag-coverage tests below construct
    # their own payload_json to exercise the missing-owner/missing-tag paths.
    "payload_json": json.dumps({"owner": "team-platform", "tags": {"environment": "production"}}),
    "resource_group": "rg",
    "status": "",
    "os_name": "",
    "os_version": "",
    "vm_size": "",
}

OPERATIONAL = {
    key: BASE[key]
    for key in (
        "tenant_id",
        "subscription_id",
        "resource_id",
        "timestamp",
        "change_version",
        "ingestion_run_id",
    )
}


def test_data_quality_accepts_valid_inventory() -> None:
    report = DataQualityValidator().validate_table("bronze_resources", [BASE])

    assert report.passed
    assert report.failed_records == 0


def test_data_quality_detects_missing_fields_and_duplicates() -> None:
    duplicate = dict(BASE)
    missing = {
        **{key: value for key, value in BASE.items() if key != "tenant_id"},
        "resource_id": "/subscriptions/sub-1/resources/r2",
    }

    report = DataQualityValidator().validate_table(
        "bronze_resources",
        [BASE, duplicate, missing],
    )

    assert not report.passed
    assert report.rule_counts["required_fields"] == 1
    assert report.rule_counts["duplicates"] == 1


def test_data_quality_detects_subscription_mismatch() -> None:
    row = {**BASE, "subscription_id": "sub-2"}

    report = DataQualityValidator().validate_table("bronze_resources", [row])

    assert report.rule_counts["subscription_consistency"] == 1


def test_data_quality_detects_orphan_relationship() -> None:
    relationship = {
        **OPERATIONAL,
        "subject_id": BASE["resource_id"],
        "predicate": "dependsOn",
        "object_id": "/subscriptions/sub-1/resources/missing",
        "confidence": 1.0,
        "source": "test",
        "payload_json": "{}",
    }

    report = DataQualityValidator().validate_relationships(
        [relationship],
        entity_ids={BASE["resource_id"]},
    )

    assert not report.passed
    assert report.rule_counts["orphan_relationships"] == 1


def test_data_quality_rejects_negative_governed_compliance_counts() -> None:
    compliance = {
        key: BASE[key]
        for key in (
            "tenant_id",
            "subscription_id",
            "resource_id",
            "timestamp",
            "change_version",
            "ingestion_run_id",
            "entity_type",
            "name",
            "resource_type",
            "location",
            "payload_json",
        )
    }
    compliance.update(
        {
            "assessed_resource_id": BASE["resource_id"],
            "status": "noncompliant",
            "last_modified": BASE["timestamp"],
            "available_updates": 0,
            "missing_critical_updates": 0,
            "missing_security_updates": 0,
        }
    )
    for field_name in (
        "available_updates",
        "missing_critical_updates",
        "missing_security_updates",
    ):
        row = {**compliance, field_name: -1}
        report = DataQualityValidator().validate_table("silver_compliance", [row])
        assert not report.passed, field_name
        assert report.rule_counts["schema_validation"] == 1


def test_data_quality_rejects_invalid_numeric_domains_and_canonical_duplicates() -> None:
    relationship = {
        **OPERATIONAL,
        "subject_id": BASE["resource_id"],
        "predicate": "dependsOn",
        "object_id": "/subscriptions/sub-1/resources/r2",
        "confidence": 1.0,
        "source": "test",
        "payload_json": "{}",
    }
    for confidence in (True, math.nan, math.inf, -0.1, 1.1):
        report = DataQualityValidator().validate_table(
            "silver_resource_relationships",
            [{**relationship, "confidence": confidence}],
        )
        assert not report.passed, confidence

    alias = {**BASE, "resource_id": BASE["resource_id"].upper()}
    report = DataQualityValidator().validate_table(
        "bronze_resources", [BASE, alias]
    )
    assert not report.passed
    assert report.rule_counts["duplicates"] == 1


def test_data_quality_ownership_tag_coverage_ignores_populated_rows() -> None:
    report = DataQualityValidator().validate_table("bronze_resources", [BASE])

    assert report.rule_counts["ownership_coverage"] == 0
    assert report.rule_counts["tag_coverage"] == 0


def test_data_quality_ownership_coverage_flags_missing_owner() -> None:
    row = {**BASE, "payload_json": json.dumps({"tags": {"environment": "production"}})}

    report = DataQualityValidator().validate_table("bronze_resources", [row])

    assert report.rule_counts["ownership_coverage"] == 1
    assert any(failure["rule"] == "ownership_coverage" for failure in report.failures)


def test_data_quality_tag_coverage_flags_missing_tags() -> None:
    for payload in ({"owner": "team-platform"}, {"owner": "team-platform", "tags": {}}):
        row = {**BASE, "payload_json": json.dumps(payload)}

        report = DataQualityValidator().validate_table("bronze_resources", [row])

        assert report.rule_counts["tag_coverage"] == 1, payload
        assert any(failure["rule"] == "tag_coverage" for failure in report.failures), payload


def test_data_quality_ownership_tag_coverage_only_applies_to_asset_rows() -> None:
    relationship = {
        **OPERATIONAL,
        "subject_id": BASE["resource_id"],
        "predicate": "dependsOn",
        "object_id": "/subscriptions/sub-1/resources/r2",
        "confidence": 1.0,
        "source": "test",
        "payload_json": "{}",
    }

    report = DataQualityValidator().validate_table(
        "silver_resource_relationships", [relationship]
    )

    # Relationship rows have no `entity_type`, so the asset-scoped
    # ownership/tag rule never fires -- it is not a relevant governance
    # signal for an edge, only for the assets it connects.
    assert report.rule_counts["ownership_coverage"] == 0
    assert report.rule_counts["tag_coverage"] == 0


def test_data_quality_ownership_tag_warn_mode_never_blocks() -> None:
    row = {**BASE, "payload_json": json.dumps({})}
    validator = DataQualityValidator(
        ownership_tag_thresholds={
            "mode": "warn",
            "max_missing_ownership_pct": 0,
            "max_missing_tag_pct": 0,
        }
    )

    report = validator.validate_table("bronze_resources", [row])

    assert report.rule_counts["ownership_coverage"] == 1
    assert report.rule_counts["tag_coverage"] == 1
    assert report.passed


def test_data_quality_ownership_tag_block_mode_flips_passed_over_threshold() -> None:
    row = {**BASE, "payload_json": json.dumps({})}
    validator = DataQualityValidator(
        ownership_tag_thresholds={
            "mode": "block",
            "max_missing_ownership_pct": 0,
            "max_missing_tag_pct": 0,
        }
    )

    report = validator.validate_table("bronze_resources", [row])

    assert not report.passed


def test_data_quality_ownership_tag_block_mode_within_threshold_passes() -> None:
    populated = BASE
    missing_owner = {**BASE, "payload_json": json.dumps({"tags": {"environment": "production"}})}
    validator = DataQualityValidator(
        ownership_tag_thresholds={
            "mode": "block",
            "max_missing_ownership_pct": 60,
            "max_missing_tag_pct": 60,
        }
    )

    # 1 of 2 rows missing ownership = 50%, under the 60% block threshold.
    report = validator.validate_table(
        "bronze_resources", [populated, missing_owner]
    )

    assert report.rule_counts["ownership_coverage"] == 1
    assert report.passed


def test_data_quality_from_config_loads_environment_thresholds(tmp_path) -> None:
    config_path = tmp_path / "fabric.config.yaml"
    config_path.write_text(
        """
fabric:
  data_quality:
    ownership_tag_thresholds:
      dev:
        mode: warn
        max_missing_ownership_pct: 100
        max_missing_tag_pct: 100
      prod:
        mode: block
        max_missing_ownership_pct: 5
        max_missing_tag_pct: 5
"""
    )

    dev_validator = DataQualityValidator.from_config("dev", config_path=config_path)
    prod_validator = DataQualityValidator.from_config("prod", config_path=config_path)

    row = {**BASE, "payload_json": json.dumps({})}
    dev_report = dev_validator.validate_table("bronze_resources", [row])
    prod_report = prod_validator.validate_table("bronze_resources", [row])

    assert dev_report.passed
    assert not prod_report.passed
