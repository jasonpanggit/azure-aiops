from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.rbac import Authorizer, Grant, Principal
from api.scope import Scope
from api.telemetry import ApiTelemetry
from intelligence.inventory import InventoryService
from intelligence.inventory.eol_repository import LocalEOLCatalogRepository
from intelligence.inventory.eol_review import (
    CandidateResolver,
    EOLReviewService,
    UnavailableLifecycleSearchProvider,
)
from intelligence.inventory.mapping_repository import SoftwareMappingRepository
from intelligence.inventory.software_normalization import normalize_configuration_data
from onboarding.service import SubscriptionOnboardingService

TOKEN = "inventory-token-0123456789"
READER_TOKEN = "inventory-reader-012345"
FIXTURE = Path(__file__).parent / "fixtures" / "mock_inventory_arg.json"
SOFTWARE_FIXTURE = Path(__file__).parent / "fixtures" / "mock_configurationdata.json"


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    review_service = EOLReviewService(
        LocalEOLCatalogRepository(tmp_path / "eol.json"),
        CandidateResolver(
            endoflife_fetch=lambda *_: (
                {
                    "date": "2030-01-01",
                    "citation": "https://endoflife.date/api/windows-server.json",
                    "retrieved_at": "2026-08-26T00:00:00Z",
                    "extracted_claim": "endoflife.date claim",
                    "confidence": 0.8,
                },
            ),
            official_vendor_fetch=lambda *_: (),
            web_search_fetch=UnavailableLifecycleSearchProvider().resolve,
        ),
    )
    os_service = InventoryService.from_fixture(FIXTURE, eol_review=review_service)
    software_rows = json.loads(SOFTWARE_FIXTURE.read_text(encoding="utf-8"))
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["software_observations"] = [
        row.to_dict()
        for row in normalize_configuration_data(software_rows, os_service.snapshot.observations)
    ]
    payload["software_mapping_suggestions"] = [
        {
            "raw_name": "Reviewable Agent",
            "raw_version": "v3.2",
            "publisher": "Contoso",
            "source_timestamp": "2026-08-26T00:00:00Z",
            "scope_predicate": {"subscription": ["sub-a"]},
            "model_output": {
                "canonical_name": "Reviewable Agent",
                "canonical_version": "3.2",
                "confidence": 0.86,
                "provenance": {"model": "approved-normalizer"},
            },
        }
    ]
    payload["software_source_status"] = {"logs": {"state": "ready", "query_version": "inventory-software-v1"}}
    mapping_repository = SoftwareMappingRepository(tmp_path / "software-mappings.json")
    context = ApiContext(
        onboarding=SubscriptionOnboardingService(tmp_path / "aiops"),
        authenticator=StaticTokenAuthenticator(
            {
                TOKEN: Principal(subject="operator@example.com", grants=(Grant("admin"),)),
                READER_TOKEN: Principal(
                    subject="reader@example.com",
                    grants=(Grant("reader", Scope.from_mapping({"subscription": ["sub-b"]})),),
                ),
            }
        ),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        inventory_provider=lambda: InventoryService(
            payload,
            eol_review=review_service,
            mapping_repository=mapping_repository,
        ),
    )
    return TestClient(create_app(context), raise_server_exceptions=False)


def _auth() -> dict[str, str]:
    return {"Authorization": "Bearer " + TOKEN}


