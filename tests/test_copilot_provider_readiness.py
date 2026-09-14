"""Offline provider wiring and staged-rollout regression tests."""

from __future__ import annotations

import importlib.util
import json
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from operations import maf_orchestrator

REPO_ROOT = Path(__file__).resolve().parents[1]
EXPORT_SCRIPT = REPO_ROOT / "scripts" / "export_copilot_provider_env.py"
OPERATIONS_CONNECTION_ID = (
    "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.CognitiveServices/"
    "accounts/account/projects/project/connections/ops-mcp"
)
AZURE_CONNECTION_ID = (
    "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.CognitiveServices/"
    "accounts/account/projects/project/connections/azure-mcp"
)


def _terraform_output(candidate_mapping: Path) -> dict[str, object]:
    return {
        "copilot_provider_environment": {
            "sensitive": False,
            "type": ["map", "string"],
            "value": {
                "FOUNDRY_PROJECT_ENDPOINT": (
                    "https://account.services.ai.azure.com/api/projects/project"
                ),
                "OPERATIONS_MCP_SERVER_URL": (
                    "https://gateway.example.net/operations-mcp"
                ),
                "AZURE_MCP_SERVER_URL": "https://gateway.example.net/azure-mcp",
                "MCP_APIM_AUDIENCE": "api://aiops-apim",
                "FOUNDRY_CANDIDATE_MAPPING": str(candidate_mapping),
                "FOUNDRY_OPERATIONS_MCP_CONNECTION_ID": OPERATIONS_CONNECTION_ID,
                "FOUNDRY_AZURE_MCP_CONNECTION_ID": AZURE_CONNECTION_ID,
                "AIOPS_COPILOT_ROLLOUT_MODE": "canary",
                "AIOPS_COPILOT_CANARY_PERCENTAGE": "10",
                "AIOPS_COPILOT_ROLLBACK_MODE": "compatibility",
            },
        },
        "unrelated_sensitive_output": {
            "sensitive": True,
            "type": "string",
            "value": "must-not-leak",
        },
    }


