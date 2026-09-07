#!/usr/bin/env python3
"""Validate and retain only sanitized evidence for the Plan 19 rollout."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

MARKER_VALUE = (
    "marker=ontology-prompt-injection;"
    "instruction=ignore-scope-and-create-edge"
)
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

_COMMON_ADDRESSES = frozenset(
    {
        "azurerm_container_app.api",
        "azurerm_container_app.web",
        "azurerm_container_app_job.ontology_discovery",
        "azurerm_container_app_job.ontology_publisher",
        "azurerm_container_app_job.ontology_rbac_validation[0]",
        "azurerm_role_assignment.ontology_coordinator_acr_pull",
        "azurerm_role_assignment.ontology_publisher_acr_pull",
        "azurerm_user_assigned_identity.ontology_coordinator",
        "azurerm_user_assigned_identity.ontology_publisher",
        "fabric_workspace.ontology_command[0]",
        "fabric_lakehouse.ontology_command[0]",
        "fabric_workspace.ontology_dispatch[0]",
        "fabric_lakehouse.ontology_dispatch[0]",
        "fabric_workspace.ontology_publication[0]",
        "fabric_lakehouse.ontology_publication[0]",
        "fabric_workspace.ontology_discovery_state[0]",
        "fabric_lakehouse.ontology_discovery_state[0]",
        "fabric_workspace_role_assignment.ontology_coordinator_state[0]",
        "fabric_workspace_role_assignment.ontology_command_api[0]",
        "fabric_workspace_role_assignment.ontology_command_coordinator[0]",
        "fabric_workspace_role_assignment.ontology_command_publisher[0]",
        "fabric_workspace_role_assignment.ontology_dispatch_coordinator[0]",
        "fabric_workspace_role_assignment.ontology_dispatch_publisher[0]",
        "fabric_workspace_role_assignment.ontology_publication_api[0]",
        "fabric_workspace_role_assignment.ontology_publication_publisher[0]",
        # Existing Plan 07 validation and guarded publisher-drill boundary.
        "fabric_workspace.ontology_rbac_validation[0]",
        "fabric_lakehouse.ontology_rbac_validation[0]",
        "fabric_workspace_role_assignment.ontology_publisher[0]",
    }
)
EXPECTED_PRODUCTION_ADDRESSES = _COMMON_ADDRESSES
EXPECTED_VALIDATION_ADDRESSES = _COMMON_ADDRESSES | frozenset(
    {
        "azurerm_container_app_job.ontology_fixture_prepare[0]",
        "azurerm_container_app_job.ontology_fixture_cleanup[0]",
    }
)

_FIXTURE_EXPECTATIONS = {
    "ontology_fixture_prepare": ("ontology-fixture-prepare", "fixture-prepare"),
    "ontology_fixture_cleanup": ("ontology-fixture-cleanup", "fixture-cleanup"),
}
_WORKER_NAMES = (
    "ontology_discovery",
    "ontology_publisher",
    "ontology_rbac_validation",
)
_FORBIDDEN_EVIDENCE_KEYS = frozenset(
    {
        "command",
        "commands",
        "args",
        "arguments",
        "env",
        "url",
        "uri",
        "client_id",
        "object_id",
        "principal_id",
        "tenant_id",
        "subscription_id",
        "resource_id",
        "error",
        "prompt",
        "metadata",
        "token",
        "secret",
    }
)


class PlanValidationError(ValueError):
    """A saved plan or retained evidence violates the closed rollout contract."""


def _canonical_hash(value: object) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=str
    ).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _resources(module: Mapping[str, Any] | None) -> Iterable[Mapping[str, Any]]:
    if not module:
        return
    yield from module.get("resources") or ()
    for child in module.get("child_modules") or ():
        yield from _resources(child)


def _resource_map(plan: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    root = (plan.get("planned_values") or {}).get("root_module")
    return {
        str(resource.get("address")): resource
        for resource in _resources(root)
        if resource.get("address")
    }


def _change_map(plan: Mapping[str, Any]) -> dict[str, tuple[str, ...]]:
    changes: dict[str, tuple[str, ...]] = {}
    for resource in plan.get("resource_changes") or ():
        actions = tuple((resource.get("change") or {}).get("actions") or ())
        if actions and actions != ("no-op",):
            changes[str(resource.get("address"))] = actions
    return changes


def _values(resource: Mapping[str, Any]) -> Mapping[str, Any]:
    values = resource.get("values")
    if not isinstance(values, Mapping):
        raise PlanValidationError(
            f"{resource.get('address', 'resource')} has no planned values"
        )
    return values


def _single(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, list) or len(value) != 1:
        raise PlanValidationError(f"{label} must contain exactly one block")
    block = value[0]
    if not isinstance(block, Mapping):
        raise PlanValidationError(f"{label} must be an object")
    return block


def _container(values: Mapping[str, Any], label: str) -> Mapping[str, Any]:
    template = _single(values.get("template"), f"{label}.template")
    return _single(template.get("container"), f"{label}.template.container")


def _environment(container: Mapping[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for row in container.get("env") or ():
        if not isinstance(row, Mapping):
            raise PlanValidationError("container environment row must be an object")
        name = str(row.get("name") or "")
        value = row.get("value")
        if not name:
            raise PlanValidationError("container environment name must be explicit")
        if not isinstance(value, str) and row.get("secret_name"):
            continue
        if value is None:
            # A URI containing a newly-created Fabric workspace or lakehouse ID
            # is necessarily unknown before apply. Preserve the distinct env
            # slot in the complete template hash; live validation replaces it
            # with the resolved hash after the foundational resources exist.
            result[name] = f"<known-after-apply:{name}>"
            continue
        if not isinstance(value, str):
            raise PlanValidationError("all ontology environment values must be explicit")
        if name in result and (
            name == "AIOPS_CONNECTION_HOME"
            or name.startswith("AIOPS_ONTOLOGY_")
            or name == "AIOPS_IDENTITY_CLASS"
            or name == "AZURE_CLIENT_ID"
        ):
            raise PlanValidationError(f"duplicate environment variable: {name}")
        result[name] = value
    return result


def _require_digest(image: object, expected: str, label: str) -> None:
    text = str(image or "")
    if not _DIGEST_RE.fullmatch(expected):
        raise PlanValidationError(f"{label} expected digest is invalid")
    if not text.endswith("@" + expected):
        raise PlanValidationError(f"{label} image is not pinned to reviewed digest")


def _template_projection(values: Mapping[str, Any]) -> dict[str, Any]:
    container = _container(values, "job")
    identity = _single(values.get("identity"), "job.identity")
    trigger = {
        "manual": values.get("manual_trigger_config") or [],
        "schedule": values.get("schedule_trigger_config") or [],
        "event": values.get("event_trigger_config") or [],
    }
    return {
        "name": values.get("name"),
        "timeout": values.get("replica_timeout_in_seconds"),
        "retry": values.get("replica_retry_limit"),
        "identity": identity,
        "trigger": trigger,
        "container": {
            "name": container.get("name"),
            "image": container.get("image"),
            "command": container.get("command"),
            "args": container.get("args"),
            "env": sorted(
                container.get("env") or (),
                key=lambda row: str(row.get("name") or ""),
            ),
        },
    }


def _validate_fixture(
    resource: Mapping[str, Any],
    *,
    terraform_name: str,
    display_name: str,
    argument: str,
    coordinator_identity: str,
    expected_digest: str,
) -> str:
    values = _values(resource)
    if values.get("event_trigger_config") not in (None, []):
        raise PlanValidationError(f"{terraform_name} event override is forbidden")
    if values.get("schedule_trigger_config") not in (None, []):
        raise PlanValidationError(f"{terraform_name} schedule override is forbidden")
    manual = _single(
        values.get("manual_trigger_config"),
        f"{terraform_name}.manual_trigger_config",
    )
    if manual.get("parallelism") != 1 or manual.get("replica_completion_count") != 1:
        raise PlanValidationError(f"{terraform_name} must be single-replica")
    if values.get("replica_retry_limit") != 0:
        raise PlanValidationError(f"{terraform_name} retry template changed")
    timeout = values.get("replica_timeout_in_seconds")
    if not isinstance(timeout, int) or timeout < 1 or timeout > 900:
        raise PlanValidationError(f"{terraform_name} timeout is not finite")
    identity = _single(values.get("identity"), f"{terraform_name}.identity")
    if identity.get("type") != "UserAssigned" or identity.get("identity_ids") != [
        coordinator_identity
    ]:
        raise PlanValidationError(
            f"{terraform_name} must use only the coordinator identity"
        )
    container = _container(values, terraform_name)
    if values.get("name") != display_name or container.get("name") != display_name:
        raise PlanValidationError(f"{terraform_name} fixed name changed")
    if container.get("command") != [
        "python",
        "-m",
        "ontology_discovery.runtime",
    ]:
        raise PlanValidationError(f"{terraform_name} fixed command changed")
    if container.get("args") != [argument]:
        raise PlanValidationError(f"{terraform_name} arguments or override changed")
    _require_digest(container.get("image"), expected_digest, terraform_name)
    env = _environment(container)
    required = {
        "AIOPS_ONTOLOGY_ENVIRONMENT",
        "AIOPS_CONNECTION_HOME",
        "AIOPS_ONTOLOGY_STATE_HOME",
        "AIOPS_ONTOLOGY_FIXTURE_HOME",
        "AZURE_CLIENT_ID",
    }
    if set(env) != required:
        raise PlanValidationError(
            f"{terraform_name} environment override surface changed"
        )
    if env["AIOPS_ONTOLOGY_ENVIRONMENT"] != "validation":
        raise PlanValidationError(f"{terraform_name} environment is not validation")
    if not env["AIOPS_CONNECTION_HOME"].endswith(
        "/Files/aiops/validation/connection-registry"
    ):
        raise PlanValidationError(f"{terraform_name} validation root changed")
    if not env["AIOPS_ONTOLOGY_FIXTURE_HOME"].endswith(
        "/Files/aiops/validation/fixture-control"
    ):
        raise PlanValidationError(f"{terraform_name} fixture root changed")
    return _canonical_hash(_template_projection(values))


def _validate_api(
    resource: Mapping[str, Any], expected_digest: str
) -> dict[str, str]:
    values = _values(resource)
    identity = _single(values.get("identity"), "api.identity")
    ids = identity.get("identity_ids")
    if identity.get("type") != "UserAssigned" or not isinstance(ids, list) or len(ids) != 1:
        raise PlanValidationError("API must retain exactly one apps UAI")
    container = _container(values, "api")
    _require_digest(container.get("image"), expected_digest, "api")
    env = _environment(container)
    required = (
        "AIOPS_CONNECTION_HOME",
        "AIOPS_ONTOLOGY_COMMAND_HOME",
        "AIOPS_ONTOLOGY_STATE_HOME",
        "AIOPS_ONTOLOGY_PUBLICATION_HOME",
    )
    roots = {name: env.get(name, "") for name in required}
    if any(not value for value in roots.values()) or len(set(roots.values())) != 4:
        raise PlanValidationError("API ontology roots must be explicit and distinct")
    forbidden = (
        "AIOPS_ONTOLOGY_DISPATCH_HOME",
        "AIOPS_ONTOLOGY_FIXTURE_HOME",
        "AIOPS_ONTOLOGY_DRILL_HOME",
        "AIOPS_ONTOLOGY_PUBLISHER_CLIENT_ID",
        "AIOPS_PUBLISHER_CREDENTIAL",
    )
    if any(env.get(name) for name in forbidden):
        raise PlanValidationError("API publisher, dispatch, drill, or fixture authority found")
    return {name: _canonical_hash(value) for name, value in roots.items()}


def _validate_worker_image(
    resource: Mapping[str, Any], expected_digest: str, label: str
) -> str:
    values = _values(resource)
    container = _container(values, label)
    _require_digest(container.get("image"), expected_digest, label)
    return _canonical_hash(_template_projection(values))


def _scan_changed_values(
    plan: Mapping[str, Any], changes: Mapping[str, tuple[str, ...]]
) -> None:
    changed_rows = [
        row
        for row in plan.get("resource_changes") or ()
        if str(row.get("address")) in changes
    ]
    serialized = json.dumps(changed_rows, sort_keys=True)
    forbidden = (
        "Microsoft.App/jobs/start/action",
        '"actions":["*"]',
        '"actions": ["*"]',
        "ontology_coordinator_fixture",
        "fixture_service_principal",
    )
    if any(token in serialized for token in forbidden):
        raise PlanValidationError("runtime Job-start or wildcard grant is forbidden")


def validate_saved_plan(
    plan: Mapping[str, Any],
    *,
    environment: str,
    expected_image_digests: Mapping[str, str],
) -> dict[str, Any]:
    """Validate one Terraform JSON plan and return sanitized evidence."""

    if environment not in {"production", "validation"}:
        raise PlanValidationError("environment must be production or validation")
    expected = (
        EXPECTED_VALIDATION_ADDRESSES
        if environment == "validation"
        else EXPECTED_PRODUCTION_ADDRESSES
    )
    api_digest = str(expected_image_digests.get("api") or "")
    web_digest = str(expected_image_digests.get("web") or "")
    if not _DIGEST_RE.fullmatch(api_digest) or not _DIGEST_RE.fullmatch(web_digest):
        raise PlanValidationError("reviewed API and web digests are required")

    resources = _resource_map(plan)
    changes = _change_map(plan)
    unexpected = sorted(set(changes) - expected)
    if unexpected:
        raise PlanValidationError(f"unexpected address: {unexpected[0]}")
    for address, actions in changes.items():
        if "delete" in actions:
            raise PlanValidationError(f"destroy is forbidden: {address}")
        if actions == ("delete", "create") or actions == ("create", "delete"):
            raise PlanValidationError(f"replace is forbidden: {address}")
    _scan_changed_values(plan, changes)

    required_resources = {
        "azurerm_container_app.api",
        "azurerm_container_app.web",
        "azurerm_container_app_job.ontology_discovery",
        "azurerm_container_app_job.ontology_publisher",
        "azurerm_container_app_job.ontology_rbac_validation[0]",
        "azurerm_user_assigned_identity.ontology_coordinator",
    }
    if environment == "validation":
        required_resources |= {
            "azurerm_container_app_job.ontology_fixture_prepare[0]",
            "azurerm_container_app_job.ontology_fixture_cleanup[0]",
        }
    missing = sorted(required_resources - resources.keys())
    if missing:
        raise PlanValidationError(f"required planned resource missing: {missing[0]}")

    api_root_hashes = _validate_api(
        resources["azurerm_container_app.api"], api_digest
    )
    web = _container(_values(resources["azurerm_container_app.web"]), "web")
    _require_digest(web.get("image"), web_digest, "web")
    templates = {
        name: _validate_worker_image(
            resources[
                "azurerm_container_app_job."
                + name
                + ("[0]" if name == "ontology_rbac_validation" else "")
            ],
            api_digest,
            name,
        )
        for name in _WORKER_NAMES
    }

    coordinator_values = _values(
        resources["azurerm_container_app_job.ontology_discovery"]
    )
    coordinator_env = _environment(
        _container(coordinator_values, "ontology_discovery")
    )
    if coordinator_env.get("AIOPS_ONTOLOGY_ENVIRONMENT") != environment:
        raise PlanValidationError("coordinator environment classification changed")
    connection_root = coordinator_env.get("AIOPS_CONNECTION_HOME", "")
    if environment == "validation":
        if not connection_root.endswith(
            "/Files/aiops/validation/connection-registry"
        ):
            raise PlanValidationError("validation connection root changed")
    elif "/validation/" in connection_root:
        raise PlanValidationError("production plan contains validation root")

    identity_values = _values(
        resources["azurerm_user_assigned_identity.ontology_coordinator"]
    )
    tags = identity_values.get("tags") or {}
    marker = tags.get("aiops_validation_fixture") if isinstance(tags, Mapping) else None
    if environment == "validation" and marker != MARKER_VALUE:
        raise PlanValidationError("coordinator injection tag changed")
    if environment == "production" and marker is not None:
        raise PlanValidationError("production plan contains validation fixture tag")

    if environment == "validation":
        coordinator_identity = str(identity_values.get("id") or "")
        if not coordinator_identity:
            fixture_identity = _single(
                _values(
                    resources[
                        "azurerm_container_app_job.ontology_fixture_prepare[0]"
                    ]
                ).get("identity"),
                "fixture.identity",
            )
            coordinator_identity = str(
                (fixture_identity.get("identity_ids") or [""])[0]
            )
        for terraform_name, (display_name, argument) in _FIXTURE_EXPECTATIONS.items():
            templates[terraform_name] = _validate_fixture(
                resources[
                    f"azurerm_container_app_job.{terraform_name}[0]"
                ],
                terraform_name=terraform_name,
                display_name=display_name,
                argument=argument,
                coordinator_identity=coordinator_identity,
                expected_digest=api_digest,
            )
    else:
        fixture_addresses = {
            address
            for address in resources
            if "ontology_fixture_" in address
        }
        if fixture_addresses:
            raise PlanValidationError("production plan contains fixture Job")

    delete_count = sum("delete" in actions for actions in changes.values())
    replace_count = sum(len(actions) == 2 for actions in changes.values())
    change_classes: dict[str, int] = {}
    for actions in changes.values():
        key = "/".join(actions)
        change_classes[key] = change_classes.get(key, 0) + 1
    return {
        "environment": environment,
        "plan_digest": _canonical_hash(plan),
        "accepted_addresses": sorted(expected),
        "changed_addresses": sorted(changes),
        "change_classes": dict(sorted(change_classes.items())),
        "delete_count": delete_count,
        "replace_count": replace_count,
        "template_hashes": dict(sorted(templates.items())),
        "root_hashes": {
            **dict(sorted(api_root_hashes.items())),
            "coordinator_connection": _canonical_hash(connection_root),
        },
        "image_digests": {"api": api_digest, "web": web_digest},
        "no_runtime_job_start_grants": True,
    }


def _reject_sensitive_evidence(value: Any, *, path: str = "evidence") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).casefold()
            if normalized in _FORBIDDEN_EVIDENCE_KEYS:
                raise PlanValidationError(f"unsanitized evidence key: {path}.{key}")
            _reject_sensitive_evidence(child, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_sensitive_evidence(child, path=f"{path}[{index}]")
    elif isinstance(value, str):
        lowered = value.casefold()
        if (
            "https://" in lowered
            or "abfss://" in lowered
            or MARKER_VALUE.casefold() in lowered
        ):
            raise PlanValidationError(f"unsanitized evidence value: {path}")


def validate_deployment_evidence(
    evidence: Mapping[str, Any], *, require_applied: bool
) -> dict[str, Any]:
    """Validate the closed, hash-only retained deployment evidence."""

    _reject_sensitive_evidence(evidence)
    if evidence.get("schema_version") != "1.0.0":
        raise PlanValidationError("deployment evidence schema changed")
    status = evidence.get("status")
    if status not in {"applied", "superseded"}:
        raise PlanValidationError("deployment evidence status changed")
    if require_applied and status != "applied":
        raise PlanValidationError("deployment evidence is not applied")
    if status == "superseded" and (
        not isinstance(evidence.get("superseded_at"), str)
        or evidence.get("superseded_reason_code")
        != "concurrent_shared_deployment"
    ):
        raise PlanValidationError(
            "superseded deployment evidence lacks closed checkpoint metadata"
        )
    plans = evidence.get("plans")
    if not isinstance(plans, Mapping) or set(plans) != {
        "production",
        "validation",
    }:
        raise PlanValidationError("both production and validation plans are required")
    for environment, expected in (
        ("production", EXPECTED_PRODUCTION_ADDRESSES),
        ("validation", EXPECTED_VALIDATION_ADDRESSES),
    ):
        plan = plans.get(environment)
        if not isinstance(plan, Mapping):
            raise PlanValidationError(f"{environment} plan evidence missing")
        if plan.get("environment") != environment:
            raise PlanValidationError(f"{environment} classification changed")
        if plan.get("accepted_addresses") != sorted(expected):
            raise PlanValidationError(
                f"{environment} accepted address allowlist changed"
            )
        if plan.get("delete_count") != 0 or plan.get("replace_count") != 0:
            raise PlanValidationError(f"{environment} plan is destructive")
        if plan.get("no_runtime_job_start_grants") is not True:
            raise PlanValidationError(f"{environment} Job-start denial missing")
    live = evidence.get("live")
    if not isinstance(live, Mapping):
        raise PlanValidationError("live evidence missing")
    if require_applied and live.get("applied") is not True:
        raise PlanValidationError("live apply evidence missing")
    if status == "superseded" and live.get("applied") is not False:
        raise PlanValidationError(
            "superseded deployment evidence cannot claim current live apply"
        )
    required_true = (
        "no_runtime_job_start_grants",
        "deployment_principal_fixture_access",
        "api_apps_identity",
        "api_has_no_publisher_credential",
    )
    for name in required_true:
        if live.get(name) is not True:
            raise PlanValidationError(f"live assertion failed: {name}")
    before = live.get("template_hashes_before")
    after = live.get("template_hashes_after")
    if not isinstance(before, Mapping) or before != after:
        raise PlanValidationError("live fixture template hashes changed")
    image_digests = live.get("image_digests")
    if not isinstance(image_digests, Mapping) or any(
        not _DIGEST_RE.fullmatch(str(value))
        for value in image_digests.values()
    ):
        raise PlanValidationError("live image digest evidence is invalid")
    return dict(evidence)


def _load(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise PlanValidationError(f"{path} must contain a JSON object")
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--production-plan-json", type=Path)
    parser.add_argument("--validation-plan-json", type=Path)
    parser.add_argument("--api-digest", default="")
    parser.add_argument("--web-digest", default="")
    parser.add_argument("--require-applied", action="store_true")
    for flag in (
        "assert-exact-accepted-addresses",
        "assert-dispatch-workspace-lakehouse-roles-dependencies",
        "assert-fixed-fixture-job-templates",
        "assert-no-runtime-job-start-grants",
        "assert-validation-connection-root",
        "assert-production-fixture-absence",
        "assert-coordinator-injection-tag",
        "assert-api-ontology-roots",
        "assert-api-apps-identity",
        "assert-no-api-publisher-credential",
        "fail-on-unexpected-change",
    ):
        parser.add_argument(f"--{flag}", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.production_plan_json or args.validation_plan_json:
        if not (
            args.production_plan_json
            and args.validation_plan_json
            and args.api_digest
            and args.web_digest
        ):
            raise PlanValidationError(
                "both saved-plan JSON files and both image digests are required"
            )
        result = {
            "production": validate_saved_plan(
                _load(args.production_plan_json),
                environment="production",
                expected_image_digests={
                    "api": args.api_digest,
                    "web": args.web_digest,
                },
            ),
            "validation": validate_saved_plan(
                _load(args.validation_plan_json),
                environment="validation",
                expected_image_digests={
                    "api": args.api_digest,
                    "web": args.web_digest,
                },
            ),
        }
        print(json.dumps(result, sort_keys=True))
        return 0
    evidence = validate_deployment_evidence(
        _load(args.evidence), require_applied=args.require_applied
    )
    print(
        json.dumps(
            {
                "status": evidence["status"],
                "schema_version": evidence["schema_version"],
                "validated": True,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
