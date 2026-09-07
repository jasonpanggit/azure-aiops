#!/usr/bin/env python3
"""Fail closed on the targeted Phase 13 evidence rollout plan."""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_ROLE_NAMES = (
    "ontology_discovery_state",
    "ontology_command",
    "ontology_dispatch",
    "ontology_publication",
    "ontology_rbac_validation",
)
CREATE_ADDRESSES = frozenset(
    {
        "azurerm_container_app_job.ontology_evidence_read[0]",
        *{
            f"fabric_workspace_role_assignment.ontology_evidence_{name}[0]"
            for name in _ROLE_NAMES
        },
        *{
            f"fabric_onelake_data_access_security.ontology_evidence_{name}[0]"
            for name in _ROLE_NAMES
        },
    }
)
UPDATE_ADDRESSES = frozenset(
    {
        "azurerm_container_app_job.ontology_discovery",
        "azurerm_container_app_job.ontology_publisher",
        "azurerm_container_app_job.ontology_rbac_validation[0]",
        "azurerm_container_app_job.ontology_fixture_prepare[0]",
        "azurerm_container_app_job.ontology_fixture_cleanup[0]",
    }
)


class EvidencePlanError(ValueError):
    """The saved plan exceeds the exact evidence rollout boundary."""


def _changed_paths(
    before: object,
    after: object,
    *,
    prefix: str = "",
) -> set[str]:
    if isinstance(before, Mapping) and isinstance(after, Mapping):
        paths: set[str] = set()
        for key in set(before) | set(after):
            path = f"{prefix}.{key}" if prefix else str(key)
            paths |= _changed_paths(before.get(key), after.get(key), prefix=path)
        return paths
    if isinstance(before, list) and isinstance(after, list):
        paths = set()
        for index in range(max(len(before), len(after))):
            left = before[index] if index < len(before) else None
            right = after[index] if index < len(after) else None
            paths |= _changed_paths(left, right, prefix=f"{prefix}[{index}]")
        return paths
    return set() if before == after else {prefix}


def _single(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, list) or len(value) != 1:
        raise EvidencePlanError(f"{label} must contain exactly one object")
    row = value[0]
    if not isinstance(row, Mapping):
        raise EvidencePlanError(f"{label} must contain an object")
    return row


def _validate_evidence_job(
    values: Mapping[str, Any],
    *,
    expected_api_digest: str,
    expected_identity_id: str,
) -> None:
    if values.get("name") != "ontology-evidence-read":
        raise EvidencePlanError("evidence Job name is not fixed")
    identity = _single(values.get("identity"), "evidence Job identity")
    if (
        identity.get("type") != "UserAssigned"
        or identity.get("identity_ids") != [expected_identity_id]
    ):
        raise EvidencePlanError("evidence Job must use only the Azure MCP identity")
    manual = _single(
        values.get("manual_trigger_config"),
        "evidence Job manual trigger",
    )
    if (
        manual.get("parallelism") != 1
        or manual.get("replica_completion_count") != 1
        or values.get("schedule_trigger_config") not in (None, [])
        or values.get("event_trigger_config") not in (None, [])
        or values.get("replica_retry_limit") != 0
    ):
        raise EvidencePlanError("evidence Job must be fixed and manual-only")
    template = _single(values.get("template"), "evidence Job template")
    container = _single(template.get("container"), "evidence Job container")
    if (
        container.get("command")
        != ["python", "/app/scripts/collect_ontology_evidence.py"]
        or container.get("args") != ["--emit-console-record"]
        or not str(container.get("image") or "").endswith(
            "@" + expected_api_digest
        )
    ):
        raise EvidencePlanError("evidence Job command or image is not fixed")
    env_names = {
        str(row.get("name") or "")
        for row in container.get("env") or ()
        if isinstance(row, Mapping)
    }
    if (
        "AZURE_CLIENT_ID" not in env_names
        or "AIOPS_ONTOLOGY_API_TOKEN" in env_names
        or any(
            "PUBLISHER" in name or "COORDINATOR" in name
            for name in env_names
        )
    ):
        raise EvidencePlanError("evidence Job environment widens authority")


