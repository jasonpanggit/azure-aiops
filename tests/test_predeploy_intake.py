"""Bounded artifact intake, provenance and conservative redaction semantics."""

import json

import pytest

from api.scope import Scope
from intelligence.predeploy.intake import MAX_BYTES, REDACTED, inspect_artifact
from intelligence.predeploy.models import CHANGE_SOURCES
from intelligence.predeploy.service import PreDeploymentImpactService


@pytest.mark.parametrize("source", CHANGE_SOURCES)
def test_sources_keep_unknown_fragments_and_empty_artifacts(source):
    result = inspect_artifact(source, {})
    assert len(result["sha256"]) == 64
    assert result["source"] == source
    assert result["withheld_value_count"] == 0


@pytest.mark.parametrize("key", [
    "password", "CLIENT_SECRET", "access-token", "privateKey", "connection_string",
    "Authorization", "accountKey", "sas", "api_key", "sharedKey", "credentials",
])
def test_known_sensitive_keys_are_rejected_without_echoing_values(key):
    with pytest.raises(ValueError, match="redacted locally") as error:
        inspect_artifact("terraform_plan", {"settings": {key: "fixture-private-value"}})
    assert "fixture-private-value" not in str(error.value)


@pytest.mark.parametrize("payload", [
    {"settings": [{"name": "DB_PASSWORD", "value": "fixture-private-value"}]},
    {"change": {"before": {"custom": "fixture-private-value"}, "before_sensitive": {"custom": True}}},
    {"change": {"after": [{"custom": "fixture-private-value"}], "after_sensitive": [{"custom": True}]}},
    {"change": {"after": {"custom": "fixture-private-value"}, "after_sensitive": True}},
])
def test_named_environment_values_and_terraform_masks(payload):
    with pytest.raises(ValueError, match="redacted locally"):
        inspect_artifact("terraform_plan", payload)


def test_masks_are_metadata_not_credentials_and_redaction_is_idempotent():
    payload = {"change": {
        "after": {"password": REDACTED, "custom": REDACTED},
        "after_sensitive": {"password": True, "custom": True},
    }}
    result = inspect_artifact("terraform_plan", payload)
    assert result["withheld_value_count"] == 2
    assert result == inspect_artifact("terraform_plan", json.loads(json.dumps(payload)))
    assert "password" not in json.dumps(result)


@pytest.mark.parametrize("payload", [
    {"resource_changes": {}}, {"resource_changes": [42]},
    {"change": {"after_sensitive": {"custom": "fixture-private-value"}}},
    {"large": float("inf")}, {"large": float("nan")}, {"large": 10**400},
    {"unicode": "\ud800"}, {"\udfff": "value"}, {"x" * 257: "value"},
])
def test_invalid_structures_fail_explicitly(payload):
    with pytest.raises(ValueError):
        inspect_artifact("terraform_plan", payload)


@pytest.mark.parametrize(("source", "payload"), [
    ("terraform_plan", {"resource_changes": [{}] * 501}),
    ("github_pull_request", {"files": [{}] * 501}),
    ("azure_devops", {"changes": [{}] * 501}),
    ("bicep_what_if", {"properties": {"changes": [{}] * 501}}),
    ("arm_diff", {"changes": [{}] * 501}),
    ("bicep_what_if", {"properties": []}),
    ("arm_diff", {"properties": {"changes": "invalid"}}),
])
def test_all_source_array_boundaries(source, payload):
    with pytest.raises(ValueError):
        inspect_artifact(source, payload)


def test_actual_utf8_byte_boundary_and_exact_cardinality():
    # {"x":""} is eight UTF-8 bytes; Unicode, not character count, sets the limit.
    exact = {"x": "é" * ((MAX_BYTES - 8) // 2)}
    assert inspect_artifact("terraform_plan", exact)["utf8_bytes"] == MAX_BYTES
    with pytest.raises(ValueError, match="2 MiB"):
        inspect_artifact("terraform_plan", {"x": exact["x"] + "é"})
    inspect_artifact("terraform_plan", {"resource_changes": [{}] * 500})
    inspect_artifact("terraform_plan", {"x": [None] * 49_998})
    with pytest.raises(ValueError, match="50000"):
        inspect_artifact("terraform_plan", {"x": [None] * 49_999})


def test_exact_depth_boundary():
    payload = {"x": None}
    for _ in range(23):
        payload = {"x": payload}
    inspect_artifact("terraform_plan", payload)
    with pytest.raises(ValueError, match="24-level"):
        inspect_artifact("terraform_plan", {"x": payload})


def test_digest_binds_values_and_source_not_key_order_and_retains_no_payload():
    left = inspect_artifact("terraform_plan", {"b": 2, "a": 1})
    assert left == inspect_artifact("terraform_plan", {"a": 1, "b": 2})
    assert left["sha256"] != inspect_artifact("terraform_plan", {"a": 3, "b": 2})["sha256"]
    assert left["sha256"] != inspect_artifact("arm_diff", {"a": 1, "b": 2})["sha256"]
    assert "payload" not in left


def test_redacted_values_never_become_high_confidence_or_approval():
    resource = {"resource_id": "/subscriptions/sub-a/rg/test", "name": "test"}
    payload = {"resource_changes": [{
        "address": "example.test", "type": "example",
        "change": {"actions": ["update"],
                   "before": {"id": resource["resource_id"], "password": REDACTED},
                   "after": {"id": resource["resource_id"], "password": REDACTED},
                   "before_sensitive": {"password": True}, "after_sensitive": {"password": True}},
    }]}
    service = PreDeploymentImpactService()
    result = service.assess(source="terraform_plan", payload=payload, discovered=[resource], scope=Scope())
    assert result["artifact"]["withheld_value_count"] == 2
    assert result["risk"]["confidence"] == "low"
    assert any("redaction" in item for item in result["risk"]["unknowns"])
    assert result["cab_recommendation"]["verdict"] == "require_review"
    assert "before_sensitive" not in json.dumps(service.get_assessment(result["assessment_id"]))


def test_invalid_root_and_source():
    with pytest.raises(TypeError, match="JSON object"):
        inspect_artifact("terraform_plan", [])
    with pytest.raises(ValueError, match="source"):
        inspect_artifact("unknown", {})