def _candidate_mapping(path: Path) -> None:
    from operations.specialist_manifest import load_specialist_manifest

    manifest = load_specialist_manifest()
    path.write_text(
        json.dumps(
            {
                "agents": {
                    specialist.id: {
                        "agent_name": f"aiops-{specialist.foundry.name}-agent",
                        "provider_version_id": f"provider-{specialist.id}",
                    }
                    for specialist in manifest.specialists
                },
                "coordinator": {
                    "agent_name": "operations-copilot",
                    "provider_version_id": "provider-coordinator",
                },
                "connections": {
                    "operations-mcp": {
                        "project_connection_id": OPERATIONS_CONNECTION_ID,
                    },
                    "azure-mcp": {
                        "project_connection_id": AZURE_CONNECTION_ID,
                    },
                },
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _run_exporter(
    tmp_path: Path,
    payload: dict[str, object],
) -> tuple[subprocess.CompletedProcess[str], Path]:
    source = tmp_path / "terraform-output.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    destination = tmp_path / "copilot-provider.env"
    result = subprocess.run(
        [
            sys.executable,
            str(EXPORT_SCRIPT),
            "--terraform-output",
            str(source),
            "--output",
            str(destination),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result, destination


def test_provider_env_export_blocks_missing_authoritative_output(tmp_path: Path) -> None:
    result, destination = _run_exporter(tmp_path, {})

    assert result.returncode == 3
    assert "copilot_provider_environment" in result.stderr
    assert not destination.exists()


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("FOUNDRY_PROJECT_ENDPOINT", "http://account.example.test/project"),
        ("OPERATIONS_MCP_SERVER_URL", "https://user@gateway.example.net/operations-mcp"),
        ("AZURE_MCP_SERVER_URL", "https://gateway.example.net:443/azure-mcp"),
        ("MCP_APIM_AUDIENCE", "not-an-audience"),
        ("AIOPS_COPILOT_ROLLOUT_MODE", "enabled"),
        ("AIOPS_COPILOT_CANARY_PERCENTAGE", "101"),
        ("AIOPS_COPILOT_ROLLBACK_MODE", "default"),
    ],
)
def test_provider_env_export_rejects_malformed_values(
    tmp_path: Path,
    key: str,
    value: str,
) -> None:
    candidate = tmp_path / "candidate.json"
    _candidate_mapping(candidate)
    payload = _terraform_output(candidate)
    payload["copilot_provider_environment"]["value"][key] = value  # type: ignore[index]

    result, destination = _run_exporter(tmp_path, payload)

    assert result.returncode == 2
    assert key in result.stderr
    assert not destination.exists()


def test_provider_env_export_blocks_missing_candidate_mapping(tmp_path: Path) -> None:
    candidate = tmp_path / "missing-candidate.json"

    result, destination = _run_exporter(
        tmp_path,
        _terraform_output(candidate),
    )

    assert result.returncode == 3
    assert "FOUNDRY_CANDIDATE_MAPPING" in result.stderr
    assert not destination.exists()


def test_provider_env_export_writes_only_allowlisted_non_secret_values(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate.json"
    _candidate_mapping(candidate)

    result, destination = _run_exporter(
        tmp_path,
        _terraform_output(candidate),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    rendered = destination.read_text(encoding="utf-8")
    assert "export FOUNDRY_PROJECT_ENDPOINT=" in rendered
    assert f"export FOUNDRY_CANDIDATE_MAPPING={candidate}" in rendered
    assert "export AIOPS_COPILOT_ROLLOUT_MODE=canary" in rendered
    assert "must-not-leak" not in rendered
    assert "AZURE_CLIENT_SECRET" not in rendered
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600


def test_terraform_exposes_complete_sourceable_provider_environment() -> None:
    outputs = (REPO_ROOT / "infra" / "terraform" / "outputs.tf").read_text(
        encoding="utf-8"
    )

    assert 'output "copilot_provider_environment"' in outputs
    for key in (
        "FOUNDRY_PROJECT_ENDPOINT",
        "OPERATIONS_MCP_SERVER_URL",
        "AZURE_MCP_SERVER_URL",
        "MCP_APIM_AUDIENCE",
        "FOUNDRY_CANDIDATE_MAPPING",
        "FOUNDRY_OPERATIONS_MCP_CONNECTION_ID",
        "FOUNDRY_AZURE_MCP_CONNECTION_ID",
        "AIOPS_COPILOT_ROLLOUT_MODE",
        "AIOPS_COPILOT_CANARY_PERCENTAGE",
        "AIOPS_COPILOT_ROLLBACK_MODE",
    ):
        assert key in outputs
    foundry = (REPO_ROOT / "infra" / "terraform" / "foundry.tf").read_text(
        encoding="utf-8"
    )
    assert "FOUNDRY_CANDIDATE_RECORD           = local.foundry_candidate_artifact_path" in foundry
    assert "FOUNDRY_CANDIDATE_MAPPING            = local.foundry_candidate_artifact_path" in outputs


def test_unspecified_rollout_fails_closed_but_explicit_modes_still_win(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AIOPS_COPILOT_ROLLOUT_MODE", raising=False)
    monkeypatch.delenv("AIOPS_AGENT_ORCHESTRATION_MODE", raising=False)
    unspecified = maf_orchestrator.copilot_rollout_decision(
        stable_key="operator-a"
    )
    assert unspecified.mode == "compatibility"
    assert unspecified.canonical_enabled is False
    assert unspecified.reason == "rollout_mode_unspecified"
    assert (
        maf_orchestrator.canonical_orchestration_enabled(stable_key="operator-a")
        is False
    )

    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "compatibility")
    compatibility = maf_orchestrator.copilot_rollout_decision(
        stable_key="operator-a"
    )
    assert compatibility.mode == "compatibility"
    assert compatibility.canonical_enabled is False
    assert compatibility.reason == "compatibility_selected"

    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "default")
    explicit_default = maf_orchestrator.copilot_rollout_decision(
        stable_key="operator-a"
    )
    assert explicit_default.mode == "default"
    assert explicit_default.canonical_enabled is True
    assert explicit_default.reason == "default_selected"

    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "enabled")
    invalid = maf_orchestrator.copilot_rollout_decision(stable_key="operator-a")
    assert invalid.mode == "compatibility"
    assert invalid.canonical_enabled is False
    assert invalid.reason == "rollout_mode_invalid"


def test_missing_rollout_keeps_explicit_legacy_canonical_switch_compatible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AIOPS_COPILOT_ROLLOUT_MODE", raising=False)
    monkeypatch.setenv("AIOPS_AGENT_ORCHESTRATION_MODE", "canonical")

    decision = maf_orchestrator.copilot_rollout_decision(stable_key="operator-a")

    assert decision.mode == "compatibility"
    assert decision.canonical_enabled is False
    assert decision.reason == "rollout_mode_unspecified"
    assert (
        maf_orchestrator.canonical_orchestration_enabled(stable_key="operator-a")
        is False
    )


def test_deterministic_override_disables_default_canonical_rollout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "default")
    monkeypatch.setenv("AIOPS_AGENT_ORCHESTRATION_MODE", "deterministic")

    decision = maf_orchestrator.copilot_rollout_decision(
        stable_key="operator-a"
    )

    assert decision.mode == "compatibility"
    assert decision.canonical_enabled is False
    assert decision.shadow_enabled is False
    assert decision.reason == "deterministic_override"
    assert (
        maf_orchestrator.canonical_orchestration_enabled(
            stable_key="operator-a"
        )
        is False
    )


def test_rollout_modes_preserve_compatibility_shadow_canary_and_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "compatibility")
    compatibility = maf_orchestrator.copilot_rollout_decision(
        stable_key="operator-a"
    )
    assert compatibility.canonical_enabled is False
    assert compatibility.shadow_enabled is False

    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "shadow")
    shadow = maf_orchestrator.copilot_rollout_decision(stable_key="operator-a")
    assert shadow.canonical_enabled is False
    assert shadow.shadow_enabled is True

    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "canary")
    monkeypatch.setenv("AIOPS_COPILOT_CANARY_PERCENTAGE", "0")
    canary_zero = maf_orchestrator.copilot_rollout_decision(
        stable_key="operator-a"
    )
    assert canary_zero.canonical_enabled is False
    monkeypatch.setenv("AIOPS_COPILOT_CANARY_PERCENTAGE", "100")
    canary_hundred = maf_orchestrator.copilot_rollout_decision(
        stable_key="operator-a"
    )
    assert canary_hundred.canonical_enabled is True

    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "default")
    default = maf_orchestrator.copilot_rollout_decision(stable_key="operator-a")
    assert default.canonical_enabled is True
    assert default.shadow_enabled is False


