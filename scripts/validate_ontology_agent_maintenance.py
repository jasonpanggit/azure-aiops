"""Read saved maintenance evidence through the EXACT runtime attestation reader.

No Azure/Fabric/model client, credential discovery, signing, collection or rollout.
Production CLI has no trust/key/clock override: only operator-owned runtime config.
Tests inject isolated readers into verify_saved_bundle; not selectable by CLI.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

# Match the project's src-layout without importing production composition/clients.
SOURCE = Path(__file__).resolve().parents[1] / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from ontology_discovery.maintenance_release import (
    PURPOSE_LIVE,
    PURPOSE_OFFLINE,
    MaintenanceConfigError,
    MaintenanceDenied,
    MaintenanceReleaseReader,
    build_production_reader,
    digest,
    verify_prerequisite_corpus,
)
from ontology_discovery.planner_capabilities import NATIVE_DENIAL_REASONS

OPEN_QUESTIONS = [
    {"id": "OQ-1", "status": "DISABLED", "reason": "native_operation_identity_not_established",
     "owners": ["provider_integration_maintainer", "security_owner"],
     "requires": ["public_operation_protocol_version", "unattended_identity_lifecycle",
                  "preview_retention_region_consent", "implemented_qualified_adapter"]},
    {"id": "OQ-2", "status": "DISABLED", "reason": "native_structured_adapter_not_established",
     "owners": ["provider_integration_maintainer", "ontology_steward"],
     "requires": ["supported_bounded_output", "actual_citations_base_diff", "adapter_qualification"]},
    {"id": "OQ-3", "status": "PENDING", "reason": "owned_upstream_acceptance_required",
     "owners": ["phase13_owner", "phase03.7_owner", "phase03.8_owner", "phase11_owner",
                "unified_deployment", "security_owner"],
     "requires": ["exact_corpus_13_count_22", "accepted_plan20_before_plan21_start",
                  "corrected_target_accepted_deployment", "operator_pinned_live_trust"]},
    {"id": "OQ-4", "status": "PENDING", "reason": "exact_live_pair_approval_missing",
     "owners": ["ontology_steward", "security_owner", "fabric_governance_steward"],
     "choice": "Application depends_on Application; description-only schema review",
     "requires": ["independent_declaration_and_appdependencies", "exact_live_pair",
                  "30_day_200_adjudication_quality", "three_independent_signed_approvals"]},
    {"id": "OQ-5", "status": "PENDING", "reason": "target_preservation_recovery_unqualified",
     "owners": ["publisher_maintainer", "unified_deployment", "fabric_governance_steward"],
     "requires": ["complete_captures", "exclusive_writer", "readback_restore",
                  "five_independent_consumers", "both_failure_windows_restart",
                  "separate_exact_migration_authority_if_requested"]},
]


def gate(status: str, *reasons: str) -> dict[str, Any]:
    return {"status": status, "reasons": list(reasons)}


def phase13_corpus_diagnostic(root: Path) -> dict[str, Any]:
    """Inventory exact required plans/evidence without granting acceptance."""
    phase = root / "phases" / "13-autonomous-ontology-discovery-and-fabric-synchronization"

    def status(path: Path) -> str:
        try:
            text = path.read_text(encoding="utf-8")
            if not text.startswith("---\n") or "\n---" not in text[4:]:
                return "unreadable_or_invalid"
            front = yaml.safe_load(text.split("\n---", 1)[0][4:])
            value = front.get("status") if isinstance(front, dict) else None
            return value.strip().casefold() if isinstance(value, str) and value.strip() else "unreadable_or_invalid"
        except (OSError, UnicodeError, yaml.YAMLError):
            return "unreadable_or_invalid"

    required = range(1, 23)
    missing = [
        f"13-{number:02d}-SUMMARY.md" for number in required
        if not (phase / f"13-{number:02d}-SUMMARY.md").is_file()
    ]
    missing_plans = [
        f"13-{number:02d}-PLAN.md" for number in required
        if not (phase / f"13-{number:02d}-PLAN.md").is_file()
    ]
    unfinished = []
    for number in required:
        path = phase / f"13-{number:02d}-SUMMARY.md"
        if path.is_file():
            value = status(path)
            if value not in {"complete", "completed", "passed"}:
                unfinished.append({"path": path.name, "status": value})
    verification = status(phase / "13-VERIFICATION.md")
    return {
        "required": 22,
        "present": 22 - len(missing),
        "missing": missing,
        "missing_plans": missing_plans,
        "unfinished_summaries": unfinished,
        "verification_status": verification,
        "status": "BLOCKED" if missing or missing_plans or unfinished or verification != "passed" else "LOCAL_ONLY",
        "reason": "phase13_count_reconciliation_owned_upstream",
        "authority": "diagnostic_only",
    }


def verify_saved_bundle(
    bundle: Mapping[str, Any], *, mode: str,
    reader: MaintenanceReleaseReader | None,
    config_reason: str = "production_trust_unconfigured",
) -> tuple[dict[str, Any], int]:
    """Read the same configured envelope/control as coordinator and publisher.

    The saved input cannot choose trust, control, current time, artifact root,
    implementation pins, or an alternate release. A request is never authority.
    """
    if mode not in {PURPOSE_OFFLINE, PURPOSE_LIVE}:
        raise ValueError("mode_invalid")
    report: dict[str, Any] = {
        "version": "maintenance-verification/v1",
        "requested_mode": mode,
        "checked_at": datetime.now(UTC).isoformat(),
        "input_digest": digest(bundle),
        "authentication": gate("BLOCKED"),
        "offline": gate("PENDING", "offline_qualification_not_supplied"),
        "native": gate("UNSUPPORTED", *NATIVE_DENIAL_REASONS, "native_adapter_unimplemented"),
        "prerequisite": gate("BLOCKED", "authenticated_prerequisites_required"),
        "migration": gate("NONE", "no_migration_authorized"),
        "admission": gate("BLOCKED", "live_authorization_required"),
        "live": gate("BLOCKED", "live_authorization_required"),
        "open_questions": copy.deepcopy(OPEN_QUESTIONS),
    }
    migration = bundle.get("migration", "none")
    if migration != "none":
        report["migration"] = gate("BLOCKED", "separate_migration_authority_required")
    release = None
    try:
        if reader is None:
            raise MaintenanceDenied(config_reason)
        # Mandatory fresh verification: never a script-specific interpretation.
        release = reader.read_saved(bundle.get("attestation"), "admit")
        report["authentication"] = gate("PASS")
    except MaintenanceDenied as denied:
        report["authentication"] = gate("BLOCKED", denied.reason)
        report["live"] = gate("BLOCKED", denied.reason)
        return report, 1

    if release.purpose == PURPOSE_OFFLINE:
        report["offline"] = gate("PASS", "isolated_offline_attestation_only")
        report["prerequisite"] = gate("SIMULATED_PASS", "offline_corpus_not_upstream_acceptance")
        report["live"] = gate("BLOCKED", "offline_purpose_cannot_authorize_live")
    else:
        report["prerequisite"] = gate("PASS")
        report["admission"] = gate("PASS", "exact_current_signed_release")
        report["live"] = gate("PASS", "authenticated_owned_live_evidence")
        for question in report["open_questions"][2:]:
            question["status"] = "PASS"
            question["reason"] = "authenticated_relationship_release_only_no_schema_migration"
    if migration != "none":
        report["live"] = gate("BLOCKED", "separate_migration_authority_required")
    if mode == PURPOSE_LIVE:
        return report, 0 if report["live"]["status"] == "PASS" else 1
    return report, 0 if report["offline"]["status"] == "PASS" and migration == "none" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--mode", required=True, choices=(PURPOSE_OFFLINE, PURPOSE_LIVE))
    args = parser.parse_args(argv)
    if args.input.resolve() == args.output.resolve():
        parser.error("input and output must differ")
    try:
        raw = args.input.read_bytes()
        if len(raw) > 8_000_000:
            raise ValueError("input too large")
        bundle = json.loads(raw)
        if not isinstance(bundle, dict):
            raise TypeError("input must be object")
    except (OSError, ValueError, TypeError):
        report, _ = verify_saved_bundle({}, mode=args.mode, reader=None, config_reason="input_unreadable")
        code = 1
    else:
        reason = "production_trust_unconfigured"
        try:
            reader = build_production_reader()
        except MaintenanceConfigError as error:
            reader, reason = None, str(error)
        report, code = verify_saved_bundle(bundle, mode=args.mode, reader=reader, config_reason=reason)
        report["input_path"] = str(args.input)
        report["input_file_sha256"] = hashlib.sha256(raw).hexdigest()
    # Independent diagnostics, never authority or a substitute for the reader.
    # Fixed repository corpus, NOT an input-selected artifact/trust root.
    root = SOURCE.parent / ".planning"
    diagnostics = []
    for target in ("03.7", "03.8"):
        try:
            manifest, _ = verify_prerequisite_corpus(root, [target])
            diagnostics.append({"target": target, "status": "LOCAL_ONLY", "manifest_digest": manifest})
        except MaintenanceDenied as denied:
            diagnostics.append({"target": target, "status": "BLOCKED", "reason": denied.reason})
    report["local_prerequisite_diagnostics"] = diagnostics
    report["phase13_count_diagnostic"] = phase13_corpus_diagnostic(root)
    # Only the explicitly requested local report is written; no authority files.
    try:
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError:
        print("maintenance_report_unwritable", file=sys.stderr)
        return 2
    print(json.dumps({"status": report["live" if args.mode == PURPOSE_LIVE else "offline"]["status"],
                      "output": str(args.output), "exit_code": code}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
