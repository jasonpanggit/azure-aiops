from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


class ChangeIncidentCorrelator:
    def correlate(self, change: dict[str, Any], incidents: list[dict[str, Any]]) -> dict[str, Any]:
        fields = {str(item).casefold() for item in change.get("changed_fields", [])}
        category = str(change.get("category") or "").casefold()
        sensitive = bool(
            category in {"network", "identity", "security", "infrastructure as code"}
            or fields
            & {
                "publicnetworkaccess",
                "firewall",
                "roleassignments",
                "networksecuritygroup",
                "sku",
            }
        )
        if not sensitive:
            return {"incident_id": None, "contribution_score": 0, "classification": "No material incident correlation", "confidence": 0.0, "confirmed_cause": False, "evidence": ["The change did not affect a configured sensitive scope."]}
        changed = self._time(change.get("changed_at"))
        key = str(change.get("resource_key") or "").casefold().rstrip("/")
        candidates = []
        for incident in incidents:
            if str(incident.get("resource_key") or "").casefold().rstrip("/") != key:
                continue
            started = self._time(incident.get("started_at"))
            if changed is None or started is None:
                continue
            seconds = (started - changed).total_seconds()
            if 0 <= seconds <= 86400:
                score = 40 + (30 if seconds <= 3600 else 20 if seconds <= 21600 else 10)
                candidates.append((score, incident))
        if not candidates:
            return {"incident_id": None, "contribution_score": 0, "classification": "No preceding incident correlation", "confidence": 0.0, "confirmed_cause": False, "evidence": ["No incident followed this change within the configured window."]}
        score, incident = min(
            candidates,
            key=lambda item: (-item[0], str(item[1].get("incident_id") or "")),
        )
        return {"incident_id": str(incident.get("incident_id") or "Unknown"), "contribution_score": score, "classification": "Probable contributor" if score >= 60 else "Possible contributor", "confidence": min(score / 100, 0.95), "confirmed_cause": False, "evidence": ["Same canonical resource.", "Change preceded incident within 24 hours."]}

    @staticmethod
    def _time(value: Any) -> datetime | None:
        try:
            parsed = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
