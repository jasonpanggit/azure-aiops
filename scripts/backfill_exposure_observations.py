#!/usr/bin/env python3
"""Resumable additive backfill for Exposure temporal products.

Rollback changes the reader or active generation pointer. It never removes the
versioned observation table, because retained history is required for replay
and any later identity migration.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from fabric.dataset_mapper import InventoryDatasetMapper, temporal_inputs_from_legacy
from fabric_pipelines.vulnerability_pipeline import TemporalExposureFabricWriter
from intelligence.vulnerability.exposure_projection import build_temporal_projection
from storage.datasets import DatasetStore
from storage.delta_writer import DeltaWriter

BACKFILL_CONTRACT_VERSION = "1.0.0"


def run_backfill_batches(
    datasets: Mapping[str, list[dict[str, Any]]],
    *,
    table_root: Path | str,
    generation_id: str,
    checkpoint_path: Path | str,
    batch_size: int = 500,
    max_batches: int | None = None,
) -> dict[str, Any]:
    """Backfill a bounded number of batches and persist an exact resume point."""

    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    if max_batches is not None and max_batches < 1:
        raise ValueError("max_batches must be positive")

    inputs = temporal_inputs_from_legacy(datasets)
    fingerprint = hashlib.sha256(
        json.dumps(
            inputs,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()
    checkpoint_file = Path(checkpoint_path)
    checkpoint = _load_checkpoint(
        checkpoint_file,
        generation_id=generation_id,
        source_fingerprint=fingerprint,
    )
    offset = int(checkpoint["next_offset"])
    processed = 0
    batches = 0
    writer = TemporalExposureFabricWriter(
        table_root=table_root,
        delta_writer=DeltaWriter(),
    )
    ingested_at = _stable_ingested_at(datasets)

    while offset < len(inputs) and (max_batches is None or batches < max_batches):
        batch = inputs[offset : offset + batch_size]
        projection = build_temporal_projection(
            batch,
            generation_id=generation_id,
            ingested_at=ingested_at,
            run_at=ingested_at,
        )
        writer.publish(projection)
        offset += len(batch)
        processed += len(batch)
        batches += 1
        _save_checkpoint(
            checkpoint_file,
            generation_id=generation_id,
            source_fingerprint=fingerprint,
            next_offset=offset,
            total=len(inputs),
        )

    completed = offset >= len(inputs)
    if not inputs:
        _save_checkpoint(
            checkpoint_file,
            generation_id=generation_id,
            source_fingerprint=fingerprint,
            next_offset=0,
            total=0,
        )
    return {
        "contract_version": BACKFILL_CONTRACT_VERSION,
        "generation_id": generation_id,
        "processed": processed,
        "next_offset": offset,
        "total": len(inputs),
        "completed": completed,
    }


def _load_checkpoint(
    path: Path,
    *,
    generation_id: str,
    source_fingerprint: str,
) -> dict[str, Any]:
    if not path.exists():
        return {"next_offset": 0}
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("contract_version") != BACKFILL_CONTRACT_VERSION:
        raise ValueError("Backfill checkpoint contract version mismatch")
    if value.get("generation_id") != generation_id:
        raise ValueError("Backfill checkpoint generation mismatch")
    if value.get("source_fingerprint") != source_fingerprint:
        raise ValueError("Backfill source changed; start with a new checkpoint")
    return value


def _save_checkpoint(
    path: Path,
    *,
    generation_id: str,
    source_fingerprint: str,
    next_offset: int,
    total: int,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "contract_version": BACKFILL_CONTRACT_VERSION,
        "generation_id": generation_id,
        "source_fingerprint": source_fingerprint,
        "next_offset": next_offset,
        "total": total,
        "completed": next_offset >= total,
    }
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _stable_ingested_at(datasets: Mapping[str, list[dict[str, Any]]]) -> str:
    timestamps = [
        str(row.get("timestamp") or "")
        for rows in datasets.values()
        for row in rows
        if row.get("timestamp")
    ]
    return max(timestamps, default="1970-01-01T00:00:00Z")


def _load_source(source_root: Path, generation_id: str) -> dict[str, list[dict]]:
    store = DatasetStore(source_root)
    active = store.current_generation()
    if active is None:
        raise RuntimeError("Source DatasetStore has no active generation")
    active_id = Path(active).name
    if generation_id and generation_id != active_id:
        raise RuntimeError("Requested generation is not the active source generation")
    return InventoryDatasetMapper().load(active, active_id)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill immutable Exposure observations and replay generation-current "
            "state from retained patch, Defender, and image products."
        )
    )
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--target-root", type=Path, required=True)
    parser.add_argument("--generation-id", required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--max-batches", type=int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = run_backfill_batches(
        _load_source(args.source_root, args.generation_id),
        table_root=args.target_root,
        generation_id=args.generation_id,
        checkpoint_path=args.checkpoint,
        batch_size=args.batch_size,
        max_batches=args.max_batches,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
