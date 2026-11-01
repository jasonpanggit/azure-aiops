"""Disconnected local per-role image plan validation; never an execution gate."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from ontology_discovery.isolated_acceptance_contract import (
    ContractError,
    QualifiedContract,
    ReviewedContract,
    _json,
    load_contract,
)
from scripts.validate_ontology_deployment_plan import (
    PlanValidationError,
    _container,
    _environment,
    _resource_map,
    _single,
    _validate_saved_plan,
    _values,
)

_WORKERS = {
    "ontology_discovery": (
        "coordinator",
        "azurerm_container_app_job.ontology_discovery",
    ),
    "ontology_publisher": (
        "validation_publisher",
        "azurerm_container_app_job.ontology_publisher",
    ),
    "ontology_rbac_validation": (
        "rbac_validator",
        "azurerm_container_app_job.ontology_rbac_validation[0]",
    ),
    "ontology_fixture_prepare": (
        "fixture_prepare",
        "azurerm_container_app_job.ontology_fixture_prepare[0]",
    ),
    "ontology_fixture_cleanup": (
        "fixture_cleanup",
        "azurerm_container_app_job.ontology_fixture_cleanup[0]",
    ),
}
_ROOTS = {
    "AIOPS_CONNECTION_HOME": "connection",
    "AIOPS_ONTOLOGY_COMMAND_HOME": "command",
    "AIOPS_ONTOLOGY_STATE_HOME": "state",
    "AIOPS_ONTOLOGY_DISPATCH_HOME": "dispatch",
    "AIOPS_ONTOLOGY_PUBLICATION_HOME": "publication",
    "AIOPS_ONTOLOGY_FIXTURE_HOME": "fixture",
    "AIOPS_ONTOLOGY_DRILL_HOME": "drill",
}


def validate_isolated_saved_plan(
    path: Path,
    *,
    artifacts: Mapping[str, bytes],
) -> dict[str, object]:
    """Check the referenced validation plan using explicit declared role pins.

    Declared review is not authenticated here. No cloud caller uses this function.
    All existing shared plan guards remain; the address allowlist is not extended.
    """
    contract = load_contract(path, artifacts=artifacts)
    if not isinstance(contract, ReviewedContract | QualifiedContract):
        raise ContractError("complete declared contract required")
    plan = _json(artifacts[contract.validation_plan.key])
    if not isinstance(plan, dict):
        raise PlanValidationError("isolated plan object required")
    root = (plan.get("planned_values") or {}).get("root_module") or {}
    if root.get("child_modules"):
        raise PlanValidationError("isolated plan requires flat resource tree")
    rows = root.get("resources")
    if not isinstance(rows, list) or any(
        not isinstance(row, dict) or not isinstance(row.get("address"), str)
        for row in rows
    ):
        raise PlanValidationError("isolated flat resource list required")
    addresses = [row["address"] for row in rows]
    if len(set(addresses)) != len(addresses):
        raise PlanValidationError("duplicate isolated root resource address")
    digests = {
        role: image.rsplit("@", 1)[1] for role, image in contract.image_pins.items()
    }
    result = _validate_saved_plan(
        plan,
        environment="validation",
        expected_image_digests={role: digests[role] for role in ("api", "web")},
        worker_image_digests={
            name: digests[role] for name, (role, _) in _WORKERS.items()
        },
    )
    resources = _resource_map(plan)
    seen = set()
    for row in plan.get("resource_changes") or []:
        address = row.get("address")
        if address in seen:
            raise PlanValidationError("duplicate isolated change address")
        seen.add(address)
        change = row.get("change") or {}
        before = change.get("before")
        if (
            isinstance(before, dict)
            and str(before.get("id", "")).casefold()
            == contract.protected.publisher_resource_id.casefold()
        ):
            raise PlanValidationError("protected publisher cannot be a change preimage")
        if address in resources and change.get("after") != resources[address].get(
            "values"
        ):
            raise PlanValidationError("isolated planned values/change target differ")
    for resource in resources.values():
        if (
            str(_values(resource).get("id", "")).casefold()
            == contract.protected.publisher_resource_id.casefold()
        ):
            raise PlanValidationError("protected publisher excluded from isolated plan")
    for role, address in _WORKERS.values():
        binding = contract.jobs[role]
        values = _values(resources[address])
        identity = _single(values.get("identity"), "isolated.identity")
        container = _container(values, "isolated")
        env = _environment(container)
        ids = identity.get("identity_ids")
        if (
            str(values.get("id", "")).casefold() != binding.resource_id.casefold()
            or str(values.get("name", "")).casefold()
            != binding.resource_id.rsplit("/", 1)[1].casefold()
            or identity.get("type") != "UserAssigned"
            or not isinstance(ids, list)
            or len(ids) != 1
            or str(ids[0]).casefold() != binding.identity_resource_id.casefold()
            or container.get("image") != contract.image_pins[role]
            or env.get("AZURE_CLIENT_ID", "").casefold() != binding.client_id.casefold()
        ):
            raise PlanValidationError("isolated Job target/identity/image differs")
        required = (
            {"connection", "state", "command", "dispatch"}
            if role == "coordinator"
            else {"connection", "command", "dispatch", "publication"}
            if role == "validation_publisher"
            else {"connection", "state", "fixture"}
            if role.startswith("fixture_")
            else set()
        )
        if not required.issubset({_ROOTS[key] for key in env if key in _ROOTS}):
            raise PlanValidationError("isolated Job roots incomplete")
        for variable, root in _ROOTS.items():
            if variable in env and env[variable] != contract.resolved.roots[root]:
                raise PlanValidationError("isolated Job root differs")
    return {
        "status": "isolated_plan_semantic_subset_verified",
        "authority": "none",
        "contract_digest": contract.contract_digest,
        "image_digests": digests,
        "plan": result,
    }
