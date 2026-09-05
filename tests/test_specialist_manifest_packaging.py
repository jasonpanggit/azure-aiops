"""Packaging and infrastructure-projection parity for the specialist manifest.

The committed manifest (``src/operations/specialists.v1.json``) is the single
source of truth for the twelve reviewed specialists. These tests fail closed
whenever a deployment boundary -- Terraform, Container Apps, the Python wheel,
or the API container image -- restates specialist identity, grants, or
versions instead of deriving them from that one file.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest

from operations import specialist_manifest as manifest_module
from operations.specialist_manifest import (
    LOCKED_SPECIALIST_IDS,
    load_specialist_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / "src" / "operations" / "specialists.v1.json"

# Stable path the loader resolves inside an installed distribution and inside
# the API container image. Packaging must place the manifest here exactly.
PACKAGED_MANIFEST_PATH = "operations/specialists.v1.json"
CONTAINER_MANIFEST_PATH = "/app/src/operations/specialists.v1.json"

# Legacy eight-specialist Terraform input retained for one migration window so
# existing tfvars keep planning and the previous revision stays selectable.
LEGACY_SPECIALIST_IDS = (
    "network",
    "vulnerability",
    "patch",
    "incident",
    "change",
    "governance",
    "remediation",
    "executive_summary",
)


def _read(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def _pyproject() -> dict:
    return tomllib.loads(_read("pyproject.toml"))


def _manifest_tool_names() -> set[str]:
    manifest = load_specialist_manifest()
    return {
        tool
        for specialist in manifest.specialists
        for tool in (*specialist.operations_mcp_tools, *specialist.azure_mcp_tools)
    }


def _hcl_block(source: str, header: str) -> str:
    """Return the body of an HCL block introduced by ``header`` up to its close."""

    start = source.index(header)
    end = source.index("\n}\n", start) if header.startswith("variable") else source.index(
        "\n  }\n", start
    )
    return source[start:end]


def _terraform_tool_registry_keys() -> set[str]:
    block = _hcl_block(_read("infra/terraform/foundry.tf"), "  foundry_tool_registry = {")
    return set(
        re.findall(
            r"^\s{4}([a-z][a-z0-9_-]*)\s*=\s*\{\s*server\s*=",
            block,
            flags=re.MULTILINE,
        )
    )


# ---------------------------------------------------------------------------
# Wheel packaging
# ---------------------------------------------------------------------------


def test_loader_resolves_the_stable_packaged_manifest_path():
    loader_path = Path(manifest_module.__file__).with_name("specialists.v1.json")

    assert loader_path.exists()
    assert loader_path.as_posix().endswith(PACKAGED_MANIFEST_PATH)
    assert load_specialist_manifest().specialist_ids == LOCKED_SPECIALIST_IDS


def test_wheel_packaging_declares_the_manifest_at_the_loader_path():
    wheel = _pyproject()["tool"]["hatch"]["build"]["targets"]["wheel"]

    assert "src/operations" in wheel["packages"]
    assert (
        wheel["force-include"]["src/operations/specialists.v1.json"]
        == PACKAGED_MANIFEST_PATH
    )


@pytest.mark.skipif(
    importlib.util.find_spec("build") is None,
    reason="python -m build is not installed in this environment",
)
def test_built_wheel_contains_the_manifest_at_the_loader_path(tmp_path):
    subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(tmp_path)],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    wheels = sorted(tmp_path.glob("*.whl"))

    assert len(wheels) == 1
    with zipfile.ZipFile(wheels[0]) as archive:
        assert PACKAGED_MANIFEST_PATH in archive.namelist()
        packaged = json.loads(archive.read(PACKAGED_MANIFEST_PATH).decode("utf-8"))

    assert packaged == json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Container image
# ---------------------------------------------------------------------------


def test_container_image_carries_and_verifies_the_manifest():
    dockerfile = _read("Dockerfile")
    dockerignore = {
        line.strip()
        for line in _read(".dockerignore").splitlines()
        if line.strip() and not line.startswith("#")
    }

    assert "COPY src/ /app/src/" in dockerfile
    # Build-time assertion: a missing or unparseable manifest must fail the
    # image build rather than surface as a runtime import error in production.
    assert CONTAINER_MANIFEST_PATH in dockerfile
    # The build context must actually carry the manifest.
    assert not {"src", "src/", "src/operations", "*.json"} & dockerignore


# ---------------------------------------------------------------------------
# Terraform projection
# ---------------------------------------------------------------------------


def test_terraform_decodes_the_committed_manifest():
    foundry = _read("infra/terraform/foundry.tf")

    assert 'jsondecode(file(local.specialist_manifest_path))' in foundry
    assert '"${path.module}/../../src/operations/specialists.v1.json"' in foundry


def test_terraform_holds_no_hardcoded_specialist_tool_grants():
    foundry = _read("infra/terraform/foundry.tf")

    duplicated = sorted(
        tool for tool in _manifest_tool_names() if f'"{tool}"' in foundry
    )

    assert duplicated == [], (
        "Terraform must project grants from the manifest, not restate them"
    )


def test_terraform_tool_registry_covers_every_manifest_tool_exactly():
    assert _terraform_tool_registry_keys() == _manifest_tool_names()


def test_terraform_projects_twelve_distinct_specialist_deployments():
    foundry = _read("infra/terraform/foundry.tf")
    variables = _read("infra/terraform/variables.tf")

    for local_name in (
        "foundry_specialist_agent_names",
        "foundry_specialist_agent_versions",
        "foundry_specialist_deployment",
        "foundry_specialist_role_prompts",
    ):
        assert f"  {local_name} = {{" in foundry
        assert "for id, specialist in local.specialists_by_id" in foundry

    for variable_name in (
        "foundry_agent_name_prefix",
        "foundry_agent_name_suffix",
        "foundry_specialist_release",
    ):
        assert f'variable "{variable_name}"' in variables


def test_terraform_agent_name_projection_reproduces_the_deployed_names():
    manifest = load_specialist_manifest()
    variables = _read("infra/terraform/variables.tf")

    prefix = re.search(
        r'variable "foundry_agent_name_prefix".*?default\s*=\s*"([^"]*)"',
        variables,
        flags=re.DOTALL,
    )
    suffix = re.search(
        r'variable "foundry_agent_name_suffix".*?default\s*=\s*"([^"]*)"',
        variables,
        flags=re.DOTALL,
    )
    assert prefix and suffix

    derived = {
        specialist.id: f"{prefix.group(1)}{specialist.foundry.name}{suffix.group(1)}"
        for specialist in manifest.specialists
    }

    assert len(set(derived.values())) == 12
    # The eight already-deployed agent names must be reproduced exactly so the
    # migration adds four agents instead of orphaning eight.
    assert {
        specialist_id: derived[specialist_id] for specialist_id in LEGACY_SPECIALIST_IDS
    } == {
        "network": "aiops-network-agent",
        "vulnerability": "aiops-vulnerability-agent",
        "patch": "aiops-patch-agent",
        "incident": "aiops-incident-agent",
        "change": "aiops-change-agent",
        "governance": "aiops-governance-agent",
        "remediation": "aiops-remediation-agent",
        "executive_summary": "aiops-executive-summary-agent",
    }


# ---------------------------------------------------------------------------
# Container Apps metadata
# ---------------------------------------------------------------------------


def test_container_apps_env_is_manifest_derived_for_all_twelve_specialists():
    container_apps = _read("infra/terraform/container_apps.tf")

    assert "local.foundry_specialist_deployment" in container_apps
    assert "AIOPS_SPECIALIST_MANIFEST_DIGEST" in container_apps
    # The per-specialist name/version env pairs the API runtime reads must be
    # generated, not hand-listed for eight of twelve specialists.
    hardcoded = sorted(
        specialist_id
        for specialist_id in LOCKED_SPECIALIST_IDS
        if f'"FOUNDRY_{specialist_id.upper()}_AGENT_NAME"' in container_apps
    )

    assert hardcoded == []
    assert 'lookup(var.foundry_specialists, "network"' not in container_apps


def test_legacy_eight_specialist_terraform_inputs_remain_accepted():
    variables = _read("infra/terraform/variables.tf")
    container_apps = _read("infra/terraform/container_apps.tf")

    block = _hcl_block(variables, 'variable "foundry_specialists"')
    for specialist_id in LEGACY_SPECIALIST_IDS:
        assert f"{specialist_id} " in block or f"{specialist_id}=" in block

    # Retained for one migration window: the previous revision's values stay
    # visible to the app so a rollback does not need a Terraform edit.
    assert "FOUNDRY_SPECIALISTS_LEGACY_JSON" in container_apps
    assert "jsonencode(var.foundry_specialists)" in container_apps


# ---------------------------------------------------------------------------
# Offline / live parity gate
# ---------------------------------------------------------------------------


def _parity_module():
    spec = importlib.util.spec_from_file_location(
        "validate_specialist_parity",
        REPO_ROOT / "scripts" / "validate_specialist_parity.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _flatten(value) -> list[str]:
    if isinstance(value, dict):
        return [str(key) for key in value] + [
            item for child in value.values() for item in _flatten(child)
        ]
    if isinstance(value, (list, tuple)):
        return [item for child in value for item in _flatten(child)]
    return [str(value)]


def test_offline_parity_passes_and_reports_only_controlled_identifiers():
    report = _parity_module().run_offline()

    assert report["mode"] == "offline"
    assert report["status"] == "pass"
    assert report["specialist_count"] == 12
    assert report["failures"] == []
    assert sorted(report["specialists"]) == sorted(LOCKED_SPECIALIST_IDS)
    assert all(check["status"] == "pass" for check in report["checks"])


def test_parity_report_never_carries_credentials(monkeypatch):
    monkeypatch.setenv("AZURE_CLIENT_SECRET", "super-secret-value")
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "")

    module = _parity_module()
    tokens = " ".join(
        _flatten(module.run_offline()) + _flatten(module.run_live(env={}))
    ).casefold()

    assert "super-secret-value" not in tokens
    for marker in ("client_secret=", "access_token", "authorization", "bearer "):
        assert marker not in tokens


def test_live_parity_without_configuration_is_blocked_not_passed():
    module = _parity_module()

    report = module.run_live(env={})

    assert report["mode"] == "live"
    assert report["status"] == "blocked"
    assert report["reason"] == "live_parity_not_configured"
    assert "FOUNDRY_PROJECT_ENDPOINT" in report["missing_configuration"]
    assert module.exit_code(report) == module.EXIT_BLOCKED == 3
    # A blocked gate must never be reported as a green promotion signal.
    assert module.exit_code(report) != module.EXIT_PASS


def test_live_catalog_comparison_rejects_extra_missing_and_mutation_grants():
    module = _parity_module()

    assert (
        module.compare_grants(
            specialist_id="network",
            server="operations-mcp",
            expected=("network_topology", "hub_dependents"),
            granted=("network_topology", "hub_dependents"),
            live_catalog=("network_topology", "hub_dependents", "unused_tool"),
        )
        == []
    )

    extra = module.compare_grants(
        specialist_id="network",
        server="operations-mcp",
        expected=("network_topology",),
        granted=("network_topology", "hub_dependents"),
        live_catalog=("network_topology", "hub_dependents"),
    )
    missing = module.compare_grants(
        specialist_id="network",
        server="operations-mcp",
        expected=("network_topology", "hub_dependents"),
        granted=("network_topology",),
        live_catalog=("network_topology", "hub_dependents"),
    )
    nonexistent = module.compare_grants(
        specialist_id="network",
        server="operations-mcp",
        expected=("network_topology",),
        granted=("network_topology",),
        live_catalog=("hub_dependents",),
    )
    mutating = module.compare_grants(
        specialist_id="network",
        server="azure-mcp",
        expected=("advisor_recommendation_apply",),
        granted=("advisor_recommendation_apply",),
        live_catalog=("advisor_recommendation_apply",),
    )

    assert [failure["kind"] for failure in extra] == ["extra_grant"]
    assert [failure["kind"] for failure in missing] == ["missing_grant"]
    assert [failure["kind"] for failure in nonexistent] == ["nonexistent_live_tool"]
    assert "mutation_capable_grant" in {failure["kind"] for failure in mutating}
    assert all(
        set(failure) <= {"kind", "specialist", "server", "tools"}
        for failure in extra + missing + nonexistent + mutating
    )


def test_parity_cli_offline_exits_zero_and_live_unconfigured_exits_blocked():
    offline = subprocess.run(
        [sys.executable, "scripts/validate_specialist_parity.py", "--offline"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    live = subprocess.run(
        [sys.executable, "scripts/validate_specialist_parity.py", "--live"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": "/usr/bin:/bin", "HOME": str(REPO_ROOT)},
    )

    assert offline.returncode == 0
    assert json.loads(offline.stdout)["status"] == "pass"
    assert live.returncode == 3
    assert json.loads(live.stdout)["status"] == "blocked"


# ---------------------------------------------------------------------------
# Additive rollout ordering
# ---------------------------------------------------------------------------


def test_rollout_creates_immutable_versions_before_any_metadata_switch():
    script = _read("infra/scripts/create-foundry-agent.sh")

    create_at = script.index("/versions?api-version=")
    parity_at = script.index("validate_specialist_parity.py")
    promote_at = script.index("FOUNDRY_PROMOTION_RECORD")

    assert create_at < parity_at < promote_at
    # Versions are additive: nothing in the rollout may delete or overwrite a
    # published agent version, so the previous one stays selectable.
    assert "-X DELETE" not in script
    assert "rollback_target" in script
    assert "previous_version" in script


def test_runtime_e2e_gates_promotion_on_parity_and_prints_controlled_fields():
    script = _read("infra/scripts/validate-runtime-e2e.sh")

    parity_at = script.index("validate_specialist_parity.py")
    promotion_at = script.index("promotion")

    assert parity_at < promotion_at
    assert "parity_status" in script
    # Controlled output only: no token, secret, or tool-argument echo.
    for marker in ("$API_TOKEN", "AZURE_CLIENT_SECRET", "echo \"$auth_header\""):
        assert marker not in script


def test_rollout_scripts_have_valid_shell_syntax():
    for script in (
        "infra/scripts/create-foundry-agent.sh",
        "infra/scripts/validate-runtime-e2e.sh",
    ):
        subprocess.run(
            ["bash", "-n", script], cwd=REPO_ROOT, check=True, capture_output=True
        )
