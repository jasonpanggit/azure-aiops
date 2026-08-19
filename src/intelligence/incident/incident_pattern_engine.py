from __future__ import annotations

from collections import defaultdict
from typing import Any


class IncidentPatternEngine:
    def detect(self, findings: list[dict[str, Any]], *, max_patterns: int = 50) -> list[dict[str, Any]]:
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for finding in findings:
            resource = finding.get("resource") or {}
            resource_name = str(resource.get("name") or "Unknown")
            for cause in finding.get("probable_causes") or []:
                if cause.get("classification") == "Probable cause":
                    grouped[(resource_name, str(cause.get("evidence_type") or "Unknown"))].append(finding)
        patterns = []
        for (resource_name, pattern_type), items in grouped.items():
            incident_ids = sorted({str(item["incident"]["incident_id"]) for item in items})
            if len(incident_ids) < 2:
                continue
            resource = items[0]["resource"]
            patterns.append(
                {
                    "pattern_type": pattern_type,
                    "resource": resource,
                    "occurrence_count": len(incident_ids),
                    "incident_ids": incident_ids,
                    "business_service": items[0]["business_service"],
                    "confidence": min(0.5 + len(incident_ids) * 0.1, 0.95),
                    "evidence": f"{len(incident_ids)} incidents share probable {pattern_type} evidence for {resource_name}.",
                }
            )
        return sorted(patterns, key=lambda row: (-row["occurrence_count"], row["pattern_type"]))[:max_patterns]
