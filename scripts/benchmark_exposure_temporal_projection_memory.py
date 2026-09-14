#!/usr/bin/env python3
"""Synthetic-scale peak-memory benchmark for exposure temporal projection.

PR #98 replaced the O(K*N) full-history replay in
``materialize_temporal_exposure_tables`` with an incremental fold that is
provably equivalent to a full replay (see the fallback conditions documented
on that function). That fix targets *comparison cost* (CPU time): it does
**not** target peak memory, because the pipeline still deserializes and
groups the complete retained observation history into ``combined_by_key``
on every run, incremental or not.

This script measures that honestly, at a scale representative of the
~87k current-key / ~174k observation counts referenced in the production
incident, using synthetic (locally generated) data:

* No cloud/Fabric access, no network calls, no production data.
* Peak RSS is measured for a cold full-history run (``project_all`` style,
  ``existing_current_rows=None``) and for a warm incremental run (a second
  publication cycle with ``existing_current_rows`` supplied and a small
  batch of genuinely new observations), so the two costs can be compared.
* This is scale-representative synthetic evidence, not a production SLO
  certification -- it cannot observe real Fabric row shapes, real payload
  sizes, or real key-cardinality skew. It exists to answer one narrow
  question honestly: does the PR #98 incremental fold reduce peak memory
  at production-representative counts, or only CPU/comparison time?

Usage:
    python3 scripts/benchmark_exposure_temporal_projection_memory.py \
        --current-keys 87000 --observations-per-key 2 --new-observations 5000
"""

from __future__ import annotations

import argparse
import gc
import json
import resource
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from fabric_pipelines.vulnerability_pipeline import (
    materialize_temporal_exposure_tables,
)
from intelligence.vulnerability.exposure_projection import (
    ExposureTemporalProjection,
)
from intelligence.vulnerability.observations import ExposureObservation

DEFAULT_CURRENT_KEYS = 87_000
DEFAULT_OBSERVATIONS_PER_KEY = 2
DEFAULT_NEW_OBSERVATIONS = 5_000


def _rss_bytes() -> int:
    usage = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    # macOS reports bytes; Linux and most other Unix platforms report KiB.
    return usage if sys.platform == "darwin" else usage * 1_024


def _make_observation(
    *, key_index: int, sequence: int, event_time: str, ingested_at: str
) -> ExposureObservation:
    return ExposureObservation.create(
        tenant_id="tenant-bench",
        connection_id="connection-bench",
        source_family="azure_update_manager_missing",
        target_id=(
            "/subscriptions/sub-bench/resourceGroups/rg/providers/"
            f"Microsoft.Compute/virtualMachines/vm-{key_index}"
        ),
        target_kind="server",
        weakness_id=f"KB-{6_000_000 + (key_index % 500)}",
        weakness_kind="kb",
        event="missing" if sequence == 1 else "installed",
        provider_operation_id=f"op-{key_index}-{sequence}",
        provider_status="succeeded",
        operation_succeeded=True,
        event_time=event_time,
        source_sequence=sequence,
        source_generation="generation-bench",
        ingested_at=ingested_at,
        run_at=ingested_at,
        published_at="",
        payload={"severity": "High", "note": f"synthetic-{key_index}-{sequence}"},
        title="Synthetic benchmark exposure",
    )


def _build_history(
    current_keys: int, observations_per_key: int
) -> tuple[ExposureObservation, ...]:
    observations: list[ExposureObservation] = []
    for key_index in range(current_keys):
        for sequence in range(1, observations_per_key + 1):
            day = 1 + (sequence - 1)
            observations.append(
                _make_observation(
                    key_index=key_index,
                    sequence=sequence,
                    event_time=f"2026-01-{day:02d}T00:00:00Z",
                    ingested_at=f"2026-01-{day:02d}T00:01:00Z",
                )
            )
    return tuple(observations)


