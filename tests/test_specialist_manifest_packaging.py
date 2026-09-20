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
import os
import re
import subprocess
import sys
import tomllib
import urllib.request
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
OPERATIONS_CONNECTION_ID = (
    "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.CognitiveServices/"
    "accounts/account/projects/project/connections/ops-mcp"
)
AZURE_CONNECTION_ID = (
    "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.CognitiveServices/"
    "accounts/account/projects/project/connections/azure-mcp"
)
SEARCH_CONNECTION_ID = (
    "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.CognitiveServices/"
    "accounts/account/projects/project/connections/ai-search"
)

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
        for tool in specialist.operations_mcp_tools
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


def _local_block(source: str, name: str) -> str:
    """Return one top-level ``locals`` assignment, whatever its shape.

    Slices from ``  <name> =`` up to the next sibling assignment at the same
    indentation or the end of the ``locals`` block, so it works for maps,
    ternaries, and single-expression locals alike.
    """

    start = re.search(rf"^  {re.escape(name)}\s*=", source, flags=re.MULTILINE)
    assert start, f"local {name} not found"
    tail = source[start.end() :]
    end = re.search(r"^(  [a-z_][a-z0-9_]*\s*=|\}|resource )", tail, flags=re.MULTILINE)
    return source[start.start() : start.end() + (end.start() if end else len(tail))]


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

    # The active revision reads the *promoted* mapping, never the candidate
    # deployment projection this plan would publish.
    assert "local.foundry_specialist_activation" in container_apps
    assert "local.foundry_specialist_deployment" not in container_apps
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

    # Textual order inside the catalog branch is the execution order: offline
    # parity gates the run before anything is published, the recursive
    # per-specialist invocation then publishes every new immutable version,
    # the *live* gate validates those exact published versions, and only then
    # is the promotion record written.
    offline_at = script.index('"${parity_validator}" --offline')
    create_at = script.index('FOUNDRY_SPECIALISTS_JSON=""')
    live_at = script.index('"${parity_validator}" --live')
    promote_at = script.index("promotion_record_path")

    assert offline_at < create_at < live_at < promote_at
    assert 'agents/${FOUNDRY_AGENT_NAME}/versions?api-version=' in script
    # Versions are additive: nothing in the rollout may delete or overwrite a
    # published agent version, so the previous one stays selectable.
    assert "-X DELETE" not in script
    assert "rollback_target" in script
    assert "previous_version" in script


def test_runtime_e2e_gates_promotion_on_parity_and_prints_controlled_fields():
    script = _read("infra/scripts/validate-runtime-e2e.sh")

    parity_at = script.index('"$PARITY_VALIDATOR" --offline')
    promotion_at = script.index('"promotion": promotion')

    assert parity_at < promotion_at
    assert "parity_status" in script
    assert "az containerapp revision show" in script
    assert "actual != expected" in script
    assert "API_URL host does not exactly match" in script

    # Controlled output only: the final report carries an allowlist of IDs,
    # statuses, and counts, and no line ever echoes a token or secret.
    report = script[script.index("json.dumps(") : script.rindex("indent=2")]
    printed = set(re.findall(r'"([a-z_]+)":', report))
    assert printed == {
        "status",
        "revision",
        "rollout_mode",
        "promotion",
        "parity_status",
        "checks",
        "live_specialist_parity",
        "offline_specialist_parity",
        "runtime_readiness",
        "scoped_topology_isolation",
        "specialist_count",
        "ontology_version",
        "hub_count",
        "spoke_count",
        "providers",
    }
    lowered_report = report.casefold()
    for forbidden in (
        "api_token",
        "auth_header",
        "client_secret",
        "access_token",
        "authorization",
        "bearer ",
    ):
        assert forbidden not in lowered_report
    assert not re.search(
        r"^\s*(echo|printf).*(API_TOKEN|auth_header|CLIENT_SECRET|access_token)",
        script,
        flags=re.MULTILINE,
    )


