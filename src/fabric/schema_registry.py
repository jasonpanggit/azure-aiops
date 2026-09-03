from __future__ import annotations

import pyarrow as pa

from fabric_pipelines.topology_fabric_contracts import (
    TOPOLOGY_EDGES_CONTRACT,
    TOPOLOGY_ENTITIES_CONTRACT,
)

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

_TOPOLOGY_ENTITY = [
    *_BASE,
    *[
        field
        for field in TOPOLOGY_ENTITIES_CONTRACT.schema
        if field.name not in {"tenant_id", "subscription_id"}
    ],
]

_TOPOLOGY_EDGE = [
    *_BASE,
    *list(TOPOLOGY_EDGES_CONTRACT.schema),
]

SCHEMAS: dict[str, pa.Schema] = {
    "assessment_change_findings": pa.schema(
        [
            *_BASE,
            pa.field("change_id", pa.string(), nullable=False),
            pa.field("resource_name", pa.string(), nullable=False),
            pa.field("change_type", pa.string(), nullable=False),
            pa.field("category", pa.string(), nullable=False),
            pa.field("authorized", pa.bool_(), nullable=True),
            pa.field("risk_score", pa.int64(), nullable=False),
            pa.field("risk_level", pa.string(), nullable=False),
            pa.field("compliance_score", pa.int64(), nullable=False),
            pa.field("configuration_drifted", pa.bool_(), nullable=True),
            pa.field("drift_fields", pa.list_(pa.string()), nullable=False),
            pa.field("incident_id", pa.string(), nullable=False),
            pa.field("incident_contribution_score", pa.int64(), nullable=False),
            pa.field("application", pa.string(), nullable=False),
            pa.field("business_service", pa.string(), nullable=False),
            pa.field("confirmed_cause", pa.bool_(), nullable=False),
            pa.field("source", pa.string(), nullable=False),
        ]
    ),
    "bronze_resources": pa.schema(_ASSET),
    "bronze_subscriptions": pa.schema(_ENTITY),
    "bronze_resourcegroups": pa.schema(_ENTITY),
    "bronze_advisor": pa.schema(_ENTITY),
    "bronze_cost_actuals": pa.schema(
        [
            *_ENTITY,
            pa.field("usage_date", pa.string(), nullable=False),
            pa.field("cost", pa.float64(), nullable=False),
            pa.field("currency", pa.string(), nullable=False),
            pa.field("target_resource_id", pa.string(), nullable=False),
            pa.field("resource_group", pa.string(), nullable=False),
            pa.field("service_name", pa.string(), nullable=False),
            pa.field("billing_period_start", pa.string(), nullable=False),
            pa.field("billing_period_end", pa.string(), nullable=False),
        ]
    ),
    "bronze_patchassessment": pa.schema(_ENTITY),
    "bronze_patchassessmentdetail": pa.schema(_ENTITY),
    "bronze_patchinstallation": pa.schema(_ENTITY),
    "bronze_defender_assessments": pa.schema(_ENTITY),
    "bronze_defender_findings": pa.schema(_ENTITY),
    "bronze_container_image_exposure": pa.schema(_ENTITY),
    "bronze_defender_alerts": pa.schema(_ENTITY),
    "bronze_defender_attack_paths": pa.schema(_ENTITY),
    "bronze_defender_attack_path_nodes": pa.schema(_ENTITY),
    "bronze_defender_attack_path_connections": pa.schema(_ENTITY),
    "bronze_defender_secure_scores": pa.schema(_ENTITY),
    "bronze_defender_secure_score_controls": pa.schema(_ENTITY),
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
    "topology_entities": pa.schema(_TOPOLOGY_ENTITY),
    "topology_edges": pa.schema(_TOPOLOGY_EDGE),
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
    "silver_cost_actuals": pa.schema(
        [
            *_ENTITY,
            pa.field("usage_date", pa.string(), nullable=False),
            pa.field("cost", pa.float64(), nullable=False),
            pa.field("currency", pa.string(), nullable=False),
            pa.field("target_resource_id", pa.string(), nullable=False),
            pa.field("resource_group", pa.string(), nullable=False),
            pa.field("service_name", pa.string(), nullable=False),
            pa.field("billing_period_start", pa.string(), nullable=False),
            pa.field("billing_period_end", pa.string(), nullable=False),
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
    "silver_defender_findings": pa.schema(
        [
            *_ENTITY,
            pa.field("target_resource_id", pa.string(), nullable=False),
            pa.field("assessment_id", pa.string(), nullable=False),
            pa.field("cve_id", pa.string(), nullable=False),
            pa.field("severity", pa.string(), nullable=False),
            pa.field("status", pa.string(), nullable=False),
            pa.field("recommendation", pa.string(), nullable=False),
            pa.field("description", pa.string(), nullable=False),
            pa.field("last_assessed_at", pa.string(), nullable=False),
            pa.field("patchable", pa.bool_(), nullable=False),
            pa.field("software_vendor", pa.string(), nullable=False),
            pa.field("software_name", pa.string(), nullable=False),
            pa.field("software_version", pa.string(), nullable=False),
            pa.field("fixed_version", pa.string(), nullable=False),
        ]
    ),
    "silver_defender_assessments": pa.schema(
        [
            *_ENTITY,
            pa.field("target_resource_id", pa.string(), nullable=False),
            pa.field("target_resource_type", pa.string(), nullable=False),
            pa.field("status", pa.string(), nullable=False),
            pa.field("severity", pa.string(), nullable=False),
            pa.field("recommendation", pa.string(), nullable=False),
            pa.field("description", pa.string(), nullable=False),
            pa.field("remediation", pa.string(), nullable=False),
            pa.field("last_assessed_at", pa.string(), nullable=False),
        ]
    ),
    "silver_container_image_exposure": pa.schema(
        [
            *_ENTITY,
            pa.field("target_resource_id", pa.string(), nullable=False),
            pa.field("registry_resource_id", pa.string(), nullable=False),
            pa.field("registry_host", pa.string(), nullable=False),
            pa.field("repository", pa.string(), nullable=False),
            pa.field("image_digest", pa.string(), nullable=False),
            pa.field("image_tags", pa.list_(pa.string()), nullable=False),
            pa.field("image_uri", pa.string(), nullable=False),
            pa.field("last_pushed_at", pa.string(), nullable=False),
            pa.field("status", pa.string(), nullable=False),
            pa.field("severity", pa.string(), nullable=False),
            pa.field("critical_count", pa.int64(), nullable=False),
            pa.field("high_count", pa.int64(), nullable=False),
            pa.field("vulnerable_package_count", pa.int64(), nullable=False),
            pa.field("cve_count", pa.int64(), nullable=False),
            pa.field("cve_ids", pa.list_(pa.string()), nullable=False),
            pa.field("vulnerable_packages", pa.list_(pa.string()), nullable=False),
            pa.field("recommendation", pa.string(), nullable=False),
            pa.field("last_assessed_at", pa.string(), nullable=False),
        ]
    ),
    "silver_defender_alerts": pa.schema(_ENTITY),
    "silver_defender_attack_paths": pa.schema(_ENTITY),
    "silver_defender_attack_path_nodes": pa.schema(_ENTITY),
    "silver_defender_attack_path_connections": pa.schema(_ENTITY),
    "silver_defender_secure_scores": pa.schema(_ENTITY),
    "silver_defender_secure_score_controls": pa.schema(_ENTITY),
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
    "silver_situations": pa.schema(
        [
            *_BASE,
            pa.field("situation_id", pa.string(), nullable=False),
            pa.field("title", pa.string(), nullable=False),
            pa.field("situation_type", pa.string(), nullable=False),
            pa.field("lifecycle_state", pa.string(), nullable=False),
            pa.field("severity", pa.string(), nullable=False),
            pa.field("priority", pa.string(), nullable=False),
            pa.field("scope_json", pa.string(), nullable=False),
            pa.field("owner", pa.string(), nullable=False),
            pa.field("support_team", pa.string(), nullable=False),
            pa.field("affected_resource_ids_json", pa.string(), nullable=False),
            pa.field("linked_evidence_ids_json", pa.string(), nullable=False),
            pa.field("started_at", pa.string(), nullable=False),
            pa.field("last_observed_at", pa.string(), nullable=False),
            pa.field("evidence_state", pa.string(), nullable=False),
            pa.field("warnings_json", pa.string(), nullable=False),
            pa.field("contradiction_ids_json", pa.string(), nullable=False),
            pa.field("unknowns_json", pa.string(), nullable=False),
        ]
    ),
    "silver_situation_evidence": pa.schema(
        [
            *_BASE,
            pa.field("evidence_id", pa.string(), nullable=False),
            pa.field("situation_id", pa.string(), nullable=False),
            pa.field("source_family", pa.string(), nullable=False),
            pa.field("source_object_id", pa.string(), nullable=False),
            pa.field("locator", pa.string(), nullable=False),
            pa.field("resource_ids_json", pa.string(), nullable=False),
            pa.field("observed_at", pa.string(), nullable=False),
            pa.field("ingested_at", pa.string(), nullable=False),
            pa.field("watermark", pa.string(), nullable=False),
            pa.field("ingestion_status", pa.string(), nullable=False),
            pa.field("provenance_json", pa.string(), nullable=False),
            pa.field("freshness", pa.string(), nullable=False),
            pa.field("quality", pa.string(), nullable=False),
            pa.field("availability", pa.string(), nullable=False),
            pa.field("confidence", pa.float64(), nullable=False),
            pa.field("assertion", pa.string(), nullable=False),
            pa.field("fingerprint", pa.string(), nullable=False),
        ]
    ),
    "silver_situation_links": pa.schema(
        [
            *_BASE,
            pa.field("link_id", pa.string(), nullable=False),
            pa.field("situation_id", pa.string(), nullable=False),
            pa.field("entity_type", pa.string(), nullable=False),
            pa.field("entity_id", pa.string(), nullable=False),
            pa.field("relation", pa.string(), nullable=False),
            pa.field("quality", pa.string(), nullable=False),
            pa.field("provenance_json", pa.string(), nullable=False),
        ]
    ),
    "metadata_audit_events": pa.schema(
        [
            *_BASE,
            pa.field("event_id", pa.string(), nullable=False),
            pa.field("actor", pa.string(), nullable=False),
            pa.field("action", pa.string(), nullable=False),
            pa.field("scope_snapshot_json", pa.string(), nullable=False),
            pa.field("event_timestamp", pa.string(), nullable=False),
            pa.field("situation_id", pa.string(), nullable=False),
            pa.field("evidence_ids_json", pa.string(), nullable=False),
            pa.field("source_references_json", pa.string(), nullable=False),
        ]
    ),
    "metadata_source_status": pa.schema(
        [
            *_BASE,
            pa.field("source_family", pa.string(), nullable=False),
            pa.field("status", pa.string(), nullable=False),
            pa.field("observed_at", pa.string(), nullable=False),
            pa.field("ingested_at", pa.string(), nullable=False),
            pa.field("watermark", pa.string(), nullable=False),
            pa.field("query_version", pa.string(), nullable=False),
            pa.field("requested_scope_json", pa.string(), nullable=False),
            pa.field("provider_status", pa.string(), nullable=False),
            pa.field("freshness", pa.string(), nullable=False),
            pa.field("availability", pa.string(), nullable=False),
            pa.field("quality", pa.string(), nullable=False),
            pa.field("error", pa.string(), nullable=False),
            # MED-03: dataset-agnostic health provider
            # (`src/fabric/medallion_health.py::dataset_status`) needs the
            # underlying table's row-count and lineage evidence alongside
            # the existing sync-attempt status columns above -- extending
            # this table rather than creating a second status table.
            pa.field("row_count", pa.int64(), nullable=True),
            pa.field("lineage_ref", pa.string(), nullable=True),
        ]
    ),
    # MED-09: publication manifest -- the lifecycle-disposition
    # (active/dormant/retired) registry for generated ontology
    # projections (`ontology.publication_manifest.PublicationManifestStore`).
    # This is intentionally NOT an extension of the existing per-connection
    # snapshot manifest (`manifest.json`, read by
    # `api/runtime.py::_load_snapshot_tables()`) -- structurally distinct
    # table, distinct keys, distinct concept. See 10-RESEARCH.md's Pitfall #4.
    "metadata_publication_manifest": pa.schema(
        [
            *_BASE,
            pa.field("projection_name", pa.string(), nullable=False),
            pa.field("disposition", pa.string(), nullable=False),
            pa.field("compatibility_version", pa.string(), nullable=True),
            pa.field("retired_reason", pa.string(), nullable=True),
            pa.field("registered_at", pa.string(), nullable=False),
            pa.field("updated_at", pa.string(), nullable=False),
        ]
    ),
}


def schema_for(table_name: str) -> pa.Schema:
    if table_name.startswith("ontology_rel_"):
        return pa.schema(_ONTOLOGY_RELATIONSHIP)
    if table_name.startswith("ontology_") and table_name.endswith("_entities"):
        return pa.schema(_ONTOLOGY_ENTITY)
    try:
        from intelligence.inventory.fabric_contracts import (
            INVENTORY_FABRIC_SCHEMAS_BY_TABLE,
        )

        return INVENTORY_FABRIC_SCHEMAS_BY_TABLE[table_name]
    except KeyError:
        pass
    try:
        return SCHEMAS[table_name]
    except KeyError as exc:
        raise KeyError(f"No versioned schema for table: {table_name}") from exc
