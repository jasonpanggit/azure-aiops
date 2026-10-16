"""Independent change reads, authorization-before-counts and safe state comparisons."""

from copy import deepcopy

import pytest
from change_scenario import change_engine
from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.rbac import Authorizer, Grant, Principal
from api.scope import Scope
from api.telemetry import ApiTelemetry
from onboarding.service import SubscriptionOnboardingService

TOKEN = "changes-admin-token-0123456789"
READER = "changes-reader-token-012345678"


@pytest.fixture
def setup(tmp_path):
    engine = change_engine(max_output_items=1)
    context = ApiContext(
        onboarding=SubscriptionOnboardingService(tmp_path / "state"),
        authenticator=StaticTokenAuthenticator(
            {
                TOKEN: Principal("admin", grants=(Grant("admin"),)),
                READER: Principal(
                    "reader",
                    grants=(Grant("reader", Scope({"subscription": ["sub-2"]})),),
                ),
            }
        ),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        change_provider=lambda: engine,
        incident_provider=lambda: pytest.fail(
            "Independent feed must not resolve incidents"
        ),
    )
    return (
        TestClient(create_app(context), raise_server_exceptions=False),
        context,
        engine,
    )


def read(setup, params=None, token=TOKEN):
    return setup[0].get(
        "/api/v1/changes/observations",
        params=params,
        headers={"Authorization": f"Bearer {token}"},
    )


def test_independent_feed_does_not_inherit_engine_public_output_cap(setup):
    response = read(setup)
    assert response.status_code == 200
    body = response.json()
    assert len(body["data"]["observations"]) == body["pagination"]["total"] == 4
    assert body["data"]["authorized_count"] == 4
    assert body["evidence"][0]["source_table"] == "independent_change_observations"
    assert body["data"]["extent"] == "loaded_change_projection"
    assert body["data"]["read_only"] is True
    assert "resource_key" not in response.text
    assert "/subscriptions/" not in response.text


def test_scoped_membership_precedes_facets_counts_and_query(setup):
    body = read(setup, token=READER).json()
    assert body["data"]["observations"] == []
    assert body["data"]["facets"] == {"source": [], "category": []}
    assert body["data"]["authorized_count"] == body["pagination"]["total"] == 0
    assert "Payments" not in str(body)
    response = read(setup, {"business_service": "not granted"}, token=READER)
    assert response.json()["data"]["observations"] == []


def test_filters_counts_paging_and_inclusive_timezone_range(setup):
    body = read(setup, {"category": "Platform", "limit": 1}).json()
    assert body["pagination"]["total"] == len(body["data"]["observations"]) == 1
    assert len(body["data"]["facets"]["category"]) == 3
    assert body["data"]["authorized_count"] == 4
    exact = {"since": "2026-08-18T14:00:00+02:00", "until": "2026-08-18T12:00:00Z"}
    assert read(setup, exact).json()["pagination"]["total"] == 1
    assert read(setup, {"q": "terraform"}).json()["pagination"]["total"] == 1
    assert read(setup, {"source": "absent"}).json()["pagination"]["total"] == 0
    assert read(setup, {"offset": 4}).json()["data"]["observations"] == []


def test_stable_oldest_newest_paging_above_existing_output_cap(setup):
    engine = setup[2]
    first = deepcopy(engine.changes[0])
    engine.changes = [{**first, "change_id": f"CHG-{index:03}"} for index in range(125)]
    body = read(setup, {"order": "oldest", "offset": 100, "limit": 25}).json()
    assert body["pagination"]["total"] == 125
    assert len(body["data"]["observations"]) == 25
    assert body["data"]["observations"][0]["change_id"] == "CHG-100"
    assert len({row["observation_id"] for row in body["data"]["observations"]}) == 25
    assert (
        read(setup, {"order": "newest", "limit": 1}).json()["data"]["observations"][0][
            "change_id"
        ]
        == "CHG-124"
    )


@pytest.mark.parametrize(
    "params",
    [
        {"since": "not a date"},
        {"since": "2026-08-18"},
        {"until": "2026-08-18T12:00:00"},
        {"since": "2026-08-19T00:00:00Z", "until": "2026-08-18T00:00:00Z"},
        {"order": "random"},
        {"limit": 101},
        {"offset": -1},
        {"q": "x" * 201},
    ],
)
def test_invalid_continuations_fail_explicitly(setup, params):
    assert read(setup, params).status_code == 400


def test_typed_configuration_states_withhold_unknown_keys_and_values(setup):
    change = setup[2].changes[0]
    change.update(
        previous_state={
            "httpsOnly": False,
            "sku": "Standard_D2s_v5",
            "encryption": "Enabled",
            "password-private-key-name": "secret-before",
        },
        current_state={
            "httpsOnly": True,
            "sku": "Standard_D4s_v5",
            "encryption": "Enabled",
            "publicNetworkAccess": "invalid-secret-after",
            "minimumTlsVersion": {"secret": "nested"},
            "password-private-key-name": "secret-after",
        },
        changed_fields=["httpsOnly", "publicNetworkAccess", "unreported-private-path"],
    )
    response = read(setup, {"q": "CHG-100"})
    result = response.json()["data"]["observations"][0]["configuration"]
    fields = {row["field"]: row for row in result["fields"]}
    assert fields["httpsOnly"]["before"] == {"status": "reported", "value": False}
    assert fields["httpsOnly"]["comparison"] == fields["sku"]["comparison"] == "changed"
    assert fields["encryption"]["comparison"] == "unchanged"
    assert fields["publicNetworkAccess"]["before"] == {"status": "unreported"}
    assert fields["publicNetworkAccess"]["after"] == {"status": "withheld"}
    assert fields["minimumTlsVersion"]["comparison"] == "not_comparable"
    assert result["withheld_field_count"] == 2
    assert "secret" not in response.text
    assert "private" not in response.text
    assert "password" not in response.text


