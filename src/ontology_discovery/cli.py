"""Finite command-line entry point for the durable discovery coordinator."""

from __future__ import annotations

import argparse
import asyncio
import json
import socket
from datetime import datetime

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
        choices=("run-once",),
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
    parser.add_argument("--owner", default=socket.gethostname())
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    async def execute() -> dict[str, int | bool]:
        runtime = build_production_runtime(owner=args.owner)
        try:
            return await runtime.run_once(limit=args.limit)
        finally:
            await runtime.aclose()

    result = asyncio.run(execute())
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
