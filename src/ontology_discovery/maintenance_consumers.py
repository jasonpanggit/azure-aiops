"""Independent consumer observations, finite budgets and cost contracts.

Offline code never probes anything: it only *aggregates* separately captured
observations.  A single local manifest or repeated booleans cannot satisfy five
families; missing observers close the maintenance path.
"""

from __future__ import annotations

import fcntl
import json
import math
import os
import tempfile
import uuid
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from ontology_discovery.maintenance_release import MaintenanceDenied

CONSUMER_FAMILIES = ("api", "fabric", "agent", "export", "semantic")
STAGES = frozenset({"staged", "active", "restore"})
MAX_OBSERVATION_AGE = timedelta(minutes=15)

# Inherited Phase 13/14 budgets (never raised here).
MAX_CHANGED_ENTITIES = 50
MAX_PAIRS = 200
MAX_EVIDENCE_RECORDS = 40
MAX_INPUT_TOKENS = 8_000
NORMAL_OUTPUT_TOKENS = 1_200
HARD_OUTPUT_TOKENS = 2_000
MAX_RETRIES = 2
MAX_REPAIRS = 2
ATTEMPT_SECONDS = 60
P95_SECONDS = 30.0


@dataclass(frozen=True)
class ConsumerObservation:
    family: str
    observer_id: str
    source_id: str
    capture_id: str
    result_hash: str
    generation_id: str
    stage: str
    definition_fingerprint: str
    product_fingerprint: str  # empty for staged schema/reader compatibility
    observed_at: datetime
    status: str


class ConsumerObservationPort(Protocol):
    def observe(
        self, family: str, generation_id: str, stage: str
    ) -> ConsumerObservation | None: ...


def evaluate_observations(
    observations: Sequence[ConsumerObservation],
    *,
    generation_id: str,
    stage: str,
    definition_fingerprint: str,
    now: datetime,
    max_age: timedelta = MAX_OBSERVATION_AGE,
    not_before: datetime | None = None,
) -> dict[str, bool]:
    """Return per-family pass booleans or raise a closed denial."""

    if stage not in STAGES:
        raise MaintenanceDenied("consumer_stage_unknown")
    by_family: dict[str, ConsumerObservation] = {}
    for item in observations:
        if item.family in by_family or item.family not in CONSUMER_FAMILIES:
            raise MaintenanceDenied("consumer_observation_duplicate_or_unknown")
        by_family[item.family] = item
    if set(by_family) != set(CONSUMER_FAMILIES):
        raise MaintenanceDenied("consumer_observation_missing")
    for attr in ("observer_id", "source_id", "capture_id", "result_hash"):
        values = [getattr(by_family[f], attr) for f in CONSUMER_FAMILIES]
        if any(not v for v in values) or len(set(values)) != len(values):
            raise MaintenanceDenied(f"consumer_observation_not_independent:{attr}")
    out: dict[str, bool] = {}
    for family in CONSUMER_FAMILIES:
        item = by_family[family]
        if (
            item.generation_id != generation_id
            or item.stage != stage
            or item.definition_fingerprint != definition_fingerprint
        ):
            raise MaintenanceDenied("consumer_observation_lineage_mismatch")
        if item.observed_at.tzinfo is None:
            raise MaintenanceDenied("consumer_observation_time_invalid")
        age = now - item.observed_at
        if age < timedelta(0) or age > max_age:
            raise MaintenanceDenied("consumer_observation_stale")
        if stage != "staged":
            if not item.product_fingerprint:
                raise MaintenanceDenied("consumer_product_observation_missing")
            if not_before is not None and item.observed_at < not_before:
                raise MaintenanceDenied("consumer_observation_before_materialization")
        out[family] = item.status == "pass"
    return out


