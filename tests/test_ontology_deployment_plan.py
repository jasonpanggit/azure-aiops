from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts.validate_ontology_deployment_plan import (
    EXPECTED_PRODUCTION_ADDRESSES,
    EXPECTED_VALIDATION_ADDRESSES,
    MARKER_VALUE,
    PlanValidationError,
    validate_deployment_evidence,
    validate_saved_plan,
)

ROOT = Path(__file__).resolve().parents[1]
JOB_TF = ROOT / "infra" / "terraform" / "ontology_discovery_job.tf"
IDENTITY_TF = ROOT / "infra" / "terraform" / "ontology_discovery_identity.tf"
CONTAINER_APPS_TF = ROOT / "infra" / "terraform" / "container_apps.tf"
VARIABLES_TF = ROOT / "infra" / "terraform" / "variables.tf"

API_DIGEST = "sha256:" + ("a" * 64)
WEB_DIGEST = "sha256:" + ("b" * 64)


def _job(
    *,
    name: str,
    module: str,
    argument: str,
    identity: str,
    environment: dict[str, str],
    image_digest: str = API_DIGEST,
) -> dict[str, object]:
    return {
        "name": name,
        "replica_timeout_in_seconds": 300,
        "replica_retry_limit": 0,
        "identity": [{"type": "UserAssigned", "identity_ids": [identity]}],
        "manual_trigger_config": [
            {"parallelism": 1, "replica_completion_count": 1}
        ],
        "template": [
            {
                "container": [
                    {
                        "name": name,
                        "image": f"registry.example/aiops-api@{image_digest}",
                        "command": ["python", "-m", module],
                        "args": [argument],
                        "env": [
                            {"name": key, "value": value}
                            for key, value in sorted(environment.items())
                        ],
                    }
                ]
            }
        ],
    }


def _resource(address: str, values: dict[str, object]) -> dict[str, object]:
    resource_type, indexed_name = address.split(".", maxsplit=1)
    name = indexed_name.split("[", maxsplit=1)[0]
    return {
        "address": address,
        "mode": "managed",
        "type": resource_type,
        "name": name,
        "values": values,
    }


def _plan(environment: str) -> dict[str, object]:
    identity = "/identities/ontology-coordinator"
    connection = "abfss://connection@onelake/registry"
    command = "abfss://command@onelake/commands"
    state = "abfss://state@onelake/state"
    dispatch = "abfss://dispatch@onelake/dispatch"
    publication = "abfss://publication@onelake/publication"
    validation_connection = (
        "abfss://state@onelake/Files/aiops/validation/connection-registry"
    )
    coordinator_connection = (
        validation_connection if environment == "validation" else connection
    )
    coordinator_tag = (
        {"aiops_validation_fixture": MARKER_VALUE}
        if environment == "validation"
        else {}
    )
    values_by_address: dict[str, dict[str, object]] = {
        "azurerm_container_app.api": {
            "identity": [{"type": "UserAssigned", "identity_ids": ["/identities/apps"]}],
            "template": [
                {
                    "container": [
                        {
                            "image": f"registry.example/aiops-api@{API_DIGEST}",
                            "env": [
                                {"name": "AIOPS_CONNECTION_HOME", "value": connection},
                                {"name": "AIOPS_ONTOLOGY_COMMAND_HOME", "value": command},
                                {"name": "AIOPS_ONTOLOGY_STATE_HOME", "value": state},
                                {
                                    "name": "AIOPS_ONTOLOGY_PUBLICATION_HOME",
                                    "value": publication,
                                },
                                {"name": "AZURE_CLIENT_ID", "value": "apps-client"},
                            ],
                        }
                    ]
                }
            ],
        },
        "azurerm_container_app.web": {
            "template": [
                {
                    "container": [
                        {"image": f"registry.example/aiops-web@{WEB_DIGEST}"}
                    ]
                }
            ]
        },
        "azurerm_container_app_job.ontology_discovery": _job(
            name="ontology-discovery",
            module="ontology_discovery.cli",
            argument="run-once",
            identity=identity,
            environment={
                "AIOPS_ONTOLOGY_ENVIRONMENT": environment,
                "AIOPS_CONNECTION_HOME": coordinator_connection,
                "AIOPS_ONTOLOGY_COMMAND_HOME": command,
                "AIOPS_ONTOLOGY_STATE_HOME": state,
                "AIOPS_ONTOLOGY_DISPATCH_HOME": dispatch,
            },
        ),
        "azurerm_container_app_job.ontology_publisher": _job(
            name="ontology-publisher",
            module="ontology_discovery.publisher_cli",
            argument="run-once",
            identity="/identities/ontology-publisher",
            environment={
                "AIOPS_CONNECTION_HOME": connection,
                "AIOPS_ONTOLOGY_COMMAND_HOME": command,
                "AIOPS_ONTOLOGY_DISPATCH_HOME": dispatch,
                "AIOPS_ONTOLOGY_PUBLICATION_HOME": publication,
                "AIOPS_IDENTITY_CLASS": "publisher",
            },
        ),
        "azurerm_container_app_job.ontology_rbac_validation[0]": _job(
            name="ontology-rbac-check",
            module="scripts.validate_ontology_publisher_rbac",
            argument="--non-production",
            identity=identity,
            environment={},
        ),
        "azurerm_user_assigned_identity.ontology_coordinator": {
            "tags": coordinator_tag
        },
    }
    if environment == "validation":
        fixture_environment = {
            "AIOPS_ONTOLOGY_ENVIRONMENT": "validation",
            "AIOPS_CONNECTION_HOME": validation_connection,
            "AIOPS_ONTOLOGY_STATE_HOME": state,
            "AIOPS_ONTOLOGY_FIXTURE_HOME": (
                "abfss://state@onelake/Files/aiops/validation/fixture-control"
            ),
            "AZURE_CLIENT_ID": "coordinator-client",
        }
        values_by_address.update(
            {
                "azurerm_container_app_job.ontology_fixture_prepare[0]": _job(
                    name="ontology-fixture-prepare",
                    module="ontology_discovery.runtime",
                    argument="fixture-prepare",
                    identity=identity,
                    environment=fixture_environment,
                ),
                "azurerm_container_app_job.ontology_fixture_cleanup[0]": _job(
                    name="ontology-fixture-cleanup",
                    module="ontology_discovery.runtime",
                    argument="fixture-cleanup",
                    identity=identity,
                    environment=fixture_environment,
                ),
            }
        )

    expected = (
        EXPECTED_VALIDATION_ADDRESSES
        if environment == "validation"
        else EXPECTED_PRODUCTION_ADDRESSES
    )
    for address in expected:
        values_by_address.setdefault(address, {})
    resources = [
        _resource(address, values_by_address[address]) for address in sorted(expected)
    ]
    return {
        "format_version": "1.2",
        "terraform_version": "1.13.0",
        "planned_values": {"root_module": {"resources": resources}},
        "resource_changes": [
            {
                "address": address,
                "mode": "managed",
                "type": address.split(".", maxsplit=1)[0],
                "name": address.split(".", maxsplit=1)[1].split("[", maxsplit=1)[0],
                "change": {
                    "actions": ["create"],
                    "before": None,
                    "after": values_by_address[address],
                },
            }
            for address in sorted(expected)
        ],
    }


