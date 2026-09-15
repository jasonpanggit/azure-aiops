#!/usr/bin/env python3
"""Validate sanitized Azure SRE Agent import and RBAC evidence offline."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SUBSCRIPTION_ID = "a87a8e64-a52a-4aa8-a760-5e8919d23cd1"
TENANT_ID = "ffc83107-fcc0-4d2e-8798-d582da36505e"
RESOURCE_ID = (
    f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/rg-sredemo-dev"
    "/providers/Microsoft.App/agents/sre-agent-sredemo"
)
RESOURCE_TYPE = "Microsoft.App/agents"
API_VERSION = "2026-01-01"
LOCATION = "australiaeast"
SYSTEM_PRINCIPAL_ID = "003cb2df-6d1f-4555-ba0b-60766e616f2d"
USER_PRINCIPAL_ID = "5b3b9ec4-16fb-4c0f-96fb-16887062f976"
USER_CLIENT_ID = "aac9179b-4f55-4d7b-8b8e-6e719e5f2dac"
USER_ASSIGNED_IDENTITY_ID = (
    f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/rg-sredemo-dev"
    "/providers/Microsoft.ManagedIdentity/userAssignedIdentities"
    "/sre-agent-sredemo-amncvvib6atbg"
)
APPLICATION_INSIGHTS_APP_ID = "55f20823-66c8-4f3a-b987-6cfc3ab096a5"
IMPORT_ADDRESS = "azapi_resource.sre_agent[0]"
RECOMMENDED_TFVARS = Path("infra/terraform/sre-agent.import.tfvars.json")

EXPECTED_MANAGED_RESOURCES = (
    f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/rg-sredemo-dev",
    (
        f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/rg-sredemo-dev"
        "/providers/Microsoft.App/containerapps/ca-api-sredemo-dev"
    ),
    (
        f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/rg-sredemo-dev"
        "/providers/Microsoft.App/containerapps/ca-web-sredemo-dev"
    ),
    (
        f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/rg-sredemo-dev"
        "/providers/microsoft.insights/components/appi-sredemo-dev"
    ),
)

READ_ONLY_PROPERTIES = frozenset(
    {
        "agentEndpoint",
        "outboundIpAddresses",
        "powerState",
        "provisioningState",
        "runningState",
    }
)
ALLOWED_RESOURCE_FIELDS = frozenset(
    {
        "id",
        "identity",
        "location",
        "name",
        "properties",
        "type",
    }
)
ALLOWED_IDENTITY_FIELDS = frozenset(
    {
        "principalId",
        "tenantId",
        "type",
        "userAssignedIdentities",
    }
)
ALLOWED_USER_IDENTITY_FIELDS = frozenset({"clientId", "principalId"})
ALLOWED_PROPERTIES = frozenset(
    {
        "actionConfiguration",
        "agentIdentity",
        "agentSpaceId",
        "aoaiDeploymentSku",
        "dashboardConfiguration",
        "defaultModel",
        "experimentalSettings",
        "firstPartyConfiguration",
        "gitHubConfiguration",
        "incidentManagementConfiguration",
        "knowledgeGraphConfiguration",
        "logConfiguration",
        "mcpServers",
        "monthlyAgentUnitLimit",
        "outboundConnectionConfiguration",
        "permissions",
        "sandboxConfiguration",
        "upgradeChannel",
        "vnetConfiguration",
    }
)
REQUIRED_PROPERTIES = frozenset(
    {
        "actionConfiguration",
        "aoaiDeploymentSku",
        "defaultModel",
        "experimentalSettings",
        "incidentManagementConfiguration",
        "knowledgeGraphConfiguration",
        "logConfiguration",
        "monthlyAgentUnitLimit",
        "sandboxConfiguration",
        "upgradeChannel",
    }
)
KNOWN_ACCESS_ROLES = frozenset(
    {
        "Application Insights Component Contributor",
        "Container Apps Operator",
        "Log Analytics Reader",
        "Monitoring Contributor",
        "Monitoring Reader",
        "Reader",
    }
)


class PreflightError(ValueError):
    """Raised when supplied evidence cannot safely authorize an import."""


def load_json(path: Path) -> dict[str, Any]:
    """Load a JSON object from ``path`` with deterministic error reporting."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PreflightError(f"cannot read JSON evidence {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PreflightError(f"JSON evidence {path} must contain an object")
    return value


def validate_resource_evidence(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the exact sanitized live resource contract and return import data."""
    _reject_unknown_fields(payload, {"apiVersion", "resource"}, "resource evidence")
    if payload.get("apiVersion") != API_VERSION:
        raise PreflightError(f"apiVersion must be exactly {API_VERSION}")
    resource = _mapping(payload.get("resource"), "resource")
    _reject_unknown_fields(resource, ALLOWED_RESOURCE_FIELDS, "resource")
    _equal_ci(resource.get("id"), RESOURCE_ID, "resource.id")
    if resource.get("name") != "sre-agent-sredemo":
        raise PreflightError("resource.name must be exactly sre-agent-sredemo")
    _equal_ci(resource.get("type"), RESOURCE_TYPE, "resource.type")
    _equal_ci(resource.get("location"), LOCATION, "resource.location")

    identity = _mapping(resource.get("identity"), "resource.identity")
    _reject_unknown_fields(identity, ALLOWED_IDENTITY_FIELDS, "resource.identity")
    identity_types = {
        item.strip() for item in str(identity.get("type", "")).split(",") if item.strip()
    }
    if identity_types != {"SystemAssigned", "UserAssigned"}:
        raise PreflightError(
            "resource.identity.type must contain SystemAssigned and UserAssigned"
        )
    if identity.get("principalId") != SYSTEM_PRINCIPAL_ID:
        raise PreflightError("resource.identity.principalId does not match the SMI")
    if identity.get("tenantId") != TENANT_ID:
        raise PreflightError("resource.identity.tenantId is outside the selected tenant")

    assigned = _mapping(
        identity.get("userAssignedIdentities"),
        "resource.identity.userAssignedIdentities",
    )
    if len(assigned) != 1:
        raise PreflightError("resource must have exactly one user-assigned identity")
    assigned_id, assigned_value = next(iter(assigned.items()))
    _equal_ci(assigned_id, USER_ASSIGNED_IDENTITY_ID, "user-assigned identity ID")
    assigned_details = _mapping(assigned_value, "user-assigned identity details")
    _reject_unknown_fields(
        assigned_details,
        ALLOWED_USER_IDENTITY_FIELDS,
        "user-assigned identity details",
    )
    if assigned_details.get("principalId") != USER_PRINCIPAL_ID:
        raise PreflightError("user-assigned identity principalId does not match")
    if assigned_details.get("clientId") != USER_CLIENT_ID:
        raise PreflightError("user-assigned identity clientId does not match")

    properties = _mapping(resource.get("properties"), "resource.properties")
    read_only = sorted(READ_ONLY_PROPERTIES.intersection(properties))
    if read_only:
        raise PreflightError(
            "sanitized resource contains read-only properties: " + ", ".join(read_only)
        )
    unknown = sorted(set(properties).difference(ALLOWED_PROPERTIES))
    if unknown:
        raise PreflightError(
            "sanitized resource contains unrecognized properties: " + ", ".join(unknown)
        )
    missing = sorted(REQUIRED_PROPERTIES.difference(properties))
    if missing:
        raise PreflightError(
            "sanitized resource is missing required properties: " + ", ".join(missing)
        )

    _validate_action(properties)
    managed_resources = _validate_knowledge_graph(properties)
    _validate_incident(properties)
    _validate_model_and_runtime(properties)
    _validate_log_configuration(properties)
    _validate_null_and_blocked_properties(properties)

    return build_import_contract(managed_resources)


def build_import_contract(managed_resources: Sequence[str]) -> dict[str, Any]:
    """Build the exact non-secret tfvars fragment and future import command."""
    tfvars = {
        "enable_sre_agent_management": True,
        "sre_agent_managed_resources": list(managed_resources),
    }
    tfvars_argument = RECOMMENDED_TFVARS.name
    command = _import_command(tfvars_argument)
    return {
        "status": "resource-ready",
        "resourceId": RESOURCE_ID,
        "importAddress": IMPORT_ADDRESS,
        "tfvarsPath": str(RECOMMENDED_TFVARS),
        "tfvars": tfvars,
        "importCommand": command,
        "liveMutationPerformed": False,
    }


def _import_command(tfvars_argument: str) -> str:
    return " ".join(
        [
            "terraform",
            "-chdir=infra/terraform",
            "import",
            "-input=false",
            f"-var-file={shlex.quote(tfvars_argument)}",
            _single_quote(IMPORT_ADDRESS),
            _single_quote(RESOURCE_ID),
        ]
    )


def validate_rbac_evidence(
    payload: Mapping[str, Any],
    managed_resources: Sequence[str] = EXPECTED_MANAGED_RESOURCES,
) -> dict[str, Any]:
    """Validate complete supplied RBAC listings for both known principals."""
    _reject_unknown_fields(
        payload,
        {
            "includeInherited",
            "principals",
            "queriedSubscriptionIds",
            "subscriptionId",
            "tenantId",
            "visibleTenantSubscriptionIds",
        },
        "RBAC evidence",
    )
    if payload.get("subscriptionId") != SUBSCRIPTION_ID:
        raise PreflightError("RBAC evidence subscriptionId does not match")
    if payload.get("tenantId") != TENANT_ID:
        raise PreflightError("RBAC evidence tenantId does not match")
    if payload.get("includeInherited") is not True:
        raise PreflightError("RBAC evidence must include inherited assignments")

    visible = _string_list(
        payload.get("visibleTenantSubscriptionIds"),
        "visibleTenantSubscriptionIds",
    )
    queried = _string_list(
        payload.get("queriedSubscriptionIds"),
        "queriedSubscriptionIds",
    )
    if SUBSCRIPTION_ID not in visible:
        raise PreflightError("selected subscription is absent from visible tenant evidence")
    if SUBSCRIPTION_ID not in queried:
        raise PreflightError("selected subscription was not queried for RBAC")

    principal_rows = payload.get("principals")
    if not isinstance(principal_rows, list):
        raise PreflightError("RBAC evidence principals must be a list")
    expected_principals = {SYSTEM_PRINCIPAL_ID, USER_PRINCIPAL_ID}
    indexed: dict[str, Mapping[str, Any]] = {}
    for index, row in enumerate(principal_rows):
        principal = _mapping(row, f"principals[{index}]")
        _reject_unknown_fields(
            principal,
            {"principalId", "queries"},
            f"principals[{index}]",
        )
        principal_id = principal.get("principalId")
        if principal_id not in expected_principals:
            raise PreflightError(f"unexpected principalId in RBAC evidence: {principal_id}")
        if principal_id in indexed:
            raise PreflightError(f"duplicate principal RBAC evidence: {principal_id}")
        indexed[str(principal_id)] = principal
    missing_principals = sorted(expected_principals.difference(indexed))
    if missing_principals:
        raise PreflightError(
            "RBAC evidence is missing principals: " + ", ".join(missing_principals)
        )

    visible_set = {value.casefold() for value in visible}
    queried_set = {value.casefold() for value in queried}
    if len(visible_set) != len(visible):
        raise PreflightError("visible tenant subscription evidence contains duplicates")
    if len(queried_set) != len(queried):
        raise PreflightError("queried subscription evidence contains duplicates")
    if visible_set != queried_set:
        raise PreflightError(
            "queried subscriptions must exactly match visible tenant subscriptions"
        )

    normalized: dict[str, list[dict[str, str]]] = {}
    for principal_id, principal in indexed.items():
        queries = principal.get("queries")
        if not isinstance(queries, list):
            raise PreflightError(f"queries for {principal_id} must be a list")
        normalized[principal_id] = _validate_principal_queries(
            principal_id,
            queries,
            visible_set,
        )

    user_assignments = normalized[USER_PRINCIPAL_ID]
    if not user_assignments:
        raise PreflightError("user-assigned identity has no selected-subscription access")
    if not any(
        row["scope"].casefold() == f"/subscriptions/{SUBSCRIPTION_ID}".casefold()
        and row["roleDefinitionName"] in KNOWN_ACCESS_ROLES
        for row in user_assignments
    ):
        raise PreflightError(
            "user-assigned identity lacks unambiguous selected-subscription access"
        )
    for resource_id in managed_resources:
        if not any(
            row["roleDefinitionName"] in KNOWN_ACCESS_ROLES
            and _scope_covers(row["scope"], resource_id)
            for row in user_assignments
        ):
            raise PreflightError(
                f"user-assigned identity lacks recognized access covering {resource_id}"
            )

    return {
        "status": "rbac-ready",
        "subscriptionId": SUBSCRIPTION_ID,
        "systemAssignedAssignmentCount": len(normalized[SYSTEM_PRINCIPAL_ID]),
        "userAssignedAssignmentCount": len(user_assignments),
        "coveredManagedResources": list(managed_resources),
        "outsideSubscriptionAssignments": 0,
        "liveMutationPerformed": False,
    }


def _validate_action(properties: Mapping[str, Any]) -> None:
    action = _mapping(properties.get("actionConfiguration"), "actionConfiguration")
    if action.get("mode") == "ReadOnly":
        raise PreflightError("read-only SRE Agent action mode cannot be imported")
    expected = {
        "accessLevel": "Low",
        "identity": USER_ASSIGNED_IDENTITY_ID,
        "mode": "Review",
    }
    _exact_mapping_ci_ids(action, expected, "actionConfiguration", {"identity"})


def _validate_knowledge_graph(properties: Mapping[str, Any]) -> tuple[str, ...]:
    graph = _mapping(
        properties.get("knowledgeGraphConfiguration"),
        "knowledgeGraphConfiguration",
    )
    _equal_ci(
        graph.get("identity"),
        USER_ASSIGNED_IDENTITY_ID,
        "knowledgeGraphConfiguration.identity",
    )
    resources = _string_list(
        graph.get("managedResources"),
        "knowledgeGraphConfiguration.managedResources",
    )
    if len(resources) != len({item.casefold() for item in resources}):
        raise PreflightError("managedResources contains duplicate resource IDs")
    expected = {item.casefold() for item in EXPECTED_MANAGED_RESOURCES}
    actual = {item.casefold() for item in resources}
    if actual != expected:
        raise PreflightError("managedResources does not match the exact observed set")
    prefix = f"/subscriptions/{SUBSCRIPTION_ID}/"
    if any(not item.casefold().startswith(prefix.casefold()) for item in resources):
        raise PreflightError("managedResources contains a cross-subscription resource")
    return tuple(resources)


def _validate_incident(properties: Mapping[str, Any]) -> None:
    incident = _mapping(
        properties.get("incidentManagementConfiguration"),
        "incidentManagementConfiguration",
    )
    expected = {
        "apiConnectionName": None,
        "connectionName": "azmonitor",
        "connectionUrl": None,
        "oboUser": "",
        "type": "AzMonitor",
    }
    for key, value in expected.items():
        if key in incident and incident[key] != value:
            raise PreflightError(
                f"incidentManagementConfiguration.{key} does not match"
            )
    if incident.get("connectionName") != "azmonitor":
        raise PreflightError("incidentManagementConfiguration.connectionName is required")
    if incident.get("oboUser") != "":
        raise PreflightError("incidentManagementConfiguration.oboUser must be empty")
    if incident.get("type") != "AzMonitor":
        raise PreflightError("incidentManagementConfiguration.type must be AzMonitor")
    _require_absent_secret(incident, "connectionKey", "incident management")


def _validate_model_and_runtime(properties: Mapping[str, Any]) -> None:
    model = _mapping(properties.get("defaultModel"), "defaultModel")
    if model != {"name": "Automatic", "provider": "MicrosoftFoundry"}:
        raise PreflightError("defaultModel does not match the observed contract")
    if properties.get("aoaiDeploymentSku") != "GlobalStandard":
        raise PreflightError("aoaiDeploymentSku must be GlobalStandard")
    if properties.get("experimentalSettings") != {"EnableWorkspaceTools": True}:
        raise PreflightError("experimentalSettings does not match the observed contract")
    if properties.get("monthlyAgentUnitLimit") != 10000:
        raise PreflightError("monthlyAgentUnitLimit must be 10000")
    sandbox = _mapping(properties.get("sandboxConfiguration"), "sandboxConfiguration")
    egress = _mapping(sandbox.get("egress"), "sandboxConfiguration.egress")
    if egress.get("mode") != "Unrestricted":
        raise PreflightError("sandboxConfiguration.egress.mode must be Unrestricted")
    for key, value in egress.items():
        if key != "mode" and value is not None:
            raise PreflightError(
                f"sandboxConfiguration.egress.{key} must remain null or absent"
            )
    if sandbox.get("packages") is not None:
        raise PreflightError("sandboxConfiguration.packages must remain null or absent")
    if properties.get("upgradeChannel") != "Stable":
        raise PreflightError("upgradeChannel must be Stable")


def _validate_log_configuration(properties: Mapping[str, Any]) -> None:
    log_config = _mapping(properties.get("logConfiguration"), "logConfiguration")
    app_insights = _mapping(
        log_config.get("applicationInsightsConfiguration"),
        "logConfiguration.applicationInsightsConfiguration",
    )
    if app_insights.get("appId") != APPLICATION_INSIGHTS_APP_ID:
        raise PreflightError("Application Insights appId does not match")
    if app_insights.get("applicationInsightsResourceId") is not None:
        raise PreflightError("applicationInsightsResourceId must remain null or absent")
    _require_absent_secret(app_insights, "connectionString", "Application Insights")
    if log_config.get("logAnalyticsConfiguration") is not None:
        raise PreflightError("logAnalyticsConfiguration must remain null or absent")


def _validate_null_and_blocked_properties(properties: Mapping[str, Any]) -> None:
    for key in (
        "agentIdentity",
        "agentSpaceId",
        "dashboardConfiguration",
        "firstPartyConfiguration",
        "outboundConnectionConfiguration",
        "permissions",
    ):
        if properties.get(key) is not None:
            raise PreflightError(f"{key} must remain null or absent")
    if properties.get("mcpServers") is not None:
        raise PreflightError("mcpServers remains blocked and must be null or absent")
    github = properties.get("gitHubConfiguration")
    if github is not None:
        github_config = _mapping(github, "gitHubConfiguration")
        _require_absent_secret(github_config, "patTokenOverride", "GitHub")
        if set(github_config).difference({"patTokenOverride"}):
            raise PreflightError("gitHubConfiguration contains unrecognized settings")
    vnet = properties.get("vnetConfiguration")
    if vnet is not None:
        vnet_config = _mapping(vnet, "vnetConfiguration")
        if any(value is not None for value in vnet_config.values()):
            raise PreflightError("vnetConfiguration must contain only null values")


def _validate_assignments(
    principal_id: str,
    assignments: Sequence[object],
    query_subscription_id: str,
) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    selected_prefix = f"/subscriptions/{SUBSCRIPTION_ID}"
    query_prefix = f"/subscriptions/{query_subscription_id}"
    for index, value in enumerate(assignments):
        row = _mapping(value, f"assignments[{principal_id}][{index}]")
        _reject_unknown_fields(
            row,
            {
                "condition",
                "conditionVersion",
                "principalId",
                "principalType",
                "roleDefinitionId",
                "roleDefinitionName",
                "scope",
            },
            f"assignments[{principal_id}][{index}]",
        )
        if row.get("principalId") != principal_id:
            raise PreflightError(f"assignment principalId mismatch for {principal_id}")
        if row.get("principalType") not in (None, "ServicePrincipal"):
            raise PreflightError(f"assignment principalType is ambiguous for {principal_id}")
        if row.get("condition") not in (None, ""):
            raise PreflightError(f"conditional assignment is ambiguous for {principal_id}")
        scope = row.get("scope")
        role_name = row.get("roleDefinitionName")
        if not isinstance(scope, str) or not scope.startswith("/"):
            raise PreflightError(f"assignment scope is invalid for {principal_id}")
        normalized_scope = scope.rstrip("/").casefold()
        normalized_selected = selected_prefix.casefold()
        if normalized_scope != normalized_selected and not normalized_scope.startswith(
            normalized_selected + "/"
        ):
            raise PreflightError(
                f"assignment for {principal_id} permits access outside selected "
                f"subscription: {scope}"
            )
        normalized_query = query_prefix.casefold()
        if normalized_scope != normalized_query and not normalized_scope.startswith(
            normalized_query + "/"
        ):
            raise PreflightError(
                f"assignment scope does not match its query subscription for "
                f"{principal_id}: {scope}"
            )
        if not isinstance(role_name, str) or not role_name:
            raise PreflightError(f"assignment role is ambiguous for {principal_id}")
        key = (scope.casefold(), role_name.casefold())
        if key in seen:
            raise PreflightError(f"duplicate assignment is ambiguous for {principal_id}")
        seen.add(key)
        normalized.append({"scope": scope, "roleDefinitionName": role_name})
    return normalized


def _validate_principal_queries(
    principal_id: str,
    queries: Sequence[object],
    visible_subscription_ids: set[str],
) -> list[dict[str, str]]:
    assignments: list[dict[str, str]] = []
    queried: set[str] = set()
    for index, value in enumerate(queries):
        query = _mapping(value, f"queries[{principal_id}][{index}]")
        _reject_unknown_fields(
            query,
            {"assignments", "includeInherited", "subscriptionId"},
            f"queries[{principal_id}][{index}]",
        )
        subscription_id = query.get("subscriptionId")
        if not isinstance(subscription_id, str) or not subscription_id:
            raise PreflightError(f"query subscriptionId is invalid for {principal_id}")
        normalized_subscription_id = subscription_id.casefold()
        if normalized_subscription_id in queried:
            raise PreflightError(
                f"duplicate subscription query evidence for {principal_id}"
            )
        if normalized_subscription_id not in visible_subscription_ids:
            raise PreflightError(
                f"query subscription is not visible in the selected tenant: "
                f"{subscription_id}"
            )
        if query.get("includeInherited") is not True:
            raise PreflightError(
                f"query for {principal_id} must include inherited assignments"
            )
        query_assignments = query.get("assignments")
        if not isinstance(query_assignments, list):
            raise PreflightError(
                f"query assignments for {principal_id} must be a list"
            )
        assignments.extend(
            _validate_assignments(
                principal_id,
                query_assignments,
                subscription_id,
            )
        )
        queried.add(normalized_subscription_id)
    missing = sorted(visible_subscription_ids.difference(queried))
    if missing:
        raise PreflightError(
            f"RBAC queries for {principal_id} do not cover visible subscriptions: "
            + ", ".join(missing)
        )
    return assignments


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PreflightError(f"{label} must be an object")
    return value


def _reject_unknown_fields(
    value: Mapping[str, Any],
    allowed: set[str] | frozenset[str],
    label: str,
) -> None:
    unknown = sorted(set(value).difference(allowed))
    if unknown:
        raise PreflightError(
            f"{label} contains unrecognized or output-only fields: "
            + ", ".join(unknown)
        )


def _string_list(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise PreflightError(f"{label} must be a list of non-empty strings")
    return value


def _equal_ci(value: object, expected: str, label: str) -> None:
    if not isinstance(value, str) or value.casefold() != expected.casefold():
        raise PreflightError(f"{label} does not match {expected}")


def _exact_mapping_ci_ids(
    actual: Mapping[str, Any],
    expected: Mapping[str, Any],
    label: str,
    case_insensitive_keys: set[str],
) -> None:
    if set(actual) != set(expected):
        raise PreflightError(f"{label} keys do not match the expected contract")
    for key, expected_value in expected.items():
        if key in case_insensitive_keys:
            _equal_ci(actual.get(key), str(expected_value), f"{label}.{key}")
        elif actual.get(key) != expected_value:
            raise PreflightError(f"{label}.{key} does not match")


def _require_absent_secret(
    container: Mapping[str, Any],
    key: str,
    label: str,
) -> None:
    if key in container:
        raise PreflightError(f"{label} evidence must omit secret field {key}")


def _scope_covers(scope: str, resource_id: str) -> bool:
    normalized_scope = scope.rstrip("/").casefold()
    normalized_resource = resource_id.rstrip("/").casefold()
    return normalized_resource == normalized_scope or normalized_resource.startswith(
        normalized_scope + "/"
    )


def _single_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _write_tfvars(path: Path, tfvars: Mapping[str, Any]) -> str:
    if not path.name.endswith(".tfvars.json"):
        raise PreflightError("tfvars output must end with .tfvars.json")
    resolved = path.resolve()
    try:
        repository_relative = resolved.relative_to(REPO_ROOT)
    except ValueError:
        tfvars_argument = str(resolved)
    else:
        if (
            repository_relative.parent != Path("infra/terraform")
            or not repository_relative.name.endswith(".tfvars.json")
        ):
            raise PreflightError(
                "in-repo tfvars output must be a gitignored "
                "infra/terraform/*.tfvars.json file"
            )
        tfvars_argument = repository_relative.name
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent,
            mode="w",
            encoding="utf-8",
            prefix=f".{path.name}.",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            os.chmod(temporary_path, 0o600)
            handle.write(json.dumps(tfvars, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    return tfvars_argument


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="mode", required=True)

    resource = subparsers.add_parser("resource", help="validate sanitized resource JSON")
    resource.add_argument("--resource-json", required=True, type=Path)
    resource.add_argument(
        "--tfvars-output",
        type=Path,
        help=(
            "optionally write the non-secret tfvars fragment; use "
            "infra/terraform/sre-agent.import.tfvars.json"
        ),
    )

    rbac = subparsers.add_parser("rbac", help="validate supplied RBAC listing JSON")
    rbac.add_argument("--rbac-json", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one offline preflight mode and emit deterministic JSON."""
    args = _parser().parse_args(argv)
    try:
        if args.mode == "resource":
            result = validate_resource_evidence(load_json(args.resource_json))
            if args.tfvars_output is not None:
                tfvars_argument = _write_tfvars(args.tfvars_output, result["tfvars"])
                result["tfvarsPath"] = str(args.tfvars_output)
                result["importCommand"] = _import_command(tfvars_argument)
                result["writtenTfvarsPath"] = str(args.tfvars_output)
        else:
            result = validate_rbac_evidence(load_json(args.rbac_json))
    except PreflightError as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
