#!/usr/bin/env python3
"""Exact offline and live parity gate for the Operations specialist contract.

The committed manifest (``src/operations/specialists.v1.json``) is the single
source of truth for the twelve reviewed specialists. This script proves that
every other authority still agrees with it:

* ``--offline`` compares the manifest against the Python runtime projections,
  the governed Operations MCP catalog, the Azure MCP grants, the API/UI
  catalog projection, the Terraform/Container Apps projection, and the
  packaged artifact layout. It needs no credentials and no network.
* ``--live`` additionally reads the deployed Foundry agent versions and the
  ``tools/list`` catalogs of the Operations and Azure MCP servers, and fails
  on any extra grant, missing grant, grant naming a tool that does not exist
  live, or mutation-capable grant.

Live mode is **read-only**. When the live services are not configured it
reports an explicit ``blocked`` outcome with exit code 3 -- never a pass --
so a promotion cannot be justified by an unverifiable gate.

Exit codes:
    0  pass
    1  fail
    3  blocked (live gate not configured; offline parity still runnable)

Output is a single JSON document containing only specialist IDs, tool names,
server labels, statuses, and counts. No credential, token, endpoint secret, or
tool argument is ever read into the report.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = str(REPO_ROOT / "src")
# Put src/ at the FRONT of sys.path so the repo's own packages win. The
# installed `openai-agents` distribution also provides a top-level `agents`
# package, and site-packages is searched before any .pth-appended entry, so a
# plain "append if missing" would silently resolve `agents.operations` to the
# third-party package. Remove any existing entry first, exactly as
# tests/conftest.py does.
while SRC_ROOT in sys.path:
    sys.path.remove(SRC_ROOT)
sys.path.insert(0, SRC_ROOT)

from operations import specialist_manifest as manifest_module
from operations.autonomous_investigation import AGENTS, agent_catalog
from operations.foundry_agent import SPECIALIST_IDS, specialist_catalog
from operations.mcp_server import (
    REVIEWED_TOOLS,
    reviewed_tools_for_specialist,
)
from operations.specialist_manifest import (
    LOCKED_SPECIALIST_IDS,
    load_specialist_manifest,
)
from operations.tools import TOOL_REGISTRY

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_BLOCKED = 3

PACKAGED_MANIFEST_PATH = "operations/specialists.v1.json"
CONTAINER_MANIFEST_PATH = "/app/src/operations/specialists.v1.json"

OPERATIONS_SERVER_LABEL = "operations-mcp"
AZURE_SERVER_LABEL = "azure-mcp"
CONNECTION_LABELS = (OPERATIONS_SERVER_LABEL, AZURE_SERVER_LABEL)
PROJECT_CONNECTION_ID_PATTERN = re.compile(
    r"^/subscriptions/[^/]+/resourcegroups/[^/]+/providers/"
    r"microsoft\.cognitiveservices/accounts/[^/]+/projects/[^/]+/"
    r"connections/[^/]+$",
    re.IGNORECASE,
)

# Credential-bearing variables are only ever tested for presence. Their values
# are never read into the report, logged, or echoed.
#
# MCP_APIM_AUDIENCE is required, not defaulted: the Foundry data plane and the
# APIM MCP gateway are different services with different audiences, and
# reusing one service's access token against the other both leaks a credential
# across a trust boundary and produces meaningless 401s that look like parity
# failures. FOUNDRY_CANDIDATE_MAPPING is required because the live gate
# validates exact, pinned provider version IDs -- there is no defensible
# "just check the newest one" fallback.
LIVE_REQUIRED_ENV = (
    "FOUNDRY_PROJECT_ENDPOINT",
    "AZURE_TENANT_ID",
    "AZURE_CLIENT_ID",
    "AZURE_CLIENT_SECRET",
    "OPERATIONS_MCP_SERVER_URL",
    "AZURE_MCP_SERVER_URL",
    "MCP_APIM_AUDIENCE",
    "FOUNDRY_CANDIDATE_MAPPING",
)

# Foundry's own data-plane audience. Overridable for sovereign clouds, but it
# is never used for the APIM MCP endpoints.
DEFAULT_FOUNDRY_AUDIENCE = "https://ai.azure.com"

# Service labels used in failure records. These are controlled constants, not
# URLs -- a report never carries an endpoint, token, or header.
FOUNDRY_SERVICE = "foundry"

# Restates the manifest loader's read-only contract so a *live* catalog can be
# screened before any grant is accepted, plus the mutating azmcp verb suffixes
# the loader's pinned read-only allowlist already excludes. Markers are
# deliberately suffix-anchored where a bare word would false-positive on a
# read tool (e.g. arm_get_deployment_status is a read).
MUTATION_MARKERS = (
    "approve",
    "create",
    "delete",
    "execute",
    "mutation",
    "patch_apply",
    "restart",
    "update",
    "write",
    "whatif",
    "_apply",
    "_send",
    "_set",
    "_start",
    "_stop",
)
READ_ONLY_EXECUTE_TOOLS = frozenset({"arm_execute_query"})

HTTP_TIMEOUT_SECONDS = 20


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def is_mutation_capable(tool: str) -> bool:
    """Return whether a tool name reads as mutation-capable."""

    normalized = tool.casefold()
    if normalized in READ_ONLY_EXECUTE_TOOLS:
        return False
    return any(marker in normalized for marker in MUTATION_MARKERS)


def _read(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def _check(name: str, failures: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "name": name,
        "status": "pass" if not failures else "fail",
        "failures": failures,
    }


def _failure(kind: str, **fields: Any) -> dict[str, Any]:
    return {"kind": kind, **fields}


def compare_grants(
    *,
    specialist_id: str,
    server: str,
    expected: tuple[str, ...] | list[str],
    granted: tuple[str, ...] | list[str],
    live_catalog: tuple[str, ...] | list[str],
) -> list[dict[str, Any]]:
    """Compare one specialist's effective grants against the reviewed set.

    Fails on a grant the manifest does not authorize, a manifest grant that is
    absent from the deployment, a grant naming a tool the live server does not
    publish, and any mutation-capable tool in either set. A mismatch never
    widens to the broader set -- it is reported and the promotion is held.
    """

    expected_set = set(expected)
    granted_set = set(granted)
    live_set = set(live_catalog)
    failures: list[dict[str, Any]] = []

    extra = sorted(granted_set - expected_set)
    if extra:
        failures.append(
            _failure("extra_grant", specialist=specialist_id, server=server, tools=extra)
        )

    missing = sorted(expected_set - granted_set)
    if missing:
        failures.append(
            _failure(
                "missing_grant", specialist=specialist_id, server=server, tools=missing
            )
        )

    nonexistent = sorted((expected_set | granted_set) - live_set)
    if nonexistent:
        failures.append(
            _failure(
                "nonexistent_live_tool",
                specialist=specialist_id,
                server=server,
                tools=nonexistent,
            )
        )

    mutating = sorted(
        tool for tool in expected_set | granted_set if is_mutation_capable(tool)
    )
    if mutating:
        failures.append(
            _failure(
                "mutation_capable_grant",
                specialist=specialist_id,
                server=server,
                tools=mutating,
            )
        )

    return failures


# ---------------------------------------------------------------------------
# Offline checks
# ---------------------------------------------------------------------------


def _check_runtime_projection(manifest) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []

    if manifest.specialist_ids != LOCKED_SPECIALIST_IDS:
        failures.append(_failure("locked_portfolio_mismatch"))
    if SPECIALIST_IDS != LOCKED_SPECIALIST_IDS:
        failures.append(_failure("foundry_specialist_ids_mismatch"))

    expected = {item["id"]: item for item in manifest.runtime_projection()}
    actual = {agent.id: agent.to_dict() for agent in AGENTS}
    if actual != expected:
        failures.append(
            _failure(
                "runtime_projection_mismatch",
                specialists=sorted(
                    specialist_id
                    for specialist_id in set(expected) | set(actual)
                    if expected.get(specialist_id) != actual.get(specialist_id)
                ),
            )
        )
    return _check("runtime_projection", failures)


def _check_operations_grants(manifest) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []

    if set(REVIEWED_TOOLS) != set(TOOL_REGISTRY):
        failures.append(_failure("reviewed_catalog_registry_mismatch"))

    for specialist_id, expected in manifest.operations_mcp_grants().items():
        failures.extend(
            compare_grants(
                specialist_id=specialist_id,
                server=OPERATIONS_SERVER_LABEL,
                expected=expected,
                granted=reviewed_tools_for_specialist(specialist_id),
                live_catalog=tuple(TOOL_REGISTRY),
            )
        )
    return _check("operations_mcp_grants", failures)


def _check_azure_grants(manifest) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []

    for specialist_id, expected in manifest.azure_mcp_grants().items():
        mutating = sorted(tool for tool in expected if is_mutation_capable(tool))
        if mutating:
            failures.append(
                _failure(
                    "mutation_capable_grant",
                    specialist=specialist_id,
                    server=AZURE_SERVER_LABEL,
                    tools=mutating,
                )
            )
    return _check("azure_mcp_grants", failures)


def _check_api_catalog(manifest) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    expected = {item["id"]: item for item in manifest.catalog_projection()}

    runtime = {
        specialist_id: {
            key: value
            for key, value in entry.items()
            if key in {"id", "display_name", "purpose", "ui_metadata", "page_mappings"}
        }
        for specialist_id, entry in (
            (item["id"], item) for item in agent_catalog()
        )
    }
    if runtime != expected:
        failures.append(_failure("api_catalog_mismatch"))

    foundry_ids = {item["id"] for item in specialist_catalog()}
    if foundry_ids != set(LOCKED_SPECIALIST_IDS):
        failures.append(_failure("foundry_catalog_mismatch"))

    pages = manifest.page_mapping_projection()
    unmapped = sorted(
        specialist.id
        for specialist in manifest.specialists
        if not any(specialist.id in candidates for candidates in pages.values())
    )
    if unmapped:
        failures.append(_failure("unmapped_specialist", specialists=unmapped))
    return _check("api_catalog_and_page_mappings", failures)


def _terraform_registry_keys(foundry_tf: str) -> set[str]:
    start = foundry_tf.index("  foundry_tool_registry = {")
    block = foundry_tf[start : foundry_tf.index("\n  }\n", start)]
    return set(
        re.findall(
            r"^\s{4}([a-z][a-z0-9_-]*)\s*=\s*\{\s*server\s*=", block, flags=re.MULTILINE
        )
    )


def _check_terraform_projection(manifest) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    foundry_tf = _read("infra/terraform/foundry.tf")
    container_tf = _read("infra/terraform/container_apps.tf")
    variables_tf = _read("infra/terraform/variables.tf")

    if "jsondecode(file(local.specialist_manifest_path))" not in foundry_tf:
        failures.append(_failure("terraform_does_not_decode_manifest"))

    tool_names = {
        tool
        for specialist in manifest.specialists
        for tool in (*specialist.operations_mcp_tools, *specialist.azure_mcp_tools)
    }
    restated = sorted(tool for tool in tool_names if f'"{tool}"' in foundry_tf)
    if restated:
        failures.append(_failure("terraform_restates_grants", tools=restated))

    registry = _terraform_registry_keys(foundry_tf)
    if registry != tool_names:
        failures.append(
            _failure(
                "terraform_registry_mismatch",
                tools=sorted(registry.symmetric_difference(tool_names)),
            )
        )

    for local_name in (
        "foundry_specialist_agent_names",
        "foundry_specialist_agent_versions",
        "foundry_specialist_deployment",
        "foundry_specialist_role_prompts",
    ):
        if f"  {local_name} = {{" not in foundry_tf:
            failures.append(_failure("terraform_missing_projection", tools=[local_name]))

    if "local.foundry_specialist_activation" not in container_tf:
        failures.append(_failure("container_apps_not_manifest_derived"))
    if "AIOPS_SPECIALIST_MANIFEST_DIGEST" not in container_tf:
        failures.append(_failure("container_apps_missing_manifest_digest"))
    hardcoded = sorted(
        specialist.id
        for specialist in manifest.specialists
        if f'"FOUNDRY_{specialist.id.upper()}_AGENT_NAME"' in container_tf
    )
    if hardcoded:
        failures.append(
            _failure("container_apps_hardcodes_specialist", specialists=hardcoded)
        )

    # Legacy compatibility window: the previous eight-specialist input must
    # still be accepted so existing tfvars plan and the prior revision stays
    # selectable for rollback.
    if 'variable "foundry_specialists"' not in variables_tf:
        failures.append(_failure("legacy_specialist_input_removed"))
    if "FOUNDRY_SPECIALISTS_LEGACY_JSON" not in container_tf:
        failures.append(_failure("legacy_rollback_metadata_removed"))
    return _check("terraform_projection", failures)


MODEL_CONTRACT_DIVERGENCE = "acknowledged_deployment_name_distinct_from_contract_model"
DEPLOYMENT_MODEL_SOURCE = "var.foundry_model_name"


# Staged rollout controls (Plan 11-12 Task 2). The canonical OrchestrationService
# is introduced compatibility -> shadow -> canary -> default and can be reversed
# to the prior revision/mode without rewriting threads or ledgers. The offline
# gate proves the Terraform seam and the operator runbook agree on every stage,
# the automatic hold, and the separately reviewed legacy-retirement condition.
ROLLOUT_MODES = ("compatibility", "shadow", "canary", "default")


def _check_rollout_controls() -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    container_tf = _read("infra/terraform/container_apps.tf")
    variables_source = container_tf + "\n" + _read("infra/terraform/variables.tf")

    # A single reviewed variable selects the rollout stage, constrained to the
    # four modes; a big-bang cutover is unrepresentable.
    if 'variable "copilot_rollout_mode"' not in variables_source:
        failures.append(_failure("rollout_mode_variable_missing"))
    else:
        for mode in ROLLOUT_MODES:
            if f'"{mode}"' not in variables_source:
                failures.append(_failure("rollout_mode_absent", mode=mode))

    # The mode and its bounded canary traffic reach the running revision as
    # environment, and a rollback fallback mode is retained.
    for token in (
        "AIOPS_COPILOT_ROLLOUT_MODE",
        "AIOPS_COPILOT_CANARY_PERCENTAGE",
        "AIOPS_COPILOT_ROLLBACK_MODE",
    ):
        if token not in container_tf:
            failures.append(_failure("rollout_env_missing", token=token))

    if 'variable "copilot_canary_percentage"' not in variables_source:
        failures.append(_failure("canary_percentage_variable_missing"))

    runtime_source = _read("src/operations/maf_orchestrator.py")
    route_source = "\n".join(
        (
            _read("src/api/routers/copilot.py"),
            _read("src/api/routers/multi_agent.py"),
        )
    )
    for token in (
        "AIOPS_COPILOT_ROLLOUT_MODE",
        "AIOPS_COPILOT_CANARY_PERCENTAGE",
        "AIOPS_COPILOT_ROLLBACK_MODE",
    ):
        if token not in runtime_source:
            failures.append(_failure("rollout_runtime_input_missing", token=token))
    if "canonical_orchestration_enabled(stable_key=principal.subject)" not in route_source:
        failures.append(_failure("rollout_request_boundary_missing"))

    # Legacy page-anchored planners must remain selectable for rollback
    # throughout Phase 11; this plan never deletes them.
    if '"deterministic"' not in variables_source:
        failures.append(_failure("legacy_deterministic_mode_removed"))

    # The operator runbook must document every stage, the automatic hold, the
    # deterministic rollback, and the separately reviewed retirement gate.
    try:
        runbook = _read("docs/runbooks/copilot-orchestration-rollout.md")
    except FileNotFoundError:
        failures.append(_failure("rollout_runbook_missing"))
        runbook = ""
    runbook_lower = runbook.lower()
    for stage in ROLLOUT_MODES:
        if stage not in runbook_lower:
            failures.append(_failure("runbook_missing_stage", stage=stage))
    for token in ("hold", "rollback", "30", "shadow", "canary"):
        if token not in runbook_lower:
            failures.append(_failure("runbook_missing_procedure", token=token))
    if "zero" not in runbook_lower or "v1" not in runbook_lower:
        failures.append(_failure("runbook_missing_retirement_gate"))

    return _check("rollout_controls", failures)


def _check_provider_environment() -> dict[str, Any]:
    """Prove deterministic provider values have one sourceable output."""

    failures: list[dict[str, Any]] = []
    outputs = _read("infra/terraform/outputs.tf")
    foundry = _read("infra/terraform/foundry.tf")
    exporter_path = REPO_ROOT / "scripts" / "export_copilot_provider_env.py"
    required = (
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
    )
    if 'output "copilot_provider_environment"' not in outputs:
        failures.append(_failure("provider_environment_output_missing"))
    for token in required:
        if token not in outputs:
            failures.append(_failure("provider_environment_value_missing", token=token))
    if not exporter_path.is_file():
        failures.append(_failure("provider_environment_exporter_missing"))
    for connection in (
        "azapi_resource.foundry_mcp_connection[0].id",
        "azapi_resource.foundry_azure_mcp_connection[0].id",
    ):
        if f"project_connection_id = {connection}" not in foundry:
            failures.append(
                _failure("terraform_project_connection_not_immutable")
            )
    return _check("provider_environment", failures)


def contract_models(manifest) -> list[str]:
    """Return the distinct model names the manifest declares."""

    return sorted({specialist.foundry.model for specialist in manifest.specialists})


def _check_model_contract(manifest) -> dict[str, Any]:
    """Validate the acknowledged contract-model / deployment-name distinction.

    The manifest's ``foundry.model`` is a *contract* declaration; the value an
    agent is actually deployed against is the Azure model DEPLOYMENT name
    (``var.foundry_model_name``). Forcing them equal would point every agent at
    a deployment that does not exist, so the divergence is deliberate -- but it
    must be an explicitly validated and reported distinction, not an unchecked
    field that merely looks like it is being verified.
    """

    failures: list[dict[str, Any]] = []
    foundry_tf = _read("infra/terraform/foundry.tf")

    models = contract_models(manifest)
    if len(models) != 1:
        # More than one contract model means "the contract model" is not a
        # single reviewable fact and the divergence cannot be acknowledged.
        failures.append(_failure("contract_model_not_singular", tools=models))

    # The projection must carry BOTH, so neither can be silently dropped.
    if not re.search(
        r"^\s*contract_model\s*=\s*specialist\.foundry\.model\s*$",
        foundry_tf,
        flags=re.MULTILINE,
    ):
        failures.append(_failure("contract_model_not_projected"))
    if not re.search(
        r"^\s*model\s*=\s*var\.foundry_model_name\s*$", foundry_tf, flags=re.MULTILINE
    ):
        failures.append(_failure("deployment_model_not_variable_derived"))

    # The live gate is what actually proves the deployed model; wire it or the
    # distinction is unverifiable end to end.
    if "FOUNDRY_MODEL_DEPLOYMENT_NAME" not in foundry_tf:
        failures.append(_failure("deployment_model_not_passed_to_live_gate"))

    return _check("model_contract", failures)


def _check_package_contents() -> dict[str, Any]:
    failures: list[dict[str, Any]] = []

    loader_path = Path(manifest_module.__file__).with_name("specialists.v1.json")
    if not loader_path.exists():
        failures.append(_failure("loader_manifest_missing"))
    elif not loader_path.as_posix().endswith(PACKAGED_MANIFEST_PATH):
        failures.append(_failure("loader_manifest_path_unstable"))

    wheel = tomllib.loads(_read("pyproject.toml"))["tool"]["hatch"]["build"]["targets"][
        "wheel"
    ]
    if "src/operations" not in wheel.get("packages", []):
        failures.append(_failure("wheel_missing_operations_package"))
    if (
        wheel.get("force-include", {}).get("src/operations/specialists.v1.json")
        != PACKAGED_MANIFEST_PATH
    ):
        failures.append(_failure("wheel_manifest_path_not_pinned"))

    dockerfile = _read("Dockerfile")
    if CONTAINER_MANIFEST_PATH not in dockerfile:
        failures.append(_failure("container_manifest_not_verified"))
    return _check("package_contents", failures)


def run_offline() -> dict[str, Any]:
    """Run every credential-free parity check against the committed manifest."""

    manifest = load_specialist_manifest()
    checks = [
        _check_runtime_projection(manifest),
        _check_operations_grants(manifest),
        _check_azure_grants(manifest),
        _check_api_catalog(manifest),
        _check_terraform_projection(manifest),
        _check_model_contract(manifest),
        _check_package_contents(),
        _check_rollout_controls(),
        _check_provider_environment(),
    ]
    failures = [failure for check in checks for failure in check["failures"]]
    models = contract_models(manifest)
    return {
        "mode": "offline",
        "status": "pass" if not failures else "fail",
        "contract_version": manifest.contract_version,
        "runtime_contract_version": manifest.runtime_contract_version,
        "specialist_count": len(manifest.specialists),
        "specialists": list(manifest.specialist_ids),
        # The contract model and the Azure model DEPLOYMENT name are
        # deliberately different things. Reporting both, side by side, is what
        # keeps that an acknowledged distinction rather than hidden drift.
        "model_contract": {
            "contract_model": models[0] if len(models) == 1 else None,
            "contract_models": models,
            "deployment_model_source": DEPLOYMENT_MODEL_SOURCE,
            "divergence": MODEL_CONTRACT_DIVERGENCE,
        },
        "checks": checks,
        "failures": failures,
    }


# ---------------------------------------------------------------------------
# Live checks (read-only)
# ---------------------------------------------------------------------------


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str]) -> Any:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def _get_json(url: str, headers: dict[str, str]) -> Any:
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def _access_token(env: dict[str, str], *, scope: str) -> str:
    """Acquire a token for one explicit audience."""

    data = urllib.parse.urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": env["AZURE_CLIENT_ID"],
            "client_secret": env["AZURE_CLIENT_SECRET"],
            "scope": scope,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"https://login.microsoftonline.com/{env['AZURE_TENANT_ID']}/oauth2/v2.0/token",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))["access_token"]


def _live_tool_catalog(url: str, token: str) -> tuple[str, ...]:
    payload = _post_json(
        url,
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        {"Authorization": f"Bearer {token}"},
    )
    tools = (payload or {}).get("result", {}).get("tools", [])
    return tuple(
        str(tool.get("name", "")) for tool in tools if isinstance(tool, dict)
    )


def _deployed_agent_name(specialist, env: dict[str, str]) -> str:
    override = env.get(f"FOUNDRY_{specialist.id.upper()}_AGENT_NAME", "").strip()
    if override:
        return override
    prefix = env.get("FOUNDRY_AGENT_NAME_PREFIX", "aiops-")
    suffix = env.get("FOUNDRY_AGENT_NAME_SUFFIX", "-agent")
    return f"{prefix}{specialist.foundry.name}{suffix}"


def _agent_allowed_tools(definition: Any) -> dict[str, tuple[str, ...]]:
    granted: dict[str, tuple[str, ...]] = {
        OPERATIONS_SERVER_LABEL: (),
        AZURE_SERVER_LABEL: (),
    }
    for tool in (definition or {}).get("tools", []) or []:
        if not isinstance(tool, dict) or tool.get("type") != "mcp":
            continue
        label = str(tool.get("server_label", ""))
        if label in granted:
            granted[label] = tuple(
                str(name) for name in tool.get("allowed_tools", []) or []
            )
    return granted


def _agent_connection_ids(definition: Any) -> dict[str, str]:
    """Return each governed MCP label's exact project connection identity."""

    connections = {label: "" for label in CONNECTION_LABELS}
    for tool in (definition or {}).get("tools", []) or []:
        if not isinstance(tool, dict) or tool.get("type") != "mcp":
            continue
        label = str(tool.get("server_label", ""))
        if label in connections:
            connections[label] = str(tool.get("project_connection_id", "")).strip()
    return connections