def _run_runtime_e2e_host_guard(
    tmp_path: Path,
    *,
    api_url: str,
    revision: str = "candidate",
    azure_fqdn: str = "candidate.example.azurecontainerapps.io",
) -> subprocess.CompletedProcess[str]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(exist_ok=True)
    az = fake_bin / "az"
    az.write_text(f"#!/bin/sh\nprintf '%s\\n' '{azure_fqdn}'\n", encoding="utf-8")
    az.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "API_URL": api_url,
        "WEB_URL": "https://web.example.invalid",
        "API_TOKEN": "not-a-real-token",
        "HUB_CONNECTION_ID": "hub",
        "SPOKE_CONNECTION_ID": "spoke",
        "AIOPS_ARG_CONFIG": "arg.yaml",
        "AIOPS_FABRIC_CONFIG": "fabric.yaml",
        "COPILOT_DEPLOYED_REVISION": revision,
        "AZURE_SUBSCRIPTION_ID": "subscription",
        "AZURE_RESOURCE_GROUP": "resource-group",
        "API_APP": "api-app",
        "PARITY_PYTHON": sys.executable,
        "PARITY_VALIDATOR": str(tmp_path / "missing-validator.py"),
    }
    return subprocess.run(
        ["sh", "infra/scripts/validate-runtime-e2e.sh"],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_runtime_e2e_requires_exact_azure_revision_fqdn(tmp_path: Path) -> None:
    valid = _run_runtime_e2e_host_guard(
        tmp_path,
        api_url="https://candidate.example.azurecontainerapps.io",
    )
    assert valid.returncode == 2
    assert "Specialist parity validator not found" in valid.stderr

    for invalid_url in (
        "https://candidate.attacker.invalid",
        "https://shared.example.azurecontainerapps.io",
        "https://other.example.azurecontainerapps.io",
        "http://candidate.example.azurecontainerapps.io",
        "https://user@candidate.example.azurecontainerapps.io",
        "https://candidate.example.azurecontainerapps.io:443",
        "https://candidate.example.azurecontainerapps.io/path",
        "",
        "not-a-url",
    ):
        result = _run_runtime_e2e_host_guard(tmp_path, api_url=invalid_url)
        assert result.returncode != 0
        assert "Specialist parity validator not found" not in result.stderr

    revision_mismatch = _run_runtime_e2e_host_guard(
        tmp_path,
        api_url="https://candidate.example.azurecontainerapps.io",
        revision="other-revision",
    )
    assert revision_mismatch.returncode == 2
    assert "does not identify COPILOT_DEPLOYED_REVISION" in revision_mismatch.stderr


def test_runtime_e2e_uses_bearer_token_without_leaking_it(
    tmp_path: Path,
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    token = "secret-runtime-token"
    curl_log = tmp_path / "curl-args.txt"
    az = fake_bin / "az"
    az.write_text(
        "#!/bin/sh\nprintf '%s\\n' 'candidate.example.azurecontainerapps.io'\n",
        encoding="utf-8",
    )
    az.chmod(0o755)
    aiops = fake_bin / "aiops-inventory"
    aiops.write_text(
        '#!/bin/sh\nprintf \'%s\\n\' \'{"status":"activated","connections":["hub","spoke"],"ontology_version":"v1"}\'\n',
        encoding="utf-8",
    )
    aiops.chmod(0o755)
    parity = tmp_path / "parity.py"
    parity.write_text(
        "import json\nprint(json.dumps({'status':'pass','failures':[],'specialist_count':12}))\n",
        encoding="utf-8",
    )
    curl = fake_bin / "curl"
    curl.write_text(
        """#!/bin/sh
for arg in "$@"; do
  printf '%s\\n' "$arg" >>"$CURL_ARGS_LOG"
  case "$arg" in
    http*) url="$arg" ;;
  esac
done
case "$url" in
  */ready)
    printf '%s\\n' '{"readiness":"ready","last_discovery_run":"t","last_ontology_publication":"t","ontology_version":"v1","providers":{"semantic":{"loaded":true,"state":"ready"},"network":{"loaded":true,"state":"ready"},"vulnerability":{"loaded":true,"state":"ready"},"incidents":{"loaded":true,"state":"ready"},"remediation":{"loaded":true,"state":"ready"}}}'
    ;;
  *subscription_connection=hub)
    printf '%s\\n' '{"scope":{"subscription_connection":["hub"]},"data":{"topology":{"connection_ids":["hub"],"resources":[{"resource_id":"hub-r","connection_id":"hub"}]}}}'
    ;;
  *subscription_connection=spoke)
    printf '%s\\n' '{"scope":{"subscription_connection":["spoke"]},"data":{"topology":{"connection_ids":["spoke"],"resources":[{"resource_id":"spoke-r","connection_id":"spoke"}]}}}'
    ;;
  */network/topology)
    printf '%s\\n' '{"data":{"summary":{"connection_count":2,"hub_count":1,"spoke_count":1}}}'
    ;;
  *) printf '%s\\n' '{}' ;;
esac
""",
        encoding="utf-8",
    )
    curl.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "CURL_ARGS_LOG": str(curl_log),
        "API_URL": "https://candidate.example.azurecontainerapps.io",
        "WEB_URL": "https://web.example.invalid",
        "API_TOKEN": token,
        "HUB_CONNECTION_ID": "hub",
        "SPOKE_CONNECTION_ID": "spoke",
        "AIOPS_ARG_CONFIG": "arg.yaml",
        "AIOPS_FABRIC_CONFIG": "fabric.yaml",
        "COPILOT_DEPLOYED_REVISION": "candidate",
        "COPILOT_ROLLOUT_MODE": "canary",
        "AZURE_SUBSCRIPTION_ID": "subscription",
        "AZURE_RESOURCE_GROUP": "resource-group",
        "API_APP": "api-app",
        "PARITY_PYTHON": sys.executable,
        "PARITY_VALIDATOR": str(parity),
        "AIOPS_CLI": str(aiops),
    }

    result = subprocess.run(
        ["sh", "infra/scripts/validate-runtime-e2e.sh"],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert f"Authorization: Bearer {token}" in curl_log.read_text(encoding="utf-8")
    assert token not in result.stdout
    assert token not in result.stderr
    assert json.loads(result.stdout)["revision"] == "candidate"


def test_rollout_scripts_have_valid_shell_syntax():
    for script in (
        "infra/scripts/create-foundry-agent.sh",
        "infra/scripts/validate-runtime-e2e.sh",
    ):
        subprocess.run(
            ["bash", "-n", script], cwd=REPO_ROOT, check=True, capture_output=True
        )


# ---------------------------------------------------------------------------
# Promotion boundary: create -> validate -> promote
#
# A candidate version published by *this* apply must not be able to activate
# in the same unvalidated step. The active Container Apps revision may only
# consume a previously validated, persisted provider-ID mapping; without one
# it must fall back to the legacy eight-agent set.
# ---------------------------------------------------------------------------

PROMOTION_GATE_RESOURCE = 'resource "terraform_data" "foundry_specialist_promotion_gate"'


def test_terraform_declares_a_reviewed_validated_promotion_artifact_input():
    variables = _read("infra/terraform/variables.tf")

    assert 'variable "foundry_specialist_promotion_artifact"' in variables
    block = _hcl_block(variables, 'variable "foundry_specialist_promotion_artifact"')
    # Absent by default: a fresh environment must not activate anything the
    # current apply just created.
    assert re.search(r'default\s*=\s*""', block)


def test_promotion_gate_requires_exact_twelve_provider_id_mapping():
    foundry = _read("infra/terraform/foundry.tf")

    assert PROMOTION_GATE_RESOURCE in foundry
    gate = foundry[foundry.index(PROMOTION_GATE_RESOURCE) :]

    # The gate is a real Terraform validation resource, not a comment.
    assert "precondition" in gate
    for local_name in (
        "foundry_promotion_status_ok",
        "foundry_promotion_digest_ok",
        "foundry_promotion_ids_ok",
        "foundry_promotion_ids_complete",
        "foundry_promotion_no_candidate_ids",
    ):
        assert f"  {local_name} = " in foundry
        assert f"local.{local_name}" in gate

    # Exact mapping: the promoted key set must equal the manifest's specialist
    # IDs, and every entry must carry a non-empty provider version ID.
    assert "keys(local.specialists_by_id)" in foundry
    assert "provider_version_id" in foundry
    # The digest ties the validated mapping to the exact reviewed manifest.
    assert "local.specialist_manifest_digest" in foundry


def test_activation_never_uses_a_candidate_synthetic_version():
    foundry = _read("infra/terraform/foundry.tf")

    activation = _local_block(foundry, "foundry_specialist_activation")
    # Synthetic manifest-derived stamps are candidates only; the activated
    # version must be an actual provider version ID.
    assert "foundry_specialist_agent_versions" not in activation
    assert "provider_version_id" in activation
    # ... and a crafted artifact restating a candidate stamp is rejected.
    no_candidate = _local_block(foundry, "foundry_promotion_no_candidate_ids")
    assert "values(local.foundry_specialist_agent_versions)" in no_candidate


def test_activation_falls_back_to_unversioned_legacy_eight_without_artifact():
    foundry = _read("infra/terraform/foundry.tf")

    activation = _local_block(foundry, "foundry_specialist_activation")
    assert "local.foundry_promotion_validated" in activation
    assert "var.foundry_specialists" in activation
    assert "legacy_unversioned" in activation
    assert 'version = ""' in activation


def test_container_app_revision_depends_on_the_promotion_gate():
    container_apps = _read("infra/terraform/container_apps.tf")

    api = container_apps[container_apps.index('resource "azurerm_container_app" "api"') :]
    depends_on = api[api.index("depends_on = [") : api.index("]", api.index("depends_on = ["))]

    assert "terraform_data.foundry_specialist_promotion_gate" in depends_on
    # The activation source is observable on the running revision.
    assert "AIOPS_SPECIALIST_ACTIVATION_SOURCE" in container_apps
    assert "local.foundry_specialist_activation_source" in container_apps


def test_foundry_rollout_retriggers_for_promotion_path_and_gate_implementation():
    foundry = _read("infra/terraform/foundry.tf")
    rollout = foundry[
        foundry.index('resource "terraform_data" "foundry_agent"') :
        foundry.index(PROMOTION_GATE_RESOURCE)
    ]
    triggers = rollout[
        rollout.index("triggers_replace = {") :
        rollout.index("\n  }", rollout.index("triggers_replace = {"))
    ]

    assert "promotion_artifact" in triggers
    assert "local.foundry_promotion_artifact_path" in triggers
    assert "rollout_script" in triggers
    assert "create-foundry-agent.sh" in triggers
    assert "parity_validator" in triggers
    assert "validate_specialist_parity.py" in triggers
    assert triggers.count("filesha256(") >= 2


def test_candidate_publication_is_explicitly_staged_and_safe_by_default():
    variables = _read("infra/terraform/variables.tf")
    foundry = _read("infra/terraform/foundry.tf")

    publish = _hcl_block(
        variables, 'variable "enable_foundry_specialist_candidate_publish"'
    )
    verified = _hcl_block(
        variables, 'variable "foundry_version_pinning_runtime_verified"'
    )
    assert re.search(r"default\s*=\s*false", publish)
    assert re.search(r"default\s*=\s*false", verified)

    rollout = foundry[
        foundry.index('resource "terraform_data" "foundry_agent"') :
        foundry.index(PROMOTION_GATE_RESOURCE)
    ]
    assert (
        "var.create_foundry_agent && var.enable_foundry_specialist_candidate_publish"
        in rollout
    )
    assert "var.foundry_version_pinning_runtime_verified" in rollout
    assert "condition     = var.enable_foundry_knowledge_search" in rollout
    assert (
        "Specialist candidate publication requires the governed Azure AI Search"
        in rollout
    )
    assert "azurerm_container_app.api" in rollout


def test_specialist_candidate_payload_is_operations_mcp_plus_search_only():
    foundry = _read("infra/terraform/foundry.tf")
    manifest_payload = json.loads(_read("src/operations/specialists.v1.json"))
    start = foundry.index("  foundry_specialists_json = jsonencode({")
    end = foundry.index("\n\n  # Ontology curation", start)
    payload_projection = foundry[start:end]
    publisher = _read("infra/scripts/create-foundry-agent.sh")
    outputs = _read("infra/terraform/outputs.tf")
    exporter = _read("scripts/export_copilot_provider_env.py")

    assert all(
        "azure_mcp_tools" not in specialist
        for specialist in manifest_payload["specialists"]
    )
    assert "local.foundry_mcp_tool_config" in payload_projection
    assert "local.foundry_ai_search_tool_config" in payload_projection
    assert "foundry_azure_mcp_tool_config" not in payload_projection
    assert 'server_label          = "azure-mcp"' not in foundry
    assert '"azure-mcp"' not in publisher
    assert "AZURE_MCP_SERVER_URL" not in outputs
    assert "FOUNDRY_AZURE_MCP_CONNECTION_ID" not in outputs
    assert "AZURE_MCP_SERVER_URL" not in exporter
    assert "FOUNDRY_AZURE_MCP_CONNECTION_ID" not in exporter


def test_activation_selector_supports_validated_active_and_rollback_maps():
    variables = _read("infra/terraform/variables.tf")
    foundry = _read("infra/terraform/foundry.tf")

    selector = _hcl_block(
        variables, 'variable "foundry_specialist_activation_target"'
    )
    assert '"legacy"' in selector
    assert '"active"' in selector
    assert '"rollback"' in selector
    assert re.search(r'default\s*=\s*"legacy"', selector)

    activation = _local_block(foundry, "foundry_specialist_activation")
    assert "foundry_specialist_activation_target" in activation
    assert "foundry_promoted_agents" in activation
    assert "foundry_rollback_agents" in activation
    assert "provider_version_id" in activation

    for local_name in (
        "foundry_promoted_coordinator",
        "foundry_coordinator_validated",
        "foundry_rollback_ids_ok",
        "foundry_rollback_ids_complete",
        "foundry_rollback_no_candidate_ids",
        "foundry_rollback_coordinator_validated",
        "foundry_rollback_validated",
        "foundry_activation_selection_valid",
        "foundry_coordinator_activation",
    ):
        assert re.search(rf"^\s*{local_name}\s*=", foundry, flags=re.MULTILINE)


def test_promotion_gate_validates_only_the_mapping_selected_for_activation():
    foundry = _read("infra/terraform/foundry.tf")
    gate = foundry[foundry.index(PROMOTION_GATE_RESOURCE) :]

    active_guard = (
        'lower(var.foundry_specialist_activation_target) != "active" ||'
    )
    rollback_guard = (
        'lower(var.foundry_specialist_activation_target) != "rollback" ||'
    )
    assert gate.count(active_guard) >= 5
    assert rollback_guard in gate
    assert "local.foundry_rollback_status_ok" in gate
    assert "local.foundry_rollback_digest_ok" in gate
    assert "local.foundry_rollback_ids_complete" in gate
    assert "local.foundry_rollback_coordinator_validated" in gate


def test_pinned_activation_emits_the_validated_shared_coordinator_version():
    foundry = _read("infra/terraform/foundry.tf")
    container_apps = _read("infra/terraform/container_apps.tf")

    coordinator = _local_block(foundry, "foundry_coordinator_activation")
    assert "foundry_promoted_coordinator" in coordinator
    assert "foundry_rollback_coordinator" in coordinator
    assert "provider_version_id" in coordinator
    assert "foundry_coordinator_artifact.provider_version_id" in coordinator
    assert 'name  = "FOUNDRY_AGENT_VERSION"' in container_apps
    assert "local.foundry_coordinator_activation.version" in container_apps


def test_legacy_specialists_can_use_a_separately_pinned_coordinator():
    variables = _read("infra/terraform/variables.tf")
    foundry = _read("infra/terraform/foundry.tf")

    assert 'variable "foundry_coordinator_activation_artifact"' in variables
    assert 'variable "enable_foundry_coordinator_candidate_publish"' in variables
    coordinator = _local_block(foundry, "foundry_coordinator_activation")
    assert "local.foundry_coordinator_artifact.provider_version_id" in coordinator
    assert '"coordinator_pinned"' in coordinator
    assert 'resource "terraform_data" "foundry_coordinator_candidate"' in foundry
    assert "publish-foundry-coordinator.sh" in foundry
    assert "validate_foundry_coordinator.py" in foundry
    assert "validation_digest" in foundry
    assert "synthesis_probe" in foundry
    assert "supersedes_unusable_versions" in foundry

    publisher = _read("infra/scripts/publish-foundry-coordinator.sh")
    assert "FOUNDRY_COORDINATOR_PYTHON" in publisher
    assert ".venv/bin/python" in publisher
    assert "validator interpreter lacks repository dependencies" in publisher


def test_coordinator_validator_sends_the_supplied_foundry_token(monkeypatch):
    module_path = REPO_ROOT / "scripts" / "validate_foundry_coordinator.py"
    spec = importlib.util.spec_from_file_location(
        "validate_foundry_coordinator",
        module_path,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    observed = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return b"{}"

    def urlopen(request, timeout):
        observed["authorization"] = request.get_header("Authorization")
        observed["timeout"] = timeout
        return Response()

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)

    assert module._request_json(
        "https://example.test",
        token="test-foundry-token",
    ) == {}
    assert observed == {
        "authorization": "Bearer test-foundry-token",
        "timeout": 90,
    }


def test_rollback_rotation_uses_an_explicit_stable_epoch():
    variables = _read("infra/terraform/variables.tf")
    foundry = _read("infra/terraform/foundry.tf")

    rotate = _hcl_block(
        variables, 'variable "foundry_specialist_rollback_rotation"'
    )
    assert re.search(r'default\s*=\s*""', rotate)
    assert "FOUNDRY_ROLLBACK_ROTATION" in foundry
    assert "rollback_rotation" in foundry


def test_legacy_migration_does_not_send_synthetic_versions():
    foundry = _read("infra/terraform/foundry.tf")
    container_apps = _read("infra/terraform/container_apps.tf")

    activation = _local_block(foundry, "foundry_specialist_activation")
    assert 'version = ""' in activation
    assert "legacy_unversioned" in activation
    assert "foundry_specialist_agent_versions" not in activation

    version_env = container_apps[
        container_apps.index('name  = "FOUNDRY_${upper(env.key)}_AGENT_VERSION"') - 180 :
        container_apps.index('name  = "FOUNDRY_${upper(env.key)}_AGENT_VERSION"') + 180
    ]
    assert 'if agent.version != ""' in version_env
    assert "AIOPS_FOUNDRY_VERSION_PINNING_REQUIRED" in container_apps


# ---------------------------------------------------------------------------
# Actual immutable provider IDs captured from create/version responses
# ---------------------------------------------------------------------------

CREATE_AGENT_SCRIPT = REPO_ROOT / "infra" / "scripts" / "create-foundry-agent.sh"

_CURL_STUB = """#!/usr/bin/env bash
set -eu
if [ -n "${STUB_CURL_ARGS:-}" ]; then
  printf '%s\\n' "$@" >>"$STUB_CURL_ARGS"
fi
for arg in "$@"; do
  case "$arg" in
    @*)
      if [ "$(cat "${arg#@}")" = "Authorization: Bearer ${STUB_EXPECTED_TOKEN:-stub-token}" ]; then
        printf 'valid\\n' >>"$STUB_AUTH_RESULT"
      else
        printf 'invalid\\n' >>"$STUB_AUTH_RESULT"
      fi
      ;;
  esac
done
for arg in "$@"; do
  case "$arg" in
    *login.microsoftonline.com*)
      printf '%s' '{"access_token": "stub-token"}'
      exit 0
      ;;
  esac
done
printf 'create\\n' >>"$STUB_CREATE_LOG"
n=$(wc -l <"$STUB_CREATE_LOG" | tr -d ' ')
out=""
prev=""
for arg in "$@"; do
  if [ "$prev" = "-o" ]; then out="$arg"; fi
  prev="$arg"
done
if [ -n "$out" ]; then
  sed "s/__N__/${n}/g" "$STUB_RESPONSE_FILE" >"$out"
fi
printf '%s' "${STUB_HTTP_STATUS:-201}"
"""

_AZ_STUB = """#!/usr/bin/env bash
set -eu
if [ -n "${STUB_AZ_ARGS:-}" ]; then
  printf '%s\\n' "$@" >>"$STUB_AZ_ARGS"
fi
printf '%s' "${STUB_AZ_TOKEN-stub-token}"
"""

_VALIDATOR_STUB = """import json, os, sys

mode = sys.argv[1] if len(sys.argv) > 1 else "--offline"
if mode == "--selftest":
    sys.exit(int(os.environ.get("STUB_SELFTEST_EXIT", "0")))
if mode == "--offline":
    sys.exit(int(os.environ.get("STUB_OFFLINE_EXIT", "0")))
log = os.environ.get("STUB_LIVE_LOG")
if log:
    mapping_path = os.environ.get("FOUNDRY_CANDIDATE_MAPPING", "")
    payload = {"argv": sys.argv[1:], "mapping_path": mapping_path}
    if mapping_path and os.path.exists(mapping_path):
        payload["mapping"] = json.load(open(mapping_path, encoding="utf-8"))
    with open(log, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
sys.exit(int(os.environ.get("STUB_LIVE_EXIT", "0")))
"""


def _rollout_fixture(tmp_path, *, response: dict, specialists: dict | None = None):
    """Build a stubbed environment for infra/scripts/create-foundry-agent.sh."""

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    curl = bin_dir / "curl"
    curl.write_text(_CURL_STUB, encoding="utf-8")
    curl.chmod(0o755)
    az = bin_dir / "az"
    az.write_text(_AZ_STUB, encoding="utf-8")
    az.chmod(0o755)

    response_file = tmp_path / "response.json"
    response_file.write_text(json.dumps(response), encoding="utf-8")

    validator = tmp_path / "stub_validator.py"
    validator.write_text(_VALIDATOR_STUB, encoding="utf-8")

    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(tmp_path),
        "FOUNDRY_PROJECT_ENDPOINT": "https://example.services.ai.azure.com/api/projects/ops",
        "FOUNDRY_AGENT_NAME": "operations-copilot",
        "FOUNDRY_AGENT_MODEL": "gpt-5-4-mini",
        "FOUNDRY_AGENT_PROMPT": "prompt",
        "AZURE_TENANT_ID": "tenant",
        "AZURE_CLIENT_ID": "client",
        "AZURE_CLIENT_SECRET": "secret",
        "STUB_CREATE_LOG": str(tmp_path / "create.log"),
        "STUB_CURL_ARGS": str(tmp_path / "curl-args.log"),
        "STUB_AUTH_RESULT": str(tmp_path / "auth-result.log"),
        "STUB_AZ_ARGS": str(tmp_path / "az-args.log"),
        "STUB_RESPONSE_FILE": str(response_file),
        "STUB_LIVE_LOG": str(tmp_path / "live.json"),
        "FOUNDRY_PARITY_VALIDATOR": str(validator),
        "FOUNDRY_PARITY_PYTHON": sys.executable,
        "FOUNDRY_SPECIALIST_MANIFEST_DIGEST": "digest-abc",
        "FOUNDRY_SPECIALIST_RELEASE": "2026.09",
        "FOUNDRY_OPERATIONS_MCP_CONNECTION_ID": (
            OPERATIONS_CONNECTION_ID
        ),
        "FOUNDRY_AI_SEARCH_CONNECTION_ID": SEARCH_CONNECTION_ID,
        "FOUNDRY_AI_SEARCH_INDEX_NAME": "aiops-knowledge",
        "OPERATIONS_MCP_SERVER_URL": "https://apim.example.net/operations-mcp",
    }
    (tmp_path / "create.log").write_text("", encoding="utf-8")
    (tmp_path / "curl-args.log").write_text("", encoding="utf-8")
    (tmp_path / "auth-result.log").write_text("", encoding="utf-8")
    (tmp_path / "az-args.log").write_text("", encoding="utf-8")

    if specialists is not None:
        env["FOUNDRY_SPECIALISTS_JSON"] = json.dumps(specialists)
    return env


def _run_rollout(env, tmp_path):
    return subprocess.run(
        [str(CREATE_AGENT_SCRIPT)],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _twelve_specialists():
    manifest = load_specialist_manifest()
    return {
        specialist.id: {
            "name": f"aiops-{specialist.foundry.name}-agent",
            "version": f"2026.09.{specialist.foundry.version}",
            "model": "gpt-5-4-mini",
            "prompt": "role prompt",
            "tools": [
                {
                    "type": "mcp",
                    "server_label": "operations-mcp",
                    "server_url": "https://apim.example.net/operations-mcp",
                    "require_approval": "never",
                    "project_connection_id": OPERATIONS_CONNECTION_ID,
                    "allowed_tools": list(specialist.operations_mcp_tools),
                },
                {
                    "type": "azure_ai_search",
                    "azure_ai_search": {
                        "indexes": [
                            {
                                "project_connection_id": SEARCH_CONNECTION_ID,
                                "index_name": "aiops-knowledge",
                                "query_type": "vector_semantic_hybrid",
                            }
                        ]
                    },
                },
            ],
        }
        for specialist in manifest.specialists
    }


def test_create_agent_supports_explicit_azure_cli_auth_without_client_secret(
    tmp_path,
):
    env = _rollout_fixture(
        tmp_path,
        response={"name": "operations-copilot", "version": "provider-1"},
    )
    env["FOUNDRY_AUTH_MODE"] = "azure_cli"
    env.pop("AZURE_TENANT_ID")
    env.pop("AZURE_CLIENT_ID")
    env.pop("AZURE_CLIENT_SECRET")

    result = _run_rollout(env, tmp_path)

    assert result.returncode == 0, result.stderr
    az_args = (tmp_path / "az-args.log").read_text(encoding="utf-8")
    assert "get-access-token" in az_args
    assert "https://ai.azure.com" in az_args
    curl_args = (tmp_path / "curl-args.log").read_text(encoding="utf-8")
    assert "stub-token" not in curl_args
    assert "secret" not in curl_args
    assert "stub-token" not in result.stdout
    assert "stub-token" not in result.stderr
    assert (tmp_path / "auth-result.log").read_text(encoding="utf-8") == "valid\n"


def test_create_agent_rejects_azure_cli_auth_when_az_is_missing(tmp_path):
    env = _rollout_fixture(
        tmp_path,
        response={"name": "operations-copilot", "version": "provider-1"},
    )
    env["FOUNDRY_AUTH_MODE"] = "azure_cli"
    env.pop("AZURE_TENANT_ID")
    env.pop("AZURE_CLIENT_ID")
    env.pop("AZURE_CLIENT_SECRET")
    (tmp_path / "bin" / "az").unlink()

    result = _run_rollout(env, tmp_path)

    assert result.returncode != 0
    assert "az is required" in result.stderr.casefold()
    assert (tmp_path / "create.log").read_text(encoding="utf-8") == ""


def test_create_agent_rejects_unknown_auth_mode_before_provider_io(tmp_path):
    env = _rollout_fixture(
        tmp_path,
        response={"name": "operations-copilot", "version": "provider-1"},
    )
    env["FOUNDRY_AUTH_MODE"] = "unknown"

    result = _run_rollout(env, tmp_path)

    assert result.returncode != 0
    assert "unsupported foundry_auth_mode" in result.stderr.casefold()
    assert (tmp_path / "create.log").read_text(encoding="utf-8") == ""
    assert (tmp_path / "az-args.log").read_text(encoding="utf-8") == ""


def test_create_agent_rejects_empty_azure_cli_token_before_provider_io(tmp_path):
    env = _rollout_fixture(
        tmp_path,
        response={"name": "operations-copilot", "version": "provider-1"},
    )
    env["FOUNDRY_AUTH_MODE"] = "azure_cli"
    env["STUB_AZ_TOKEN"] = ""
    env.pop("AZURE_TENANT_ID")
    env.pop("AZURE_CLIENT_ID")
    env.pop("AZURE_CLIENT_SECRET")

    result = _run_rollout(env, tmp_path)

    assert result.returncode != 0
    assert "empty access token" in result.stderr.casefold()
    assert (tmp_path / "create.log").read_text(encoding="utf-8") == ""


def test_create_agent_keeps_client_secret_and_token_out_of_curl_arguments(tmp_path):
    env = _rollout_fixture(
        tmp_path,
        response={"name": "operations-copilot", "version": "provider-1"},
    )
    env["FOUNDRY_AUTH_MODE"] = "client_credentials"
    env["AZURE_CLIENT_SECRET"] = "s3cr3t-value-123"

    result = _run_rollout(env, tmp_path)

    assert result.returncode == 0, result.stderr
    curl_args = (tmp_path / "curl-args.log").read_text(encoding="utf-8")
    assert env["AZURE_CLIENT_SECRET"] not in curl_args
    assert "stub-token" not in curl_args
    assert env["AZURE_CLIENT_SECRET"] not in result.stdout
    assert env["AZURE_CLIENT_SECRET"] not in result.stderr
    assert "stub-token" not in result.stdout
    assert "stub-token" not in result.stderr
    assert (tmp_path / "auth-result.log").read_text(encoding="utf-8") == "valid\n"


def test_create_agent_requires_secret_for_client_credentials_before_provider_io(
    tmp_path,
):
    env = _rollout_fixture(
        tmp_path,
        response={"name": "operations-copilot", "version": "provider-1"},
    )
    env["FOUNDRY_AUTH_MODE"] = "client_credentials"
    env.pop("AZURE_CLIENT_SECRET")

    result = _run_rollout(env, tmp_path)

    assert result.returncode != 0
    assert "azure_client_secret is required" in result.stderr.casefold()
    assert (tmp_path / "create.log").read_text(encoding="utf-8") == ""


def test_create_agent_auth_contract_never_enables_xtrace():
    script = CREATE_AGENT_SCRIPT.read_text(encoding="utf-8")

    assert "set -x" not in script


def test_create_agent_records_the_actual_provider_version_id(tmp_path):
    env = _rollout_fixture(
        tmp_path,
        response={
            "name": "aiops-network-agent",
            "version": "prov-__N__",
            "id": "/agents/aiops-network-agent/versions/prov-__N__",
        },
    )
    record = tmp_path / "versions.tsv"
    env.update(
        {
            "FOUNDRY_AGENT_NAME": "aiops-network-agent",
            "FOUNDRY_AGENT_SPECIALIST_ID": "network",
            "FOUNDRY_AGENT_VERSION": "2026.09.1",
            "FOUNDRY_AGENT_VERSION_RECORD": str(record),
        }
    )

    result = _run_rollout(env, tmp_path)

    assert result.returncode == 0, result.stderr
    row = record.read_text(encoding="utf-8").strip().split("\t")
    # id/name/actual provider version id/candidate contract stamp
    assert row[0] == "network"
    assert row[1] == "aiops-network-agent"
    assert row[2] == "prov-1"
    assert row[3] == "2026.09.1"
    # The synthetic manifest stamp is never stored as the provider ID.
    assert row[2] != row[3]


def test_create_agent_normalizes_a_path_shaped_provider_id(tmp_path):
    env = _rollout_fixture(
        tmp_path,
        response={
            "name": "aiops-network-agent",
            "id": "/agents/aiops-network-agent/versions/prov-__N__",
        },
    )
    record = tmp_path / "versions.tsv"
    env.update(
        {
            "FOUNDRY_AGENT_NAME": "aiops-network-agent",
            "FOUNDRY_AGENT_SPECIALIST_ID": "network",
            "FOUNDRY_AGENT_VERSION": "2026.09.1",
            "FOUNDRY_AGENT_VERSION_RECORD": str(record),
        }
    )

    result = _run_rollout(env, tmp_path)

    assert result.returncode == 0, result.stderr
    assert record.read_text(encoding="utf-8").strip().split("\t")[2] == "prov-1"


def test_create_agent_normalizes_a_path_shaped_version_field(tmp_path):
    env = _rollout_fixture(
        tmp_path,
        response={
            "name": "aiops-network-agent",
            "version": "agents/aiops-network-agent/versions/prov-__N__",
            "id": "/agents/aiops-network-agent/versions/prov-__N__",
        },
    )
    record = tmp_path / "versions.tsv"
    env.update(
        {
            "FOUNDRY_AGENT_NAME": "aiops-network-agent",
            "FOUNDRY_AGENT_SPECIALIST_ID": "network",
            "FOUNDRY_AGENT_VERSION": "2026.09.1",
            "FOUNDRY_AGENT_VERSION_RECORD": str(record),
        }
    )

    result = _run_rollout(env, tmp_path)

    assert result.returncode == 0, result.stderr
    assert record.read_text(encoding="utf-8").strip().split("\t")[2] == "prov-1"


@pytest.mark.parametrize(
    "response",
    [
        {"name": "aiops-network-agent"},
        {"name": "aiops-network-agent", "id": "/agents/aiops-network-agent"},
        {"name": "aiops-network-agent", "version": ""},
        {"name": "aiops-network-agent", "version": {"nested": "no"}},
        {"name": "aiops-network-agent", "version": "has space"},
    ],
)
def test_create_agent_fails_closed_without_a_usable_provider_version_id(
    tmp_path, response
):
    env = _rollout_fixture(tmp_path, response=response)
    record = tmp_path / "versions.tsv"
    env.update(
        {
            "FOUNDRY_AGENT_NAME": "aiops-network-agent",
            "FOUNDRY_AGENT_SPECIALIST_ID": "network",
            "FOUNDRY_AGENT_VERSION": "2026.09.1",
            "FOUNDRY_AGENT_VERSION_RECORD": str(record),
        }
    )

    result = _run_rollout(env, tmp_path)

    assert result.returncode != 0
    assert "provider version id" in result.stderr.casefold()
    assert not record.exists() or record.read_text(encoding="utf-8").strip() == ""


def test_candidate_publication_requires_operations_mcp_connection_id(
    tmp_path,
):
    env = _rollout_fixture(
        tmp_path,
        response={"name": "agent", "version": "prov-__N__"},
        specialists=_twelve_specialists(),
    )
    env.pop("FOUNDRY_OPERATIONS_MCP_CONNECTION_ID")

    missing = _run_rollout(env, tmp_path)

    assert missing.returncode != 0
    assert "Operations MCP project connection ID is required" in missing.stderr
    assert (tmp_path / "create.log").read_text(encoding="utf-8") == ""

    env["FOUNDRY_OPERATIONS_MCP_CONNECTION_ID"] = "operations-mcp"
    malformed = _run_rollout(env, tmp_path)

    assert malformed.returncode != 0
    assert "Operations MCP project connection ID is required" in malformed.stderr
    assert (tmp_path / "create.log").read_text(encoding="utf-8") == ""


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("server_url", "https://apim.example.net/azure-mcp"),
        ("require_approval", "always"),
    ],
)
def test_candidate_publication_rejects_operations_mcp_boundary_drift(
    tmp_path, field, value
):
    specialists = _twelve_specialists()
    specialists["network"]["tools"][0][field] = value
    env = _rollout_fixture(
        tmp_path,
        response={"name": "agent", "version": "prov-__N__"},
        specialists=specialists,
    )

    result = _run_rollout(env, tmp_path)

    assert result.returncode != 0
    assert "Operations MCP boundary mismatch" in result.stderr
    assert (tmp_path / "create.log").read_text(encoding="utf-8") == ""


