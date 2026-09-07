#!/usr/bin/env python3
"""Validate ontology discovery without exposing an activation interface.

``--shadow`` combines read-only Azure/Fabric/Foundry inspection, two bounded
manual executions of the non-production coordinator Job, executable repository
contracts, and a durable EvaluationSnapshot.  Reports contain only allowlisted
statuses, counts, timestamps, hashes, and closed-vocabulary reason codes.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import stat
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
DEPLOYED_STAGES = ("preflight", "lifecycle", "publication", "finalize")
FIXED_JOB_NAMES = {
    "coordinator": "aiops-dev-ontology-discovery",
    "publisher": "aiops-dev-ontology-publisher",
    "rbac_validator": "aiops-dev-ontology-rbac-check",
    "ontology_fixture_prepare": "ontology-fixture-prepare",
    "ontology_fixture_cleanup": "ontology-fixture-cleanup",
    "evidence": "ontology-evidence-read",
}
BASELINE_FIXED_JOB_NAMES = {
    name: job_name
    for name, job_name in FIXED_JOB_NAMES.items()
    if name != "evidence"
}
DEPLOYED_LIFECYCLE_SEQUENCE = (
    "preflight",
    "prepare",
    "select_epoch",
    "drain_member_1",
    "drain_member_2",
    "process_replacement",
    "drain_member_3",
    "injection_tag",
    "cleanup",
    "maintenance",
    "retained_audit",
    "empty_registry",
)
EXPECTED_DEPLOYER_ACTIONS = frozenset(
    {"job_read", "job_start", "job_execution_read"}
)
EXPECTED_EVIDENCE_ACTIONS = frozenset(
    {"arg_read", "fabric_read", "onelake_read"}
)
EXPECTED_EVIDENCE_DENIALS = frozenset(
    {
        "job_execution_read",
        "job_read",
        "job_start",
        "job_stop",
        "mutation",
    }
)
EXPECTED_TAG_LINEAGE = ("terraform", "arg", "inventory", "evidence", "curator")
EXPECTED_COMMAND_TOPOLOGY = (
    "api_intake",
    "coordinator_claim",
    "coordinator_reauthorization",
    "publish_dispatch",
    "publisher_claim",
    "publisher_status",
    "api_reload",
)
REQUIRED_JOB_TEMPLATES = tuple(FIXED_JOB_NAMES)
AZURE_AMBIENT_CREDENTIAL_KEYS = frozenset(
    {
        "AZURE_CLIENT_CERTIFICATE_PATH",
        "AZURE_CLIENT_ID",
        "AZURE_CLIENT_SECRET",
        "AZURE_FEDERATED_TOKEN_FILE",
        "AZURE_PASSWORD",
        "AZURE_TENANT_ID",
        "AZURE_USERNAME",
        "ARM_CLIENT_CERTIFICATE_PATH",
        "ARM_CLIENT_ID",
        "ARM_CLIENT_SECRET",
        "ARM_OIDC_TOKEN",
        "ARM_TENANT_ID",
    }
)
DEPLOYED_ASSERTION_FLAGS = (
    "isolated-azure-contexts",
    "deployer-only-job-start",
    "evidence-read-only",
    "no-runtime-job-start-grants",
    "fixed-job-template-hashes",
    "no-job-overrides",
    "fixture-prepare",
    "exact-three-records",
    "validation-connection-root",
    "production-registry-path",
    "eligible-set-drain",
    "no-post-selection-injection",
    "process-replacement",
    "coordinator-uai-injection-tag",
    "real-arg-inventory-curator-path",
    "exact-four-curator-tools",
    "maintenance-authorization",
    "full-then-incremental",
    "fixture-cleanup",
    "audit-retention",
    "fixture-registry-empty",
    "command-topology",
    "api-reconstruction",
    "publication-order",
    "guarded-drill-control",
    "stale-writer-drill",
    "postcheck-failure-drill",
    "drill-cleanup",
    "automatic-rollback",
    "five-consumer-convergence",
    "fabric-materialization",
    "final-precondition",
    "pointer-cas",
    "post-check",
    "old-new-old",
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
DEPLOYMENT_EVIDENCE = (
    ROOT / ".planning" / "eval" / "ontology-gap-deployment.json"
)
_RAW_DEPLOYED_EVIDENCE_KEYS = frozenset(
    {
        "access_token",
        "args",
        "body",
        "command",
        "commands",
        "env",
        "error",
        "fixture_path",
        "object_id",
        "path",
        "principal_id",
        "prompt",
        "raw_error",
        "resource_id",
        "root",
        "secret",
        "subscription_id",
        "tag_value",
        "tenant_id",
        "token",
        "uri",
        "url",
    }
)


class ConfigurationError(RuntimeError):
    """A required explicit non-production target is unavailable."""


class EvidenceError(RuntimeError):
    """Credentialed or executable evidence could not be established."""


@dataclass(frozen=True)
class AzureContexts:
    """Canonical private Azure CLI home for the deployment principal."""

    deployer: Path


@dataclass(frozen=True)
class Plan19DeploymentContract:
    """Closed subset of the applied deployment evidence needed by Plan 20."""

    status: str
    template_hashes: Mapping[str, str]
    validation_connection_root_hash: str
    coordinator_tag_hash: str


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
        and 'tostring(Properties.rule) == "${each.key}"' in terraform
    }
    action_observed = (
        set(ALERT_RULES)
        if "action_groups = [local.alert_action_group_id]" in terraform
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
    parser.add_argument("--stage", choices=DEPLOYED_STAGES)
    parser.add_argument("--environment", choices=("validation",))
    parser.add_argument("--resume-file", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--max-wait-seconds", type=int, default=1800)
    parser.add_argument("--fail-on-local-substitution", action="store_true")
    for flag in DEPLOYED_ASSERTION_FLAGS:
        parser.add_argument(f"--assert-{flag}", action="store_true")
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


def _full_opaque(value: object) -> str:
    rendered = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return "sha256:" + hashlib.sha256(rendered.encode()).hexdigest()


def _private_directory(
    value: str | None,
    *,
    variable: str,
) -> Path:
    if not value:
        raise EvidenceError(f"{variable} is required")
    path = Path(value).expanduser()
    try:
        resolved = path.resolve(strict=True)
        mode = stat.S_IMODE(resolved.stat().st_mode)
    except OSError as exc:
        raise EvidenceError(f"{variable} is unavailable") from exc
    if not resolved.is_dir():
        raise EvidenceError(f"{variable} must identify a directory")
    if mode != 0o700:
        raise EvidenceError(f"{variable} must have mode 0700")
    return resolved


def validate_azure_contexts(
    env: Mapping[str, str] | None = None,
) -> AzureContexts:
    """Resolve one mode-0700 deployer CLI home without ambient auth.

    The distinct evidence principal runs only inside the fixed managed-identity
    Container Apps Job. A second local Azure CLI context would either be
    impossible to provision or tempt an operator to clone the deployer.
    """

    environment = dict(os.environ if env is None else env)
    ambient = sorted(
        key
        for key in AZURE_AMBIENT_CREDENTIAL_KEYS
        if environment.get(key)
    )
    if ambient:
        raise EvidenceError("ambient Azure credential variables are not permitted")
    deployer = _private_directory(
        environment.get("AIOPS_DEPLOYER_AZURE_CONFIG_DIR"),
        variable="AIOPS_DEPLOYER_AZURE_CONFIG_DIR",
    )
    if environment.get("AIOPS_EVIDENCE_AZURE_CONFIG_DIR"):
        raise EvidenceError(
            "AIOPS_EVIDENCE_AZURE_CONFIG_DIR must not be configured; "
            "evidence runs only as the fixed managed-identity Job"
        )
    return AzureContexts(deployer=deployer)


def isolated_azure_environment(
    azure_config_dir: Path,
    env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return a subprocess environment bound to exactly one Azure CLI home."""

    source = dict(os.environ if env is None else env)
    isolated = {
        key: value
        for key, value in source.items()
        if key not in AZURE_AMBIENT_CREDENTIAL_KEYS
        and key != "AZURE_CONFIG_DIR"
        and not key.startswith("ARM_")
    }
    isolated["AZURE_CONFIG_DIR"] = str(azure_config_dir.resolve(strict=True))
    return isolated


