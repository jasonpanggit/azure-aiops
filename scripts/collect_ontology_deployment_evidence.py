#!/usr/bin/env python3
"""Collect closed, hash-only evidence for the Plan 19 validation rollout."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import subprocess
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from validate_ontology_deployment_plan import (
    MARKER_VALUE,
    PlanValidationError,
    validate_deployment_evidence,
    validate_saved_plan,
)

_FIXTURE_JOBS = {
    "ontology_fixture_prepare": ("ontology-fixture-prepare", "fixture-prepare"),
    "ontology_fixture_cleanup": ("ontology-fixture-cleanup", "fixture-cleanup"),
}
_IMAGE_RESOURCES = {
    "api": ("app", "aiops-dev-api"),
    "web": ("app", "aiops-dev-web"),
    "coordinator": ("job", "aiops-dev-ontology-discovery"),
    "publisher": ("job", "aiops-dev-ontology-publisher"),
    "rbac_validator": ("job", "aiops-dev-ontology-rbac-check"),
    "prepare": ("job", "ontology-fixture-prepare"),
    "cleanup": ("job", "ontology-fixture-cleanup"),
}
_RUNTIME_IDENTITIES = {
    "api": ("azurerm_user_assigned_identity", "apps"),
    "coordinator": (
        "azurerm_user_assigned_identity",
        "ontology_coordinator",
    ),
    "publisher": (
        "azurerm_user_assigned_identity",
        "ontology_publisher",
    ),
    "curator": ("azurerm_cognitive_account_project", "ops"),
}
_JOB_READ = "Microsoft.App/jobs/read"
_JOB_START = "Microsoft.App/jobs/start/action"


def _run_json(command: list[str]) -> Any:
    output = subprocess.check_output(command, text=True)
    return json.loads(output)


def _hash(value: object) -> str:
    canonical = json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=str
    ).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _load(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise PlanValidationError(f"{path} must contain a JSON object")
    return payload


def _state_resources(path: Path) -> dict[tuple[str, str], Mapping[str, Any]]:
    state = _load(path)
    result: dict[tuple[str, str], Mapping[str, Any]] = {}
    for row in state.get("resources") or []:
        if not isinstance(row, Mapping):
            continue
        instances = row.get("instances")
        if not isinstance(instances, list) or len(instances) != 1:
            continue
        attributes = instances[0].get("attributes")
        if isinstance(attributes, Mapping):
            result[(str(row["type"]), str(row["name"]))] = attributes
    return result


def _state_value(
    resources: Mapping[tuple[str, str], Mapping[str, Any]],
    resource_type: str,
    name: str,
) -> Mapping[str, Any]:
    try:
        return resources[(resource_type, name)]
    except KeyError as exc:
        raise PlanValidationError(
            f"live Terraform state is missing {resource_type}.{name}"
        ) from exc


def _principal(
    resources: Mapping[tuple[str, str], Mapping[str, Any]],
    identity_class: str,
) -> str:
    resource_type, name = _RUNTIME_IDENTITIES[identity_class]
    values = _state_value(resources, resource_type, name)
    if identity_class == "curator":
        identity = values.get("identity")
        if not isinstance(identity, list) or len(identity) != 1:
            raise PlanValidationError("curator identity is unavailable")
        value = identity[0].get("principal_id")
    else:
        value = values.get("principal_id")
    if not isinstance(value, str) or not value:
        raise PlanValidationError(f"{identity_class} principal is unavailable")
    return value


def _job_projection(job: Mapping[str, Any]) -> dict[str, Any]:
    properties = job.get("properties") or {}
    configuration = properties.get("configuration") or {}
    template = properties.get("template") or {}
    identity = job.get("identity") or {}
    containers = template.get("containers") or []
    projected_containers = []
    for container in containers:
        environment = {
            str(row.get("name") or ""): str(row.get("value") or "")
            for row in container.get("env") or []
        }
        projected_containers.append(
            {
                "name": container.get("name"),
                "image": container.get("image"),
                "command": container.get("command") or [],
                "args": container.get("args") or [],
                "environment": dict(sorted(environment.items())),
                "cpu": (container.get("resources") or {}).get("cpu"),
                "memory": (container.get("resources") or {}).get("memory"),
            }
        )
    return {
        "name": job.get("name"),
        "identity_type": identity.get("type"),
        "identity_count": len(identity.get("userAssignedIdentities") or {}),
        "trigger_type": configuration.get("triggerType"),
        "replica_timeout": configuration.get("replicaTimeout"),
        "replica_retry_limit": configuration.get("replicaRetryLimit"),
        "manual_trigger": configuration.get("manualTriggerConfig"),
        "schedule_trigger": configuration.get("scheduleTriggerConfig"),
        "event_trigger": configuration.get("eventTriggerConfig"),
        "containers": projected_containers,
    }


def _read_jobs(resource_group: str) -> dict[str, dict[str, Any]]:
    names = {
        "coordinator": "aiops-dev-ontology-discovery",
        "publisher": "aiops-dev-ontology-publisher",
        "rbac_validator": "aiops-dev-ontology-rbac-check",
        **{
            key: value[0]
            for key, value in _FIXTURE_JOBS.items()
        },
    }
    return {
        key: _job_projection(
            _run_json(
                [
                    "az",
                    "containerapp",
                    "job",
                    "show",
                    "--resource-group",
                    resource_group,
                    "--name",
                    name,
                    "--output",
                    "json",
                ]
            )
        )
        for key, name in names.items()
    }


def _assert_fixture_templates(jobs: Mapping[str, Mapping[str, Any]]) -> None:
    for key, (name, argument) in _FIXTURE_JOBS.items():
        job = jobs[key]
        if (
            job["name"] != name
            or job["identity_type"] != "UserAssigned"
            or job["identity_count"] != 1
            or job["trigger_type"] != "Manual"
            or job["manual_trigger"]
            != {"parallelism": 1, "replicaCompletionCount": 1}
            or job["schedule_trigger"] not in (None, {})
            or job["event_trigger"] not in (None, {})
            or job["replica_retry_limit"] != 0
            or len(job["containers"]) != 1
        ):
            raise PlanValidationError(f"live {name} template changed")
        container = job["containers"][0]
        if (
            container["name"] != name
            or container["command"]
            != ["python", "-m", "ontology_discovery.runtime"]
            or container["args"] != [argument]
        ):
            raise PlanValidationError(f"live {name} command changed")
        environment = container["environment"]
        if set(environment) != {
            "AIOPS_ONTOLOGY_ENVIRONMENT",
            "AIOPS_CONNECTION_HOME",
            "AIOPS_ONTOLOGY_STATE_HOME",
            "AIOPS_ONTOLOGY_FIXTURE_HOME",
            "AZURE_CLIENT_ID",
        }:
            raise PlanValidationError(f"live {name} environment changed")
        if (
            environment["AIOPS_ONTOLOGY_ENVIRONMENT"] != "validation"
            or not environment["AIOPS_CONNECTION_HOME"].endswith(
                "/Files/aiops/validation/connection-registry"
            )
            or not environment["AIOPS_ONTOLOGY_FIXTURE_HOME"].endswith(
                "/Files/aiops/validation/fixture-control"
            )
        ):
            raise PlanValidationError(f"live {name} validation roots changed")


def _role_definitions(principal_id: str) -> list[Mapping[str, Any]]:
    assignments = _run_json(
        [
            "az",
            "role",
            "assignment",
            "list",
            "--assignee-object-id",
            principal_id,
            "--all",
            "--output",
            "json",
        ]
    )
    definitions = []
    for role_name in sorted(
        {
            str(row.get("roleDefinitionName") or "")
            for row in assignments
            if row.get("roleDefinitionName")
        }
    ):
        rows = _run_json(
            [
                "az",
                "role",
                "definition",
                "list",
                "--name",
                role_name,
                "--output",
                "json",
            ]
        )
        if len(rows) != 1:
            raise PlanValidationError("role definition resolution failed")
        definitions.append(rows[0])
    return definitions


def _allows(definition: Mapping[str, Any], action: str) -> bool:
    target = action.casefold()
    for permission in definition.get("permissions") or []:
        denied = [
            str(pattern).casefold()
            for pattern in (
                permission.get("notActions") or []
            )
        ]
        if any(fnmatch.fnmatchcase(target, pattern) for pattern in denied):
            continue
        allowed = [
            str(pattern).casefold()
            for pattern in permission.get("actions") or []
        ]
        if any(fnmatch.fnmatchcase(target, pattern) for pattern in allowed):
            return True
    return False


def _role_projection(definitions: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        [
            {
                "name": row.get("roleName"),
                "actions_hash": _hash(
                    [
                        {
                            "actions": sorted(permission.get("actions") or []),
                            "not_actions": sorted(
                                permission.get("notActions") or []
                            ),
                            "data_actions": sorted(
                                permission.get("dataActions") or []
                            ),
                            "not_data_actions": sorted(
                                permission.get("notDataActions") or []
                            ),
                        }
                        for permission in row.get("permissions") or []
                    ]
                ),
            }
            for row in definitions
        ],
        key=lambda row: str(row["name"]),
    )


def _app(resource_group: str, name: str) -> Mapping[str, Any]:
    return _run_json(
        [
            "az",
            "containerapp",
            "show",
            "--resource-group",
            resource_group,
            "--name",
            name,
            "--output",
            "json",
        ]
    )


def _app_projection(app: Mapping[str, Any]) -> dict[str, Any]:
    properties = app.get("properties") or {}
    containers = (properties.get("template") or {}).get("containers") or []
    if len(containers) != 1:
        raise PlanValidationError("live app must contain one container")
    container = containers[0]
    environment = {
        str(row.get("name") or ""): str(row.get("value") or "")
        for row in container.get("env") or []
        if row.get("value") is not None
    }
    return {
        "identity_type": (app.get("identity") or {}).get("type"),
        "identity_count": len(
            (app.get("identity") or {}).get("userAssignedIdentities") or {}
        ),
        "image": container.get("image"),
        "environment": environment,
    }


def _image_digest(image: object) -> str:
    text = str(image or "")
    marker = "@sha256:"
    if marker not in text:
        raise PlanValidationError("live image is not digest-pinned")
    digest = "sha256:" + text.rsplit(marker, maxsplit=1)[1]
    if len(digest) != 71:
        raise PlanValidationError("live image digest is malformed")
    return digest


def collect(args: argparse.Namespace) -> dict[str, Any]:
    resources = _state_resources(args.terraform_state)
    resource_group = str(
        _state_value(resources, "azurerm_resource_group", "main").get("name")
        or ""
    )
    if not resource_group:
        raise PlanValidationError("resource group is unavailable")

    expected_digests = {
        "api": args.api_digest,
        "web": args.web_digest,
    }
    plans = {
        "production": validate_saved_plan(
            _load(args.production_plan_json),
            environment="production",
            expected_image_digests=expected_digests,
        ),
        "validation": validate_saved_plan(
            _load(args.validation_plan_json),
            environment="validation",
            expected_image_digests=expected_digests,
        ),
    }

    before = _read_jobs(resource_group)
    _assert_fixture_templates(before)
    principals = {
        identity_class: _principal(resources, identity_class)
        for identity_class in _RUNTIME_IDENTITIES
    }
    runtime_roles = {
        identity_class: _role_definitions(principal)
        for identity_class, principal in principals.items()
    }
    offenders = [
        identity_class
        for identity_class, definitions in runtime_roles.items()
        if any(_allows(definition, _JOB_START) for definition in definitions)
    ]
    if offenders:
        raise PlanValidationError(
            "runtime identity can start Container Apps Jobs: "
            + ",".join(sorted(offenders))
        )

    deployer_object_id = _run_json(
        [
            "az",
            "ad",
            "sp",
            "show",
            "--id",
            args.deployer_client_id,
            "--output",
            "json",
        ]
    ).get("id")
    if not deployer_object_id:
        raise PlanValidationError("deployment principal is unavailable")
    deployer_roles = _role_definitions(str(deployer_object_id))
    deployer_access = any(
        _allows(definition, _JOB_READ) and _allows(definition, _JOB_START)
        for definition in deployer_roles
    )
    if not deployer_access:
        raise PlanValidationError(
            "deployment principal lacks fixture Job read/start authority"
        )

    api = _app_projection(_app(resource_group, "aiops-dev-api"))
    web = _app_projection(_app(resource_group, "aiops-dev-web"))
    api_roots = {
        name: api["environment"].get(name, "")
        for name in (
            "AIOPS_CONNECTION_HOME",
            "AIOPS_ONTOLOGY_COMMAND_HOME",
            "AIOPS_ONTOLOGY_STATE_HOME",
            "AIOPS_ONTOLOGY_PUBLICATION_HOME",
        )
    }
    if any(not value for value in api_roots.values()) or len(
        set(api_roots.values())
    ) != 4:
        raise PlanValidationError("live API ontology roots are not exact")
    if (
        api["identity_type"] != "UserAssigned"
        or api["identity_count"] != 1
        or api["environment"].get("AIOPS_ONTOLOGY_DISPATCH_HOME")
        or api["environment"].get("AIOPS_ONTOLOGY_PUBLISHER_CLIENT_ID")
    ):
        raise PlanValidationError("live API identity or publisher denial changed")

    jobs_after = _read_jobs(resource_group)
    _assert_fixture_templates(jobs_after)
    before_hashes = {key: _hash(value) for key, value in before.items()}
    after_hashes = {key: _hash(value) for key, value in jobs_after.items()}
    if before_hashes != after_hashes:
        raise PlanValidationError("live Job template changed during read audit")

    live_images = {
        "api": _image_digest(api["image"]),
        "web": _image_digest(web["image"]),
        **{
            key: _image_digest(job["containers"][0]["image"])
            for key, job in jobs_after.items()
        },
    }
    if live_images["api"] != args.api_digest or live_images["web"] != args.web_digest:
        raise PlanValidationError("live app image digest differs from reviewed image")
    if any(
        digest != args.api_digest
        for key, digest in live_images.items()
        if key not in {"api", "web"}
    ):
        raise PlanValidationError("live worker image digest differs from API image")

    coordinator = _state_value(
        resources,
        "azurerm_user_assigned_identity",
        "ontology_coordinator",
    )
    tags = coordinator.get("tags") or {}
    if tags.get("aiops_validation_fixture") != MARKER_VALUE:
        raise PlanValidationError("live coordinator injection tag changed")
    coordinator_role_names = sorted(
        str(row.get("roleName") or "") for row in runtime_roles["coordinator"]
    )
    if coordinator_role_names != ["AcrPull"]:
        raise PlanValidationError("coordinator Azure role set widened")

    evidence = {
        "schema_version": "1.0.0",
        "status": "applied",
        "generated_at": datetime.now(UTC).isoformat(),
        "plans": plans,
        "live": {
            "applied": True,
            "resource_classes": {
                "container_apps": 2,
                "container_app_jobs": 5,
                "fabric_roots": 5,
            },
            "image_digests": live_images,
            "template_hashes_before": before_hashes,
            "template_hashes_after": after_hashes,
            "root_hashes": {
                name: _hash(value) for name, value in sorted(api_roots.items())
            },
            "runtime_action_set_hashes": {
                identity_class: _hash(_role_projection(definitions))
                for identity_class, definitions in sorted(runtime_roles.items())
            },
            "deployment_action_set_hash": _hash(
                _role_projection(deployer_roles)
            ),
            "no_runtime_job_start_grants": True,
            "deployment_principal_fixture_access": True,
            "coordinator_role_set_hash": _hash(coordinator_role_names),
            "coordinator_tag_hash": _hash(MARKER_VALUE),
            "api_apps_identity": True,
            "api_has_no_publisher_credential": True,
        },
    }
    validate_deployment_evidence(evidence, require_applied=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return evidence


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--terraform-state", type=Path, required=True)
    parser.add_argument("--production-plan-json", type=Path, required=True)
    parser.add_argument("--validation-plan-json", type=Path, required=True)
    parser.add_argument("--api-digest", required=True)
    parser.add_argument("--web-digest", required=True)
    parser.add_argument("--deployer-client-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    evidence = collect(_parser().parse_args(argv))
    print(
        json.dumps(
            {
                "status": evidence["status"],
                "schema_version": evidence["schema_version"],
                "evidence_digest": _hash(evidence),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
