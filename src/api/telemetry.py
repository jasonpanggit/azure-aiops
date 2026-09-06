"""Telemetry for the Operations API.

Records request counts, latency, and authorization outcomes through the
OpenTelemetry metrics API already used across the intelligence engines. No
request payloads, headers, principals, or scope values are recorded — only
low-cardinality dimensions — so telemetry can never become a secret sink.
"""

from __future__ import annotations

import time
from typing import Any

from opentelemetry import metrics

from operations.exposure_metrics import ExposureMetrics


class ApiTelemetry:
    def __init__(self, meter: Any = None) -> None:
        self._meter = meter or metrics.get_meter("aiops.api")
        self.exposure = ExposureMetrics(meter=self._meter)
        self._requests = self._meter.create_counter(
            "aiops.api.requests",
            description="Operations API requests by route, method and status class",
        )
        self._latency = self._meter.create_histogram(
            "aiops.api.request.duration",
            unit="ms",
            description="Operations API request latency",
        )
        self._denied = self._meter.create_counter(
            "aiops.api.authorization.denied",
            description="Requests rejected by authentication or authorization",
        )

    def record_request(
        self, *, route: str, method: str, status_code: int, duration_ms: float
    ) -> None:
        attributes = {
            "route": route,
            "method": method,
            # Status class only: avoids high-cardinality per-status series.
            "status_class": f"{status_code // 100}xx",
        }
        self._requests.add(1, attributes)
        self._latency.record(max(duration_ms, 0.0), attributes)

    def record_denied(self, *, route: str, reason: str) -> None:
        self._denied.add(1, {"route": route, "reason": reason})


class Timer:
    """Wall-clock timer in milliseconds."""

    def __init__(self, clock=time.monotonic) -> None:
        self._clock = clock
        self._start = clock()

    def elapsed_ms(self) -> float:
        return (self._clock() - self._start) * 1000.0
