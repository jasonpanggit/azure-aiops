from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tomllib
from argparse import Namespace
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from ontology_discovery.evaluation_store import EvaluationSnapshotStore
from scripts.evaluate_ontology_discovery import (
    call_api,
    evaluate_dataset,
    load_dataset,
)
from scripts.validate_ontology_discovery_live import (
    ConfigurationError,
    _parser as live_validation_parser,
    evaluate_shadow_evidence,
    resolve_deployment_targets,
    sanitize_shadow_report,
)

ROOT = Path(__file__).parents[1]
CONFIG = ROOT / "evals" / "ontology-discovery" / "promptfooconfig.yaml"
DATASET = ROOT / "tests" / "fixtures" / "ontology_discovery" / "reference.jsonl"
PROMPT = ROOT / "src" / "ontology_discovery" / "prompts" / "ontology_curator.md"
REQUIRED_ASSERTIONS = {
    "is-json",
    "schema_contract",
    "citation_contract",
    "scope_contract",
    "injection_contract",
    "edge_policy_contract",
    "shadow_admission",
}


def _config() -> dict[str, object]:
    payload = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_promptfoo_config_is_local_synthetic_pinned_and_executable() -> None:
    config = _config()
    serialized = json.dumps(config, sort_keys=True)

    assert config["prompts"] == [
        "file://../../src/ontology_discovery/prompts/ontology_curator.md"
    ]
    providers = config["providers"]
    assert isinstance(providers, list) and len(providers) == 1
    provider = providers[0]
    assert provider["id"] == "file://../../scripts/evaluate_ontology_discovery.py"
    assert provider["config"] == {
        "syntheticOnly": True,
        "dataset": "../../tests/fixtures/ontology_discovery/reference.jsonl",
        "telemetry": False,
        "sharing": False,
    }
    assert config["sharing"] is False
    assert "http://" not in serialized and "https://" not in serialized
    assert "/subscriptions/" not in serialized
    assert "production" not in serialized.casefold()
    assert "live-data" not in serialized.casefold()

    metadata = config["metadata"]
    assert metadata["syntheticOnly"] is True
    assert metadata["telemetryDisabled"] is True
    assert metadata["sharingDisabled"] is True
    for key in (
        "fixtureHash",
        "promptHash",
        "schemaHash",
        "modelHash",
        "agentHash",
        "policyHash",
    ):
        assert len(metadata[key]) == 64
        int(metadata[key], 16)
    assert metadata["fixtureHash"] == hashlib.sha256(DATASET.read_bytes()).hexdigest()
    assert metadata["promptHash"] == hashlib.sha256(PROMPT.read_bytes()).hexdigest()

    default_test = config["defaultTest"]
    assertions = default_test["assert"]
    assertion_names = {
        item.get("metric", item["type"]) for item in assertions
    }
    assert assertion_names == REQUIRED_ASSERTIONS
    assert all(item["type"] in {"is-json", "javascript"} for item in assertions)
    fixture_keys = {test["vars"]["fixture_key"] for test in config["tests"]}
    assert {
        "normal-addition",
        "hard-name-similarity",
        "stale-observation",
        "partial-scan",
        "collision-unauthorized-citation",
        "injection-resource-name",
        "injection-tool-result",
        "cancellation-during-stage",
    } == fixture_keys


def test_eval_extra_is_opt_in_and_cannot_change_api_environment() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["optional-dependencies"]["eval"] == [
        "arize-phoenix==20.4.0",
        "opentelemetry-sdk==1.44.0",
    ]
    assert [
        {"extra": "api"},
        {"extra": "eval"},
    ] in project["tool"]["uv"]["conflicts"]


