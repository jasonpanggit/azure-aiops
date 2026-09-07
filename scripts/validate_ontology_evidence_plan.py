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


def validate_targeted_plan(
    plan: Mapping[str, Any],
    *,
    expected_api_digest: str,
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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    payload = json.loads(args.plan_json.read_text(encoding="utf-8"))
    result = validate_targeted_plan(payload, expected_api_digest=args.api_digest)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