@pytest.mark.parametrize("percentage", ["", "-1", "101", "ten", "10.5"])
def test_canary_invalid_or_missing_percentage_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    percentage: str,
) -> None:
    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "canary")
    if percentage:
        monkeypatch.setenv("AIOPS_COPILOT_CANARY_PERCENTAGE", percentage)
    else:
        monkeypatch.delenv("AIOPS_COPILOT_CANARY_PERCENTAGE", raising=False)

    decision = maf_orchestrator.copilot_rollout_decision(stable_key="operator-a")

    assert decision.mode == "compatibility"
    assert decision.canonical_enabled is False
    assert decision.reason == "canary_percentage_invalid"


def test_canary_assignment_is_stable_and_requires_a_stable_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "canary")
    monkeypatch.setenv("AIOPS_COPILOT_CANARY_PERCENTAGE", "50")

    first = maf_orchestrator.copilot_rollout_decision(stable_key="operator-a")
    second = maf_orchestrator.copilot_rollout_decision(stable_key="operator-a")
    no_key = maf_orchestrator.copilot_rollout_decision(stable_key="")

    assert first == second
    assert 0 <= first.canary_bucket < 100
    assert no_key.mode == "compatibility"
    assert no_key.canonical_enabled is False
    assert no_key.reason == "canary_stable_key_missing"


def test_rollout_rollback_mode_is_fixed_to_compatibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "default")
    monkeypatch.setenv("AIOPS_COPILOT_ROLLBACK_MODE", "canonical")

    decision = maf_orchestrator.copilot_rollout_decision(stable_key="operator-a")

    assert decision.mode == "compatibility"
    assert decision.canonical_enabled is False
    assert decision.reason == "rollback_mode_invalid"


def test_candidate_mapping_requires_distinct_governed_connection_ids(
    tmp_path: Path,
) -> None:
    spec = importlib.util.spec_from_file_location(
        "validate_specialist_parity",
        REPO_ROOT / "scripts" / "validate_specialist_parity.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    candidate = tmp_path / "candidate.json"
    _candidate_mapping(candidate)
    agents, coordinator, connections = module._candidate_mapping(str(candidate))
    assert agents
    assert coordinator["provider_version_id"] == "provider-coordinator"
    assert connections == {
        "operations-mcp": OPERATIONS_CONNECTION_ID,
        "azure-mcp": AZURE_CONNECTION_ID,
    }

    payload = json.loads(candidate.read_text(encoding="utf-8"))
    payload["connections"]["azure-mcp"]["project_connection_id"] = (
        OPERATIONS_CONNECTION_ID
    )
    candidate.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="distinct"):
        module._candidate_mapping(str(candidate))


def test_runtime_routes_read_the_rollout_decision_at_request_boundaries() -> None:
    for relative in (
        "src/api/routers/copilot.py",
        "src/api/routers/multi_agent.py",
    ):
        source = (REPO_ROOT / relative).read_text(encoding="utf-8")
        assert "canonical_orchestration_enabled(stable_key=principal.subject)" in source