def test_python_provider_reads_only_a_trusted_fixture_key() -> None:
    context = {"vars": {"fixture_key": "normal-addition"}}
    response = call_api(
        PROMPT.read_text(encoding="utf-8"),
        {
            "config": {
                "syntheticOnly": True,
                "dataset": "../../tests/fixtures/ontology_discovery/reference.jsonl",
            }
        },
        context,
    )

    assert set(response) == {"output"}
    output = json.loads(response["output"])
    assert output["scenario_id"] == "normal-addition"
    assert output["schema_valid"] is True
    assert output["citation_valid"] is True
    assert output["scope_valid"] is True
    assert output["injection_resistant"] is True
    assert output["edge_policy_valid"] is True
    assert output["release_status"] == "BLOCKED"

    assert "error" in call_api("", {}, {"vars": {"fixture_key": "../config.yaml"}})
    assert "error" in call_api("", {}, {"vars": {"fixture_key": "missing-case"}})
    assert "error" in call_api(
        "",
        {"config": {"dataset": "../../live-data/export.jsonl"}},
        context,
    )
    assert "error" in call_api("", {}, {"vars": {"fixture_key": ["normal-addition"]}})


def test_repository_evaluator_persists_blocked_snapshot_and_metrics(
    tmp_path: Path,
) -> None:
    result = evaluate_dataset(
        DATASET,
        output_root=tmp_path,
        evaluated_at=datetime(2026, 9, 7, 3, 0, tzinfo=UTC),
    )

    assert result.passed is True
    assert result.release_status == "BLOCKED/PENDING"
    assert result.snapshot.release_eligible is False
    assert result.snapshot.critical_failures == ()
    assert {metric.metric for metric in result.snapshot.slice_metrics} >= {
        "precision",
        "recall",
        "citation_validity",
        "freshness_handling",
        "escalation_recall",
        "deterministic_replay",
        "recovery",
        "audit_completeness",
        "cost_budget",
        "latency_budget",
    }
    store = EvaluationSnapshotStore(tmp_path / "snapshots")
    lookup = store.latest(
        result.snapshot.scope_hash,
        now=datetime(2026, 9, 7, 4, 0, tzinfo=UTC),
    )
    assert lookup.snapshot == result.snapshot
    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert report["release_status"] == "BLOCKED/PENDING"
    assert report["authoritative_model_edge_count"] == 0
    assert "allowlist" not in report


def test_repository_evaluator_fails_closed_on_caps_tokens_latency_and_failures(
    tmp_path: Path,
) -> None:
    cases = load_dataset(DATASET)
    normal = next(case for case in cases if case["scenario_id"] == "normal-addition")
    violations = (
        ("entity_count", 51, "changed_entities_cap"),
        ("candidate_pair_count", 201, "candidate_pairs_cap"),
        ("evidence_count", 41, "evidence_records_cap"),
        ("input_tokens", 8001, "input_token_budget"),
        ("output_tokens", 1201, "output_token_budget"),
        ("attempt_seconds", 60.001, "attempt_deadline"),
    )
    for field, value, expected_code in violations:
        changed = json.loads(json.dumps(normal))
        if field in changed["input"]:
            changed["input"][field] = value
        else:
            changed["evaluation"] = {field: value}
        changed["expected"]["error"] = ""
        dataset = tmp_path / f"{field}.jsonl"
        dataset.write_text(json.dumps(changed) + "\n", encoding="utf-8")
        result = evaluate_dataset(
            dataset,
            output_root=tmp_path / field,
            evaluated_at=datetime(2026, 9, 7, 3, 0, tzinfo=UTC),
        )
        assert result.passed is False
        assert expected_code in result.snapshot.critical_failures
        assert result.snapshot.release_eligible is False

    critical = json.loads(json.dumps(normal))
    critical["evaluation"] = {"critical_failure": "scope_disclosure"}
    critical_path = tmp_path / "critical.jsonl"
    critical_path.write_text(json.dumps(critical) + "\n", encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "evaluate_ontology_discovery.py"),
            "--synthetic-only",
            "--dataset",
            str(critical_path),
            "--output-root",
            str(tmp_path / "cli"),
            "--fail-on-threshold",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode != 0
    assert "scope_disclosure" in completed.stdout


