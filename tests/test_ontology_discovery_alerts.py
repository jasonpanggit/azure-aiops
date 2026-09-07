"""Exact Phase 13 ontology telemetry and Azure Monitor alert contracts."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from ontology_discovery.telemetry import (
    ALERT_RULES,
    OntologyDiscoveryTelemetry,
    emit_sanitized_alert_smoke,
)

ROOT = Path(__file__).parents[1]
ALERTING_TF = ROOT / "infra" / "terraform" / "alerting.tf"
VALIDATOR = ROOT / "scripts" / "validate_ontology_discovery_live.py"


EXPECTED_RULES = {
    # Immediate page and fail-closed shadow reset.
    "scope_disclosure": ("immediate", 0.0, "GreaterThan", "PT5M", 0, True),
    "unauthorized_mutation": ("immediate", 0.0, "GreaterThan", "PT5M", 0, True),
    "successful_injection": ("immediate", 0.0, "GreaterThan", "PT5M", 0, True),
    "invalid_edge_promotion": ("immediate", 0.0, "GreaterThan", "PT5M", 0, True),
    "stale_writer_promotion": ("immediate", 0.0, "GreaterThan", "PT5M", 0, True),
    "partial_active_generation": ("immediate", 0.0, "GreaterThan", "PT5M", 0, True),
    "missing_audit": ("immediate", 0.0, "GreaterThan", "PT5M", 0, True),
    "active_generation_unrecoverable": (
        "immediate",
        0.0,
        "GreaterThan",
        "PT5M",
        0,
        True,
    ),
    # Production liveness pages.
    "successful_run_gap": ("page", 30.0, "GreaterThan", "PT30M", 1, False),
    "active_generation_age": ("page", 21600.0, "GreaterThan", "PT15M", 1, False),
    "fenced_publication_failures": (
        "page",
        2.0,
        "GreaterThanOrEqual",
        "PT15M",
        1,
        False,
    ),
    "critical_pending_edge_age": (
        "page",
        86400.0,
        "GreaterThan",
        "PT15M",
        1,
        False,
    ),
    "nonterminal_run_age": ("page", 2700.0, "GreaterThan", "PT15M", 1, False),
    # One-hour operational-quality alerts.
    "citation_validity": ("hour", 1.0, "LessThan", "PT1H", 2, False),
    "citation_freshness": ("hour", 0.99, "LessThan", "PT1H", 2, False),
    "post_repair_schema_validity": ("hour", 1.0, "LessThan", "PT1H", 1, False),
    "repair_rate": ("hour", 0.05, "GreaterThan", "PT1H", 2, False),
    "timeout_rate": ("hour", 0.01, "GreaterThan", "PT1H", 2, False),
    "model_latency_p95": ("hour", 30.0, "GreaterThan", "PT15M", 2, False),
    "attempt_duration_max": ("hour", 60.0, "GreaterThan", "PT1H", 1, False),
    "cap_violation": ("hour", 0.0, "GreaterThan", "PT1H", 1, False),
    # Weekly release-quality gates. They remain disable/reset signals only.
    "overall_precision": ("weekly", 0.98, "LessThan", "P7D", 1, True),
    "critical_precision": ("weekly", 0.95, "LessThan", "P7D", 1, True),
    "overall_recall": ("weekly", 0.90, "LessThan", "P7D", 2, True),
    "critical_recall": ("weekly", 0.85, "LessThan", "P7D", 2, True),
    "escalation_f1": ("weekly", 0.95, "LessThan", "P7D", 1, True),
    "mandatory_review_recall": ("weekly", 1.0, "LessThan", "P7D", 0, True),
    "pair_precision_wilson_lower_bound": (
        "weekly",
        0.98,
        "LessThan",
        "P7D",
        1,
        True,
    ),
}


class _Instrument:
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


class _Meter:
    def __init__(self) -> None:
        self.instruments: dict[str, _Instrument] = {}

    def create_counter(self, name: str, **_: object) -> _Instrument:
        instrument = _Instrument(name)
        self.instruments[name] = instrument
        return instrument

    def create_histogram(self, name: str, **_: object) -> _Instrument:
        instrument = _Instrument(name)
        self.instruments[name] = instrument
        return instrument


def test_alert_catalog_matches_every_ai_spec_threshold_exactly() -> None:
    actual = {
        rule_id: (
            rule.tier,
            rule.threshold,
            rule.operator,
            rule.window,
            rule.severity,
            rule.shadow_reset,
        )
        for rule_id, rule in ALERT_RULES.items()
    }
    assert actual == EXPECTED_RULES
    assert all(rule.metric_name.startswith("ontology.discovery.") for rule in ALERT_RULES.values())
    assert all(rule.action_group == "ontology-operations" for rule in ALERT_RULES.values())


def test_telemetry_emits_only_closed_low_cardinality_dimensions() -> None:
    meter = _Meter()
    telemetry = OntologyDiscoveryTelemetry(meter=meter)
    emitted = emit_sanitized_alert_smoke(telemetry)

    assert emitted == tuple(EXPECTED_RULES)
    assert set(meter.instruments) == {
        "ontology.discovery.alert.signal",
        "ontology.discovery.run.duration",
        "ontology.discovery.publication.stale_writer_blocked",
    }
    records = meter.instruments["ontology.discovery.alert.signal"].records
    assert len(records) == len(EXPECTED_RULES)
    for value, attributes in records:
        assert value >= 0
        assert set(attributes) == {"rule", "tier", "status", "reset_scope"}
        assert attributes["rule"] in EXPECTED_RULES
        assert attributes["tier"] in {"immediate", "page", "hour", "weekly"}
        assert attributes["status"] == "synthetic_violation"
        assert attributes["reset_scope"] in {"none", "affected_pair"}
        serialized = json.dumps(attributes)
        for forbidden in (
            "/subscriptions/",
            "prompt",
            "credential",
            "principal",
            "scope_value",
            "resource_id",
            "raw_error",
        ):
            assert forbidden not in serialized.casefold()

    with pytest.raises(ValueError, match="unknown ontology alert rule"):
        telemetry.emit_alert_signal("tenant-secret", 1)
    with pytest.raises(ValueError, match="finite"):
        telemetry.emit_alert_signal("repair_rate", float("nan"))


def test_terraform_defines_actioned_rule_for_every_catalog_entry() -> None:
    terraform = ALERTING_TF.read_text(encoding="utf-8")
    assert 'resource "azurerm_monitor_scheduled_query_rules_alert_v2" "ontology_discovery"' in terraform
    assert "for_each = local.ontology_discovery_alert_rules" in terraform
    assert 'action_groups = [azurerm_monitor_action_group.ops[0].id]' in terraform
    assert 'Name == "ontology.discovery.alert.signal"' in terraform
    assert "tostring(Properties.rule) == each.key" in terraform
    assert "ontology-operations" in terraform
    for rule_id, (
        tier,
        threshold,
        operator,
        window,
        severity,
        shadow_reset,
    ) in EXPECTED_RULES.items():
        expected_block = (
            f"{rule_id} = {{\n"
            f'      tier         = "{tier}"\n'
            f"      threshold    = {threshold:g}\n"
            f'      operator     = "{operator}"\n'
            f'      window       = "{window}"\n'
            f"      severity     = {severity}\n"
            f"      shadow_reset = {str(shadow_reset).lower()}"
        )
        assert expected_block in terraform


def test_synthetic_alert_smoke_observes_every_query_and_action_group(
    tmp_path: Path,
) -> None:
    report = tmp_path / "alert-smoke.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(VALIDATOR),
            "--alert-smoke",
            "--synthetic-only",
            "--fail-on-missing-evidence",
            "--report",
            str(report),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["mode"] == "alert-smoke"
    assert payload["sanitized"] is True
    assert payload["rules_expected"] == len(EXPECTED_RULES)
    assert payload["rules_observed"] == len(EXPECTED_RULES)
    assert payload["queries_observed"] == len(EXPECTED_RULES)
    assert payload["action_groups_observed"] == len(EXPECTED_RULES)
    assert payload["missing_evidence"] == []
    assert payload["status"] == "PASS"
    assert "allowlist" not in json.dumps(payload).casefold()
