"""Synthetic structural checks; none of these fixtures grants live authority."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from ontology_discovery.isolated_acceptance_contract import (
    ContractError,
    contract_digest,
    load_contract,
    require_qualified_contract,
)

HASH = "sha256:" + "a" * 64
UUID = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
BASE = f"abfss://{UUID}@onelake.dfs.fabric.microsoft.com/{UUID}"
PROTECTED = f"abfss://{OTHER}@onelake.dfs.fabric.microsoft.com/{OTHER}"
ARM = f"/subscriptions/{UUID}/resourceGroups/synthetic/providers/Microsoft.App"
ROLES = (
    "api",
    "web",
    "coordinator",
    "rbac_validator",
    "fixture_prepare",
    "fixture_cleanup",
    "evidence",
    "validation_publisher",
    "production_publisher",
)
JOBS = ROLES[2:-1]
CONSUMERS = ("api", "fabric", "agent", "export", "semantic")


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def fixture():
    artifacts = {}

    def ref(name, value):
        body = encoded(value)
        artifacts[name] = body
        return {"key": name, "sha256": "sha256:" + hashlib.sha256(body).hexdigest()}

    roots = {
        name: f"{BASE}/Files/validation/{name}"
        for name in (
            "connection",
            "state",
            "command",
            "dispatch",
            "publication",
            "fixture",
            "drill",
        )
    }
    materialization = {
        "workspace_id": UUID,
        "lakehouse_id": UUID,
        "tables": [{"schema_name": "validation", "table_name": "entities"}],
        "native_enabled": True,
        "native_item_ids": [UUID],
    }
    consumers = {
        name: {
            "resource_id": f"synthetic-{name}",
            "publication_root": roots["publication"],
            "materialization_fingerprint": "sha256:"
            + hashlib.sha256(encoded(materialization)).hexdigest(),
        }
        for name in CONSUMERS
    }
    expected_target = dict.fromkeys(
        (
            "tenant_id",
            "subscription_id",
            "connection_id",
            "workspace_id",
            "item_id",
        ),
        UUID,
    )
    expected_target["definition_fingerprint"] = HASH
    resolved = {
        "roots": roots,
        "materialization": materialization,
        "consumers": consumers,
        "maintenance_target": expected_target,
    }
    pins = {
        role: f"synthetic.invalid/worker@sha256:{i:064x}"
        for i, role in enumerate(ROLES, 1)
    }
    jobs = {
        role: {
            "resource_id": f"{ARM}/jobs/synthetic-{role.replace('_', '-')}",
            "identity_resource_id": (
                f"/subscriptions/{UUID}/resourceGroups/synthetic"
                "/providers/Microsoft.ManagedIdentity/userAssignedIdentities/publisher"
            ),
            "client_id": UUID,
            "image": pins[role],
            "template": ref(f"template-{role}", {"synthetic": role}),
            "runtime_job_start": False,
        }
        for role in JOBS
    }
    protected = {
        "publisher_resource_id": f"{ARM}/jobs/production",
        "api_resource_id": f"{ARM}/containerApps/production-api",
        "publisher_client_id": UUID,
        "publisher_image": pins["production_publisher"],
        "api_image": pins["api"],
        "api_preimage": ref("api-freeze", {"freeze": "current-api-only"}),
        "publisher_preimage": ref("production-freeze", {"freeze": "current-only"}),
        "roots": [f"{PROTECTED}/Files/production"],
        "materialization": {
            "workspace_id": OTHER,
            "lakehouse_id": OTHER,
            "tables": [{"schema_name": "dbo", "table_name": "entities"}],
            "native_enabled": True,
            "native_item_ids": [OTHER],
        },
        "historical_divergence": "unresolved",
    }
    payload = {
        "schema_version": "isolated-acceptance/v1",
        "purpose": "offline-contract-validation",
        "authority": "none",
        "status": "reviewed",
        "source_sha": "1" * 40,
        "contract_digest": HASH,
        "tenant_id": UUID,
        "subscription_id": UUID,
        "production_plan": ref("production-plan", {"synthetic": "production"}),
        "validation_plan": ref("validation-plan", {"synthetic": "validation"}),
        "terraform_state": ref("state", {"synthetic": "state"}),
        "review": ref("review", {"synthetic": "review"}),
        "image_pins": pins,
        "jobs": jobs,
        "protected": protected,
        "resolved": resolved,
        "resolved_config": ref("resolved-config", resolved),
        "maintenance_authorizer": ref("authorizer", {"synthetic": "authorizer"}),
        "maintenance_observers": ref("observers", {"synthetic": "observers"}),
        "drill_templates": {
            name: ref(f"drill-{name}", {"synthetic": name})
            for name in ("arm", "inspect", "resume", "cleanup")
        },
    }
    payload["contract_digest"] = contract_digest(payload)
    return payload, artifacts


def load(tmp_path, payload, artifacts, *, resign=True):
    if resign:
        payload["contract_digest"] = contract_digest(payload)
    path = tmp_path / "synthetic.json"
    path.write_bytes(encoded(payload))
    return load_contract(path, artifacts=artifacts)


def test_reviewed_distinct_role_pins_are_structural_only(tmp_path):
    payload, artifacts = fixture()
    result = load(tmp_path, payload, artifacts)
    assert result.status == "reviewed"
    assert result.authority == "none"
    with pytest.raises(ContractError, match="qualified"):
        require_qualified_contract(tmp_path / "synthetic.json", artifacts=artifacts)


def test_draft_parses_without_review_or_qualification(tmp_path):
    payload = {
        "schema_version": "isolated-acceptance/v1",
        "purpose": "offline-contract-validation",
        "authority": "none",
        "status": "draft",
        "source_sha": "1" * 40,
        "contract_digest": HASH,
        "unresolved_fields": ["jobs", "materialization"],
    }
    assert load(tmp_path, payload, {}).status == "draft"
    with pytest.raises(ContractError, match="qualified"):
        require_qualified_contract(tmp_path / "synthetic.json", artifacts={})


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.update(schema_version="isolated-acceptance/v2"),
        lambda p: p.update(status="observed"),
        lambda p: p.update(authority="execute"),
        lambda p: p.update(status="qualified"),
        lambda p: p.update(unknown=True),
        lambda p: p["jobs"]["coordinator"].update(runtime_job_start=0),
        lambda p: p["jobs"].pop("evidence"),
        lambda p: p["image_pins"].update(extra="x"),
        lambda p: p["jobs"]["coordinator"].update(image=p["image_pins"]["api"]),
        lambda p: p["jobs"]["validation_publisher"].update(
            resource_id=p["protected"]["publisher_resource_id"]
        ),
        lambda p: p["jobs"]["validation_publisher"].update(runtime_job_start=True),
        lambda p: p["protected"].update(publisher_image=p["image_pins"]["api"]),
        lambda p: p["resolved"]["maintenance_target"].update(extra="x"),
        lambda p: p["resolved"]["consumers"].pop("semantic"),
        lambda p: p["resolved"]["consumers"]["agent"].update(
            resource_id="synthetic-api"
        ),
        lambda p: p["resolved"]["materialization"].update(workspace_id=OTHER),
    ],
)
def test_rejects_contract_substitution(tmp_path, mutate):
    payload, artifacts = fixture()
    mutate(payload)
    with pytest.raises(ContractError):
        load(tmp_path, payload, artifacts)


@pytest.mark.parametrize(
    "suffix",
    [
        "/Files/validation/connection",
        "/Files/validation/connection/",
        "/Files/validation/connection/child",
        "/Files/validation",
        "/Files/validation/%2fchild",
        "/Files/validation/%2e%2e/child",
        "/Files/validation/../child",
        "/Files/validation/child?x=1",
        "/Files/validation/child#x",
        "/Files//validation/child",
        "/Files/validation/a\nb",
        "/Files/validation/%252fchild",
        "/Files/validation/a\\b",
    ],
)
def test_rejects_root_aliases_and_ambiguous_paths(tmp_path, suffix):
    payload, artifacts = fixture()
    payload["resolved"]["roots"]["state"] = BASE + suffix
    with pytest.raises(ContractError):
        load(tmp_path, payload, artifacts)


def test_rejects_protected_root_even_with_separate_files_namespace(tmp_path):
    payload, artifacts = fixture()
    payload["resolved"]["roots"]["drill"] = PROTECTED + "/Files/production/canary"
    with pytest.raises(ContractError):
        load(tmp_path, payload, artifacts)


@pytest.mark.parametrize(
    "key", ["template-coordinator", "production-freeze", "resolved-config"]
)
def test_rejects_stale_or_missing_referenced_bytes(tmp_path, key):
    payload, artifacts = fixture()
    artifacts[key] += b" "
    with pytest.raises(ContractError, match="artifact"):
        load(tmp_path, payload, artifacts)
    del artifacts[key]
    with pytest.raises(ContractError, match="artifact"):
        load(tmp_path, payload, artifacts)


def test_resolved_config_must_bind_effective_targets(tmp_path):
    payload, artifacts = fixture()
    payload["resolved"]["consumers"]["api"]["resource_id"] = "different-target"
    with pytest.raises(ContractError, match="resolved"):
        load(tmp_path, payload, artifacts)


def test_digest_excludes_only_its_own_field(tmp_path):
    payload, artifacts = fixture()
    before = contract_digest(payload)
    payload["contract_digest"] = "sha256:" + "b" * 64
    assert contract_digest(payload) == before
    with pytest.raises(ContractError, match="digest"):
        load(tmp_path, payload, artifacts, resign=False)
    payload["source_sha"] = "2" * 40
    assert contract_digest(payload) != before


def test_duplicate_json_keys_and_nonfinite_values_rejected(tmp_path):
    path = tmp_path / "bad.json"
    for text in ('{"status":"draft","status":"reviewed"}', '{"x":NaN}'):
        path.write_text(text)
        with pytest.raises(ContractError):
            load_contract(path, artifacts={})


def test_qualified_requires_independent_receipts_not_metadata_echo(tmp_path):
    payload, artifacts = fixture()
    payload["status"] = "qualified"
    with pytest.raises(ContractError):
        load(tmp_path, payload, artifacts)


def qualified_fixture():
    payload, artifacts = fixture()
    payload["status"] = "qualified"
    payload["consumer_receipts"] = {}
    payload["capability_receipts"] = {}
    binding_digest = (
        "sha256:"
        + hashlib.sha256(
            encoded({key: payload[key] for key in ("jobs", "resolved", "protected")})
        ).hexdigest()
    )
    for role in (
        *CONSUMERS,
        "publisher_write_cas_delete",
        "denied_principals",
        "lifecycle",
        "rollback",
    ):
        is_consumer = role in CONSUMERS
        fingerprint = (
            "sha256:"
            + hashlib.sha256(
                encoded(payload["resolved"]["consumers"][role])
            ).hexdigest()
            if is_consumer
            else binding_digest
        )
        observation_key = f"synthetic-observation-{role}"
        artifacts[observation_key] = encoded({"synthetic": role, "not_live": True})
        observed = {
            "key": observation_key,
            "sha256": "sha256:"
            + hashlib.sha256(artifacts[observation_key]).hexdigest(),
        }
        receipt = {
            "source_sha": payload["source_sha"],
            "role": role,
            "mode": "direct_observation",
            "outcome": "passed",
            "observer_kind": "in_process_surface"
            if is_consumer
            else "effective_capability",
            "binding_fingerprint": fingerprint,
            "observation": observed,
        }
        key = f"synthetic-receipt-{role}"
        artifacts[key] = encoded(receipt)
        payload["consumer_receipts" if is_consumer else "capability_receipts"][role] = {
            "artifact": {
                "key": key,
                "sha256": "sha256:" + hashlib.sha256(artifacts[key]).hexdigest(),
            },
            "outcome": "passed",
            "observer_kind": receipt["observer_kind"],
            "binding_fingerprint": fingerprint,
        }
    return payload, artifacts


def test_qualified_is_declared_structural_state_and_not_external_proof(tmp_path):
    payload, artifacts = qualified_fixture()
    result = load(tmp_path, payload, artifacts)
    assert result.status == "qualified"
    assert result.authority == "none"
    assert result.consumer_receipts["api"].observer_kind == "in_process_surface"
    assert (
        require_qualified_contract(tmp_path / "synthetic.json", artifacts=artifacts)
        == result
    )


@pytest.mark.parametrize(
    "change", ["echo", "binding", "kind", "missing-observation", "source"]
)
def test_qualification_rejects_echo_or_unbound_receipts(tmp_path, change):
    payload, artifacts = qualified_fixture()
    receipt = payload["consumer_receipts"]["api"]
    key = receipt["artifact"]["key"]
    body = json.loads(artifacts[key])
    if change == "echo":
        body = {"manifest": {"complete": True}, "validation": {"passed": True}}
    elif change == "binding":
        body["binding_fingerprint"] = HASH
    elif change == "source":
        body["source_sha"] = "3" * 40
    elif change == "kind":
        body["observer_kind"] = "external_client"
    else:
        del artifacts[body["observation"]["key"]]
    artifacts[key] = encoded(body)
    receipt["artifact"]["sha256"] = (
        "sha256:" + hashlib.sha256(artifacts[key]).hexdigest()
    )
    with pytest.raises(ContractError):
        load(tmp_path, payload, artifacts)


def test_schema_has_disjoint_versions_and_closed_statuses():
    from ontology_discovery.isolated_acceptance_contract import contract_json_schema

    schema = contract_json_schema()
    assert set(schema["discriminator"]["mapping"]) == {"draft", "reviewed", "qualified"}
    assert all(
        definition["additionalProperties"] is False
        for definition in schema["$defs"].values()
    )


def test_root_canonicalization_does_not_depend_on_config_mismatch():
    from ontology_discovery.isolated_acceptance_contract import canonical_onelake_root

    assert canonical_onelake_root(BASE + "/Files/example/") == canonical_onelake_root(
        BASE.upper().replace("FILES", "Files") + "/Files/example"
    )
    for path in (
        "/Files/part\nname",
        "/Files/part\tname",
        "/Files/%2e%2e/x",
        "/Tables/entities",
        "/Files/a/../b",
        "/Files/x?ignored",
        "/Files/x#ignored",
    ):
        with pytest.raises(ValueError):
            canonical_onelake_root(BASE + path)


def test_sibling_paths_are_not_ancestor_aliases(tmp_path):
    payload, artifacts = fixture()
    payload["resolved"]["roots"]["state"] = (
        payload["resolved"]["roots"]["connection"] + "-state"
    )
    key = payload["resolved_config"]["key"]
    artifacts[key] = encoded(payload["resolved"])
    payload["resolved_config"]["sha256"] = (
        "sha256:" + hashlib.sha256(artifacts[key]).hexdigest()
    )
    assert load(tmp_path, payload, artifacts).status == "reviewed"


def test_default_schema_and_explicit_native_disabled_are_not_unknown(tmp_path):
    payload, artifacts = fixture()
    targets = payload["resolved"]["materialization"]
    targets["tables"][0]["schema_name"] = ""
    targets["native_enabled"] = False
    targets["native_item_ids"] = []
    fingerprint = "sha256:" + hashlib.sha256(encoded(targets)).hexdigest()
    for consumer in payload["resolved"]["consumers"].values():
        consumer["materialization_fingerprint"] = fingerprint
    key = payload["resolved_config"]["key"]
    artifacts[key] = encoded(payload["resolved"])
    payload["resolved_config"]["sha256"] = (
        "sha256:" + hashlib.sha256(artifacts[key]).hexdigest()
    )
    assert (
        load(tmp_path, payload, artifacts).resolved.materialization.native_enabled
        is False
    )


def test_nested_duplicate_keys_and_unknown_resolved_fields_fail(tmp_path):
    payload, artifacts = fixture()
    path = tmp_path / "duplicate.json"
    text = (
        encoded(payload)
        .decode()
        .replace(
            '"runtime_job_start":false',
            '"runtime_job_start":false,"runtime_job_start":true',
            1,
        )
    )
    path.write_text(text)
    with pytest.raises(ContractError, match="duplicate"):
        load_contract(path, artifacts=artifacts)
    payload["resolved"]["environment"] = "validation"
    with pytest.raises(ContractError):
        load(tmp_path, payload, artifacts)


def test_legacy_validators_are_not_imported_or_modified():
    source = (
        Path(__file__).parents[1]
        / "src/ontology_discovery/isolated_acceptance_contract.py"
    ).read_text()
    assert "import validate_ontology" not in source
    from scripts.validate_ontology_deployment_plan import (
        PlanValidationError,
        validate_saved_plan,
    )
    from tests.test_ontology_deployment_plan import API_DIGEST, WEB_DIGEST, _plan

    plan = _plan("validation")
    expected = {"api": API_DIGEST, "web": WEB_DIGEST}
    assert validate_saved_plan(
        plan, environment="validation", expected_image_digests=expected
    )
    changed = copy.deepcopy(plan)
    resources = changed["planned_values"]["root_module"]["resources"]
    worker = next(
        r
        for r in resources
        if r["address"] == "azurerm_container_app_job.ontology_discovery"
    )
    worker["values"]["template"][0]["container"][0]["image"] = (
        "synthetic.invalid/worker@sha256:" + "f" * 64
    )
    with pytest.raises(PlanValidationError):
        validate_saved_plan(
            changed, environment="validation", expected_image_digests=expected
        )