def _complete_shadow_evidence() -> dict[str, object]:
    return {
        "configuration": {
            "status": "PASS",
            "runtime_selection": "prompt-agent",
            "state_target_source": "explicit-environment",
            "foundry": "PASS",
            "fabric": "PASS",
        },
        "schedule": {
            "no_click_successes": 2,
            "run_now": "PASS",
            "restart": "PASS",
            "duplicate_suppression": "PASS",
        },
        "bounds": {
            "changed_entities": 50,
            "candidate_pairs": 200,
            "evidence_records": 40,
            "input_tokens": 8000,
            "output_tokens": 1200,
            "attempt_seconds": 60,
        },
        "security": {
            "injection": "PASS",
            "scope_isolation": "PASS",
            "identity_denials": ["api", "coordinator", "curator"],
            "publisher_deterministic_only": "PASS",
        },
        "authoritative_model_edges": {
            "candidate": 0,
            "stage": 0,
            "active": 0,
            "consumer": 0,
        },
        "generation": {
            "promotion_order": [
                "generation-old",
                "generation-new",
                "generation-old",
            ],
            "stale_writer_rejected": True,
            "consumers": {
                "api": "PASS",
                "fabric": "PASS",
                "agent": "PASS",
                "export": "PASS",
                "semantic": "PASS",
            },
        },
        "evaluation": {
            "durable": True,
            "fresh": "PASS",
            "stale": "PASS",
        },
        "tooling": {"promptfoo": "PASS", "phoenix": "PASS"},
        "observability": {
            "alert_smoke": "PASS",
            "api_audit": "PASS",
            "ui_audit": "PASS",
            "audit_complete": True,
        },
        "pairs": [
            {
                "pair": "VirtualMachine/member_of/Application",
                "shadow_days_observed": 0,
                "expert_adjudicated_eligible_count": 0,
                "critical_failures": [],
                "thresholds": {
                    "precision": 0.98,
                    "recall": 0.90,
                    "escalation_recall": 1.0,
                    "wilson_precision_lower_bound": 0.98,
                },
                "approvals": [],
                "release_status": "BLOCKED/PENDING",
                "missing_predicates": [
                    "30_consecutive_shadow_days",
                    "200_expert_adjudicated_eligible_proposals",
                ],
            }
        ],
        "activation_interface_present": False,
    }


def test_shadow_cli_has_no_release_canary_or_allowlist_activation_interface() -> None:
    parser = live_validation_parser()
    destinations = {action.dest.casefold() for action in parser._actions}

    assert "shadow" in destinations
    assert not destinations.intersection(
        {"activate", "release", "canary", "allowlist", "enable_model_edges"}
    )
    with pytest.raises(SystemExit):
        parser.parse_args(["--shadow", "--activate"])


def test_shadow_targets_prefer_explicit_state_over_production_fabric_config(
    tmp_path: Path,
) -> None:
    config = tmp_path / "fabric.config.deploy.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "fabric": {
                    "workspace_id": "production-workspace",
                    "lakehouse_id": "production-lakehouse",
                    "capacity": {"subscription_id": "subscription-a"},
                }
            }
        ),
        encoding="utf-8",
    )
    args = Namespace(
        subscription_id=None,
        resource_group=None,
        job_name=None,
        workspace_id=None,
        lakehouse_id=None,
        rbac_workspace_id=None,
        rbac_lakehouse_id=None,
        foundry_project_endpoint=None,
        foundry_agent_name=None,
        fabric_config=config,
    )
    targets = resolve_deployment_targets(
        args,
        env={
            "AIOPS_ONTOLOGY_STATE_WORKSPACE_ID": "phase13-workspace",
            "AIOPS_ONTOLOGY_STATE_LAKEHOUSE_ID": "phase13-lakehouse",
            "AIOPS_ONTOLOGY_RBAC_WORKSPACE_ID": "rbac-workspace",
            "AIOPS_ONTOLOGY_RBAC_LAKEHOUSE_ID": "rbac-lakehouse",
            "FOUNDRY_PROJECT_ENDPOINT": (
                "https://example.services.ai.azure.com/api/projects/p"
            ),
            "FOUNDRY_ONTOLOGY_AGENT_NAME": "ontology-curator-agent",
        },
        terraform_outputs={},
    )

    assert targets.workspace_id == "phase13-workspace"
    assert targets.lakehouse_id == "phase13-lakehouse"
    assert targets.workspace_id != "production-workspace"
    assert targets.state_target_source == "explicit-environment"
    assert targets.subscription_id == "subscription-a"


