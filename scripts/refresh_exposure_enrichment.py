#!/usr/bin/env python3
"""Refresh durable Exposure enrichment outside API request paths."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from intelligence.vulnerability.enrichment_cache import (
    EXPOSURE_ENRICHMENT_DOCUMENT,
    EnrichmentCache,
)
from intelligence.vulnerability.enrichment_worker import (
    EnrichmentTarget,
    EnrichmentWorker,
)
from storage.onelake_documents import OneLakeDocumentStore

DEFAULT_MAX_ITEMS = 100
MAX_ITEMS_LIMIT = 1_000
_OUTCOME_FIELDS = (
    "source",
    "identifier",
    "status",
    "attempted_at",
    "succeeded_at",
    "stale",
    "safe_error_code",
)


def _bounded_item_count(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("max-items must be an integer") from exc
    if parsed < 1 or parsed > MAX_ITEMS_LIMIT:
        raise argparse.ArgumentTypeError(
            f"max-items must be between 1 and {MAX_ITEMS_LIMIT}"
        )
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Refresh bounded MSRC, NVD, EPSS, and KEV items into the durable "
            "Exposure enrichment store."
        )
    )
    parser.add_argument(
        "--all-due",
        action="store_true",
        help="Refresh due items already registered in the durable store.",
    )
    parser.add_argument(
        "--source",
        choices=("msrc", "nvd", "epss", "kev"),
        help="Refresh one source for each supplied --id.",
    )
    parser.add_argument(
        "--id",
        action="append",
        dest="identifiers",
        default=[],
        help="Canonical KB/CVE identifier; repeat for a bounded source batch.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Refresh selected items even when their refresh-after time is in the future.",
    )
    parser.add_argument(
        "--max-items",
        type=_bounded_item_count,
        default=DEFAULT_MAX_ITEMS,
        help=f"Maximum items per execution (1-{MAX_ITEMS_LIMIT}; default {DEFAULT_MAX_ITEMS}).",
    )
    return parser


def _build_worker(*, max_items: int) -> EnrichmentWorker:
    root = os.environ.get("AIOPS_HOME", "").strip() or str(Path.home() / ".aiops")
    cache = EnrichmentCache(
        EXPOSURE_ENRICHMENT_DOCUMENT,
        store=OneLakeDocumentStore(root),
    )
    return EnrichmentWorker(cache, max_items=max_items)


def _targets(args: argparse.Namespace, worker: EnrichmentWorker) -> tuple[EnrichmentTarget, ...]:
    if args.all_due:
        if args.source or args.identifiers:
            raise ValueError("all_due_cannot_be_combined_with_source_or_id")
        identities = sorted(
            {
                (
                    str(record.get("source") or ""),
                    str(record.get("identifier") or ""),
                )
                for record in worker.cache.records()
                if _record_is_due(record)
            }
        )
        return tuple(
            EnrichmentTarget(source, identifier)
            for source, identifier in identities[: args.max_items]
        )
    if not args.source or not args.identifiers:
        raise ValueError("source_and_id_are_required_without_all_due")
    return tuple(
        EnrichmentTarget(args.source, identifier)
        for identifier in args.identifiers[: args.max_items]
    )


def _record_is_due(record: dict[str, Any]) -> bool:
    value = str(record.get("refresh_after") or "").strip()
    if not value:
        return False
    try:
        refresh_after = datetime.fromisoformat(value)
    except ValueError:
        return False
    if refresh_after.tzinfo is None:
        return False
    return datetime.now(UTC) >= refresh_after.astimezone(UTC)


def _redacted_outcome(outcome: Any) -> dict[str, Any]:
    row = outcome.to_dict()
    return {field: row.get(field) for field in _OUTCOME_FIELDS}


def _write_report(stdout: TextIO, report: dict[str, Any]) -> None:
    stdout.write(json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n")


def main(
    argv: Sequence[str] | None = None,
    *,
    worker_factory: Callable[..., EnrichmentWorker] = _build_worker,
    stdout: TextIO = sys.stdout,
) -> int:
    """Run one bounded refresh and emit only scheduler-safe JSON."""

    args = _parser().parse_args(argv)
    outcomes: list[dict[str, Any]] = []
    try:
        worker = worker_factory(max_items=args.max_items)
        targets = _targets(args, worker)
        worker.refresh(
            targets,
            force=args.force,
            on_outcome=lambda outcome: outcomes.append(
                _redacted_outcome(outcome)
            ),
        )
    except ValueError:
        _write_report(
            stdout,
            {
                "status": "failed",
                "safe_error_code": "invalid_refresh_contract",
                "outcomes": outcomes,
            },
        )
        return 2
    except Exception:  # noqa: BLE001 - never serialize provider/store exception text.
        _write_report(
            stdout,
            {
                "status": "failed",
                "safe_error_code": "enrichment_scheduler_failed",
                "outcomes": outcomes,
            },
        )
        return 1

    failed_count = sum(row["status"] == "failed" for row in outcomes)
    _write_report(
        stdout,
        {
            "status": "partial" if failed_count else "succeeded",
            "selected_count": len(targets),
            "attempted_count": sum(
                row["status"] != "not_due" for row in outcomes
            ),
            "failed_count": failed_count,
            "outcomes": outcomes,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