def compare_connection_bindings(
    *,
    specialist_id: str,
    expected: dict[str, str],
    actual: dict[str, str],
) -> list[dict[str, Any]]:
    """Require every MCP tool definition to use its governed connection ID."""

    failures: list[dict[str, Any]] = []
    for server in CONNECTION_LABELS:
        expected_id = expected.get(server, "").strip().rstrip("/").casefold()
        actual_id = actual.get(server, "").strip().rstrip("/").casefold()
        if not expected_id or actual_id != expected_id:
            failures.append(
                _failure(
                    "project_connection_mismatch",
                    specialist=specialist_id,
                    server=server,
                )
            )
    return failures


def _secure_service_urls(env: dict[str, str]) -> list[dict[str, Any]]:
    """Reject credential-bearing requests to non-HTTPS service URLs."""

    failures: list[dict[str, Any]] = []
    expected_paths = (
        ("FOUNDRY_PROJECT_ENDPOINT", FOUNDRY_SERVICE, None),
        ("OPERATIONS_MCP_SERVER_URL", OPERATIONS_SERVER_LABEL, "/operations-mcp"),
        ("AZURE_MCP_SERVER_URL", AZURE_SERVER_LABEL, "/azure-mcp"),
    )
    for variable, service, expected_path in expected_paths:
        try:
            parsed = urllib.parse.urlsplit(env[variable])
            port = parsed.port
        except ValueError:
            parsed = urllib.parse.SplitResult("", "", "", "", "")
            port = None
        path_valid = (
            re.fullmatch(r"/api/projects/[^/]+/?", parsed.path) is not None
            if expected_path is None
            else parsed.path.rstrip("/") == expected_path
        )
        if (
            parsed.scheme.casefold() != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or port is not None
            or parsed.query
            or parsed.fragment
            or not path_valid
        ):
            failures.append(_failure("insecure_service_url", service=service))
    operation_host = urllib.parse.urlsplit(
        env["OPERATIONS_MCP_SERVER_URL"]
    ).hostname
    azure_host = urllib.parse.urlsplit(env["AZURE_MCP_SERVER_URL"]).hostname
    if (
        operation_host
        and azure_host
        and operation_host.casefold() != azure_host.casefold()
    ):
        failures.append(
            _failure("insecure_service_url", service=AZURE_SERVER_LABEL)
        )
    return failures


