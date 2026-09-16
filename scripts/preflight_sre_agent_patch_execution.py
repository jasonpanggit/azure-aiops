#!/usr/bin/env python3
"""Render, validate offline evidence, and collect live SRE readiness safely."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from fnmatch import fnmatchcase
from ipaddress import ip_address
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DEFINITION = REPO_ROOT / "infra/sre-agent/patch-trigger.v1.json"
SUBSCRIPTION_ID = "a87a8e64-a52a-4aa8-a760-5e8919d23cd1"
TENANT_ID = "ffc83107-fcc0-4d2e-8798-d582da36505e"
AGENT_RESOURCE_ID = (
    f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/rg-sredemo-dev"
    "/providers/Microsoft.App/agents/sre-agent-sredemo"
)
AGENT_NAME = "sre-agent-sredemo"
AGENT_API_VERSION = "2026-01-01"
AGENT_ARM_URL = (
    f"https://management.azure.com{AGENT_RESOURCE_ID}?api-version={AGENT_API_VERSION}"
)
API_CONTAINER_APP_RESOURCE_GROUP = "aiops-dev-rg"
API_CONTAINER_APP_NAME = "aiops-dev-api"
SRE_UAI_RESOURCE_ID = (
    f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/rg-sredemo-dev"
    "/providers/Microsoft.ManagedIdentity/userAssignedIdentities"
    "/sre-agent-sredemo-amncvvib6atbg"
)
SRE_UAI_PRINCIPAL_ID = "5b3b9ec4-16fb-4c0f-96fb-16887062f976"
API_UAI_PRINCIPAL_ID = "2c367602-bb4f-4868-8dbb-7f4ca117a719"
API_UAI_RESOURCE_ID = (
    f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/aiops-dev-rg"
    "/providers/Microsoft.ManagedIdentity/userAssignedIdentities/aiops-dev-apps-id"
)
TRIGGER_SCOPE = "59f0a04a-b322-4310-adc9-39ac41e9631e/.default"
THREAD_SCOPE = "https://azuresre.dev/.default"
TRIGGER_ROLE_NAME = "aiops-dev-sre-agent-trigger-invoker"
THREAD_READER_ROLE_NAME = "aiops-dev-sre-agent-thread-reader"
PATCH_ROLE_NAME = "aiops-dev-sre-agent-patch-executor"
TRIGGER_WRITE_DATA_ACTIONS = frozenset({"Microsoft.App/agents/threads/write"})
THREAD_READ_DATA_ACTIONS = frozenset({"Microsoft.App/agents/threads/read"})
TRIGGER_DATA_ACTIONS = TRIGGER_WRITE_DATA_ACTIONS | THREAD_READ_DATA_ACTIONS
PATCH_ACTIONS = frozenset(
    {
        "Microsoft.Compute/virtualMachines/read",
        "Microsoft.Compute/virtualMachines/installPatches/action",
        "Microsoft.HybridCompute/machines/read",
        "Microsoft.HybridCompute/machines/installPatches/action",
    }
)
PATCH_WRITE_ACTIONS = frozenset(
    action for action in PATCH_ACTIONS if action.endswith("/action")
)
SECRET_NAME = "sre-agent-http-trigger-url"
SECRET_ENVIRONMENT_VARIABLE = "AIOPS_SRE_AGENT_TRIGGER_URL"
SECRET_TAG_TRIGGER_ID = "aiops-trigger-id"
SECRET_TAG_TRIGGER_ORIGIN = "aiops-trigger-origin"
SECRET_TAG_CANONICAL_HASH = "aiops-trigger-definition-sha256"
TRIGGER_ID_PATTERN = re.compile(r"^[A-Za-z0-9._~-]{1,256}$")
SUBSCRIPTION_ID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
DEFINITION_FIELDS = frozenset(
    {
        "artifactVersion",
        "description",
        "name",
        "payloadSchema",
        "prompt",
        "runMode",
        "threadGrouping",
    }
)
ARTIFACT_FIELDS = DEFINITION_FIELDS | {"keyVault"}
LIVE_TRIGGER_REQUIRED_FIELDS = {"enabled", "id", "prompt", "runMode", "threadGrouping"}
LIVE_TRIGGER_OPTIONAL_FIELDS = DEFINITION_FIELDS - {
    "prompt",
    "runMode",
    "threadGrouping",
}
RAW_LIVE_TRIGGER_FIELDS = frozenset(
    {
        "agent",
        "agentMode",
        "agentPrompt",
        "createdAt",
        "createdBy",
        "description",
        "executionCount",
        "id",
        "lastExecutionTime",
        "modelTier",
        "name",
        "threadId",
        "triggerEnabled",
        "triggerLastCalledAt",
        "triggerUrl",
    }
)
SECRET_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9]+$")


class ReadinessError(ValueError):
    """Raised when supplied readiness evidence fails closed."""


CommandRunner = Callable[[Sequence[str]], tuple[int, bytes, bytes]]
HttpRequester = Callable[[str, str], tuple[int, bytes, Mapping[str, str]]]


def load_json_value(path: Path) -> Any:
    """Load one JSON value from ``path`` with deterministic errors."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReadinessError(f"cannot read JSON {path}: {exc}") from exc


def load_json(path: Path) -> dict[str, Any]:
    """Load one JSON object from ``path`` with deterministic errors."""
    value = load_json_value(path)
    if not isinstance(value, dict):
        raise ReadinessError(f"JSON {path} must contain an object")
    return value


