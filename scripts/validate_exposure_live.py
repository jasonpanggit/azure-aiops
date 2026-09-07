#!/usr/bin/env python3
"""Evaluate the redacted live Exposure release evidence contract.

The validator intentionally consumes only aggregate/status metadata. It rejects
credential-like fields and raw payloads before producing a report so the same
command is safe to run in a managed-identity Container Apps Job and to retain
as release evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

REQUIRED_EXECUTABLE_ACTION_IDS = frozenset(
    {
        "controlled-patch-recovery",
        "defender-enable-servers-plan-p1",
        "defender-enable-storage-plan-v2",
    }
)
REQUIRED_UI_SUITES = (
    "shared_primitives",
    "overview",
    "cve",
    "kb",
    "risk_dialog",
)
FORBIDDEN_EVIDENCE_KEYS = frozenset(
    {
        "access_token",
        "authorization",
        "client_secret",
        "credential",
        "cursor_key",
        "password",
        "raw_payload",
        "secret",
        "secret_value",
        "token",
    }
)
PHASE4_BLOCKER = (
    "exact_supported_defender_digest_to_container_insights_workload_round_trip"
)


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _status_pass(value: object) -> bool:
    return str(_mapping(value).get("status") or "").strip().casefold() == "pass"


def _scan_unsafe_keys(value: object, path: tuple[str, ...] = ()) -> None:
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            key = str(raw_key).strip().casefold()
            if key in FORBIDDEN_EVIDENCE_KEYS or key.endswith("_secret"):
                dotted = ".".join((*path, key))
                raise ValueError(f"unsafe evidence field: {dotted}")
            _scan_unsafe_keys(child, (*path, key))
    elif isinstance(value, list | tuple):
        for index, child in enumerate(value):
            _scan_unsafe_keys(child, (*path, str(index)))


def _check(name: str, passed: bool, reason: str) -> dict[str, object]:
    return {
        "name": name,
        "status": "pass" if passed else "blocked",
        "reason_code": "" if passed else reason,
    }


def evaluate_live_evidence(evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Return a fail-closed, sanitized release decision for live evidence."""
    _scan_unsafe_keys(evidence)

    binding = _mapping(evidence.get("binding"))
    sources = _mapping(evidence.get("sources"))
    aum = _mapping(sources.get("aum"))
    defender = _mapping(sources.get("defender_digest"))
    workloads = _mapping(sources.get("container_insights"))
    fabric_sql = _mapping(sources.get("fabric_sql"))
    persistence = _mapping(evidence.get("persistence"))
    ontology = _mapping(evidence.get("ontology"))
    scope = _mapping(evidence.get("scope_identity"))
    cursor = _mapping(evidence.get("cursor"))
    governance = _mapping(evidence.get("governance"))
    telemetry = _mapping(evidence.get("telemetry"))
    alerts = _mapping(evidence.get("alerts"))
    benchmark = _mapping(evidence.get("benchmark"))
    benchmark_adapter = _mapping(benchmark.get("adapter"))
    benchmark_dataset = _mapping(benchmark.get("dataset"))
    benchmark_walk = _mapping(benchmark.get("full_walk"))
    benchmark_slo = _mapping(benchmark.get("slo"))
    phase4 = _mapping(evidence.get("phase4"))
    traversal = _mapping(phase4.get("digest_to_workload"))
    ui_suites = _mapping(evidence.get("ui_suites"))

    generation = str(binding.get("generation_id") or "")
    config_digest = str(binding.get("config_digest") or "")
    active_kid = str(cursor.get("active_kid") or "")
    previous_kid = str(cursor.get("previous_kid") or "")
    action_ids = frozenset(
        str(value) for value in governance.get("executable_action_ids") or ()
    )
    target_counts = _mapping(benchmark_dataset.get("target_kind_counts"))
    benchmark_rows = int(benchmark_dataset.get("row_count") or 0)
    represented = int(traversal.get("represented") or 0)
    total = int(traversal.get("total") or 0)

    exact_phase4 = (
        _status_pass(phase4)
        and str(traversal.get("evidence_kind") or "") == "exact_digest"
        and str(traversal.get("source") or "") == "container_insights"
        and traversal.get("supported") is True
        and traversal.get("round_trip") is True
        and represented > 0
        and total >= represented
    )
    checks = [
        _check(
            "release_binding",
            bool(binding.get("commit"))
            and config_digest.startswith("sha256:")
            and bool(generation),
            "release_binding_missing",
        ),
        _check("aum_source", _status_pass(aum), "aum_source_not_ready"),
        _check(
            "defender_exact_digest",
            _status_pass(defender)
            and defender.get("evidence_kind") == "exact_digest",
            "defender_exact_digest_missing",
        ),
        _check(
            "supported_container_insights",
            _status_pass(workloads)
            and workloads.get("supported") is True
            and workloads.get("deployment_match") == "exact",
            "supported_container_insights_missing",
        ),
        _check(
            "fabric_sql",
            _status_pass(fabric_sql)
            and fabric_sql.get("adapter") == "fabric_sql"
            and fabric_sql.get("driver") == "ODBC Driver 18 for SQL Server",
            "fabric_sql_not_ready",
        ),
        _check(
            "persistence_ontology_round_trip",
            _status_pass(persistence)
            and _status_pass(ontology)
            and persistence.get("generation_id") == generation
            and ontology.get("generation_id") == generation,
            "generation_round_trip_failed",
        ),
        _check(
            "api_web_scope_identity",
            _status_pass(scope)
            and bool(scope.get("api_scope_hash"))
            and scope.get("api_scope_hash") == scope.get("web_scope_hash"),
            "scope_identity_mismatch",
        ),
        _check(
            "ui_release_suites",
            all(ui_suites.get(name) == "pass" for name in REQUIRED_UI_SUITES),
            "ui_release_suite_missing",
        ),
        _check(
            "cursor_rotation_expiry",
            _status_pass(cursor)
            and cursor.get("active_ref") == "exposure-cursor-active"
            and cursor.get("previous_ref") == "exposure-cursor-previous"
            and bool(active_kid)
            and bool(previous_kid)
            and active_kid != previous_kid
            and cursor.get("ttl_minutes") == 15
            and cursor.get("overlap_minutes") == 30
            and cursor.get("rotation_verified") is True
            and cursor.get("expiry_verified") is True
            and cursor.get("secret_values_exposed") is False,
            "cursor_rotation_or_expiry_unproven",
        ),
        _check(
            "governed_container_handoff",
            _status_pass(governance)
            and action_ids == REQUIRED_EXECUTABLE_ACTION_IDS
            and governance.get("container_handoff")
            in {"review_handoff", "no_safe_action"}
            and governance.get("container_operation_calls") == 0,
            "container_governance_failed",
        ),
        _check(
            "telemetry_alerts",
            _status_pass(telemetry)
            and _status_pass(alerts)
            and alerts.get("enabled") is True
            and alerts.get("one_cycle") is True,
            "telemetry_or_alerts_missing",
        ),
        _check(
            "qualified_100k_benchmark",
            _status_pass(benchmark)
            and benchmark_adapter.get("adapter_id") == "fabric_sql"
            and benchmark_adapter.get("production_slo_evidence") is True
            and benchmark_adapter.get("delta_selected") is False
            and benchmark_rows >= 100_000
            and int(target_counts.get("server") or 0) > 0
            and int(target_counts.get("container_image") or 0) > 0
            and benchmark_walk.get("duplicate_count") == 0
            and benchmark_walk.get("omission_count") == 0
            and benchmark_slo.get("observed_under_target") is True
            and benchmark_slo.get("production_certified") is True,
            "qualified_100k_benchmark_failed",
        ),
        _check("phase4_exact_path", exact_phase4, PHASE4_BLOCKER),
    ]

    missing = [
        str(check["reason_code"])
        for check in checks
        if check["status"] != "pass"
    ]
    # The exact live traversal is the canonical blocker name, even when the
    # source reported a typed unknown rather than an outright failure.
    if not exact_phase4:
        missing = [
            reason for reason in missing if reason != PHASE4_BLOCKER
        ] + [PHASE4_BLOCKER]

    return {
        "schema_version": "1.0.0",
        "status": "pass" if not missing else "blocked",
        "phase4_ready": not missing and exact_phase4,
        "checks": checks,
        "missing_evidence": missing,
        "binding": {
            "commit": str(binding.get("commit") or ""),
            "config_digest": config_digest,
            "generation_id": generation,
        },
        "sanitized": True,
    }


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("live evidence must be a JSON object")
    return value