def test_rollout_validates_and_promotes_only_actual_provider_ids(tmp_path):
    env = _rollout_fixture(
        tmp_path,
        response={"name": "agent", "version": "prov-__N__"},
        specialists=_twelve_specialists(),
    )
    promotion = tmp_path / "promotion.json"
    previous = {
        specialist_id: {
            "agent_name": f"aiops-{specialist_id}-agent",
            "provider_version_id": f"old-{specialist_id}",
        }
        for specialist_id in LEGACY_SPECIALIST_IDS
    }
    promotion.write_text(
        json.dumps(
            {
                "status": "validated",
                "promotion": "promoted",
                "manifest_digest": "digest-old",
                "agents": previous,
                "coordinator": {
                    "agent_name": "operations-copilot",
                    "provider_version_id": "old-coordinator",
                },
            }
        ),
        encoding="utf-8",
    )
    env["FOUNDRY_PROMOTION_RECORD"] = str(promotion)

    result = _run_rollout(env, tmp_path)

    assert result.returncode == 0, result.stderr

    # The live gate validated the exact captured provider IDs, not "latest".
    live = json.loads((tmp_path / "live.json").read_text(encoding="utf-8"))
    assert live["mapping_path"]
    mapping = live["mapping"]["agents"]
    assert sorted(mapping) == sorted(LOCKED_SPECIALIST_IDS)
    assert all(
        entry["provider_version_id"].startswith("prov-") for entry in mapping.values()
    )
    assert len({entry["provider_version_id"] for entry in mapping.values()}) == 12
    assert live["mapping"]["coordinator"]["provider_version_id"].startswith("prov-")

    record = json.loads(promotion.read_text(encoding="utf-8"))
    assert record["status"] == "validated"
    assert record["promotion"] == "promoted"
    assert record["manifest_digest"] == "digest-abc"
    assert sorted(record["agents"]) == sorted(LOCKED_SPECIALIST_IDS)
    assert record["coordinator"]["agent_name"] == "operations-copilot"
    assert record["coordinator"]["provider_version_id"].startswith("prov-")
    assert all(
        entry["provider_version_id"].startswith("prov-")
        for entry in record["agents"].values()
    )
    # No synthetic release label is ever promoted as a provider ID.
    assert all(
        not entry["provider_version_id"].startswith("2026.")
        for entry in record["agents"].values()
    )
    # The previously promoted mapping is retained as the rollback target.
    assert record["rollback_target"] == previous
    assert record["rollback_coordinator"]["provider_version_id"] == "old-coordinator"
    assert record["rollback_manifest_digest"] == "digest-old"