def _build_new_batch(
    current_keys: int, observations_per_key: int, count: int
) -> tuple[ExposureObservation, ...]:
    """New observations for the *last* ``count`` keys only (a realistic
    incremental publication touches a small fraction of all known keys)."""
    start = max(0, current_keys - count)
    next_sequence = observations_per_key + 1
    return tuple(
        _make_observation(
            key_index=key_index,
            sequence=next_sequence,
            event_time="2026-02-01T00:00:00Z",
            ingested_at="2026-02-01T00:01:00Z",
        )
        for key_index in range(start, current_keys)
    )


def _measure(label: str, fn) -> dict[str, Any]:
    gc.collect()
    baseline_rss = _rss_bytes()
    start = time.perf_counter()
    result = fn()
    elapsed = time.perf_counter() - start
    gc.collect()
    peak_rss = _rss_bytes()
    return {
        "label": label,
        "elapsed_seconds": round(elapsed, 3),
        "baseline_rss_bytes": baseline_rss,
        "peak_rss_bytes": peak_rss,
        "peak_rss_delta_mib": round((peak_rss - baseline_rss) / (1024 * 1024), 2),
        "result": result,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current-keys", type=int, default=DEFAULT_CURRENT_KEYS)
    parser.add_argument(
        "--observations-per-key", type=int, default=DEFAULT_OBSERVATIONS_PER_KEY
    )
    parser.add_argument(
        "--new-observations", type=int, default=DEFAULT_NEW_OBSERVATIONS
    )
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    print(
        f"Building synthetic history: {args.current_keys} keys x "
        f"{args.observations_per_key} observations/key = "
        f"{args.current_keys * args.observations_per_key} total observations",
        file=sys.stderr,
    )
    history = _build_history(args.current_keys, args.observations_per_key)

    def cold_full_replay() -> dict[str, Any]:
        projection = ExposureTemporalProjection(
            observations=history, current=(), generation_id="gen-cold"
        )
        materialization = materialize_temporal_exposure_tables(projection)
        return {
            "observation_rows": len(materialization.observation_rows),
            "current_rows": len(materialization.current_rows),
        }

    cold = _measure("cold_full_replay (existing_current_rows=None)", cold_full_replay)

    # Re-run once (without measuring) to obtain the persisted rows needed to
    # seed the warm/incremental run, mirroring how a real second publication
    # cycle would read back its own prior output.
    projection = ExposureTemporalProjection(
        observations=history, current=(), generation_id="gen-cold"
    )
    first_run = materialize_temporal_exposure_tables(projection)
    existing_rows = list(first_run.observation_rows)
    existing_current_rows = list(first_run.current_rows)

    new_batch = _build_new_batch(
        args.current_keys, args.observations_per_key, args.new_observations
    )

    def warm_incremental_fold() -> dict[str, Any]:
        projection = ExposureTemporalProjection(
            observations=new_batch, current=(), generation_id="gen-warm"
        )
        materialization = materialize_temporal_exposure_tables(
            projection,
            existing_rows=existing_rows,
            known_observation_rows=existing_rows,
            existing_current_rows=existing_current_rows,
        )
        return {
            "observation_rows": len(materialization.observation_rows),
            "current_rows": len(materialization.current_rows),
        }

    warm = _measure(
        "warm_incremental_fold (existing_current_rows supplied)",
        warm_incremental_fold,
    )

    report = {
        "synthetic": True,
        "production_certified": False,
        "reason_code": "synthetic_local_data_not_production_measurement",
        "parameters": {
            "current_keys": args.current_keys,
            "observations_per_key": args.observations_per_key,
            "total_history_observations": len(history),
            "new_observations": len(new_batch),
        },
        "cold_full_replay": cold,
        "warm_incremental_fold": warm,
        "notes": [
            (
                "PR #98's incremental fold reduces comparison/CPU cost for "
                "keys that pass the fold-base validity checks; it does not "
                "reduce peak memory, because the full retained history is "
                "still deserialized and grouped by key on every run."
            ),
            (
                "Real production peak RSS depends on actual Fabric row "
                "width, payload sizes, and key/observation skew, none of "
                "which this synthetic fixture can reproduce. Treat these "
                "numbers as a scale-representative lower bound on memory "
                "pressure, not a production SLO certification."
            ),
        ],
    }

    output_json = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(output_json + "\n")
        print(f"Wrote report to {args.output}", file=sys.stderr)
    print(output_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
