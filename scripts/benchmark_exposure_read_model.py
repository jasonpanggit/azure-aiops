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
import importlib
import json
import math
import os
import re
import sys
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

PRODUCTION_ADAPTER_ID = "fabric_sql"
LOCAL_ADAPTER_ID = "deterministic_memory"
REQUIRED_DRIVER = "ODBC Driver 18 for SQL Server"
DEFAULT_ROWS = 100_000
DEFAULT_SEED = 31_001
DEFAULT_WARMUPS = 5
DEFAULT_MEASUREMENTS = 20
DEFAULT_PAGE_SIZE = 50
SLO_MILLISECONDS = 2_000.0
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9_]+$")

REQUIRED_GOLD_SCHEMA: dict[str, frozenset[str]] = {
    "gold_exposure_read_model": frozenset(
        {
            "exposure_id",
            "read_model_generation_id",
            "tenant_id",
            "subscription_id",
            "connection_id",
            "target_id",
            "target_kind",
            "source_family",
            "priority_score",
        }
    ),
    "gold_exposure_summary": frozenset(
        {
            "read_model_generation_id",
            "tenant_id",
            "subscription_id",
            "total_count",
        }
    ),
}


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


@dataclass(frozen=True, slots=True)
class ProbeCheck:
    check_id: str
    status: str
    reason_code: str
    detail: dict[str, Any]


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
    for _ in range(warmups):
        operation()
    samples_ms: list[float] = []
    for _ in range(measurements):
        started = time.perf_counter_ns()
        operation()
        elapsed_ns = time.perf_counter_ns() - started
        samples_ms.append(elapsed_ns / 1_000_000)
    return {
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
    return {
        "schema_version": "1.0.0",
        "status": "pass",
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
            "fingerprint": _stable_digest(*(row.exposure_id for row in rows)),
        },
        "query_contract": {
            "page_size": page_size,
            "sort": ["priority_score:desc", "exposure_id:asc"],
            "scope_first": True,
        },
        "timings": timings,
        "full_walk": walk,
        "slo": {
            "target_p95_ms": SLO_MILLISECONDS,
            "observed_filtered_first_page_p95_ms": filtered_p95,
            "observed_under_target": filtered_p95 <= SLO_MILLISECONDS,
            "production_certified": False,
            "reason_code": "local_adapter_is_not_production_slo_evidence",
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


def _check(
    check_id: str,
    status: str,
    reason_code: str,
    **detail: Any,
) -> ProbeCheck:
    return ProbeCheck(
        check_id=check_id,
        status=status,
        reason_code=reason_code,
        detail=detail,
    )


def probe_production_adapter(config_path: Path) -> dict[str, Any]:
    """Return a sanitized, exhaustive readiness report for Fabric SQL."""
    config = _load_yaml(config_path)
    endpoint, endpoint_source = _endpoint_metadata(config)
    checks: list[ProbeCheck] = []
    server = endpoint["server"]
    database = endpoint["database"]
    schema = endpoint["schema"]
    endpoint_valid = (
        bool(server)
        and bool(database)
        and bool(schema)
        and bool(_SAFE_IDENTIFIER.fullmatch(schema))
    )
    checks.append(
        _check(
            "lakehouse_sql_endpoint_metadata",
            "ready" if endpoint_valid else "not_ready",
            "ready" if endpoint_valid else "fabric_sql_endpoint_metadata_missing_or_invalid",
            configured=endpoint_valid,
            source=endpoint_source,
        )
    )

    pyodbc_module: Any | None = None
    try:
        pyodbc_module = importlib.import_module("pyodbc")
    except Exception:  # noqa: BLE001 - no package install or raw error disclosure.
        pyodbc_module = None
    checks.append(
        _check(
            "pyodbc_import",
            "ready" if pyodbc_module is not None else "not_ready",
            "ready" if pyodbc_module is not None else "pyodbc_not_importable",
            importable=pyodbc_module is not None,
        )
    )

    registered_drivers: list[str] = []
    if pyodbc_module is not None:
        try:
            registered_drivers = [str(item) for item in pyodbc_module.drivers()]
        except Exception:  # noqa: BLE001 - safe reason code only.
            registered_drivers = []
    driver_ready = REQUIRED_DRIVER in registered_drivers
    checks.append(
        _check(
            "microsoft_odbc_driver_18",
            "ready" if driver_ready else "not_ready",
            "ready" if driver_ready else "odbc_driver_18_not_registered",
            registered=driver_ready,
            registered_driver_count=len(registered_drivers),
        )
    )

    fabric = config.get("fabric")
    fabric = fabric if isinstance(fabric, dict) else {}
    credential: Any | None = None
    token_ready = False
    token_blockers = not endpoint_valid or pyodbc_module is None or not driver_ready
    if not token_blockers:
        try:
            from fabric.auth import FabricAuthConfig, build_credential
            from fabric.sql_endpoint import SQL_SCOPE

            credential = build_credential(FabricAuthConfig.from_mapping(fabric.get("auth") or {}))
            token = credential.get_token(SQL_SCOPE)
            token_ready = bool(getattr(token, "token", ""))
        except Exception:  # noqa: BLE001 - never expose credential/provider details.
            credential = None
            token_ready = False
    checks.append(
        _check(
            "entra_token",
            "ready" if token_ready else ("blocked" if token_blockers else "not_ready"),
            (
                "ready"
                if token_ready
                else (
                    "entra_token_check_blocked_by_local_prerequisite"
                    if token_blockers
                    else "entra_token_unavailable"
                )
            ),
            acquired=token_ready,
        )
    )

    reader: Any | None = None
    connectivity_ready = False
    connectivity_blocked = not (endpoint_valid and pyodbc_module and driver_ready and token_ready)
    if not connectivity_blocked:
        try:
            from fabric.sql_endpoint import FabricSqlReader, SqlEndpoint

            reader = FabricSqlReader(
                SqlEndpoint(server=server, database=database, schema=schema),
                credential,
                driver=REQUIRED_DRIVER,
            )
            connectivity_ready = bool(reader.query("SELECT 1 AS probe"))
        except Exception:  # noqa: BLE001 - sanitized readiness only.
            reader = None
            connectivity_ready = False
    checks.append(
        _check(
            "token_connectivity",
            (
                "ready"
                if connectivity_ready
                else ("blocked" if connectivity_blocked else "not_ready")
            ),
            (
                "ready"
                if connectivity_ready
                else (
                    "fabric_sql_connectivity_blocked_by_local_prerequisite"
                    if connectivity_blocked
                    else "fabric_sql_connectivity_failed"
                )
            ),
            connected=connectivity_ready,
        )
    )

    schema_ready = False
    missing_tables: list[str] = []
    missing_columns: dict[str, list[str]] = {}
    if connectivity_ready and reader is not None:
        try:
            for table, required_columns in REQUIRED_GOLD_SCHEMA.items():
                if not reader.table_exists(table):
                    missing_tables.append(table)
                    continue
                available = reader.column_names(table)
                absent = sorted(required_columns - available)
                if absent:
                    missing_columns[table] = absent
            schema_ready = not missing_tables and not missing_columns
        except Exception:  # noqa: BLE001 - report safe schema reason only.
            schema_ready = False
    checks.append(
        _check(
            "required_gold_schema",
            "ready" if schema_ready else ("blocked" if not connectivity_ready else "not_ready"),
            (
                "ready"
                if schema_ready
                else (
                    "gold_schema_check_blocked_by_connectivity"
                    if not connectivity_ready
                    else "required_gold_schema_missing"
                )
            ),
            missing_tables=missing_tables,
            missing_columns=missing_columns,
            required_tables=sorted(REQUIRED_GOLD_SCHEMA),
            required_columns={
                table: sorted(columns)
                for table, columns in sorted(REQUIRED_GOLD_SCHEMA.items())
            },
        )
    )

    bounded_query_ready = False
    if schema_ready and reader is not None:
        try:
            qualified = f"[{schema}].[gold_exposure_read_model]"
            probe_generation = "__readiness_probe__"
            probe_subscription = "00000000-0000-0000-0000-000000000000"
            reader.query(
                f"SELECT COUNT_BIG(1) AS total_count FROM {qualified} "
                "WHERE [read_model_generation_id] = ? AND [subscription_id] = ?",
                (probe_generation, probe_subscription),
            )
            reader.query(
                "SELECT TOP (1) [exposure_id], [priority_score] "
                f"FROM {qualified} "
                "WHERE [read_model_generation_id] = ? AND [subscription_id] = ? "
                "AND ([priority_score] < ? OR "
                "([priority_score] = ? AND [exposure_id] > ?)) "
                "ORDER BY [priority_score] DESC, [exposure_id] ASC",
                (probe_generation, probe_subscription, 0, 0, ""),
            )
            bounded_query_ready = True
        except Exception:  # noqa: BLE001 - report safe capability reason only.
            bounded_query_ready = False
    checks.append(
        _check(
            "bound_count_and_page_query",
            "ready" if bounded_query_ready else ("blocked" if not schema_ready else "not_ready"),
            (
                "ready"
                if bounded_query_ready
                else (
                    "bound_query_check_blocked_by_schema"
                    if not schema_ready
                    else "bound_count_or_page_query_failed"
                )
            ),
            parameters_bound=True,
            page_bounded=True,
        )
    )

    ready = all(item.status == "ready" for item in checks)
    return {
        "schema_version": "1.0.0",
        "probe": "production_exposure_adapter",
        "selected_production_adapter": PRODUCTION_ADAPTER_ID,
        "ready": ready,
        "status": "ready" if ready else "not_ready",
        "fallback": {
            "adapter_id": "delta",
            "selected": False,
            "production_scale_certified": False,
        },
        "checks": [asdict(item) for item in checks],
        "reason_codes": [
            item.reason_code for item in checks if item.status != "ready"
        ],
        "sanitized": True,
    }


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
        report = probe_production_adapter(config_path)
        _emit(report, as_json=args.json)
        if args.require_ready and not report["ready"]:
            return 2
        if args.probe_production_adapter:
            return 0
        if args.require_ready:
            blocked = {
                "schema_version": "1.0.0",
                "status": "not_ready",
                "adapter": PRODUCTION_ADAPTER_ID,
                "reason_code": "production_benchmark_wiring_pending_plan_03.1_13",
                "sanitized": True,
            }
            _emit(blocked, as_json=args.json)
            return 3

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
