from __future__ import annotations

import pyarrow as pa

SCHEMA_VERSION = "2.0.0"

_BASE = [
    pa.field("tenant_id", pa.string(), nullable=False),
    pa.field("subscription_id", pa.string(), nullable=False),
    pa.field("resource_id", pa.string(), nullable=False),
    pa.field("timestamp", pa.string(), nullable=False),
    pa.field("change_version", pa.string(), nullable=False),
    pa.field("ingestion_run_id", pa.string(), nullable=False),
]

_ENTITY = [
    *_BASE,
    pa.field("entity_type", pa.string(), nullable=False),
    pa.field("name", pa.string(), nullable=False),
    pa.field("resource_type", pa.string(), nullable=False),
    pa.field("location", pa.string(), nullable=False),
    pa.field("payload_json", pa.string(), nullable=False),
]

_ASSET = [
    *_ENTITY,
    pa.field("resource_group", pa.string(), nullable=False),
    pa.field("status", pa.string(), nullable=False),
    pa.field("os_name", pa.string(), nullable=False),
    pa.field("os_version", pa.string(), nullable=False),
    pa.field("vm_size", pa.string(), nullable=False),
]

_RELATIONSHIP = [
    *_BASE,
    pa.field("subject_id", pa.string(), nullable=False),
    pa.field("predicate", pa.string(), nullable=False),
    pa.field("object_id", pa.string(), nullable=False),
    pa.field("confidence", pa.float64(), nullable=False),
    pa.field("source", pa.string(), nullable=False),
    pa.field("payload_json", pa.string(), nullable=False),
]

_ONTOLOGY_ENTITY = [
    *_ENTITY,
    pa.field("lineage_json", pa.string(), nullable=False),
    pa.field("semantic_metadata_json", pa.string(), nullable=False),
    pa.field("lifecycle_status", pa.string(), nullable=False),
    pa.field("valid_from", pa.string(), nullable=False),
    pa.field("retired_at", pa.string(), nullable=False),
    pa.field("ontology_version", pa.string(), nullable=False),
]

_ONTOLOGY_RELATIONSHIP = [
    *_BASE,
    pa.field("subject_id", pa.string(), nullable=False),
    pa.field("subject_type", pa.string(), nullable=False),
    pa.field("predicate", pa.string(), nullable=False),
    pa.field("object_id", pa.string(), nullable=False),
    pa.field("object_type", pa.string(), nullable=False),
    pa.field("confidence", pa.float64(), nullable=False),
    pa.field("source", pa.string(), nullable=False),
    pa.field("payload_json", pa.string(), nullable=False),
    pa.field("lineage_json", pa.string(), nullable=False),
    pa.field("lifecycle_status", pa.string(), nullable=False),
    pa.field("valid_from", pa.string(), nullable=False),
    pa.field("retired_at", pa.string(), nullable=False),
    pa.field("ontology_version", pa.string(), nullable=False),
]