def test_accepted_addresses_are_exact_and_exclude_runtime_job_start_grants() -> None:
    required = {
        "azurerm_container_app.api",
        "azurerm_container_app.web",
        "azurerm_container_app_job.ontology_discovery",
        "azurerm_container_app_job.ontology_publisher",
        "azurerm_container_app_job.ontology_rbac_validation[0]",
        "fabric_workspace.ontology_command[0]",
        "fabric_lakehouse.ontology_command[0]",
        "fabric_workspace.ontology_dispatch[0]",
        "fabric_lakehouse.ontology_dispatch[0]",
        "fabric_workspace.ontology_publication[0]",
        "fabric_lakehouse.ontology_publication[0]",
    }
    assert required <= EXPECTED_PRODUCTION_ADDRESSES
    assert EXPECTED_VALIDATION_ADDRESSES == EXPECTED_PRODUCTION_ADDRESSES | {
        "azurerm_container_app_job.ontology_fixture_prepare[0]",
        "azurerm_container_app_job.ontology_fixture_cleanup[0]",
    }
    forbidden_fragments = (
        "fixture_identity",
        "fixture_principal",
        "resource_group",
        "job_start",
        "*",
    )
    assert not any(
        fragment in address
        for address in EXPECTED_VALIDATION_ADDRESSES
        for fragment in forbidden_fragments
    )


@pytest.mark.parametrize("environment", ["production", "validation"])
def test_saved_plan_accepts_only_exact_zero_destroy_digest_pinned_topology(
    environment: str,
) -> None:
    result = validate_saved_plan(
        _plan(environment),
        environment=environment,
        expected_image_digests={"api": API_DIGEST, "web": WEB_DIGEST},
    )

    assert result["environment"] == environment
    assert result["delete_count"] == 0
    assert result["replace_count"] == 0
    assert result["accepted_addresses"] == sorted(
        EXPECTED_VALIDATION_ADDRESSES
        if environment == "validation"
        else EXPECTED_PRODUCTION_ADDRESSES
    )
    assert set(result["template_hashes"]) == {
        "ontology_discovery",
        "ontology_publisher",
        "ontology_rbac_validation",
        *(
            ("ontology_fixture_prepare", "ontology_fixture_cleanup")
            if environment == "validation"
            else ()
        ),
    }


