from __future__ import annotations

from typing import Any, ClassVar

from .change_classifier import ChangeClassifier


class ChangeCollector:
    """Collects already-governed source projections; it never queries Azure directly."""

    SOURCE_DEFAULTS: ClassVar[dict[str, str]] = {
        "resource_changes": "Azure Resource Graph ResourceChanges",
        "policy_deviations": "Azure Policy",
        "security_deviations": "Security Baseline",
        "network_changes": "Network Change Projection",
        "identity_changes": "Identity Change Projection",
        "iac_changes": "Infrastructure as Code",
    }

    def __init__(self, classifier=None, *, max_records: int = 50000) -> None:
        self.classifier = classifier or ChangeClassifier()
        self.max_records = max_records

    def collect(self, sources: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
        rows = []
        for source_name, records in sources.items():
            if not isinstance(records, list):
                raise TypeError("Change collector sources must be lists")
            for source in records:
                row = dict(source)
                row.setdefault("source", self.SOURCE_DEFAULTS.get(source_name, source_name))
                row["category"] = self.classifier.classify(row)
                row["collector_source"] = source_name
                rows.append(row)
        if len(rows) > self.max_records:
            raise ValueError("Collected changes exceed configured bound")
        return rows