def test_later_publications_do_not_advance_rollback_without_explicit_rotation(
    tmp_path,
):
    env = _rollout_fixture(
        tmp_path,
        response={"name": "agent", "version": "prov-__N__"},
        specialists=_twelve_specialists(),
    )
    promotion = tmp_path / "promotion.json"
    stable_rollback = {
        specialist_id: {
            "agent_name": f"aiops-{specialist_id}-agent",
            "provider_version_id": f"rollback-{specialist_id}",
        }
        for specialist_id in LOCKED_SPECIALIST_IDS
    }
    stable_coordinator = {
        "agent_name": "operations-copilot",
        "provider_version_id": "rollback-coordinator",
    }
    current_active = {
        specialist_id: {
            "agent_name": f"aiops-{specialist_id}-agent",
            "provider_version_id": f"active-{specialist_id}",
        }
        for specialist_id in LOCKED_SPECIALIST_IDS
    }
    current_coordinator = {
        "agent_name": "operations-copilot",
        "provider_version_id": "active-coordinator",
    }
    promotion.write_text(
        json.dumps(
            {
                "status": "validated",
                "promotion": "promoted",
                "manifest_digest": "digest-abc",
                "agents": current_active,
                "coordinator": current_coordinator,
                "rollback_target": stable_rollback,
                "rollback_coordinator": stable_coordinator,
                "rollback_manifest_digest": "digest-abc",
            }
        ),
        encoding="utf-8",
    )
    env["FOUNDRY_PROMOTION_RECORD"] = str(promotion)

    first = _run_rollout(env, tmp_path)
    second = _run_rollout(env, tmp_path)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    record = json.loads(promotion.read_text(encoding="utf-8"))
    assert record["rollback_target"] == stable_rollback
    assert record["rollback_coordinator"] == stable_coordinator


def test_corrupt_promotion_artifact_halts_without_publish_or_overwrite(tmp_path):
    env = _rollout_fixture(
        tmp_path,
        response={"name": "agent", "version": "prov-__N__"},
        specialists=_twelve_specialists(),
    )
    promotion = tmp_path / "promotion.json"
    corrupt = '{"status":"validated","agents":'
    promotion.write_text(corrupt, encoding="utf-8")
    env["FOUNDRY_PROMOTION_RECORD"] = str(promotion)

    result = _run_rollout(env, tmp_path)

    assert result.returncode != 0
    assert "promotion artifact" in result.stderr.casefold()
    assert promotion.read_text(encoding="utf-8") == corrupt
    assert (tmp_path / "create.log").read_text(encoding="utf-8") == ""


def test_promotion_artifact_is_replaced_atomically():
    script = _read("infra/scripts/create-foundry-agent.sh")
    writer = script[script.index("promotion_record_path =") :]

    assert "tempfile.NamedTemporaryFile" in writer
    assert "os.replace(" in writer
    assert "promotion_record_path.write_text" not in writer


def test_new_rotation_epoch_advances_rollback_once(tmp_path):
    env = _rollout_fixture(
        tmp_path,
        response={"name": "agent", "version": "prov-__N__"},
        specialists=_twelve_specialists(),
    )
    promotion = tmp_path / "promotion.json"
    active = {
        specialist_id: {
            "agent_name": f"aiops-{specialist_id}-agent",
            "provider_version_id": f"active-{specialist_id}",
        }
        for specialist_id in LOCKED_SPECIALIST_IDS
    }
    coordinator = {
        "agent_name": "operations-copilot",
        "provider_version_id": "active-coordinator",
    }
    promotion.write_text(
        json.dumps(
            {
                "status": "validated",
                "promotion": "promoted",
                "manifest_digest": "digest-abc",
                "agents": active,
                "coordinator": coordinator,
                "rollback_target": {},
                "rollback_coordinator": {},
                "rollback_manifest_digest": "",
            }
        ),
        encoding="utf-8",
    )
    env.update(
        {
            "FOUNDRY_PROMOTION_RECORD": str(promotion),
            "FOUNDRY_ROLLBACK_ROTATION": "epoch-2",
        }
    )

    first = _run_rollout(env, tmp_path)
    after_first = json.loads(promotion.read_text(encoding="utf-8"))
    second = _run_rollout(env, tmp_path)
    after_second = json.loads(promotion.read_text(encoding="utf-8"))

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert after_first["rollback_target"] == active
    assert after_first["rollback_coordinator"] == coordinator
    assert after_first["rollback_rotation"] == "epoch-2"
    assert after_second["rollback_target"] == active
    assert after_second["rollback_coordinator"] == coordinator


