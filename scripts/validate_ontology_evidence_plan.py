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
_EVIDENCE_ENV_NAMES = frozenset(
    {
        "AZURE_CLIENT_ID",
        "AIOPS_EVIDENCE_OBJECT_ID",
        "AIOPS_EVIDENCE_SUBSCRIPTION_ID",
        "AIOPS_EVIDENCE_RESOURCE_GROUP",
        "AIOPS_EVIDENCE_API_URL",
        "AIOPS_EVIDENCE_API_SCOPE",
        *{
            f"AIOPS_EVIDENCE_{name}_WORKSPACE_ID"
            for name in (
                "STATE",
                "COMMAND",
                "DISPATCH",
                "PUBLICATION",
                "VALIDATION",
            )
        },
        *{
            f"AIOPS_EVIDENCE_{name}_LAKEHOUSE_ID"
            for name in (
                "STATE",
                "COMMAND",
                "DISPATCH",
                "PUBLICATION",
                "VALIDATION",
            )
        },
    }
)
CREATE_ADDRESSES = frozenset(
    {
        "azurerm_container_app_job.ontology_evidence_read[0]",
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
    env_rows = [
        row for row in container.get("env") or () if isinstance(row, Mapping)
    ]
    env_names = {str(row.get("name") or "") for row in env_rows}
    if (
        env_names != _EVIDENCE_ENV_NAMES
        or len(env_rows) != len(_EVIDENCE_ENV_NAMES)
        or any(not str(row.get("value") or "").strip() for row in env_rows)
        or any(
            row.get("secret_name") or row.get("secretRef") for row in env_rows
        )
    ):
        raise EvidencePlanError(
            "evidence Job environment is not the exact secret-free read contract"
        )


def _validate_evidence_job_update(change: Mapping[str, object]) -> None:
    before = json.loads(json.dumps(change.get("before")))
    after = json.loads(json.dumps(change.get("after")))
    try:
        before_container = before["template"][0]["container"][0]
        after_container = after["template"][0]["container"][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise EvidencePlanError("evidence Job update shape is invalid") from exc
    before_env = {
        row.get("name"): row
        for row in before_container.get("env") or ()
        if isinstance(row, Mapping)
    }
    after_env = {
        row.get("name"): row
        for row in after_container.get("env") or ()
        if isinstance(row, Mapping)
    }
    removed = set(before_env) - set(after_env)
    added = set(after_env) - set(before_env)
    allowed_boundary = frozenset(
        {
            "AIOPS_EVIDENCE_API_URL",
            "AIOPS_EVIDENCE_API_SCOPE",
        }
    )
    if (
        frozenset(removed) not in {frozenset(), allowed_boundary}
        or frozenset(added) not in {frozenset(), allowed_boundary}
        or (removed and added)
        or any(
            before_env[name] != after_env[name]
            for name in set(before_env) & set(after_env)
        )
    ):
        raise EvidencePlanError(
            "evidence Job update may only change the API denial boundary"
        )
    before_container["env"] = []
    after_container["env"] = []
    before_container["image"] = ""
    after_container["image"] = ""
    if before != after:
        raise EvidencePlanError(
            "evidence Job update may change only image and API denial env"
        )


def _validate_fixture_job_update(change: Mapping[str, object]) -> None:
    before = json.loads(json.dumps(change.get("before")))
    after = json.loads(json.dumps(change.get("after")))
    try:
        before_container = before["template"][0]["container"][0]
        after_container = after["template"][0]["container"][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise EvidencePlanError("fixture Job update shape is invalid") from exc
    before_env = {
        row.get("name"): row
        for row in before_container.get("env") or ()
        if isinstance(row, Mapping)
    }
    after_env = {
        row.get("name"): row
        for row in after_container.get("env") or ()
        if isinstance(row, Mapping)
    }
    added = set(after_env) - set(before_env)
    if frozenset(added) not in {
        frozenset(),
        frozenset(
            {
                "AIOPS_ONTOLOGY_FIXTURE_TENANT_ID",
                "AIOPS_ONTOLOGY_FIXTURE_SUBSCRIPTION_ID",
            }
        ),
    } or any(before_env[name] != after_env[name] for name in before_env):
        raise EvidencePlanError(
            "fixture Job update may only add fixed validation scope"
        )
    if any(not str(after_env[name].get("value") or "").strip() for name in added):
        raise EvidencePlanError("fixture validation scope must be explicit")
    before_container["env"] = []
    after_container["env"] = []
    before_container["image"] = ""
    after_container["image"] = ""
    if before != after:
        raise EvidencePlanError(
            "fixture Job update may change only image and validation scope"
        )


def _validate_validation_manual_transition(
    change: Mapping[str, object],
    *,
    address: str,
) -> None:
    before = json.loads(json.dumps(change.get("before")))
    after = json.loads(json.dumps(change.get("after")))
    try:
        before_container = before["template"][0]["container"][0]
        after_container = after["template"][0]["container"][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise EvidencePlanError(
            f"{address} validation trigger shape is invalid"
        ) from exc
    schedule = before.get("schedule_trigger_config")
    manual = after.get("manual_trigger_config")
    if (
        not isinstance(schedule, list)
        or len(schedule) != 1
        or after.get("schedule_trigger_config") not in (None, [])
        or before.get("manual_trigger_config") not in (None, [])
        or not isinstance(manual, list)
        or manual
        != [{"parallelism": 1, "replica_completion_count": 1}]
    ):
        raise EvidencePlanError(
            f"{address} must transition from schedule to fixed manual trigger"
        )
    before["schedule_trigger_config"] = []
    after["manual_trigger_config"] = []
    before_container["image"] = ""
    after_container["image"] = ""
    if before != after:
        raise EvidencePlanError(
            f"{address} may change only image and validation trigger"
        )


def _coordinator_role_addresses(subscription_id: str) -> dict[str, str]:
    return {
        (
            "azurerm_role_assignment."
            f'ontology_coordinator_validation_reader["{subscription_id}"]'
        ): "Reader",
        (
            "azurerm_role_assignment."
            "ontology_coordinator_validation_monitoring_reader"
            f'["{subscription_id}"]'
        ): "Monitoring Reader",
        (
            "azurerm_role_assignment."
            "ontology_coordinator_key_vault_secrets"
        ): "Key Vault Secrets User",
    }


def _validate_coordinator_roles(
    rows: Mapping[str, Mapping[str, Any]],
    *,
    expected_principal_id: str,
    expected_subscription_id: str,
    expected_key_vault_id: str,
) -> dict[str, str]:
    expected = _coordinator_role_addresses(expected_subscription_id)
    for address, role_name in expected.items():
        change = rows.get(address)
        if not isinstance(change, Mapping):
            raise EvidencePlanError(
                f"missing coordinator role contract {address}"
            )
        actions = tuple(str(value) for value in change.get("actions") or ())
        if actions not in {("create",), ("no-op",)}:
            raise EvidencePlanError(
                f"{address} must be create-only or already converged"
            )
        values = change.get("after")
        values = values if isinstance(values, Mapping) else {}
        expected_scope = (
            expected_key_vault_id
            if role_name == "Key Vault Secrets User"
            else f"/subscriptions/{expected_subscription_id}"
        )
        if (
            values.get("principal_id") != expected_principal_id
            or values.get("role_definition_name") != role_name
            or str(values.get("scope") or "").casefold()
            != expected_scope.casefold()
        ):
            raise EvidencePlanError(
                f"{address} exceeds the coordinator read-only boundary"
            )
    return expected


def validate_targeted_plan(
    plan: Mapping[str, Any],
    *,
    expected_api_digest: str,
    expected_principal_id: str,
    expected_identity_id: str,
    production_workspace_id: str,
    expected_coordinator_principal_id: str,
    expected_subscription_id: str,
    expected_key_vault_id: str,
) -> dict[str, object]:
    """Require six creates plus image-only updates to five existing Jobs."""

    if not _DIGEST.fullmatch(expected_api_digest):
        raise EvidencePlanError("expected API digest is invalid")
    changes: dict[str, tuple[str, ...]] = {}
    rows: dict[str, Mapping[str, Any]] = {}
    all_rows: dict[str, Mapping[str, Any]] = {}
    for row in plan.get("resource_changes") or ():
        if not isinstance(row, Mapping):
            continue
        address = str(row.get("address") or "")
        change = row.get("change")
        change = change if isinstance(change, Mapping) else {}
        actions = tuple(str(value) for value in change.get("actions") or ())
        all_rows[address] = change
        if actions and actions != ("no-op",):
            changes[address] = actions
            rows[address] = change
    coordinator_roles = _validate_coordinator_roles(
        all_rows,
        expected_principal_id=expected_coordinator_principal_id,
        expected_subscription_id=expected_subscription_id,
        expected_key_vault_id=expected_key_vault_id,
    )
    allowed_addresses = CREATE_ADDRESSES | UPDATE_ADDRESSES | set(
        coordinator_roles
    )

    missing_contract = sorted(
        (CREATE_ADDRESSES | set(coordinator_roles)) - set(all_rows)
    )
    invalid_contract = sorted(
        address
        for address in CREATE_ADDRESSES
        if tuple(all_rows.get(address, {}).get("actions") or ())
        not in {("create",), ("update",), ("no-op",)}
    )
    required_changes = {
        "azurerm_container_app_job.ontology_evidence_read[0]",
        *UPDATE_ADDRESSES,
    }
    if (
        missing_contract
        or invalid_contract
        or not required_changes.issubset(changes)
        or set(changes) - allowed_addresses
    ):
        unexpected = sorted(set(changes) - allowed_addresses)
        missing = sorted(required_changes - set(changes))
        raise EvidencePlanError(
            "targeted plan must contain the exact evidence rollout "
            f"(unexpected={unexpected}, missing={missing}, "
            f"contract_missing={missing_contract}, invalid={invalid_contract})"
        )
    evidence_address = "azurerm_container_app_job.ontology_evidence_read[0]"
    evidence_actions = changes[evidence_address]
    if evidence_actions not in {("create",), ("update",)}:
        raise EvidencePlanError(
            "evidence Job must be created or updated in place"
        )
    _validate_evidence_job(
        rows[evidence_address].get("after", {}),
        expected_api_digest=expected_api_digest,
        expected_identity_id=expected_identity_id,
    )
    if evidence_actions == ("update",):
        _validate_evidence_job_update(rows[evidence_address])
    for address in UPDATE_ADDRESSES:
        if changes[address] != ("update",):
            raise EvidencePlanError(f"{address} must be an in-place update")
        change = rows[address]
        if address in {
            "azurerm_container_app_job.ontology_fixture_prepare[0]",
            "azurerm_container_app_job.ontology_fixture_cleanup[0]",
        }:
            _validate_fixture_job_update(change)
        elif address in {
            "azurerm_container_app_job.ontology_discovery",
            "azurerm_container_app_job.ontology_publisher",
        }:
            paths = _changed_paths(change.get("before"), change.get("after"))
            if paths == {"template[0].container[0].image"}:
                pass
            else:
                _validate_validation_manual_transition(
                    change,
                    address=address,
                )
        else:
            paths = _changed_paths(change.get("before"), change.get("after"))
            if paths != {"template[0].container[0].image"}:
                raise EvidencePlanError(
                    f"{address} update must be image-only; "
                    f"changed={sorted(paths)}"
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
        "create_addresses": sorted(
            address
            for address, actions in changes.items()
            if actions == ("create",)
        ),
        "update_addresses": sorted(
            [
                *UPDATE_ADDRESSES,
                *(
                    [evidence_address]
                    if evidence_actions == ("update",)
                    else []
                ),
            ]
        ),
        "delete_count": 0,
        "replace_count": 0,
        "api_digest": expected_api_digest,
        "external_role_contract": (
            "Workspace=Viewer;ManagedIdentity:Path=*:Action=Read"
        ),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan-json", type=Path, required=True)
    parser.add_argument("--api-digest", required=True)
    parser.add_argument("--evidence-principal-id", required=True)
    parser.add_argument("--evidence-identity-id", required=True)
    parser.add_argument("--production-workspace-id", required=True)
    parser.add_argument("--coordinator-principal-id", required=True)
    parser.add_argument("--subscription-id", required=True)
    parser.add_argument("--key-vault-id", required=True)
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
        expected_coordinator_principal_id=args.coordinator_principal_id,
        expected_subscription_id=args.subscription_id,
        expected_key_vault_id=args.key_vault_id,
    )
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
