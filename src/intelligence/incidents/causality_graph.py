from __future__ import annotations

import hashlib
import json

from ontology.entity_builder import stable_version


class CausalityGraph:
    """Builds a bounded, referentially valid incident knowledge projection."""

    def __init__(self, *, freshness: str, max_output_items: int = 50) -> None:
        if (
            isinstance(max_output_items, bool)
            or not isinstance(max_output_items, int)
            or max_output_items < 1
        ):
            raise ValueError("Causality graph output bound must be a positive integer")
        self.freshness = freshness
        self.max_output_items = max_output_items

    def build(self, analysis):
        entities = []
        relationships = []
        for finding in analysis["findings"]:
            incident_id = f"incident:{self._digest(finding['incident']['incident_id'])}"
            entities.append(self._entity(incident_id, "Incident", finding["incident"]["title"]))
            operational_id = f"{incident_id}:finding"
            entities.append(self._entity(operational_id, "OperationalFinding", "Incident correlation finding"))
            relationships.append(self._relationship(incident_id, "hasFinding", operational_id, "Incident", "OperationalFinding"))
            blast_id = f"{incident_id}:blast"
            chain_id = f"{incident_id}:dependency"
            entities.append(self._entity(blast_id, "BlastRadius", "Incident blast radius"))
            entities.append(self._entity(chain_id, "DependencyChain", "Incident dependency chain"))
            relationships.append(self._relationship(incident_id, "hasBlastRadius", blast_id, "Incident", "BlastRadius"))
            relationships.append(self._relationship(blast_id, "hasDependencyChain", chain_id, "BlastRadius", "DependencyChain"))
            for event in finding["related_events"]:
                event_identity = f"{event.get('event_id')}|{event.get('event_type')}"
                event_id = f"{incident_id}:event:{self._digest(event_identity)}"
                entities.append(self._entity(event_id, "OperationalEvent", event["event_type"]))
                relationships.append(self._relationship(incident_id, "hasEvent", event_id, "Incident", "OperationalEvent"))
            for cause in finding["root_cause_analysis"]["probable_causes"]:
                cause_identity = (
                    f"{cause.get('evidence_id')}|{cause.get('evidence_type')}"
                )
                cause_id = f"{incident_id}:cause:{self._digest(cause_identity)}"
                entities.append(self._entity(cause_id, "RootCause", cause["summary"]))
                relationships.append(self._relationship(incident_id, "hasProbableCause", cause_id, "Incident", "RootCause"))
        for pattern in analysis["operational_patterns"]:
            pattern_id = f"risk-pattern:{self._digest(pattern['pattern_type'])}"
            entities.append(self._entity(pattern_id, "RiskPattern", pattern["pattern_type"]))
        entity_count = len(entities)
        relationship_count = len(relationships)
        entities = entities[: self.max_output_items]
        known = {row["resource_id"] for row in entities}
        relationships = [
            row
            for row in relationships
            if row["subject_id"] in known and row["object_id"] in known
        ][: self.max_output_items]
        return {
            "entities": entities,
            "relationships": relationships,
            "collection_metadata": {
                "entities": self._metadata(entity_count, len(entities)),
                "relationships": self._metadata(relationship_count, len(relationships)),
            },
            "read_only": True,
        }

    def _entity(self, identity, entity_type, name):
        row = {
            "tenant_id": "not-applicable",
            "subscription_id": "not-applicable",
            "resource_id": identity,
            "timestamp": self.freshness,
            "change_version": "",
            "ingestion_run_id": "incident-causality-projection",
            "entity_type": entity_type,
            "name": str(name)[:512],
            "resource_type": f"incident/{entity_type.casefold()}",
            "location": "",
            "payload_json": "{}",
            "lineage_json": "{}",
            "semantic_metadata_json": json.dumps({"source": "Incident Causality"}, sort_keys=True),
            "lifecycle_status": "active",
            "valid_from": self.freshness,
            "retired_at": "",
            "ontology_version": "1",
        }
        row["change_version"] = stable_version(
            {key: value for key, value in row.items() if key not in {"timestamp", "ingestion_run_id", "change_version", "valid_from"}}
        )
        return row

    def _relationship(self, subject, predicate, obj, subject_type, object_type):
        identity = f"incident-rel:{self._digest(f'{subject}|{predicate}|{obj}')}"
        row = {
            "tenant_id": "not-applicable",
            "subscription_id": "not-applicable",
            "resource_id": identity,
            "timestamp": self.freshness,
            "change_version": "",
            "ingestion_run_id": "incident-causality-projection",
            "subject_id": subject,
            "subject_type": subject_type,
            "predicate": predicate,
            "object_id": obj,
            "object_type": object_type,
            "confidence": 1.0,
            "source": "Incident Causality",
            "payload_json": "{}",
            "lineage_json": "{}",
            "lifecycle_status": "active",
            "valid_from": self.freshness,
            "retired_at": "",
            "ontology_version": "1",
        }
        row["change_version"] = stable_version(
            {key: value for key, value in row.items() if key not in {"timestamp", "ingestion_run_id", "change_version", "valid_from"}}
        )
        return row

    @staticmethod
    def _digest(value):
        return hashlib.sha256(str(value).casefold().encode()).hexdigest()[:20]

    @staticmethod
    def _metadata(count, returned):
        return {"count": count, "returned": returned, "truncated": returned < count}
