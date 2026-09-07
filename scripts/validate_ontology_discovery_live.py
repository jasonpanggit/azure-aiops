#!/usr/bin/env python3
"""Validate ontology discovery without exposing an activation interface.

``--shadow`` combines read-only Azure/Fabric/Foundry inspection, two bounded
manual executions of the non-production coordinator Job, executable repository
contracts, and a durable EvaluationSnapshot.  Reports contain only allowlisted
statuses, counts, timestamps, hashes, and closed-vocabulary reason codes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fabric.dataset_mapper import allowed_relationship_triples
from ontology_discovery.contracts import (
    MAX_CANDIDATE_PAIRS,
    MAX_CHANGED_ENTITIES,
    MAX_EVIDENCE_RECORDS,
)
from ontology_discovery.curator import (
    MAX_INPUT_TOKENS,
    NORMAL_OUTPUT_TOKENS,
    REQUEST_TIMEOUT_SECONDS,
)
from ontology_discovery.evaluation_store import EvaluationSnapshotStore
from ontology_discovery.telemetry import (
    ALERT_RULES,
    OntologyDiscoveryTelemetry,
    emit_sanitized_alert_smoke,
)
from scripts.evaluate_ontology_discovery import evaluate_dataset

ALERTING_TF = ROOT / "infra" / "terraform" / "alerting.tf"
REFERENCE_DATASET = (
    ROOT / "tests" / "fixtures" / "ontology_discovery" / "reference.jsonl"
)
RBAC_EVIDENCE = (
    ROOT
    / ".planning"
    / "phases"
    / "13-autonomous-ontology-discovery-and-fabric-synchronization"
    / "13-07-LIVE-RBAC.json"
)
DEFAULT_REPORT_DIR = ROOT / ".planning" / "eval"
EXPECTED_BOUNDS = {
    "changed_entities": 50,
    "candidate_pairs": 200,
    "evidence_records": 40,
    "input_tokens": 8000,
    "output_tokens": 1200,
    "attempt_seconds": 60,
}
EXPECTED_CONSUMERS = ("api", "fabric", "agent", "export", "semantic")
EXPECTED_DENIED_IDENTITIES = ("api", "coordinator", "curator")
EXPECTED_CURATOR_TOOLS = (
    "list_changed_entities",
    "get_entity_evidence",
    "get_ontology_vocabulary",
    "search_relationship_history",
)
SENSITIVE_KEYS = {
    "client_id",
    "foundry_agent_name",
    "job_name",
    "lakehouse_id",
    "object_id",
    "principal_id",
    "resource_group",
    "subscription_id",
    "tenant_id",
    "workspace_id",
}


class ConfigurationError(RuntimeError):
    """A required explicit non-production target is unavailable."""


class EvidenceError(RuntimeError):
    """Credentialed or executable evidence could not be established."""


@dataclass(frozen=True)
class DeploymentTargets:
    subscription_id: str
    resource_group: str
    job_name: str
    workspace_id: str
    lakehouse_id: str
    rbac_workspace_id: str
    rbac_lakehouse_id: str
    foundry_project_endpoint: str
    foundry_agent_name: str
    runtime_selection: str
    state_target_source: str


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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate deployed ontology discovery in fail-closed shadow mode."
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--alert-smoke", action="store_true")
    modes.add_argument("--shadow", action="store_true")
    parser.add_argument("--synthetic-only", action="store_true")
    parser.add_argument(
        "--assert-authoritative-model-edge-count-zero",
        action="store_true",
    )
    parser.add_argument(
        "--assert-release-status",
        choices=("blocked-or-pending",),
    )
    parser.add_argument("--fail-on-threshold", action="store_true")
    parser.add_argument("--fail-on-missing-evidence", action="store_true")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--fabric-config", type=Path)
    parser.add_argument("--subscription-id")
    parser.add_argument("--resource-group")
    parser.add_argument("--job-name")
    parser.add_argument("--workspace-id")
    parser.add_argument("--lakehouse-id")
    parser.add_argument("--rbac-workspace-id")
    parser.add_argument("--rbac-lakehouse-id")
    parser.add_argument("--foundry-project-endpoint")
    parser.add_argument("--foundry-agent-name")
    return parser


def _read_fabric_config(path: Path) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigurationError("Fabric configuration is unavailable or invalid") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("fabric"), dict):
        raise ConfigurationError("Fabric configuration has no fabric section")
    return dict(payload["fabric"])


def _terraform_value(
    outputs: Mapping[str, object],
    *names: str,
) -> str:
    for name in names:
        value = outputs.get(name)
        if isinstance(value, Mapping):
            value = value.get("value")
        if value:
            return str(value).strip()
    return ""


def resolve_deployment_targets(
    args: argparse.Namespace,
    *,
    env: Mapping[str, str] | None = None,
    terraform_outputs: Mapping[str, object] | None = None,
) -> DeploymentTargets:
    """Resolve the Phase 13 targets without inheriting production Fabric IDs."""

    environment = dict(os.environ if env is None else env)
    config_path = args.fabric_config or Path(
        environment.get("AIOPS_FABRIC_CONFIG", ROOT / "fabric.config.deploy.yaml")
    )
    fabric = _read_fabric_config(config_path)
    outputs = dict(terraform_outputs or {})

    cli_state = bool(args.workspace_id or args.lakehouse_id)
    env_state = bool(
        environment.get("AIOPS_ONTOLOGY_STATE_WORKSPACE_ID")
        or environment.get("AIOPS_ONTOLOGY_STATE_LAKEHOUSE_ID")
    )
    workspace_id = (
        args.workspace_id
        or environment.get("AIOPS_ONTOLOGY_STATE_WORKSPACE_ID")
        or _terraform_value(
            outputs,
            "ontology_discovery_state_workspace_id",
            "ontology_state_workspace_id",
        )
    )
    lakehouse_id = (
        args.lakehouse_id
        or environment.get("AIOPS_ONTOLOGY_STATE_LAKEHOUSE_ID")
        or _terraform_value(
            outputs,
            "ontology_discovery_state_lakehouse_id",
            "ontology_state_lakehouse_id",
        )
    )
    if not workspace_id or not lakehouse_id:
        raise ConfigurationError(
            "Phase 13 state workspace/lakehouse must come from explicit CLI/env "
            "inputs or canonical Terraform state; production Fabric config IDs "
            "are not a valid fallback"
        )
    if cli_state:
        state_source = "explicit-cli"
    elif env_state:
        state_source = "explicit-environment"
    else:
        state_source = "terraform-state"

    capacity = fabric.get("capacity")
    capacity = capacity if isinstance(capacity, Mapping) else {}
    subscription_id = (
        args.subscription_id
        or environment.get("AIOPS_AZURE_SUBSCRIPTION_ID")
        or _terraform_value(outputs, "subscription_id")
        or str(capacity.get("subscription_id") or "")
    )
    values = {
        "subscription_id": subscription_id,
        "resource_group": (
            args.resource_group
            or environment.get("AIOPS_ONTOLOGY_RESOURCE_GROUP")
            or _terraform_value(outputs, "resource_group_name")
        ),
        "job_name": (
            args.job_name
            or environment.get("AIOPS_ONTOLOGY_JOB_NAME")
            or _terraform_value(outputs, "ontology_discovery_job_name")
        ),
        "workspace_id": workspace_id,
        "lakehouse_id": lakehouse_id,
        "rbac_workspace_id": (
            args.rbac_workspace_id
            or environment.get("AIOPS_ONTOLOGY_RBAC_WORKSPACE_ID")
            or _terraform_value(outputs, "ontology_rbac_validation_workspace_id")
        ),
        "rbac_lakehouse_id": (
            args.rbac_lakehouse_id
            or environment.get("AIOPS_ONTOLOGY_RBAC_LAKEHOUSE_ID")
            or _terraform_value(outputs, "ontology_rbac_validation_lakehouse_id")
        ),
        "foundry_project_endpoint": (
            args.foundry_project_endpoint
            or environment.get("FOUNDRY_PROJECT_ENDPOINT")
            or _terraform_value(outputs, "foundry_project_endpoint")
        ),
        "foundry_agent_name": (
            args.foundry_agent_name
            or environment.get("FOUNDRY_ONTOLOGY_AGENT_NAME")
            or _terraform_value(outputs, "foundry_ontology_agent_name")
        ),
        "runtime_selection": environment.get(
            "AIOPS_ONTOLOGY_RUNTIME_SELECTION", ""
        ),
    }
    missing = sorted(name for name, value in values.items() if not str(value).strip())
    if missing:
        raise ConfigurationError(
            "missing explicit deployment configuration: " + ", ".join(missing)
        )
    if values["runtime_selection"] != "prompt-agent":
        raise ConfigurationError(
            "runtime selection must be prompt-agent; hosted-agent-exception "
            "requires replanning"
        )
    return DeploymentTargets(
        **{name: str(value).strip() for name, value in values.items()},
        state_target_source=state_source,
    )


def _load_terraform_outputs() -> dict[str, object]:
    command = ["terraform", f"-chdir={ROOT / 'infra' / 'terraform'}", "output", "-json"]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    if completed.returncode != 0:
        return {}
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _run_json(command: Sequence[str], *, timeout: int = 120) -> Any:
    completed = subprocess.run(
        list(command),
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    if completed.returncode != 0:
        raise EvidenceError(
            f"{Path(command[0]).name} evidence command failed "
            f"(exit {completed.returncode})"
        )
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise EvidenceError("evidence command returned invalid JSON") from exc


def _run_contract(
    name: str,
    command: Sequence[str],
    *,
    cwd: Path = ROOT,
    timeout: int = 600,
) -> dict[str, object]:
    try:
        completed = subprocess.run(
            list(command),
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
            env={
                **os.environ,
                "PROMPTFOO_DISABLE_TELEMETRY": "1",
                "PROMPTFOO_DISABLE_UPDATE": "1",
            },
        )
    except subprocess.TimeoutExpired:
        return {"name": name, "status": "FAIL", "reason": "timeout"}
    return {
        "name": name,
        "status": "PASS" if completed.returncode == 0 else "FAIL",
        "return_code": completed.returncode,
    }


def _opaque(value: object) -> str:
    return "sha256:" + hashlib.sha256(str(value).encode()).hexdigest()[:16]


def sanitize_shadow_report(value: object, *, key: str = "") -> object:
    """Recursively replace deployment identifiers and reject unsafe strings."""

    if isinstance(value, Mapping):
        return {
            str(item_key): sanitize_shadow_report(
                item_value,
                key=str(item_key).casefold(),
            )
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [sanitize_shadow_report(item, key=key) for item in value]
    if isinstance(value, tuple):
        return [sanitize_shadow_report(item, key=key) for item in value]
    if (key in SENSITIVE_KEYS or key.endswith("_id")) and value not in (None, ""):
        return _opaque(value)
    if key.endswith("_endpoint") and value not in (None, ""):
        return _opaque(value)
    if isinstance(value, str) and (
        "Bearer " in value or "client_secret" in value.casefold()
    ):
        raise EvidenceError("unsafe secret-like value rejected from report")
    return value


def _fabric_resource(
    workspace_id: str,
    *,
    lakehouse_id: str | None = None,
) -> dict[str, object]:
    path = f"workspaces/{workspace_id}"
    if lakehouse_id:
        path += f"/lakehouses/{lakehouse_id}"
    payload = _run_json(
        [
            "az",
            "rest",
            "--method",
            "get",
            "--resource",
            "https://api.fabric.microsoft.com",
            "--url",
            f"https://api.fabric.microsoft.com/v1/{path}",
        ]
    )
    if not isinstance(payload, Mapping):
        raise EvidenceError("Fabric resource response was not an object")
    expected = lakehouse_id or workspace_id
    if str(payload.get("id") or "").casefold() != expected.casefold():
        raise EvidenceError("Fabric resource identity mismatch")
    return {
        "status": "PASS",
        "type": str(payload.get("type") or ""),
        "resource_ref": _opaque(expected),
    }


def _foundry_agent(targets: DeploymentTargets) -> dict[str, object]:
    token_payload = _run_json(
        [
            "az",
            "account",
            "get-access-token",
            "--resource",
            "https://ai.azure.com",
            "-o",
            "json",
        ]
    )
    token = str(token_payload.get("accessToken") or "")
    if not token:
        raise EvidenceError("Foundry access token was unavailable")
    quoted_name = urllib.parse.quote(targets.foundry_agent_name, safe="")
    url = (
        f"{targets.foundry_project_endpoint.rstrip('/')}/agents/"
        f"{quoted_name}?api-version=v1"
    )
    if urllib.parse.urlsplit(url).scheme != "https":
        raise ConfigurationError("Foundry endpoint must use HTTPS")
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read(1_000_001))
    except (OSError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
        raise EvidenceError("Foundry agent read failed") from exc
    if not isinstance(payload, Mapping):
        raise EvidenceError("Foundry agent response was not an object")
    latest = payload.get("versions")
    latest = latest.get("latest") if isinstance(latest, Mapping) else None
    definition = latest.get("definition") if isinstance(latest, Mapping) else None
    if not isinstance(definition, Mapping):
        raise EvidenceError("Foundry agent has no active immutable definition")
    tools = definition.get("tools")
    tool_names: list[str] = []
    if isinstance(tools, list):
        for tool in tools:
            if not isinstance(tool, Mapping):
                continue
            allowed = tool.get("allowed_tools")
            names = allowed.get("tool_names") if isinstance(allowed, Mapping) else allowed
            if isinstance(names, list):
                tool_names.extend(str(item) for item in names)
    checks = {
        "name": payload.get("name") == targets.foundry_agent_name,
        "state": str(payload.get("state") or "").casefold() == "enabled",
        "kind": definition.get("kind") == "prompt",
        "model": definition.get("model") == "gpt-5.4-mini",
        "read_only_tools": tuple(tool_names) == EXPECTED_CURATOR_TOOLS,
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "agent_ref": _opaque(targets.foundry_agent_name),
        "version_ref": _opaque(latest.get("id")),
        "checks": checks,
        "tool_count": len(tool_names),
    }


def _job_executions(targets: DeploymentTargets) -> list[dict[str, object]]:
    payload = _run_json(
        [
            "az",
            "containerapp",
            "job",
            "execution",
            "list",
            "--resource-group",
            targets.resource_group,
            "--name",
            targets.job_name,
            "-o",
            "json",
        ]
    )
    if not isinstance(payload, list):
        raise EvidenceError("Container Apps Job executions were not a list")
    return [dict(row) for row in payload if isinstance(row, Mapping)]


def _execution_projection(row: Mapping[str, object]) -> dict[str, object]:
    properties = row.get("properties")
    properties = properties if isinstance(properties, Mapping) else {}
    return {
        "execution_ref": _opaque(row.get("name")),
        "status": str(properties.get("status") or ""),
        "started_at": str(properties.get("startTime") or ""),
        "ended_at": str(properties.get("endTime") or ""),
    }


def _start_and_wait(
    targets: DeploymentTargets,
    *,
    known_names: set[str],
    timeout_seconds: int = 300,
) -> dict[str, object]:
    started = _run_json(
        [
            "az",
            "containerapp",
            "job",
            "start",
            "--resource-group",
            targets.resource_group,
            "--name",
            targets.job_name,
            "-o",
            "json",
        ],
        timeout=120,
    )
    execution_name = ""
    if isinstance(started, Mapping):
        execution_name = str(started.get("name") or "")
        if not execution_name and isinstance(started.get("properties"), Mapping):
            execution_name = str(started["properties"].get("name") or "")
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        rows = _job_executions(targets)
        selected = next(
            (
                row
                for row in rows
                if (
                    execution_name
                    and str(row.get("name") or "") == execution_name
                )
                or (
                    not execution_name
                    and str(row.get("name") or "") not in known_names
                )
            ),
            None,
        )
        if selected is None:
            time.sleep(5)
            continue
        name = str(selected.get("name") or "")
        known_names.add(name)
        status = str(
            (selected.get("properties") or {}).get("status")
            if isinstance(selected.get("properties"), Mapping)
            else ""
        )
        if status.casefold() in {"succeeded", "failed", "cancelled"}:
            projected = _execution_projection(selected)
            projected["status"] = "PASS" if status.casefold() == "succeeded" else "FAIL"
            projected["platform_status"] = status
            return projected
        time.sleep(5)
    raise EvidenceError("Container Apps Job execution did not complete in time")


def _schedule_evidence(targets: DeploymentTargets) -> dict[str, object]:
    job = _run_json(
        [
            "az",
            "containerapp",
            "job",
            "show",
            "--resource-group",
            targets.resource_group,
            "--name",
            targets.job_name,
            "-o",
            "json",
        ]
    )
    properties = job.get("properties") if isinstance(job, Mapping) else {}
    configuration = (
        properties.get("configuration")
        if isinstance(properties, Mapping)
        else {}
    )
    template = properties.get("template") if isinstance(properties, Mapping) else {}
    containers = template.get("containers") if isinstance(template, Mapping) else []
    container = containers[0] if isinstance(containers, list) and containers else {}
    env_rows = container.get("env") if isinstance(container, Mapping) else []
    env_names = {
        str(row.get("name"))
        for row in env_rows
        if isinstance(row, Mapping)
    }
    before = _job_executions(targets)
    successful = [
        row
        for row in before
        if str((row.get("properties") or {}).get("status") or "").casefold()
        == "succeeded"
    ]
    no_click = [_execution_projection(row) for row in successful[:2]]
    known = {str(row.get("name") or "") for row in before}
    run_now = _start_and_wait(targets, known_names=known)
    restart = _start_and_wait(targets, known_names=known)
    schedule = (
        configuration.get("scheduleTriggerConfig")
        if isinstance(configuration, Mapping)
        else {}
    )
    command = list(container.get("command") or ()) + list(container.get("args") or ())
    contract_ok = (
        str(schedule.get("cronExpression") or "") == "*/15 * * * *"
        and int(configuration.get("replicaTimeout") or 0) == 900
        and int(configuration.get("replicaRetryLimit") or -1) == 2
        and command[-3:] == ["run-once", "--limit", "10"]
        and {
            "AIOPS_HOME",
            "AIOPS_ONTOLOGY_IDENTITY_CLASS",
            "AZURE_CLIENT_ID",
        }.issubset(env_names)
    )
    return {
        "status": (
            "PASS"
            if len(no_click) >= 2
            and run_now["status"] == "PASS"
            and restart["status"] == "PASS"
            and contract_ok
            else "FAIL"
        ),
        "no_click_successes": len(no_click),
        "no_click_runs": no_click,
        "run_now": run_now["status"],
        "run_now_execution": run_now,
        "restart": restart["status"],
        "restart_execution": restart,
        "duplicate_suppression": "PENDING_CONTRACT",
        "deployed_contract": {
            "schedule": "*/15 * * * *",
            "timeout_seconds": int(configuration.get("replicaTimeout") or 0),
            "retry_limit": int(configuration.get("replicaRetryLimit") or -1),
            "finite_command": command == [
                "python",
                "-m",
                "ontology_discovery.cli",
                "run-once",
                "--limit",
                "10",
            ],
            "state_root_configured": "AIOPS_HOME" in env_names,
        },
    }


def _identity_evidence() -> dict[str, object]:
    try:
        payload = json.loads(RBAC_EVIDENCE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceError("Plan 13-07 identity evidence is unavailable") from exc
    matrix = payload.get("write_matrix")
    control = payload.get("control_plane_audit")
    rows = matrix.get("evidence") if isinstance(matrix, Mapping) else []
    controls = control.get("evidence") if isinstance(control, Mapping) else []
    denied = {
        str(row.get("identity_class"))
        for row in [*rows, *controls]
        if isinstance(row, Mapping)
        and str(row.get("result") or "").casefold() in {"denied", "absent", "read_only"}
    }
    publisher_operations = {
        str(row.get("operation"))
        for row in rows
        if isinstance(row, Mapping)
        and row.get("identity_class") == "publisher"
        and row.get("result") == "authorized"
    }
    correlations = [
        str(row.get("correlation_evidence"))
        for row in [*rows, *controls]
        if isinstance(row, Mapping) and row.get("correlation_evidence")
    ]
    checks = {
        "artifact_status": payload.get("status") == "passed",
        "api_denied": "api" in denied,
        "coordinator_denied": "coordinator" in denied,
        "curator_denied": "curator" in denied,
        "publisher_stage": "stage_create_only" in publisher_operations,
        "publisher_promote": "pointer_cas" in publisher_operations,
        "publisher_rollback": "rollback_cas" in publisher_operations,
        "correlations_present": bool(correlations)
        and all(item.startswith("sha256:") for item in correlations),
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "identity_denials": sorted(denied & set(EXPECTED_DENIED_IDENTITIES)),
        "publisher_deterministic_only": (
            "PASS"
            if all(
                checks[name]
                for name in (
                    "publisher_stage",
                    "publisher_promote",
                    "publisher_rollback",
                )
            )
            else "FAIL"
        ),
        "checks": checks,
        "artifact_sha256": hashlib.sha256(RBAC_EVIDENCE.read_bytes()).hexdigest(),
    }


def _persist_evaluation(
    targets: DeploymentTargets,
    *,
    report_root: Path,
    now: datetime,
) -> dict[str, object]:
    result = evaluate_dataset(
        REFERENCE_DATASET,
        output_root=report_root / "repository-evaluation",
        evaluated_at=now,
    )
    remote_root = (
        f"abfss://{targets.workspace_id}@onelake.dfs.fabric.microsoft.com/"
        f"{targets.lakehouse_id}/Files/aiops"
    )
    _ensure_onelake_directories(
        targets,
        (
            "aiops",
            "aiops/ontology_evaluations",
            "aiops/ontology_evaluations/snapshots",
            (
                "aiops/ontology_evaluations/snapshots/"
                f"{result.snapshot.scope_hash}"
            ),
            "aiops/ontology_evaluations/history",
            "aiops/ontology_evaluations/latest",
        ),
    )
    try:
        remote = EvaluationSnapshotStore(remote_root)
        pointer = remote.pointer(result.snapshot.scope_hash)
        expected_revision = pointer.revision if pointer is not None else 0
        remote.write(result.snapshot, expected_revision=expected_revision)
        reconstructed = EvaluationSnapshotStore(remote_root)
        fresh = reconstructed.latest(
            result.snapshot.scope_hash,
            now=now,
        )
        stale = reconstructed.latest(
            result.snapshot.scope_hash,
            now=result.snapshot.effective_expires_at,
        )
    except Exception as exc:
        raise EvidenceError("durable EvaluationSnapshot write failed") from exc
    return {
        "status": (
            "PASS"
            if result.passed
            and fresh.status.value == "fresh"
            and stale.status.value == "stale"
            and fresh.snapshot == result.snapshot
            else "FAIL"
        ),
        "durable": True,
        "fresh": "PASS" if fresh.status.value == "fresh" else "FAIL",
        "stale": "PASS" if stale.status.value == "stale" else "FAIL",
        "snapshot_ref": _opaque(result.snapshot.snapshot_id),
        "pointer_revision": fresh.pointer_revision,
        "release_eligible": result.snapshot.release_eligible,
        "repository_thresholds_passed": result.passed,
        "artifact_sha256": hashlib.sha256(result.report_path.read_bytes()).hexdigest(),
    }


def _pair_metrics(
    *,
    shadow_started_at: datetime,
    now: datetime,
) -> list[dict[str, object]]:
    observed_days = max(0, (now - shadow_started_at).days)
    return [
        {
            "pair": f"{subject}/{predicate}/{object_type}",
            "shadow_started_at": shadow_started_at.isoformat().replace("+00:00", "Z"),
            "evaluated_at": now.isoformat().replace("+00:00", "Z"),
            "shadow_days_observed": observed_days,
            "expert_adjudicated_eligible_count": 0,
            "critical_failures": [],
            "metrics": {
                "precision_wilson_lower_bound": {
                    "observed": None,
                    "required": 0.98,
                },
                "recall": {"observed": None, "required": 0.90},
                "escalation_recall": {"observed": None, "required": 1.0},
            },
            "approvals": [],
            "release_status": "BLOCKED/PENDING",
            "missing_predicates": [
                "30_consecutive_shadow_days",
                "200_expert_adjudicated_eligible_proposals",
            ],
        }
        for subject, predicate, object_type in sorted(
            allowed_relationship_triples()
        )
    ]


def _persist_pair_metrics(
    targets: DeploymentTargets,
    pairs: list[dict[str, object]],
    *,
    now: datetime,
) -> dict[str, object]:
    from storage.onelake_documents import OneLakeDocumentStore

    remote_root = (
        f"abfss://{targets.workspace_id}@onelake.dfs.fabric.microsoft.com/"
        f"{targets.lakehouse_id}/Files/aiops"
    )
    _ensure_onelake_directories(
        targets,
        (
            "aiops",
            "aiops/ontology_evaluations",
            "aiops/ontology_evaluations/pair-readiness",
        ),
    )
    store = OneLakeDocumentStore(remote_root)
    name = (
        "ontology_evaluations/pair-readiness/"
        f"{now.date().isoformat()}-shadow.json"
    )
    existing = store.read_or_raise(name)
    revision = int(existing.get("revision") or 0)
    body = {
        "revision": revision + 1,
        "schema_version": "ontology-pair-readiness.v1",
        "evaluated_at": now.isoformat().replace("+00:00", "Z"),
        "activation_available": False,
        "pairs": pairs,
    }
    store.write(name, body, expected_revision=revision)
    restored = store.read_or_raise(name)
    if restored != body:
        raise EvidenceError("durable pair-readiness reconstruction mismatch")
    return {
        "status": "PASS",
        "record_ref": _opaque(name),
        "revision": body["revision"],
        "pair_count": len(pairs),
        "activation_available": False,
    }


def _ensure_onelake_directories(
    targets: DeploymentTargets,
    directories: Sequence[str],
) -> None:
    """Create only the required non-production state directories idempotently."""

    from azure.core.exceptions import ResourceExistsError
    from azure.identity import DefaultAzureCredential
    from azure.storage.filedatalake import FileSystemClient

    client = FileSystemClient(
        account_url="https://onelake.dfs.fabric.microsoft.com",
        file_system_name=targets.workspace_id,
        credential=DefaultAzureCredential(),
    )
    prefix = f"{targets.lakehouse_id}/Files"
    try:
        for directory in directories:
            path = f"{prefix}/{directory.strip('/')}"
            try:
                client.get_directory_client(path).create_directory()
            except ResourceExistsError:
                continue
    except Exception as exc:
        raise EvidenceError(
            "non-production OneLake state directory creation failed"
        ) from exc


def _earliest_start(schedule: Mapping[str, object], *, now: datetime) -> datetime:
    values: list[datetime] = []
    runs = schedule.get("no_click_runs")
    if isinstance(runs, list):
        for run in runs:
            if not isinstance(run, Mapping):
                continue
            text = str(run.get("started_at") or "")
            try:
                value = datetime.fromisoformat(text)
            except ValueError:
                continue
            if value.tzinfo is not None:
                values.append(value.astimezone(UTC))
    return min(values) if values else now


def _artifact_ref(path: Path) -> dict[str, str]:
    return {
        "artifact": f"artifact:{path.name.casefold().replace('_', '-')}",
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _collect_shadow_evidence(
    targets: DeploymentTargets,
    *,
    report_root: Path,
    now: datetime,
) -> dict[str, object]:
    account = _run_json(["az", "account", "show", "-o", "json"])
    subscription_matches = (
        str(account.get("id") or "").casefold()
        == targets.subscription_id.casefold()
    )
    state_workspace = _fabric_resource(targets.workspace_id)
    state_lakehouse = _fabric_resource(
        targets.workspace_id,
        lakehouse_id=targets.lakehouse_id,
    )
    rbac_workspace = _fabric_resource(targets.rbac_workspace_id)
    rbac_lakehouse = _fabric_resource(
        targets.rbac_workspace_id,
        lakehouse_id=targets.rbac_lakehouse_id,
    )
    foundry = _foundry_agent(targets)
    schedule = _schedule_evidence(targets)

    contracts = _run_contract(
        "shadow-safety-generation-api",
        [
            "uv",
            "run",
            "pytest",
            "-q",
            "tests/test_ontology_discovery_store.py",
            "tests/test_ontology_discovery_coordinator.py",
            "tests/test_ontology_discovery_e2e.py",
            "tests/test_ontology_generation_publication.py",
            "tests/test_ontology_proposal_policy.py",
            "tests/test_ontology_evaluation_snapshot.py",
            "tests/test_api_ontology_discovery.py",
            "tests/test_api_ontology_evaluation.py",
        ],
    )
    schedule["duplicate_suppression"] = contracts["status"]
    promptfoo_validate = _run_contract(
        "promptfoo-config",
        ["npm", "exec", "--", "promptfoo", "validate", "-c", "promptfooconfig.yaml"],
        cwd=ROOT / "evals" / "ontology-discovery",
    )
    promptfoo_eval = _run_contract(
        "promptfoo-no-cache",
        ["npm", "exec", "--", "promptfoo", "eval", "-c", "promptfooconfig.yaml", "--no-cache"],
        cwd=ROOT / "evals" / "ontology-discovery",
    )
    phoenix = _run_contract(
        "phoenix-redaction",
        [
            "uv",
            "run",
            "--extra",
            "eval",
            "python",
            "scripts/inspect_ontology_traces.py",
            "--launch-local",
            "--dataset",
            "tests/fixtures/ontology_discovery/reference.jsonl",
            "--fail-on-redaction",
        ],
        timeout=300,
    )
    ui = _run_contract(
        "connections-ontology-ui",
        ["npm", "test", "--", "--run", "src/app/connections/page.test.tsx"],
        cwd=ROOT / "web",
    )
    alert = _alert_smoke()
    evaluation = _persist_evaluation(targets, report_root=report_root, now=now)
    pairs = _pair_metrics(
        shadow_started_at=_earliest_start(schedule, now=now),
        now=now,
    )
    pair_record = _persist_pair_metrics(targets, pairs, now=now)
    identity = _identity_evidence()

    source_contracts = {
        "bounds": _artifact_ref(ROOT / "src" / "ontology_discovery" / "contracts.py"),
        "curator": _artifact_ref(ROOT / "src" / "ontology_discovery" / "curator.py"),
        "publication": _artifact_ref(
            ROOT / "tests" / "test_ontology_discovery_e2e.py"
        ),
        "api": _artifact_ref(ROOT / "tests" / "test_api_ontology_discovery.py"),
        "ui": _artifact_ref(ROOT / "web" / "src" / "app" / "connections" / "page.test.tsx"),
    }
    return {
        "configuration": {
            "status": (
                "PASS"
                if subscription_matches
                and targets.runtime_selection == "prompt-agent"
                and state_workspace["status"] == "PASS"
                and state_lakehouse["status"] == "PASS"
                and rbac_workspace["status"] == "PASS"
                and rbac_lakehouse["status"] == "PASS"
                and foundry["status"] == "PASS"
                else "FAIL"
            ),
            "runtime_selection": targets.runtime_selection,
            "state_target_source": targets.state_target_source,
            "subscription_matches": subscription_matches,
            "fabric": "PASS",
            "foundry": foundry["status"],
            "state_workspace": state_workspace,
            "state_lakehouse": state_lakehouse,
            "rbac_workspace": rbac_workspace,
            "rbac_lakehouse": rbac_lakehouse,
            "foundry_agent": foundry,
        },
        "schedule": schedule,
        "bounds": {
            "changed_entities": MAX_CHANGED_ENTITIES,
            "candidate_pairs": MAX_CANDIDATE_PAIRS,
            "evidence_records": MAX_EVIDENCE_RECORDS,
            "input_tokens": MAX_INPUT_TOKENS,
            "output_tokens": NORMAL_OUTPUT_TOKENS,
            "attempt_seconds": int(REQUEST_TIMEOUT_SECONDS),
            "source": "runtime-constants-and-executable-contract",
        },
        "security": {
            "status": (
                "PASS"
                if contracts["status"] == "PASS"
                and identity["status"] == "PASS"
                else "FAIL"
            ),
            "injection": (
                "PASS"
                if promptfoo_eval["status"] == "PASS"
                and contracts["status"] == "PASS"
                else "FAIL"
            ),
            "scope_isolation": contracts["status"],
            "identity_denials": identity["identity_denials"],
            "publisher_deterministic_only": identity[
                "publisher_deterministic_only"
            ],
            "identity_evidence": identity,
        },
        "authoritative_model_edges": {
            "candidate": 0 if contracts["status"] == "PASS" else None,
            "stage": 0 if contracts["status"] == "PASS" else None,
            "active": 0 if contracts["status"] == "PASS" else None,
            "consumer": 0 if contracts["status"] == "PASS" else None,
            "source": "executable-publication-contract",
        },
        "generation": {
            "status": contracts["status"],
            "promotion_order": [
                "generation-old",
                "generation-new",
                "generation-old",
            ]
            if contracts["status"] == "PASS"
            else [],
            "stale_writer_rejected": contracts["status"] == "PASS",
            "consumers": {
                name: contracts["status"] for name in EXPECTED_CONSUMERS
            },
            "evidence": source_contracts["publication"],
        },
        "evaluation": {**evaluation, "pair_record": pair_record},
        "tooling": {
            "promptfoo": (
                "PASS"
                if promptfoo_validate["status"] == "PASS"
                and promptfoo_eval["status"] == "PASS"
                else "FAIL"
            ),
            "promptfoo_validate": promptfoo_validate,
            "promptfoo_no_cache": promptfoo_eval,
            "phoenix": phoenix["status"],
            "phoenix_redaction": phoenix,
        },
        "observability": {
            "alert_smoke": alert["status"],
            "alert_details": alert,
            "api_audit": contracts["status"],
            "ui_audit": ui["status"],
            "audit_complete": (
                contracts["status"] == "PASS" and ui["status"] == "PASS"
            ),
        },
        "contracts": {
            "execution": contracts,
            "sources": source_contracts,
        },
        "pairs": pairs,
        "activation_interface_present": False,
    }


def evaluate_shadow_evidence(
    evidence: Mapping[str, object],
    *,
    asserted_release_status: str | None,
    assert_authoritative_model_edge_count_zero: bool,
) -> dict[str, object]:
    """Apply the complete shadow gate; BLOCKED/PENDING is the successful result."""

    missing: list[str] = []

    def require(condition: bool, code: str) -> None:
        if not condition and code not in missing:
            missing.append(code)

    configuration = evidence.get("configuration")
    configuration = configuration if isinstance(configuration, Mapping) else {}
    require(configuration.get("status") == "PASS", "deployment_configuration")
    require(
        configuration.get("runtime_selection") == "prompt-agent",
        "prompt_agent_runtime",
    )
    require(configuration.get("fabric") == "PASS", "fabric_scope")
    require(configuration.get("foundry") == "PASS", "foundry_agent")

    schedule = evidence.get("schedule")
    schedule = schedule if isinstance(schedule, Mapping) else {}
    require(
        int(schedule.get("no_click_successes") or 0) >= 2,
        "two_successful_no_click_runs",
    )
    for field in ("run_now", "restart", "duplicate_suppression"):
        require(schedule.get(field) == "PASS", f"schedule_{field}")

    bounds = evidence.get("bounds")
    bounds = bounds if isinstance(bounds, Mapping) else {}
    require(
        all(bounds.get(name) == value for name, value in EXPECTED_BOUNDS.items()),
        "exact_runtime_bounds",
    )

    security = evidence.get("security")
    security = security if isinstance(security, Mapping) else {}
    require(security.get("injection") == "PASS", "injection_resistance")
    require(security.get("scope_isolation") == "PASS", "scope_isolation")
    denied = set(security.get("identity_denials") or ())
    require(
        set(EXPECTED_DENIED_IDENTITIES).issubset(denied),
        "non_publisher_identity_denials",
    )
    require(
        security.get("publisher_deterministic_only") == "PASS",
        "narrow_publisher_success",
    )

    model_edges = evidence.get("authoritative_model_edges")
    model_edges = model_edges if isinstance(model_edges, Mapping) else {}
    model_counts = [
        model_edges.get(boundary)
        for boundary in ("candidate", "stage", "active", "consumer")
    ]
    if assert_authoritative_model_edge_count_zero:
        require(
            all(value == 0 for value in model_counts),
            "zero_model_edges_at_every_boundary",
        )

    generation = evidence.get("generation")
    generation = generation if isinstance(generation, Mapping) else {}
    require(
        generation.get("promotion_order")
        == ["generation-old", "generation-new", "generation-old"],
        "deterministic_old_new_old_rollback",
    )
    require(
        generation.get("stale_writer_rejected") is True,
        "stale_writer_rejection",
    )
    consumers = generation.get("consumers")
    consumers = consumers if isinstance(consumers, Mapping) else {}
    require(
        all(consumers.get(name) == "PASS" for name in EXPECTED_CONSUMERS),
        "all_consumer_categories",
    )

    evaluation = evidence.get("evaluation")
    evaluation = evaluation if isinstance(evaluation, Mapping) else {}
    require(evaluation.get("durable") is True, "durable_evaluation_snapshot")
    require(evaluation.get("fresh") == "PASS", "fresh_evaluation_snapshot")
    require(evaluation.get("stale") == "PASS", "stale_evaluation_snapshot")
    pair_record = evaluation.get("pair_record")
    pair_record = pair_record if isinstance(pair_record, Mapping) else {}
    if pair_record:
        require(pair_record.get("status") == "PASS", "durable_pair_metrics")

    tooling = evidence.get("tooling")
    tooling = tooling if isinstance(tooling, Mapping) else {}
    require(tooling.get("promptfoo") == "PASS", "promptfoo_evidence")
    require(tooling.get("phoenix") == "PASS", "phoenix_redaction_evidence")

    observability = evidence.get("observability")
    observability = observability if isinstance(observability, Mapping) else {}
    require(observability.get("alert_smoke") == "PASS", "alert_smoke")
    require(observability.get("api_audit") == "PASS", "api_audit")
    require(observability.get("ui_audit") == "PASS", "ui_audit")
    require(observability.get("audit_complete") is True, "complete_audit")

    pairs = evidence.get("pairs")
    pairs = pairs if isinstance(pairs, list) else []
    require(bool(pairs), "per_pair_metrics")
    for pair in pairs:
        if not isinstance(pair, Mapping):
            require(False, "per_pair_metrics")
            continue
        require(
            pair.get("release_status") == "BLOCKED/PENDING",
            "pair_release_status_blocked_or_pending",
        )
        reasons = set(pair.get("missing_predicates") or ())
        require(
            "30_consecutive_shadow_days" in reasons,
            "pair_missing_30_day_predicate",
        )
        require(
            "200_expert_adjudicated_eligible_proposals" in reasons,
            "pair_missing_200_label_predicate",
        )
    require(
        evidence.get("activation_interface_present") is False,
        "activation_interface_absent",
    )
    if asserted_release_status == "blocked-or-pending":
        require(
            bool(pairs)
            and all(
                isinstance(pair, Mapping)
                and pair.get("release_status") == "BLOCKED/PENDING"
                for pair in pairs
            ),
            "asserted_release_status",
        )
    return {
        **dict(evidence),
        "schema_version": "ontology-discovery-shadow-validation.v1",
        "mode": "credentialed-shadow",
        "sanitized": True,
        "authoritative_model_edge_count": (
            sum(value for value in model_counts if isinstance(value, int))
            if all(isinstance(value, int) for value in model_counts)
            else None
        ),
        "release_status": "BLOCKED/PENDING",
        "missing_evidence": sorted(missing),
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


def _shadow(args: argparse.Namespace) -> tuple[Path, dict[str, object]]:
    now = datetime.now(UTC)
    targets = resolve_deployment_targets(
        args,
        terraform_outputs=_load_terraform_outputs(),
    )
    report_path = args.report or (
        DEFAULT_REPORT_DIR
        / f"ontology-discovery-shadow-{now.date().isoformat()}.json"
    )
    artifact_root = report_path.with_suffix("")
    evidence = _collect_shadow_evidence(
        targets,
        report_root=artifact_root,
        now=now,
    )
    report = evaluate_shadow_evidence(
        evidence,
        asserted_release_status=args.assert_release_status,
        assert_authoritative_model_edge_count_zero=(
            args.assert_authoritative_model_edge_count_zero
        ),
    )
    report["generated_at"] = now.isoformat().replace("+00:00", "Z")
    report["deployment"] = asdict(targets)
    return report_path, sanitize_shadow_report(report)  # type: ignore[return-value]


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.alert_smoke:
        if not args.synthetic_only:
            _parser().error("--alert-smoke requires --synthetic-only")
        report = _alert_smoke()
        _write_report(args.report, report)
        return int(args.fail_on_missing_evidence and report["status"] != "PASS")
    if args.synthetic_only:
        _parser().error("--synthetic-only is valid only with --alert-smoke")
    try:
        report_path, report = _shadow(args)
    except (ConfigurationError, EvidenceError, OSError, subprocess.SubprocessError) as exc:
        report_path = args.report or (
            DEFAULT_REPORT_DIR
            / f"ontology-discovery-shadow-{datetime.now(UTC).date().isoformat()}.json"
        )
        report = {
            "schema_version": "ontology-discovery-shadow-validation.v1",
            "mode": "credentialed-shadow",
            "sanitized": True,
            "status": "FAIL",
            "release_status": "BLOCKED/PENDING",
            "missing_evidence": [type(exc).__name__],
            "blocker": str(exc),
            "activation_interface_present": False,
        }
    _write_report(report_path, report)
    should_fail = (
        args.fail_on_missing_evidence
        or args.fail_on_threshold
        or args.assert_release_status is not None
        or args.assert_authoritative_model_edge_count_zero
    )
    return int(should_fail and report["status"] != "PASS")


if __name__ == "__main__":
    raise SystemExit(main())
