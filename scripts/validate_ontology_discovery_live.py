#!/usr/bin/env python3
"""Validate ontology discovery without exposing an activation interface."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ontology_discovery.telemetry import (
    ALERT_RULES,
    OntologyDiscoveryTelemetry,
    emit_sanitized_alert_smoke,
)

ROOT = Path(__file__).resolve().parents[1]
ALERTING_TF = ROOT / "infra" / "terraform" / "alerting.tf"


class _SmokeInstrument:
    def __init__(self, name: str) -> None:
        self.name = name
        self.records: list[tuple[float, dict[str, str]]] = []

    def add(
        self, value: float, attributes: dict[str, str] | None = None
    ) -> None:
        self.records.append((float(value), dict(attributes or {})))

    def record(
        self, value: float, attributes: dict[str, str] | None = None
    ) -> None:
        self.records.append((float(value), dict(attributes or {})))


class _SmokeMeter:
    def __init__(self) -> None:
        self.instruments: dict[str, _SmokeInstrument] = {}

    def create_counter(self, name: str, **_: object) -> _SmokeInstrument:
        return self._create(name)

    def create_histogram(self, name: str, **_: object) -> _SmokeInstrument:
        return self._create(name)

    def _create(self, name: str) -> _SmokeInstrument:
        instrument = _SmokeInstrument(name)
        self.instruments[name] = instrument
        return instrument


def _alert_smoke() -> dict[str, object]:
    meter = _SmokeMeter()
    telemetry = OntologyDiscoveryTelemetry(meter=meter)
    emitted = emit_sanitized_alert_smoke(telemetry)
    terraform = ALERTING_TF.read_text(encoding="utf-8")
    records = meter.instruments["ontology.discovery.alert.signal"].records
    observed = {
        attributes["rule"]
        for _, attributes in records
        if attributes.get("status") == "synthetic_violation"
    }
    query_observed = {
        rule_id
        for rule_id in ALERT_RULES
        if f"{rule_id} = {{" in terraform
        and 'Name == "ontology.discovery.alert.signal"' in terraform
        and "tostring(Properties.rule) == each.key" in terraform
    }
    action_observed = (
        set(ALERT_RULES)
        if "azurerm_monitor_action_group.ops[0].id" in terraform
        and "ontology-operations" in terraform
        else set()
    )
    missing = sorted(
        (set(ALERT_RULES) - set(emitted))
        | (set(ALERT_RULES) - observed)
        | (set(ALERT_RULES) - query_observed)
        | (set(ALERT_RULES) - action_observed)
    )
    return {
        "schema_version": "ontology-discovery-live-validation.v1",
        "mode": "alert-smoke",
        "sanitized": True,
        "rules_expected": len(ALERT_RULES),
        "rules_observed": len(observed),
        "queries_observed": len(query_observed),
        "action_groups_observed": len(action_observed),
        "missing_evidence": missing,
        "status": "PASS" if not missing else "FAIL",
    }


def _write_report(path: Path | None, report: dict[str, object]) -> None:
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f"{path.suffix}.tmp")
        temporary.write_text(rendered, encoding="utf-8")
        temporary.replace(path)
    print(rendered, end="")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate deployed ontology discovery in fail-closed shadow mode."
    )
    parser.add_argument("--alert-smoke", action="store_true")
    parser.add_argument("--synthetic-only", action="store_true")
    parser.add_argument("--fail-on-missing-evidence", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if not args.alert_smoke:
        parser.error("this build supports --alert-smoke only")
    if not args.synthetic_only:
        parser.error("--alert-smoke requires --synthetic-only")
    report = _alert_smoke()
    _write_report(args.report, report)
    return int(args.fail_on_missing_evidence and report["status"] != "PASS")


if __name__ == "__main__":
    raise SystemExit(main())
