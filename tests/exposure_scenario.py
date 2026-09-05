"""Shared deterministic Phase 03.1 Exposure scenario helpers.

Wave 0 owns evidence and behavior contracts only. Production imports stay in
the skipped behavior tests until the plan named in each skip reason implements
the corresponding surface.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

SCENARIO_PATH = Path(__file__).parent / "fixtures" / "exposure_authoritative.json"
EXPECTED_SCHEMA_VERSION = "1.0.0"
EXPECTED_GENERATION_ID = "exposure-generation-0001"
EXPECTED_TIED_PRIORITY_ROWS = 101


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def scenario_fingerprint(scenario: dict[str, Any]) -> str:
    """Return a drift-sensitive SHA-256 fingerprint without self-reference."""
    payload = deepcopy(scenario)
    payload.pop("fixture_fingerprint", None)
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def stable_identity(namespace: str, *parts: object) -> str:
    """Create a process-independent identity from canonical, case-folded parts."""
    normalized = [str(part).strip().casefold() for part in parts]
    digest = hashlib.sha256(_canonical_json(normalized).encode("utf-8")).hexdigest()
    return f"{namespace}:{digest}"


def fixture_identity(scenario: dict[str, Any], case: str) -> str:
    return str(scenario["identity_cases"][case]["exposure_id"])


def tied_priority_rows(scenario: dict[str, Any]) -> list[dict[str, Any]]:
    """Expand the compact fixture contract into 101 deterministic tied rows."""
    spec = scenario["cursor_case"]
    subscriptions = scenario["scope"]["authorized_subscriptions"]
    generation_id = scenario["read_model_generation_id"]
    rows: list[dict[str, Any]] = []
    for index in range(int(spec["row_count"])):
        ordinal = index + 1
        subscription_id = str(subscriptions[index % len(subscriptions)])
        target_id = (
            f"/subscriptions/{subscription_id}/resourceGroups/rg-scale/providers/"
            f"Microsoft.Compute/virtualMachines/vm-{ordinal:06d}"
        )
        weakness_id = f"CVE-2026-{5000 + (index % 17):04d}"
        rows.append(
            {
                "exposure_id": stable_identity(
                    "exposure",
                    scenario["scope"]["tenant_id"],
                    target_id,
                    "server",
                    weakness_id,
                ),
                "read_model_generation_id": generation_id,
                "subscription_id": subscription_id,
                "target_id": target_id,
                "target_kind": "server",
                "weakness_id": weakness_id,
                "source_family": "aum" if index % 2 == 0 else "defender",
                "priority_score": int(spec["priority_score"]),
            }
        )
    return sorted(rows, key=lambda row: (-row["priority_score"], row["exposure_id"]))


def validate_exposure_scenario(scenario: dict[str, Any]) -> None:
    """Validate Wave 0's locked scenario shape and safety invariants."""
    if scenario.get("fixture_schema_version") != EXPECTED_SCHEMA_VERSION:
        raise ValueError("unexpected fixture_schema_version")
    if scenario.get("read_model_generation_id") != EXPECTED_GENERATION_ID:
        raise ValueError("unexpected read_model_generation_id")
    if scenario.get("fixture_fingerprint") != scenario_fingerprint(scenario):
        raise ValueError("fixture_fingerprint does not match canonical fixture content")

    scope = scenario["scope"]
    authorized_subscriptions = set(scope["authorized_subscriptions"])
    unauthorized_subscriptions = set(scope["unauthorized_subscriptions"])
    if len(authorized_subscriptions) != 2:
        raise ValueError("fixture must contain exactly two authorized subscriptions")
    if len(unauthorized_subscriptions) != 1:
        raise ValueError("fixture must contain exactly one unauthorized subscription")
    if authorized_subscriptions & unauthorized_subscriptions:
        raise ValueError("authorized and unauthorized subscriptions overlap")

    authorized_connections = [
        item for item in scope["connections"] if item.get("authorized") is True
    ]
    if len(authorized_connections) != 2:
        raise ValueError("fixture must contain exactly two authorized connections")
    if {
        item["subscription_id"] for item in authorized_connections
    } != authorized_subscriptions:
        raise ValueError("authorized connections do not match authorized subscriptions")

    identity_cases = scenario["identity_cases"]
    for required_case in ("aum_only", "defender_only", "merged", "unauthorized"):
        if required_case not in identity_cases:
            raise ValueError(f"missing identity case: {required_case}")
    if set(identity_cases["merged"]["source_families"]) != {"aum", "defender"}:
        raise ValueError("merged identity must preserve AUM and Defender attribution")

    source_states = {item["state"] for item in scenario["source_partitions"]}
    required_source_states = {
        "complete",
        "healthy-empty",
        "failed-with-lkg",
        "failed-without-lkg",
    }
    if not required_source_states <= source_states:
        raise ValueError("source partitions do not cover every Wave 0 state")
    for partition in scenario["source_partitions"]:
        if partition["state"] == "failed-with-lkg" and (
            not partition["carried_forward"] or not partition["effective_generation_id"]
        ):
            raise ValueError("failed-with-lkg must retain an effective generation")
        if partition["state"] == "failed-without-lkg" and (
            partition["carried_forward"]
            or partition["effective_generation_id"] is not None
        ):
            raise ValueError("failed-without-lkg cannot expose an effective generation")

    temporal_cases = {item["case_id"]: item for item in scenario["temporal_cases"]}
    required_temporal_cases = {
        "missing-installed-reintroduced",
        "out-of-order-and-same-time-tie",
        "unknown-first-detection",
    }
    if set(temporal_cases) != required_temporal_cases:
        raise ValueError("temporal matrix is incomplete")
    temporal_events = {
        event["event"]
        for case in temporal_cases.values()
        for event in case["observations"]
    }
    if not {"missing", "installed", "resolved", "reintroduced"} <= temporal_events:
        raise ValueError("temporal matrix lacks required event states")

    container_cases = scenario["container_cases"]
    digests = container_cases["digests"]
    observed = [
        item for item in digests if item["workload_state"] == "observed-exact-digest"
    ]
    unknown = [item for item in digests if item["workload_state"] == "unknown"]
    if len(observed) != 1 or len(unknown) != 1:
        raise ValueError("container fixture needs one exact and one unknown workload")
    movement = container_cases["tag_movement"]
    if movement["from_digest"] == movement["to_digest"]:
        raise ValueError("tag movement must cross immutable digests")
    digest_values = {item["digest"] for item in digests}
    if {movement["from_digest"], movement["to_digest"]} != digest_values:
        raise ValueError("tag movement references an unknown digest")

    enrichment_states = {item["state"] for item in scenario["enrichment_cases"]}
    if enrichment_states != {"complete", "stale", "unavailable"}:
        raise ValueError("enrichment fixture must cover complete, stale, and unavailable")

    tied_rows = tied_priority_rows(scenario)
    if len(tied_rows) != EXPECTED_TIED_PRIORITY_ROWS:
        raise ValueError("cursor fixture must generate exactly 101 rows")
    tied_ids = [row["exposure_id"] for row in tied_rows]
    if len(tied_ids) != len(set(tied_ids)):
        raise ValueError("cursor fixture generated duplicate exposure identities")


def load_exposure_scenario() -> dict[str, Any]:
    scenario = json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))
    validate_exposure_scenario(scenario)
    return scenario


__all__ = [
    "EXPECTED_GENERATION_ID",
    "EXPECTED_SCHEMA_VERSION",
    "EXPECTED_TIED_PRIORITY_ROWS",
    "SCENARIO_PATH",
    "fixture_identity",
    "load_exposure_scenario",
    "scenario_fingerprint",
    "stable_identity",
    "tied_priority_rows",
    "validate_exposure_scenario",
]
