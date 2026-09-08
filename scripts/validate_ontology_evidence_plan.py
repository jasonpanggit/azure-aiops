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


def validate_targeted_plan(
    plan: Mapping[str, Any],
    *,
    expected_api_digest: str,
    expected_principal_id: str,
    expected_identity_id: str,
    production_workspace_id: str,
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

    missing_contract = sorted(CREATE_ADDRESSES - set(all_rows))
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
        or set(changes) - CREATE_ADDRESSES - UPDATE_ADDRESSES
    ):
        unexpected = sorted(set(changes) - CREATE_ADDRESSES - UPDATE_ADDRESSES)
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
        paths = _changed_paths(
            rows[evidence_address].get("before"),
            rows[evidence_address].get("after"),
        )
        if paths != {"template[0].container[0].image"}:
            raise EvidencePlanError(
                "evidence Job update must be image-only; "
                f"changed={sorted(paths)}"
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