def test_blocked_live_parity_holds_promotion_and_preserves_the_validated_mapping(
    tmp_path,
):
    env = _rollout_fixture(
        tmp_path,
        response={"name": "agent", "version": "prov-__N__"},
        specialists=_twelve_specialists(),
    )
    env["STUB_LIVE_EXIT"] = "3"
    promotion = tmp_path / "promotion.json"
    previous = {
        specialist_id: {
            "agent_name": f"aiops-{specialist_id}-agent",
            "provider_version_id": f"old-{specialist_id}",
        }
        for specialist_id in LEGACY_SPECIALIST_IDS
    }
    promotion.write_text(
        json.dumps(
            {
                "status": "validated",
                "promotion": "promoted",
                "manifest_digest": "digest-old",
                "agents": previous,
                "coordinator": {
                    "agent_name": "operations-copilot",
                    "provider_version_id": "old-coordinator",
                },
            }
        ),
        encoding="utf-8",
    )
    env["FOUNDRY_PROMOTION_RECORD"] = str(promotion)

    result = _run_rollout(env, tmp_path)

    assert result.returncode == 0, result.stderr
    record = json.loads(promotion.read_text(encoding="utf-8"))

    assert record["promotion"] == "held"
    # A held rollout never moves candidates into the activated position and
    # never destroys the mapping the running revision depends on.
    assert record["agents"] == previous
    assert record["manifest_digest"] == "digest-old"
    assert record["candidate"]["promotion"] == "held"
    assert record["candidate"]["reason"] == "live_parity_blocked"
    assert sorted(record["candidate"]["agents"]) == sorted(LOCKED_SPECIALIST_IDS)


def test_failed_live_parity_fails_the_rollout(tmp_path):
    env = _rollout_fixture(
        tmp_path,
        response={"name": "agent", "version": "prov-__N__"},
        specialists=_twelve_specialists(),
    )
    env["STUB_LIVE_EXIT"] = "1"

    result = _run_rollout(env, tmp_path)

    assert result.returncode == 1
    assert "live specialist parity failed" in result.stderr.casefold()


# ---------------------------------------------------------------------------
# Deploy interpreter and validator availability
# ---------------------------------------------------------------------------


def test_parity_interpreter_defaults_to_the_repo_venv_with_an_override():
    script = _read("infra/scripts/create-foundry-agent.sh")

    assert '${repo_root}/.venv/bin/python' in script
    assert "FOUNDRY_PARITY_PYTHON" in script
    # The override must win over the default when supplied.
    default_at = script.index('${repo_root}/.venv/bin/python')
    override_at = script.index('-n "${FOUNDRY_PARITY_PYTHON:-}"')
    assert override_at < default_at


def test_unavailable_validator_holds_promotion_without_claiming_a_mismatch(tmp_path):
    env = _rollout_fixture(
        tmp_path,
        response={"name": "agent", "version": "prov-__N__"},
        specialists=_twelve_specialists(),
    )
    # Interpreter/import failure, not a parity mismatch.
    env["STUB_SELFTEST_EXIT"] = "9"
    candidate = tmp_path / "promotion.json.candidate"
    env["FOUNDRY_CANDIDATE_RECORD"] = str(candidate)

    result = _run_rollout(env, tmp_path)

    assert result.returncode == 0, result.stderr
    stderr = result.stderr.casefold()
    assert "validator_unavailable" in stderr or "validator unavailable" in stderr
    assert "parity failed" not in stderr
    assert "mismatch" not in stderr
    assert "held" in result.stdout.casefold()


def test_unavailable_validator_does_not_republish_versions_on_re_run(tmp_path):
    env = _rollout_fixture(
        tmp_path,
        response={"name": "agent", "version": "prov-__N__"},
        specialists=_twelve_specialists(),
    )
    env["STUB_SELFTEST_EXIT"] = "9"
    env["FOUNDRY_CANDIDATE_RECORD"] = str(tmp_path / "promotion.json.candidate")

    first = _run_rollout(env, tmp_path)
    creates_after_first = len(
        (tmp_path / "create.log").read_text(encoding="utf-8").split()
    )
    second = _run_rollout(env, tmp_path)
    creates_after_second = len(
        (tmp_path / "create.log").read_text(encoding="utf-8").split()
    )

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert creates_after_first == 13
    # No publication churn: the same unvalidated candidate set is not
    # republished while the validator stays unavailable.
    assert creates_after_second == creates_after_first


# ---------------------------------------------------------------------------
# Token audiences, URL safety, and failure classification
# ---------------------------------------------------------------------------


def _live_env(**overrides) -> dict[str, str]:
    env = {
        "FOUNDRY_PROJECT_ENDPOINT": "https://example.services.ai.azure.com/api/projects/ops",
        "AZURE_TENANT_ID": "tenant",
        "AZURE_CLIENT_ID": "client",
        "AZURE_CLIENT_SECRET": "secret",
        "OPERATIONS_MCP_SERVER_URL": "https://apim.example.net/operations-mcp",
        "MCP_APIM_AUDIENCE": "api://aiops-apim",
        "FOUNDRY_CANDIDATE_MAPPING": "",
        "FOUNDRY_AI_SEARCH_CONNECTION_ID": SEARCH_CONNECTION_ID,
        "FOUNDRY_AI_SEARCH_INDEX_NAME": "aiops-knowledge",
    }
    env.update(overrides)
    return env


