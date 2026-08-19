from __future__ import annotations

from collections import Counter

from .change_incident_correlator import ChangeIncidentCorrelator


class ChangeCorrelator(ChangeIncidentCorrelator):
    """Adds portfolio pattern summaries to probabilistic incident correlation."""

    @staticmethod
    def patterns(findings):
        categories = Counter(
            finding["change"]["category"]
            for finding in findings
            if finding["incident_correlation"]["incident_id"]
        )
        return [
            {"category": category, "incident_following_change_count": count}
            for category, count in sorted(
                categories.items(), key=lambda item: (-item[1], item[0])
            )
        ]
