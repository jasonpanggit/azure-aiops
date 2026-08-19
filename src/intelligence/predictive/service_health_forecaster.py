from __future__ import annotations


class ServiceHealthForecaster:
    """Aggregates resource forecasts into application/service horizon health."""

    def forecast(self, predictions, field):
        grouped = {}
        for prediction in predictions:
            grouped.setdefault(str(prediction.get(field) or "Unknown"), []).append(prediction)
        rows = []
        for name, items in grouped.items():
            horizons = {
                str(days): max(item[f"forecast_{days}_day"]["score"] for item in items)
                for days in (30, 60, 90)
            }
            rows.append(
                {
                    "name": name,
                    "resource_count": len(items),
                    "forecast_30_day": horizons["30"],
                    "forecast_60_day": horizons["60"],
                    "forecast_90_day": horizons["90"],
                    "service_degradation_risk": max(horizons.values()),
                    "compliance_decline_risk": max(
                        item["forecast_90_day"]["compliance_degradation_score"]
                        for item in items
                    ),
                    "operational_debt_growth": max(
                        int(item["trend"].get("growth_index") or 0) for item in items
                    ),
                    "drivers": sorted(
                        {driver for item in items for driver in item["risk_drivers"]}
                    ),
                }
            )
        return sorted(rows, key=lambda row: (-row["service_degradation_risk"], row["name"]))
