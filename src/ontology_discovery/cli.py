"""Finite command-line entry point for the durable discovery coordinator."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import uuid
from datetime import datetime
from pathlib import Path

from .coordinator import OntologyDiscoveryCoordinator
from .runtime import build_production_runtime


async def run_once(
    coordinator: OntologyDiscoveryCoordinator,
    *,
    now: datetime | None = None,
    limit: int = 10,
) -> dict[str, int]:
    """Execute exactly one bounded coordinator pass."""
    return await coordinator.run_once(now=now, limit=limit)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one bounded ontology discovery coordinator pass"
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=("run-once", "schema-proposal-import", "schema-proposal-review"),
        default="run-once",
        help="Execute exactly one finite coordinator pass",
    )
    parser.add_argument(
        "--limit",
        type=int,
        choices=(1,),
        default=1,
        help="Production safety bound; exactly one connection per pass",
    )
    parser.add_argument("--owner")
    schema = parser.add_argument_group("schema proposals (advisory, local only)")
    schema.add_argument("--store-root", help="Local schema proposal store directory")
    schema.add_argument("--envelope", help="Schema proposal envelope JSON file")
    schema.add_argument("--base-definition", help="Captured base definition JSON file")
    schema.add_argument("--evidence", help="JSON list of trusted evidence refs")
    schema.add_argument("--scope")
    schema.add_argument("--workspace-id")
    schema.add_argument("--item-id")
    schema.add_argument("--format", dest="definition_format")
    schema.add_argument("--proposal-id")
    schema.add_argument("--decision", choices=("approve", "reject"))
    schema.add_argument("--reviewer")
    schema.add_argument("--expected-revision", type=int)
    return parser


def _schema_store(args: argparse.Namespace):
    from .schema_proposal_store import SchemaProposalStore

    if not args.store_root or "://" in args.store_root:
        raise SystemExit("schema proposals require a local --store-root")
    stewards = {
        v.strip()
        for v in os.environ.get("AIOPS_SCHEMA_STEWARDS", "").split(",")
        if v.strip()
    }
    return SchemaProposalStore(args.store_root, is_steward=lambda actor: actor in stewards)


def _load_json(path: str | None, label: str):
    if not path:
        raise SystemExit(f"--{label} is required")
    return json.loads(Path(path).read_text(encoding="utf-8"))


def run_schema_import(args: argparse.Namespace) -> dict:
    """Advisory import: strict envelope + trusted base/target/evidence binding."""

    from ontology.definition_compatibility import (
        classify_definition,
        definition_fingerprint,
        stable_ids,
    )

    from .schema_proposals import parse_envelope, validate_against_trusted

    base = _load_json(args.base_definition, "base-definition")
    envelope = parse_envelope(Path(args.envelope or "").read_bytes())
    detected = classify_definition(base)
    if detected != args.definition_format:
        raise SystemExit(f"captured base format {detected} != {args.definition_format}")
    ids = stable_ids(base)
    validate_against_trusted(
        envelope,
        scope=args.scope or "",
        workspace_id=args.workspace_id or "",
        item_id=args.item_id or "",
        format=args.definition_format or "",
        base_fingerprint=definition_fingerprint(base),
        known_evidence_refs=_load_json(args.evidence, "evidence"),
        base_stable_ids=ids or None,
    )
    proposal_id = _schema_store(args).import_proposal(envelope)
    return {"proposal_id": proposal_id, "status": "imported", "advisory_only": True}


def run_schema_review(args: argparse.Namespace) -> dict:
    from ontology.definition_compatibility import definition_fingerprint

    base = _load_json(args.base_definition, "base-definition")
    event = _schema_store(args).review(
        args.proposal_id or "",
        reviewer=args.reviewer or "",
        decision=args.decision or "",
        expected_revision=args.expected_revision if args.expected_revision is not None else -1,
        current_base_fingerprint=definition_fingerprint(base),
    )
    return {"proposal_id": event["proposal_id"], "decision": event["decision"],
            "sequence": event["sequence"]}


def _process_owner() -> str:
    """Return a lease owner unique to this coordinator process invocation."""

    return f"{socket.gethostname()}:{uuid.uuid4().hex}"


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "schema-proposal-import":
        print(json.dumps(run_schema_import(args), sort_keys=True))
        return 0
    if args.command == "schema-proposal-review":
        print(json.dumps(run_schema_review(args), sort_keys=True))
        return 0
    owner = args.owner if args.owner is not None else _process_owner()

    async def execute() -> dict[str, int | bool]:
        runtime = build_production_runtime(owner=owner)
        try:
            return await runtime.run_once(limit=args.limit)
        finally:
            await runtime.aclose()

    result = asyncio.run(execute())
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
