from __future__ import annotations

from semantic.hybrid_query import HybridQueryService
from semantic.live_provider import LiveResourceProvider


class Reader:
    def query(self, spec, scope_ids):
        return [{"id": "resource-1", "properties": {"provisioningState": "Succeeded"}}]


class Graph:
    def get_resource_context(self, resource, *, subject_type=""):
        return {
            "freshness": "graph-published-at",
            "sections": {"ownership": [{"team": "platform"}]},
        }

    def get_service_context(self, service, *, subject_type=""):
        return {
            "sections": {"infrastructure": [{"resource_id": "resource-1"}]},
            "freshness": "graph-time",
        }


def test_hybrid_context_keeps_graph_and_live_freshness_separate():
    result = HybridQueryService(
        Graph(), LiveResourceProvider(Reader())
    ).resource_context("resource-1", subscription_ids=["sub-1"])

    assert result["graph_freshness"] == "graph-published-at"
    assert result["live_observed_at"].endswith("Z")
    assert result["source_status"] == {"azure-resource-graph": "ok"}
    assert result["sections"]["ownership"] == [{"team": "platform"}]
    assert result["live_observation"]["rows"][0]["properties"]["provisioningState"] == "Succeeded"


def test_hybrid_service_context_refreshes_graph_linked_resources():
    result = HybridQueryService(
        Graph(), LiveResourceProvider(Reader())
    ).service_context("checkout", subscription_ids=["sub-1"])

    assert result["live_resource_state"][0]["id"] == "resource-1"
    assert result["live_observed_at"].endswith("Z")
