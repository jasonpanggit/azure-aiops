from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar


class CausalityEngine:
    """Deterministic evidence-strength model; it never asserts confirmed causation."""

    RELEVANCE: ClassVar[dict[str, int]] = {
        "Resource Change": 20,
        "Patch Failure": 18,
        "Alert": 15,
        "Lifecycle Risk": 8,
    }
    SEVERITY: ClassVar[dict[str, int]] = {
        "critical": 20,
        "high": 15,
        "medium": 10,
        "moderate": 10,
        "low": 5,
    }

    def score(
        self,
        incident: dict[str, Any],
        evidence: dict[str, Any],
        *,
        now: datetime,
    ) -> dict[str, Any]:
        incident_at = self._time(incident.get("started_at"))
        evidence_at = self._time(evidence.get("observed_at"))
        current = now if now.tzinfo else now.replace(tzinfo=UTC)
        target_match = 35 if str(incident.get("resource_key") or "").casefold() == str(evidence.get("resource_key") or "").casefold() else 0
        temporal, precedes = self._temporal(incident_at, evidence_at, current)
        signal_strength = self.SEVERITY.get(str(evidence.get("severity") or "").casefold(), 5)
        evidence_type = str(evidence.get("evidence_type") or "Unknown")
        causal_relevance = self.RELEVANCE.get(evidence_type, 0) if precedes else 0
        factors = {
            "target_match": target_match,
            "temporal_proximity": temporal,
            "signal_strength": signal_strength,
            "causal_relevance": causal_relevance,
        }
        score = min(sum(factors.values()), 100)
        causal_eligible = bool(evidence.get("causal_eligible", True)) and precedes
        if not causal_eligible:
            score = min(score, 34)
        classification = (
            "Probable cause" if score >= 60 else "Contributing factor" if score >= 35 else "Contextual evidence"
        )
        evidence_summary = [
            f"{name.replace('_', ' ')} +{points}"
            for name, points in factors.items()
            if points
        ]
        if not precedes:
            evidence_summary.append("Evidence occurred after incident start and cannot establish a preceding cause.")
        return {
            "evidence_id": str(evidence.get("evidence_id") or "Unknown"),
            "evidence_type": evidence_type,
            "summary": str(evidence.get("summary") or "Unknown"),
            "observed_at": str(evidence.get("observed_at") or ""),
            "causal_score": score,
            "classification": classification,
            "conclusion": classification,
            "confidence": min(round(score / 100, 2), 0.95),
            "precedes_incident": precedes,
            "causal_eligible": causal_eligible,
            "factors": factors,
            "evidence": evidence_summary or ["No causal factors were confirmed."],
        }

    @staticmethod
    def _time(value: Any) -> datetime | None:
        try:
            parsed = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)

    @staticmethod
    def _temporal(
        incident_at: datetime | None,
        evidence_at: datetime | None,
        now: datetime,
    ) -> tuple[int, bool]:
        if incident_at is None or evidence_at is None or evidence_at > now:
            return 0, False
        seconds = (incident_at - evidence_at).total_seconds()
        if seconds < 0:
            return 0, False
        if seconds <= 3600:
            return 25, True
        if seconds <= 6 * 3600:
            return 20, True
        if seconds <= 24 * 3600:
            return 10, True
        if seconds <= 7 * 24 * 3600:
            return 3, True
        return 0, True
