from __future__ import annotations

from api.scope import Scope
from operations.tools import (
    STATUS_DENIED,
    STATUS_EMPTY,
    STATUS_OK,
    STATUS_UNAVAILABLE,
    FabricIQToolAdapter,
    ToolContext,
)


class Context:
    pass


def test_fabric_iq_is_bounded_scope_checked_and_not_identity_authority():
    context = Context()
    context.fabric_iq_provider = lambda: FabricIQToolAdapter(
        source="fabric-iq",
        query=lambda kind, args, scope: {
            "data": {"subject": args["subject"], "items": list(range(100))},
            "freshness": "fresh",
            "provenance": "ontology-test",
        },
    )
    result = context.fabric_iq_provider().run(
        "topology", {"subject": "/subscriptions/sub-1"}, Scope.unrestricted()
    )
    assert result.status == STATUS_OK
    assert len(result.data["enrichment"]["items"]) == 25
    assert result.data["metadata"]["identity_authority"] is False
    assert result.data["metadata"]["provenance"] == "ontology-test"


def test_fabric_iq_allowlist_and_provider_outcomes_are_explicit():
    scope = Scope.unrestricted()
    denied = FabricIQToolAdapter(lambda *_: {}).run("inventory", {}, scope)
    assert denied.status == STATUS_DENIED
    unavailable = FabricIQToolAdapter(lambda *_: (_ for _ in ()).throw(TimeoutError())).run(
        "topology", {"subject": "x"}, scope
    )
    assert unavailable.status == STATUS_UNAVAILABLE
    empty = FabricIQToolAdapter(lambda *_: {"data": {}}).run(
        "topology", {"subject": "x"}, scope
    )
    assert empty.status == STATUS_EMPTY
