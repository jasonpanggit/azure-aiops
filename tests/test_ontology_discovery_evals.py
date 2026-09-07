from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path

import yaml

from ontology_discovery.evaluation_store import EvaluationSnapshotStore
from scripts.evaluate_ontology_discovery import (
    call_api,
    evaluate_dataset,
    load_dataset,
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
