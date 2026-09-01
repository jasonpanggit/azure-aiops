"""Fabric incident causality pipeline — forwards ``IncidentEngine``'s
projected ``Incident``/``OperationalFinding``/``BlastRadius``/
``DependencyChain``/``OperationalEvent``/``RootCause``/``RiskPattern``
ontology rows.

Mirrors ``change_pipeline.py``'s shape exactly (MED-04, Task 4): before
this fix, ``IncidentEngine.knowledge_projection()`` already built this
bounded ``CausalityGraph``, but ``IncidentEngine`` was only ever
instantiated in ``src/semantic/live_operations.py``'s on-demand query path
— never in ``sync_service.py``'s batch dataset-assembly flow — so the
graph never reached ontology publication.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from intelligence.incidents.incident_engine import IncidentEngine

SOURCE_TAG = "fabric_pipeline:incident"


@dataclass(frozen=True)
class IncidentPipelineResult:
    entities: list[dict[str, Any]] = field(default_factory=list)
    relationships: list[dict[str, Any]] = field(default_factory=list)


def run(*, now: Any | None = None, **snapshot: Any) -> IncidentPipelineResult:
    engine = IncidentEngine.from_snapshot(
        **snapshot,
        now=now or (lambda: datetime.now(UTC)),
    )
    engine.analyze()
    projection = engine.knowledge_projection()
    return IncidentPipelineResult(
        entities=list(projection["entities"]),
        relationships=list(projection["relationships"]),
    )


__all__ = ["SOURCE_TAG", "IncidentPipelineResult", "run"]
