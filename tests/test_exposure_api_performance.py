"""Bounded-work contracts for the production Exposure query path."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.exposure_query import (
    MAX_EXPOSURE_PAGE_SIZE,
    MAX_EXPOSURE_QUERY_TIMEOUT_SECONDS,
    ExposureAuthorization,
    ExposureCursorError,
    ExposureQuery,
    ExposureQueryPage,
    ExposureQueryService,
    ExposureRestartConflict,
)
from api.rbac import Authorizer, Grant, Principal
from api.scope import Scope
from api.telemetry import ApiTelemetry
from onboarding.service import SubscriptionOnboardingService
from scripts.benchmark_exposure_read_model import (
    DeterministicFabricSqlReader,
    DeterministicMemoryAdapter,
    derive_benchmark_authorization,
    generate_exposure_rows,
    run_fabric_sql_benchmark,
    run_local_benchmark,
)


class PageReader:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], int | None]] = []

    def query(
        self,
        sql: str,
        parameters: tuple[Any, ...] = (),
        *,
        max_rows: int | None = None,
    ) -> list[dict[str, Any]]:
        self.calls.append((sql, tuple(parameters), max_rows))
        if "COUNT_BIG" in sql:
            return [{"total_count": 100_000}]
        if "dimension_name" in sql:
            return []
        page_limit = int(max_rows or 0)
        return [
            {"exposure_id": f"exposure-{index:06d}", "priority_score": 1000 - index}
            for index in range(page_limit)
        ]


def _authorization() -> ExposureAuthorization:
    return ExposureAuthorization(
        subject="scale-reader@example.com",
        tenant_id="tenant-scale",
        connection_ids=("connection-scale",),
        scope={"subscription": ("subscription-scale",)},
    )


def test_page_work_is_bounded_independently_of_total_count() -> None:
    reader = PageReader()
    result = ExposureQueryService(reader).list_page(
        _authorization(),
        generation_id="generation-100k",
        query=ExposureQuery(page_size=MAX_EXPOSURE_PAGE_SIZE),
    )

    assert result.total_count == 100_000
    assert len(result.items) == MAX_EXPOSURE_PAGE_SIZE
    assert result.next_position == (
        result.items[-1]["priority_score"],
        result.items[-1]["exposure_id"],
    )
    page_sql, _parameters, max_rows = reader.calls[-1]
    assert f"TOP ({MAX_EXPOSURE_PAGE_SIZE + 1})" in page_sql
    assert max_rows == MAX_EXPOSURE_PAGE_SIZE + 1
    assert " OFFSET " not in page_sql.upper()
    assert "SELECT *" not in page_sql.upper()


@pytest.mark.parametrize("page_size", [0, MAX_EXPOSURE_PAGE_SIZE + 1, 10_000])
def test_page_size_is_rejected_before_query(page_size: int) -> None:
    reader = PageReader()

    with pytest.raises(ValueError, match="page_size"):
        ExposureQueryService(reader).list_page(
            _authorization(),
            generation_id="generation-100k",
            query=ExposureQuery(page_size=page_size),
        )

    assert reader.calls == []


def test_query_service_rejects_unbounded_statement_timeout() -> None:
    reader = PageReader()
    reader.timeout_seconds = MAX_EXPOSURE_QUERY_TIMEOUT_SECONDS + 1

    with pytest.raises(ValueError, match="query timeout"):
        ExposureQueryService(reader)


class ApiExposureService:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def authorization_for(
        self,
        principal: Principal,
        scope: Any,
    ) -> ExposureAuthorization:
        assert principal.subject == "exposure-reader@example.com"
        assert scope.to_dict() == {"subscription": ["subscription-scale"]}
        return ExposureAuthorization(
            subject=principal.subject,
            tenant_id="tenant-scale",
            connection_ids=("connection-scale",),
            scope={
                "subscription": ("subscription-scale",),
                "subscription_connection": ("connection-scale",),
            },
        )

    def list_page(self, authorization: ExposureAuthorization, **values: Any):
        if self.error is not None:
            raise self.error
        self.calls.append({"authorization": authorization, **values})
        return ExposureQueryPage(
            items=(
                {
                    "exposure_id": "exposure-1",
                    "target_kind": "server",
                    "severity": "critical",
                },
            ),
            total_count=100_000,
            facets={
                "severity": [{"value": "critical", "count": 75_000}],
                "target_kind": [{"value": "server", "count": 100_000}],
            },
            generation="generation-100k",
            applied_scope=authorization.canonical_scope(),
            applied_filters=(
                {"field": "severity", "operator": "eq", "value": "critical"},
            ),
            applied_sort={"field": "priority_score", "direction": "desc"},
            next_position=(100.0, "exposure-1"),
            next_cursor="signed-next-cursor",
            completeness={"state": "complete"},
            freshness={
                "state": "reported",
                "as_of": "2026-09-06T08:00:00+00:00",
            },
        )


@pytest.fixture
def exposure_api(tmp_path: Path) -> tuple[TestClient, ApiExposureService]:
    token = "exposure-api-token-0123456789"
    service = ApiExposureService()
    context = ApiContext(
        onboarding=SubscriptionOnboardingService(tmp_path / "aiops"),
        authenticator=StaticTokenAuthenticator(
            {
                token: Principal(
                    subject="exposure-reader@example.com",
                    grants=(
                        Grant(
                            "reader",
                            Scope.from_mapping(
                                {"subscription": ["subscription-scale"]}
                            ),
                        ),
                    ),
                )
            }
        ),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
    )
    context.exposure_query_provider = lambda: service
    client = TestClient(create_app(context), raise_server_exceptions=False)
    client.headers["Authorization"] = f"Bearer {token}"
    return client, service


def test_exposure_list_endpoint_returns_cursor_envelope(
    exposure_api: tuple[TestClient, ApiExposureService],
) -> None:
    client, service = exposure_api

    response = client.get(
        "/api/v1/vulnerabilities/exposure/items",
        params={
            "subscription": "subscription-scale",
            "generation": "generation-100k",
            "severity": "critical",
            "facet": ["severity", "target_kind"],
            "page_size": 25,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    data = dict(body["data"])
    contract = data.pop("contract")
    assert contract["version"] == "1.0.0"
    assert contract["query"]["generation"] == "generation-100k"
    assert contract["counts"]["total"] == 100_000
    assert contract["counts"]["returned"] == 1
    assert contract["safe_error"] is None
    assert data == {
        "total_count": 100_000,
        "items": [
            {
                "exposure_id": "exposure-1",
                "target_kind": "server",
                "severity": "critical",
            }
        ],
        "next_cursor": "signed-next-cursor",
        "generation": "generation-100k",
        "applied": {
            "scope": {
                "subscription": ["subscription-scale"],
                "subscription_connection": ["connection-scale"],
            },
            "filters": [
                {"field": "severity", "operator": "eq", "value": "critical"}
            ],
            "sort": {"field": "priority_score", "direction": "desc"},
        },
        "completeness": {"state": "complete"},
        "freshness": {
            "state": "reported",
            "as_of": "2026-09-06T08:00:00+00:00",
        },
    }
    assert body["scope"] == {"subscription": ["subscription-scale"]}
    assert body["pagination"] == {
        "limit": 25,
        "total": 100_000,
        "next_cursor": "signed-next-cursor",
    }
    assert body["evidence"][0]["source_engine"] == "fabric_sql"
    assert service.calls[0]["query"].facets == ("severity", "target_kind")
    assert service.calls[0]["generation_id"] == "generation-100k"


@pytest.mark.parametrize(
    ("path", "expected_keys"),
    [
        (
            "/api/v1/vulnerabilities/exposure/overview",
            {
                "total_count",
                "generation",
                "completeness",
                "freshness",
                "applied",
                "contract",
            },
        ),
        (
            "/api/v1/vulnerabilities/exposure/facets",
            {
                "total_count",
                "facets",
                "items",
                "generation",
                "completeness",
                "freshness",
                "applied",
                "contract",
            },
        ),
    ],
)
def test_exposure_overview_and_facet_endpoints_use_shared_contract(
    exposure_api: tuple[TestClient, ApiExposureService],
    path: str,
    expected_keys: set[str],
) -> None:
    client, _service = exposure_api

    response = client.get(
        path,
        params={"subscription": "subscription-scale"},
    )

    assert response.status_code == 200, response.text
    assert set(response.json()["data"]) == expected_keys


@pytest.mark.parametrize(
    ("error", "status", "code", "reason"),
    [
        (
            ExposureCursorError(
                "exposure_cursor_invalid",
                "Exposure cursor signature is invalid",
            ),
            400,
            "invalid_request",
            "exposure_cursor_invalid",
        ),
        (
            ExposureRestartConflict(
                "exposure_generation_evicted",
                generation="generation-old",
            ),
            409,
            "conflict",
            "exposure_generation_evicted",
        ),
    ],
)
def test_exposure_endpoint_maps_cursor_failures_to_safe_errors(
    tmp_path: Path,
    error: Exception,
    status: int,
    code: str,
    reason: str,
) -> None:
    token = "exposure-api-token-0123456789"
    context = ApiContext(
        onboarding=SubscriptionOnboardingService(tmp_path / "aiops"),
        authenticator=StaticTokenAuthenticator(
            {
                token: Principal(
                    subject="exposure-reader@example.com",
                    grants=(Grant("reader"),),
                )
            }
        ),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
    )
    service = ApiExposureService(error)
    context.exposure_query_provider = lambda: service
    client = TestClient(create_app(context), raise_server_exceptions=False)

    response = client.get(
        "/api/v1/vulnerabilities/exposure/items",
        headers={"Authorization": f"Bearer {token}"},
        params={"subscription": "subscription-scale"},
    )

    assert response.status_code == status
    body = response.json()["error"]
    assert body["code"] == code
    assert body["details"]["reason_code"] == reason
    assert "key" not in response.text.casefold()


def test_100k_server_and_image_benchmark_is_exact_bounded_and_under_budget() -> None:
    report = run_local_benchmark(
        row_count=100_000,
        seed=31_001,
        page_size=100,
        warmups=2,
        measurements=5,
    )

    assert report["status"] == "pass"
    assert report["dataset"]["row_count"] == 100_000
    assert report["dataset"]["target_kind_counts"] == {
        "container_image": 20_000,
        "server": 80_000,
    }
    assert report["full_walk"] == {
        **report["full_walk"],
        "expected_total": 100_000,
        "returned_count": 100_000,
        "unique_count": 100_000,
        "duplicate_count": 0,
        "omission_count": 0,
        "status": "pass",
    }
    assert report["work"]["max_rows_fetched_per_query"] <= 101
    assert report["work"]["full_table_materializations"] == 0
    assert report["work"]["delta_fallbacks"] == 0
    assert report["memory"]["rss_delta_bytes"] > 0
    assert report["memory"]["under_budget"] is True
    assert report["environment"]["python"]
    assert {
        "server_scoped_first_page",
        "image_scoped_first_page",
    } <= set(report["timings"])
    assert all(
        timing["p95_ms"] < 2_000
        for timing in report["timings"].values()
    )


def test_benchmark_scope_is_derived_from_active_connection_metadata() -> None:
    authorization = derive_benchmark_authorization(
        [
            SimpleNamespace(
                tenant_id="tenant-live",
                subscription_id="subscription-a",
                connection_id="connection-a",
                is_active=True,
            ),
            SimpleNamespace(
                tenant_id="tenant-live",
                subscription_id="subscription-b",
                connection_id="connection-b",
                is_active=True,
            ),
            SimpleNamespace(
                tenant_id="tenant-live",
                subscription_id="subscription-disabled",
                connection_id="connection-disabled",
                is_active=False,
            ),
        ],
    )

    assert authorization.tenant_id == "tenant-live"
    assert authorization.connection_ids == ("connection-a", "connection-b")
    assert authorization.scope == {
        "subscription": ("subscription-a", "subscription-b"),
        "subscription_connection": ("connection-a", "connection-b"),
    }


def test_benchmark_scope_refuses_mixed_tenants_or_empty_live_metadata() -> None:
    with pytest.raises(ValueError, match="one tenant"):
        derive_benchmark_authorization(
            [
                SimpleNamespace(
                    tenant_id="tenant-a",
                    subscription_id="subscription-a",
                    connection_id="connection-a",
                    is_active=True,
                ),
                SimpleNamespace(
                    tenant_id="tenant-b",
                    subscription_id="subscription-b",
                    connection_id="connection-b",
                    is_active=True,
                ),
            ],
        )

    with pytest.raises(ValueError, match="active connection"):
        derive_benchmark_authorization([])


def test_qualified_benchmark_requires_100k_total_with_both_target_kinds() -> None:
    rows = generate_exposure_rows(100_000)
    adapter = DeterministicMemoryAdapter(rows)
    report = run_fabric_sql_benchmark(
        DeterministicFabricSqlReader(adapter),
        ExposureAuthorization(
            subject="exposure-benchmark",
            tenant_id="benchmark-tenant",
            connection_ids=("benchmark-connection-1", "benchmark-connection-2"),
            scope={
                "subscription": tuple(
                    sorted({row.subscription_id for row in rows})
                ),
                "subscription_connection": (
                    "benchmark-connection-1",
                    "benchmark-connection-2",
                ),
            },
        ),
        generation_id="benchmark-generation-0001",
        expected_rows=100_000,
        page_size=100,
        warmups=1,
        measurements=2,
    )

    assert report["status"] == "pass"
    assert report["dataset"]["row_count"] == 100_000
    assert report["dataset"]["target_kind_counts"] == {
        "container_image": 20_000,
        "server": 80_000,
    }
    assert report["full_walk"] == {
        "duplicate_count": 0,
        "omission_count": 0,
        "returned_count": 100_000,
        "unique_count": 100_000,
    }
