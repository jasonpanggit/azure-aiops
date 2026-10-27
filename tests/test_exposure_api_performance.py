"""Bounded-work contracts for the production Exposure query path."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from decimal import Decimal
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
    ExposureCursorCodec,
    ExposureCursorError,
    ExposureCursorKeyRing,
    ExposureFilter,
    ExposureKbIdentifierError,
    ExposureProvenanceEvidence,
    ExposureQuery,
    ExposureQueryPage,
    ExposureQueryService,
    ExposureRestartConflict,
)
from api.exposure_refresh import (
    ExposurePatchRefreshScope,
    ExposurePatchRefreshState,
)
from api.rbac import Authorizer, Grant, Principal
from api.scope import Scope
from api.telemetry import ApiTelemetry
from onboarding.service import SubscriptionOnboardingService
from scripts.benchmark_exposure_read_model import (
    DeterministicFabricSqlReader,
    DeterministicMemoryAdapter,
    derive_benchmark_authorization,
    derive_live_benchmark_inputs,
    generate_exposure_rows,
    run_fabric_sql_benchmark,
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


class ProvenanceReader:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], int | None]] = []
        self.endpoint = SimpleNamespace(schema="dbo")

    def query(
        self,
        sql: str,
        parameters: tuple[Any, ...] = (),
        *,
        max_rows: int | None = None,
    ) -> list[dict[str, Any]]:
        self.calls.append((sql, tuple(parameters), max_rows))
        if "[metadata_patch_snapshot]" in sql:
            if parameters[0] != "tenant-scale":
                return []
            return [
                {
                    "subscription_id": "subscription-scale",
                    "ingestion_run_id": "source-generation-17",
                    "source_generation": "source-effective-17",
                    "status": "succeeded",
                    "completeness": "complete",
                    "freshness": "current",
                    "freshness_at": "2026-09-10T02:41:10Z",
                    "freshness_threshold_seconds": 3600,
                    "represented_count": 1,
                    "expected_count": 1,
                }
            ]
        return [
            {
                "active_fact_count": 11,
                "expected_connection_fact_count": 11,
                "legacy_connection_fact_count": 0,
                "unexpected_connection_fact_count": 0,
            }
        ]


def _authorization() -> ExposureAuthorization:
    return ExposureAuthorization(
        subject="scale-reader@example.com",
        tenant_id="tenant-scale",
        connection_ids=("connection-scale",),
        scope={"subscription": ("subscription-scale",)},
    )


@pytest.mark.parametrize("counts", [
    {"distinct_targets": 20, "distinct_weaknesses": 50, "distinct_recorded_digests": 10},
    {},
])
def test_distinct_units_come_from_scoped_sql_count_not_cursor_rows(counts) -> None:
    class DistinctReader(PageReader):
        def query(self, sql, parameters=(), *, max_rows=None):
            rows = super().query(sql, parameters, max_rows=max_rows)
            if "COUNT_BIG" in sql:
                rows[0].update(counts)
            return rows

    reader = DistinctReader()
    page = ExposureQueryService(reader).list_page(_authorization(), generation_id="generation-17", query=ExposureQuery(page_size=25))
    assert page.distinct_counts == {name.removeprefix("distinct_"): value for name, value in counts.items()}
    assert page.total_count == 100_000
    assert len(page.items) == 25
    sql, parameters, _ = reader.calls[0]
    assert "COUNT_BIG(DISTINCT NULLIF(LOWER([target_id]), ''))" in sql
    assert "COUNT_BIG(DISTINCT NULLIF(LOWER([weakness_id]), ''))" in sql
    assert "COUNT_BIG(DISTINCT NULLIF(LOWER([image_digest]), ''))" in sql
    assert "generation-17" in parameters
    assert "subscription-scale" in parameters
    assert "connection-scale" in parameters


@pytest.mark.parametrize("value", [-1, True, 100_001, 1.5])
def test_inconsistent_distinct_counts_are_rejected(value) -> None:
    class InvalidReader(PageReader):
        def query(self, sql, parameters=(), *, max_rows=None):
            rows = super().query(sql, parameters, max_rows=max_rows)
            if "COUNT_BIG" in sql:
                rows[0]["distinct_targets"] = value
            return rows
    with pytest.raises(ValueError, match="distinct counts"):
        ExposureQueryService(InvalidReader()).list_page(_authorization(), generation_id="generation-17", query=ExposureQuery(page_size=25))


def test_provenance_query_is_scope_bounded_and_returns_redacted_counts() -> None:
    reader = ProvenanceReader()
    authorization = ExposureAuthorization(
        subject="scale-reader@example.com",
        tenant_id="tenant-scale",
        connection_ids=("connection-scale",),
        connection_subscriptions={
            "connection-scale": "subscription-scale",
        },
        scope={
            "subscription": ("subscription-scale",),
            "subscription_connection": ("connection-scale",),
        },
    )

    evidence = ExposureQueryService(reader).active_provenance_evidence(
        authorization,
        generation_id="silver-patch:source-generation-17",
        expected_connection_id="connection-scale",
    )

    assert evidence.to_dict() == {
        "generation": "silver-patch:source-generation-17",
        "active_fact_count": 11,
        "expected_connection_fact_count": 11,
        "legacy_connection_fact_count": 0,
        "unexpected_connection_fact_count": 0,
    }
    assert len(reader.calls) == 2
    barrier_sql, barrier_parameters, barrier_max_rows = reader.calls[0]
    assert "[metadata_patch_snapshot]" in barrier_sql
    assert "[subscription_id] IN (?)" in barrier_sql
    assert "[connection_id]" not in barrier_sql
    assert barrier_parameters == ("tenant-scale", "subscription-scale")
    assert barrier_max_rows == 2
    sql, parameters, max_rows = reader.calls[1]
    assert "[silver_patch_snapshot_findings]" in sql
    assert "[tenant_id] = ?" in sql
    assert "[subscription_id] IN (?)" in sql
    assert "[ingestion_run_id] = ?" in sql
    assert "LOWER([status]) IN ('missing', 'installation_failed')" in sql
    assert "legacy:%" in sql
    assert parameters == (
        "connection-scale",
        "connection-scale",
        "tenant-scale",
        "subscription-scale",
        "source-generation-17",
    )
    assert max_rows == 1


def test_provenance_rejects_unauthorized_connection_before_sql() -> None:
    reader = ProvenanceReader()
    authorization = ExposureAuthorization(
        subject="scale-reader@example.com",
        tenant_id="tenant-scale",
        connection_ids=("connection-scale",),
        connection_subscriptions={
            "connection-scale": "subscription-scale",
        },
        scope={
            "subscription": ("subscription-scale",),
            "subscription_connection": ("connection-scale",),
        },
    )

    with pytest.raises(PermissionError, match="outside authorization"):
        ExposureQueryService(reader).active_provenance_evidence(
            authorization,
            generation_id="silver-patch:source-generation-17",
            expected_connection_id="other-connection",
        )

    assert reader.calls == []


def test_provenance_rejects_gold_generation_before_sql() -> None:
    reader = ProvenanceReader()
    authorization = ExposureAuthorization(
        subject="scale-reader@example.com",
        tenant_id="tenant-scale",
        connection_ids=("connection-scale",),
        connection_subscriptions={
            "connection-scale": "subscription-scale",
        },
        scope={
            "subscription": ("subscription-scale",),
            "subscription_connection": ("connection-scale",),
        },
    )

    with pytest.raises(ValueError, match="Silver patch generation"):
        ExposureQueryService(reader).active_provenance_evidence(
            authorization,
            generation_id="exposure-gold-fresh",
            expected_connection_id="connection-scale",
        )

    assert reader.calls == []


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
        self.catalog_calls: list[dict[str, Any]] = []
        self.kb_calls: list[dict[str, Any]] = []
        self.provenance_calls: list[dict[str, Any]] = []
        self.refresh_calls: list[ExposurePatchRefreshScope] = []
        self.generation = "generation-100k"
        self.completeness_state = "complete"
        self.freshness_state = "reported"
        self.refresh_state = ExposurePatchRefreshState(
            state="refreshing",
            refreshing=True,
            last_success_at="2026-09-06T08:00:00+00:00",
        )

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
            connection_subscriptions={
                "connection-scale": "subscription-scale",
            },
            scope={
                "subscription": ("subscription-scale",),
                "subscription_connection": ("connection-scale",),
            },
        )

    def list_page(self, authorization: ExposureAuthorization, **values: Any):
        if self.error is not None:
            raise self.error
        self.calls.append({"authorization": authorization, **values})
        next_cursor = "signed-next-cursor"
        if values["query"].page_size == 1:
            next_cursor = ExposureCursorCodec(
                ExposureCursorKeyRing(
                    active_kid="test-active",
                    active_key=b"a" * 32,
                    loaded_at=datetime(2026, 9, 10, tzinfo=UTC),
                )
            ).issue(
                authorization,
                generation_id="generation-100k",
                query=values["query"],
                position=(Decimal("100.00"), "exposure-1"),
                now=datetime(2026, 9, 10, tzinfo=UTC),
            )
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
            generation=self.generation,
            applied_scope=authorization.canonical_scope(),
            applied_filters=(
                {"field": "severity", "operator": "eq", "value": "critical"},
            ),
            applied_sort={"field": "priority_score", "direction": "desc"},
            next_position=(100.0, "exposure-1"),
            next_cursor=next_cursor,
            completeness={"state": self.completeness_state},
            freshness={
                "state": self.freshness_state,
                "as_of": "2026-09-06T08:00:00+00:00",
            },
        )

    def request_refresh(
        self,
        scope: ExposurePatchRefreshScope,
    ) -> ExposurePatchRefreshState:
        self.refresh_calls.append(scope)
        return self.refresh_state

    def catalog_item(
        self,
        authorization: ExposureAuthorization,
        **values: Any,
    ) -> dict[str, Any]:
        self.catalog_calls.append({"authorization": authorization, **values})
        return {
            "contract_version": "1.0.0",
            "catalog_scope": "external_public_metadata",
            "environment_membership_included": False,
            "generation": "generation-100k",
            "item": {"cve_id": "CVE-2026-0001", "sources": {}},
        }

    def kb_item(
        self,
        authorization: ExposureAuthorization,
        **values: Any,
    ) -> dict[str, Any]:
        if self.error is not None:
            raise self.error
        self.kb_calls.append({"authorization": authorization, **values})
        return {
            "generation": "silver-patch:source-generation-17",
            "snapshot_freshness_at": "2026-09-10T02:41:10Z",
            "snapshot": {
                "completeness": "complete",
                "freshness": "fresh",
                "as_of": "2026-09-10T02:41:10Z",
            },
            "kb_id": "KB6000001",
            "title": "Contoso security update",
            "severity": "Critical",
            "published_at": "2026-08-01",
            "cve_ids": ["CVE-2026-0001"],
            "cves": [],
            "affected_servers": ["server-1"],
            "affected_business_services": [],
            "findings": [],
            "enrichment": {
                "status": "complete",
                "complete": True,
                "stale": False,
                "expected_count": 1,
                "available_count": 1,
                "sources": {},
            },
        }

    def active_provenance_evidence(
        self,
        authorization: ExposureAuthorization,
        **values: Any,
    ) -> ExposureProvenanceEvidence:
        self.provenance_calls.append(
            {"authorization": authorization, **values}
        )
        return ExposureProvenanceEvidence(
            generation=str(values["generation_id"]),
            active_fact_count=11,
            expected_connection_fact_count=11,
            legacy_connection_fact_count=0,
            unexpected_connection_fact_count=0,
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
    context.exposure_patch_refresh_provider = lambda: service
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
            "weakness_id": "CVE-2026-0001",
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
    assert service.calls[0]["query"].filters == (
        ExposureFilter("severity", "eq", "critical"),
        ExposureFilter("weakness_id", "eq", "CVE-2026-0001"),
    )
    assert service.calls[0]["generation_id"] == "generation-100k"
    assert service.refresh_calls == []


def test_distinct_counts_survive_the_authorized_api_projection(exposure_api, monkeypatch) -> None:
    client, service = exposure_api
    original = service.list_page

    def with_counts(*args, **kwargs):
        from dataclasses import replace
        return replace(original(*args, **kwargs), distinct_counts={"targets": 2, "weaknesses": 3, "recorded_digests": 1})

    monkeypatch.setattr(service, "list_page", with_counts)
    response = client.get("/api/v1/vulnerabilities/exposure/items", params={"subscription": "subscription-scale", "generation": "generation-100k"})
    assert response.status_code == 200, response.text
    assert response.json()["data"]["distinct_counts"] == {"targets": 2, "weaknesses": 3, "recorded_digests": 1}


def test_stale_patch_items_return_lkg_and_trigger_scoped_background_refresh(
    exposure_api: tuple[TestClient, ApiExposureService],
) -> None:
    client, service = exposure_api
    service.generation = "silver-patch:source-generation-17"
    service.freshness_state = "stale"

    response = client.get(
        "/api/v1/vulnerabilities/exposure/items",
        params={
            "subscription": "subscription-scale",
            "target_kind": "server",
            "source_family": "aum",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["data"]["items"][0]["exposure_id"] == "exposure-1"
    assert body["data"]["freshness"]["refresh"] == {
        "state": "refreshing",
        "refreshing": True,
        "last_success_at": "2026-09-06T08:00:00+00:00",
        "last_failure_at": "",
        "failure_code": "",
    }
    assert service.refresh_calls == [
        ExposurePatchRefreshScope(
            tenant_id="tenant-scale",
            connection_id="connection-scale",
            subscription_id="subscription-scale",
        )
    ]


def test_failed_patch_refresh_preserves_lkg_with_sanitized_warning_metadata(
    exposure_api: tuple[TestClient, ApiExposureService],
) -> None:
    client, service = exposure_api
    service.generation = "silver-patch:source-generation-17"
    service.completeness_state = "partial"
    service.refresh_state = ExposurePatchRefreshState(
        state="failed",
        refreshing=False,
        last_success_at="2026-09-06T08:00:00+00:00",
        last_failure_at="2026-09-14T05:00:00+00:00",
        failure_code="refresh_backoff",
    )

    response = client.get(
        "/api/v1/vulnerabilities/exposure/items",
        params={
            "subscription": "subscription-scale",
            "target_kind": "server",
            "source_family": "aum",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["data"]["items"][0]["exposure_id"] == "exposure-1"
    assert body["data"]["freshness"]["refresh"]["failure_code"] == (
        "refresh_backoff"
    )
    assert "connection-scale" not in str(body["data"]["freshness"]["refresh"])


def test_external_catalog_uses_authorized_generation_bound_query_service(
    exposure_api: tuple[TestClient, ApiExposureService],
) -> None:
    client, service = exposure_api

    response = client.get(
        "/api/v1/vulnerabilities/exposure/external-catalog/CVE-2026-0001",
        params={
            "subscription": "subscription-scale",
            "generation": "generation-100k",
        },
    )

    assert response.status_code == 200, response.text
    assert service.catalog_calls[0]["weakness_id"] == "CVE-2026-0001"
    assert service.catalog_calls[0]["generation_id"] == "generation-100k"
    data = response.json()["data"]
    assert data["catalog_scope"] == "external_public_metadata"
    assert data["environment_membership_included"] is False


def test_provenance_evidence_endpoint_returns_only_redacted_counts(
    exposure_api: tuple[TestClient, ApiExposureService],
) -> None:
    client, service = exposure_api

    response = client.get(
        "/api/v1/vulnerabilities/exposure/provenance-evidence",
        params={
            "subscription": "subscription-scale",
            "generation": "silver-patch:source-generation-17",
            "connection_id": "connection-scale",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["data"] == {
        "generation": "silver-patch:source-generation-17",
        "active_fact_count": 11,
        "expected_connection_fact_count": 11,
        "legacy_connection_fact_count": 0,
        "unexpected_connection_fact_count": 0,
    }
    assert body["scope"] == {}
    assert body["evidence"][0]["source_table"] == (
        "silver_patch_snapshot_findings"
    )
    assert "connection-scale" not in response.text
    assert "subscription-scale" not in response.text
    assert service.provenance_calls[0]["expected_connection_id"] == (
        "connection-scale"
    )


def test_kb_detail_uses_authorized_silver_query_service(
    exposure_api: tuple[TestClient, ApiExposureService],
) -> None:
    client, service = exposure_api

    response = client.get(
        "/api/v1/kbs/KB6000001",
        params={"subscription": "subscription-scale"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["kb_id"] == "KB6000001"
    assert response.json()["knowledge_version"] == (
        "silver-patch:source-generation-17"
    )
    assert response.json()["evidence"][0]["freshness"] == "fresh"
    assert response.json().get("warnings", []) == []
    assert service.kb_calls[0]["kb_id"] == "KB6000001"


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_message"),
    [
        (
            ExposureKbIdentifierError(
                "KB detail requires a canonical KB identifier"
            ),
            400,
            "KB detail requires a canonical KB identifier",
        ),
        (ValueError("sensitive SQL conversion detail"), 500, "Internal server error"),
    ],
)
def test_kb_detail_maps_only_identifier_errors_to_safe_client_failures(
    exposure_api: tuple[TestClient, ApiExposureService],
    error: Exception,
    expected_status: int,
    expected_message: str,
) -> None:
    client, service = exposure_api
    service.error = error

    response = client.get(
        "/api/v1/kbs/KB6000001",
        params={"subscription": "subscription-scale"},
    )

    assert response.status_code == expected_status
    assert response.json()["error"]["message"] == expected_message
    assert "sensitive SQL conversion detail" not in response.text


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
    result = subprocess.run(
        [
            sys.executable,
            str(
                Path(__file__).resolve().parents[1]
                / "scripts"
                / "benchmark_exposure_read_model.py"
            ),
            "--rows",
            "100000",
            "--seed",
            "31001",
            "--page-size",
            "100",
            "--warmups",
            "2",
            "--measurements",
            "5",
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"benchmark stderr:\n{result.stderr}\nstdout:\n{result.stdout}"
    )
    report = json.loads(result.stdout)

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


@pytest.mark.parametrize("connection_home", [None, "  ", "separate-connections"])
def test_live_benchmark_uses_connection_root_and_separate_gold_pointer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    connection_home: str | None,
) -> None:
    from onboarding import registry
    from storage.onelake_documents import OneLakeDocumentStore

    gold_root = str(tmp_path / "gold")
    monkeypatch.setenv("AIOPS_HOME", gold_root)
    if connection_home is None:
        monkeypatch.delenv("AIOPS_CONNECTION_HOME", raising=False)
    else:
        monkeypatch.setenv("AIOPS_CONNECTION_HOME", connection_home)
    roots: list[str] = []

    class Registry:
        def __init__(self, root: str) -> None:
            roots.append(root)

        def list(self, *, include_disabled: bool) -> list[SimpleNamespace]:
            assert include_disabled is False
            return [
                SimpleNamespace(
                    tenant_id="tenant-live",
                    subscription_id="subscription-live",
                    connection_id="connection-live",
                    is_active=True,
                )
            ]

    monkeypatch.setattr(registry, "ConnectionRegistry", Registry)
    OneLakeDocumentStore(gold_root).write(
        "exposure/gold-generation-pointer.json",
        {"readable_generation_id": "generation-live"},
        expected_revision=0,
    )

    authorization, generation = derive_live_benchmark_inputs()

    assert roots == [(connection_home or "").strip() or gold_root]
    assert authorization.tenant_id == "tenant-live"
    assert authorization.connection_ids == ("connection-live",)
    assert generation == "generation-live"


def test_live_benchmark_surfaces_pointer_read_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from onboarding import registry
    from storage.onelake_documents import OneLakeDocumentStore

    monkeypatch.setenv("AIOPS_HOME", str(tmp_path))
    monkeypatch.setattr(
        registry,
        "ConnectionRegistry",
        lambda root: SimpleNamespace(
            list=lambda **kwargs: [
                SimpleNamespace(
                    tenant_id="tenant-live",
                    subscription_id="subscription-live",
                    connection_id="connection-live",
                    is_active=True,
                )
            ]
        ),
    )

    def denied(self: OneLakeDocumentStore, name: str) -> dict[str, Any]:
        raise PermissionError("pointer read denied")

    monkeypatch.setattr(OneLakeDocumentStore, "read_or_raise", denied)
    with pytest.raises(PermissionError, match="pointer read denied"):
        derive_live_benchmark_inputs()


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
