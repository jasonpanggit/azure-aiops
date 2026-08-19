from __future__ import annotations

from typing import Any


class ImpactAnalyzer:
    def __init__(self, semantic_engine, *, max_results: int = 50) -> None:
        if (
            isinstance(max_results, bool)
            or not isinstance(max_results, int)
            or max_results < 1
        ):
            raise ValueError("Impact result limit must be positive")
        self.semantic = semantic_engine
        self.max_results = max_results

    def analyze(self, subject: str, *, subject_type: str = "") -> dict[str, Any]:
        impact = self.semantic.get_impact_context(subject, subject_type=subject_type)
        if not isinstance(impact, dict):
            raise TypeError("Operational impact context must be a mapping")
        for key in (
            "impacted_applications",
            "impacted_business_services",
            "impacted_services",
        ):
            rows = impact.get(key, [])
            if not isinstance(rows, list) or any(
                not isinstance(item, dict) for item in rows
            ):
                raise TypeError(f"Operational {key} must be a list of mappings")
        upstream: dict[tuple[str, str], dict[str, Any]] = {}
        downstream: dict[tuple[str, str], dict[str, Any]] = {}
        dependency_truncated = False
        for application in impact.get("impacted_applications", []):
            application_context = self.semantic.get_application_context(
                str(application.get("name") or "")
            )
            sections = application_context.get("sections") or {}
            metadata = application_context.get("section_metadata") or {}
            dependency_truncated = dependency_truncated or bool(
                (metadata.get("upstream_dependencies") or {}).get("truncated")
                or (metadata.get("downstream_dependents") or {}).get("truncated")
            )
            for row in sections.get("upstream_dependencies") or []:
                upstream[(str(row.get("entity_type")), str(row.get("name")))] = row
            for row in sections.get("downstream_dependents") or []:
                downstream[(str(row.get("entity_type")), str(row.get("name")))] = row
        risk_context = self.semantic.get_risk_context(
            subject, subject_type=subject_type
        )
        if not isinstance(risk_context, dict):
            raise TypeError("Operational risk context must be a mapping")
        risk = risk_context.get("risk") or {}
        if not isinstance(risk, dict):
            raise TypeError("Operational risk must be a mapping")
        upstream_keys = sorted(upstream)
        downstream_keys = sorted(downstream)
        dependency_truncated = dependency_truncated or (
            len(upstream_keys) > self.max_results
            or len(downstream_keys) > self.max_results
        )
        evidence = dict(impact.get("collection_metadata", {}))
        evidence["dependencies"] = {
            "upstream_returned": min(len(upstream_keys), self.max_results),
            "downstream_returned": min(len(downstream_keys), self.max_results),
            "truncated": dependency_truncated,
        }
        return {
            "subject": impact.get("root", {}),
            "impacted_applications": impact.get("impacted_applications", []),
            "impacted_business_services": impact.get(
                "impacted_business_services", []
            ),
            "impacted_services": impact.get("impacted_services", []),
            "blast_radius": impact.get("blast_radius", {}),
            "dependency_tree": impact.get("tree", {}),
            "upstream_dependencies": [
                upstream[key] for key in upstream_keys[: self.max_results]
            ],
            "downstream_dependencies": [
                downstream[key] for key in downstream_keys[: self.max_results]
            ],
            "criticality": {
                "risk_level": str(risk.get("level") or "Unknown"),
                "criticality_points": int(
                    (risk.get("factors") or {}).get("resource_criticality") or 0
                ),
            },
            "truncated": bool(impact.get("truncated")) or dependency_truncated,
            "evidence": evidence,
            "data_sources": ["Semantic Knowledge Layer", "Fabric Ontology relationships"],
            "freshness": impact.get("freshness", ""),
            "knowledge_version": impact.get("knowledge_version", ""),
        }