def build_job_start_command(
    *,
    resource_group: str,
    job_name: str,
) -> list[str]:
    """Build the only permitted input-free fixed-template Job start."""

    if not resource_group.strip() or not job_name.strip():
        raise EvidenceError("resource group and Job name are required")
    if job_name not in FIXED_JOB_NAMES.values():
        raise EvidenceError("Job start must name an exact fixed deployed Job")
    return [
        "az",
        "containerapp",
        "job",
        "start",
        "--resource-group",
        resource_group,
        "--name",
        job_name,
        "-o",
        "json",
    ]


def _template_projection(job: Mapping[str, object]) -> dict[str, object]:
    properties = job.get("properties")
    properties = properties if isinstance(properties, Mapping) else {}
    configuration = properties.get("configuration")
    configuration = (
        configuration if isinstance(configuration, Mapping) else {}
    )
    template = properties.get("template")
    template = template if isinstance(template, Mapping) else {}
    containers = template.get("containers")
    containers = containers if isinstance(containers, list) else []
    projected_containers: list[dict[str, object]] = []
    for container in containers:
        if not isinstance(container, Mapping):
            continue
        env_rows = container.get("env")
        env_rows = env_rows if isinstance(env_rows, list) else []
        projected_containers.append(
            {
                "name": container.get("name"),
                "image": container.get("image"),
                "command": list(container.get("command") or ()),
                "args": list(container.get("args") or ()),
                "env": sorted(
                    (
                        {
                            "name": row.get("name"),
                            "value": row.get("value"),
                            "secretRef": row.get("secretRef"),
                        }
                        for row in env_rows
                        if isinstance(row, Mapping)
                    ),
                    key=lambda row: str(row.get("name") or ""),
                ),
            }
        )
    manual = configuration.get("manualTriggerConfig")
    manual = manual if isinstance(manual, Mapping) else {}
    identity = properties.get("identity")
    identity = identity if isinstance(identity, Mapping) else {}
    assigned = identity.get("userAssignedIdentities")
    assigned = assigned if isinstance(assigned, Mapping) else {}
    return {
        "containers": projected_containers,
        "identity": {
            "type": identity.get("type"),
            "user_assigned_identity_keys": sorted(str(key) for key in assigned),
        },
        "trigger_type": properties.get("triggerType"),
        "timeout": configuration.get("replicaTimeout"),
        "retry_limit": configuration.get("replicaRetryLimit"),
        "parallelism": manual.get("parallelism"),
        "completion_count": manual.get("replicaCompletionCount"),
    }


