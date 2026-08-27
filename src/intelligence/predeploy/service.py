"""Orchestration of the pre-deployment impact assessment pipeline.

The service runs the stages in dependency order — ingest, compare against
discovered state, traverse blast radius, simulate, score, recommend — and holds
the assessments it produces so they can be listed and re-read.

Scope is applied once, at the point discovered state enters the pipeline, and
the narrowed resource set is then the only estate view every downstream stage
sees. Filtering at the boundary rather than per-stage means a stage cannot
accidentally reach around the restriction, and there is exactly one place to
audit for scope isolation.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

# ``api`` imports the FastAPI app, whose router package imports this one, so
# Scope is typed statically and constructed lazily.
if TYPE_CHECKING:
    from api.scope import Scope

from .blast_radius import DEFAULT_MAX_DEPTH, DEFAULT_MAX_NODES, analyze_blast_radius
from .cab import recommend
from .ingestion import ingest
from .models import DiscoveredResource, unrestricted_scope
from .risk import score_change
from .simulation import simulate
from .state_comparison import compare_states

SOURCE_ENGINE = "intelligence.PreDeploymentImpactService"


def _now() -> str:
    return datetime.now(UTC).isoformat()


class PreDeploymentImpactService:
    """Assess proposed changes before deployment."""

    def __init__(
        self,
        *,
        max_depth: int = DEFAULT_MAX_DEPTH,
        max_nodes: int = DEFAULT_MAX_NODES,
        history_limit: int = 200,
    ) -> None:
        self._max_depth = max_depth
        self._max_nodes = max_nodes
        self._history_limit = history_limit
        self._assessments: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Assessment
    # ------------------------------------------------------------------
    def assess(
        self,
        *,
        source: str,
        payload: Mapping[str, Any],
        discovered: Sequence[DiscoveredResource] | Sequence[Mapping[str, Any]] = (),
        scope: Scope | None = None,
        change_id: str = "",
        vulnerability_index: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    ) -> dict[str, Any]:
        """Run the full pipeline for one submitted change."""
        effective_scope = scope or unrestricted_scope()
        change = ingest(source, payload, change_id=change_id or uuid.uuid4().hex)
        resources = _coerce_resources(discovered)

        # Single scope boundary. Everything downstream sees only this list, so
        # out-of-scope resources cannot appear in any count, name, or roll-up.
        if not effective_scope.is_satisfiable():
            in_scope: list[DiscoveredResource] = []
        else:
            in_scope = [item for item in resources if effective_scope.matches(item.scope_attributes())]
        excluded = len(resources) - len(in_scope)

        comparison = compare_states(change, in_scope)
        blast_radius = analyze_blast_radius(
            change,
            in_scope,
            scope=effective_scope,
            max_depth=self._max_depth,
            max_nodes=self._max_nodes,
            vulnerability_index=vulnerability_index,
        )
        simulation = simulate(change)
        risk = score_change(
            change,
            comparison=comparison,
            blast_radius=blast_radius,
            simulation=simulation,
        )
        cab = recommend(
            change,
            risk=risk,
            blast_radius=blast_radius,
            simulation=simulation,
        )

        assessment = {
            "assessment_id": uuid.uuid4().hex,
            "assessed_at": _now(),
            "change": change.to_dict(),
            "state_comparison": comparison,
            "blast_radius": blast_radius,
            "simulation": simulation,
            "risk": risk,
            "cab_recommendation": cab,
            "scope": effective_scope.to_dict(),
            "scope_excluded_resource_count": excluded,
            "source_engine": SOURCE_ENGINE,
            "confirmed_cause": False,
        }
        self._remember(assessment)
        return assessment

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------
    def _remember(self, assessment: Mapping[str, Any]) -> None:
        self._assessments[str(assessment["assessment_id"])] = dict(assessment)
        if len(self._assessments) > self._history_limit:
            for key in list(self._assessments)[: len(self._assessments) - self._history_limit]:
                self._assessments.pop(key, None)

    def get_assessment(self, assessment_id: str) -> dict[str, Any] | None:
        return self._assessments.get(str(assessment_id))

    def list_assessments(self, *, scope: Scope | None = None) -> list[dict[str, Any]]:
        """Summaries of stored assessments, newest first."""
        effective_scope = scope or unrestricted_scope()
        rows: list[dict[str, Any]] = []
        for assessment in self._assessments.values():
            if not _summary_in_scope(assessment, effective_scope):
                continue
            change = assessment.get("change", {})
            cab = assessment.get("cab_recommendation", {})
            risk = assessment.get("risk", {})
            blast_radius = assessment.get("blast_radius", {})
            rows.append(
                {
                    "assessment_id": assessment.get("assessment_id"),
                    "assessed_at": assessment.get("assessed_at"),
                    "change_id": change.get("change_id"),
                    "source": change.get("source"),
                    "title": change.get("title"),
                    "author": change.get("author"),
                    "target_environment": change.get("target_environment"),
                    "resource_change_count": len(change.get("resource_changes", [])),
                    "risk_score": risk.get("score"),
                    "risk_level": risk.get("level"),
                    "confidence": risk.get("confidence"),
                    "verdict": cab.get("verdict"),
                    "total_impacted_count": blast_radius.get("total_impacted_count"),
                    "business_services": blast_radius.get("business_services", []),
                }
            )
        rows.sort(key=lambda row: str(row.get("assessed_at") or ""), reverse=True)
        return rows


def _summary_in_scope(assessment: Mapping[str, Any], scope: Scope) -> bool:
    """Keep an assessment only when its own reach intersects the caller's scope.

    An assessment produced under a wider scope must not leak through a listing
    requested under a narrower one, so it is re-checked against the impacted
    resources it actually recorded.
    """
    if scope.is_unrestricted():
        return True
    if not scope.is_satisfiable():
        return False
    blast_radius = assessment.get("blast_radius", {})
    impacted = blast_radius.get("impacted_resources", []) or []
    if not impacted:
        # Nothing to attribute the assessment to, so it cannot be shown to a
        # restricted caller.
        return False
    return any(
        scope.matches(
            {
                key: str(resource.get(key) or "")
                for key in ("subscription", "environment", "application", "business_service", "region", "owner")
                if resource.get(key)
            }
        )
        for resource in impacted
    )


def _coerce_resources(
    discovered: Sequence[DiscoveredResource] | Sequence[Mapping[str, Any]],
) -> list[DiscoveredResource]:
    resources: list[DiscoveredResource] = []
    for item in discovered:
        if isinstance(item, DiscoveredResource):
            resources.append(item)
        elif isinstance(item, Mapping):
            resources.append(_from_mapping(item))
    return resources


_RESOURCE_ID_KEYS = ("resource_id", "id", "resourceId", "azure_resource_id")
_TYPE_KEYS = ("resource_type", "type", "resourceType")


def _first(payload: Mapping[str, Any], keys: Sequence[str]) -> str:
    for key in keys:
        value = payload.get(key)
        if value:
            return str(value)
    return ""


def _from_mapping(payload: Mapping[str, Any]) -> DiscoveredResource:
    depends_on = payload.get("depends_on") or payload.get("dependencies") or ()
    if isinstance(depends_on, (str, bytes)):
        depends_on = [depends_on]
    properties = payload.get("properties")
    return DiscoveredResource(
        resource_id=_first(payload, _RESOURCE_ID_KEYS),
        resource_type=_first(payload, _TYPE_KEYS),
        name=str(payload.get("name") or ""),
        application=str(payload.get("application") or ""),
        business_service=str(payload.get("business_service") or payload.get("businessService") or ""),
        environment=str(payload.get("environment") or ""),
        subscription=str(payload.get("subscription") or payload.get("subscription_id") or ""),
        owner=str(payload.get("owner") or ""),
        support_team=str(payload.get("support_team") or payload.get("supportTeam") or ""),
        region=str(payload.get("region") or payload.get("location") or ""),
        criticality=str(payload.get("criticality") or ""),
        depends_on=tuple(str(value) for value in depends_on if value),
        properties=dict(properties) if isinstance(properties, Mapping) else {},
        observed_at=str(payload.get("observed_at") or payload.get("observedAt") or ""),
    )
