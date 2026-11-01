"""Synthetic per-role plans; no deployed approval or execution is implied."""

import hashlib
from copy import deepcopy

import pytest

from ontology_discovery.isolated_acceptance_contract import ContractError
from scripts.validate_isolated_saved_plan import (
    _ROOTS,
    _WORKERS,
    validate_isolated_saved_plan,
)
from scripts.validate_ontology_deployment_plan import (
    PlanValidationError,
    validate_saved_plan,
)
from tests.test_isolated_acceptance_contract import BASE, encoded, fixture, load
from tests.test_ontology_deployment_plan import _plan


def example(tmp_path):
    payload, artifacts = fixture()
    roots = payload["resolved"]["roots"]
    roots["connection"] = BASE + "/Files/aiops/validation/connection-registry"
    roots["fixture"] = BASE + "/Files/aiops/validation/fixture-control"
    for consumer in payload["resolved"]["consumers"].values():
        consumer["publication_root"] = roots["publication"]
    plan = _plan("validation")
    resources = {
        r["address"]: r["values"]
        for r in plan["planned_values"]["root_module"]["resources"]
    }
    coordinator_id = payload["jobs"]["coordinator"]["identity_resource_id"]
    resources["azurerm_user_assigned_identity.ontology_coordinator"]["id"] = (
        coordinator_id
    )
    for role, address in _WORKERS.values():
        binding = payload["jobs"][role]
        if role.startswith("fixture_"):
            fixed = "ontology-fixture-" + role.removeprefix("fixture_")
            binding["resource_id"] = (
                binding["resource_id"].rsplit("/", 1)[0] + "/" + fixed
            )
        values = resources[address]
        values["id"] = binding["resource_id"]
        values["name"] = binding["resource_id"].rsplit("/", 1)[1]
        values["identity"][0]["identity_ids"] = [binding["identity_resource_id"]]
        container = values["template"][0]["container"][0]
        container["image"] = payload["image_pins"][role]
        container["name"] = values["name"]
        env = {r["name"]: r["value"] for r in container["env"]}
        for variable, root in _ROOTS.items():
            if variable in env:
                env[variable] = roots[root]
        env["AZURE_CLIENT_ID"] = binding["client_id"]
        container["env"] = [{"name": k, "value": v} for k, v in env.items()]
    for role in ("api", "web"):
        values = resources[f"azurerm_container_app.{role}"]
        values["template"][0]["container"][0]["image"] = payload["image_pins"][role]
    for row in plan["resource_changes"]:
        row["change"]["after"] = resources[row["address"]]
    for ref, value in (
        (payload["resolved_config"], payload["resolved"]),
        (payload["validation_plan"], plan),
    ):
        artifacts[ref["key"]] = encoded(value)
        ref["sha256"] = "sha256:" + hashlib.sha256(artifacts[ref["key"]]).hexdigest()
    return payload, artifacts, plan


def run(tmp_path, payload, artifacts, plan):
    ref = payload["validation_plan"]
    artifacts[ref["key"]] = encoded(plan)
    ref["sha256"] = "sha256:" + hashlib.sha256(artifacts[ref["key"]]).hexdigest()
    load(tmp_path, payload, artifacts)
    return validate_isolated_saved_plan(
        tmp_path / "synthetic.json", artifacts=artifacts
    )


def test_distinct_roles_only_accepted_by_opt_in_entrypoint(tmp_path):
    payload, artifacts, plan = example(tmp_path)
    assert run(tmp_path, payload, artifacts, plan)["authority"] == "none"
    with pytest.raises(PlanValidationError):
        validate_saved_plan(
            plan,
            environment="validation",
            expected_image_digests={
                r: payload["image_pins"][r].rsplit("@", 1)[1] for r in ("api", "web")
            },
        )