def _oauth_scope(audience: str) -> str:
    """Normalize an Entra audience into a client-credentials scope."""

    audience = audience.strip().rstrip("/")
    return audience if audience.endswith("/.default") else f"{audience}/.default"


def _live_failure(error: Exception, *, service: str) -> dict[str, Any]:
    """Return a controlled failure for a configured live-service error."""

    if isinstance(error, urllib.error.HTTPError):
        kind = (
            "live_auth_rejected"
            if error.code in {401, 403}
            else "live_service_error"
        )
        return _failure(
            kind,
            service=service,
            status=error.code,
            error_type=type(error).__name__,
        )
    return _failure(
        "live_service_error",
        service=service,
        status=0,
        error_type=type(error).__name__,
    )


def _candidate_mapping(
    path: str,
) -> tuple[dict[str, dict[str, str]], dict[str, str], dict[str, str]]:
    """Load exact provider IDs emitted by the candidate rollout."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    agents = payload.get("agents")
    if not isinstance(agents, dict):
        raise TypeError("candidate mapping has no agents map")

    result: dict[str, dict[str, str]] = {}
    for specialist_id, entry in agents.items():
        if not isinstance(specialist_id, str) or not isinstance(entry, dict):
            raise TypeError("candidate mapping entry is malformed")
        agent_name = entry.get("agent_name")
        provider_version_id = entry.get("provider_version_id")
        if not isinstance(agent_name, str) or not agent_name.strip():
            raise ValueError("candidate mapping has no agent name")
        if not isinstance(provider_version_id, str) or not provider_version_id.strip():
            raise ValueError("candidate mapping has no provider version id")
        result[specialist_id] = {
            "agent_name": agent_name.strip(),
            "provider_version_id": provider_version_id.strip(),
        }
    coordinator = payload.get("coordinator")
    if not isinstance(coordinator, dict):
        raise TypeError("candidate mapping has no coordinator")
    coordinator_name = coordinator.get("agent_name")
    coordinator_version = coordinator.get("provider_version_id")
    if not isinstance(coordinator_name, str) or not coordinator_name.strip():
        raise ValueError("candidate coordinator has no agent name")
    if not isinstance(coordinator_version, str) or not coordinator_version.strip():
        raise ValueError("candidate coordinator has no provider version id")
    candidate_connections = payload.get("connections")
    if not isinstance(candidate_connections, dict):
        raise TypeError("candidate mapping has no connections map")
    if set(candidate_connections) != set(CONNECTION_LABELS):
        raise ValueError("candidate mapping must contain the exact connection labels")
    connections: dict[str, str] = {}
    for label in CONNECTION_LABELS:
        connection = candidate_connections[label]
        if not isinstance(connection, dict):
            raise TypeError("candidate connection entry is malformed")
        connection_id = connection.get("project_connection_id")
        if not isinstance(connection_id, str):
            raise TypeError("candidate connection id is malformed")
        normalized = connection_id.strip().rstrip("/")
        if not PROJECT_CONNECTION_ID_PATTERN.fullmatch(normalized):
            raise ValueError("candidate mapping has no immutable project connection id")
        connections[label] = normalized
    if len({value.casefold() for value in connections.values()}) != len(connections):
        raise ValueError("candidate project connection ids must be distinct")
    return result, {
        "agent_name": coordinator_name.strip(),
        "provider_version_id": coordinator_version.strip(),
    }, connections


def _entry_provider_version_id(entry: dict[str, Any]) -> str:
    """Extract the immutable provider version identifier from a live entry."""

    for key in (
        "version",
        "agentVersion",
        "agent_version",
        "versionId",
        "version_id",
        "id",
    ):
        value = entry.get(key)
        if not isinstance(value, str):
            continue
        normalized = value.strip()
        if "/" in normalized:
            path = "/" + normalized.strip("/")
            marker = "/versions/"
            if marker not in path:
                continue
            normalized = path.rsplit(marker, 1)[-1].strip("/")
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}", normalized):
            return normalized
    return ""


def run_live(env: dict[str, str] | None = None) -> dict[str, Any]:
    """Read deployed Foundry and MCP state and compare it to the manifest."""

    env = dict(os.environ if env is None else env)
    missing = [name for name in LIVE_REQUIRED_ENV if not env.get(name, "").strip()]
    if missing:
        return {
            "mode": "live",
            "status": "blocked",
            "reason": "live_parity_not_configured",
            "missing_configuration": missing,
            "specialists": [],
            "checks": [],
            "failures": [],
        }

    url_failures = _secure_service_urls(env)
    if url_failures:
        return {
            "mode": "live",
            "status": "fail",
            "reason": "insecure_service_url",
            "missing_configuration": [],
            "specialists": [],
            "checks": [_check("live_configuration", url_failures)],
            "failures": url_failures,
        }

    manifest = load_specialist_manifest()
    endpoint = env["FOUNDRY_PROJECT_ENDPOINT"].rstrip("/")
    api_version = env.get("FOUNDRY_API_VERSION", "v1")

    try:
        candidate_agents, candidate_coordinator, candidate_connections = _candidate_mapping(
            env["FOUNDRY_CANDIDATE_MAPPING"]
        )
    except (OSError, ValueError, TypeError) as error:
        failure = _failure(
            "candidate_mapping_unreadable",
            service=FOUNDRY_SERVICE,
            status=0,
            error_type=type(error).__name__,
        )
        return {
            "mode": "live",
            "status": "fail",
            "reason": "candidate_mapping_invalid",
            "missing_configuration": [],
            "specialists": [],
            "checks": [_check("live_configuration", [failure])],
            "failures": [failure],
        }

    candidate_failures: list[dict[str, Any]] = []
    extra_candidate_ids = set(candidate_agents) - set(manifest.specialist_ids)
    if extra_candidate_ids:
        candidate_failures.append(
            _failure(
                "candidate_specialist_ids_mismatch",
                specialists=sorted(extra_candidate_ids),
            )
        )
    for specialist in manifest.specialists:
        candidate = candidate_agents.get(specialist.id)
        if candidate is not None and candidate["agent_name"] != _deployed_agent_name(
            specialist, env
        ):
            candidate_failures.append(
                _failure(
                    "candidate_agent_identity_mismatch",
                    specialist=specialist.id,
                    server=FOUNDRY_SERVICE,
                )
            )
    if candidate_failures:
        return {
            "mode": "live",
            "status": "fail",
            "reason": "candidate_mapping_invalid",
            "missing_configuration": [],
            "specialists": [],
            "checks": [_check("live_configuration", candidate_failures)],
            "failures": candidate_failures,
        }

    try:
        foundry_token = _access_token(
            env,
            scope=_oauth_scope(
                env.get("FOUNDRY_AUDIENCE", DEFAULT_FOUNDRY_AUDIENCE)
            ),
        )
    except (urllib.error.URLError, OSError, KeyError, ValueError) as error:
        failure = _live_failure(error, service=FOUNDRY_SERVICE)
        return {
            "mode": "live",
            "status": "fail",
            "reason": "live_auth_or_service_failure",
            "missing_configuration": [],
            "specialists": [],
            "checks": [_check("live_authentication", [failure])],
            "failures": [failure],
        }

    try:
        apim_token = _access_token(
            env,
            scope=_oauth_scope(env["MCP_APIM_AUDIENCE"]),
        )
    except (urllib.error.URLError, OSError, KeyError, ValueError) as error:
        failure = _live_failure(error, service="apim")
        return {
            "mode": "live",
            "status": "fail",
            "reason": "live_auth_or_service_failure",
            "missing_configuration": [],
            "specialists": [],
            "checks": [_check("live_authentication", [failure])],
            "failures": [failure],
        }

    catalogs: dict[str, tuple[str, ...]] = {}
    for server, variable in (
        (OPERATIONS_SERVER_LABEL, "OPERATIONS_MCP_SERVER_URL"),
        (AZURE_SERVER_LABEL, "AZURE_MCP_SERVER_URL"),
    ):
        try:
            catalogs[server] = _live_tool_catalog(env[variable], apim_token)
        except (urllib.error.URLError, OSError, KeyError, ValueError) as error:
            failure = _live_failure(error, service=server)
            return {
                "mode": "live",
                "status": "fail",
                "reason": "live_auth_or_service_failure",
                "missing_configuration": [],
                "specialists": [],
                "checks": [_check("live_catalogs", [failure])],
                "failures": [failure],
            }

    try:
        connection_payload = _get_json(
            f"{endpoint}/connections?api-version={api_version}",
            {"Authorization": "Bearer " + foundry_token},
        )
    except (urllib.error.URLError, OSError, ValueError) as error:
        failure = _live_failure(error, service=FOUNDRY_SERVICE)
        return {
            "mode": "live",
            "status": "fail",
            "reason": "live_auth_or_service_failure",
            "missing_configuration": [],
            "specialists": [],
            "checks": [_check("live_connections", [failure])],
            "failures": [failure],
        }
    live_connection_ids = {
        str(entry.get("id", "")).strip().rstrip("/").casefold()
        for entry in (connection_payload or {}).get("value", []) or []
        if isinstance(entry, dict) and entry.get("id")
    }
    missing_connections = [
        label
        for label, connection_id in candidate_connections.items()
        if connection_id.casefold() not in live_connection_ids
    ]
    if missing_connections:
        failures = [
            _failure(
                "governed_connection_not_onboarded",
                server=label,
            )
            for label in missing_connections
        ]
        return {
            "mode": "live",
            "status": "blocked",
            "reason": "governed_connections_not_onboarded",
            "missing_configuration": [],
            "specialists": [],
            "checks": [_check("live_connections", failures)],
            "failures": failures,
        }

    failures: list[dict[str, Any]] = []
    observed: list[dict[str, Any]] = []
    deployment_model = env.get("FOUNDRY_MODEL_DEPLOYMENT_NAME", "").strip()
    coordinator_name = candidate_coordinator["agent_name"]
    coordinator_version = candidate_coordinator["provider_version_id"]
    try:
        coordinator_versions = _get_json(
            f"{endpoint}/agents/{coordinator_name}/versions?api-version={api_version}",
            {"Authorization": "Bearer " + foundry_token},
        )
        coordinator_entries = (coordinator_versions or {}).get("value", []) or []
        coordinator_pinned = next(
            (
                entry
                for entry in coordinator_entries
                if isinstance(entry, dict)
                and _entry_provider_version_id(entry) == coordinator_version
            ),
            None,
        )
        if coordinator_pinned is None:
            failures.append(
                _failure(
                    "pinned_version_missing",
                    specialist="operations_copilot",
                    server=FOUNDRY_SERVICE,
                    provider_version_id=coordinator_version,
                )
            )
        else:
            coordinator_definition = coordinator_pinned.get("definition") or {}
            if (
                deployment_model
                and coordinator_definition.get("model") != deployment_model
            ):
                failures.append(
                    _failure(
                        "deployed_model_mismatch",
                        specialist="operations_copilot",
                        server=FOUNDRY_SERVICE,
                    )
                )
            observed.append(
                {
                    "specialist": "operations_copilot",
                    "provider_version_id": coordinator_version,
                    "version_count": len(coordinator_entries),
                    "operations_grant_count": 0,
                    "azure_grant_count": 0,
                }
            )
    except (urllib.error.URLError, OSError, ValueError) as error:
        failure = _live_failure(error, service=FOUNDRY_SERVICE)
        failure["specialist"] = "operations_copilot"
        failures.append(failure)

    for specialist_id in sorted(set(manifest.specialist_ids) - set(candidate_agents)):
        failures.append(
            _failure(
                "pinned_version_absent",
                specialist=specialist_id,
                server=FOUNDRY_SERVICE,
                tools=[],
            )
        )

    for specialist in manifest.specialists:
        candidate = candidate_agents.get(specialist.id)
        if candidate is None:
            continue
        agent_name = candidate["agent_name"]
        provider_version_id = candidate["provider_version_id"]
        try:
            versions = _get_json(
                f"{endpoint}/agents/{agent_name}/versions?api-version={api_version}",
                {"Authorization": f"Bearer {foundry_token}"},
            )
        except (urllib.error.URLError, OSError, ValueError) as error:
            failure = _live_failure(error, service=FOUNDRY_SERVICE)
            failure["specialist"] = specialist.id
            failures.append(failure)
            continue

        entries = (versions or {}).get("value", []) or []
        pinned = next(
            (
                entry
                for entry in entries
                if isinstance(entry, dict)
                and _entry_provider_version_id(entry) == provider_version_id
            ),
            None,
        )
        if pinned is None:
            failures.append(
                _failure(
                    "pinned_version_missing",
                    specialist=specialist.id,
                    server=FOUNDRY_SERVICE,
                    provider_version_id=provider_version_id,
                )
            )
            continue

        definition = pinned.get("definition") or {}
        if deployment_model and definition.get("model") != deployment_model:
            failures.append(
                _failure(
                    "deployed_model_mismatch",
                    specialist=specialist.id,
                    server=FOUNDRY_SERVICE,
                )
            )

        granted = _agent_allowed_tools(definition)
        failures.extend(
            compare_connection_bindings(
                specialist_id=specialist.id,
                expected=candidate_connections,
                actual=_agent_connection_ids(definition),
            )
        )
        failures.extend(
            compare_grants(
                specialist_id=specialist.id,
                server=OPERATIONS_SERVER_LABEL,
                expected=specialist.operations_mcp_tools,
                granted=granted[OPERATIONS_SERVER_LABEL],
                live_catalog=catalogs[OPERATIONS_SERVER_LABEL],
            )
        )
        failures.extend(
            compare_grants(
                specialist_id=specialist.id,
                server=AZURE_SERVER_LABEL,
                expected=specialist.azure_mcp_tools,
                granted=granted[AZURE_SERVER_LABEL],
                live_catalog=catalogs[AZURE_SERVER_LABEL],
            )
        )
        observed.append(
            {
                "specialist": specialist.id,
                "provider_version_id": provider_version_id,
                "version_count": len(entries),
                "operations_grant_count": len(granted[OPERATIONS_SERVER_LABEL]),
                "azure_grant_count": len(granted[AZURE_SERVER_LABEL]),
            }
        )

    return {
        "mode": "live",
        "status": "pass" if not failures else "fail",
        "reason": "live_parity_verified" if not failures else "live_parity_mismatch",
        "missing_configuration": [],
        "specialist_count": len(manifest.specialists),
        "specialists": list(manifest.specialist_ids),
        "operations_catalog_size": len(catalogs[OPERATIONS_SERVER_LABEL]),
        "azure_catalog_size": len(catalogs[AZURE_SERVER_LABEL]),
        "deployment_model_verified": bool(deployment_model),
        "checks": [_check("live_grants", failures)],
        "observed": observed,
        "failures": failures,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def exit_code(report: dict[str, Any]) -> int:
    """Map a report status onto a process exit code."""

    status = report.get("status")
    if status == "pass":
        return EXIT_PASS
    if status == "blocked":
        return EXIT_BLOCKED
    return EXIT_FAIL


def _combine(reports: list[dict[str, Any]]) -> dict[str, Any]:
    if len(reports) == 1:
        return reports[0]
    statuses = [report["status"] for report in reports]
    if "fail" in statuses:
        status = "fail"
    elif "blocked" in statuses:
        status = "blocked"
    else:
        status = "pass"
    return {
        "mode": "offline+live",
        "status": status,
        "reports": reports,
        "failures": [failure for report in reports for failure in report["failures"]],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate specialist manifest parity offline and, optionally, live.",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Run credential-free manifest/runtime/Terraform/package parity.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Additionally read deployed Foundry versions and MCP tool catalogs.",
    )
    parser.add_argument(
        "--candidate-mapping",
        help="Path to the candidate provider-version mapping to validate live.",
    )
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="Verify that this interpreter can import and initialize the validator.",
    )
    args = parser.parse_args(argv)
    if args.selftest:
        load_specialist_manifest()
        return EXIT_PASS
    if args.candidate_mapping:
        os.environ["FOUNDRY_CANDIDATE_MAPPING"] = args.candidate_mapping
    if not args.offline and not args.live:
        args.offline = True

    reports: list[dict[str, Any]] = []
    if args.offline:
        reports.append(run_offline())
    if args.live:
        reports.append(run_live())

    report = _combine(reports)
    json.dump(report, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return exit_code(report)


if __name__ == "__main__":
    raise SystemExit(main())