def _runtime_evidence(config_path: Path) -> dict[str, Any]:
    """Collect only locally observable managed-runtime facts.

    Source, UI, telemetry, and exact ontology evidence require a retained
    release manifest. Missing facts remain blocked rather than inferred.
    """
    from scripts.benchmark_exposure_read_model import probe_production_adapter

    config_bytes = config_path.read_bytes()
    readiness = probe_production_adapter(config_path)
    ready = readiness.get("ready") is True
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        commit = os.environ.get("AIOPS_RELEASE_COMMIT", "").strip()
    return {
        "schema_version": "1.0.0",
        "binding": {
            "commit": commit,
            "config_digest": "sha256:" + hashlib.sha256(config_bytes).hexdigest(),
            "generation_id": os.environ.get(
                "AIOPS_EXPOSURE_READ_GENERATION_ID", ""
            ).strip(),
        },
        "sources": {
            "fabric_sql": {
                "status": "pass" if ready else "blocked",
                "adapter": readiness.get("adapter", ""),
                "driver": "ODBC Driver 18 for SQL Server"
                if readiness.get("driver_ready")
                else "",
            }
        },
        "cursor": {
            "status": "pass"
            if os.environ.get("EXPOSURE_CURSOR_ACTIVE_KEY")
            and os.environ.get("EXPOSURE_CURSOR_PREVIOUS_KEY")
            else "blocked",
            "active_ref": "exposure-cursor-active",
            "previous_ref": "exposure-cursor-previous",
            "active_kid": os.environ.get("EXPOSURE_CURSOR_ACTIVE_KID", ""),
            "previous_kid": os.environ.get("EXPOSURE_CURSOR_PREVIOUS_KID", ""),
            "ttl_minutes": 15,
            "overlap_minutes": 30,
            "rotation_verified": False,
            "expiry_verified": False,
            "secret_values_exposed": False,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate sanitized live Exposure release evidence."
    )
    parser.add_argument(
        "--evidence",
        default=os.environ.get("AIOPS_EXPOSURE_LIVE_EVIDENCE_FILE", ""),
        help="Sanitized JSON evidence manifest. Runtime-only checks are used when absent.",
    )
    parser.add_argument(
        "--config",
        default=os.environ.get("AIOPS_FABRIC_CONFIG", "fabric.config.yaml"),
    )
    parser.add_argument("--require-all", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = (
        _load_json(Path(args.evidence))
        if args.evidence
        else _runtime_evidence(Path(args.config))
    )
    report = evaluate_live_evidence(evidence)
    print(
        json.dumps(
            report,
            sort_keys=True,
            separators=(",", ":") if args.json else None,
            indent=None if args.json else 2,
        )
    )
    return 0 if report["status"] == "pass" or not args.require_all else 2


if __name__ == "__main__":
    raise SystemExit(main())
