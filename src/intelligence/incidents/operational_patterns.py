from __future__ import annotations

from collections import defaultdict


class OperationalPatterns:
    """Detects recurring governed event and risk patterns."""

    def __init__(self, *, max_patterns: int = 50) -> None:
        if isinstance(max_patterns, bool) or not isinstance(max_patterns, int) or max_patterns < 1:
            raise ValueError("Pattern bound must be a positive integer")
        self.max_patterns = max_patterns

    def detect(self, events, findings):
        patterns = []
        labels = {
            "Patch Failure": "Repeated Patch Failure",
            "OS EOL Threshold Crossed": "Repeated Lifecycle Alert",
            "Ownership Change": "Ownership Change Pattern",
            "Service Degradation": "Recurring Risk",
            "Configuration Change": "Chronic Configuration Contributor",
            "Resource Modified": "Recurring Risk",
        }
        event_groups = defaultdict(set)
        for event in events:
            resource_key = str(event.get("_resource_key") or "")
            event_type = str(event.get("event_type") or "Unknown")
            event_id = str(event.get("event_id") or "")
            if resource_key and event_id:
                event_groups[(resource_key, event_type)].add(event_id)
        for (_resource_key, event_type), event_ids in event_groups.items():
            count = len(event_ids)
            if count >= 2 and event_type in labels:
                patterns.append(
                    {
                        "pattern_type": labels[event_type],
                        "occurrence_count": count,
                        "confidence": min(0.5 + count * 0.1, 0.95),
                        "evidence": [f"{count} normalized {event_type} events"],
                    }
                )
        ownership_gaps = sum(
            str(finding.get("owner") or "Unknown").casefold() == "unknown"
            for finding in findings
        )
        if ownership_gaps >= 2:
            patterns.append(
                {
                    "pattern_type": "Ownership Gap",
                    "occurrence_count": ownership_gaps,
                    "confidence": 0.8,
                    "evidence": [f"{ownership_gaps} incidents lack governed ownership"],
                }
            )
        subscription_incidents = defaultdict(set)
        resource_incidents = defaultdict(set)
        for finding in findings:
            incident_id = str((finding.get("incident") or {}).get("incident_id") or "")
            subscription_alias = str(finding.get("subscription_alias") or "Unknown")
            resource_key = str(finding.get("_resource_key") or "")
            if incident_id and subscription_alias.casefold() != "unknown":
                subscription_incidents[subscription_alias].add(incident_id)
            if incident_id and resource_key:
                resource_incidents[resource_key].add(incident_id)
        for subscription_alias, incident_ids in subscription_incidents.items():
            count = len(incident_ids)
            if count >= 2:
                patterns.append(
                    {
                        "pattern_type": "Subscription Degradation",
                        "occurrence_count": count,
                        "confidence": min(0.5 + count * 0.1, 0.95),
                        "evidence": [
                            f"{count} incidents affect governed subscription alias {subscription_alias}"
                        ],
                    }
                )
        for incident_ids in resource_incidents.values():
            count = len(incident_ids)
            if count >= 2:
                patterns.append(
                    {
                        "pattern_type": "Recurring Risk",
                        "occurrence_count": count,
                        "confidence": min(0.5 + count * 0.1, 0.95),
                        "evidence": [
                            f"{count} distinct incidents share one canonical resource"
                        ],
                    }
                )
        unique = {row["pattern_type"]: row for row in patterns}
        return sorted(
            unique.values(),
            key=lambda row: (-row["occurrence_count"], row["pattern_type"]),
        )[: self.max_patterns]