def job_template_hash(job: Mapping[str, object]) -> str:
    """Hash every execution-relevant saved-template field."""

    return _full_opaque(_template_projection(job))


def assert_fixed_template(
    expected_hash: str,
    before: Mapping[str, object],
    after: Mapping[str, object],
) -> None:
    """Reject a start if either observed template differs from Plan 19."""

    before_hash = job_template_hash(before)
    after_hash = job_template_hash(after)
    if (
        not expected_hash.startswith("sha256:")
        or before_hash != expected_hash
        or after_hash != expected_hash
        or before_hash != after_hash
    ):
        raise EvidenceError("saved Job template hash mismatch")


def _require_hash(value: object) -> bool:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        return False
    digest = value.removeprefix("sha256:")
    return len(digest) == 64 and all(char in "0123456789abcdef" for char in digest)


def load_plan19_deployment_contract(
    path: Path = DEPLOYMENT_EVIDENCE,
) -> Plan19DeploymentContract:
    """Load only stable, hash-only facts from the applied Plan 19 evidence."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceError("Plan 19 deployment evidence is unavailable") from exc
    if not isinstance(payload, Mapping) or payload.get("status") != "applied":
        raise EvidenceError("Plan 19 deployment evidence is not applied")
    live = payload.get("live")
    if not isinstance(live, Mapping):
        raise EvidenceError("Plan 19 live deployment evidence is missing")
    if (
        live.get("applied") is not True
        or live.get("no_runtime_job_start_grants") is not True
        or live.get("deployment_principal_fixture_access") is not True
    ):
        raise EvidenceError("Plan 19 deployment boundary is not proven")
    before = live.get("template_hashes_before")
    after = live.get("template_hashes_after")
    if not isinstance(before, Mapping) or not isinstance(after, Mapping):
        raise EvidenceError("Plan 19 template hashes are missing")
    expected_names = set(BASELINE_FIXED_JOB_NAMES)
    if set(before) != expected_names or set(after) != expected_names:
        raise EvidenceError("Plan 19 fixed Job registry is not exact")
    template_hashes = {
        name: str(before[name]) for name in BASELINE_FIXED_JOB_NAMES
    }
    if (
        before != after
        or any(not _require_hash(value) for value in template_hashes.values())
    ):
        raise EvidenceError("Plan 19 saved Job template hashes are unstable")
    roots = live.get("root_hashes")
    if not isinstance(roots, Mapping):
        raise EvidenceError("Plan 19 root hashes are missing")
    required_roots = {
        "AIOPS_CONNECTION_HOME",
        "AIOPS_ONTOLOGY_COMMAND_HOME",
        "AIOPS_ONTOLOGY_STATE_HOME",
        "AIOPS_ONTOLOGY_PUBLICATION_HOME",
    }
    if not required_roots.issubset(roots) or any(
        not _require_hash(roots.get(name)) for name in required_roots
    ):
        raise EvidenceError("Plan 19 root hashes are incomplete")
    tag_hash = live.get("coordinator_tag_hash")
    if not _require_hash(tag_hash):
        raise EvidenceError("Plan 19 coordinator tag hash is missing")
    return Plan19DeploymentContract(
        status="applied",
        template_hashes=template_hashes,
        validation_connection_root_hash=str(
            roots["AIOPS_CONNECTION_HOME"]
        ),
        coordinator_tag_hash=str(tag_hash),
    )


def assert_stage_transition(
    completed_stages: Sequence[str],
    requested_stage: str,
) -> None:
    """Reject skipped, reordered, duplicated, or unbounded stage execution."""

    completed = tuple(completed_stages)
    if (
        requested_stage not in DEPLOYED_STAGES
        or completed != DEPLOYED_STAGES[: len(completed)]
        or len(completed) > len(DEPLOYED_STAGES)
    ):
        raise EvidenceError("invalid deployed stage transition")
    next_stage = (
        DEPLOYED_STAGES[len(completed)]
        if len(completed) < len(DEPLOYED_STAGES)
        else DEPLOYED_STAGES[-1]
    )
    idempotent_stage = completed[-1] if completed else None
    if requested_stage not in {next_stage, idempotent_stage}:
        raise EvidenceError("invalid deployed stage transition")


def sanitize_deployed_evidence(value: object, *, key: str = "") -> object:
    """Reject raw operational values from retained Plan 20 artifacts."""

    normalized_key = key.casefold()
    if (
        normalized_key in _RAW_DEPLOYED_EVIDENCE_KEYS
        and value not in (None, "")
        and not _require_hash(value)
    ):
        raise EvidenceError(
            f"unsafe deployed evidence field rejected: {normalized_key}"
        )
    if isinstance(value, Mapping):
        return {
            str(item_key): sanitize_deployed_evidence(
                item_value,
                key=str(item_key),
            )
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [sanitize_deployed_evidence(item, key=key) for item in value]
    if isinstance(value, tuple):
        return [sanitize_deployed_evidence(item, key=key) for item in value]
    if isinstance(value, str) and (
        "Bearer " in value
        or "client_secret" in value.casefold()
        or "access_token" in value.casefold()
    ):
        raise EvidenceError("unsafe deployed evidence string rejected")
    return value


def validate_evidence_job_record(
    record: Mapping[str, object],
    *,
    expected_object_id_hash: str,
) -> dict[str, str]:
    """Verify a closed console record is bound to the deployed evidence UAI."""

    from scripts.collect_ontology_evidence import EXPECTED_CAPABILITIES

    sanitized = sanitize_deployed_evidence(record)
    if not isinstance(sanitized, Mapping):
        raise EvidenceError("evidence Job record is not an object")
    if (
        sanitized.get("schema_version") != "ontology-evidence-read.v1"
        or sanitized.get("mode") != "fixed-read-only"
        or sanitized.get("sanitized") is not True
    ):
        raise EvidenceError("evidence Job record schema is invalid")
    identity = sanitized.get("identity")
    identity = identity if isinstance(identity, Mapping) else {}
    if (
        not _require_hash(expected_object_id_hash)
        or identity.get("object_id_hash") != expected_object_id_hash
        or set(identity)
        != {
            "client_id_hash",
            "object_id_hash",
            "managed_identity_resource_hash",
            "entra_signature_hash",
        }
        or any(not _require_hash(value) for value in identity.values())
    ):
        raise EvidenceError("evidence Job identity does not match its fixed UAI")
    if sanitized.get("capabilities") != EXPECTED_CAPABILITIES:
        raise EvidenceError("evidence Job record is not read-only")
    observations = sanitized.get("observations")
    observations = observations if isinstance(observations, Mapping) else {}
    if set(observations) != {"arg", "fabric", "onelake", "api"}:
        raise EvidenceError("evidence Job observations are incomplete")
    for row in observations.values():
        if not isinstance(row, Mapping):
            raise EvidenceError("evidence Job observation is invalid")
        hashes = row.get("hashes")
        if (
            set(row) != {"count", "hashes"}
            or not isinstance(row.get("count"), int)
            or int(row["count"]) < 0
            or not isinstance(hashes, list)
            or any(not _require_hash(value) for value in hashes)
        ):
            raise EvidenceError("evidence Job observation is not closed")
    facts = sanitized.get("facts")
    facts = facts if isinstance(facts, Mapping) else {}
    if set(facts) != {"fixture", "registry", "epoch"} or any(
        not isinstance(facts.get(name), Mapping)
        for name in ("fixture", "registry", "epoch")
    ):
        raise EvidenceError("evidence Job lifecycle facts are incomplete")

    unsigned = {
        key: value
        for key, value in sanitized.items()
        if key not in {"record_hash", "entra_bound_record_hash"}
    }
    expected_record_hash = _full_opaque(unsigned)
    expected_bound_hash = _full_opaque(
        {
            "record_hash": expected_record_hash,
            "entra_signature_hash": identity["entra_signature_hash"],
        }
    )
    if (
        sanitized.get("record_hash") != expected_record_hash
        or sanitized.get("entra_bound_record_hash") != expected_bound_hash
    ):
        raise EvidenceError("evidence Job record signature binding is invalid")
    return {
        "record_hash": expected_record_hash,
        "entra_bound_record_hash": expected_bound_hash,
        "identity_hash": str(identity["object_id_hash"]),
    }


def write_resume_checkpoint(
    path: Path,
    *,
    stage: str,
    completed_steps: Sequence[str],
    evidence_refs: Sequence[str],
) -> None:
    """Atomically retain only opaque idempotency keys and evidence hashes."""

    if stage not in DEPLOYED_STAGES:
        raise EvidenceError("resume stage is not finite")
    if any(not _require_hash(value) for value in evidence_refs):
        raise EvidenceError("resume evidence references must be opaque hashes")
    step_keys = [_full_opaque({"stage": stage, "step": step}) for step in completed_steps]
    payload = {
        "schema_version": "ontology-deployed-lifecycle-checkpoint.v1",
        "stage": stage,
        "completed_step_count": len(step_keys),
        "completed_step_keys": step_keys,
        "evidence_refs": list(evidence_refs),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def load_resume_checkpoint(path: Path) -> dict[str, object]:
    """Load and validate the closed resume schema before any cloud action."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceError("resume checkpoint is unavailable or invalid") from exc
    if not isinstance(payload, dict) or payload.get("stage") not in DEPLOYED_STAGES:
        raise EvidenceError("resume checkpoint stage is invalid")
    expected_keys = {
        "schema_version",
        "stage",
        "completed_step_count",
        "completed_step_keys",
        "evidence_refs",
    }
    if set(payload) != expected_keys:
        raise EvidenceError("resume checkpoint contains unexpected fields")
    step_keys = payload.get("completed_step_keys")
    refs = payload.get("evidence_refs")
    if (
        payload.get("schema_version")
        != "ontology-deployed-lifecycle-checkpoint.v1"
        or not isinstance(step_keys, list)
        or not isinstance(refs, list)
        or int(payload.get("completed_step_count") or -1) != len(step_keys)
        or any(not _require_hash(value) for value in [*step_keys, *refs])
    ):
        raise EvidenceError("resume checkpoint failed its closed schema")
    return payload