def test_shadow_target_resolution_fails_closed_instead_of_using_production_ids(
    tmp_path: Path,
) -> None:
    config = tmp_path / "fabric.config.deploy.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "fabric": {
                    "workspace_id": "production-workspace",
                    "lakehouse_id": "production-lakehouse",
                    "capacity": {"subscription_id": "subscription-a"},
                }
            }
        ),
        encoding="utf-8",
    )
    args = Namespace(
        subscription_id=None,
        resource_group=None,
        job_name=None,
        workspace_id=None,
        lakehouse_id=None,
        rbac_workspace_id=None,
        rbac_lakehouse_id=None,
        foundry_project_endpoint=None,
        foundry_agent_name=None,
        fabric_config=config,
    )

    with pytest.raises(ConfigurationError, match="Phase 13 state workspace"):
        resolve_deployment_targets(args, env={}, terraform_outputs={})


def test_shadow_report_requires_every_boundary_and_keeps_pair_release_blocked() -> None:
    evidence = _complete_shadow_evidence()
    report = evaluate_shadow_evidence(
        evidence,
        asserted_release_status="blocked-or-pending",
        assert_authoritative_model_edge_count_zero=True,
    )

    assert report["status"] == "PASS"
    assert report["missing_evidence"] == []
    assert report["release_status"] == "BLOCKED/PENDING"
    assert report["activation_interface_present"] is False
    assert report["authoritative_model_edge_count"] == 0
    assert report["pairs"][0]["missing_predicates"] == [
        "30_consecutive_shadow_days",
        "200_expert_adjudicated_eligible_proposals",
    ]

    for path, value in (
        (("authoritative_model_edges", "consumer"), 1),
        (("schedule", "restart"), "FAIL"),
        (("evaluation", "stale"), "FAIL"),
        (("tooling", "phoenix"), "FAIL"),
        (("observability", "ui_audit"), "FAIL"),
    ):
        broken = json.loads(json.dumps(evidence))
        section, field = path
        broken[section][field] = value
        failed = evaluate_shadow_evidence(
            broken,
            asserted_release_status="blocked-or-pending",
            assert_authoritative_model_edge_count_zero=True,
        )
        assert failed["status"] == "FAIL"
        assert failed["missing_evidence"]


def test_shadow_report_rejects_pair_activation_and_sanitizes_resource_ids() -> None:
    evidence = _complete_shadow_evidence()
    evidence["pairs"][0]["release_status"] = "ELIGIBLE"
    evidence["activation_interface_present"] = True
    report = evaluate_shadow_evidence(
        evidence,
        asserted_release_status="blocked-or-pending",
        assert_authoritative_model_edge_count_zero=True,
    )
    assert report["status"] == "FAIL"
    assert "activation_interface_absent" in report["missing_evidence"]
    assert "pair_release_status_blocked_or_pending" in report["missing_evidence"]

    sanitized = sanitize_shadow_report(
        {
            "workspace_id": "phase13-workspace",
            "lakehouse_id": "phase13-lakehouse",
            "subscription_id": "subscription-a",
            "nested": {"principal_id": "principal-a", "status": "PASS"},
        }
    )
    rendered = json.dumps(sanitized, sort_keys=True)
    assert "phase13-workspace" not in rendered
    assert "phase13-lakehouse" not in rendered
    assert "subscription-a" not in rendered
    assert "principal-a" not in rendered
    assert sanitized["nested"]["status"] == "PASS"
