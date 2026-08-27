from __future__ import annotations

from copy import deepcopy
from typing import Protocol

from .live_provider import LiveObservation, LiveResourceProvider


class GraphContextReader(Protocol):
    def get_resource_context(self, resource: str, *, subject_type: str = "") -> dict: ...


class HybridQueryService:
    """Join durable graph context with request-time observations."""

    def __init__(
        self, graph: GraphContextReader, live_resources: LiveResourceProvider
    ) -> None:
        self.graph = graph
        self.live_resources = live_resources

    def resource_context(
        self,
        resource_id: str,
        *,
        subscription_ids: list[str],
        subject_type: str = "",
    ) -> dict:
        graph_context = deepcopy(
            self.graph.get_resource_context(resource_id, subject_type=subject_type)
        )
        observation: LiveObservation = self.live_resources.get_resource(
            resource_id, subscription_ids=subscription_ids
        )
        graph_context["graph_freshness"] = str(
            graph_context.get("freshness") or graph_context.get("graph_freshness") or ""
        )
        graph_context["live_observed_at"] = observation.observed_at
        graph_context["source_status"] = {
            observation.source: observation.status,
        }
        graph_context["live_observation"] = {
            "source": observation.source,
            "observed_at": observation.observed_at,
            "rows": list(observation.rows),
        }
        return graph_context

    def search(self, query: str, *, subscription_ids: list[str]) -> dict:
        observation = self.live_resources.search_resources(
            query, subscription_ids=subscription_ids
        )
        return {
            "intent": "live_resource_search",
            "results": list(observation.rows),
            "count": len(observation.rows),
            "graph_freshness": str(
                getattr(self.graph, "freshness", "") or ""
            ),
            "live_observed_at": observation.observed_at,
            "source_status": {observation.source: observation.status},
        }

    def service_context(
        self, service: str, *, subscription_ids: list[str], subject_type: str = ""
    ) -> dict:
        context = deepcopy(
            self.graph.get_service_context(service, subject_type=subject_type)
        )
        resources = context.get("sections", {}).get("infrastructure", [])
        live_rows: list[dict] = []
        observed_at = ""
        for item in resources if isinstance(resources, list) else []:
            if not isinstance(item, dict):
                continue
            resource_id = str(item.get("resource_id") or item.get("id") or "")
            if resource_id:
                observation = self.live_resources.get_resource(
                    resource_id, subscription_ids=subscription_ids
                )
                live_rows.extend(observation.rows)
                observed_at = max(observed_at, observation.observed_at)
        context["live_resource_state"] = live_rows
        context["live_observed_at"] = observed_at
        context["source_status"] = {"azure-resource-graph": "ok"}
        return context