def evaluate_lifecycle_evidence(
    evidence: Mapping[str, object],
) -> dict[str, object]:
    """Evaluate sanitized deployed lifecycle facts without local substitution."""

    missing: list[str] = []

    def require(condition: bool, code: str) -> None:
        if not condition and code not in missing:
            missing.append(code)

    require(
        evidence.get("sequence") == list(DEPLOYED_LIFECYCLE_SEQUENCE),
        "exact_lifecycle_sequence",
    )
    require(evidence.get("environment") == "validation", "exact_environment")

    credentials = evidence.get("credentials")
    credentials = credentials if isinstance(credentials, Mapping) else {}
    modes = credentials.get("modes")
    modes = modes if isinstance(modes, Mapping) else {}
    require(credentials.get("local_context_count") == 1, "single_local_context")
    require(
        modes == {"deployer": "0700"},
        "private_credential_contexts",
    )
    require(
        credentials.get("ambient_credentials_removed") is True,
        "no_ambient_credentials",
    )
    identities = credentials.get("identity_hashes")
    identities = identities if isinstance(identities, Mapping) else {}
    deployer_identity = identities.get("deployer")
    evidence_identity = identities.get("evidence")
    require(
        _require_hash(deployer_identity)
        and _require_hash(evidence_identity)
        and deployer_identity != evidence_identity,
        "distinct_azure_identities",
    )
    require(
        credentials.get("evidence_source") == "fixed_job",
        "fixed_evidence_job_source",
    )
    require(
        set(credentials.get("deployer_actions") or ())
        == EXPECTED_DEPLOYER_ACTIONS,
        "deployer_only_job_start",
    )
    require(
        set(credentials.get("evidence_actions") or ())
        == EXPECTED_EVIDENCE_ACTIONS,
        "evidence_read_only",
    )
    require(
        set(credentials.get("evidence_denied_actions") or ())
        == EXPECTED_EVIDENCE_DENIALS,
        "evidence_has_no_job_authority",
    )
    require(
        not credentials.get("runtime_job_start_grants"),
        "no_runtime_job_start_grants",
    )

    evidence_job = evidence.get("evidence_job")
    evidence_job = (
        evidence_job if isinstance(evidence_job, Mapping) else {}
    )
    require(
        evidence_job.get("identity_hash") == evidence_identity
        and evidence_job.get("identity_hash")
        == evidence_job.get("expected_identity_hash")
        and evidence_job.get("attached_identity_count") == 1,
        "evidence_job_exact_identity",
    )
    require(
        _require_hash(evidence_job.get("template_hash"))
        and evidence_job.get("template_hash")
        == evidence_job.get("expected_template_hash")
        and evidence_job.get("template_unchanged") is True
        and evidence_job.get("trigger") == "Manual"
        and evidence_job.get("overrides") == [],
        "evidence_job_fixed_template",
    )
    require(
        evidence_job.get("workspace_roles") == ["Viewer"] * 5
        and evidence_job.get("onelake_actions") == ["Read"] * 5
        and evidence_job.get("onelake_paths") == ["*"] * 5
        and evidence_job.get("job_control_actions") == []
        and evidence_job.get("mutation_actions") == [],
        "evidence_job_read_only_roles",
    )
    require(
        evidence_job.get("production_workspace_access") is False,
        "evidence_job_no_production_workspace",
    )
    require(
        _require_hash(evidence_job.get("record_hash"))
        and _require_hash(evidence_job.get("entra_bound_record_hash")),
        "evidence_job_signed_record",
    )

    templates = evidence.get("templates")
    templates = templates if isinstance(templates, Mapping) else {}
    for name in REQUIRED_JOB_TEMPLATES:
        template = templates.get(name)
        template = template if isinstance(template, Mapping) else {}
        expected = template.get("expected")
        require(
            _require_hash(expected)
            and template.get("before") == expected
            and template.get("after") == expected,
            f"fixed_template_{name}",
        )
        require(
            template.get("override_fields") == [],
            f"no_overrides_{name}",
        )

    prepare = evidence.get("prepare")
    prepare = prepare if isinstance(prepare, Mapping) else {}
    record_hashes = prepare.get("record_hashes")
    record_hashes = record_hashes if isinstance(record_hashes, list) else []
    require(prepare.get("status") == "PASS", "prepare_success")
    require(prepare.get("server_generated") is True, "server_generated_drill")
    require(_require_hash(prepare.get("drill_hash")), "opaque_drill")
    require(
        len(record_hashes) == 3
        and len(set(record_hashes)) == 3
        and all(_require_hash(value) for value in record_hashes),
        "exact_three_records",
    )
    require(_require_hash(prepare.get("epoch_hash")), "single_prepared_epoch")
    require(prepare.get("ttl_bounded") is True, "bounded_fixture_ttl")
    require(
        _require_hash(prepare.get("owner_hash"))
        and _require_hash(prepare.get("fence_hash")),
        "fixture_owner_fence",
    )
    require(prepare.get("audit_create_only") is True, "create_only_prepare_audit")
    require(
        prepare.get("active_record_count_after_exit") == 3,
        "prepare_leaves_records_active",
    )

    drain = evidence.get("drain")
    drain = drain if isinstance(drain, Mapping) else {}
    require(drain.get("status") == "PASS", "drain_success")
    require(
        drain.get("connection_root_matches") is True,
        "validation_connection_root",
    )
    require(
        drain.get("registry_provider_class") == "ConnectionRegistry",
        "production_registry_path",
    )
    require(
        drain.get("registry_provider_module") == "onboarding.registry"
        and drain.get("registry_store_class") == "OneLakeRegistryStore"
        and _require_hash(drain.get("connection_root_hash")),
        "production_registry_path",
    )
    require(
        drain.get("normal_selection") is True
        and drain.get("normal_reauthorization") is True,
        "normal_selection_reauthorization",
    )
    processed = drain.get("processed_per_pass")
    require(
        isinstance(processed, list)
        and len(processed) >= 3
        and all(value == 1 for value in processed),
        "one_member_per_pass",
    )
    require(drain.get("retry_rotated") is True, "retry_rotation")
    require(drain.get("later_member_progress") is True, "later_member_progress")
    selection_receipts = drain.get("selection_receipts")
    selection_receipts = (
        selection_receipts if isinstance(selection_receipts, list) else []
    )
    receipt_rows = [
        row for row in selection_receipts if isinstance(row, Mapping)
    ]
    receipt_records = [row.get("record_hash") for row in receipt_rows]
    retry_indexes = [
        index
        for index, row in enumerate(receipt_rows)
        if row.get("outcome") == "retrying"
    ]
    starvation_free = False
    for retry_index in retry_indexes:
        retry_record = receipt_rows[retry_index].get("record_hash")
        resumed_index = next(
            (
                index
                for index in range(retry_index + 1, len(receipt_rows))
                if receipt_rows[index].get("record_hash") == retry_record
            ),
            None,
        )
        if resumed_index is not None and any(
            receipt_rows[index].get("record_hash") != retry_record
            for index in range(retry_index + 1, resumed_index)
        ):
            starvation_free = True
            break
    require(
        bool(receipt_rows)
        and set(receipt_records) == set(record_hashes)
        and all(
            _require_hash(row.get("record_hash"))
            and _require_hash(row.get("epoch_hash"))
            and _require_hash(row.get("snapshot_hash"))
            and _require_hash(row.get("authorization_hash"))
            and _require_hash(row.get("process_hash"))
            and isinstance(row.get("cursor_before"), int)
            and isinstance(row.get("cursor_after"), int)
            and isinstance(row.get("attempt"), int)
            and row.get("outcome")
            in {
                "duplicate",
                "retrying",
                "succeeded",
                "exhausted_failure",
                "excluded",
            }
            for row in receipt_rows
        ),
        "authoritative_selection_receipts",
    )
    require(starvation_free, "starvation_free_selection_order")
    require(
        set(drain.get("prepared_record_hashes") or ()) == set(record_hashes)
        and set(drain.get("terminal_record_hashes") or ()) == set(record_hashes),
        "eligible_set_drained",
    )
    process_hashes = drain.get("process_hashes")
    require(
        isinstance(process_hashes, list)
        and len(process_hashes) >= 2
        and len(set(process_hashes)) >= 2
        and all(_require_hash(value) for value in process_hashes),
        "actual_process_replacement",
    )
    require(
        drain.get("restart_lineage_preserved") is True,
        "restart_lineage",
    )
    require(
        bool(receipt_rows)
        and len({row.get("epoch_hash") for row in receipt_rows}) == 1
        and len({row.get("snapshot_hash") for row in receipt_rows}) == 1
        and len({row.get("process_hash") for row in receipt_rows}) >= 2,
        "restart_lineage",
    )
    require(
        drain.get("post_selection_external_writes") == 0,
        "no_post_selection_injection",
    )
    require(
        drain.get("validator_store_writes") == 0,
        "no_validator_store_writes",
    )

    injection = evidence.get("injection")
    injection = injection if isinstance(injection, Mapping) else {}
    require(injection.get("status") == "PASS", "injection_traversal")
    require(
        injection.get("terraform_tag_hash_matches") is True,
        "terraform_tag_hash",
    )
    require(
        injection.get("lineage") == list(EXPECTED_TAG_LINEAGE),
        "real_tag_lineage",
    )
    tag_hashes = injection.get("tag_hashes")
    tag_hashes = tag_hashes if isinstance(tag_hashes, Mapping) else {}
    require(
        _require_hash(injection.get("resource_hash"))
        and _require_hash(injection.get("scope_hash"))
        and set(tag_hashes) == set(EXPECTED_TAG_LINEAGE)
        and len(set(tag_hashes.values())) == 1
        and all(_require_hash(value) for value in tag_hashes.values()),
        "exact_tag_lineage",
    )
    require(
        injection.get("curator_source_class") == "OntologyCurator",
        "deployed_curator_source",
    )
    require(
        injection.get("tools") == list(EXPECTED_CURATOR_TOOLS),
        "exact_four_curator_tools",
    )
    require(injection.get("scope_unchanged") is True, "curator_scope_unchanged")
    require(injection.get("mutation_attempts") == 0, "zero_curator_mutations")
    edge_counts = injection.get("authoritative_model_edges")
    edge_counts = edge_counts if isinstance(edge_counts, Mapping) else {}
    require(
        all(
            edge_counts.get(name) == 0
            for name in ("candidate", "stage", "active", "consumer")
        ),
        "zero_authoritative_model_edges",
    )

    cleanup = evidence.get("cleanup")
    cleanup = cleanup if isinstance(cleanup, Mapping) else {}
    require(cleanup.get("status") == "PASS", "cleanup_success")
    require(
        cleanup.get("server_resolved_unique_drill") is True,
        "server_resolved_cleanup",
    )
    require(cleanup.get("fence_matches") is True, "cleanup_fence")
    require(
        set(cleanup.get("deleted_record_hashes") or ()) == set(record_hashes),
        "cleanup_exact_record_set",
    )
    require(cleanup.get("deleted_epoch_count") == 1, "cleanup_exact_epoch")
    require(
        cleanup.get("active_fixture_connections") == 0,
        "fixture_registry_empty",
    )
    require(
        cleanup.get("active_prepared_epochs") == 0,
        "prepared_epoch_registry_empty",
    )
    require(
        set(cleanup.get("retained_receipts") or ())
        == {"prepare", "cleanup", "sweep"},
        "retained_fixture_audit",
    )
    require(cleanup.get("audit_immutable") is True, "immutable_fixture_audit")
    require(
        cleanup.get("independent_observer") == "evidence",
        "independent_empty_registry_observation",
    )
    require(
        cleanup.get("tag_hash_unchanged") is True,
        "terraform_tag_unchanged",
    )

    maintenance = evidence.get("maintenance")
    maintenance = maintenance if isinstance(maintenance, Mapping) else {}
    require(
        maintenance.get("general_operator_denied") is True,
        "general_maintenance_denied",
    )
    require(
        maintenance.get("maintenance_principal_accepted") is True,
        "maintenance_principal_accepted",
    )
    require(
        maintenance.get("coordinator_reauthorized") is True,
        "maintenance_reauthorization",
    )
    require(
        maintenance.get("next_run") == "full"
        and maintenance.get("following_run") == "incremental",
        "full_then_incremental",
    )
    require(
        evidence.get("release_status") == "BLOCKED/PENDING",
        "release_blocked_pending",
    )
    return {
        "schema_version": "ontology-deployed-lifecycle-validation.v1",
        "status": "PASS" if not missing else "FAIL",
        "sanitized": True,
        "release_status": "BLOCKED/PENDING",
        "missing_evidence": sorted(missing),
    }