def _candidate_mapping_file(tmp_path, provider_id="prov-1") -> str:
    manifest = load_specialist_manifest()
    path = tmp_path / "candidate.json"
    path.write_text(
        json.dumps(
            {
                "agents": {
                    specialist.id: {
                        "agent_name": f"aiops-{specialist.foundry.name}-agent",
                        "provider_version_id": provider_id,
                    }
                    for specialist in manifest.specialists
                },
                "coordinator": {
                    "agent_name": "operations-copilot",
                    "provider_version_id": provider_id,
                },
                "connections": {
                    "operations-mcp": {
                        "project_connection_id": OPERATIONS_CONNECTION_ID,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    return str(path)


def test_apim_audience_is_required_configuration_for_live_parity():
    module = _parity_module()

    report = module.run_live(env=_live_env(MCP_APIM_AUDIENCE=""))

    assert report["status"] == "blocked"
    assert report["reason"] == "live_parity_not_configured"
    assert "MCP_APIM_AUDIENCE" in report["missing_configuration"]


def test_live_parity_azure_cli_mode_does_not_require_client_secret_env(tmp_path):
    module = _parity_module()
    report = module.run_live(
        env=_live_env(
            FOUNDRY_AUTH_MODE="azure_cli",
            AZURE_TENANT_ID="",
            AZURE_CLIENT_ID="",
            AZURE_CLIENT_SECRET="",
            FOUNDRY_CANDIDATE_MAPPING=str(tmp_path / "missing.json"),
        )
    )

    assert report["status"] == "fail"
    assert report["reason"] == "candidate_mapping_invalid"


def test_live_parity_blocks_disabled_ai_search_configuration(tmp_path):
    module = _parity_module()
    report = module.run_live(
        env=_live_env(
            FOUNDRY_AUTH_MODE="azure_cli",
            AZURE_TENANT_ID="",
            AZURE_CLIENT_ID="",
            AZURE_CLIENT_SECRET="",
            FOUNDRY_AI_SEARCH_CONNECTION_ID="",
            FOUNDRY_AI_SEARCH_INDEX_NAME="",
            FOUNDRY_CANDIDATE_MAPPING=str(tmp_path / "missing.json"),
        )
    )

    assert report["status"] == "blocked"
    assert "FOUNDRY_AI_SEARCH_CONNECTION_ID" in report["missing_configuration"]
    assert "FOUNDRY_AI_SEARCH_INDEX_NAME" in report["missing_configuration"]


def test_live_parity_rejects_partial_ai_search_configuration():
    module = _parity_module()
    report = module.run_live(
        env=_live_env(FOUNDRY_AI_SEARCH_INDEX_NAME="")
    )

    assert report["status"] == "blocked"
    assert "FOUNDRY_AI_SEARCH_INDEX_NAME" in report["missing_configuration"]


@pytest.mark.parametrize(
    "missing_name",
    ["AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET"],
)
def test_live_parity_client_secret_mode_requires_all_credentials(missing_name):
    module = _parity_module()
    env = _live_env()
    env[missing_name] = ""

    report = module.run_live(env=env)

    assert report["status"] == "blocked"
    assert missing_name in report["missing_configuration"]


def test_live_access_token_uses_explicit_azure_cli_scope(monkeypatch):
    module = _parity_module()
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="token-value\n", stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    token = module._access_token(
        {"FOUNDRY_AUTH_MODE": "azure_cli"},
        scope="https://ai.azure.com/.default",
    )

    assert token == "token-value"
    assert calls == [
        (
            [
                "az",
                "account",
                "get-access-token",
                "--scope",
                "https://ai.azure.com/.default",
                "--query",
                "accessToken",
                "--output",
                "tsv",
            ],
            {
                "check": False,
                "capture_output": True,
                "text": True,
            },
        )
    ]


def test_live_parity_uses_separate_foundry_and_apim_tokens(tmp_path, monkeypatch):
    module = _parity_module()
    scopes: list[str] = []
    authorizations: dict[str, str] = {}

    def fake_token(env, *, scope):
        scopes.append(scope)
        return f"token-for-{scope}"

    def fake_post(url, payload, headers):
        authorizations[url] = headers["Authorization"]
        return {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}

    def fake_get(url, headers):
        authorizations[url] = headers["Authorization"]
        if "/connections?" in url:
            return {
                "value": [
                    {"id": OPERATIONS_CONNECTION_ID},
                    {"id": AZURE_CONNECTION_ID},
                    {"id": SEARCH_CONNECTION_ID},
                ]
            }
        return {"value": []}

    monkeypatch.setattr(module, "_access_token", fake_token)
    monkeypatch.setattr(module, "_post_json", fake_post)
    monkeypatch.setattr(module, "_get_json", fake_get)

    env = _live_env(FOUNDRY_CANDIDATE_MAPPING=_candidate_mapping_file(tmp_path))
    module.run_live(env=env)

    assert len(scopes) == 2
    assert len(set(scopes)) == 2
    assert "https://ai.azure.com/.default" in scopes
    assert "api://aiops-apim/.default" in scopes

    apim_token = "token-for-api://aiops-apim/.default"
    foundry_token = "token-for-https://ai.azure.com/.default"
    for url, header in authorizations.items():
        expected = apim_token if "apim.example.net" in url else foundry_token
        assert header.endswith(expected), url
    # The Foundry token must never be presented to the APIM MCP endpoints.
    assert not any(
        foundry_token in header
        for url, header in authorizations.items()
        if "apim.example.net" in url
    )


@pytest.mark.parametrize(
    "variable",
    ["OPERATIONS_MCP_SERVER_URL", "FOUNDRY_PROJECT_ENDPOINT"],
)
def test_live_parity_refuses_to_send_credentials_over_plain_http(
    tmp_path, monkeypatch, variable
):
    module = _parity_module()
    called: list[str] = []
    monkeypatch.setattr(
        module,
        "_access_token",
        lambda env, *, scope: called.append(scope) or "token",
    )

    env = _live_env(
        FOUNDRY_CANDIDATE_MAPPING=_candidate_mapping_file(tmp_path),
        **{variable: "http://insecure.example.net/mcp"},
    )
    report = module.run_live(env=env)

    assert report["status"] == "fail"
    assert module.exit_code(report) == module.EXIT_FAIL
    assert {failure["kind"] for failure in report["failures"]} == {
        "insecure_service_url"
    }
    # No token may be acquired, let alone sent, before the URL is proven safe.
    assert called == []


@pytest.mark.parametrize("status", [401, 403, 500])
def test_live_auth_and_service_failures_are_fail_not_blocked(
    tmp_path, monkeypatch, status
):
    module = _parity_module()
    monkeypatch.setattr(module, "_access_token", lambda env, *, scope: "token")

    def raise_http(url, payload, headers):
        raise module.urllib.error.HTTPError(url, status, "denied", {}, None)

    monkeypatch.setattr(module, "_post_json", raise_http)

    env = _live_env(FOUNDRY_CANDIDATE_MAPPING=_candidate_mapping_file(tmp_path))
    report = module.run_live(env=env)

    assert report["status"] == "fail"
    assert report["status"] != "blocked"
    assert module.exit_code(report) == module.EXIT_FAIL
    kinds = {failure["kind"] for failure in report["failures"]}
    expected = "live_auth_rejected" if status in (401, 403) else "live_service_error"
    assert kinds == {expected}
    assert all(failure["status"] == status for failure in report["failures"])
    # Controlled fields only -- no token, header, or URL is reported.
    assert all(
        set(failure) <= {"kind", "service", "status", "error_type"}
        for failure in report["failures"]
    )
    reported = " ".join(_flatten(report)).casefold()
    assert "token" not in reported
    assert "authorization" not in reported


# ---------------------------------------------------------------------------
# Pinned provider version validation
# ---------------------------------------------------------------------------


def _live_module_with_versions(monkeypatch, module, entries):
    manifest = load_specialist_manifest()
    operations_tools = sorted(
        {
            tool
            for specialist in manifest.specialists
            for tool in specialist.operations_mcp_tools
        }
    )
    monkeypatch.setattr(module, "_access_token", lambda env, *, scope: "token")
    monkeypatch.setattr(
        module,
        "_post_json",
        lambda url, payload, headers: {
            "result": {
                "tools": [{"name": name} for name in operations_tools]
            }
        },
    )
    bound_entries = json.loads(json.dumps(entries))
    for entry in bound_entries:
        definition = entry.get("definition") or {}
        definition["tools"] = [
            tool
            for tool in definition.get("tools", [])
            if tool.get("server_label") != "azure-mcp"
        ]
        for tool in definition.get("tools", []):
            if tool.get("server_label") == "operations-mcp":
                tool["project_connection_id"] = OPERATIONS_CONNECTION_ID
                tool["server_url"] = "https://apim.example.net/operations-mcp"
                tool["require_approval"] = "never"
        if not any(
            tool.get("type") == "azure_ai_search"
            for tool in definition.get("tools", [])
        ):
            definition.setdefault("tools", []).append(
                {
                    "type": "azure_ai_search",
                    "azure_ai_search": {
                        "indexes": [
                            {
                                "project_connection_id": SEARCH_CONNECTION_ID,
                                "index_name": "aiops-knowledge",
                                "query_type": "vector_semantic_hybrid",
                            }
                        ]
                    },
                }
            )

    def fake_get(url, headers):
        if "/connections?" in url:
            return {
                "value": [
                    {"id": OPERATIONS_CONNECTION_ID},
                    {"id": SEARCH_CONNECTION_ID},
                ]
            }
        if "/agents/operations-copilot/" in url:
            return {
                "value": [
                    {
                        "version": entry.get("version"),
                        "definition": {
                            "model": (entry.get("definition") or {}).get("model"),
                        },
                    }
                    for entry in bound_entries
                ]
            }
        return {"value": bound_entries}

    monkeypatch.setattr(module, "_get_json", fake_get)


def test_live_parity_validates_the_pinned_version_not_the_last_entry(
    tmp_path, monkeypatch
):
    module = _parity_module()
    manifest = load_specialist_manifest()
    network = next(s for s in manifest.specialists if s.id == "network")

    pinned_definition = {
        "tools": [
            {
                "type": "mcp",
                "server_label": "operations-mcp",
                "allowed_tools": list(network.operations_mcp_tools),
            },
        ]
    }
    # entries[-1] is a *newer, unvalidated* version with a widened grant. If
    # the validator looked at the last entry it would fail; pinning must make
    # it look only at prov-1.
    entries = [
        {"version": "prov-1", "definition": pinned_definition},
        {
            "version": "prov-99",
            "definition": {
                "tools": [
                    {
                        "type": "mcp",
                        "server_label": "operations-mcp",
                        "allowed_tools": list(network.operations_mcp_tools)
                        + ["defender_alerts"],
                    }
                ]
            },
        },
    ]
    _live_module_with_versions(monkeypatch, module, entries)

    env = _live_env(
        FOUNDRY_CANDIDATE_MAPPING=_candidate_mapping_file(tmp_path, "prov-1")
    )
    report = module.run_live(env=env)

    network_failures = [
        failure
        for failure in report["failures"]
        if failure.get("specialist") == "network"
    ]
    assert network_failures == []
    assert all(
        observation["provider_version_id"] == "prov-1"
        for observation in report["observed"]
    )


def test_live_parity_fails_when_the_pinned_version_is_absent(tmp_path, monkeypatch):
    module = _parity_module()
    _live_module_with_versions(
        monkeypatch, module, [{"version": "some-other-id", "definition": {}}]
    )

    env = _live_env(
        FOUNDRY_CANDIDATE_MAPPING=_candidate_mapping_file(tmp_path, "prov-1")
    )
    report = module.run_live(env=env)

    assert report["status"] == "fail"
    kinds = {failure["kind"] for failure in report["failures"]}
    assert "pinned_version_missing" in kinds
    missing = next(
        failure for failure in report["failures"] if failure["kind"] == "pinned_version_missing"
    )
    assert missing["provider_version_id"] == "prov-1"


def test_live_parity_requires_the_pinned_shared_coordinator(tmp_path, monkeypatch):
    module = _parity_module()
    manifest = load_specialist_manifest()
    entries = [
        {
            "version": "prov-1",
            "definition": {
                "tools": [
                    {
                        "type": "mcp",
                        "server_label": "operations-mcp",
                        "allowed_tools": list(manifest.specialists[0].operations_mcp_tools),
                    },
                ]
            },
        }
    ]

    def fake_get(url, headers):
        if "/connections?" in url:
            return {
                "value": [
                    {"id": OPERATIONS_CONNECTION_ID},
                    {"id": AZURE_CONNECTION_ID},
                    {"id": SEARCH_CONNECTION_ID},
                ]
            }
        if "/agents/operations-copilot/" in url:
            return {"value": []}
        return {"value": entries}

    monkeypatch.setattr(module, "_access_token", lambda env, *, scope: "token")
    monkeypatch.setattr(module, "_live_tool_catalog", lambda url, token: ())
    monkeypatch.setattr(module, "_get_json", fake_get)

    report = module.run_live(
        env=_live_env(
            FOUNDRY_CANDIDATE_MAPPING=_candidate_mapping_file(tmp_path, "prov-1")
        )
    )

    assert any(
        failure.get("specialist") == "operations_copilot"
        and failure["kind"] == "pinned_version_missing"
        for failure in report["failures"]
    )


def test_live_provider_version_normalization_matches_rollout_capture():
    module = _parity_module()

    assert (
        module._entry_provider_version_id(
            {
                "version": "agents/network/versions/provider-42",
                "id": "/agents/network/versions/provider-42",
            }
        )
        == "provider-42"
    )
    assert (
        module._entry_provider_version_id(
            {
                "version": "has space",
                "id": "/agents/network/versions/provider-42",
            }
        )
        == "provider-42"
    )
    assert module._entry_provider_version_id({"id": "/agents/network"}) == ""


@pytest.mark.parametrize("payload", [None, [], {"value": {}}, {"value": [None]}])
def test_live_version_entries_reject_malformed_envelopes(payload):
    module = _parity_module()

    with pytest.raises((TypeError, ValueError)):
        module._version_entries(payload)


@pytest.mark.parametrize(
    "payload",
    [None, [], {"result": []}, {"result": {"tools": {}}}, {"result": {"tools": [None]}}],
)
def test_live_tool_catalog_rejects_malformed_envelopes(monkeypatch, payload):
    module = _parity_module()
    monkeypatch.setattr(module, "_post_json", lambda url, body, headers: payload)

    with pytest.raises((TypeError, ValueError)):
        module._live_tool_catalog(
            "https://apim.example.net/operations-mcp",
            "token",
        )


def test_live_parity_reports_malformed_catalog_without_raising(
    tmp_path, monkeypatch
):
    module = _parity_module()
    monkeypatch.setattr(module, "_access_token", lambda env, *, scope: "token")
    monkeypatch.setattr(module, "_post_json", lambda url, body, headers: [])

    report = module.run_live(
        env=_live_env(
            FOUNDRY_CANDIDATE_MAPPING=_candidate_mapping_file(tmp_path, "prov-1")
        )
    )

    assert report["status"] == "fail"
    assert report["reason"] == "live_auth_or_service_failure"
    assert report["failures"][0]["error_type"] == "TypeError"


def test_live_parity_reports_malformed_specialist_versions_without_raising(
    tmp_path, monkeypatch
):
    module = _parity_module()
    monkeypatch.setattr(module, "_access_token", lambda env, *, scope: "token")
    monkeypatch.setattr(module, "_live_tool_catalog", lambda url, token: ())

    def fake_get(url, headers):
        if "/connections?" in url:
            return {
                "value": [
                    {"id": OPERATIONS_CONNECTION_ID},
                    {"id": AZURE_CONNECTION_ID},
                    {"id": SEARCH_CONNECTION_ID},
                ]
            }
        if "/agents/operations-copilot/" in url:
            return {
                "value": [
                    {
                        "version": "prov-1",
                        "definition": {"model": "gpt-5.4-mini"},
                    }
                ]
            }
        return []

    monkeypatch.setattr(module, "_get_json", fake_get)

    report = module.run_live(
        env=_live_env(
            FOUNDRY_CANDIDATE_MAPPING=_candidate_mapping_file(tmp_path, "prov-1")
        )
    )

    assert report["status"] == "fail"
    assert report["reason"] == "live_parity_mismatch"
    assert any(
        failure.get("specialist") == "network"
        and failure.get("error_type") == "TypeError"
        for failure in report["failures"]
    )


def test_live_parity_rejects_non_object_candidate_mapping(tmp_path):
    module = _parity_module()
    path = tmp_path / "candidate.json"
    path.write_text("[]", encoding="utf-8")

    report = module.run_live(
        env=_live_env(FOUNDRY_CANDIDATE_MAPPING=str(path))
    )

    assert report["status"] == "fail"
    assert report["reason"] == "candidate_mapping_invalid"


def test_live_parity_requires_operations_and_search_connections(
    tmp_path, monkeypatch
):
    module = _parity_module()
    monkeypatch.setattr(module, "_access_token", lambda env, *, scope: "token")
    monkeypatch.setattr(module, "_live_tool_catalog", lambda url, token: ())
    monkeypatch.setattr(
        module,
        "_get_json",
        lambda url, headers: {
            "value": [
                {
                    "id": (
                        "/subscriptions/sub/resourceGroups/rg/providers/"
                        "Microsoft.CognitiveServices/accounts/account/projects/"
                        "project/connections/demo"
                    )
                }
            ]
        },
    )

    report = module.run_live(
        env=_live_env(
            FOUNDRY_CANDIDATE_MAPPING=_candidate_mapping_file(tmp_path, "prov-1")
        )
    )

    assert report["status"] == "blocked"
    assert report["reason"] == "governed_connections_not_onboarded"
    assert {
        failure["server"] for failure in report["failures"]
    } == {"operations-mcp", "azure_ai_search"}


def test_live_parity_requires_governed_ai_search_connection(
    tmp_path, monkeypatch
):
    module = _parity_module()
    monkeypatch.setattr(module, "_access_token", lambda env, *, scope: "token")
    monkeypatch.setattr(module, "_live_tool_catalog", lambda url, token: ())
    monkeypatch.setattr(
        module,
        "_get_json",
        lambda url, headers: {
            "value": [
                {"id": OPERATIONS_CONNECTION_ID},
                {"id": AZURE_CONNECTION_ID},
            ]
        },
    )

    report = module.run_live(
        env=_live_env(
            FOUNDRY_CANDIDATE_MAPPING=_candidate_mapping_file(tmp_path, "prov-1")
        )
    )

    assert report["status"] == "blocked"
    assert report["reason"] == "governed_connections_not_onboarded"
    assert report["failures"] == [
        {
            "kind": "governed_connection_not_onboarded",
            "server": "azure_ai_search",
        }
    ]


@pytest.mark.parametrize(
    "connection_payload",
    [
        None,
        {},
        {"value": {}},
        {"value": [None]},
        {"value": [{"id": 42}]},
        {"value": [{"id": "not-a-project-connection-id"}]},
    ],
)
def test_live_parity_rejects_malformed_connection_inventory(
    tmp_path, monkeypatch, connection_payload
):
    module = _parity_module()
    monkeypatch.setattr(module, "_access_token", lambda env, *, scope: "token")
    monkeypatch.setattr(module, "_live_tool_catalog", lambda url, token: ())
    monkeypatch.setattr(
        module,
        "_get_json",
        lambda url, headers: connection_payload,
    )

    report = module.run_live(
        env=_live_env(
            FOUNDRY_CANDIDATE_MAPPING=_candidate_mapping_file(tmp_path, "prov-1")
        )
    )

    assert report["status"] == "fail"
    assert report["reason"] == "live_connection_inventory_invalid"
    assert report["failures"][0]["kind"] in {
        "malformed_live_connection_inventory",
        "malformed_live_connection_entry",
    }


def test_live_parity_rejects_duplicate_governed_connection_inventory(
    tmp_path, monkeypatch
):
    module = _parity_module()
    monkeypatch.setattr(module, "_access_token", lambda env, *, scope: "token")
    monkeypatch.setattr(module, "_live_tool_catalog", lambda url, token: ())
    monkeypatch.setattr(
        module,
        "_get_json",
        lambda url, headers: {
            "value": [
                {"id": OPERATIONS_CONNECTION_ID},
                {"id": OPERATIONS_CONNECTION_ID},
                {"id": AZURE_CONNECTION_ID},
                {"id": SEARCH_CONNECTION_ID},
            ]
        },
    )

    report = module.run_live(
        env=_live_env(
            FOUNDRY_CANDIDATE_MAPPING=_candidate_mapping_file(tmp_path, "prov-1")
        )
    )

    assert report["status"] == "fail"
    assert report["reason"] == "live_connection_inventory_invalid"
    assert report["failures"] == [
        {
            "kind": "duplicate_live_connection",
            "count": 1,
        }
    ]


def test_live_parity_rejects_ambiguous_live_connection_terminal_name(
    tmp_path, monkeypatch
):
    module = _parity_module()
    wrong_project_same_name = (
        "/subscriptions/other/resourceGroups/rg/providers/"
        "Microsoft.CognitiveServices/accounts/account/projects/other/"
        "connections/ops-mcp"
    )
    monkeypatch.setattr(module, "_access_token", lambda env, *, scope: "token")
    monkeypatch.setattr(module, "_live_tool_catalog", lambda url, token: ())
    monkeypatch.setattr(
        module,
        "_get_json",
        lambda url, headers: {
            "value": [
                {"id": OPERATIONS_CONNECTION_ID},
                {"id": wrong_project_same_name},
                {"id": AZURE_CONNECTION_ID},
                {"id": SEARCH_CONNECTION_ID},
            ]
        },
    )

    report = module.run_live(
        env=_live_env(
            FOUNDRY_CANDIDATE_MAPPING=_candidate_mapping_file(tmp_path, "prov-1")
        )
    )

    assert report["status"] == "fail"
    assert report["reason"] == "live_connection_inventory_invalid"
    assert report["failures"] == [
        {
            "kind": "governed_connection_ambiguous",
            "server": "operations-mcp",
        }
    ]


def test_live_parity_rejects_wrong_project_terminal_name_when_expected_is_missing(
    tmp_path, monkeypatch
):
    module = _parity_module()
    wrong_project_same_name = (
        "/subscriptions/other/resourceGroups/rg/providers/"
        "Microsoft.CognitiveServices/accounts/account/projects/other/"
        "connections/ops-mcp"
    )
    monkeypatch.setattr(module, "_access_token", lambda env, *, scope: "token")
    monkeypatch.setattr(module, "_live_tool_catalog", lambda url, token: ())
    monkeypatch.setattr(
        module,
        "_get_json",
        lambda url, headers: {
            "value": [
                {"id": wrong_project_same_name},
                {"id": AZURE_CONNECTION_ID},
                {"id": SEARCH_CONNECTION_ID},
            ]
        },
    )

    report = module.run_live(
        env=_live_env(
            FOUNDRY_CANDIDATE_MAPPING=_candidate_mapping_file(tmp_path, "prov-1")
        )
    )

    assert report["status"] == "fail"
    assert report["reason"] == "live_connection_inventory_invalid"
    assert report["failures"] == [
        {
            "kind": "governed_connection_ambiguous",
            "server": "operations-mcp",
        }
    ]


def test_live_parity_rejects_duplicate_expected_connection_id(
    tmp_path, monkeypatch
):
    module = _parity_module()
    monkeypatch.setattr(module, "_access_token", lambda env, *, scope: "token")
    monkeypatch.setattr(module, "_live_tool_catalog", lambda url, token: ())
    monkeypatch.setattr(module, "_get_json", lambda url, headers: {"value": []})

    report = module.run_live(
        env=_live_env(
            FOUNDRY_CANDIDATE_MAPPING=_candidate_mapping_file(tmp_path, "prov-1"),
            FOUNDRY_AI_SEARCH_CONNECTION_ID=OPERATIONS_CONNECTION_ID,
        )
    )

    assert report["status"] == "fail"
    assert report["reason"] == "candidate_mapping_invalid"
    assert report["failures"] == [
        {
            "kind": "governed_connection_identity_duplicate",
        }
    ]


def test_live_parity_rejects_governed_connections_from_different_projects(
    tmp_path, monkeypatch
):
    module = _parity_module()
    monkeypatch.setattr(module, "_access_token", lambda env, *, scope: "token")
    monkeypatch.setattr(module, "_live_tool_catalog", lambda url, token: ())
    monkeypatch.setattr(module, "_get_json", lambda url, headers: {"value": []})
    wrong_project_search = (
        "/subscriptions/other/resourceGroups/rg/providers/"
        "Microsoft.CognitiveServices/accounts/account/projects/other/"
        "connections/ai-search"
    )

    report = module.run_live(
        env=_live_env(
            FOUNDRY_CANDIDATE_MAPPING=_candidate_mapping_file(tmp_path, "prov-1"),
            FOUNDRY_AI_SEARCH_CONNECTION_ID=wrong_project_search,
        )
    )

    assert report["status"] == "fail"
    assert report["reason"] == "candidate_mapping_invalid"
    assert report["failures"] == [
        {
            "kind": "governed_connection_project_mismatch",
        }
    ]


def test_live_parity_rejects_agent_binding_to_wrong_project_connection():
    module = _parity_module()

    failures = module.compare_connection_bindings(
        specialist_id="network",
        expected={
            "operations-mcp": OPERATIONS_CONNECTION_ID,
        },
        actual={
            "operations-mcp": SEARCH_CONNECTION_ID,
        },
    )

    assert failures == [
        {
            "kind": "project_connection_mismatch",
            "specialist": "network",
            "server": "operations-mcp",
        }
    ]


def test_live_parity_accepts_foundry_normalized_mcp_definition():
    module = _parity_module()
    manifest = load_specialist_manifest()
    network = next(s for s in manifest.specialists if s.id == "network")
    definition = {
        "tools": [
            {
                "type": "mcp",
                "server_label": "operations-mcp",
                "allowed_tools": {
                    "tool_names": list(network.operations_mcp_tools),
                },
                "project_connection_id": OPERATIONS_CONNECTION_ID.rsplit("/", 1)[-1],
            },
        ]
    }

    assert module._agent_allowed_tools(definition) == {
        "operations-mcp": network.operations_mcp_tools,
    }
    assert module.compare_connection_bindings(
        specialist_id="network",
        expected={
            "operations-mcp": OPERATIONS_CONNECTION_ID,
        },
        actual=module._agent_connection_ids(definition),
    ) == []
    assert module.validate_agent_mcp_definition(
        specialist_id="network",
        definition=definition,
    ) == []


def test_live_parity_keeps_legacy_mcp_definition_compatible():
    module = _parity_module()
    manifest = load_specialist_manifest()
    network = next(s for s in manifest.specialists if s.id == "network")
    definition = {
        "tools": [
            {
                "type": "mcp",
                "server_label": "operations-mcp",
                "allowed_tools": list(network.operations_mcp_tools),
                "project_connection_id": OPERATIONS_CONNECTION_ID,
            },
        ]
    }

    assert module._agent_allowed_tools(definition) == {
        "operations-mcp": network.operations_mcp_tools,
    }
    assert module.validate_agent_mcp_definition(
        specialist_id="network",
        definition=definition,
    ) == []


def test_live_parity_rejects_injected_azure_mcp_definition():
    module = _parity_module()
    definition = {
        "tools": [
            {
                "type": "mcp",
                "server_label": "operations-mcp",
                "allowed_tools": [],
                "project_connection_id": OPERATIONS_CONNECTION_ID,
            },
            {
                "type": "mcp",
                "server_label": "azure-mcp",
                "allowed_tools": ["subscription_list"],
                "project_connection_id": AZURE_CONNECTION_ID,
            },
        ]
    }

    failures = module.validate_agent_mcp_definition(
        specialist_id="network",
        definition=definition,
    )

    assert failures == [
        {
            "kind": "mcp_tool_definition_mismatch",
            "specialist": "network",
            "unexpected": ["azure-mcp"],
            "missing": [],
            "duplicate": [],
        }
    ]


@pytest.mark.parametrize(
    ("field", "value", "delete", "expected_kind"),
    [
        (
            "server_url",
            "https://apim.example.net/azure-mcp",
            False,
            "mcp_server_url_mismatch",
        ),
        ("require_approval", "always", False, "mcp_approval_policy_mismatch"),
        ("server_url", None, True, "mcp_server_url_mismatch"),
        ("require_approval", None, True, "mcp_approval_policy_mismatch"),
    ],
)
def test_live_parity_rejects_operations_mcp_boundary_drift(
    field, value, delete, expected_kind
):
    module = _parity_module()
    operation = {
        "type": "mcp",
        "server_label": "operations-mcp",
        "server_url": "https://apim.example.net/operations-mcp",
        "require_approval": "never",
        "allowed_tools": [],
        "project_connection_id": OPERATIONS_CONNECTION_ID,
    }
    if delete:
        operation.pop(field)
    else:
        operation[field] = value

    failures = module.validate_agent_mcp_definition(
        specialist_id="network",
        definition={"tools": [operation]},
        expected_operations_mcp_url="https://apim.example.net/operations-mcp",
    )

    assert expected_kind in {failure["kind"] for failure in failures}


@pytest.mark.parametrize(
    ("mutate", "expected_kind"),
    [
        (
            lambda tools: tools.pop(),
            "mcp_tool_definition_mismatch",
        ),
        (
            lambda tools: tools.append(dict(tools[0])),
            "mcp_tool_definition_mismatch",
        ),
        (
            lambda tools: tools.append(
                {
                    "type": "mcp",
                    "server_label": "unexpected-mcp",
                    "allowed_tools": [],
                    "project_connection_id": "unexpected",
                }
            ),
            "mcp_tool_definition_mismatch",
        ),
        (
            lambda tools: tools[0].update(
                allowed_tools={"tool_names": ["network_topology", "network_topology"]}
            ),
            "malformed_mcp_grants",
        ),
        (
            lambda tools: tools[0].update(allowed_tools={}),
            "malformed_mcp_grants",
        ),
        (
            lambda tools: tools[0].update(allowed_tools={"tool_names": None}),
            "malformed_mcp_grants",
        ),
        (
            lambda tools: tools[0].pop("allowed_tools"),
            "malformed_mcp_grants",
        ),
        (
            lambda tools: tools[0].update(allowed_tools=None),
            "malformed_mcp_grants",
        ),
        (
            lambda tools: tools[0].update(allowed_tools=False),
            "malformed_mcp_grants",
        ),
        (
            lambda tools: tools[0].update(allowed_tools="network_topology"),
            "malformed_mcp_grants",
        ),
        (
            lambda tools: tools[0].update(project_connection_id=""),
            "project_connection_mismatch",
        ),
    ],
)
def test_live_parity_rejects_malformed_normalized_mcp_definitions(
    mutate, expected_kind
):
    module = _parity_module()
    tools = [
        {
            "type": "mcp",
            "server_label": "operations-mcp",
            "allowed_tools": {"tool_names": ["network_topology"]},
            "project_connection_id": OPERATIONS_CONNECTION_ID.rsplit("/", 1)[-1],
        },
    ]
    mutate(tools)

    failures = module.validate_agent_mcp_definition(
        specialist_id="network",
        definition={"tools": tools},
    )

    assert expected_kind in {failure["kind"] for failure in failures}


@pytest.mark.parametrize(
    ("definition", "expected_kind"),
    [
        ("not-an-object", "malformed_agent_definition"),
        ({"tools": 42}, "malformed_mcp_tools"),
    ],
)
def test_live_parity_rejects_malformed_agent_definition(
    definition, expected_kind
):
    module = _parity_module()

    failures = module.validate_agent_mcp_definition(
        specialist_id="network",
        definition=definition,
    )

    assert failures == [
        {
            "kind": expected_kind,
            "specialist": "network",
        }
    ]
    assert module._agent_allowed_tools(definition) == {
        "operations-mcp": (),
    }
    assert module._agent_connection_ids(definition) == {
        "operations-mcp": "",
    }


def test_live_parity_accepts_one_exact_azure_ai_search_tool():
    module = _parity_module()
    definition = {
        "tools": [
            {
                "type": "mcp",
                "server_label": "operations-mcp",
                "allowed_tools": [],
                "project_connection_id": OPERATIONS_CONNECTION_ID,
            },
            {
                "type": "azure_ai_search",
                "azure_ai_search": {
                    "indexes": [
                        {
                            "project_connection_id": (
                                OPERATIONS_CONNECTION_ID.rsplit("/", 1)[0]
                                + "/aiops-dev-ai-search"
                            ),
                            "index_name": "aiops-knowledge",
                            "query_type": "vector_semantic_hybrid",
                        }
                    ]
                },
            },
        ]
    }

    assert module.validate_agent_mcp_definition(
        specialist_id="executive_summary",
        definition=definition,
        expected_ai_search_connection_id=(
            OPERATIONS_CONNECTION_ID.rsplit("/", 1)[0]
            + "/aiops-dev-ai-search"
        ),
        expected_ai_search_index_name="aiops-knowledge",
    ) == []


@pytest.mark.parametrize(
    ("connection_id", "index_name"),
    [
        (
            (
                "/subscriptions/other/resourceGroups/rg/providers/"
                "Microsoft.CognitiveServices/accounts/account/projects/project/"
                "connections/aiops-dev-ai-search"
            ),
            "aiops-knowledge",
        ),
        (SEARCH_CONNECTION_ID, "other-index"),
    ],
)
def test_live_parity_rejects_wrong_ai_search_target(connection_id, index_name):
    module = _parity_module()
    definition = {
        "tools": [
            {
                "type": "mcp",
                "server_label": "operations-mcp",
                "allowed_tools": [],
                "project_connection_id": OPERATIONS_CONNECTION_ID,
            },
            {
                "type": "azure_ai_search",
                "azure_ai_search": {
                    "indexes": [
                        {
                            "project_connection_id": connection_id,
                            "index_name": index_name,
                            "query_type": "vector_semantic_hybrid",
                        }
                    ]
                },
            },
        ]
    }

    failures = module.validate_agent_mcp_definition(
        specialist_id="executive_summary",
        definition=definition,
        expected_ai_search_connection_id=SEARCH_CONNECTION_ID,
        expected_ai_search_index_name="aiops-knowledge",
    )

    assert any(
        failure["kind"] == "malformed_azure_ai_search_tool"
        for failure in failures
    )


@pytest.mark.parametrize(
    ("extra_tool", "expected_kind"),
    [
        ({"type": "code_interpreter"}, "unexpected_agent_tool"),
        ({"type": "mcp"}, "project_connection_mismatch"),
        ({"type": "azure_ai_search"}, "unexpected_agent_tool"),
        ("not-an-object", "malformed_agent_tool"),
    ],
)
def test_live_parity_rejects_unreviewed_or_malformed_extra_tools(
    extra_tool, expected_kind
):
    module = _parity_module()
    definition = {
        "tools": [
            {
                "type": "mcp",
                "server_label": "operations-mcp",
                "allowed_tools": [],
                "project_connection_id": OPERATIONS_CONNECTION_ID,
            },
            extra_tool,
        ]
    }

    failures = module.validate_agent_mcp_definition(
        specialist_id="executive_summary",
        definition=definition,
    )

    assert expected_kind in {failure["kind"] for failure in failures}


def test_live_parity_rejects_duplicate_azure_ai_search_tools():
    module = _parity_module()
    search_tool = {
        "type": "azure_ai_search",
        "azure_ai_search": {
            "indexes": [
                {
                    "project_connection_id": (
                        OPERATIONS_CONNECTION_ID.rsplit("/", 1)[0]
                        + "/aiops-dev-ai-search"
                    ),
                    "index_name": "aiops-knowledge",
                    "query_type": "vector_semantic_hybrid",
                }
            ]
        },
    }
    definition = {
        "tools": [
            {
                "type": "mcp",
                "server_label": "operations-mcp",
                "allowed_tools": [],
                "project_connection_id": OPERATIONS_CONNECTION_ID,
            },
            search_tool,
            dict(search_tool),
        ]
    }

    failures = module.validate_agent_mcp_definition(
        specialist_id="executive_summary",
        definition=definition,
    )

    assert any(failure["kind"] == "duplicate_agent_tool" for failure in failures)


@pytest.mark.parametrize(
    "definition",
    [
        {"model": "gpt-5.4-mini"},
        {"model": "gpt-5.4-mini", "tools": []},
    ],
)
def test_live_parity_accepts_toolless_coordinator(definition):
    module = _parity_module()

    assert module.validate_coordinator_definition(definition) == []


@pytest.mark.parametrize(
    "definition",
    [
        "not-an-object",
        {"model": "gpt-5.4-mini", "tools": None},
        {"model": "gpt-5.4-mini", "tools": [{"type": "code_interpreter"}]},
        {
            "model": "gpt-5.4-mini",
            "tools": [
                {
                    "type": "mcp",
                    "server_label": "operations-mcp",
                    "allowed_tools": [],
                }
            ],
        },
    ],
)
def test_live_parity_rejects_coordinator_tools_or_malformed_definition(
    definition,
):
    module = _parity_module()

    assert module.validate_coordinator_definition(definition)


def test_live_parity_accepts_unique_bare_connection_name():
    module = _parity_module()
    common_name = "shared"

    failures = module.compare_connection_bindings(
        specialist_id="network",
        expected={
            "operations-mcp": OPERATIONS_CONNECTION_ID.rsplit("/", 1)[0]
            + f"/{common_name}",
        },
        actual={
            "operations-mcp": common_name,
        },
    )

    assert failures == []


def test_live_parity_fails_when_a_specialist_is_absent_from_the_mapping(
    tmp_path, monkeypatch
):
    module = _parity_module()
    _live_module_with_versions(monkeypatch, module, [])

    path = tmp_path / "partial.json"
    path.write_text(
        json.dumps(
            {
                "agents": {
                    "network": {
                        "agent_name": "aiops-network-agent",
                        "provider_version_id": "prov-1",
                    }
                },
                "coordinator": {
                    "agent_name": "operations-copilot",
                    "provider_version_id": "prov-1",
                },
                "connections": {
                    "operations-mcp": {
                        "project_connection_id": OPERATIONS_CONNECTION_ID,
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    report = module.run_live(env=_live_env(FOUNDRY_CANDIDATE_MAPPING=str(path)))

    assert report["status"] == "fail"
    unpinned = {
        failure["specialist"]
        for failure in report["failures"]
        if failure["kind"] == "pinned_version_absent"
    }
    assert unpinned == set(LOCKED_SPECIALIST_IDS) - {"network"}


# ---------------------------------------------------------------------------
# Model contract
# ---------------------------------------------------------------------------


def test_offline_parity_validates_and_reports_the_model_contract():
    module = _parity_module()
    report = module.run_offline()
    manifest = load_specialist_manifest()

    names = [check["name"] for check in report["checks"]]
    assert "model_contract" in names
    check = next(check for check in report["checks"] if check["name"] == "model_contract")
    assert check["status"] == "pass"

    contract = report["model_contract"]
    assert contract["contract_model"] == manifest.specialists[0].foundry.model
    assert contract["deployment_model_source"] == "var.foundry_model_name"
    # The divergence is an acknowledged, reported distinction -- not dead data
    # described as checked.
    assert contract["divergence"] == "acknowledged_deployment_name_distinct_from_contract_model"


def test_terraform_carries_both_the_deployment_and_contract_model():
    foundry = _read("infra/terraform/foundry.tf")

    assert re.search(
        r"^\s*model\s*=\s*var\.foundry_model_name\s*$", foundry, re.MULTILINE
    )
    assert re.search(
        r"^\s*contract_model\s*=\s*specialist\.foundry\.model\s*$",
        foundry,
        re.MULTILINE,
    )


def test_live_parity_verifies_the_deployed_model_deployment_name(tmp_path, monkeypatch):
    module = _parity_module()
    _live_module_with_versions(
        monkeypatch,
        module,
        [{"version": "prov-1", "definition": {"model": "wrong-deployment", "tools": []}}],
    )

    env = _live_env(
        FOUNDRY_CANDIDATE_MAPPING=_candidate_mapping_file(tmp_path, "prov-1"),
        FOUNDRY_MODEL_DEPLOYMENT_NAME="gpt-5-4-mini",
    )
    report = module.run_live(env=env)

    assert report["status"] == "fail"
    mismatch = [
        failure
        for failure in report["failures"]
        if failure["kind"] == "deployed_model_mismatch"
    ]
    assert mismatch
    assert report["deployment_model_verified"] is True
