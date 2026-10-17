"""Dataset-agnostic Fabric medallion health provider (MED-03).

Generalizes the Defender-family-only freshness/status/quality pattern
already proven in `VulnerabilityIntelligenceService._coverage_for_family()`
and `src/api/runtime.py::_snapshot_failure_table()` into one canonical
health contract usable by every Bronze/Silver/Gold/metadata dataset --
not just the Defender family.

`dataset_status(table_name)` is the single function every later Phase 10
surface (the dedicated health API, the web tab, Data Agent grounding's
freshness-SLO guardrail) calls for "what is this dataset's status".

Freshness objectives are *always* a bounded multiple of a dataset's own
producing-pipeline cadence, configured per table in
`fabric.medallion_health.freshness_slo` -- never a single global threshold.
Zero rows never implies success or failure on its own: a dataset's
`availability` distinguishes `healthy`, `healthy-empty`, `stale`, `degraded`,
`failed`, and `unavailable`.
"""

from __future__ import annotations

import json
import math
import os
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

# Safe-by-default: an unconfigured table still gets a real, dataset-scoped
# SLO -- (default cadence * default multiplier) -- never a single hardcoded
# constant shared by every dataset.
_DEFAULT_CADENCE_MINUTES = 60.0
_DEFAULT_SLO_MULTIPLIER = 3.0


