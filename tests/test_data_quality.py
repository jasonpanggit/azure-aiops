from __future__ import annotations

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
    "payload_json": "{}",
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
