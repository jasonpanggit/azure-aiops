#!/usr/bin/env .venv/bin/python3
"""Seed the governed remediation action catalog and approval policies.

Usage:
    .venv/bin/python scripts/seed_remediation_catalog.py --target <lakehouse-root-or-table-uri> [--dry-run]

Reads the governed catalog content from
`tests/fixtures/governed_remediation_catalog.json` (override with
`--catalog`), validates it through the real
`RemediationOpportunityEngine` and `ApprovalEngine` shapes, and writes
`silver_remediation_action_catalog` and
`silver_remediation_approval_policies` through `DeltaWriter` in
overwrite mode keyed on the action/policy identifiers, so repeated
runs converge rather than accumulate.

Seeding a catalog action grants it no execution authority: this
script only writes governed, human-reviewed, declarative content that
later phases may read. Nothing in this repository executes any action
described here.

Requires an explicit `--target` and refuses to run without one, so it
can never write to a default production location by accident.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from intelligence.remediation.approval_engine import ApprovalEngine
from intelligence.remediation.remediation_opportunity_engine import (
    RemediationOpportunityEngine,
)
from storage.delta_writer import DeltaWriteMode, DeltaWriter
from storage.onelake_writer import OneLakeWriter

DEFAULT_CATALOG_PATH = Path("tests/fixtures/governed_remediation_catalog.json")

_ACTION_JSON_FIELDS = (
    "trigger",
    "execution_steps",
    "preconditions",
    "rollback_actions",
    "success_criteria",
    "failure_criteria",
    "deployment_stages",
    "effectiveness",
)


def _load_catalog(path: Path) -> dict:
    return json.loads(path.read_text())


def _validate(catalog: dict) -> None:
    """Validate content through the real engines; raises on invalid content."""
    RemediationOpportunityEngine(catalog.get("action_catalog") or [])
    ApprovalEngine(catalog.get("approval_policies") or [])


def _base_columns(run_id: str, now: str) -> dict:
    return {
        "tenant_id": "governed-catalog",
        "subscription_id": "governed-catalog",
        "resource_id": "governed-catalog",
        "timestamp": now,
        "change_version": run_id,
        "ingestion_run_id": run_id,
    }


def _action_rows(actions: list[dict], base: dict) -> list[dict]:
    rows = []
    for action in actions:
        row = {
            **base,
            "resource_id": str(action["action_id"]),
            "action_id": str(action["action_id"]),
            "title": str(action["title"]),
            "opportunity_type": str(action["opportunity_type"]),
        }
        for field in _ACTION_JSON_FIELDS:
            row[f"{field}_json"] = json.dumps(action[field])
        rows.append(row)
    return rows


def _policy_rows(policies: list[dict], base: dict) -> list[dict]:
    rows = []
    for policy in policies:
        rows.append(
            {
                **base,
                "resource_id": str(policy["policy_id"]),
                "policy_id": str(policy["policy_id"]),
                "conditions_json": json.dumps(policy["conditions"]),
                "roles_json": json.dumps(policy["roles"]),
                # Optional (Phase 03.5 CR-05 fix): a policy may declare an
                # explicit stable id per role; absent entirely (the common
                # case), ApprovalEngine derives a deterministic distinct
                # id per role on its own -- this column is never fabricated
                # by a UI layer, only ever sourced from governed policy
                # data or computed deterministically from it.
                "role_ids_json": json.dumps(policy.get("role_ids") or {}),
            }
        )
    return rows


def _resolve_writer(target: str) -> OneLakeWriter:
    return OneLakeWriter(
        workspace_id="local",
        lakehouse_id="local",
        local_root=Path(target),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        default="",
        help=(
            "Required. Local lakehouse root path or Fabric OneLake table URI "
            "root to seed into. There is no default target."
        ),
    )
    parser.add_argument(
        "--catalog",
        default=str(DEFAULT_CATALOG_PATH),
        help="Path to the governed catalog JSON file to seed.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be written without writing anything.",
    )
    args = parser.parse_args(argv)

    if not args.target:
        print("error: --target is required; refusing to guess a default location")
        return 1

    catalog_path = Path(args.catalog)
    if not catalog_path.exists():
        print(f"error: catalog file not found: {catalog_path}")
        return 1

    catalog = _load_catalog(catalog_path)
    actions = catalog.get("action_catalog") or []
    policies = catalog.get("approval_policies") or []

    try:
        _validate(catalog)
    except (ValueError, TypeError) as exc:
        print(f"error: governed catalog content failed validation: {exc}")
        return 1

    if args.dry_run:
        print(
            f"dry run: would write {len(actions)} action(s) to "
            "silver_remediation_action_catalog and "
            f"{len(policies)} polic{'y' if len(policies) == 1 else 'ies'} to "
            "silver_remediation_approval_policies at "
            f"{args.target}"
        )
        return 0

    writer = _resolve_writer(args.target)
    delta = DeltaWriter()
    run_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    base = _base_columns(run_id, now)

    action_result = delta.write(
        writer.table_uri("silver", "remediation_action_catalog"),
        _action_rows(actions, base),
        mode=DeltaWriteMode.OVERWRITE,
        key_columns=("action_id",),
    )
    policy_result = delta.write(
        writer.table_uri("silver", "remediation_approval_policies"),
        _policy_rows(policies, base),
        mode=DeltaWriteMode.OVERWRITE,
        key_columns=("policy_id",),
    )

    print(
        f"seeded {len(actions)} action(s) into silver_remediation_action_catalog "
        f"(version {action_result.version}) and {len(policies)} polic"
        f"{'y' if len(policies) == 1 else 'ies'} into "
        f"silver_remediation_approval_policies (version {policy_result.version}) "
        f"at {args.target}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
