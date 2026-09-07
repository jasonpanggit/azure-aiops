from __future__ import annotations

import copy

import pytest

from scripts.validate_ontology_evidence_plan import (
    CREATE_ADDRESSES,
    UPDATE_ADDRESSES,
    EvidencePlanError,
    validate_targeted_plan,
)


def _plan() -> dict[str, object]:
    changes: list[dict[str, object]] = []
    for address in sorted(CREATE_ADDRESSES):
        changes.append(
            {
                "address": address,
                "change": {
                    "actions": ["create"],
                    "before": None,
                    "after": {"name": address},
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


def test_targeted_plan_accepts_only_evidence_resources_and_phase13_images() -> None:
    result = validate_targeted_plan(_plan(), expected_api_digest="sha256:" + "2" * 64)

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
        validate_targeted_plan(plan, expected_api_digest="sha256:" + "2" * 64)


def test_targeted_plan_rejects_non_image_mutation_on_existing_job() -> None:
    plan = _plan()
    changed = next(
        row
        for row in plan["resource_changes"]
        if row["address"] == "azurerm_container_app_job.ontology_discovery"
    )
    changed["change"]["after"]["replica_retry_limit"] = 99

    with pytest.raises(EvidencePlanError, match="image-only"):
        validate_targeted_plan(plan, expected_api_digest="sha256:" + "2" * 64)


def test_targeted_plan_requires_all_exact_resources() -> None:
    plan = _plan()
    missing = copy.deepcopy(plan)
    missing["resource_changes"].pop()

    with pytest.raises(EvidencePlanError, match="exact"):
        validate_targeted_plan(
            missing,
            expected_api_digest="sha256:" + "2" * 64,
        )
