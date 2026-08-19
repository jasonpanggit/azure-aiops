from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar


class LifecycleTrendEngine:
    WINDOWS: ClassVar[tuple[int, ...]] = (30, 90, 180)

    def calculate(
        self, history: list[dict[str, Any]], *, now: datetime
    ) -> dict[str, Any]:
        ordered = sorted(
            history,
            key=lambda row: (
                str(row.get("observed_at") or ""),
                str(row.get("ingestion_run_id") or ""),
            ),
        )
        return {
            f"{days}_day": self._window(ordered, now=now, days=days)
            for days in self.WINDOWS
        }

    def _window(
        self, rows: list[dict[str, Any]], *, now: datetime, days: int
    ) -> dict[str, Any]:
        cutoff = now - timedelta(days=days)
        selected = [
            row
            for row in rows
            if (observed := self._date(row.get("observed_at"))) is not None
            and cutoff <= observed <= now
        ]
        by_snapshot: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in selected:
            by_snapshot[
                (
                    str(row.get("observed_at") or ""),
                    str(row.get("ingestion_run_id") or ""),
                )
            ].append(row)
        averages = []
        for sample in by_snapshot.values():
            known = [row["risk_score"] for row in sample if row.get("risk_score") is not None]
            if known:
                averages.append(sum(known) / len(known))
        change = (
            round(averages[-1] - averages[0], 2)
            if len(averages) >= 2
            else 0.0
            if averages
            else None
        )
        direction = (
            "Improving"
            if change is not None and change < 0
            else "Degrading"
            if change is not None and change > 0
            else "Stable"
            if change == 0
            else "Unknown"
        )
        state_before: dict[str, str] = {}
        state_in_window: dict[str, str] = {}
        for row in rows:
            observed = self._date(row.get("observed_at"))
            if observed is None or observed > now:
                continue
            key = str(row.get("resource_key") or "")
            status = str(row.get("lifecycle_status") or "Unknown")
            if observed < cutoff:
                state_before[key] = status
            else:
                state_in_window[key] = status
        earlier_eol = {key for key, status in state_before.items() if status == "EOL"}
        window_eol = {key for key, status in state_in_window.items() if status == "EOL"}
        last_state: dict[str, str] = {}
        for row in rows:
            observed = self._date(row.get("observed_at"))
            if observed is None or observed >= cutoff:
                continue
            last_state[str(row.get("resource_key") or "")] = str(
                row.get("modernization_state") or ""
            ).casefold()
        modernization_progress = 0
        for row in selected:
            key = str(row.get("resource_key") or "")
            state = str(row.get("modernization_state") or "").casefold()
            if (
                state in {"planned", "in_progress", "completed"}
                and state != last_state.get(key, "")
            ):
                modernization_progress += 1
            last_state[key] = state
        return {
            "observation_count": len(selected),
            "new_eol_discoveries": len(window_eol - earlier_eol),
            "risk_score_change": change,
            "modernization_progress_events": modernization_progress,
            "lifecycle_debt_reduction": len(
                {
                    key
                    for key in earlier_eol
                    if state_in_window.get(key) not in {None, "EOL"}
                }
            ),
            "trend": direction,
        }

    @staticmethod
    def _date(value: Any) -> datetime | None:
        try:
            parsed = datetime.fromisoformat(str(value))
            return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed
        except (TypeError, ValueError):
            return None