@dataclass(frozen=True)
class FreshnessSloConfig:
    """Per-dataset freshness SLO thresholds (MED-03).

    Every table's SLO is its own (possibly overridden) cadence multiplied by
    its own (possibly overridden) multiplier -- two datasets with different
    cadences are always judged independently, never against one shared
    threshold.
    """

    default_cadence_minutes: float = _DEFAULT_CADENCE_MINUTES
    default_slo_multiplier: float = _DEFAULT_SLO_MULTIPLIER
    tables: Mapping[str, Mapping[str, float]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Invalid policy must fail, not turn every source into success or failure."""
        _positive_number(self.default_cadence_minutes)
        _positive_number(self.default_slo_multiplier)
        for name in self.tables:
            if not isinstance(self.tables[name], Mapping):
                raise TypeError("Fabric per-table freshness policy must be a mapping")
            self.slo_seconds(name)

    @classmethod
    def from_config(
        cls,
        config_path: str | Path | None = None,
    ) -> FreshnessSloConfig:
        """Load `fabric.medallion_health.freshness_slo` from `config_path`.

        Missing file/section/keys fall back to the safe defaults -- absence
        of config never crashes the health provider, it only ever falls back
        to the default multiplier applied to the default cadence.
        """
        path = Path(config_path or os.environ.get("AIOPS_FABRIC_CONFIG") or "fabric.config.yaml")
        if not path.is_file():
            return cls()
        try:
            payload = yaml.safe_load(path.read_text())
        except yaml.YAMLError as exc:
            raise ValueError("Fabric freshness configuration is invalid YAML") from exc
        if payload is None:
            payload = {}
        if not isinstance(payload, Mapping) or not isinstance(payload.get("fabric", {}), Mapping):
            raise TypeError("Fabric freshness configuration must be a mapping")
        section = payload.get("fabric", {}).get("medallion_health", {})
        if not isinstance(section, Mapping):
            raise TypeError("Fabric medallion health configuration must be a mapping")
        slo_section = section.get("freshness_slo", {})
        if not isinstance(slo_section, Mapping):
            raise TypeError("Fabric freshness policy must be a mapping")
        default_cadence = slo_section.get("default_cadence_minutes", _DEFAULT_CADENCE_MINUTES)
        default_multiplier = slo_section.get("default_slo_multiplier", _DEFAULT_SLO_MULTIPLIER)
        tables_section = slo_section.get("tables", {})
        tables: dict[str, dict[str, float]] = {}
        if not isinstance(tables_section, Mapping):
            raise TypeError("Fabric per-table freshness policies must be a mapping")
        for name, entry in tables_section.items():
            if not isinstance(entry, Mapping):
                raise TypeError("Fabric per-table freshness policy must be a mapping")
            tables[str(name)] = dict(entry)
        return cls(
            default_cadence_minutes=default_cadence,
            default_slo_multiplier=default_multiplier,
            tables=tables,
        )

    def slo_seconds(self, table_name: str) -> float:
        """Return the freshness SLO, in seconds, for `table_name`.

        Falls back to `default_cadence_minutes` * `default_slo_multiplier`
        when the table has no explicit override -- never a single global
        threshold shared by every dataset.
        """
        entry = self.tables.get(table_name) or {}
        cadence_minutes = _positive_number(entry.get("cadence_minutes", self.default_cadence_minutes))
        multiplier = _positive_number(entry.get("slo_multiplier", self.default_slo_multiplier))
        return _positive_number(cadence_minutes * multiplier * 60.0)


def _positive_number(value: Any) -> float:
    if isinstance(value, bool):
        raise TypeError("Fabric freshness cadence and multiplier must be finite positive numbers")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Fabric freshness cadence and multiplier must be finite positive numbers") from exc
    if not math.isfinite(number) or number <= 0:
        raise ValueError("Fabric freshness cadence and multiplier must be finite positive numbers")
    return number


def _freshness_slo_seconds(
    table_name: str,
    *,
    config: FreshnessSloConfig | None = None,
) -> float:
    """Module-level convenience wrapper around
    `FreshnessSloConfig.slo_seconds`, reading `fabric.config.yaml` by
    default when no `config` is injected."""
    return (config or FreshnessSloConfig.from_config()).slo_seconds(table_name)


def _parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.utcoffset() is None:
        return None
    return parsed


def _freshness_status(
    observed_at: str,
    table_name: str,
    *,
    config: FreshnessSloConfig | None = None,
    clock: Callable[[], datetime] | None = None,
) -> str:
    """Classify one dataset's freshness relative to its own configured SLO.

    `fresh`/`stale` are judged against `table_name`'s own threshold -- the
    same raw age can be `fresh` for a slow-cadence table and `stale` for a
    fast-cadence one.
    """
    parsed = _parse_timestamp(observed_at)
    if parsed is None:
        return "unknown"
    now = (clock or (lambda: datetime.now(UTC)))()
    age_seconds = (now - parsed).total_seconds()
    if age_seconds < 0:
        return "unknown"
    threshold = _freshness_slo_seconds(table_name, config=config)
    return "stale" if age_seconds > threshold else "fresh"


def _requested_scope(row: Mapping[str, Any]) -> dict[str, list[str]]:
    """Lifted from `VulnerabilityIntelligenceService._requested_scope`,
    generalized: no table-specific assumptions."""
    value = row.get("requested_scope")
    if not isinstance(value, Mapping):
        raw = row.get("requested_scope_json")
        if isinstance(raw, str) and raw:
            try:
                value = json.loads(raw)
            except json.JSONDecodeError:
                value = {}
    if not isinstance(value, Mapping):
        value = {}
    return {
        str(name): [str(item) for item in values if str(item)]
        for name, values in value.items()
        if isinstance(values, (list, tuple, set))
    }


def _status_timestamp(row: Mapping[str, Any]) -> str:
    return str(row.get("ingested_at") or row.get("observed_at") or row.get("timestamp") or "")


def _source_scope(row: Mapping[str, Any]) -> dict[str, list[str]]:
    scope = _requested_scope(row)
    if row.get("subscription_id"):
        scope["subscription"] = [str(row["subscription_id"])]
    connection = row.get("subscription_connection") or row.get("connection_id")
    if connection:
        scope["subscription_connection"] = [str(connection)]
    return scope


def _latest_per_scope(
    rows: Iterable[Mapping[str, Any]],
    table_name: str,
) -> list[dict[str, Any]]:
    """Reduce status by authoritative identity and requested scope.

    Unorderable clocks cannot safely be dismissed as old successes.
    """
    applicable = [
        dict(row)
        for row in rows
        if str(row.get("source_family") or row.get("table_name") or "") == table_name
    ]
    latest: dict[tuple[tuple[str, tuple[str, ...]], ...], dict[str, Any]] = {}
    for row in applicable:
        scope = _source_scope(row)
        key = tuple(sorted((name, tuple(sorted(values))) for name, values in scope.items()))
        existing = latest.get(key)
        timestamp = _parse_timestamp(_status_timestamp(row))
        previous = _parse_timestamp(_status_timestamp(existing)) if existing else None
        if existing is None or timestamp is None or previous is not None and timestamp > previous:
            latest[key] = row
    return list(latest.values())


def _freshness_budget(rows: list[dict[str, Any]], table_name: str, config: FreshnessSloConfig, now: datetime) -> dict[str, Any]:
    threshold = config.slo_seconds(table_name)
    policy = config.tables.get(table_name) or {}
    sources = []
    for row in rows:
        timestamp = _status_timestamp(row)
        parsed = _parse_timestamp(timestamp)
        age = None if parsed is None else (now - parsed).total_seconds()
        if age is not None and age < 0:
            age = None
        state = "unknown" if age is None else "stale" if age > threshold else "fresh"
        sources.append({
            "scope": _source_scope(row), "status_at": timestamp, "state": state,
            "age_seconds": age, "remaining_seconds": None if age is None else threshold - age,
        })
    states = {row["state"] for row in sources}
    state = "stale" if "stale" in states else "unknown" if not sources or "unknown" in states else "fresh"
    known = [row["age_seconds"] for row in sources if row["age_seconds"] is not None]
    return {
        "evaluated_at": now.isoformat(), "clock": "metadata_status_ingested_then_observed_then_timestamp",
        "state": state, "threshold_seconds": threshold,
        "cadence_minutes": _positive_number(policy.get("cadence_minutes", config.default_cadence_minutes)),
        "slo_multiplier": _positive_number(policy.get("slo_multiplier", config.default_slo_multiplier)),
        "policy": "table_override" if policy else "defaults",
        "source_count": len(sources), "known_clock_count": len(known),
        "worst_known_age_seconds": max(known) if known else None,
        "remaining_seconds": threshold - max(known) if sources and len(known) == len(sources) else None,
        "sources": sources,
    }


_AVAILABILITY_VALUES = (
    "healthy",
    "healthy-empty",
    "stale",
    "degraded",
    "failed",
    "unavailable",
)


def dataset_status(
    table_name: str,
    *,
    source_status: Iterable[Mapping[str, Any]] = (),
    row_count: int | None = None,
    freshness_slo: FreshnessSloConfig | None = None,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Dataset-agnostic health contract (MED-03).

    Returns `{availability, freshness, quality, row_count, last_success_at,
    lineage_ref}` for `table_name`, reading from the existing generalized
    `metadata_source_status` table (`source_status` rows, keyed by
    `source_family` == `table_name`). Every Bronze/Silver/Gold/metadata
    family uses this exact code path -- there is no copy-pasted
    Defender-only variant.

    `availability` never conflates zero-rows-healthy with a failure state:
    - `unavailable`: the source/provider itself could not be reached.
    - `failed`: the source was reachable but the last sync attempt failed.
    - `stale`: reachable, succeeded, but the data is older than its SLO.
    - `degraded`: reachable, succeeded, fresh, but quality checks failed.
    - `healthy-empty`: reachable, succeeded, fresh, quality complete, but
      zero rows -- never reported as `unavailable`/`failed`.
    - `healthy`: reachable, succeeded, fresh, quality complete, rows present.
    """
    rows = _latest_per_scope(source_status, table_name)
    config = freshness_slo or FreshnessSloConfig.from_config()
    now = (clock or (lambda: datetime.now(UTC)))()
    budget = _freshness_budget(rows, table_name, config, now)

    if not rows:
        total_row_count = int(row_count) if row_count is not None else 0
        if row_count is None:
            availability = "unavailable"
        elif total_row_count == 0:
            availability = "healthy-empty"
        else:
            availability = "healthy"
        return {
            "table_name": table_name,
            "availability": availability,
            "freshness": "unknown",
            "quality": "unknown",
            "row_count": total_row_count,
            "stale_after_seconds": budget["threshold_seconds"],
            "freshness_budget": budget,
            "observed_at": "",
            "ingested_at": "",
            "watermark": "",
            "last_success_at": "",
            "error": "",
            "lineage_ref": "",
        }

    any_unavailable = any(str(row.get("availability") or "") == "unavailable" for row in rows)
    any_failed = any(str(row.get("status") or "") == "failed" for row in rows)

    quality_values = {str(row.get("quality") or "unknown") for row in rows}
    quality = (
        "degraded"
        if "degraded" in quality_values
        else "complete"
        if quality_values == {"complete"}
        else "unknown"
    )

    latest_observed_at = max(_status_timestamp(row) for row in rows)
    freshness = budget["state"]

    total_row_count = (
        int(row_count)
        if row_count is not None
        else sum(int(row.get("row_count") or 0) for row in rows)
    )

    last_success_at = max(
        (_status_timestamp(row) for row in rows if str(row.get("status") or "") == "succeeded"),
        default="",
    )

    lineage_ref = ""
    for row in sorted(rows, key=_status_timestamp):
        candidate = str(row.get("lineage_ref") or "")
        if candidate:
            lineage_ref = candidate

    error = "; ".join(
        sorted({str(row.get("error") or "") for row in rows if row.get("error")})
    )

    # The durable upstream checkpoint the last sync advanced to. Falls back to
    # the ingestion timestamp so a published dataset never reports "unknown"
    # purely because its pipeline does not carry a distinct watermark column.
    watermark = max(
        (str(row.get("watermark") or "") for row in rows),
        default="",
    ) or latest_observed_at

    if any_unavailable:
        availability = "unavailable"
    elif any_failed:
        availability = "failed"
    elif freshness == "stale":
        availability = "stale"
    elif quality == "degraded" or freshness == "unknown":
        availability = "degraded"
    elif total_row_count == 0:
        availability = "healthy-empty"
    else:
        availability = "healthy"

    result: dict[str, Any] = {
        "table_name": table_name,
        "availability": availability,
        "freshness": freshness,
        "quality": quality,
        "row_count": total_row_count,
        "stale_after_seconds": budget["threshold_seconds"],
        "freshness_budget": budget,
        "observed_at": max((str(row.get("observed_at") or "") for row in rows), default=""),
        "ingested_at": max((str(row.get("ingested_at") or "") for row in rows), default=""),
        "watermark": watermark,
        "last_success_at": last_success_at,
        "error": error,
        "lineage_ref": lineage_ref,
    }
    return result


__all__ = [
    "FreshnessSloConfig",
    "dataset_status",
]
