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

# Credential-bearing variables are only ever tested for presence. Their values
# are never read into the report, logged, or echoed.
LIVE_REQUIRED_ENV = (
    "FOUNDRY_PROJECT_ENDPOINT",
    "AZURE_TENANT_ID",
    "AZURE_CLIENT_ID",
    "AZURE_CLIENT_SECRET",
    "OPERATIONS_MCP_SERVER_URL",
    "AZURE_MCP_SERVER_URL",
)

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

    if "local.foundry_specialist_deployment" not in container_tf:
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
        _check_package_contents(),
    ]
    failures = [failure for check in checks for failure in check["failures"]]
    return {
        "mode": "offline",
        "status": "pass" if not failures else "fail",
        "contract_version": manifest.contract_version,
        "runtime_contract_version": manifest.runtime_contract_version,
        "specialist_count": len(manifest.specialists),
        "specialists": list(manifest.specialist_ids),
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


def _access_token(env: dict[str, str]) -> str:
    """Acquire a data-plane token. The token is never returned in a report."""

    data = urllib.parse.urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": env["AZURE_CLIENT_ID"],
            "client_secret": env["AZURE_CLIENT_SECRET"],
            "scope": "https://ai.azure.com/.default",
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

    manifest = load_specialist_manifest()
    endpoint = env["FOUNDRY_PROJECT_ENDPOINT"].rstrip("/")
    api_version = env.get("FOUNDRY_API_VERSION", "v1")

    try:
        token = _access_token(env)
        catalogs = {
            OPERATIONS_SERVER_LABEL: _live_tool_catalog(
                env["OPERATIONS_MCP_SERVER_URL"], token
            ),
            AZURE_SERVER_LABEL: _live_tool_catalog(env["AZURE_MCP_SERVER_URL"], token),
        }
    except (urllib.error.URLError, OSError, KeyError, ValueError) as error:
        return {
            "mode": "live",
            "status": "blocked",
            "reason": "live_services_unreachable",
            "error_type": type(error).__name__,
            "missing_configuration": [],
            "specialists": [],
            "checks": [],
            "failures": [],
        }

    failures: list[dict[str, Any]] = []
    observed: list[dict[str, Any]] = []
    for specialist in manifest.specialists:
        agent_name = _deployed_agent_name(specialist, env)
        try:
            versions = _get_json(
                f"{endpoint}/agents/{agent_name}/versions?api-version={api_version}",
                {"Authorization": f"Bearer {token}"},
            )
        except (urllib.error.URLError, OSError, ValueError) as error:
            failures.append(
                _failure(
                    "agent_version_unreadable",
                    specialist=specialist.id,
                    server="foundry",
                    tools=[type(error).__name__],
                )
            )
            continue

        entries = (versions or {}).get("value", []) or []
        if not entries:
            failures.append(
                _failure(
                    "agent_version_missing",
                    specialist=specialist.id,
                    server="foundry",
                    tools=[],
                )
            )
            continue

        latest = entries[-1]
        granted = _agent_allowed_tools(latest.get("definition"))
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
    args = parser.parse_args(argv)
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
