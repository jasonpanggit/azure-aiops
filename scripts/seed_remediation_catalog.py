#!/usr/bin/env .venv/bin/python3
"""Compatibility wrapper for local remediation catalog publication.

Usage:
    .venv/bin/python scripts/seed_remediation_catalog.py --target <local-lakehouse-root> [--dry-run]

Production deployment publishes the versioned catalog automatically through
``aiops-inventory fabric "Publish governed remediation catalog"``. This
wrapper remains for local development and break-glass validation only.

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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fabric.remediation_catalog import (
    DEFAULT_CATALOG_PATH,
    load_governed_catalog,
    publish_governed_catalog,
)
from storage.delta_writer import DeltaWriter
from storage.onelake_writer import OneLakeWriter


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
            "Required local lakehouse root path. Production OneLake publication "
            "uses the authenticated aiops-inventory Fabric command."
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
    if "://" in args.target:
        print(
            "error: this compatibility wrapper accepts local paths only; "
            "use the authenticated aiops-inventory Fabric command for OneLake"
        )
        return 1

    catalog_path = Path(args.catalog)
    if not catalog_path.exists():
        print(f"error: catalog file not found: {catalog_path}")
        return 1

    try:
        catalog = load_governed_catalog(catalog_path)
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
        print(f"error: governed catalog content failed validation: {exc}")
        return 1
    actions = catalog["action_catalog"]
    policies = catalog["approval_policies"]

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
    result = publish_governed_catalog(
        onelake=writer,
        delta=DeltaWriter(),
        catalog_path=catalog_path,
    )

    print(
        f"seeded {len(actions)} action(s) into silver_remediation_action_catalog "
        f"(version {result.action_table.version}) and {len(policies)} polic"
        f"{'y' if len(policies) == 1 else 'ies'} into "
        f"silver_remediation_approval_policies (version {result.policy_table.version}) "
        f"at {args.target}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
