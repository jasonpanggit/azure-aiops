from __future__ import annotations

from types import SimpleNamespace

import pytest

from api.dependencies import live_subscription_ids
from api.routers import compliance, network, operations, patching, vulnerability
from api.scope import Scope


def _connection(connection_id: str, subscription_id: str):
    return SimpleNamespace(
        connection_id=connection_id,
        subscription_id=subscription_id,
        is_active=True,
    )


def _context(*connections):
    return SimpleNamespace(
        onboarding=SimpleNamespace(
            registry=SimpleNamespace(
                list=lambda *, include_disabled=False: list(connections)
            )
        )
    )


def test_live_subscription_scope_resolves_selected_connection_and_intersection() -> None:
    context = _context(
        _connection("conn-a", "sub-a"),
        _connection("conn-b", "sub-b"),
    )

    assert live_subscription_ids(
        context,
        Scope.from_mapping({"subscription_connection": ["conn-b"]}),
        default_all=True,
    ) == ["sub-b"]
    assert live_subscription_ids(
        context,
        Scope.from_mapping(
            {
                "subscription": ["sub-a"],
                "subscription_connection": ["conn-b"],
            }
        ),
        default_all=True,
    ) == []


@pytest.mark.parametrize(
    "scope",
    [
        Scope.unrestricted(),
        Scope.from_mapping({"environment": ["production"]}),
    ],
)
def test_unscoped_snapshot_read_does_not_access_connection_registry(scope: Scope) -> None:
    def fail_if_listed(*, include_disabled: bool = False):
        del include_disabled
        raise AssertionError("snapshot-backed read must not access connection registry")

    context = _context()
    context.onboarding.registry.list = fail_if_listed

    assert live_subscription_ids(context, scope) == []


@pytest.mark.parametrize(
    "resolve",
    [
        lambda context, scope: network._service(context, scope),
        lambda context, scope: vulnerability._service(context, scope),
        lambda context, scope: patching._service(context, scope),
        lambda context, scope: operations._require(
            context, "incidents_provider", "incidents", scope
        ),
        lambda context, scope: compliance._service(context, scope),
    ],
    ids=["network", "vulnerability", "patching", "incidents", "compliance"],
)
def test_page_provider_factories_use_selected_connection_subscription(resolve) -> None:
    captured: list[list[str]] = []

    class NetworkService:
        def scoped(self, _scope):
            return self

    context = _context(
        _connection("conn-a", "sub-a"),
        _connection("conn-b", "sub-b"),
    )
    context.hybrid_network_provider = (
        lambda subscription_ids: captured.append(subscription_ids) or NetworkService()
    )
    context.hybrid_vulnerability_provider = (
        lambda subscription_ids: captured.append(subscription_ids) or object()
    )
    context.hybrid_patching_provider = (
        lambda subscription_ids: captured.append(subscription_ids) or object()
    )
    context.hybrid_incident_provider = (
        lambda subscription_ids: captured.append(subscription_ids) or object()
    )
    context.hybrid_remediation_provider = None
    context.hybrid_change_provider = (
        lambda subscription_ids: captured.append(subscription_ids) or object()
    )
    context.resolve_provider = lambda _name: (_ for _ in ()).throw(
        AssertionError("selected connection must use the live provider")
    )

    resolve(
        context,
        Scope.from_mapping({"subscription_connection": ["conn-b"]}),
    )

    assert captured == [["sub-b"]]