def canonical_trigger_body(definition: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and return the versioned canonical trigger review body."""
    _exact_fields(definition, ARTIFACT_FIELDS, "trigger definition")
    if definition.get("artifactVersion") != "1.0":
        raise ReadinessError("artifactVersion must be exactly 1.0")
    if definition.get("name") != "aiops-selected-patch-execution-v1":
        raise ReadinessError("trigger name does not match the versioned contract")
    if definition.get("runMode") != "Autonomous":
        raise ReadinessError("trigger runMode must be Autonomous")
    if definition.get("threadGrouping") != "NewThreadPerRun":
        raise ReadinessError("trigger threadGrouping must be NewThreadPerRun")
    _canonical_secret_contract(definition)
    for field in ("description", "prompt"):
        if not isinstance(definition.get(field), str) or not definition[field].strip():
            raise ReadinessError(f"trigger {field} must be a non-empty string")

    prompt = definition["prompt"]
    required_prompt_terms = (
        "run_id",
        "subscription_id",
        "target_id",
        "patch_ids",
        "reboot_setting",
        "Do not discover",
        "fall back to all available patches",
        "stop without fallback",
    )
    missing_terms = [term for term in required_prompt_terms if term not in prompt]
    if missing_terms:
        raise ReadinessError(
            "trigger prompt is missing locked terms: " + ", ".join(missing_terms)
        )

    payload_schema = _mapping(definition.get("payloadSchema"), "payloadSchema")
    required = _string_list(payload_schema.get("required"), "payloadSchema.required")
    properties = _mapping(payload_schema.get("properties"), "payloadSchema.properties")
    expected_fields = {
        "approved_by",
        "operation",
        "patch_ids",
        "reboot_setting",
        "requested_by",
        "run_id",
        "schema_version",
        "subscription_id",
        "target_id",
        "target_kind",
    }
    if payload_schema.get("type") != "object":
        raise ReadinessError("payloadSchema.type must be object")
    if payload_schema.get("additionalProperties") is not False:
        raise ReadinessError("payloadSchema.additionalProperties must be false")
    if set(required) != expected_fields or set(properties) != expected_fields:
        raise ReadinessError("payloadSchema fields do not match the runtime envelope")
    if properties["schema_version"] != {"const": "1.0"}:
        raise ReadinessError("payload schema_version must be fixed at 1.0")
    if properties["operation"] != {"const": "install_patches"}:
        raise ReadinessError("payload operation must be fixed at install_patches")

    return {field: definition[field] for field in sorted(DEFINITION_FIELDS)}


def _runtime_patch_envelope_contract() -> dict[str, Any]:
    try:
        from src.operations.patching.sre_agent_adapter import (
            sre_agent_patch_envelope_contract,
        )
    except ImportError as exc:
        raise ReadinessError(
            "cannot import runtime SRE Agent patch envelope contract"
        ) from exc
    contract = sre_agent_patch_envelope_contract()
    if not isinstance(contract, dict):
        raise ReadinessError("runtime SRE Agent patch envelope contract is invalid")
    return contract


def _validate_runtime_outbound_envelope(
    definition: Mapping[str, Any],
) -> dict[str, Any]:
    expected_schema = _mapping(definition.get("payloadSchema"), "payloadSchema")
    runtime_schema = _mapping(
        _runtime_patch_envelope_contract(),
        "runtime SRE Agent patch envelope contract",
    )
    if runtime_schema != expected_schema:
        raise ReadinessError("runtime outbound SRE Agent patch envelope drift detected")
    return {
        "status": "runtime-outbound-envelope-ready",
        "source": "src.operations.patching.sre_agent_adapter",
        "serverPayloadSchemaAvailable": False,
        "serverPayloadSchemaStatus": "not-returned-by-live-api",
        "validatedAgainst": "runtime-locked-outgoing-envelope",
    }


def canonical_hash(body: Mapping[str, Any]) -> str:
    """Return the SHA-256 hash of deterministic canonical JSON."""
    return _json_sha256(body)


def _json_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_trigger_evidence(
    payload: Mapping[str, Any],
    canonical_body: Mapping[str, Any],
    *,
    expected_trigger_id: str,
    expected_trigger_origin: str,
    definition: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate normalized read-only trigger evidence against the canonical body."""
    _exact_fields(
        payload, {"captureVersion", "sourceOrigin", "trigger"}, "trigger evidence"
    )
    if payload.get("captureVersion") != "1.0":
        raise ReadinessError("trigger evidence captureVersion must be 1.0")
    source_origin = _https_origin(payload.get("sourceOrigin"), "trigger sourceOrigin")
    expected_origin = _https_origin(
        expected_trigger_origin,
        "expected trigger origin",
    )
    if source_origin != expected_origin:
        raise ReadinessError("trigger sourceOrigin does not match the reviewed origin")
    trigger = _mapping(payload.get("trigger"), "trigger")
    trigger_fields = set(LIVE_TRIGGER_REQUIRED_FIELDS) | (
        set(trigger) & LIVE_TRIGGER_OPTIONAL_FIELDS
    )
    _exact_fields(trigger, trigger_fields, "trigger")
    missing_trigger_fields = sorted(LIVE_TRIGGER_REQUIRED_FIELDS - set(trigger))
    if missing_trigger_fields:
        raise ReadinessError(
            "trigger is missing required normalized fields: "
            + ", ".join(missing_trigger_fields)
        )
    trigger_id = _trigger_id(trigger.get("id"), "trigger.id")
    reviewed_trigger_id = _trigger_id(
        expected_trigger_id,
        "expected trigger ID",
    )
    if trigger_id != reviewed_trigger_id:
        raise ReadinessError("trigger.id does not match the reviewed trigger ID")
    if trigger.get("enabled") is not True:
        raise ReadinessError("trigger must be enabled")
    actual_body = {
        field: trigger[field]
        for field in (set(DEFINITION_FIELDS) - {"payloadSchema"})
        if field in trigger
    }
    _exact_fields(canonical_body, DEFINITION_FIELDS, "canonical trigger body")
    expected_body = dict(canonical_body)
    drift = sorted(
        field for field in actual_body if actual_body[field] != expected_body[field]
    )
    if (
        "payloadSchema" in trigger
        and trigger["payloadSchema"] != expected_body["payloadSchema"]
    ):
        drift.append("payloadSchema")
    if drift:
        raise ReadinessError("trigger drift detected in: " + ", ".join(drift))
    envelope_result = (
        _validate_runtime_outbound_envelope(definition)
        if definition is not None
        else {
            "status": "not-validated",
            "serverPayloadSchemaAvailable": "payloadSchema" in trigger,
            "serverPayloadSchemaStatus": (
                "returned-by-evidence"
                if "payloadSchema" in trigger
                else "not-returned-by-live-api"
            ),
        }
    )
    return {
        "status": "trigger-ready",
        "triggerId": trigger_id,
        "triggerOrigin": source_origin,
        "canonicalTriggerName": expected_body["name"],
        "canonicalTriggerNameEvidence": (
            "canonical definition hash bound to Key Vault metadata"
        ),
        "canonicalHash": canonical_hash(expected_body),
        "description": {
            "serverDescriptionAvailable": "description" in trigger,
            "serverDescriptionStatus": (
                "returned-by-live-api"
                if "description" in trigger
                else "not-returned-or-empty-by-live-api"
            ),
            "validatedAgainst": "canonical-definition-hash",
        },
        "payloadSchema": envelope_result,
    }


def validate_agent_resource(
    payload: Mapping[str, Any],
    *,
    expected_agent_endpoint: str,
    target_prefix: str,
) -> dict[str, Any]:
    """Validate sanitized running agent state and managed-resource coverage."""
    _exact_fields(payload, {"apiVersion", "resource"}, "agent evidence")
    if payload.get("apiVersion") != "2026-01-01":
        raise ReadinessError("agent apiVersion must be 2026-01-01")
    resource = _mapping(payload.get("resource"), "agent resource")
    _exact_fields(resource, {"id", "name", "properties", "type"}, "agent resource")
    _equal_ci(resource.get("id"), AGENT_RESOURCE_ID, "agent resource.id")
    if resource.get("name") != AGENT_NAME:
        raise ReadinessError(f"agent resource.name must be {AGENT_NAME}")
    _equal_ci(resource.get("type"), "Microsoft.App/agents", "agent resource.type")
    properties = _mapping(resource.get("properties"), "agent properties")
    _exact_fields(
        properties,
        {
            "actionConfiguration",
            "agentEndpoint",
            "knowledgeGraphConfiguration",
            "powerState",
            "provisioningState",
            "runningState",
        },
        "agent properties",
    )
    if properties.get("provisioningState") != "Succeeded":
        raise ReadinessError("agent provisioningState must be Succeeded")
    if properties.get("runningState") != "Running":
        raise ReadinessError("agent runningState must be Running")
    if properties.get("powerState") != "Running":
        raise ReadinessError("agent powerState must be Running")
    endpoint = _https_origin(properties.get("agentEndpoint"), "agentEndpoint")
    if endpoint != _https_origin(expected_agent_endpoint, "expected agent endpoint"):
        raise ReadinessError("agentEndpoint does not match the reviewed endpoint")

    action = _mapping(properties.get("actionConfiguration"), "actionConfiguration")
    _exact_fields(action, {"accessLevel", "identity", "mode"}, "actionConfiguration")
    if action.get("mode") != "Review" or action.get("accessLevel") != "Low":
        raise ReadinessError("agent global fallback must remain Review/Low")
    _equal_ci(action.get("identity"), SRE_UAI_RESOURCE_ID, "action identity")

    graph = _mapping(
        properties.get("knowledgeGraphConfiguration"),
        "knowledgeGraphConfiguration",
    )
    _exact_fields(graph, {"managedResources"}, "knowledgeGraphConfiguration")
    managed = _string_list(
        graph.get("managedResources"),
        "knowledgeGraphConfiguration.managedResources",
    )
    normalized_target = _target_scope(target_prefix)
    normalized_managed = [_target_scope(scope) for scope in managed]
    if len({scope.casefold() for scope in normalized_managed}) != len(
        normalized_managed
    ):
        raise ReadinessError("managedResources contain duplicate scopes")
    if not any(_scope_covers(scope, normalized_target) for scope in normalized_managed):
        raise ReadinessError("managedResources do not cover the patch target prefix")
    return {
        "status": "agent-ready",
        "agentEndpoint": endpoint,
        "managedResourceCount": len(managed),
        "targetPrefix": normalized_target,
    }


def validate_rbac_evidence(
    payload: Mapping[str, Any],
    *,
    target_prefix: str,
) -> dict[str, Any]:
    """Validate offline RBAC evidence without granting a production verdict."""
    result = _validate_rbac_contract(payload, target_prefix=target_prefix)
    result["status"] = "offline-evidence-valid"
    result["blockers"] = ["fresh live collector required"]
    return result


def _validate_rbac_contract(
    payload: Mapping[str, Any],
    *,
    target_prefix: str,
) -> dict[str, Any]:
    """Validate the complete RBAC contract independent of evidence source."""
    _exact_fields(
        payload,
        {
            "assignmentCaptures",
            "roleDefinitionCaptures",
            "subscriptionId",
            "tenantId",
            "visibleTenantSubscriptionIds",
        },
        "RBAC evidence",
    )
    if payload.get("subscriptionId") != SUBSCRIPTION_ID:
        raise ReadinessError("RBAC subscriptionId does not match")
    if payload.get("tenantId") != TENANT_ID:
        raise ReadinessError("RBAC tenantId does not match")
    visible = _normalized_unique_ids(
        payload.get("visibleTenantSubscriptionIds"),
        "visibleTenantSubscriptionIds",
    )
    if SUBSCRIPTION_ID.casefold() not in visible:
        raise ReadinessError("selected subscription is not visible in the tenant")

    role_definitions = _index_role_definition_captures(
        payload.get("roleDefinitionCaptures")
    )
    principals, referenced_role_ids = _index_assignment_captures(
        payload.get("assignmentCaptures"),
        visible,
        role_definitions,
    )
    if set(principals) != {
        API_UAI_PRINCIPAL_ID.casefold(),
        SRE_UAI_PRINCIPAL_ID.casefold(),
    }:
        raise ReadinessError("RBAC evidence must contain exactly the API and SRE UAIs")
    if referenced_role_ids != set(role_definitions):
        raise ReadinessError(
            "role-definition captures must reconcile one-for-one with raw assignments"
        )

    normalized_target = _target_scope(target_prefix)
    trigger_definition = _require_exact_role(
        role_definitions,
        TRIGGER_ROLE_NAME,
        actions=frozenset(),
        data_actions=TRIGGER_WRITE_DATA_ACTIONS,
    )
    thread_reader_definition = _require_exact_role(
        role_definitions,
        THREAD_READER_ROLE_NAME,
        actions=frozenset(),
        data_actions=THREAD_READ_DATA_ACTIONS,
    )
    patch_definition = _require_exact_role(
        role_definitions,
        PATCH_ROLE_NAME,
        actions=PATCH_ACTIONS,
        data_actions=frozenset(),
    )
    _require_exact_assignment(
        principals[API_UAI_PRINCIPAL_ID.casefold()],
        trigger_definition["id"],
        AGENT_RESOURCE_ID,
        "API UAI trigger role",
    )
    _require_exact_assignment(
        principals[API_UAI_PRINCIPAL_ID.casefold()],
        thread_reader_definition["id"],
        AGENT_RESOURCE_ID,
        "API UAI thread reader role",
    )
    _require_exact_assignment(
        principals[SRE_UAI_PRINCIPAL_ID.casefold()],
        patch_definition["id"],
        normalized_target,
        "SRE UAI patch role",
    )

    for principal_id, assignments in principals.items():
        for assignment in assignments:
            role = role_definitions[assignment["roleDefinitionId"].casefold()]
            assignment_scope = assignment["scope"]
            if (
                principal_id == API_UAI_PRINCIPAL_ID.casefold()
                and _grants_any(role["dataActions"], TRIGGER_DATA_ACTIONS)
                and not (
                    assignment_scope.rstrip("/").casefold()
                    == AGENT_RESOURCE_ID.casefold()
                    and assignment["roleDefinitionId"].casefold()
                    in {
                        trigger_definition["id"].casefold(),
                        thread_reader_definition["id"].casefold(),
                    }
                )
            ):
                raise ReadinessError(
                    "API UAI has a broader fallback role granting agent thread access"
                )
            if (
                principal_id == SRE_UAI_PRINCIPAL_ID.casefold()
                and _grants_any(role["actions"], PATCH_WRITE_ACTIONS)
                and not (
                    assignment_scope.rstrip("/").casefold()
                    == normalized_target.casefold()
                    and assignment["roleDefinitionId"].casefold()
                    == patch_definition["id"].casefold()
                )
            ):
                raise ReadinessError(
                    "SRE UAI has a broader fallback role granting patch writes"
                )
    return {
        "status": "rbac-contract-valid",
        "apiPrincipalId": API_UAI_PRINCIPAL_ID,
        "srePrincipalId": SRE_UAI_PRINCIPAL_ID,
        "targetPrefix": normalized_target,
        "visibleSubscriptionCount": len(visible),
    }


def validate_secret_evidence(
    payload: Mapping[str, Any],
    *,
    expected_secret_id: str,
    expected_trigger_id: str,
    expected_trigger_origin: str,
    expected_canonical_hash: str,
) -> dict[str, Any]:
    """Validate value-free secret metadata bound to the reviewed trigger."""
    _reject_secret_values(payload, "secret evidence")
    _exact_fields(payload, {"metadata", "secretReference"}, "secret evidence")
    reference = _mapping(payload.get("secretReference"), "secretReference")
    _exact_fields(
        reference,
        {"containerAppSecretName", "environmentVariable", "keyVaultSecretId"},
        "secretReference",
    )
    if reference.get("containerAppSecretName") != SECRET_NAME:
        raise ReadinessError("Container Apps secret name does not match")
    if reference.get("environmentVariable") != SECRET_ENVIRONMENT_VARIABLE:
        raise ReadinessError("trigger secret environment variable does not match")
    secret_id = _key_vault_secret_id(
        reference.get("keyVaultSecretId"),
        "secretReference.keyVaultSecretId",
    )
    if secret_id != expected_secret_id:
        raise ReadinessError("secret reference is outside the canonical Key Vault")

    metadata = _mapping(payload.get("metadata"), "metadata")
    _exact_fields(metadata, {"enabled", "expires", "id", "name", "tags"}, "metadata")
    if metadata.get("name") != SECRET_NAME:
        raise ReadinessError("secret metadata name does not match")
    if metadata.get("enabled") is not True:
        raise ReadinessError("trigger secret metadata must be enabled")
    expires = metadata.get("expires")
    if expires is not None:
        try:
            expiry = datetime.fromisoformat(str(expires))
        except ValueError as exc:
            raise ReadinessError("secret metadata expiry is invalid") from exc
        if expiry <= datetime.now(UTC):
            raise ReadinessError("trigger secret metadata is expired")
    metadata_id = _key_vault_secret_id(metadata.get("id"), "metadata.id")
    if metadata_id.casefold() != secret_id.casefold():
        raise ReadinessError("secret metadata does not match the configured reference")
    tags = _mapping(metadata.get("tags"), "metadata.tags")
    _exact_fields(
        tags,
        {
            SECRET_TAG_CANONICAL_HASH,
            SECRET_TAG_TRIGGER_ID,
            SECRET_TAG_TRIGGER_ORIGIN,
        },
        "metadata.tags",
    )
    trigger_id = _trigger_id(expected_trigger_id, "expected trigger ID")
    trigger_origin = _https_origin(
        expected_trigger_origin,
        "expected trigger origin",
    )
    if tags.get(SECRET_TAG_TRIGGER_ID) != trigger_id:
        raise ReadinessError("secret metadata trigger ID attestation does not match")
    if tags.get(SECRET_TAG_TRIGGER_ORIGIN) != trigger_origin:
        raise ReadinessError(
            "secret metadata trigger origin attestation does not match"
        )
    if tags.get(SECRET_TAG_CANONICAL_HASH) != expected_canonical_hash:
        raise ReadinessError(
            "secret metadata canonical hash attestation does not match"
        )
    return {
        "status": "secret-ready",
        "secretName": SECRET_NAME,
        "versionPinned": True,
        "secretValueRead": False,
        "triggerId": trigger_id,
        "triggerOrigin": trigger_origin,
    }


def _validate_secret_against_artifact(
    definition: Mapping[str, Any],
    payload: Mapping[str, Any],
    *,
    expected_trigger_id: str,
    expected_trigger_origin: str,
    expected_canonical_hash: str,
) -> dict[str, Any]:
    reference = _mapping(payload.get("secretReference"), "secretReference")
    expected_secret_id = _canonical_secret_reference(
        definition,
        reference.get("keyVaultSecretId"),
    )
    return validate_secret_evidence(
        payload,
        expected_secret_id=expected_secret_id,
        expected_trigger_id=expected_trigger_id,
        expected_trigger_origin=expected_trigger_origin,
        expected_canonical_hash=expected_canonical_hash,
    )


def build_readiness_report(
    *,
    definition: Mapping[str, Any],
    trigger_evidence: Mapping[str, Any],
    agent_evidence: Mapping[str, Any],
    rbac_evidence: Mapping[str, Any],
    secret_evidence: Mapping[str, Any],
    expected_trigger_id: str,
    expected_trigger_origin: str,
    expected_agent_endpoint: str,
    target_prefix: str,
) -> dict[str, Any]:
    """Run offline gates; offline evidence can never authorize a canary."""
    return _build_readiness_report(
        definition=definition,
        trigger_evidence=trigger_evidence,
        agent_evidence=agent_evidence,
        rbac_validator=lambda: validate_rbac_evidence(
            rbac_evidence,
            target_prefix=target_prefix,
        ),
        secret_evidence=secret_evidence,
        expected_trigger_id=expected_trigger_id,
        expected_trigger_origin=expected_trigger_origin,
        expected_agent_endpoint=expected_agent_endpoint,
        target_prefix=target_prefix,
    )


def _build_readiness_report(
    *,
    definition: Mapping[str, Any],
    trigger_evidence: Mapping[str, Any],
    agent_evidence: Mapping[str, Any],
    rbac_validator: Any,
    secret_evidence: Mapping[str, Any],
    expected_trigger_id: str,
    expected_trigger_origin: str,
    expected_agent_endpoint: str,
    target_prefix: str,
) -> dict[str, Any]:
    body = canonical_trigger_body(definition)
    body_hash = canonical_hash(body)
    checks: dict[str, Any] = {}
    blockers: list[str] = []
    validators = (
        (
            "trigger",
            lambda: validate_trigger_evidence(
                trigger_evidence,
                body,
                expected_trigger_id=expected_trigger_id,
                expected_trigger_origin=expected_trigger_origin,
                definition=definition,
            ),
        ),
        (
            "agent",
            lambda: validate_agent_resource(
                agent_evidence,
                expected_agent_endpoint=expected_agent_endpoint,
                target_prefix=target_prefix,
            ),
        ),
        (
            "rbac",
            rbac_validator,
        ),
        (
            "secret",
            lambda: _validate_secret_against_artifact(
                definition,
                secret_evidence,
                expected_trigger_id=expected_trigger_id,
                expected_trigger_origin=expected_trigger_origin,
                expected_canonical_hash=body_hash,
            ),
        ),
    )
    for name, validator in validators:
        try:
            result = validator()
            checks[name] = result
            for blocker in result.get("blockers", []):
                blockers.append(f"{name}: {blocker}")
        except ReadinessError as exc:
            checks[name] = {"status": "blocked", "reason": str(exc)}
            blockers.append(f"{name}: {exc}")
    return {
        "status": "component-validation-passed" if not blockers else "blocked",
        "readinessSource": "component-validation",
        "canonicalBody": body,
        "canonicalHash": body_hash,
        "checks": checks,
        "blockers": blockers,
        "mutationSupported": False,
        "liveMutationPerformed": False,
        "nextCommands": _next_commands(
            expected_trigger_id=expected_trigger_id,
            expected_trigger_origin=expected_trigger_origin,
            canonical_body_hash=body_hash,
        ),
    }


def _next_commands(
    *,
    expected_trigger_id: str,
    expected_trigger_origin: str,
    canonical_body_hash: str,
) -> list[str]:
    return [
        (
            "HUMAN GATE: create or update the HTTP trigger in Azure portal for "
            f"{AGENT_RESOURCE_ID}; set Autonomous and New chat thread for each run, "
            "then compare the rendered canonical hash before saving."
        ),
        (
            "az rest --method get --url "
            "'https://management.azure.com"
            f"{AGENT_RESOURCE_ID}?api-version=2026-01-01' --only-show-errors"
        ),
        (
            "az keyvault secret set --vault-name <vault> "
            f'--name {SECRET_NAME} --value "$SRE_TRIGGER_URL" '
            f'--tags "{SECRET_TAG_TRIGGER_ID}={expected_trigger_id}" '
            f'"{SECRET_TAG_TRIGGER_ORIGIN}={expected_trigger_origin}" '
            f'"{SECRET_TAG_CANONICAL_HASH}={canonical_body_hash}"'
        ),
        (
            "terraform -chdir=infra/terraform plan -input=false "
            "-var-file=<existing-production.tfvars> "
            "-var-file=<reviewed-sre-readiness.tfvars.json> "
            "-out=<reviewed-saved-plan>"
        ),
    ]


def build_rbac_evidence(
    *,
    visible_subscription_ids: Sequence[str],
    assignment_captures: Sequence[tuple[str, str, Sequence[object]]],
    role_definitions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build provenance-bound evidence from complete raw Azure CLI results."""
    captures = []
    for principal_id, subscription_id, rows in assignment_captures:
        raw_rows = list(rows)
        captures.append(
            {
                "principalId": principal_id,
                "subscriptionId": subscription_id,
                "includeInherited": True,
                "rawRowCount": len(raw_rows),
                "rawSha256": _json_sha256(raw_rows),
                "rawAssignments": raw_rows,
            }
        )
    role_captures = [
        {"rawSha256": _json_sha256(role), "raw": dict(role)}
        for role in role_definitions
    ]
    return {
        "subscriptionId": SUBSCRIPTION_ID,
        "tenantId": TENANT_ID,
        "visibleTenantSubscriptionIds": list(visible_subscription_ids),
        "assignmentCaptures": captures,
        "roleDefinitionCaptures": role_captures,
    }


def _collect_live_rbac_evidence(
    runner: CommandRunner,
    *,
    target_prefix: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    command_provenance: list[dict[str, Any]] = []
    account_rows = _run_fixed_json_list(
        runner,
        (
            "az",
            "account",
            "list",
            "--all",
            "--refresh",
            "--only-show-errors",
            "-o",
            "json",
        ),
        purpose="visible target-tenant subscriptions",
        provenance=command_provenance,
    )
    visible_subscriptions = []
    for index, raw in enumerate(account_rows):
        account = _mapping(raw, f"az account list row {index}")
        if str(account.get("tenantId", "")).casefold() != TENANT_ID.casefold():
            continue
        subscription_id = _subscription_id(
            account.get("id"),
            f"az account list row {index}.id",
        )
        visible_subscriptions.append(subscription_id)
    if len({item.casefold() for item in visible_subscriptions}) != len(
        visible_subscriptions
    ):
        raise ReadinessError("az account list returned duplicate subscriptions")
    if SUBSCRIPTION_ID.casefold() not in {
        item.casefold() for item in visible_subscriptions
    }:
        raise ReadinessError("selected subscription is not visible in live collection")

    assignment_captures: list[tuple[str, str, Sequence[object]]] = []
    role_definition_ids: set[str] = set()
    for subscription_id in sorted(visible_subscriptions, key=str.casefold):
        for principal_id, label in (
            (API_UAI_PRINCIPAL_ID, "API UAI"),
            (SRE_UAI_PRINCIPAL_ID, "SRE UAI"),
        ):
            descendant_rows = _run_fixed_json_list(
                runner,
                (
                    "az",
                    "role",
                    "assignment",
                    "list",
                    "--subscription",
                    subscription_id,
                    "--assignee-object-id",
                    principal_id,
                    "--all",
                    "--include-inherited",
                    "--include-groups",
                    "--only-show-errors",
                    "-o",
                    "json",
                ),
                purpose=f"{label} assignments in {subscription_id}",
                provenance=command_provenance,
            )
            inherited_rows = _run_fixed_json_list(
                runner,
                (
                    "az",
                    "role",
                    "assignment",
                    "list",
                    "--subscription",
                    subscription_id,
                    "--assignee-object-id",
                    principal_id,
                    "--scope",
                    f"/subscriptions/{subscription_id}",
                    "--include-inherited",
                    "--include-groups",
                    "--only-show-errors",
                    "-o",
                    "json",
                ),
                purpose=f"{label} parent-scope assignments in {subscription_id}",
                provenance=command_provenance,
            )
            rows = _deduplicate_raw_assignments(descendant_rows + inherited_rows)
            assignment_captures.append((principal_id, subscription_id, rows))
            for row_index, raw in enumerate(rows):
                row = _mapping(raw, f"{label} raw assignment row {row_index}")
                role_definition_ids.add(
                    _arm_id(
                        row.get("roleDefinitionId"),
                        f"{label} raw assignment roleDefinitionId",
                    )
                )

    role_definitions = []
    for role_definition_id in sorted(role_definition_ids, key=str.casefold):
        role_name = role_definition_id.rstrip("/").split("/")[-1]
        role_scope = _role_definition_query_scope(role_definition_id)
        rows = _run_fixed_json_list(
            runner,
            (
                "az",
                "role",
                "definition",
                "list",
                "--name",
                role_name,
                "--scope",
                role_scope,
                "--only-show-errors",
                "-o",
                "json",
            ),
            purpose=f"role definition {role_definition_id}",
            provenance=command_provenance,
        )
        if len(rows) != 1:
            raise ReadinessError(
                f"role definition query must return exactly one row: "
                f"{role_definition_id}"
            )
        role = _mapping(rows[0], f"role definition {role_definition_id}")
        _equal_ci(role.get("id"), role_definition_id, "role definition.id")
        role_definitions.append(role)

    rbac_evidence = build_rbac_evidence(
        visible_subscription_ids=visible_subscriptions,
        assignment_captures=assignment_captures,
        role_definitions=role_definitions,
    )
    rbac_result = _validate_rbac_contract(
        rbac_evidence,
        target_prefix=target_prefix,
    )
    rbac_result["status"] = "live-rbac-valid"
    rbac_result["blockers"] = []
    collection_summary = {
        "assignmentCaptureCount": len(assignment_captures),
        "roleDefinitionCount": len(role_definitions),
        "rawAssignmentRowCount": sum(
            len(rows) for _principal, _subscription, rows in assignment_captures
        ),
        "rawEvidenceRetainedInOutput": False,
    }
    return rbac_result, command_provenance, collection_summary


def collect_live_rbac(
    *,
    runner: CommandRunner,
    target_prefix: str,
) -> dict[str, Any]:
    """Collect and validate live RBAC without issuing a canary-ready verdict."""
    rbac_result, command_provenance, collection_summary = _collect_live_rbac_evidence(
        runner,
        target_prefix=target_prefix,
    )
    return {
        "status": "live-rbac-valid",
        "readinessSource": "live-fixed-command-collector",
        "readyForApprovedTriggerCanary": False,
        "checks": {"rbac": rbac_result},
        "blockers": ["full live readiness collector required before canary"],
        "commandProvenance": command_provenance,
        "rbacCollection": collection_summary,
    }


def collect_live_predeploy(
    *,
    runner: CommandRunner,
    http_requester: HttpRequester,
    definition: Mapping[str, Any],
    expected_trigger_id: str,
    expected_trigger_origin: str,
    expected_agent_endpoint: str,
    secret_version: str,
    target_prefix: str,
) -> dict[str, Any]:
    """Collect every pre-deploy gate in-process using fixed read-only calls."""
    provenance: list[dict[str, Any]] = []
    agent_raw = _run_fixed_json_object(
        runner,
        (
            "az",
            "rest",
            "--method",
            "get",
            "--url",
            AGENT_ARM_URL,
            "--only-show-errors",
            "-o",
            "json",
        ),
        purpose="SRE Agent resource",
        provenance=provenance,
    )
    agent_evidence = _normalize_live_agent(agent_raw)
    agent_endpoint = _https_origin(
        _mapping(agent_evidence["resource"], "agent resource")["properties"][
            "agentEndpoint"
        ],
        "live agent endpoint",
    )
    if agent_endpoint != _https_origin(
        expected_agent_endpoint,
        "expected agent endpoint",
    ):
        raise ReadinessError("live agent endpoint does not match expected endpoint")

    token = _run_fixed_text(
        runner,
        (
            "az",
            "account",
            "get-access-token",
            "--resource",
            "https://azuresre.dev",
            "--query",
            "accessToken",
            "--only-show-errors",
            "-o",
            "tsv",
        ),
        purpose="SRE data-plane token",
        provenance=provenance,
        sensitive=True,
    )
    trigger_url = f"{agent_endpoint}/api/v1/httptriggers"
    try:
        status, body, _headers = http_requester(trigger_url, token)
    except (OSError, ReadinessError, RuntimeError, ValueError):
        token = ""
        raise ReadinessError("SRE trigger read failed") from None
    token = ""
    trigger_rows = _parse_http_json_list(
        status,
        body,
        purpose="SRE trigger list",
        url=trigger_url,
        provenance=provenance,
    )
    trigger_evidence = _normalize_live_trigger(
        trigger_rows,
        expected_trigger_id=expected_trigger_id,
        expected_trigger_origin=expected_trigger_origin,
    )

    versioned_secret_id = _canonical_secret_id(definition, secret_version)
    secret_metadata = _run_fixed_json_object(
        runner,
        (
            "az",
            "keyvault",
            "secret",
            "show",
            "--id",
            versioned_secret_id,
            "--query",
            (
                "{id:id,name:name,enabled:attributes.enabled,"
                "expires:attributes.expires,tags:tags}"
            ),
            "--only-show-errors",
            "-o",
            "json",
        ),
        purpose="Key Vault trigger secret metadata",
        provenance=provenance,
    )
    secret_evidence = {
        "secretReference": {
            "keyVaultSecretId": versioned_secret_id,
            "containerAppSecretName": SECRET_NAME,
            "environmentVariable": SECRET_ENVIRONMENT_VARIABLE,
        },
        "metadata": secret_metadata,
    }
    rbac_result, rbac_provenance, collection_summary = _collect_live_rbac_evidence(
        runner, target_prefix=target_prefix
    )
    provenance.extend(rbac_provenance)
    report = _build_readiness_report(
        definition=definition,
        trigger_evidence=trigger_evidence,
        agent_evidence=agent_evidence,
        rbac_validator=lambda: rbac_result,
        secret_evidence=secret_evidence,
        expected_trigger_id=expected_trigger_id,
        expected_trigger_origin=expected_trigger_origin,
        expected_agent_endpoint=expected_agent_endpoint,
        target_prefix=target_prefix,
    )
    report["readinessSource"] = "live-fixed-command-collector"
    report["status"] = (
        "ready-for-approved-enable-plan" if not report["blockers"] else "blocked"
    )
    report["readinessStage"] = "live-predeploy"
    report["commandProvenance"] = provenance
    report["rbacCollection"] = collection_summary
    return report


def collect_live_canary(
    *,
    runner: CommandRunner,
    http_requester: HttpRequester,
    definition: Mapping[str, Any],
    expected_trigger_id: str,
    expected_trigger_origin: str,
    expected_agent_endpoint: str,
    secret_version: str,
    target_prefix: str,
) -> dict[str, Any]:
    """Collect pre-deploy plus deployed ACA gates for a canary verdict."""
    report = collect_live_predeploy(
        runner=runner,
        http_requester=http_requester,
        definition=definition,
        expected_trigger_id=expected_trigger_id,
        expected_trigger_origin=expected_trigger_origin,
        expected_agent_endpoint=expected_agent_endpoint,
        secret_version=secret_version,
        target_prefix=target_prefix,
    )
    provenance = report["commandProvenance"]
    app_state = _run_fixed_json_object(
        runner,
        (
            "az",
            "containerapp",
            "show",
            "--subscription",
            SUBSCRIPTION_ID,
            "--resource-group",
            API_CONTAINER_APP_RESOURCE_GROUP,
            "--name",
            API_CONTAINER_APP_NAME,
            "--query",
            (
                "{secrets:properties.configuration.secrets[?"
                "name=='sre-agent-http-trigger-url']"
                ".{name:name,keyVaultUrl:keyVaultUrl,identity:identity},"
                "env:properties.template.containers[0].env[?"
                "name=='AIOPS_PATCH_EXECUTION' || "
                "name=='AIOPS_SRE_AGENT_TRIGGER_URL' || "
                "name=='AIOPS_SRE_AGENT_TRIGGER_ID' || "
                "name=='AIOPS_SRE_AGENT_TRIGGER_ORIGIN' || "
                "name=='AIOPS_SRE_AGENT_ENDPOINT' || "
                "name=='AIOPS_SRE_AGENT_SUBSCRIPTION_ID' || "
                "name=='AIOPS_SRE_AGENT_TARGET_PREFIX' || "
                "name=='AIOPS_SRE_AGENT_TRIGGER_SCOPE' || "
                "name=='AIOPS_SRE_AGENT_THREAD_SCOPE']"
                ".{name:name,value:value,secretRef:secretRef}}"
            ),
            "--only-show-errors",
            "-o",
            "json",
        ),
        purpose="deployed API SRE configuration",
        provenance=provenance,
    )
    try:
        app_result = validate_container_app_state(
            app_state,
            expected_trigger_id=expected_trigger_id,
            expected_trigger_origin=expected_trigger_origin,
            expected_agent_endpoint=expected_agent_endpoint,
            secret_id=_canonical_secret_id(definition, secret_version),
            target_prefix=target_prefix,
        )
        report["checks"]["containerApp"] = app_result
    except ReadinessError as exc:
        report["checks"]["containerApp"] = {"status": "blocked", "reason": str(exc)}
        report["blockers"].append(f"containerApp: {exc}")
    report["status"] = (
        "ready-for-approved-trigger-canary" if not report["blockers"] else "blocked"
    )
    report["readinessStage"] = "live-canary"
    return report


def validate_container_app_state(
    payload: Mapping[str, Any],
    *,
    expected_trigger_id: str,
    expected_trigger_origin: str,
    expected_agent_endpoint: str,
    secret_id: str,
    target_prefix: str,
) -> dict[str, Any]:
    """Validate the deployed ACA secret reference and exact SRE environment."""
    _exact_fields(payload, {"env", "secrets"}, "Container App evidence")
    secrets = payload.get("secrets")
    if not isinstance(secrets, list) or len(secrets) != 1:
        raise ReadinessError("Container App must expose one canonical SRE secret")
    secret = _mapping(secrets[0], "Container App secret")
    if secret != {
        "name": SECRET_NAME,
        "keyVaultUrl": _key_vault_secret_id(secret_id, "configured secret ID"),
        "identity": API_UAI_RESOURCE_ID,
    }:
        raise ReadinessError("Container App Key Vault secret reference does not match")
    env_rows = payload.get("env")
    if not isinstance(env_rows, list):
        raise ReadinessError("Container App SRE environment must be a list")
    env = {}
    for index, raw in enumerate(env_rows):
        row = _mapping(raw, f"Container App env[{index}]")
        name = _nonempty_string(row.get("name"), "Container App env name")
        if name in env:
            raise ReadinessError(f"duplicate Container App environment: {name}")
        value = row.get("value")
        secret_ref = row.get("secretRef")
        if secret_ref and value == "":
            value = None
        env[name] = {"value": value, "secretRef": secret_ref}
    expected = {
        "AIOPS_PATCH_EXECUTION": {"value": "sre-agent", "secretRef": None},
        SECRET_ENVIRONMENT_VARIABLE: {"value": None, "secretRef": SECRET_NAME},
        "AIOPS_SRE_AGENT_TRIGGER_ID": {
            "value": _trigger_id(expected_trigger_id, "expected trigger ID"),
            "secretRef": None,
        },
        "AIOPS_SRE_AGENT_TRIGGER_ORIGIN": {
            "value": _https_origin(expected_trigger_origin, "expected trigger origin"),
            "secretRef": None,
        },
        "AIOPS_SRE_AGENT_ENDPOINT": {
            "value": _https_origin(expected_agent_endpoint, "expected agent endpoint"),
            "secretRef": None,
        },
        "AIOPS_SRE_AGENT_SUBSCRIPTION_ID": {
            "value": SUBSCRIPTION_ID,
            "secretRef": None,
        },
        "AIOPS_SRE_AGENT_TARGET_PREFIX": {
            "value": _target_scope(target_prefix),
            "secretRef": None,
        },
        "AIOPS_SRE_AGENT_TRIGGER_SCOPE": {
            "value": TRIGGER_SCOPE,
            "secretRef": None,
        },
        "AIOPS_SRE_AGENT_THREAD_SCOPE": {
            "value": THREAD_SCOPE,
            "secretRef": None,
        },
    }
    if env != expected:
        raise ReadinessError("deployed Container App SRE environment drifted")
    return {"status": "container-app-ready", "secretValueRead": False}


def write_informational_evidence(path: Path, evidence: Mapping[str, Any]) -> None:
    """Atomically write mode-0600 evidence that cannot authorize readiness."""
    resolved = path.resolve()
    try:
        resolved.relative_to(REPO_ROOT)
    except ValueError:
        pass
    else:
        raise ReadinessError("live informational evidence must stay outside the repo")
    wrapper = {
        "classification": "informational-live-collector-output",
        "authorizesReadinessWhenReimported": False,
        "sanitizedCollectorSummary": evidence,
    }
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
            handle.write(json.dumps(wrapper, indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _subprocess_runner(argv: Sequence[str]) -> tuple[int, bytes, bytes]:
    import subprocess

    completed = subprocess.run(
        list(argv),
        check=False,
        capture_output=True,
        shell=False,
    )
    return completed.returncode, completed.stdout, completed.stderr


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _http_requester(url: str, token: str) -> tuple[int, bytes, Mapping[str, str]]:
    request = Request(
        url,
        method="GET",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
    )
    try:
        with build_opener(_NoRedirect()).open(request, timeout=30) as response:
            return response.status, response.read(), dict(response.headers.items())
    except HTTPError as exc:
        status = exc.code
        raise ReadinessError(
            f"SRE trigger read returned HTTP {status}; redirects are forbidden"
        ) from None
    except (URLError, OSError):
        raise ReadinessError("SRE trigger read failed") from None
    finally:
        request.headers.pop("Authorization", None)


def _run_fixed_text(
    runner: CommandRunner,
    argv: Sequence[str],
    *,
    purpose: str,
    provenance: list[dict[str, Any]],
    sensitive: bool = False,
) -> str:
    _assert_read_only_az_argv(argv)
    returncode, stdout, stderr = runner(tuple(argv))
    if returncode != 0:
        raise ReadinessError(f"read-only Azure CLI command failed: {purpose}")
    if stderr:
        raise ReadinessError(f"read-only Azure CLI command wrote stderr: {purpose}")
    try:
        value = stdout.decode("utf-8", errors="strict").strip()
    except UnicodeDecodeError as exc:
        raise ReadinessError(
            f"read-only Azure CLI command returned invalid UTF-8: {purpose}"
        ) from exc
    if not value:
        raise ReadinessError(
            f"read-only Azure CLI command returned empty text: {purpose}"
        )
    provenance.append(
        {
            "purpose": purpose,
            "argv": list(argv),
            "exitCode": returncode,
            "stdoutByteCount": len(stdout),
            "stdoutSha256": hashlib.sha256(stdout).hexdigest(),
            "parsedRowCount": 1,
            "sensitiveStdoutExcluded": sensitive,
        }
    )
    return value


def _run_fixed_json_object(
    runner: CommandRunner,
    argv: Sequence[str],
    *,
    purpose: str,
    provenance: list[dict[str, Any]],
) -> dict[str, Any]:
    _assert_read_only_az_argv(argv)
    returncode, stdout, stderr = runner(tuple(argv))
    if returncode != 0:
        raise ReadinessError(f"read-only Azure CLI command failed: {purpose}")
    if stderr:
        raise ReadinessError(f"read-only Azure CLI command wrote stderr: {purpose}")
    try:
        payload = json.loads(stdout.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReadinessError(
            f"read-only Azure CLI command returned malformed JSON: {purpose}"
        ) from exc
    if not isinstance(payload, dict):
        raise ReadinessError(
            f"read-only Azure CLI command must return a JSON object: {purpose}"
        )
    provenance.append(
        {
            "purpose": purpose,
            "argv": list(argv),
            "exitCode": returncode,
            "stdoutByteCount": len(stdout),
            "stdoutSha256": hashlib.sha256(stdout).hexdigest(),
            "parsedRowCount": 1,
        }
    )
    return payload


def _parse_http_json_list(
    status: int,
    body: bytes,
    *,
    purpose: str,
    url: str,
    provenance: list[dict[str, Any]],
) -> list[object]:
    if status != 200:
        raise ReadinessError(f"{purpose} returned HTTP {status}")
    try:
        payload = json.loads(body.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReadinessError(f"{purpose} returned malformed JSON") from exc
    if not isinstance(payload, list):
        raise ReadinessError(f"{purpose} must return a JSON list")
    provenance.append(
        {
            "purpose": purpose,
            "argv": ["HTTP", "GET", url],
            "exitCode": status,
            "stdoutByteCount": len(body),
            "stdoutSha256": hashlib.sha256(body).hexdigest(),
            "parsedRowCount": len(payload),
            "authorizationExcluded": True,
            "redirectsFollowed": False,
        }
    )
    return payload


def _normalize_live_agent(raw: Mapping[str, Any]) -> dict[str, Any]:
    properties = _mapping(raw.get("properties"), "live agent properties")
    graph = _mapping(
        properties.get("knowledgeGraphConfiguration"),
        "live knowledgeGraphConfiguration",
    )
    return {
        "apiVersion": AGENT_API_VERSION,
        "resource": {
            "id": raw.get("id"),
            "name": raw.get("name"),
            "type": raw.get("type"),
            "properties": {
                "provisioningState": properties.get("provisioningState"),
                "runningState": properties.get("runningState"),
                "powerState": properties.get("powerState"),
                "agentEndpoint": properties.get("agentEndpoint"),
                "actionConfiguration": properties.get("actionConfiguration"),
                "knowledgeGraphConfiguration": {
                    "managedResources": graph.get("managedResources")
                },
            },
        },
    }


def _normalize_live_trigger(
    rows: Sequence[object],
    *,
    expected_trigger_id: str,
    expected_trigger_origin: str,
) -> dict[str, Any]:
    trigger_id = _trigger_id(expected_trigger_id, "expected trigger ID")
    matches = [
        _mapping(row, f"live trigger row {index}")
        for index, row in enumerate(rows)
        if isinstance(row, Mapping) and row.get("id") == trigger_id
    ]
    if len(matches) != 1:
        raise ReadinessError("live trigger list must contain the exact trigger once")
    raw = matches[0]
    _exact_fields(raw, RAW_LIVE_TRIGGER_FIELDS, "live trigger row")
    invocation_url = raw.get("triggerUrl")
    if not isinstance(invocation_url, str):
        raise ReadinessError("live trigger row is missing its invocation URL")
    marker = "/api/v1/httptriggers/trigger/"
    parsed = urlsplit(invocation_url)
    if marker not in parsed.path or parsed.query or parsed.fragment:
        raise ReadinessError("live trigger invocation URL is invalid")
    prefix, observed_id = parsed.path.split(marker, 1)
    observed_origin = _https_origin(
        f"{parsed.scheme}://{parsed.netloc}{prefix}".rstrip("/"),
        "live trigger origin",
    )
    if observed_id != trigger_id or "/" in observed_id:
        raise ReadinessError("live trigger invocation URL ID does not match")
    if observed_origin != _https_origin(
        expected_trigger_origin,
        "expected trigger origin",
    ):
        raise ReadinessError("live trigger invocation origin does not match")
    exact_url = f"{observed_origin}{marker}{trigger_id}"
    if invocation_url != exact_url:
        raise ReadinessError("live trigger invocation URL is not exact")
    if raw.get("agent") is not None:
        raise ReadinessError("live trigger response agent must remain the default")
    if raw.get("agentMode") != "autonomous":
        raise ReadinessError("live trigger agentMode must be autonomous")
    raw_thread_id = raw.get("threadId")
    if raw_thread_id not in ("", None):
        raise ReadinessError("live trigger threadId must be empty for NewThreadPerRun")
    trigger = {
        "id": trigger_id,
        "enabled": raw.get("triggerEnabled"),
        "prompt": raw.get("agentPrompt"),
        "runMode": "Autonomous",
        "threadGrouping": "NewThreadPerRun",
        "name": raw.get("name"),
    }
    raw_description = raw.get("description")
    if raw_description not in (None, ""):
        trigger["description"] = raw_description
    return {
        "captureVersion": "1.0",
        "sourceOrigin": observed_origin,
        "trigger": trigger,
    }


def _run_fixed_json_list(
    runner: CommandRunner,
    argv: Sequence[str],
    *,
    purpose: str,
    provenance: list[dict[str, Any]],
) -> list[object]:
    _assert_read_only_az_argv(argv)
    returncode, stdout, stderr = runner(tuple(argv))
    if returncode != 0:
        raise ReadinessError(f"read-only Azure CLI command failed: {purpose}")
    if stderr:
        raise ReadinessError(f"read-only Azure CLI command wrote stderr: {purpose}")
    try:
        decoded = stdout.decode("utf-8", errors="strict")
        payload = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReadinessError(
            f"read-only Azure CLI command returned malformed JSON: {purpose}"
        ) from exc
    if not isinstance(payload, list):
        raise ReadinessError(
            f"read-only Azure CLI command must return a JSON list: {purpose}"
        )
    provenance.append(
        {
            "purpose": purpose,
            "argv": list(argv),
            "exitCode": returncode,
            "stdoutByteCount": len(stdout),
            "stdoutSha256": hashlib.sha256(stdout).hexdigest(),
            "parsedRowCount": len(payload),
        }
    )
    return payload


def _assert_read_only_az_argv(argv: Sequence[str]) -> None:
    command = tuple(argv)
    if not command or command[0] != "az":
        raise ReadinessError("live collector permits Azure CLI only")
    allowed_prefixes = {
        ("az", "account", "list"),
        ("az", "account", "get-access-token"),
        ("az", "rest"),
        ("az", "role", "assignment", "list"),
        ("az", "role", "definition", "list"),
        ("az", "keyvault", "secret", "show"),
        ("az", "containerapp", "show"),
    }
    if not any(command[: len(prefix)] == prefix for prefix in allowed_prefixes):
        raise ReadinessError(
            "live collector permits fixed read-only Azure CLI commands"
        )
    forbidden = {
        "create",
        "delete",
        "set",
        "update",
        "write",
        "assign",
        "remove",
    }
    if any(part.casefold() in forbidden for part in command):
        raise ReadinessError("live collector command contains a write-capable verb")


def _role_definition_query_scope(role_definition_id: str) -> str:
    marker = "/providers/Microsoft.Authorization/roleDefinitions/"
    marker_index = role_definition_id.casefold().find(marker.casefold())
    if marker_index > 0:
        scope = role_definition_id[:marker_index]
        if scope.casefold().startswith("/subscriptions/"):
            parts = scope.strip("/").split("/")
            subscription_id = _subscription_id(
                parts[1],
                "role definition subscription",
            )
            return f"/subscriptions/{subscription_id}"
        if _is_management_group_scope(scope):
            return scope
    return f"/subscriptions/{SUBSCRIPTION_ID}"


def _deduplicate_raw_assignments(rows: Sequence[object]) -> list[object]:
    merged = []
    seen: set[str] = set()
    for row in rows:
        mapping = _mapping(row, "raw assignment")
        assignment_id = str(mapping.get("id") or "").casefold()
        key = assignment_id or _json_sha256(mapping)
        if key in seen:
            continue
        seen.add(key)
        merged.append(row)
    return merged


def _index_role_definition_captures(value: object) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        raise ReadinessError("roleDefinitionCaptures must be a list")
    indexed: dict[str, dict[str, Any]] = {}
    for index, captured in enumerate(value):
        capture = _mapping(captured, f"roleDefinitionCaptures[{index}]")
        _exact_fields(
            capture,
            {"raw", "rawSha256"},
            f"roleDefinitionCaptures[{index}]",
        )
        role = _mapping(capture.get("raw"), f"roleDefinitionCaptures[{index}].raw")
        if _sha256(capture.get("rawSha256"), "role-definition rawSha256") != (
            _json_sha256(role)
        ):
            raise ReadinessError("role-definition raw digest does not match")
        role_id = _arm_id(role.get("id"), f"roleDefinitionCaptures[{index}].raw.id")
        if role_id.casefold() in indexed:
            raise ReadinessError(f"duplicate role definition: {role_id}")
        permission_blocks = role.get("permissions")
        if not isinstance(permission_blocks, list) or not permission_blocks:
            raise ReadinessError("raw role definition permissions must be a list")
        flattened = {
            "actions": set(),
            "notActions": set(),
            "dataActions": set(),
            "notDataActions": set(),
        }
        for permission_index, raw_permission in enumerate(permission_blocks):
            permission = _mapping(
                raw_permission,
                f"roleDefinitionCaptures[{index}].permissions[{permission_index}]",
            )
            for field, values in flattened.items():
                values.update(
                    _permission_list(
                        permission.get(field),
                        f"raw role definition {field}",
                    )
                )
        indexed[role_id.casefold()] = {
            "id": role_id,
            "name": _nonempty_string(role.get("roleName"), "role definition roleName"),
            "assignableScopes": _string_list(
                role.get("assignableScopes"),
                "role definition assignableScopes",
            ),
            **{field: sorted(values) for field, values in flattened.items()},
        }
    return indexed


def _index_assignment_captures(
    value: object,
    visible_subscriptions: set[str],
    role_definitions: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, list[dict[str, str]]], set[str]]:
    if not isinstance(value, list):
        raise ReadinessError("assignmentCaptures must be a list")
    indexed: dict[str, list[dict[str, str]]] = {}
    seen_captures: set[tuple[str, str]] = set()
    referenced_role_ids: set[str] = set()
    for capture_index, raw in enumerate(value):
        capture = _mapping(raw, f"assignmentCaptures[{capture_index}]")
        _exact_fields(
            capture,
            {
                "includeInherited",
                "principalId",
                "rawAssignments",
                "rawRowCount",
                "rawSha256",
                "subscriptionId",
            },
            f"assignmentCaptures[{capture_index}]",
        )
        principal_id = _nonempty_string(
            capture.get("principalId"),
            "principalId",
        ).casefold()
        subscription_id = _nonempty_string(
            capture.get("subscriptionId"),
            "capture subscriptionId",
        ).casefold()
        if subscription_id not in visible_subscriptions:
            raise ReadinessError("RBAC capture references an invisible subscription")
        capture_key = (principal_id, subscription_id)
        if capture_key in seen_captures:
            raise ReadinessError("duplicate principal/subscription RBAC capture")
        if capture.get("includeInherited") is not True:
            raise ReadinessError(
                "every RBAC capture must include inherited assignments"
            )
        rows = capture.get("rawAssignments")
        if not isinstance(rows, list):
            raise ReadinessError("rawAssignments must be a complete raw list")
        raw_row_count = capture.get("rawRowCount")
        if (
            not isinstance(raw_row_count, int)
            or isinstance(raw_row_count, bool)
            or raw_row_count != len(rows)
        ):
            raise ReadinessError("raw assignment row count does not reconcile")
        if _sha256(capture.get("rawSha256"), "assignment rawSha256") != (
            _json_sha256(rows)
        ):
            raise ReadinessError("raw assignment digest does not reconcile")
        assignments = indexed.setdefault(principal_id, [])
        seen_assignments: set[tuple[str, str]] = set()
        for assignment_index, raw_assignment in enumerate(rows):
            assignment = _mapping(
                raw_assignment,
                f"rawAssignments[{principal_id}][{assignment_index}]",
            )
            assignment_principal_id = _nonempty_string(
                assignment.get("principalId"),
                "raw assignment principalId",
            )
            assignment_principal_type = assignment.get("principalType")
            if assignment_principal_type not in {"ServicePrincipal", "Group"}:
                raise ReadinessError("raw assignment principalType is ambiguous")
            if (
                assignment_principal_type == "ServicePrincipal"
                and assignment_principal_id.casefold() != principal_id
            ):
                raise ReadinessError("raw assignment principalId is misattributed")
            if assignment.get("condition") not in (None, ""):
                raise ReadinessError("conditional raw RBAC assignment is ambiguous")
            scope = _arm_id(assignment.get("scope"), "raw assignment scope")
            if not _scope_applies_to_subscription(scope, subscription_id):
                raise ReadinessError(
                    "raw assignment is outside its queried subscription inheritance"
                )
            role_id = _arm_id(
                assignment.get("roleDefinitionId"),
                "raw assignment roleDefinitionId",
            )
            normalized_role_id = role_id.casefold()
            if normalized_role_id not in role_definitions:
                raise ReadinessError(
                    f"raw assignment references unknown role definition: {role_id}"
                )
            assignment_key = (
                scope.casefold(),
                normalized_role_id,
                assignment_principal_id.casefold(),
                str(assignment_principal_type).casefold(),
            )
            if assignment_key in seen_assignments:
                raise ReadinessError("duplicate raw assignment cannot be reconciled")
            seen_assignments.add(assignment_key)
            referenced_role_ids.add(normalized_role_id)
            assignments.append(
                {
                    "roleDefinitionId": role_id,
                    "scope": scope,
                    "principalId": assignment_principal_id,
                    "principalType": str(assignment_principal_type),
                    "queryPrincipalId": principal_id,
                }
            )
        seen_captures.add(capture_key)

    expected_principals = {
        API_UAI_PRINCIPAL_ID.casefold(),
        SRE_UAI_PRINCIPAL_ID.casefold(),
    }
    for principal_id in expected_principals:
        captured_subscriptions = {
            subscription_id
            for captured_principal, subscription_id in seen_captures
            if captured_principal == principal_id
        }
        if captured_subscriptions != visible_subscriptions:
            raise ReadinessError(
                f"raw RBAC captures for {principal_id} do not cover visible subscriptions"
            )
    return indexed, referenced_role_ids


def _require_exact_role(
    definitions: Mapping[str, Mapping[str, Any]],
    name: str,
    *,
    actions: frozenset[str],
    data_actions: frozenset[str],
) -> Mapping[str, Any]:
    matches = [
        definition for definition in definitions.values() if definition["name"] == name
    ]
    if len(matches) != 1:
        raise ReadinessError(f"exact custom role is missing or duplicated: {name}")
    role = matches[0]
    if (
        set(role["actions"]) != set(actions)
        or set(role["dataActions"]) != set(data_actions)
        or role["notActions"]
        or role["notDataActions"]
        or [scope.casefold() for scope in role["assignableScopes"]]
        != [f"/subscriptions/{SUBSCRIPTION_ID}".casefold()]
    ):
        raise ReadinessError(f"custom role permissions drifted: {name}")
    return role


def _require_exact_assignment(
    assignments: Sequence[Mapping[str, str]],
    role_definition_id: str,
    scope: str,
    label: str,
) -> None:
    matches = [
        assignment
        for assignment in assignments
        if assignment["roleDefinitionId"].casefold() == role_definition_id.casefold()
        and assignment["scope"].rstrip("/").casefold() == scope.rstrip("/").casefold()
        and assignment["principalType"] == "ServicePrincipal"
        and assignment["principalId"].casefold()
        == assignment["queryPrincipalId"].casefold()
    ]
    if len(matches) != 1:
        raise ReadinessError(f"{label} must exist exactly once at the exact scope")


def _grants_any(grants: Sequence[str], required: frozenset[str]) -> bool:
    return any(
        fnmatchcase(required_action.casefold(), grant.casefold())
        for grant in grants
        for required_action in required
    )


def _target_scope(value: object) -> str:
    target = _arm_id(value, "target prefix")
    parts = target.strip("/").split("/")
    if (
        len(parts) < 4
        or parts[0].casefold() != "subscriptions"
        or parts[1].casefold() != SUBSCRIPTION_ID.casefold()
        or parts[2].casefold() != "resourcegroups"
        or not parts[3]
        or "?" in target
        or "#" in target
        or "//" in target
        or target.endswith("/")
        or any(
            not part or any(ord(character) < 32 for character in part) for part in parts
        )
        or (
            len(parts) > 4
            and (
                len(parts) < 8
                or parts[4].casefold() != "providers"
                or (len(parts) - 6) % 2 != 0
            )
        )
    ):
        raise ReadinessError(
            "target prefix must be a canonical resource-group-or-narrower scope "
            "in the selected subscription"
        )
    return target


def _scope_covers(scope: str, resource_id: str) -> bool:
    normalized_scope = scope.rstrip("/").casefold()
    normalized_resource = resource_id.rstrip("/").casefold()
    return normalized_resource == normalized_scope or normalized_resource.startswith(
        normalized_scope + "/"
    )


def _inside_subscription(scope: str, subscription_id: str) -> bool:
    prefix = f"/subscriptions/{subscription_id}".casefold()
    normalized = scope.rstrip("/").casefold()
    return normalized == prefix or normalized.startswith(prefix + "/")


def _is_management_group_scope(scope: str) -> bool:
    parts = scope.strip("/").split("/")
    return (
        len(parts) == 4
        and parts[0].casefold() == "providers"
        and parts[1].casefold() == "microsoft.management"
        and parts[2].casefold() == "managementgroups"
        and bool(parts[3])
    )


def _scope_applies_to_subscription(scope: str, subscription_id: str) -> bool:
    return _inside_subscription(scope, subscription_id) or _is_management_group_scope(
        scope
    )


def _trigger_id(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ReadinessError(f"{label} must be a non-empty string")
    trigger_id = value
    if not TRIGGER_ID_PATTERN.fullmatch(trigger_id):
        raise ReadinessError(
            f"{label} must be an exact URL-safe identifier of at most 256 characters"
        )
    return trigger_id


def _sha256(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ReadinessError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _https_origin(value: object, label: str) -> str:
    origin = _nonempty_string(value, label).rstrip("/")
    parsed = urlsplit(origin)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ReadinessError(f"{label} has an invalid port") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ReadinessError(f"{label} must be an exact public HTTPS origin")
    hostname = parsed.hostname
    if hostname.casefold() == "localhost":
        raise ReadinessError(f"{label} must use a public DNS hostname")
    try:
        ip_address(hostname.strip("[]"))
    except ValueError:
        pass
    else:
        raise ReadinessError(f"{label} must use a public DNS hostname")
    return origin


def _key_vault_secret_id(value: object, label: str) -> str:
    secret_id = _nonempty_string(value, label).rstrip("/")
    parsed = urlsplit(secret_id)
    parts = parsed.path.strip("/").split("/")
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or not parsed.hostname.casefold().endswith(".vault.azure.net")
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.query
        or parsed.fragment
        or len(parts) != 3
        or parts[0] != "secrets"
        or parts[1] != SECRET_NAME
        or not all(parts)
    ):
        raise ReadinessError(
            f"{label} must be a versioned Azure Key Vault URI for {SECRET_NAME}"
        )
    return secret_id


def _canonical_secret_contract(
    definition: Mapping[str, Any],
) -> tuple[str, str]:
    key_vault = _mapping(definition.get("keyVault"), "trigger definition keyVault")
    _exact_fields(key_vault, {"secretName", "vaultUri"}, "trigger definition keyVault")
    vault_uri = _nonempty_string(key_vault.get("vaultUri"), "keyVault.vaultUri")
    if not vault_uri.endswith("/"):
        raise ReadinessError("keyVault.vaultUri must end with one slash")
    origin = _https_origin(vault_uri.rstrip("/"), "keyVault.vaultUri")
    secret_name = _nonempty_string(
        key_vault.get("secretName"),
        "keyVault.secretName",
    )
    if secret_name != SECRET_NAME:
        raise ReadinessError(f"keyVault.secretName must be exactly {SECRET_NAME}")
    return origin + "/", secret_name


def _canonical_secret_id(
    definition: Mapping[str, Any],
    secret_version: object,
) -> str:
    version = _nonempty_string(secret_version, "secret version")
    if not SECRET_VERSION_PATTERN.fullmatch(version):
        raise ReadinessError("secret version must be an exact URL-safe version")
    vault_uri, secret_name = _canonical_secret_contract(definition)
    return f"{vault_uri}secrets/{secret_name}/{version}"


def _canonical_secret_reference(
    definition: Mapping[str, Any],
    value: object,
) -> str:
    secret_id = _key_vault_secret_id(value, "secretReference.keyVaultSecretId")
    version = urlsplit(secret_id).path.strip("/").split("/")[2]
    expected = _canonical_secret_id(definition, version)
    if secret_id != expected:
        raise ReadinessError("secret reference is outside the canonical Key Vault")
    return expected


def _reject_secret_values(value: object, label: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).casefold() in {
                "access_token",
                "accesstoken",
                "secretvalue",
                "token",
                "value",
            }:
                raise ReadinessError(f"{label} must not contain secret field {key}")
            _reject_secret_values(item, label)
    elif isinstance(value, list):
        for item in value:
            _reject_secret_values(item, label)


def _normalized_unique_ids(value: object, label: str) -> set[str]:
    values = _string_list(value, label)
    normalized = {item.casefold() for item in values}
    if len(normalized) != len(values):
        raise ReadinessError(f"{label} contains duplicates")
    return normalized


def _offline_rbac_evidence(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    if set(payload) == {"blockers", "rbacEvidence", "status"}:
        if payload.get("status") != "offline-evidence-valid":
            raise ReadinessError("offline RBAC wrapper status is invalid")
        blockers = payload.get("blockers")
        if blockers != ["fresh live collector required"]:
            raise ReadinessError("offline RBAC wrapper blocker is invalid")
        return _mapping(payload.get("rbacEvidence"), "offline rbacEvidence")
    return payload


def _load_assignment_specs(
    values: Sequence[str],
    *,
    principal_id: str,
) -> list[tuple[str, str, Sequence[object]]]:
    captures = []
    for value in values:
        if "=" not in value:
            raise ReadinessError(
                "assignment capture must use SUBSCRIPTION_ID=JSON_PATH"
            )
        subscription_id, raw_path = value.split("=", 1)
        subscription_id = subscription_id.strip()
        path = Path(raw_path)
        rows = load_json_value(path)
        if not isinstance(rows, list):
            raise ReadinessError(f"raw assignment capture {path} must be a JSON list")
        captures.append((principal_id, subscription_id, rows))
    return captures


def _load_role_definition_files(paths: Sequence[Path]) -> list[Mapping[str, Any]]:
    definitions = []
    for path in paths:
        raw = load_json_value(path)
        if not isinstance(raw, list):
            raise ReadinessError(f"raw role-definition capture {path} must be a list")
        for index, value in enumerate(raw):
            definitions.append(_mapping(value, f"raw role definition {path}[{index}]"))
    return definitions


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ReadinessError(f"{label} must be an object")
    return value


def _string_list(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise ReadinessError(f"{label} must be a list of non-empty strings")
    return value


def _permission_list(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise ReadinessError(f"{label} must be a list of strings")
    return value


def _nonempty_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReadinessError(f"{label} must be a non-empty string")
    return value.strip()


def _subscription_id(value: object, label: str) -> str:
    subscription_id = _nonempty_string(value, label)
    if not SUBSCRIPTION_ID_PATTERN.fullmatch(subscription_id):
        raise ReadinessError(f"{label} must be a subscription GUID")
    return subscription_id


def _arm_id(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ReadinessError(f"{label} must be a non-empty string")
    resource_id = value
    if (
        resource_id != resource_id.strip()
        or not resource_id.startswith("/")
        or "?" in resource_id
        or "#" in resource_id
    ):
        raise ReadinessError(f"{label} must be an ARM resource ID")
    return resource_id


def _equal_ci(value: object, expected: str, label: str) -> None:
    if not isinstance(value, str) or value.casefold() != expected.casefold():
        raise ReadinessError(f"{label} does not match the reviewed value")


def _exact_fields(
    value: Mapping[str, Any],
    expected: set[str] | frozenset[str],
    label: str,
) -> None:
    if set(value) != set(expected):
        raise ReadinessError(f"{label} fields do not match the sanitized contract")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="mode", required=True)
    render = subparsers.add_parser("render", help="render the canonical review body")
    render.add_argument("--definition", type=Path, default=DEFAULT_DEFINITION)
    build_rbac = subparsers.add_parser(
        "build-rbac",
        help="bind complete raw Azure CLI RBAC captures to provenance",
    )
    build_rbac.add_argument("--visible-subscriptions-json", type=Path, required=True)
    build_rbac.add_argument(
        "--api-inherited-assignment-json",
        action="append",
        required=True,
        metavar="SUBSCRIPTION_ID=PATH",
    )
    build_rbac.add_argument(
        "--sre-inherited-assignment-json",
        action="append",
        required=True,
        metavar="SUBSCRIPTION_ID=PATH",
    )
    build_rbac.add_argument(
        "--role-definitions-json",
        action="append",
        type=Path,
        required=True,
    )
    build_rbac.add_argument("--target-prefix", required=True)
    verify = subparsers.add_parser("verify", help="verify sanitized readiness evidence")
    verify.add_argument("--definition", type=Path, default=DEFAULT_DEFINITION)
    verify.add_argument("--trigger-json", type=Path, required=True)
    verify.add_argument("--agent-json", type=Path, required=True)
    verify.add_argument("--rbac-json", type=Path, required=True)
    verify.add_argument("--secret-json", type=Path, required=True)
    verify.add_argument("--expected-trigger-id", required=True)
    verify.add_argument("--expected-trigger-origin", required=True)
    verify.add_argument("--expected-agent-endpoint", required=True)
    verify.add_argument("--target-prefix", required=True)
    collector = subparsers.add_parser(
        "collect-live-rbac",
        help="collect and validate fixed read-only Azure RBAC commands",
    )
    collector.add_argument("--target-prefix", required=True)
    collector.add_argument("--evidence-output", type=Path)
    for mode, help_text in (
        (
            "live-predeploy",
            "collect all live pre-deploy gates for an enable-plan verdict",
        ),
        (
            "live-canary",
            "collect all live gates including deployed ACA state for canary readiness",
        ),
    ):
        live = subparsers.add_parser(mode, help=help_text)
        live.add_argument("--expected-trigger-id", required=True)
        live.add_argument("--expected-trigger-origin", required=True)
        live.add_argument("--expected-agent-endpoint", required=True)
        live.add_argument("--secret-version", required=True)
        live.add_argument("--target-prefix", required=True)
        live.add_argument("--evidence-output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the offline render or verification command and emit JSON."""
    args = _parser().parse_args(argv)
    try:
        if args.mode == "build-rbac":
            visible = load_json_value(args.visible_subscriptions_json)
            if not isinstance(visible, list):
                raise ReadinessError("visible subscription capture must be a JSON list")
            assignment_captures = _load_assignment_specs(
                args.api_inherited_assignment_json,
                principal_id=API_UAI_PRINCIPAL_ID,
            ) + _load_assignment_specs(
                args.sre_inherited_assignment_json,
                principal_id=SRE_UAI_PRINCIPAL_ID,
            )
            result = build_rbac_evidence(
                visible_subscription_ids=visible,
                assignment_captures=assignment_captures,
                role_definitions=_load_role_definition_files(
                    args.role_definitions_json
                ),
            )
            validation = validate_rbac_evidence(
                result,
                target_prefix=args.target_prefix,
            )
            output = {
                "status": validation["status"],
                "blockers": validation["blockers"],
                "rbacEvidence": result,
            }
            print(json.dumps(output, indent=2, sort_keys=True))
            return 0
        if args.mode == "collect-live-rbac":
            result = collect_live_rbac(
                runner=_subprocess_runner,
                target_prefix=args.target_prefix,
            )
            if args.evidence_output is not None:
                write_informational_evidence(
                    args.evidence_output,
                    {
                        "checks": result["checks"],
                        "commandProvenance": result["commandProvenance"],
                        "rbacCollection": result["rbacCollection"],
                    },
                )
                result["writtenInformationalEvidence"] = str(args.evidence_output)
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
        if args.mode in {"live-predeploy", "live-canary"}:
            collector = (
                collect_live_predeploy
                if args.mode == "live-predeploy"
                else collect_live_canary
            )
            result = collector(
                runner=_subprocess_runner,
                http_requester=_http_requester,
                definition=load_json(DEFAULT_DEFINITION),
                expected_trigger_id=args.expected_trigger_id,
                expected_trigger_origin=args.expected_trigger_origin,
                expected_agent_endpoint=args.expected_agent_endpoint,
                secret_version=args.secret_version,
                target_prefix=args.target_prefix,
            )
            expected_status = (
                "ready-for-approved-enable-plan"
                if args.mode == "live-predeploy"
                else "ready-for-approved-trigger-canary"
            )
            if args.evidence_output is not None:
                if result["status"] != expected_status:
                    raise ReadinessError(
                        "informational evidence is written only after live readiness passes"
                    )
                write_informational_evidence(
                    args.evidence_output,
                    {
                        "canonicalHash": result["canonicalHash"],
                        "checks": result["checks"],
                        "commandProvenance": result["commandProvenance"],
                        "rbacCollection": result["rbacCollection"],
                    },
                )
                result["writtenInformationalEvidence"] = str(args.evidence_output)
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0 if result["status"] == expected_status else 2
        definition = load_json(args.definition)
        body = canonical_trigger_body(definition)
        if args.mode == "render":
            result = {
                "status": "rendered",
                "canonicalBody": body,
                "canonicalHash": canonical_hash(body),
                "mutationSupported": False,
                "liveMutationPerformed": False,
            }
        else:
            result = build_readiness_report(
                definition=definition,
                trigger_evidence=load_json(args.trigger_json),
                agent_evidence=load_json(args.agent_json),
                rbac_evidence=_offline_rbac_evidence(load_json(args.rbac_json)),
                secret_evidence=load_json(args.secret_json),
                expected_trigger_id=args.expected_trigger_id,
                expected_trigger_origin=args.expected_trigger_origin,
                expected_agent_endpoint=args.expected_agent_endpoint,
                target_prefix=args.target_prefix,
            )
    except ReadinessError as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] != "blocked" else 2


if __name__ == "__main__":
    raise SystemExit(main())