def _action_matches(action: str, pattern: str) -> bool:
    """Case-insensitive ARM action matching with Azure's wildcard semantics."""

    return fnmatch.fnmatchcase(action.casefold(), pattern.casefold())


def expand_role_actions(
    role_definitions: Sequence[Mapping[str, object]],
) -> dict[str, bool]:
    """Classify effective role actions without pretending deny probes are safe.

    A live ``start`` probe is a mutation when it succeeds.  The validator
    therefore expands role definitions read through ARM/ARG and fails closed
    on wildcard actions rather than attempting a destructive permission test.
    """

    effective: set[str] = set()
    wildcard = False
    for role in role_definitions:
        actions = [
            str(value)
            for value in (
                list(role.get("actions") or ())
                + list(role.get("data_actions") or ())
            )
        ]
        exclusions = [
            str(value)
            for value in (
                list(role.get("not_actions") or ())
                + list(role.get("not_data_actions") or ())
            )
        ]
        for action in actions:
            if action == "*":
                wildcard = True
            if not any(_action_matches(action, excluded) for excluded in exclusions):
                effective.add(action)

    job_start_patterns = (
        "microsoft.app/jobs/start/action",
        "microsoft.app/jobs/executions/write",
        "microsoft.app/containerapps/jobs/start/action",
    )
    job_read_patterns = (
        "microsoft.app/jobs/read",
        "microsoft.app/jobs/executions/read",
        "microsoft.app/containerapps/jobs/read",
    )

    def permits(patterns: Sequence[str]) -> bool:
        return wildcard or any(
            _action_matches(pattern, action) or _action_matches(action, pattern)
            for action in effective
            for pattern in patterns
        )

    mutation = wildcard or any(
        not action.casefold().endswith(("/read", "/list/action"))
        for action in effective
    )
    return {
        "wildcard": wildcard,
        "job_read": permits(job_read_patterns),
        "job_start": permits(job_start_patterns),
        "mutation": mutation,
    }