SCHEMAS: dict[str, pa.Schema] = {
    "bronze_resources": pa.schema(_ASSET),
    "bronze_subscriptions": pa.schema(_ENTITY),
    "bronze_resourcegroups": pa.schema(_ENTITY),
    "bronze_advisor": pa.schema(_ENTITY),
    "bronze_patchassessment": pa.schema(_ENTITY),
    "bronze_patchassessmentdetail": pa.schema(_ENTITY),
    "bronze_patchinstallation": pa.schema(_ENTITY),
    "bronze_resource_changes": pa.schema(
        [
            *_BASE,
            pa.field("target_resource_id", pa.string(), nullable=False),
            pa.field("change_type", pa.string(), nullable=False),
            pa.field("payload_json", pa.string(), nullable=False),
        ]
    ),
    "silver_vm_inventory": pa.schema(_ASSET),
    "silver_server_inventory": pa.schema(_ASSET),
    "silver_compliance": pa.schema(
        [
            *_ENTITY,
            pa.field("assessed_resource_id", pa.string(), nullable=False),
            pa.field("status", pa.string(), nullable=False),
            pa.field("last_modified", pa.string(), nullable=False),
            pa.field("available_updates", pa.int64(), nullable=False),
            pa.field("missing_critical_updates", pa.int64(), nullable=False),
            pa.field("missing_security_updates", pa.int64(), nullable=False),
        ]
    ),
    "silver_patch_installations": pa.schema(
        [
            *_ENTITY,
            pa.field("target_resource_id", pa.string(), nullable=False),
            pa.field("update_id", pa.string(), nullable=False),
            pa.field("update_name", pa.string(), nullable=False),
            pa.field("category", pa.string(), nullable=False),
            pa.field("severity", pa.string(), nullable=False),
            pa.field("status", pa.string(), nullable=False),
            pa.field("published_at", pa.string(), nullable=False),
            pa.field("installed_at", pa.string(), nullable=False),
            pa.field("error", pa.string(), nullable=False),
        ]
    ),
    "silver_patch_history": pa.schema(
        [
            *_ENTITY,
            pa.field("assessed_resource_id", pa.string(), nullable=False),
            pa.field("status", pa.string(), nullable=False),
            pa.field("last_modified", pa.string(), nullable=False),
            pa.field("available_updates", pa.int64(), nullable=False),
            pa.field("missing_critical_updates", pa.int64(), nullable=False),
            pa.field("missing_security_updates", pa.int64(), nullable=False),
        ]
    ),
    "silver_patch_findings": pa.schema(
        [
            *_ENTITY,
            pa.field("target_resource_id", pa.string(), nullable=False),
            pa.field("kb_id", pa.string(), nullable=False),
            pa.field("update_name", pa.string(), nullable=False),
            pa.field("category", pa.string(), nullable=False),
            pa.field("severity", pa.string(), nullable=False),
            pa.field("status", pa.string(), nullable=False),
            pa.field("published_at", pa.string(), nullable=False),
            pa.field("last_modified", pa.string(), nullable=False),
        ]
    ),
    "silver_patch_policies": pa.schema(
        [
            *_BASE,
            pa.field("name", pa.string(), nullable=False),
            pa.field("environment", pa.string(), nullable=False),
            pa.field("max_patch_age_days", pa.int64(), nullable=False),
            pa.field("minimum_compliance_score", pa.int64(), nullable=False),
        ]
    ),
    "metadata_lifecycle_catalog": pa.schema(
        [
            *_BASE,
            pa.field("product", pa.string(), nullable=False),
            pa.field("version", pa.string(), nullable=False),
            pa.field("release_date", pa.string(), nullable=False),
            pa.field("mainstream_support_end", pa.string(), nullable=False),
            pa.field("extended_support_end", pa.string(), nullable=False),
            pa.field("last_update_date", pa.string(), nullable=False),
            pa.field("recommended_upgrade_path", pa.string(), nullable=False),
            pa.field("source_url", pa.string(), nullable=False),
            pa.field("notes", pa.string(), nullable=False),
            pa.field("default_support_channel", pa.string(), nullable=False),
        ]
    ),
    "silver_lifecycle_history": pa.schema(
        [
            *_BASE,
            pa.field("resource_key", pa.string(), nullable=False),
            pa.field("observed_at", pa.string(), nullable=False),
            pa.field("lifecycle_status", pa.string(), nullable=False),
            pa.field("risk_score", pa.int64(), nullable=False),
            pa.field("modernization_state", pa.string(), nullable=False),
        ]
    ),
    "silver_incidents": pa.schema(
        [
            *_BASE,
            pa.field("incident_id", pa.string(), nullable=False),
            pa.field("title", pa.string(), nullable=False),
            pa.field("status", pa.string(), nullable=False),
            pa.field("severity", pa.string(), nullable=False),
            pa.field("started_at", pa.string(), nullable=False),
            pa.field("target_resource_id", pa.string(), nullable=False),
        ]
    ),
    "silver_alerts": pa.schema(
        [
            *_BASE,
            pa.field("alert_id", pa.string(), nullable=False),
            pa.field("title", pa.string(), nullable=False),
            pa.field("severity", pa.string(), nullable=False),
            pa.field("fired_at", pa.string(), nullable=False),
            pa.field("target_resource_id", pa.string(), nullable=False),
            pa.field("signal", pa.string(), nullable=False),
        ]
    ),
    "silver_incident_history": pa.schema(
        [
            *_BASE,
            pa.field("incident_id", pa.string(), nullable=False),
            pa.field("observed_at", pa.string(), nullable=False),
            pa.field("status", pa.string(), nullable=False),
            pa.field("severity", pa.string(), nullable=False),
            pa.field("target_resource_id", pa.string(), nullable=False),
        ]
    ),
    "silver_policy_deviations": pa.schema(
        [*_BASE, pa.field("deviation_id", pa.string(), nullable=False), pa.field("target_resource_id", pa.string(), nullable=False), pa.field("observed_at", pa.string(), nullable=False), pa.field("severity", pa.string(), nullable=False), pa.field("control", pa.string(), nullable=False), pa.field("status", pa.string(), nullable=False)]
    ),
    "silver_security_deviations": pa.schema(
        [*_BASE, pa.field("deviation_id", pa.string(), nullable=False), pa.field("target_resource_id", pa.string(), nullable=False), pa.field("observed_at", pa.string(), nullable=False), pa.field("severity", pa.string(), nullable=False), pa.field("control", pa.string(), nullable=False), pa.field("status", pa.string(), nullable=False)]
    ),
    "silver_network_changes": pa.schema(
        [*_BASE, pa.field("change_id", pa.string(), nullable=False), pa.field("target_resource_id", pa.string(), nullable=False), pa.field("changed_at", pa.string(), nullable=False), pa.field("severity", pa.string(), nullable=False), pa.field("changed_by", pa.string(), nullable=False), pa.field("summary", pa.string(), nullable=False)]
    ),
    "silver_identity_changes": pa.schema(
        [*_BASE, pa.field("change_id", pa.string(), nullable=False), pa.field("target_resource_id", pa.string(), nullable=False), pa.field("changed_at", pa.string(), nullable=False), pa.field("severity", pa.string(), nullable=False), pa.field("changed_by", pa.string(), nullable=False), pa.field("summary", pa.string(), nullable=False)]
    ),
    "silver_iac_changes": pa.schema(
        [*_BASE, pa.field("change_id", pa.string(), nullable=False), pa.field("target_resource_id", pa.string(), nullable=False), pa.field("changed_at", pa.string(), nullable=False), pa.field("severity", pa.string(), nullable=False), pa.field("changed_by", pa.string(), nullable=False), pa.field("source", pa.string(), nullable=False), pa.field("summary", pa.string(), nullable=False)]
    ),
    "silver_expected_configurations": pa.schema(
        [*_BASE, pa.field("target_resource_id", pa.string(), nullable=False), pa.field("configuration_json", pa.string(), nullable=False)]
    ),
    "silver_observed_configurations": pa.schema(
        [*_BASE, pa.field("target_resource_id", pa.string(), nullable=False), pa.field("configuration_json", pa.string(), nullable=False)]
    ),
    "silver_predictive_history": pa.schema(
        [*_BASE, pa.field("target_resource_id", pa.string(), nullable=False), pa.field("observed_at", pa.string(), nullable=False), pa.field("patch_debt", pa.int64(), nullable=False), pa.field("lifecycle_risk_score", pa.int64(), nullable=False), pa.field("incident_count_30d", pa.int64(), nullable=False), pa.field("configuration_drift_count", pa.int64(), nullable=False), pa.field("risk_score", pa.int64(), nullable=False), pa.field("ownership_coverage_score", pa.int64(), nullable=True), pa.field("security_debt_score", pa.int64(), nullable=True)]
    ),
    "silver_remediation_action_catalog": pa.schema(
        [*_BASE, pa.field("action_id", pa.string(), nullable=False), pa.field("title", pa.string(), nullable=False), pa.field("opportunity_type", pa.string(), nullable=False), pa.field("trigger_json", pa.string(), nullable=False), pa.field("execution_steps_json", pa.string(), nullable=False), pa.field("preconditions_json", pa.string(), nullable=False), pa.field("rollback_actions_json", pa.string(), nullable=False), pa.field("success_criteria_json", pa.string(), nullable=False), pa.field("failure_criteria_json", pa.string(), nullable=False), pa.field("deployment_stages_json", pa.string(), nullable=False), pa.field("effectiveness_json", pa.string(), nullable=False)]
    ),
    "silver_remediation_approval_policies": pa.schema(
        [*_BASE, pa.field("policy_id", pa.string(), nullable=False), pa.field("conditions_json", pa.string(), nullable=False), pa.field("roles_json", pa.string(), nullable=False)]
    ),
    "silver_resource_relationships": pa.schema(_RELATIONSHIP),
    "ontology_entities": pa.schema(_ONTOLOGY_ENTITY),
    "ontology_relationships": pa.schema(_ONTOLOGY_RELATIONSHIP),
    "ontology_application_context": pa.schema(_ONTOLOGY_ENTITY),
    "ontology_infrastructure_context": pa.schema(_ONTOLOGY_ENTITY),
    "ontology_subscription_context": pa.schema(_ONTOLOGY_ENTITY),
    "ontology_compliance_context": pa.schema(_ONTOLOGY_ENTITY),
    "ontology_business_context": pa.schema(_ONTOLOGY_ENTITY),
    "ontology_health": pa.schema(
        [
            *_BASE,
            pa.field("entity_count", pa.int64(), nullable=False),
            pa.field("relationship_count", pa.int64(), nullable=False),
            pa.field("orphan_resources", pa.int64(), nullable=False),
            pa.field("missing_ownership", pa.int64(), nullable=False),
            pa.field("missing_tags", pa.int64(), nullable=False),
            pa.field("synchronization_errors", pa.int64(), nullable=False),
        ]
    ),
    "ontology_quality_report": pa.schema(
        [
            *_BASE,
            pa.field("passed", pa.bool_(), nullable=False),
            pa.field("report_json", pa.string(), nullable=False),
        ]
    ),
    "metadata_ingestion_state": pa.schema(
        [
            *_BASE,
            pa.field("status", pa.string(), nullable=False),
            pa.field("source_run_id", pa.string(), nullable=False),
            pa.field("failed_records", pa.int64(), nullable=False),
            pa.field("rows_processed", pa.int64(), nullable=False),
            pa.field("rows_added", pa.int64(), nullable=False),
            pa.field("rows_changed", pa.int64(), nullable=False),
            pa.field("rows_removed", pa.int64(), nullable=False),
            pa.field("watermark", pa.string(), nullable=False),
            pa.field("error", pa.string(), nullable=False),
            pa.field("replay", pa.bool_(), nullable=False),
        ]
    ),
    "metadata_quality_reports": pa.schema(
        [
            *_BASE,
            pa.field("source_run_id", pa.string(), nullable=False),
            pa.field("passed", pa.bool_(), nullable=False),
            pa.field("failed_records", pa.int64(), nullable=False),
            pa.field("report_json", pa.string(), nullable=False),
        ]
    ),
}


def schema_for(table_name: str) -> pa.Schema:
    if table_name.startswith("ontology_rel_"):
        return pa.schema(_ONTOLOGY_RELATIONSHIP)
    if table_name.startswith("ontology_") and table_name.endswith("_entities"):
        return pa.schema(_ONTOLOGY_ENTITY)
    try:
        return SCHEMAS[table_name]
    except KeyError as exc:
        raise KeyError(f"No versioned schema for table: {table_name}") from exc
