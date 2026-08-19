from __future__ import annotations

from .forecast_engine import ForecastEngine


class RiskForecaster(ForecastEngine):
    """Produces transparent 30/60/90-day scenario-risk forecasts."""
