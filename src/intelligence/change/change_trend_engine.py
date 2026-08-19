from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any


class ChangeTrendEngine:
    def calculate(self, history: list[dict[str, Any]], *, now: datetime) -> dict[str, Any]:
        return {f"{days}_day": self._window(history, now, days) for days in (30, 90, 180)}

    def _window(self, history, now, days):
        cutoff = now - timedelta(days=days)
        rows = [row for row in history if (stamp := self._time(row.get("observed_at"))) and cutoff <= stamp <= now]
        ordered = sorted(rows, key=lambda row: (str(row.get("observed_at") or ""), str(row.get("resource_key") or ""), int(row.get("risk_score") or 0), int(row.get("compliance_score") or 0)))
        risk_change = int(ordered[-1].get("risk_score") or 0) - int(ordered[0].get("risk_score") or 0) if ordered else 0
        compliance_change = int(ordered[-1].get("compliance_score") or 0) - int(ordered[0].get("compliance_score") or 0) if ordered else 0
        trend = "Degrading" if risk_change > 0 or compliance_change < 0 else "Improving" if risk_change < 0 or compliance_change > 0 else "Stable"
        return {"observation_count": len(rows), "risk_score_change": risk_change, "compliance_score_change": compliance_change, "trend": trend}

    @staticmethod
    def _time(value):
        try: parsed = datetime.fromisoformat(str(value))
        except (TypeError, ValueError): return None
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