@pytest.mark.parametrize(
    "change",
    ["image", "missing-pin", "production", "delete", "address", "identity", "root"],
)
def test_per_role_contract_does_not_weaken_existing_guards(tmp_path, change):
    payload, artifacts, plan = example(tmp_path)
    rows = plan["planned_values"]["root_module"]["resources"]
    worker = next(
        r["values"]
        for r in rows
        if r["address"] == "azurerm_container_app_job.ontology_publisher"
    )
    if change == "image":
        worker["template"][0]["container"][0]["image"] = payload["image_pins"]["api"]
    elif change == "missing-pin":
        del payload["image_pins"]["fixture_cleanup"]
    elif change == "production":
        worker["id"] = payload["protected"]["publisher_resource_id"]
    elif change == "delete":
        plan["resource_changes"].append(
            {"address": "azurerm_container_app.api", "change": {"actions": ["delete"]}}
        )
    elif change == "address":
        plan["resource_changes"].append(
            {"address": "unexpected.scope", "change": {"actions": ["create"]}}
        )
    elif change == "identity":
        worker["identity"][0]["identity_ids"] = ["/wrong/uai"]
    else:
        next(
            r
            for r in worker["template"][0]["container"][0]["env"]
            if r["name"] == "AIOPS_ONTOLOGY_PUBLICATION_HOME"
        )["value"] = "wrong"
    with pytest.raises((ContractError, PlanValidationError)):
        run(tmp_path, payload, artifacts, plan)


@pytest.mark.parametrize(
    "change",
    [
        "extra-container",
        "nested-address",
        "production-preimage",
        "missing-root",
        "after-disagrees",
    ],
)
def test_original_plan_scope_and_protected_preimage_are_preserved(tmp_path, change):
    payload, artifacts, plan = example(tmp_path)
    worker = next(
        r["values"]
        for r in plan["planned_values"]["root_module"]["resources"]
        if r["address"] == "azurerm_container_app_job.ontology_publisher"
    )
    if change == "extra-container":
        worker["template"][0]["container"].append(
            {"image": payload["image_pins"]["api"]}
        )
    elif change == "nested-address":
        plan["resource_changes"].append(
            {
                "address": "module.unapproved.azurerm_container_app_job.writer",
                "change": {"actions": ["create"], "after": worker},
            }
        )
    elif change == "production-preimage":
        plan["resource_changes"][0]["change"]["before"] = {
            "id": payload["protected"]["publisher_resource_id"],
        }
    elif change == "missing-root":
        worker["template"][0]["container"][0]["env"] = [
            row
            for row in worker["template"][0]["container"][0]["env"]
            if row["name"] != "AIOPS_ONTOLOGY_PUBLICATION_HOME"
        ]
    else:
        plan["resource_changes"][0]["change"]["after"] = {}
    with pytest.raises(PlanValidationError):
        run(tmp_path, payload, artifacts, plan)


@pytest.mark.parametrize("shape", ["count-cancellation", "nested-duplicate", "empty-module"])
def test_flat_format_rejects_nested_tree_and_duplicate_raw_addresses(tmp_path, shape):
    payload, artifacts, plan = example(tmp_path)
    root = plan["planned_values"]["root_module"]
    nested = deepcopy(root["resources"][0])
    if shape == "count-cancellation":
        root["resources"].append(deepcopy(root["resources"][0]))
        nested = {
            "address": "module.unapproved.unexpected.writer",
            "values": {"id": "unapproved"},
        }
    root["child_modules"] = [
        {} if shape == "empty-module" else {"resources": [nested]}
    ]
    with pytest.raises(PlanValidationError, match="flat"):
        run(tmp_path, payload, artifacts, plan)


def test_flat_format_rejects_duplicate_raw_root_addresses(tmp_path):
    payload, artifacts, plan = example(tmp_path)
    root = plan["planned_values"]["root_module"]
    root["resources"].append(deepcopy(root["resources"][0]))
    with pytest.raises(PlanValidationError, match="duplicate"):
        run(tmp_path, payload, artifacts, plan)
