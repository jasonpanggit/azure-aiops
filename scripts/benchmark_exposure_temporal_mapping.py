#!/usr/bin/env python3
"""Compare legacy and indexed Exposure timestamp mapping in fresh processes."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import platform
import resource
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from fabric_pipelines.vulnerability_pipeline import (
    _projected_at_by_current_key,
)

DEFAULT_KEYS = 5_000
DEFAULT_OBSERVATIONS_PER_KEY = 4


@dataclass(frozen=True, slots=True)
class _ObservationStamp:
    current_key: str
    ingested_at: str


def _observations(
    key_count: int,
    observations_per_key: int,
) -> tuple[_ObservationStamp, ...]:
    return tuple(
        _ObservationStamp(
            current_key=f"current-{key_index:08d}",
            ingested_at=(
                f"2026-09-{observation_index + 1:02d}T{key_index % 24:02d}:00:00Z"
            ),
        )
        for key_index in range(key_count)
        for observation_index in range(observations_per_key)
    )


def _legacy_projected_at_by_current_key(
    observations: tuple[_ObservationStamp, ...],
    current_keys: tuple[str, ...],
) -> dict[str, str]:
    return {
        current_key: max(
            observation.ingested_at
            for observation in observations
            if observation.current_key == current_key
        )
        for current_key in current_keys
    }


def _peak_rss_mib() -> float:
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    divisor = 1024 * 1024 if platform.system() == "Darwin" else 1024
    return rss / divisor


def _checksum(projected_at_by_current_key: dict[str, str]) -> str:
    serialized = json.dumps(
        projected_at_by_current_key,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(serialized).hexdigest()


def _worker(
    strategy: str,
    *,
    key_count: int,
    observations_per_key: int,
) -> dict[str, object]:
    observations = _observations(key_count, observations_per_key)
    current_keys = tuple(f"current-{key_index:08d}" for key_index in range(key_count))
    gc.collect()

    started_at = time.perf_counter()
    if strategy == "legacy":
        projected_at = _legacy_projected_at_by_current_key(
            observations,
            current_keys,
        )
    else:
        projected_at = _projected_at_by_current_key(observations)
    elapsed_seconds = time.perf_counter() - started_at

    return {
        "strategy": strategy,
        "key_count": key_count,
        "observation_count": len(observations),
        "elapsed_seconds": elapsed_seconds,
        "peak_rss_mib": _peak_rss_mib(),
        "checksum": _checksum(projected_at),
    }


def _run_isolated(
    strategy: str,
    *,
    key_count: int,
    observations_per_key: int,
) -> dict[str, object]:
    completed = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--worker",
            strategy,
            "--keys",
            str(key_count),
            "--observations-per-key",
            str(observations_per_key),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keys", type=int, default=DEFAULT_KEYS)
    parser.add_argument(
        "--observations-per-key",
        type=int,
        default=DEFAULT_OBSERVATIONS_PER_KEY,
    )
    parser.add_argument("--worker", choices=("legacy", "indexed"))
    args = parser.parse_args()
    if args.keys < 1 or args.observations_per_key < 1:
        parser.error("keys and observations-per-key must be positive")

    if args.worker is not None:
        print(
            json.dumps(
                _worker(
                    args.worker,
                    key_count=args.keys,
                    observations_per_key=args.observations_per_key,
                ),
                sort_keys=True,
            )
        )
        return 0

    legacy = _run_isolated(
        "legacy",
        key_count=args.keys,
        observations_per_key=args.observations_per_key,
    )
    indexed = _run_isolated(
        "indexed",
        key_count=args.keys,
        observations_per_key=args.observations_per_key,
    )
    if legacy["checksum"] != indexed["checksum"]:
        raise RuntimeError("legacy and indexed mappings produced different results")

    speedup = float(legacy["elapsed_seconds"]) / float(indexed["elapsed_seconds"])
    peak_rss_delta_mib = float(indexed["peak_rss_mib"]) - float(legacy["peak_rss_mib"])
    result = {
        "process_isolation": "one fresh subprocess per strategy",
        "fixture": {
            "key_count": args.keys,
            "observations_per_key": args.observations_per_key,
            "observation_count": args.keys * args.observations_per_key,
        },
        "legacy": legacy,
        "indexed": indexed,
        "speedup": speedup,
        "elapsed_improved": speedup > 1.0,
        "peak_rss_delta_mib": peak_rss_delta_mib,
        "memory_non_regressed": peak_rss_delta_mib <= 5.0,
        "results_equivalent": True,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    if speedup <= 1.0:
        raise RuntimeError("indexed mapping did not improve elapsed time")
    if peak_rss_delta_mib > 5.0:
        raise RuntimeError("indexed mapping regressed peak RSS by more than 5 MiB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
