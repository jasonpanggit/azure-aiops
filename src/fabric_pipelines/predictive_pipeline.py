"""Fabric predictive operations pipeline — forwards ``PredictiveEngine``'s
projected ``Prediction``/``Forecast``/``Trend``/``OperationalDebt``/
``RiskDriver`` ontology rows.

Discovered during MED-04's Task 3 investigation (10-06-PLAN.md): this
producer already existed but was never invoked outside its own test suite
— the identical "computed but discarded" bug class as the Change domain,
just with no ``run()`` boundary to discard *at* (there was no pipeline
module at all until this one).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from intelligence.predictive.predictive_engine import PredictiveEngine

SOURCE_TAG = "fabric_pipeline:predictive"


@dataclass(frozen=True)
class PredictivePipelineResult:
    entities: list[dict[str, Any]] = field(default_factory=list)
    relationships: list[dict[str, Any]] = field(default_factory=list)


def run(*, now: Any | None = None, **snapshot: Any) -> PredictivePipelineResult:
    engine = PredictiveEngine.from_snapshot(
        **snapshot,
        now=now or (lambda: datetime.now(UTC)),
    )
    projection = engine.knowledge_projection()
    return PredictivePipelineResult(
        entities=list(projection["entities"]),
        relationships=list(projection["relationships"]),
    )


__all__ = ["SOURCE_TAG", "PredictivePipelineResult", "run"]