class MaintenanceConsumerCheck:
    """Worker ``consumer_check`` backed by five independent observers only."""

    maintenance_observer = True

    def __init__(
        self,
        *,
        ports: Mapping[str, ConsumerObservationPort],
        definition_fingerprint: Callable[[], str],
        clock: Callable[[], datetime] | None = None,
        not_before: Callable[[str], datetime | None] | None = None,
    ) -> None:
        if set(ports) != set(CONSUMER_FAMILIES):
            raise MaintenanceDenied("consumer_observer_unbound")
        self._ports = dict(ports)
        self._definition = definition_fingerprint
        self._clock = clock or (lambda: datetime.now(UTC))
        self._not_before = not_before

    def __call__(self, stage: str, generation_id: str) -> Mapping[str, bool]:
        mapped = {"staged": "staged", "post": "active", "restore": "restore"}.get(stage)
        if mapped is None:
            raise MaintenanceDenied("consumer_stage_unknown")
        found = []
        for family in CONSUMER_FAMILIES:
            item = self._ports[family].observe(family, generation_id, mapped)
            if item is None:
                raise MaintenanceDenied("consumer_observation_missing")
            found.append(item)
        return evaluate_observations(
            found,
            generation_id=generation_id,
            stage=mapped,
            definition_fingerprint=self._definition(),
            now=self._clock(),
            not_before=(
                self._not_before(generation_id) if self._not_before else None
            ),
        )


# --------------------------------------------------------------------- budget


def p95(samples: Sequence[float]) -> float:
    if not samples:
        raise MaintenanceDenied("evaluation_samples_absent")
    ordered = sorted(samples)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


def check_evaluation_latency_tokens(
    latencies_s: Sequence[float], input_tokens: Sequence[int]
) -> None:
    if p95(latencies_s) >= P95_SECONDS:
        raise MaintenanceDenied("evaluation_p95_latency")
    if p95([float(t) for t in input_tokens]) > MAX_INPUT_TOKENS:
        raise MaintenanceDenied("evaluation_p95_tokens")


def check_batch_caps(
    *, changed_entities: int, pairs: int, evidence_records: int
) -> None:
    if (
        changed_entities > MAX_CHANGED_ENTITIES
        or pairs > MAX_PAIRS
        or evidence_records > MAX_EVIDENCE_RECORDS
    ):
        raise MaintenanceDenied("batch_cap_exceeded")


