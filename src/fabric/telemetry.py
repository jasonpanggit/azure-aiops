from __future__ import annotations

from opentelemetry import metrics


class FabricMetrics:
    def __init__(self, meter=None) -> None:
        meter = meter or metrics.get_meter("hermes.operations_graph.fabric", "0.1.0")
        self.duration = meter.create_histogram("fabric.ingestion.duration", unit="s")
        self.rows_processed = meter.create_counter("fabric.ingestion.rows.processed")
        self.rows_added = meter.create_counter("fabric.ingestion.rows.added")
        self.rows_changed = meter.create_counter("fabric.ingestion.rows.changed")
        self.rows_removed = meter.create_counter("fabric.ingestion.rows.removed")
        self.failed_records = meter.create_counter("fabric.ingestion.records.failed")
        self.ontology_entities = meter.create_histogram("fabric.ontology.entities", unit="{entity}")
        self.ontology_relationships = meter.create_histogram(
            "fabric.ontology.relationships", unit="{relationship}"
        )
        self.ontology_orphans = meter.create_histogram("fabric.ontology.orphan_resources")
        self.ontology_missing_ownership = meter.create_histogram(
            "fabric.ontology.missing_ownership"
        )
        self.ontology_missing_tags = meter.create_histogram("fabric.ontology.missing_tags")
        self.ontology_duration = meter.create_histogram("fabric.ontology.sync.duration", unit="s")
        self.ontology_errors = meter.create_counter("fabric.ontology.sync.errors")

    def record_table(self, table: str, result) -> None:
        attributes = {"table": table}
        self.rows_processed.add(result.rows_processed, attributes)
        self.rows_added.add(result.rows_added, attributes)
        self.rows_changed.add(result.rows_changed, attributes)
        self.rows_removed.add(result.rows_removed, attributes)

    def record_run(self, duration_seconds: float, failed_records: int, status: str) -> None:
        self.duration.record(duration_seconds, {"status": status})
        if failed_records:
            self.failed_records.add(failed_records, {"status": status})

    def record_ontology(self, health: dict, duration_seconds: float, errors: int = 0) -> None:
        self.ontology_entities.record(int(health.get("entity_count") or 0))
        self.ontology_relationships.record(int(health.get("relationship_count") or 0))
        self.ontology_orphans.record(int(health.get("orphan_resources") or 0))
        self.ontology_missing_ownership.record(int(health.get("missing_ownership") or 0))
        self.ontology_missing_tags.record(int(health.get("missing_tags") or 0))
        self.ontology_duration.record(duration_seconds)
        if errors:
            self.ontology_errors.add(errors)
