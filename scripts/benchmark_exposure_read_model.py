#!/usr/bin/env python3
"""Benchmark scaffold and fail-fast Fabric SQL production preflight.

Wave 0 deliberately separates two claims:

* ``deterministic_memory`` proves fixture generation, query timing, percentile
  reporting, and duplicate-free full-walk accounting. It is never production
  SLO evidence.
* ``fabric_sql`` is the selected production adapter. Its readiness probe names
  every prerequisite and never silently substitutes the Delta reader.

Plans 03.1-04 and 03.1-13 connect the strict readiness result and deployed SQL
query adapter to the 100k release gate.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
import os
import platform
import resource
import sys
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from api.exposure_query import (
    ExposureAuthorization,
    ExposureFilter,
    ExposureQuery,
    ExposureQueryService,
)
from fabric.auth import FabricAuthConfig, build_credential
from fabric.sql_endpoint import (
    FABRIC_SQL_ADAPTER_ID,
    REQUIRED_EXPOSURE_SCHEMA,
    REQUIRED_ODBC_DRIVER,
    probe_exposure_readiness,
    require_exposure_ready,
)

PRODUCTION_ADAPTER_ID = FABRIC_SQL_ADAPTER_ID
LOCAL_ADAPTER_ID = "deterministic_memory"
REQUIRED_DRIVER = REQUIRED_ODBC_DRIVER
DEFAULT_ROWS = 100_000
DEFAULT_SEED = 31_001
DEFAULT_WARMUPS = 5
DEFAULT_MEASUREMENTS = 20
DEFAULT_PAGE_SIZE = 50
SLO_MILLISECONDS = 2_000.0

REQUIRED_GOLD_SCHEMA = REQUIRED_EXPOSURE_SCHEMA


@dataclass(frozen=True, slots=True)
class ExposureRow:
    exposure_id: str
    read_model_generation_id: str
    tenant_id: str
    subscription_id: str
    connection_id: str
    target_id: str
    target_kind: str
    weakness_id: str
    source_family: str
    severity: str
    priority_score: int


@dataclass(frozen=True, slots=True)
class QuerySpec:
    subscriptions: tuple[str, ...]
    source_family: str | None = None
    severity: str | None = None
    target_kind: str | None = None
    search: str | None = None
    page_size: int = DEFAULT_PAGE_SIZE


@dataclass(frozen=True, slots=True)
class PageResult:
    rows: tuple[ExposureRow, ...]
    total_count: int
    next_position: tuple[int, str] | None


def _stable_digest(*parts: object) -> str:
    payload = json.dumps(
        [str(part).strip().casefold() for part in parts],
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def generate_exposure_rows(
    row_count: int,
    *,
    seed: int = DEFAULT_SEED,
    generation_id: str = "benchmark-generation-0001",
) -> list[ExposureRow]:
    """Generate deterministic server/image rows with deliberate priority ties."""
    if row_count <= 0:
        raise ValueError("row_count must be positive")

    tenant_id = "benchmark-tenant"
    subscriptions = tuple(f"00000000-0000-0000-0000-{index:012d}" for index in range(1, 5))
    severities = ("critical", "high", "medium", "low")
    source_families = ("aum", "defender", "container_images")
    rows: list[ExposureRow] = []
    for index in range(row_count):
        subscription_id = subscriptions[(index + seed) % len(subscriptions)]
        target_kind = "container_image" if index % 5 == 0 else "server"
        if target_kind == "container_image":
            digest = _stable_digest(seed, index)
            target_id = (
                f"/subscriptions/{subscription_id}/resourceGroups/rg-benchmark/"
                "providers/Microsoft.ContainerRegistry/registries/acrbenchmark/"
                f"repositories/platform-api/digests/sha256:{digest}"
            )
        else:
            target_id = (
                f"/subscriptions/{subscription_id}/resourceGroups/rg-benchmark/"
                f"providers/Microsoft.Compute/virtualMachines/vm-{index:06d}"
            )
        weakness_id = f"CVE-2026-{5000 + (index % 251):04d}"
        source_family = source_families[(index + seed) % len(source_families)]
        severity = severities[(index // 7 + seed) % len(severities)]
        # A small score domain intentionally creates large tie groups so the
        # stable exposure_id tie-breaker is exercised across page boundaries.
        priority_score = 1_000 - ((index + seed) % 41) * 10
        exposure_id = f"exposure:{_stable_digest(tenant_id, target_id, target_kind, weakness_id)}"
        rows.append(
            ExposureRow(
                exposure_id=exposure_id,
                read_model_generation_id=generation_id,
                tenant_id=tenant_id,
                subscription_id=subscription_id,
                connection_id=f"benchmark-connection-{(index % 2) + 1}",
                target_id=target_id,
                target_kind=target_kind,
                weakness_id=weakness_id,
                source_family=source_family,
                severity=severity,
                priority_score=priority_score,
            )
        )
    return rows


def _row_sort_key(row: ExposureRow) -> tuple[int, str]:
    return (-row.priority_score, row.exposure_id)


class DeterministicMemoryAdapter:
    """Correctness-only adapter; never production or scale certification."""

    adapter_id = LOCAL_ADAPTER_ID
    production = False

    def __init__(self, rows: Iterable[ExposureRow]) -> None:
        self._rows = tuple(sorted(rows, key=_row_sort_key))
        self._sort_keys = tuple(_row_sort_key(row) for row in self._rows)
        self._subscriptions = frozenset(row.subscription_id for row in self._rows)
        self.query_count = 0
        self.rows_fetched = 0
        self.max_rows_fetched_per_query = 0
        self.full_table_materializations = 0
        self.delta_fallbacks = 0

    @staticmethod
    def _matches(row: ExposureRow, spec: QuerySpec) -> bool:
        if row.subscription_id not in spec.subscriptions:
            return False
        if spec.source_family and row.source_family != spec.source_family:
            return False
        if spec.severity and row.severity != spec.severity:
            return False
        if spec.target_kind and row.target_kind != spec.target_kind:
            return False
        if spec.search:
            needle = spec.search.casefold()
            if needle not in row.target_id.casefold() and needle not in row.weakness_id.casefold():
                return False
        return True

    def query(
        self,
        spec: QuerySpec,
        *,
        after: tuple[int, str] | None = None,
    ) -> PageResult:
        self.query_count += 1
        if spec.page_size not in {25, 50, 100}:
            raise ValueError("page_size must be one of 25, 50, or 100")
        unfiltered_full_scope = (
            frozenset(spec.subscriptions) == self._subscriptions
            and spec.source_family is None
            and spec.severity is None
            and spec.target_kind is None
            and spec.search is None
        )
        candidates = (
            self._rows
            if unfiltered_full_scope
            else tuple(row for row in self._rows if self._matches(row, spec))
        )
        total_count = len(candidates)
        start = 0
        if after is not None:
            after_key = (-after[0], after[1])
            if len(candidates) == len(self._rows):
                start = bisect.bisect_right(self._sort_keys, after_key)
            else:
                candidate_keys = tuple(_row_sort_key(row) for row in candidates)
                start = bisect.bisect_right(candidate_keys, after_key)
        page_rows = candidates[start : start + spec.page_size]
        self.rows_fetched += len(page_rows)
        self.max_rows_fetched_per_query = max(
            self.max_rows_fetched_per_query,
            len(page_rows),
        )
        has_more = start + len(page_rows) < total_count
        next_position = (
            (page_rows[-1].priority_score, page_rows[-1].exposure_id)
            if page_rows and has_more
            else None
        )
        return PageResult(
            rows=page_rows,
            total_count=total_count,
            next_position=next_position,
        )

    def summary(self, subscriptions: Sequence[str]) -> dict[str, int]:
        self.query_count += 1
        self.rows_fetched += 1
        self.max_rows_fetched_per_query = max(
            self.max_rows_fetched_per_query,
            1,
        )
        scoped = [row for row in self._rows if row.subscription_id in subscriptions]
        return {
            "total_count": len(scoped),
            "critical_count": sum(row.severity == "critical" for row in scoped),
            "image_count": sum(row.target_kind == "container_image" for row in scoped),
        }


def exact_full_walk(
    adapter: DeterministicMemoryAdapter,
    spec: QuerySpec,
) -> dict[str, Any]:
    seen: list[str] = []
    expected_total: int | None = None
    position: tuple[int, str] | None = None
    page_count = 0
    while True:
        page = adapter.query(spec, after=position)
        page_count += 1
        expected_total = page.total_count if expected_total is None else expected_total
        if page.total_count != expected_total:
            raise AssertionError("total_count changed during full walk")
        seen.extend(row.exposure_id for row in page.rows)
        if page.next_position is None:
            break
        if page.next_position == position:
            raise AssertionError("cursor position did not advance")
        position = page.next_position

    unique_count = len(set(seen))
    if len(seen) != expected_total:
        raise AssertionError(f"full walk returned {len(seen)} rows, expected {expected_total}")
    if unique_count != expected_total:
        raise AssertionError(
            f"full walk returned {expected_total - unique_count} duplicate identities"
        )
    return {
        "expected_total": expected_total,
        "returned_count": len(seen),
        "unique_count": unique_count,
        "page_count": page_count,
        "duplicate_count": len(seen) - unique_count,
        "omission_count": expected_total - unique_count,
        "status": "pass",
    }


def _percentile(samples_ms: Sequence[float], percentile: float) -> float:
    if not samples_ms:
        raise ValueError("percentile requires at least one sample")
    ordered = sorted(samples_ms)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return round(ordered[index], 3)


def _measure(
    operation: Callable[[], object],
    *,
    warmups: int,
    measurements: int,
) -> dict[str, Any]:
    cold_started = time.perf_counter_ns()
    operation()
    cold_ms = (time.perf_counter_ns() - cold_started) / 1_000_000
    for _ in range(warmups):
        operation()
    samples_ms: list[float] = []
    for _ in range(measurements):
        started = time.perf_counter_ns()
        operation()
        elapsed_ns = time.perf_counter_ns() - started
        samples_ms.append(elapsed_ns / 1_000_000)
    return {
        "cold_ms": round(cold_ms, 3),
        "warmups": warmups,
        "measurements": measurements,
        "p50_ms": _percentile(samples_ms, 0.50),
        "p95_ms": _percentile(samples_ms, 0.95),
        "p99_ms": _percentile(samples_ms, 0.99),
        "min_ms": round(min(samples_ms), 3),
        "max_ms": round(max(samples_ms), 3),
    }


def run_local_benchmark(
    *,
    row_count: int,
    seed: int,
    page_size: int,
    warmups: int,
    measurements: int,
) -> dict[str, Any]:
    rss_before = _rss_bytes()
    rows = generate_exposure_rows(row_count, seed=seed)
    adapter = DeterministicMemoryAdapter(rows)
    subscriptions = tuple(sorted({row.subscription_id for row in rows}))
    default_query = QuerySpec(subscriptions=subscriptions, page_size=page_size)
    filtered_query = QuerySpec(
        subscriptions=(subscriptions[0],),
        source_family="defender",
        severity="critical",
        page_size=page_size,
    )
    server_query = QuerySpec(
        subscriptions=subscriptions,
        target_kind="server",
        page_size=page_size,
    )
    image_query = QuerySpec(
        subscriptions=subscriptions,
        target_kind="container_image",
        page_size=page_size,
    )
    first_page = adapter.query(default_query)
    next_position = first_page.next_position
    if next_position is None and row_count > page_size:
        raise AssertionError("first page did not produce a continuation")

    timings = {
        "count_and_default_first_page": _measure(
            lambda: adapter.query(default_query),
            warmups=warmups,
            measurements=measurements,
        ),
        "scoped_filtered_first_page": _measure(
            lambda: adapter.query(filtered_query),
            warmups=warmups,
            measurements=measurements,
        ),
        "server_scoped_first_page": _measure(
            lambda: adapter.query(server_query),
            warmups=warmups,
            measurements=measurements,
        ),
        "image_scoped_first_page": _measure(
            lambda: adapter.query(image_query),
            warmups=warmups,
            measurements=measurements,
        ),
        "next_page_keyset": _measure(
            lambda: adapter.query(default_query, after=next_position),
            warmups=warmups,
            measurements=measurements,
        ),
        "summary": _measure(
            lambda: adapter.summary(subscriptions),
            warmups=warmups,
            measurements=measurements,
        ),
    }
    walk = exact_full_walk(adapter, default_query)
    filtered_p95 = timings["scoped_filtered_first_page"]["p95_ms"]
    under_budget = all(
        timing["p95_ms"] < SLO_MILLISECONDS
        for timing in timings.values()
    )
    target_kind_counts = {
        kind: sum(row.target_kind == kind for row in rows)
        for kind in ("container_image", "server")
    }
    rss_after = _rss_bytes()
    return {
        "schema_version": "1.0.0",
        "status": "pass" if under_budget else "fail",
        "adapter": {
            "adapter_id": adapter.adapter_id,
            "selected_production_adapter": PRODUCTION_ADAPTER_ID,
            "production": adapter.production,
            "production_slo_evidence": False,
            "delta_selected": False,
        },
        "dataset": {
            "row_count": row_count,
            "seed": seed,
            "generation_id": rows[0].read_model_generation_id,
            "subscription_count": len(subscriptions),
            "target_kind_counts": target_kind_counts,
            "fingerprint": _stable_digest(*(row.exposure_id for row in rows)),
        },
        "query_contract": {
            "page_size": page_size,
            "sort": ["priority_score:desc", "exposure_id:asc"],
            "scope_first": True,
        },
        "timings": timings,
        "full_walk": walk,
        "work": {
            "query_count": adapter.query_count,
            "rows_fetched": adapter.rows_fetched,
            "max_rows_fetched_per_query": adapter.max_rows_fetched_per_query,
            "full_table_materializations": adapter.full_table_materializations,
            "delta_fallbacks": adapter.delta_fallbacks,
        },
        "memory": {
            "rss_before_bytes": rss_before,
            "rss_after_bytes": rss_after,
            "rss_delta_bytes": max(0, rss_after - rss_before),
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
        },
        "slo": {
            "target_p95_ms": SLO_MILLISECONDS,
            "observed_filtered_first_page_p95_ms": filtered_p95,
            "observed_under_target": under_budget,
            "production_certified": False,
            "reason_code": "local_adapter_is_not_production_slo_evidence",
        },
    }


def _rss_bytes() -> int:
    usage = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    # macOS reports bytes; Linux and most other Unix platforms report KiB.
    return usage if sys.platform == "darwin" else usage * 1_024


class InstrumentedFabricSqlReader:
    """Record bounded transfer work without changing the selected adapter."""

    def __init__(self, reader: Any) -> None:
        self._reader = reader
        self.endpoint = reader.endpoint
        self.query_count = 0
        self.rows_fetched = 0
        self.max_rows_fetched_per_query = 0

    def query(
        self,
        sql: str,
        parameters: Iterable[Any] = (),
        *,
        max_rows: int | None = None,
    ) -> list[dict[str, Any]]:
        if max_rows is None:
            raise AssertionError(
                "Production benchmark query attempted an unbounded fetch"
            )
        rows = self._reader.query(
            sql,
            parameters,
            max_rows=max_rows,
        )
        self.query_count += 1
        self.rows_fetched += len(rows)
        self.max_rows_fetched_per_query = max(
            self.max_rows_fetched_per_query,
            len(rows),
        )
        return rows


def _exact_service_walk(
    service: ExposureQueryService,
    authorization: ExposureAuthorization,
    query: ExposureQuery,
    *,
    generation_id: str,
) -> dict[str, Any]:
    expected_total: int | None = None
    position: tuple[Any, str] | None = None
    seen: list[str] = []
    page_count = 0
    while True:
        page = service.list_page(
            authorization,
            generation_id=generation_id,
            query=query,
            after=position,
        )
        page_count += 1
        expected_total = (
            page.total_count
            if expected_total is None
            else expected_total
        )
        if page.total_count != expected_total:
            raise AssertionError(
                "total_count changed during Fabric SQL full walk"
            )
        seen.extend(str(row["exposure_id"]) for row in page.items)
        if page.next_position is None:
            break
        if page.next_position == position:
            raise AssertionError(
                "Fabric SQL cursor position did not advance"
            )
        position = page.next_position
    unique_count = len(set(seen))
    status = (
        "pass"
        if len(seen) == expected_total == unique_count
        else "fail"
    )
    return {
        "expected_total": expected_total,
        "returned_count": len(seen),
        "unique_count": unique_count,
        "page_count": page_count,
        "duplicate_count": len(seen) - unique_count,
        "omission_count": int(expected_total or 0) - unique_count,
        "status": status,
    }


def run_fabric_sql_benchmark(
    reader: Any,
    authorization: ExposureAuthorization,
    *,
    generation_id: str,
    expected_rows_per_kind: int,
    page_size: int,
    warmups: int,
    measurements: int,
) -> dict[str, Any]:
    """Run the qualifying canary against the real Fabric SQL query service."""
    rss_before = _rss_bytes()
    instrumented = InstrumentedFabricSqlReader(reader)
    service = ExposureQueryService(instrumented)
    scenarios = {
        target_kind: ExposureQuery(
            filters=(
                ExposureFilter(
                    "target_kind",
                    "eq",
                    target_kind,
                ),
            ),
            page_size=page_size,
        )
        for target_kind in ("server", "container_image")
    }
    timings = {
        f"{name}_cold_warm_count_page": _measure(
            lambda query=query: service.list_page(
                authorization,
                generation_id=generation_id,
                query=query,
            ),
            warmups=warmups,
            measurements=measurements,
        )
        for name, query in scenarios.items()
    }
    walks = {
        name: _exact_service_walk(
            service,
            authorization,
            query,
            generation_id=generation_id,
        )
        for name, query in scenarios.items()
    }
    exact = all(
        walk["status"] == "pass"
        and walk["expected_total"] == expected_rows_per_kind
        for walk in walks.values()
    )
    under_budget = all(
        timing["p95_ms"] < SLO_MILLISECONDS
        for timing in timings.values()
    )
    bounded = (
        instrumented.max_rows_fetched_per_query <= page_size + 1
    )
    rss_after = _rss_bytes()
    return {
        "schema_version": "1.0.0",
        "status": (
            "pass"
            if exact and under_budget and bounded
            else "fail"
        ),
        "adapter": {
            "adapter_id": FABRIC_SQL_ADAPTER_ID,
            "selected_production_adapter": FABRIC_SQL_ADAPTER_ID,
            "production": True,
            "production_slo_evidence": True,
            "delta_selected": False,
        },
        "dataset": {
            "expected_rows_per_kind": expected_rows_per_kind,
            "generation_id": generation_id,
            "target_kinds": sorted(scenarios),
        },
        "query_contract": {
            "page_size": page_size,
            "sort": ["priority_score:desc", "exposure_id:asc"],
            "scope_first": True,
        },
        "timings": timings,
        "full_walks": walks,
        "work": {
            "query_count": instrumented.query_count,
            "rows_fetched": instrumented.rows_fetched,
            "max_rows_fetched_per_query": (
                instrumented.max_rows_fetched_per_query
            ),
            "full_table_materializations": 0,
            "delta_fallbacks": 0,
        },
        "memory": {
            "rss_before_bytes": rss_before,
            "rss_after_bytes": rss_after,
            "rss_delta_bytes": max(0, rss_after - rss_before),
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
        },
        "slo": {
            "target_p95_ms": SLO_MILLISECONDS,
            "observed_under_target": under_budget,
            "production_certified": exact and under_budget and bounded,
        },
    }


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        import yaml

        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 - probe records a safe config reason later.
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _endpoint_metadata(config: dict[str, Any]) -> tuple[dict[str, str], str]:
    fabric = config.get("fabric")
    fabric = fabric if isinstance(fabric, dict) else {}
    configured = fabric.get("sql_endpoint")
    configured = configured if isinstance(configured, dict) else {}
    environment = {
        "server": os.environ.get("FABRIC_SQL_SERVER", "").strip(),
        "database": os.environ.get("FABRIC_SQL_DATABASE", "").strip(),
        "schema": os.environ.get("FABRIC_SQL_SCHEMA", "").strip(),
    }
    config_values = {
        "server": str(configured.get("server") or "").strip(),
        "database": str(configured.get("database") or "").strip(),
        "schema": str(configured.get("schema") or "").strip(),
    }
    source = "environment" if environment["server"] or environment["database"] else "config"
    values = environment if source == "environment" else config_values
    values["schema"] = values["schema"] or str(fabric.get("table_schema") or "dbo").strip()
    if not values["server"] and not values["database"]:
        source = "none"
    return values, source


def probe_production_adapter(config_path: Path) -> dict[str, Any]:
    """Return the runtime-owned sanitized readiness result for Fabric SQL."""
    config = _load_yaml(config_path)
    endpoint, endpoint_source = _endpoint_metadata(config)
    try:
        fabric = config.get("fabric")
        fabric = fabric if isinstance(fabric, dict) else {}
        credential = build_credential(
            FabricAuthConfig.from_mapping(fabric.get("auth") or {})
        )
    except Exception:  # noqa: BLE001 - readiness emits only stable reason codes.
        credential = None
    return probe_exposure_readiness(
        endpoint,
        credential,
        endpoint_source=endpoint_source,
    ).to_dict()


def _require_production_reader(config_path: Path) -> Any:
    config = _load_yaml(config_path)
    endpoint, endpoint_source = _endpoint_metadata(config)
    fabric = config.get("fabric")
    fabric = fabric if isinstance(fabric, dict) else {}
    credential = build_credential(
        FabricAuthConfig.from_mapping(fabric.get("auth") or {})
    )
    return require_exposure_ready(
        endpoint,
        credential,
        endpoint_source=endpoint_source,
    )


def _environment_values(name: str) -> list[str]:
    return [
        value.strip()
        for value in os.environ.get(name, "").split(",")
        if value.strip()
    ]


def _emit(report: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
        return
    print(json.dumps(report, indent=2, sort_keys=True))


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate deterministic Exposure scale data, benchmark the local "
            "correctness harness, or probe the selected Fabric SQL adapter."
        )
    )
    parser.add_argument("--rows", type=_positive_int, default=DEFAULT_ROWS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--page-size", type=int, choices=(25, 50, 100), default=50)
    parser.add_argument("--warmups", type=_positive_int, default=DEFAULT_WARMUPS)
    parser.add_argument(
        "--measurements",
        type=_positive_int,
        default=DEFAULT_MEASUREMENTS,
    )
    parser.add_argument("--config", default="fabric.config.yaml")
    parser.add_argument(
        "--tenant-id",
        default=os.environ.get("EXPOSURE_BENCHMARK_TENANT_ID", ""),
    )
    parser.add_argument(
        "--connection-id",
        action="append",
        default=_environment_values("EXPOSURE_BENCHMARK_CONNECTION_IDS"),
    )
    parser.add_argument(
        "--subscription-id",
        action="append",
        default=_environment_values("EXPOSURE_BENCHMARK_SUBSCRIPTION_IDS"),
    )
    parser.add_argument(
        "--generation-id",
        default=os.environ.get("EXPOSURE_BENCHMARK_GENERATION_ID", ""),
    )
    parser.add_argument("--probe-production-adapter", action="store_true")
    readiness = parser.add_mutually_exclusive_group()
    readiness.add_argument(
        "--allow-not-ready",
        action="store_true",
        help="Return zero after an honest not-ready probe.",
    )
    readiness.add_argument(
        "--require-ready",
        action="store_true",
        help="Return nonzero when any production prerequisite is absent.",
    )
    parser.add_argument("--json", action="store_true", help="Emit compact JSON.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = REPO_ROOT / config_path

    if args.probe_production_adapter or args.require_ready or args.allow_not_ready:
        readiness_report = probe_production_adapter(config_path)
        if args.probe_production_adapter or not readiness_report["ready"]:
            _emit(readiness_report, as_json=args.json)
        if args.require_ready and not readiness_report["ready"]:
            return 2
        if args.probe_production_adapter:
            return 0
        if args.require_ready:
            tenant_id = str(args.tenant_id or "").strip()
            connection_ids = tuple(args.connection_id or ())
            subscription_ids = tuple(args.subscription_id or ())
            generation_id = str(args.generation_id or "").strip()
            missing = [
                name
                for name, present in (
                    ("tenant_id", bool(tenant_id)),
                    ("connection_ids", bool(connection_ids)),
                    ("subscription_ids", bool(subscription_ids)),
                    ("generation_id", bool(generation_id)),
                )
                if not present
            ]
            if missing:
                _emit(
                    {
                        "schema_version": "1.0.0",
                        "status": "not_ready",
                        "adapter": PRODUCTION_ADAPTER_ID,
                        "reason_code": "benchmark_scope_missing",
                        "missing": missing,
                        "sanitized": True,
                    },
                    as_json=args.json,
                )
                return 3
            production_report = run_fabric_sql_benchmark(
                _require_production_reader(config_path),
                ExposureAuthorization(
                    subject="exposure-benchmark",
                    tenant_id=tenant_id,
                    connection_ids=connection_ids,
                    scope={
                        "subscription": subscription_ids,
                        "subscription_connection": connection_ids,
                    },
                ),
                generation_id=generation_id,
                expected_rows_per_kind=args.rows,
                page_size=args.page_size,
                warmups=args.warmups,
                measurements=args.measurements,
            )
            production_report["readiness"] = readiness_report
            _emit(production_report, as_json=args.json)
            return 0 if production_report["status"] == "pass" else 4

    report = run_local_benchmark(
        row_count=args.rows,
        seed=args.seed,
        page_size=args.page_size,
        warmups=args.warmups,
        measurements=args.measurements,
    )
    _emit(report, as_json=args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