class BudgetLedger:
    """Durable cumulative usage per run, including failures and repairs."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    @contextmanager
    def _transaction(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path.with_suffix(self._path.suffix + ".lock"), "a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                rows = (
                    json.loads(self._path.read_text(encoding="utf-8"))
                    if self._path.is_file() else {}
                )
                yield rows
                fd, tmp = tempfile.mkstemp(dir=str(self._path.parent))
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as out:
                        json.dump(rows, out, sort_keys=True, allow_nan=False)
                        out.flush()
                        os.fsync(out.fileno())
                    os.replace(tmp, self._path)
                    directory = os.open(self._path.parent, os.O_RDONLY)
                    try:
                        os.fsync(directory)
                    finally:
                        os.close(directory)
                finally:
                    if os.path.exists(tmp):
                        os.unlink(tmp)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    @staticmethod
    def _totals(row: Mapping[str, Any]) -> dict[str, Any]:
        total = dict(row.get("legacy", {}))
        for key in ("attempts", "input_tokens", "output_tokens", "elapsed_ms", "failures"):
            total.setdefault(key, 0)
        if row.get("records") or not row.get("legacy"):
            total.setdefault("charged_cost_usd", 0.0)
        for entry in row.get("records", {}).values():
            total["attempts"] += 1
            for key in ("input_tokens", "output_tokens", "elapsed_ms"):
                total[key] += entry[key]
            total["failures"] += int(entry.get("status") in {"failed", "bound_exceeded"})
            total["charged_cost_usd"] += entry["charged_cost_usd"]
        return total

    def reserve(
        self, run_id: str, *, input_tokens: int, output_tokens: int,
        timeout_seconds: float, pricing: Mapping[str, Any],
        max_cost_usd: float, max_total_seconds: float,
        max_input_tokens: int = MAX_INPUT_TOKENS * 9,
        max_output_tokens: int = HARD_OUTPUT_TOKENS * 9,
    ) -> str:
        """Atomically charge a request upper bound BEFORE transport.

        Unsettled reservations survive crashes. Reservations are deliberately
        non-refundable: actual usage is retained separately for reconciliation.
        This keeps all charged counters monotonic even across partial failures.
        """
        if (
            not run_id or not isinstance(input_tokens, int) or input_tokens < 1
            or not isinstance(output_tokens, int) or output_tokens < 1
            or not math.isfinite(timeout_seconds) or timeout_seconds <= 0
            or not math.isfinite(max_cost_usd) or max_cost_usd <= 0
            or not math.isfinite(max_total_seconds) or max_total_seconds <= 0
        ):
            raise MaintenanceDenied("budget_configuration_invalid")
        if (
            input_tokens > MAX_INPUT_TOKENS or output_tokens > HARD_OUTPUT_TOKENS
            or timeout_seconds > ATTEMPT_SECONDS
        ):
            raise MaintenanceDenied("attempt_bound_exceeded")
        if (
            not isinstance(pricing, Mapping)
            or not isinstance(pricing.get("version"), str)
            or not 1 <= len(pricing["version"]) <= 128
        ):
            raise MaintenanceDenied("cost_unknown")
        if cost_usd({"input_tokens": input_tokens, "output_tokens": output_tokens}, pricing) is None:
            raise MaintenanceDenied("cost_unknown")
        attempt_id = uuid.uuid4().hex
        with self._transaction() as rows:
            row = rows.setdefault(run_id, {"records": {}})
            if "records" not in row:
                row = rows[run_id] = {"legacy": dict(row), "records": {}}
            if row.get("legacy", {}).get("attempts", 0):
                raise MaintenanceDenied("budget_legacy_unqualified")
            if any(entry["status"] == "bound_exceeded" for entry in row["records"].values()):
                raise MaintenanceDenied("attempt_usage_bound_exceeded")
            now = datetime.now(UTC)
            row.setdefault("started_at", now.isoformat())
            wall_elapsed = (now - datetime.fromisoformat(row["started_at"])).total_seconds()
            if wall_elapsed + timeout_seconds > max_total_seconds:
                raise MaintenanceDenied("run_time_cap_exceeded")
            entry = {
                "input_tokens": input_tokens, "output_tokens": output_tokens,
                "elapsed_ms": timeout_seconds * 1000, "status": "reserved",
                "reserved_input_tokens": input_tokens,
                "reserved_output_tokens": output_tokens,
                "caps": {
                    "max_cost_usd": max_cost_usd,
                    "max_total_seconds": max_total_seconds,
                    "max_input_tokens": max_input_tokens,
                    "max_output_tokens": max_output_tokens,
                },
                "pricing": {
                    key: pricing[key] for key in (
                        "version", "input_per_million", "output_per_million",
                    )
                },
                "charged_cost_usd": cost_usd(
                    {"input_tokens": input_tokens, "output_tokens": output_tokens}, pricing,
                ),
            }
            row["records"][attempt_id] = entry
            totals = self._totals(row)
            enforce_run_caps(
                totals, max_total_seconds=max_total_seconds,
                max_cost_usd=max_cost_usd, pricing=pricing,
            )
            if totals["input_tokens"] > max_input_tokens or totals["output_tokens"] > max_output_tokens:
                raise MaintenanceDenied("run_token_cap_exceeded")
        return attempt_id

    def settle(
        self, run_id: str, attempt_id: str, *,
        usage: Mapping[str, Any] | None, elapsed_ms: float, ok: bool,
    ) -> dict[str, Any]:
        with self._transaction() as rows:
            row = rows.get(run_id, {})
            entry = row.get("records", {}).get(attempt_id)
            if entry is None:
                raise MaintenanceDenied("budget_reservation_missing")
            if entry["status"] != "reserved":
                return self._totals(row)  # replay cannot charge twice
            actual = {}
            for key in ("input_tokens", "output_tokens"):
                value = (usage or {}).get(key)
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                    actual[key] = value
                    entry[key] = max(entry[key], value)
            entry["actual_usage"] = actual
            entry["elapsed_ms"] = max(entry["elapsed_ms"], elapsed_ms)
            entry["charged_cost_usd"] = max(
                entry["charged_cost_usd"], cost_usd(
                    {key: entry[key] for key in ("input_tokens", "output_tokens")},
                    entry["pricing"],
                ),
            )
            exceeded = any(
                entry[key] > entry[f"reserved_{key}"]
                for key in ("input_tokens", "output_tokens")
            )
            entry["status"] = "bound_exceeded" if exceeded else ("success" if ok else "failed")
            totals = self._totals(row)
            caps = entry["caps"]
        # Persist the charge even on a provider contract violation; raising
        # inside the transaction would roll it back. Never admit that result.
        if exceeded:
            raise MaintenanceDenied("attempt_usage_bound_exceeded")
        enforce_run_caps(
            totals, max_total_seconds=caps["max_total_seconds"],
            max_cost_usd=caps["max_cost_usd"], pricing=entry["pricing"],
        )
        if (
            totals["input_tokens"] > caps["max_input_tokens"]
            or totals["output_tokens"] > caps["max_output_tokens"]
        ):
            raise MaintenanceDenied("run_token_cap_exceeded")
        return totals

    def record(
        self,
        run_id: str,
        *,
        attempts: int,
        usage_log: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        # Compatibility only: snapshots can never qualify transport admission.
        # Keep the high-water mark rather than replacing durable run counters.
        snapshot = {"attempts": attempts, "input_tokens": 0, "output_tokens": 0,
                    "elapsed_ms": 0.0, "failures": 0}
        for entry in usage_log:
            for key in ("input_tokens", "output_tokens"):
                snapshot[key] += int((entry.get("usage") or {}).get(key, 0))
            snapshot["elapsed_ms"] += float(entry.get("latency_ms", 0))
            snapshot["failures"] += int(not entry.get("ok"))
        with self._transaction() as rows:
            row = rows.setdefault(run_id, {"records": {}})
            if "records" not in row:
                row = rows[run_id] = {"legacy": dict(row), "records": {}}
            legacy = row.setdefault("legacy", {})
            for key, value in snapshot.items():
                legacy[key] = max(legacy.get(key, 0), value)
            return self._totals(row)

    def totals(self, run_id: str) -> dict[str, Any] | None:
        if not self._path.is_file():
            return None
        row = json.loads(self._path.read_text(encoding="utf-8")).get(run_id)
        if row is None:
            return None
        return self._totals(row) if "records" in row else row


def cost_usd(
    totals: Mapping[str, Any], pricing: Mapping[str, Any] | None
) -> float | None:
    """Versioned price input -> cost; missing price is UNKNOWN (None), never 0."""

    if not pricing:
        return None
    try:
        rates = [float(pricing[key]) for key in ("input_per_million", "output_per_million")]
        if any(not math.isfinite(rate) or rate <= 0 for rate in rates):
            return None
        if "charged_cost_usd" in totals:
            charged = float(totals["charged_cost_usd"])
            return charged if math.isfinite(charged) and charged >= 0 else None
        result = totals["input_tokens"] / 1e6 * rates[0] + totals["output_tokens"] / 1e6 * rates[1]
        return result if math.isfinite(result) and result >= 0 else None
    except (KeyError, TypeError, ValueError):
        return None


def enforce_run_caps(
    totals: Mapping[str, Any],
    *,
    max_total_seconds: float,
    max_cost_usd: float | None,
    pricing: Mapping[str, Any] | None,
) -> None:
    attempts_cap = (MAX_RETRIES + 1) * (MAX_REPAIRS + 1)
    if totals["attempts"] > attempts_cap:
        raise MaintenanceDenied("attempt_cap_exceeded")
    if totals["elapsed_ms"] / 1000 > max_total_seconds:
        raise MaintenanceDenied("run_time_cap_exceeded")
    if max_cost_usd is not None:
        cost = cost_usd(totals, pricing)
        if cost is None:
            raise MaintenanceDenied("cost_unknown")
        if cost > max_cost_usd:
            raise MaintenanceDenied("cost_cap_exceeded")


__all__ = [
    "CONSUMER_FAMILIES",
    "BudgetLedger",
    "ConsumerObservation",
    "ConsumerObservationPort",
    "MaintenanceConsumerCheck",
    "check_batch_caps",
    "check_evaluation_latency_tokens",
    "cost_usd",
    "enforce_run_caps",
    "evaluate_observations",
    "p95",
]
