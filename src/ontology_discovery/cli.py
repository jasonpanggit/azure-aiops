"""Finite command-line entry point for the durable discovery coordinator."""

from __future__ import annotations

import argparse
import asyncio
import json
import socket
from datetime import datetime
from pathlib import Path
from typing import Any

from .contracts import CheckpointResult
from .coordinator import OntologyDiscoveryCoordinator
from .store import OntologyRunStore


class _RecordOnlyProcessor:
    """Close the foundation run without invoking any publication capability.

    Later Phase 13 plans replace this composition with the evidence and
    proposal pipeline. Keeping this processor explicit makes the initial CLI
    useful for proving durable dispatch while remaining non-authoritative.
    """

    async def advance(self, run: dict[str, Any]) -> CheckpointResult:
        return CheckpointResult(
            checkpoint="intake_recorded",
            payload={"source_generation_id": run["source_generation_id"]},
            complete=True,
        )


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
        "--store",
        default=".aiops-local/state/ontology_discovery_runs.json",
        help="Path to the durable ontology discovery run ledger",
    )
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--owner", default=socket.gethostname())
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    store = OntologyRunStore(Path(args.store).expanduser())
    coordinator = OntologyDiscoveryCoordinator(
        store=store,
        processor=_RecordOnlyProcessor(),
        owner=args.owner,
    )
    result = asyncio.run(run_once(coordinator, limit=args.limit))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