def test_os_collection_is_scoped_before_grouping(client: TestClient) -> None:
    response = client.get(
        "/api/v1/inventory/os",
        params={"subscription": "sub-a", "limit": 100},
        headers=_auth(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["scope"] == {"subscription": ["sub-a"]}
    assert body["pagination"] == {"offset": 0, "limit": 100, "total": 3, "next_offset": None}
    windows = next(group for group in body["data"]["groups"] if group["key"] == "Windows Server|2019")
    assert windows["machine_count"] == 2
    assert body["data"]["source_status"]["arc"]["state"] == "partial"


def test_detail_rejects_invalid_key_and_does_not_accept_machine_list(client: TestClient) -> None:
    invalid = client.get("/api/v1/inventory/os/not-a-group", headers=_auth())
    assert invalid.status_code == 400

    valid = client.get(
        "/api/v1/inventory/os/Windows%20Server%7C2019",
        params={"subscription": "sub-a", "machines": "forged"},
        headers=_auth(),
    )
    assert valid.status_code == 200
    assert all("forged" not in row["resource_id"] for row in valid.json()["data"]["machines"])


def test_detail_scope_isolation_and_unknown_review_state(client: TestClient) -> None:
    response = client.get(
        "/api/v1/inventory/os/Windows%20Server%7C2099-preview",
        params={"subscription": "sub-a"},
        headers=_auth(),
    )
    assert response.status_code == 200
    machine = response.json()["data"]["machines"][0]
    assert machine["review_required"] is True
    assert machine["environment"] == "dev"

    outside = client.get(
        "/api/v1/inventory/os/Windows%20Server%7C2019",
        params={"subscription": "sub-c"},
        headers=_auth(),
    )
    assert outside.status_code == 404


def test_software_routes_return_canonical_exact_details_and_unlinked_status(
    client: TestClient,
) -> None:
    response = client.get(
        "/api/v1/inventory/software",
        params={"subscription": "sub-a"},
        headers=_auth(),
    )
    assert response.status_code == 200
    body = response.json()
    seven_zip = next(group for group in body["data"]["groups"] if group["key"] == "7-Zip|19.00")
    assert seven_zip["install_count"] == 1
    assert body["data"]["source_status"]["logs"]["state"] == "ready"

    detail = client.get(
        "/api/v1/inventory/software/7-Zip%7C19.00",
        params={"subscription": "sub-a"},
        headers=_auth(),
    )
    assert detail.status_code == 200
    machine = detail.json()["data"]["machines"][0]
    assert machine["environment"] == "prod"
    assert machine["resource_join_status"] == "linked"
    assert machine["raw_identity"]["name"] == "7-Zip v19.00"

    assert client.get(
        "/api/v1/inventory/software/7-Zip%7C18.00",
        params={"subscription": "sub-a"},
        headers=_auth(),
    ).status_code == 404


def test_lifecycle_route_returns_cited_candidates_and_confirms_explicitly(
    client: TestClient,
) -> None:
    review = client.get(
        "/api/v1/inventory/os/Windows%20Server%7C2099-preview/lifecycle",
        params={"subscription": "sub-a"},
        headers=_auth(),
    )
    assert review.status_code == 200
    body = review.json()["data"]
    assert body["status"] == "review_required"
    assert body["normalized_os_key"] == "windows server|2099-preview"
    assert body["candidates"][0]["candidate_id"]
    assert body["candidates"][0]["citation"].startswith("https://")
    assert body["candidates"][0]["retrieved_at"]
    assert body["candidates"][0]["extracted_claim"]
    assert body["source_failures"][0]["source_kind"] == "web_search"
    assert body["source_failures"][0]["code"] == "provider_not_configured"

    confirmed = client.post(
        "/api/v1/inventory/os/Windows%20Server%7C2099-preview/lifecycle/confirm",
        params={"subscription": "sub-a"},
        headers=_auth(),
        json={
            "normalized_os_key": body["normalized_os_key"],
            "expected_revision": body["catalog_revision"],
            "candidate_id": body["candidates"][0]["candidate_id"],
        },
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["data"]["status"] == "confirmed"

    stale = client.post(
        "/api/v1/inventory/os/Windows%20Server%7C2099-preview/lifecycle/confirm",
        params={"subscription": "sub-a"},
        headers=_auth(),
        json={
            "normalized_os_key": body["normalized_os_key"],
            "expected_revision": body["catalog_revision"],
            "manual_date": "2031-01-01",
        },
    )
    assert stale.status_code == 409


def test_lifecycle_reads_require_auth_and_mutations_require_operate_scope(
    client: TestClient,
) -> None:
    path = "/api/v1/inventory/os/Windows%20Server%7C2099-preview/lifecycle"
    assert client.get(path).status_code == 401
    assert client.get(
        path,
        params={"subscription": "sub-a"},
        headers={"Authorization": f"Bearer {READER_TOKEN}"},
    ).status_code == 403

    response = client.post(
        path + "/confirm",
        headers={"Authorization": f"Bearer {READER_TOKEN}"},
        json={
            "normalized_os_key": "windows server|2099-preview",
            "expected_revision": 0,
            "manual_date": "2030-01-01",
        },
    )
    assert response.status_code == 403


def test_lifecycle_confirmation_rejects_extra_fields_and_malformed_dates(
    client: TestClient,
) -> None:
    path = "/api/v1/inventory/os/Windows%20Server%7C2099-preview/lifecycle/confirm"
    extra = client.post(
        path,
        headers=_auth(),
        json={
            "normalized_os_key": "windows server|2099-preview",
            "expected_revision": 0,
            "manual_date": "2030-01-01",
            "untrusted": "ignored",
        },
    )
    assert extra.status_code == 400

    malformed = client.post(
        path,
        headers=_auth(),
        json={
            "normalized_os_key": "windows server|2099-preview",
            "expected_revision": 0,
            "manual_date": "not-a-date",
        },
    )
    assert malformed.status_code == 400


def test_mapping_list_decision_is_scoped_audited_and_revision_checked(
    client: TestClient,
) -> None:
    listed = client.get(
        "/api/v1/inventory/software/mappings",
        params={"subscription": "sub-a"},
        headers=_auth(),
    )
    assert listed.status_code == 200
    mapping = listed.json()["data"]["mappings"][0]
    assert mapping["status"] == "suggested"
    assert mapping["provenance"]["model"] == "approved-normalizer"

    outside = client.get(
        "/api/v1/inventory/software/mappings",
        params={"subscription": "sub-b"},
        headers=_auth(),
    )
    assert outside.status_code == 200
    assert outside.json()["data"]["mappings"] == []

    approved = client.post(
        "/api/v1/inventory/software/mappings/approve",
        params={"subscription": "sub-a"},
        headers=_auth(),
        json={
            "mapping_id": mapping["mapping_id"],
            "expected_revision": mapping["revision"],
            "reason": "Verified vendor identity",
        },
    )
    assert approved.status_code == 200
    body = approved.json()["data"]
    assert body["status"] == "approved"
    assert body["revision"] == 1
    assert body["provenance"]["reviewer"] == "operator@example.com"
    assert body["provenance"]["scope_snapshot"] == {"subscription": ["sub-a"]}

    stale = client.post(
        "/api/v1/inventory/software/mappings/reject",
        params={"subscription": "sub-a"},
        headers=_auth(),
        json={"mapping_id": mapping["mapping_id"], "expected_revision": 0},
    )
    assert stale.status_code == 409

    reader = client.post(
        "/api/v1/inventory/software/mappings/reject",
        params={"subscription": "sub-b"},
        headers={"Authorization": "Bearer " + READER_TOKEN},
        json={"mapping_id": mapping["mapping_id"], "expected_revision": 1},
    )
    assert reader.status_code == 403


def test_inventory_narrative_returns_fact_only_fallback_with_scoped_sources(
    client: TestClient,
) -> None:
    response = client.get(
        "/api/v1/inventory/narrative",
        params={"subscription": "sub-a"},
        headers=_auth(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["status"] == "fact_only"
    assert body["data"]["narrated_summary"] is None
    assert "4 machines" in body["data"]["fact_summary"]
    assert body["data"]["source_status"]["arc"]["row_count"] == 2
    assert any("no Foundry" in warning for warning in body["warnings"])
    assert all("resource_id" not in str(item) for item in body["data"]["citations"])


def test_inventory_narrative_sends_only_aggregates_and_preserves_facts(
    client: TestClient,
) -> None:
    captured: dict[str, object] = {}

    class FakeNarrator:
        def answer(self, *, question: str, context: dict[str, object]):
            from operations.foundry_agent import AgentAnswer

            captured["question"] = question
            captured["context"] = context
            return AgentAnswer(
                text="Prioritize review of the scoped lifecycle facts.",
                agent_name="inventory-risk-agent",
                model="test-model",
            )

    client.app.state.context.foundry_agent_provider = lambda: FakeNarrator()
    response = client.get(
        "/api/v1/inventory/narrative",
        params={"subscription": "sub-a"},
        headers=_auth(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["status"] == "narrated"
    assert body["data"]["narrated_summary"].startswith("Prioritize")
    context = captured["context"]
    assert isinstance(context, dict)
    serialized = json.dumps(context)
    assert "sub-b" not in serialized
    assert "vm-" not in serialized
    assert "web-01" not in serialized
    assert "Reviewable Agent" not in serialized
    assert "fact_summary" in serialized


def test_inventory_narrative_timeout_and_malformed_output_are_fact_only(
    client: TestClient,
) -> None:
    class TimeoutNarrator:
        def answer(self, **_kwargs):
            raise TimeoutError("timed out")

    client.app.state.context.foundry_agent_provider = lambda: TimeoutNarrator()
    response = client.get("/api/v1/inventory/narrative", headers=_auth())
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "fact_only"
    assert any("Foundry prompt agent failed" in warning for warning in response.json()["warnings"])

    class MalformedNarrator:
        def answer(self, **_kwargs):
            return object()

    client.app.state.context.foundry_agent_provider = lambda: MalformedNarrator()
    response = client.get(
        "/api/v1/inventory/narrative",
        params={"business_service": "not-authorized-inventory-field"},
        headers=_auth(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["status"] == "fact_only"
    assert body["data"]["fact_summary"].startswith("0 machines across 0 OS groups")
    assert any("Foundry prompt agent failed" in warning for warning in body["warnings"])