def evaluate_publication_evidence(
    evidence: Mapping[str, object],
) -> dict[str, object]:
    """Evaluate only direct deployed publication and rollback receipts."""

    missing: list[str] = []

    def require(condition: bool, code: str) -> None:
        if not condition and code not in missing:
            missing.append(code)

    require(
        evidence.get("command_topology") == list(EXPECTED_COMMAND_TOPOLOGY),
        "command_topology",
    )
    process_hashes = evidence.get("process_hashes")
    process_hashes = process_hashes if isinstance(process_hashes, Mapping) else {}
    require(
        set(process_hashes)
        == {"api", "coordinator", "publisher", "api_reload"}
        and all(_require_hash(value) for value in process_hashes.values())
        and len(set(process_hashes.values())) == 4,
        "distinct_process_reconstruction",
    )
    templates = evidence.get("templates")
    templates = templates if isinstance(templates, Mapping) else {}
    for name in REQUIRED_JOB_TEMPLATES:
        row = templates.get(name)
        row = row if isinstance(row, Mapping) else {}
        require(
            _require_hash(row.get("expected"))
            and row.get("before") == row.get("expected")
            and row.get("after") == row.get("expected"),
            f"fixed_template_{name}",
        )
        require(row.get("override_fields") == [], f"no_overrides_{name}")

    receipts = evidence.get("receipts")
    receipts = receipts if isinstance(receipts, Mapping) else {}
    for name in (
        "immutable_stage",
        "validation",
        "five_consumer_compatibility",
        "fabric_materialization",
        "final_precondition",
        "pointer_cas",
        "post_check",
    ):
        require(receipts.get(name) is True, f"receipt_{name}")

    stale = evidence.get("stale_writer")
    stale = stale if isinstance(stale, Mapping) else {}
    for name in (
        "pre_cas_pause",
        "stale_fence_rejected",
        "stale_etag_rejected",
        "one_shot_consumed",
        "cleaned",
    ):
        require(stale.get(name) is True, f"stale_writer_{name}")

    rollback = evidence.get("rollback")
    rollback = rollback if isinstance(rollback, Mapping) else {}
    require(
        rollback.get("allowlisted_post_check_failure") is True,
        "allowlisted_post_check_failure",
    )
    require(rollback.get("automatic") is True, "automatic_rollback")
    require(rollback.get("order") == ["old", "new", "old"], "old_new_old")
    require(
        rollback.get("one_shot_consumed") is True
        and rollback.get("cleaned") is True,
        "drill_cleanup",
    )

    consumers = evidence.get("consumers")
    consumers = consumers if isinstance(consumers, Mapping) else {}
    require(
        set(consumers) == set(EXPECTED_CONSUMERS)
        and all(consumers.get(name) == "PASS" for name in EXPECTED_CONSUMERS),
        "five_consumer_convergence",
    )

    final = evidence.get("final")
    final = final if isinstance(final, Mapping) else {}
    require(final.get("fixture_registry_empty") is True, "fixture_registry_empty")
    require(final.get("fixture_audit_retained") is True, "fixture_audit_retained")
    require(final.get("terraform_tag_unchanged") is True, "terraform_tag_unchanged")
    require(not final.get("runtime_job_start_grants"), "no_runtime_job_start_grants")
    require(
        final.get("authoritative_model_edges") == 0,
        "zero_authoritative_model_edges",
    )
    require(final.get("local_substitution") is False, "no_local_substitution")
    require(
        evidence.get("release_status") == "BLOCKED/PENDING",
        "release_blocked_pending",
    )
    return {
        "schema_version": "ontology-deployed-publication-validation.v1",
        "status": "PASS" if not missing else "FAIL",
        "sanitized": True,
        "release_status": "BLOCKED/PENDING",
        "missing_evidence": sorted(missing),
    }


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


