"""Compare two saved Catalog observations offline, without fresh verification."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .catalog_changes import compare_catalog_reports, validate_catalog_report


def _read_report(path: str) -> dict[str, Any]:
    if "://" in path:
        raise ValueError("Catalog observations must be local files")
    with Path(path).open("rb") as stream:
        return validate_catalog_report(stream.read(2_000_001).decode("utf-8"))


def main(argv: Sequence[str] | None = None) -> int:
    """Print a saved-evidence advisory delta or a sanitized nonzero failure.

    This command reads local files only. It does not load runtime configuration,
    acquire credentials, verify live metadata or write either input.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, help="Local prior successful Catalog report")
    parser.add_argument("--current", required=True, help="Local subsequent successful Catalog report")
    args = parser.parse_args(argv)
    stage = "saved_report_validation"
    try:
        baseline = _read_report(args.baseline)
        current = _read_report(args.current)
        stage = "catalog_comparison"
        delta = compare_catalog_reports(baseline, current)
        print(json.dumps({
            "status": "advisory_metadata_compared",
            "mode": "offline",
            "verification_performed": False,
            "metadata_delta": delta,
        }, sort_keys=True))
        return 0
    except (OSError, ValueError, TypeError, RecursionError):
        print(
            json.dumps({"status": "failed", "failure_stage": stage}),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