def test_saved_plan_rejects_unlisted_destroy_and_override_capability() -> None:
    base = _plan("validation")
    unexpected = copy.deepcopy(base)
    unexpected["resource_changes"].append(
        {
            "address": "azurerm_role_assignment.runtime_job_start",
            "change": {"actions": ["create"], "after": {}},
        }
    )
    with pytest.raises(PlanValidationError, match="unexpected address"):
        validate_saved_plan(
            unexpected,
            environment="validation",
            expected_image_digests={"api": API_DIGEST, "web": WEB_DIGEST},
        )

    destroyed = copy.deepcopy(base)
    destroyed["resource_changes"][0]["change"]["actions"] = ["delete"]
    with pytest.raises(PlanValidationError, match="destroy"):
        validate_saved_plan(
            destroyed,
            environment="validation",
            expected_image_digests={"api": API_DIGEST, "web": WEB_DIGEST},
        )

    overridden = copy.deepcopy(base)
    fixture = next(
        row
        for row in overridden["planned_values"]["root_module"]["resources"]
        if row["address"]
        == "azurerm_container_app_job.ontology_fixture_prepare[0]"
    )
    fixture["values"]["event_trigger_config"] = [{"scale": [{"rules": ["caller"]}]}]
    with pytest.raises(PlanValidationError, match="override|event"):
        validate_saved_plan(
            overridden,
            environment="validation",
            expected_image_digests={"api": API_DIGEST, "web": WEB_DIGEST},
        )


def test_terraform_declares_exact_roots_identities_and_fixed_templates() -> None:
    jobs = JOB_TF.read_text(encoding="utf-8")
    identities = IDENTITY_TF.read_text(encoding="utf-8")
    api = CONTAINER_APPS_TF.read_text(encoding="utf-8")
    variables = VARIABLES_TF.read_text(encoding="utf-8")

    assert 'variable "ontology_discovery_environment"' in variables
    assert 'variable "api_image_digest"' in variables
    assert 'variable "web_image_digest"' in variables
    for resource in ("ontology_command", "ontology_dispatch", "ontology_publication"):
        assert f'resource "fabric_workspace" "{resource}"' in identities
        assert f'resource "fabric_lakehouse" "{resource}"' in identities
    assert 'resource "azurerm_container_app_job" "ontology_publisher"' in jobs
    assert 'args    = ["run-once"]' in jobs
    assert "ontology_publisher.client_id" in jobs
    assert "AIOPS_ONTOLOGY_PUBLICATION_HOME" in jobs
    assert "AIOPS_ONTOLOGY_DISPATCH_HOME" in jobs
    assert "AIOPS_ONTOLOGY_COMMAND_HOME" in jobs
    assert "AIOPS_CONNECTION_HOME" in jobs
    assert "AIOPS_ONTOLOGY_ENVIRONMENT" in jobs
    assert 'value = "publisher"' in jobs
    assert MARKER_VALUE in jobs

    api_resource = api.split(
        'resource "azurerm_container_app" "api"', maxsplit=1
    )[1].split('resource "azurerm_container_app_job"', maxsplit=1)[0]
    for root in (
        "AIOPS_CONNECTION_HOME",
        "AIOPS_ONTOLOGY_COMMAND_HOME",
        "AIOPS_ONTOLOGY_STATE_HOME",
        "AIOPS_ONTOLOGY_PUBLICATION_HOME",
    ):
        assert root in api_resource
    assert "AIOPS_ONTOLOGY_DISPATCH_HOME" not in api_resource
    assert "AIOPS_ONTOLOGY_PUBLISHER_CLIENT_ID" not in api_resource


def test_sanitized_applied_evidence_is_closed_and_hash_only() -> None:
    plan = validate_saved_plan(
        _plan("validation"),
        environment="validation",
        expected_image_digests={"api": API_DIGEST, "web": WEB_DIGEST},
    )
    evidence = {
        "schema_version": "1.0.0",
        "status": "applied",
        "generated_at": "2026-09-07T12:00:00+00:00",
        "plans": {
            "validation": plan,
            "production": validate_saved_plan(
                _plan("production"),
                environment="production",
                expected_image_digests={
                    "api": API_DIGEST,
                    "web": WEB_DIGEST,
                },
            ),
        },
        "live": {
            "applied": True,
            "image_digests": {"api": API_DIGEST, "web": WEB_DIGEST},
            "template_hashes_before": plan["template_hashes"],
            "template_hashes_after": plan["template_hashes"],
            "no_runtime_job_start_grants": True,
            "deployment_principal_fixture_access": True,
            "coordinator_role_set_hash": "sha256:" + ("c" * 64),
            "coordinator_tag_hash": "sha256:" + ("d" * 64),
            "api_apps_identity": True,
            "api_has_no_publisher_credential": True,
        },
    }
    validated = validate_deployment_evidence(evidence, require_applied=True)
    assert validated["status"] == "applied"
    serialized = json.dumps(validated, sort_keys=True)
    for forbidden in (
        "client_secret",
        "access_token",
        "https://",
        "abfss://",
        "marker=ontology",
    ):
        assert forbidden not in serialized