def _validate_evidence_roles(
    rows: Mapping[str, Mapping[str, Any]],
    *,
    expected_principal_id: str,
    production_workspace_id: str,
) -> None:
    workspace_ids: set[str] = set()
    data_workspace_ids: set[str] = set()
    for name in _ROLE_NAMES:
        workspace_address = (
            "fabric_workspace_role_assignment."
            f"ontology_evidence_{name}[0]"
        )
        workspace = rows[workspace_address].get("after")
        workspace = workspace if isinstance(workspace, Mapping) else {}
        principal = workspace.get("principal")
        principal = principal if isinstance(principal, Mapping) else {}
        workspace_id = str(workspace.get("workspace_id") or "")
        if (
            workspace.get("role") != "Viewer"
            or not workspace_id
            or workspace_id == production_workspace_id
            or principal
            != {
                "id": expected_principal_id,
                "type": "ServicePrincipal",
            }
        ):
            raise EvidencePlanError(
                f"{workspace_address} is not exact read-only metadata access"
            )
        workspace_ids.add(workspace_id)

        data_address = (
            "fabric_onelake_data_access_security."
            f"ontology_evidence_{name}[0]"
        )
        data_role = rows[data_address].get("after")
        data_role = data_role if isinstance(data_role, Mapping) else {}
        data_workspace_id = str(data_role.get("workspace_id") or "")
        if (
            not data_workspace_id
            or data_workspace_id == production_workspace_id
            or not data_role.get("item_id")
            or data_role.get("role_name") != "Phase13EvidenceRead"
        ):
            raise EvidencePlanError(
                f"{data_address} targets a forbidden workspace or item"
            )
        rules = data_role.get("decision_rules")
        rules = rules if isinstance(rules, list) else []
        if len(rules) != 1 or not isinstance(rules[0], Mapping):
            raise EvidencePlanError(f"{data_address} must have one permit rule")
        permissions = rules[0].get("permission")
        permissions = permissions if isinstance(permissions, list) else []
        normalized_permissions = {
            (
                str(permission.get("attribute_name") or ""),
                tuple(permission.get("attribute_value_included_in") or ()),
            )
            for permission in permissions
            if isinstance(permission, Mapping)
        }
        members = data_role.get("members")
        members = members if isinstance(members, Mapping) else {}
        entra = members.get("microsoft_entra_members")
        entra = entra if isinstance(entra, list) else []
        if (
            rules[0].get("effect") != "Permit"
            or normalized_permissions != {("Path", ("*",)), ("Action", ("Read",))}
            or members.get("fabric_item_members") not in (None, [])
            or entra
            != [
                {
                    "object_id": expected_principal_id,
                    "object_type": "ManagedIdentity",
                    "tenant_id": entra[0].get("tenant_id") if entra else None,
                }
            ]
            or not entra[0].get("tenant_id")
        ):
            raise EvidencePlanError(
                f"{data_address} is not exact OneLake Path wildcard Read"
            )
        data_workspace_ids.add(data_workspace_id)

    if len(workspace_ids) != 5 or workspace_ids != data_workspace_ids:
        raise EvidencePlanError("evidence roles must target five exact workspaces")


def validate_targeted_plan(
    plan: Mapping[str, Any],
    *,
    expected_api_digest: str,
    expected_principal_id: str,
    expected_identity_id: str,
    production_workspace_id: str,
) -> dict[str, object]:
    """Require 11 creates plus image-only updates to five existing Jobs."""

    if not _DIGEST.fullmatch(expected_api_digest):
        raise EvidencePlanError("expected API digest is invalid")
    changes: dict[str, tuple[str, ...]] = {}
    rows: dict[str, Mapping[str, Any]] = {}
    for row in plan.get("resource_changes") or ():
        if not isinstance(row, Mapping):
            continue
        address = str(row.get("address") or "")
        change = row.get("change")
        change = change if isinstance(change, Mapping) else {}
        actions = tuple(str(value) for value in change.get("actions") or ())
        if actions and actions != ("no-op",):
            changes[address] = actions
            rows[address] = change

    if set(changes) != CREATE_ADDRESSES | UPDATE_ADDRESSES:
        unexpected = sorted(set(changes) - CREATE_ADDRESSES - UPDATE_ADDRESSES)
        missing = sorted(CREATE_ADDRESSES | UPDATE_ADDRESSES - set(changes))
        raise EvidencePlanError(
            "targeted plan must contain the exact evidence rollout "
            f"(unexpected={unexpected}, missing={missing})"
        )
    for address in CREATE_ADDRESSES:
        if changes[address] != ("create",):
            raise EvidencePlanError(f"{address} must be create-only")
    _validate_evidence_job(
        rows["azurerm_container_app_job.ontology_evidence_read[0]"].get(
            "after", {}
        ),
        expected_api_digest=expected_api_digest,
        expected_identity_id=expected_identity_id,
    )
    _validate_evidence_roles(
        rows,
        expected_principal_id=expected_principal_id,
        production_workspace_id=production_workspace_id,
    )
    for address in UPDATE_ADDRESSES:
        if changes[address] != ("update",):
            raise EvidencePlanError(f"{address} must be an in-place update")
        change = rows[address]
        paths = _changed_paths(change.get("before"), change.get("after"))
        if paths != {"template[0].container[0].image"}:
            raise EvidencePlanError(
                f"{address} update must be image-only; changed={sorted(paths)}"
            )
        after = change.get("after")
        try:
            image = after["template"][0]["container"][0]["image"]
        except (KeyError, IndexError, TypeError) as exc:
            raise EvidencePlanError(f"{address} image is missing") from exc
        if not str(image).endswith("@" + expected_api_digest):
            raise EvidencePlanError(f"{address} image digest is not exact")

    return {
        "status": "PASS",
        "sanitized": True,
        "create_addresses": sorted(CREATE_ADDRESSES),
        "update_addresses": sorted(UPDATE_ADDRESSES),
        "delete_count": 0,
        "replace_count": 0,
        "api_digest": expected_api_digest,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan-json", type=Path, required=True)
    parser.add_argument("--api-digest", required=True)
    parser.add_argument("--evidence-principal-id", required=True)
    parser.add_argument("--evidence-identity-id", required=True)
    parser.add_argument("--production-workspace-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    payload = json.loads(args.plan_json.read_text(encoding="utf-8"))
    result = validate_targeted_plan(
        payload,
        expected_api_digest=args.api_digest,
        expected_principal_id=args.evidence_principal_id,
        expected_identity_id=args.evidence_identity_id,
        production_workspace_id=args.production_workspace_id,
    )
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