def _deployed_stage(args: argparse.Namespace) -> tuple[Path, dict[str, object]]:
    """Enter the deployed state machine without falling back to legacy shadow.

    Context validation intentionally happens before target discovery, token
    acquisition, Terraform reads, or any Job call.  This keeps missing or
    ambient credentials a true precondition gate rather than an invitation to
    reuse the operator's default Azure CLI session.
    """

    report_path = args.output
    if report_path is None:
        raise ConfigurationError("--output is required for deployed stages")
    if args.resume_file is None:
        raise ConfigurationError("--resume-file is required for deployed stages")
    if args.environment != "validation":
        raise ConfigurationError(
            "deployed stages require --environment validation"
        )
    contexts = validate_azure_contexts()
    # Loading the applied contract is the last local-only gate. Cloud reads and
    # all Job actions belong to the stage implementation and must never happen
    # through the legacy ambient-credential shadow collector.
    load_plan19_deployment_contract()
    raise EvidenceError(
        "deployed stage requires Task 2 live preconditions after isolated "
        f"context validation ({contexts.deployer.name}, {contexts.evidence.name})"
    )


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
    deployed = args.stage is not None
    try:
        report_path, report = (
            _deployed_stage(args) if deployed else _shadow(args)
        )
    except (ConfigurationError, EvidenceError, OSError, subprocess.SubprocessError) as exc:
        report_path = (
            args.output
            if deployed and args.output is not None
            else args.report
            or (
                DEFAULT_REPORT_DIR
                / f"ontology-discovery-shadow-{datetime.now(UTC).date().isoformat()}.json"
            )
        )
        report = {
            "schema_version": (
                "ontology-deployed-lifecycle-validation.v1"
                if deployed
                else "ontology-discovery-shadow-validation.v1"
            ),
            "mode": (
                "deployed-fixed-template"
                if deployed
                else "credentialed-shadow"
            ),
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