def test_missing_states_are_not_baseline_or_deletion_evidence(setup):
    body = read(setup).json()["data"]["observations"]
    assert all(row["configuration"]["basis"] == "change_states" for row in body)
    changed = next(row for row in body if row["change_id"] == "CHG-100")
    assert all(
        field["comparison"] == "not_comparable"
        for field in changed["configuration"]["fields"]
    )
    assert all(
        field["before"]["status"] == "unreported"
        for field in changed["configuration"]["fields"]
    )


def test_unavailable_provider_and_authentication_are_not_empty_success(setup):
    setup[1].change_provider = lambda: None
    assert read(setup).status_code == 503
    assert setup[0].get("/api/v1/changes/observations").status_code == 401


def test_unavailable_connection_is_rejected_before_resolving_provider(
    setup, monkeypatch
):
    setup[1].change_provider = lambda: pytest.fail(
        "Membership must precede provider resolution"
    )
    monkeypatch.setattr(
        setup[1].onboarding,
        "list",
        lambda **_: [
            {
                "connection_id": "private",
                "subscription_id": "sub-1",
            }
        ],
    )
    assert (
        read(setup, {"subscription_connection": "private"}, token=READER).status_code
        == 404
    )
    assert read(setup, {"subscription_connection": "missing"}).status_code == 404


def test_authorized_connection_membership_narrows_projection(setup, monkeypatch):
    monkeypatch.setattr(
        setup[1].onboarding,
        "list",
        lambda **_: [
            {
                "connection_id": "selected",
                "subscription_id": "sub-2",
            }
        ],
    )
    body = read(setup, {"subscription_connection": "selected"}).json()
    assert body["data"]["authorized_count"] == 0
    assert body["data"]["facets"]["source"] == []


def test_source_observation_identity_survives_redacted_id_collisions_and_paging(setup):
    first = deepcopy(setup[2].changes[0])
    setup[2].changes = [first, deepcopy(first)]
    body = read(setup).json()["data"]["observations"]
    assert len({row["observation_id"] for row in body}) == 2
    paged = read(setup, {"offset": 1, "limit": 1}).json()["data"]["observations"][0]
    assert paged["observation_id"] == body[1]["observation_id"]


def test_source_suggestion_cap_does_not_cap_filter_results(setup):
    first = deepcopy(setup[2].changes[0])
    setup[2].changes = [
        {**first, "change_id": f"C-{i}", "source": f"Source {i:03}"} for i in range(101)
    ]
    body = read(setup, {"source": "Source 100"}).json()
    assert body["data"]["facet_metadata"]["source"] == {
        "total": 101,
        "returned": 100,
        "truncated": True,
    }
    assert len(body["data"]["facets"]["source"]) == 100
    assert body["pagination"]["total"] == 1
    assert body["data"]["observations"][0]["source"] == "Source 100"


def test_serialized_data_bound_never_silently_truncates(setup):
    first = deepcopy(setup[2].changes[0])
    setup[2].changes = [{**first, "change_id": f"C-{i}"} for i in range(100)]
    resource = setup[2].context_builder._resources[first["resource_key"]]
    for field in ("business_service", "application", "environment"):
        resource[field] = "\u4e2d" * 512
    resource["resource"]["name"] = "\u4e2d" * 512
    assert read(setup, {"limit": 100}).status_code == 400
    assert read(setup, {"limit": 25}).status_code == 200


def test_actual_resourcechanges_property_paths_stay_distinct_and_typed(setup):
    change = setup[2].changes[0]
    change.update(
        previous_state={
            "properties.publicNetworkAccess": "Disabled",
            "properties.hardwareProfile.vmSize": "Standard_D2s_v5",
            "properties.httpsOnly": False,
            "httpsOnly": True,
        },
        current_state={
            "properties.publicNetworkAccess": "Enabled",
            "properties.hardwareProfile.vmSize": "Standard_D4s_v5",
            "properties.httpsOnly": True,
            "httpsOnly": True,
            "properties.credentials.password": "must-not-leave-source",
        },
    )
    response = read(setup, {"q": change["change_id"]})
    fields = {
        item["field"]: item
        for item in response.json()["data"]["observations"][0]["configuration"][
            "fields"
        ]
    }
    assert fields["properties.publicNetworkAccess"]["comparison"] == "changed"
    assert (
        fields["properties.hardwareProfile.vmSize"]["after"]["value"]
        == "Standard_D4s_v5"
    )
    assert fields["properties.httpsOnly"]["comparison"] == "changed"
    assert fields["httpsOnly"]["comparison"] == "unchanged"
    assert "credentials" not in response.text
    assert "must-not-leave-source" not in response.text
