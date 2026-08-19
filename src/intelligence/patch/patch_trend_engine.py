from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any


class PatchTrendEngine:
    """Computes bounded 7/30/90-day patch, compliance, and risk trends."""

    WINDOWS = (7, 30, 90)

    def calculate(
        self, history: list[dict[str, Any]], *, now: datetime
    ) -> dict[str, Any]:
        if not isinstance(history, list) or any(not isinstance(row, dict) for row in history):
            raise TypeError("Patch history must be a list of mappings")
        if not isinstance(now, datetime):
            raise TypeError("Patch trend now must be a datetime")
        return {
            f"{days}_day": self._window(history, now=now, days=days)
            for days in self.WINDOWS
        }

    def _window(
        self, history: list[dict[str, Any]], *, now: datetime, days: int
    ) -> dict[str, Any]:
        cutoff = now - timedelta(days=days)
        rows = [
            row
            for row in history
            if (observed := self._date(row.get("observed_at"))) is not None
            and cutoff <= observed <= now
        ]
        total = len(rows)
        success_statuses = {"compliant", "succeeded", "success"}
        failure_statuses = {"failed", "failure", "error", "noncompliant", "non-compliant"}
        compliant = sum(
            str(row.get("status") or "").casefold() in success_statuses
            for row in rows
        )
        failed = sum(
            str(row.get("status") or "").casefold() in failure_statuses
            for row in rows
        )
        known_outcomes = compliant + failed
        ordered = sorted(rows, key=lambda row: str(row.get("observed_at") or ""))
        risks = []
        for row in ordered:
            value = row.get("risk_score")
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
                raise ValueError("Patch trend risk_score must be an integer from 0 to 100")
            risks.append(value)
        by_observation: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in ordered:
            by_observation[str(row.get("observed_at") or "")].append(row)
        observation_scores = []
        for sample in by_observation.values():
            known = [
                str(row.get("status") or "").casefold()
                for row in sample
                if str(row.get("status") or "").casefold()
                in success_statuses | failure_statuses
            ]
            if known:
                observation_scores.append(
                    sum(status in success_statuses for status in known) / len(known)
                )
        if not observation_scores:
            direction = "insufficient data"
        elif observation_scores[-1] > observation_scores[0]:
            direction = "improving compliance"
        elif observation_scores[-1] < observation_scores[0]:
            direction = "degrading compliance"
        elif risks and risks[-1] < risks[0]:
            direction = "improving compliance"
        elif risks and risks[-1] > risks[0]:
            direction = "degrading compliance"
        else:
            direction = "stable"
        failures = Counter(
            str(row.get("resource") or "Unknown")
            for row in rows
            if str(row.get("status") or "").casefold() in failure_statuses
        )
        return {
            "observation_count": total,
            "patch_success_trend": round(100 * compliant / known_outcomes, 2)
            if known_outcomes
            else None,
            "patch_failure_trend": round(100 * failed / known_outcomes, 2)
            if known_outcomes
            else None,
            "compliance_trend": direction,
            "risk_trend": {
                "first": risks[0] if risks else None,
                "last": risks[-1] if risks else None,
                "change": risks[-1] - risks[0] if risks else None,
            },
            "recurring_failures": sorted(name for name, count in failures.items() if count >= 2),
            "chronic_offenders": sorted(name for name, count in failures.items() if count >= 3),
        }

    @staticmethod
    def _date(value: Any) -> datetime | None:
        try:
            parsed = datetime.fromisoformat(str(value))
            return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed
        except (TypeError, ValueError):
            return None
