from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any


class IncidentCorrelator:
    """Selects bounded evidence in a configurable window around incidents."""

    def __init__(self, *, lookback_hours: int = 168, max_evidence_per_incident: int = 100) -> None:
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 1
            for value in (lookback_hours, max_evidence_per_incident)
        ):
            raise ValueError("Incident correlation bounds must be positive")
        self.lookback = timedelta(hours=lookback_hours)
        self.max_evidence = max_evidence_per_incident

    def correlate(
        self,
        incident: dict[str, Any],
        evidence: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        incident_at = self._time(incident.get("started_at"))
        key = str(incident.get("resource_key") or "").casefold()
        matched = []
        for row in evidence:
            if str(row.get("resource_key") or "").casefold() != key:
                continue
            observed = self._time(row.get("observed_at"))
            if incident_at is None or observed is None:
                continue
            if incident_at - self.lookback <= observed <= incident_at + timedelta(hours=1):
                matched.append(dict(row))
        return sorted(
            matched,
            key=lambda row: (str(row.get("observed_at") or ""), str(row.get("evidence_id") or "")),
            reverse=True,
        )[: self.max_evidence]

    @staticmethod
    def _time(value: Any) -> datetime | None:
        try:
            parsed = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
