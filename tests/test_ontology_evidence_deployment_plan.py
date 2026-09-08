from __future__ import annotations

import copy

import pytest

from scripts.validate_ontology_evidence_plan import (
    CREATE_ADDRESSES,
    UPDATE_ADDRESSES,
    EvidencePlanError,
    validate_targeted_plan,
)

EVIDENCE_PRINCIPAL_ID = "11111111-1111-1111-1111-111111111111"
EVIDENCE_IDENTITY_ID = (
    "/subscriptions/sub/resourceGroups/rg/providers/"
    "Microsoft.ManagedIdentity/userAssignedIdentities/azure-mcp"
)
PRODUCTION_WORKSPACE_ID = "22222222-2222-2222-2222-222222222222"


def _plan() -> dict[str, object]:
    changes: list[dict[str, object]] = []
    for address in sorted(CREATE_ADDRESSES):
        if address.startswith("fabric_workspace_role_assignment."):
            after: dict[str, object] = {
                "workspace_id": "workspace-" + address.rsplit("_", 1)[-1],
                "role": "Viewer",
                "principal": {
                    "id": EVIDENCE_PRINCIPAL_ID,
                    "type": "ServicePrincipal",
                },
            }
        else:
            after = {
                "name": "ontology-evidence-read",
                "identity": [
                    {
                        "type": "UserAssigned",
                        "identity_ids": [EVIDENCE_IDENTITY_ID],
                    }
                ],
                "manual_trigger_config": [
                    {"parallelism": 1, "replica_completion_count": 1}
                ],
                "schedule_trigger_config": [],
                "event_trigger_config": [],
                "replica_retry_limit": 0,
                "template": [
                    {
                        "container": [
                            {
                                "image": "new@sha256:" + "2" * 64,
                                "command": ["python", "/app/scripts/collect_ontology_evidence.py"],
                                "args": ["--emit-console-record"],
                                "env": [
                                    {"name": name, "value": "fixed-value"}
                                    for name in (
                                        "AZURE_CLIENT_ID",
                                        "AIOPS_EVIDENCE_OBJECT_ID",
                                        "AIOPS_EVIDENCE_SUBSCRIPTION_ID",
                                        "AIOPS_EVIDENCE_RESOURCE_GROUP",
                                        "AIOPS_EVIDENCE_STATE_WORKSPACE_ID",
                                        "AIOPS_EVIDENCE_STATE_LAKEHOUSE_ID",
                                        "AIOPS_EVIDENCE_COMMAND_WORKSPACE_ID",
                                        "AIOPS_EVIDENCE_COMMAND_LAKEHOUSE_ID",
                                        "AIOPS_EVIDENCE_DISPATCH_WORKSPACE_ID",
                                        "AIOPS_EVIDENCE_DISPATCH_LAKEHOUSE_ID",
                                        "AIOPS_EVIDENCE_PUBLICATION_WORKSPACE_ID",
                                        "AIOPS_EVIDENCE_PUBLICATION_LAKEHOUSE_ID",
                                        "AIOPS_EVIDENCE_VALIDATION_WORKSPACE_ID",
                                        "AIOPS_EVIDENCE_VALIDATION_LAKEHOUSE_ID",
                                    )
                                ],
                            }
                        ]
                    }
                ],
            }
        changes.append(
            {
                "address": address,
                "change": {
                    "actions": ["create"],
                    "before": None,
                    "after": after,
                },
            }
        )
    for address in sorted(UPDATE_ADDRESSES):
        changes.append(
            {
                "address": address,
                "change": {
                    "actions": ["update"],
                    "before": {
                        "template": [
                            {"container": [{"image": "old@sha256:" + "1" * 64}]}
                        ]
                    },
                    "after": {
                        "template": [
                            {"container": [{"image": "new@sha256:" + "2" * 64}]}
                        ]
                    },
                },
            }
        )
    return {"resource_changes": changes}


def _validate(plan: dict[str, object]) -> dict[str, object]:
    return validate_targeted_plan(
        plan,
        expected_api_digest="sha256:" + "2" * 64,
        expected_principal_id=EVIDENCE_PRINCIPAL_ID,
        expected_identity_id=EVIDENCE_IDENTITY_ID,
        production_workspace_id=PRODUCTION_WORKSPACE_ID,
    )


