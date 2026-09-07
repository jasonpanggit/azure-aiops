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
        elif address.startswith("fabric_onelake_data_access_security."):
            after = {
                "workspace_id": "workspace-" + address.rsplit("_", 1)[-1],
                "item_id": "lakehouse-" + address.rsplit("_", 1)[-1],
                "role_name": "Phase13EvidenceRead",
                "decision_rules": [
                    {
                        "effect": "Permit",
                        "permission": [
                            {
                                "attribute_name": "Path",
                                "attribute_value_included_in": ["*"],
                            },
                            {
                                "attribute_name": "Action",
                                "attribute_value_included_in": ["Read"],
                            },
                        ],
                    }
                ],
                "members": {
                    "fabric_item_members": [],
                    "microsoft_entra_members": [
                        {
                            "object_id": EVIDENCE_PRINCIPAL_ID,
                            "object_type": "ManagedIdentity",
                            "tenant_id": "33333333-3333-3333-3333-333333333333",
                        }
                    ],
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
                                    {"name": "AZURE_CLIENT_ID", "value": "client"},
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


@pytest.mark.parametrize(
    ("kind", "field", "value"),
    [
        ("workspace", "role", "Contributor"),
        ("workspace", "workspace_id", PRODUCTION_WORKSPACE_ID),
        ("workspace", "principal.id", "wrong-principal"),
        ("onelake", "action", "ReadWrite"),
        ("onelake", "action", "Write"),
        ("onelake", "path", "/Files/too-broad"),
        ("onelake", "object_type", "ServicePrincipal"),
        ("onelake", "object_id", "wrong-principal"),
        ("onelake", "workspace_id", PRODUCTION_WORKSPACE_ID),
    ],
)
def test_targeted_plan_rejects_role_broadening_and_wrong_identity(
    kind: str,
    field: str,
    value: str,
) -> None:
    plan = _plan()
    prefix = (
        "fabric_workspace_role_assignment."
        if kind == "workspace"
        else "fabric_onelake_data_access_security."
    )
    row = next(
        change
        for change in plan["resource_changes"]
        if change["address"].startswith(prefix)
    )
    after = row["change"]["after"]
    if field == "principal.id":
        after["principal"]["id"] = value
    elif field == "action":
        permission = after["decision_rules"][0]["permission"]
        next(
            entry for entry in permission if entry["attribute_name"] == "Action"
        )["attribute_value_included_in"] = [value]
    elif field == "path":
        permission = after["decision_rules"][0]["permission"]
        next(
            entry for entry in permission if entry["attribute_name"] == "Path"
        )["attribute_value_included_in"] = [value]
    elif field in {"object_type", "object_id"}:
        after["members"]["microsoft_entra_members"][0][field] = value
    else:
        after[field] = value

    with pytest.raises(EvidencePlanError):
        _validate(plan)