def test_targeted_plan_accepts_only_evidence_resources_and_phase13_images() -> None:
    result = _validate(_plan())

    assert result["delete_count"] == 0
    assert result["replace_count"] == 0
    assert result["create_addresses"] == sorted(CREATE_ADDRESSES)
    assert result["update_addresses"] == sorted(UPDATE_ADDRESSES)
    assert result["external_role_contract"] == (
        "Workspace=Viewer;ManagedIdentity:Path=*:Action=Read"
    )


@pytest.mark.parametrize(
    ("address", "actions"),
    [
        ("azurerm_container_app.api", ["update"]),
        ("azurerm_container_app.web", ["update"]),
        ("azurerm_container_app.azure_mcp", ["update"]),
        ("azurerm_container_app_job.ontology_discovery", ["delete", "create"]),
        ("fabric_workspace_role_assignment.apps[0]", ["update"]),
    ],
)
def test_targeted_plan_rejects_shared_or_destructive_changes(
    address: str,
    actions: list[str],
) -> None:
    plan = _plan()
    plan["resource_changes"].append(
        {
            "address": address,
            "change": {"actions": actions, "before": {}, "after": {}},
        }
    )
    with pytest.raises(EvidencePlanError):
        _validate(plan)


def test_targeted_plan_rejects_non_image_mutation_on_existing_job() -> None:
    plan = _plan()
    changed = next(
        row
        for row in plan["resource_changes"]
        if row["address"] == "azurerm_container_app_job.ontology_discovery"
    )
    changed["change"]["after"]["replica_retry_limit"] = 99

    with pytest.raises(EvidencePlanError, match="image-only"):
        _validate(plan)


def test_targeted_plan_requires_all_exact_resources() -> None:
    plan = _plan()
    missing = copy.deepcopy(plan)
    missing["resource_changes"].pop()

    with pytest.raises(EvidencePlanError, match="exact"):
        _validate(missing)


def test_targeted_plan_rejects_provider_managed_onelake_role() -> None:
    plan = _plan()
    plan["resource_changes"].append(
        {
            "address": (
                "fabric_onelake_data_access_security."
                "ontology_evidence_ontology_command[0]"
            ),
            "change": {"actions": ["create"], "before": None, "after": {}},
        }
    )

    with pytest.raises(EvidencePlanError, match="unexpected"):
        _validate(plan)


def test_targeted_plan_rejects_missing_or_secret_evidence_environment() -> None:
    plan = _plan()
    job = next(
        row
        for row in plan["resource_changes"]
        if row["address"]
        == "azurerm_container_app_job.ontology_evidence_read[0]"
    )
    env = job["change"]["after"]["template"][0]["container"][0]["env"]
    env.pop()

    with pytest.raises(EvidencePlanError, match="secret-free"):
        _validate(plan)


def test_evidence_job_update_allows_only_api_read_boundary_removal() -> None:
    plan = _plan()
    job = next(
        row
        for row in plan["resource_changes"]
        if row["address"]
        == "azurerm_container_app_job.ontology_evidence_read[0]"
    )
    after = job["change"]["after"]
    before = copy.deepcopy(after)
    before["template"][0]["container"][0]["image"] = (
        "old@sha256:" + "1" * 64
    )
    before["template"][0]["container"][0]["env"].extend(
        [
            {"name": "AIOPS_EVIDENCE_API_URL", "value": "https://old.invalid"},
            {"name": "AIOPS_EVIDENCE_API_SCOPE", "value": "api://old/.default"},
        ]
    )
    job["change"]["actions"] = ["update"]
    job["change"]["before"] = before

    result = _validate(plan)

    assert (
        "azurerm_container_app_job.ontology_evidence_read[0]"
        in result["update_addresses"]
    )

    job["change"]["before"]["replica_retry_limit"] = 2
    with pytest.raises(EvidencePlanError, match="only"):
        _validate(plan)

    plan = _plan()
    job = next(
        row
        for row in plan["resource_changes"]
        if row["address"]
        == "azurerm_container_app_job.ontology_evidence_read[0]"
    )
    job["change"]["after"]["template"][0]["container"][0]["env"][0][
        "secret_name"
    ] = "unexpected"

    with pytest.raises(EvidencePlanError, match="secret-free"):
        _validate(plan)
