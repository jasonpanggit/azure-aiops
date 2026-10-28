#!/usr/bin/env python3
"""Preview or execute SPN platform setup. No commands run without --apply."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import yaml

ROOT = Path(__file__).resolve().parents[2]
MANUAL_STEPS = """Manual gates (see SETUP.md):
  Before provisioning: grant Azure RBAC; configure Entra SPA/API v2 tokens,
  scopes and user app roles; enable scoped Fabric SPN/workspace tenant settings;
  approve capacity/model quota, networking and preview features.
  After provisioning: add the deployed web URL as an Entra SPA redirect URI;
  add new managed identities to the approved Fabric security group.
  Optional BI surface: bootstrap/rebind the Direct Lake model after ingestion.
  Data/ontology sync is opt-in. Native agent activation and live RBAC acceptance
  remain separate approved operations, not consequences of running setup."""


class SetupError(RuntimeError):
    """A setup prerequisite or subprocess failed."""


def read_env(path: Path) -> dict[str, str]:
    """Read literal KEY=value settings without executing shell expressions."""
    result: dict[str, str] = {}
    for number, line in enumerate(path.read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, separator, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise SetupError(f"Invalid environment setting at {path}:{number}")
        if value.startswith(("'", '"')):
            if len(value) < 2 or value[-1] != value[0]:
                raise SetupError(f"Unterminated environment value at {path}:{number}")
            value = value[1:-1]
        result[key] = value
    return result


def private_write(path: Path, content: str) -> None:
    """Atomically write private configuration/evidence without following symlinks."""
    if path.is_symlink():
        raise SetupError(f"Refusing to overwrite symlink: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}-")
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def identifier(value: object, label: str) -> str:
    """Validate non-placeholder immutable IDs before writing target bindings."""
    if not isinstance(value, str):
        raise SetupError(f"{label} must be a UUID")
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise SetupError(f"{label} must be a UUID") from exc
    if parsed.int == 0:
        raise SetupError(f"{label} must not be a placeholder")
    return str(parsed)


def configure_fabric(
    path: Path, outputs: dict, environment: dict[str, str], source_root: Path | None
) -> str:
    """Create or merge a config bound to this deployment, never another tenant."""
    try:
        raw = (
            yaml.safe_load(path.read_text())
            if path.exists()
            else yaml.safe_load(
                (ROOT / "fabric.service-principal.example.yaml").read_text()
            )
        )
    except yaml.YAMLError as exc:
        raise SetupError(f"Invalid YAML in {path}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("fabric"), dict):
        raise SetupError(f"{path} must contain a fabric mapping")
    config = raw["fabric"]
    auth = config.setdefault("auth", {})
    if not isinstance(auth, dict) or auth.get("mode") != "service_principal":
        raise SetupError(
            "Use a separate SPN Fabric config; existing non-SPN auth is preserved"
        )
    bindings = (
        (config, "workspace_id", outputs.get("fabric_workspace_id")),
        (config, "lakehouse_id", outputs.get("fabric_lakehouse_id")),
        (auth, "tenant_id", environment["AZURE_TENANT_ID"]),
        (auth, "client_id", environment["AZURE_CLIENT_ID"]),
    )
    for mapping, key, value in bindings:
        target = identifier(value, key)
        current = mapping.get(key)
        if (
            current
            and current != str(UUID(int=0))
            and identifier(current, key) != target
        ):
            raise SetupError(
                f"{path}: {key} belongs to a different deployment; use a new config"
            )
        mapping[key] = target
    secret_env = auth.setdefault("client_secret_env", "AZURE_CLIENT_SECRET")
    if (
        not isinstance(secret_env, str)
        or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", secret_env)
        or secret_env not in {"AZURE_CLIENT_SECRET", "FABRIC_CLIENT_SECRET"}
    ):
        raise SetupError(
            "SPN setup supports AZURE_CLIENT_SECRET or FABRIC_CLIENT_SECRET only"
        )
    if "client_secret" in auth:
        raise SetupError("Remove inline client_secret; use client_secret_env")
    environment[secret_env] = environment["AZURE_CLIENT_SECRET"]
    ontology = config.setdefault("ontology", {})
    if not isinstance(ontology, dict):
        raise SetupError("fabric.ontology must be a mapping")
    if not path.exists():
        # Current main keeps native item publication off until separately approved.
        ontology["enabled"] = False
    deployed_name = outputs.get("fabric_ontology_name")
    if deployed_name:
        if (
            ontology.get("ontology_id")
            and ontology.get("ontology_name") != deployed_name
        ):
            raise SetupError(
                "Pinned ontology has a different name; review the target manually"
            )
        ontology["ontology_name"] = deployed_name
    if source_root is not None:
        config["source_data_root"] = str(source_root)
    private_write(path, yaml.safe_dump(raw, sort_keys=False))
    return secret_env


def validate_evidence_api_grants(outputs: dict, subscription_id: str) -> None:
    """Reject missing or widened collector API grants before Fabric setup writes."""
    contract = outputs.get("ontology_evidence_role_contract")
    if contract is None:
        return
    if not isinstance(contract, dict):
        raise SetupError("Ontology evidence role contract must be a mapping")
    principal = identifier(contract.get("principal_object_id"), "evidence principal")
    subscription = identifier(subscription_id, "evidence subscription")
    expected = {
        principal: [{"role": "reader", "scope": {"subscription": [subscription]}}]
    }
    if outputs.get("ontology_evidence_api_gateway_grants") != expected:
        raise SetupError(
            "Collector API grants must be exactly reader on the deployment subscription; "
            "refresh Terraform outputs before Fabric setup"
        )


class Setup:
    """Run existing deployment tools under one isolated SPN Azure CLI context."""

    def __init__(self, environment: dict[str, str]) -> None:
        self.environment = environment

    def run(self, command: list[str], label: str, *, capture: bool = False) -> str:
        """Execute an argv list, failing with a redacted diagnostic."""
        print(f"setup: {label}", flush=True)
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=self.environment,
            text=True,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE,
            check=False,
        )
        diagnostic = completed.stderr
        for key, value in self.environment.items():
            if value and any(
                part in key for part in ("SECRET", "TOKEN", "PASSWORD", "API_KEY")
            ):
                diagnostic = diagnostic.replace(value, "[REDACTED]")
        if diagnostic:
            print(diagnostic, file=sys.stderr, end="")
        if completed.returncode:
            raise SetupError(
                f"{label} failed (exit {completed.returncode}); no later steps ran"
            )
        return completed.stdout or ""

    def outputs(self) -> dict:
        """Read Terraform values without printing sensitive contract outputs."""
        raw = json.loads(
            self.run(
                ["terraform", "-chdir=infra/terraform", "output", "-json"],
                "read deployment outputs",
                capture=True,
            )
        )
        return {key: item["value"] for key, item in raw.items()}

    def fabric(self, args: argparse.Namespace, outputs: dict, cli_dir: Path) -> None:
        """Configure Fabric and publish only the requested supported artifacts."""
        workspace = outputs.get("fabric_workspace_id")
        lakehouse = outputs.get("fabric_lakehouse_id")
        if workspace is None and lakehouse is None:
            if args.stage == "fabric" or args.sync_inventory or args.publish_data_agent:
                raise SetupError(
                    "Fabric is disabled; enable_fabric=true and provision first"
                )
            print(
                "setup: Fabric disabled; skipping configuration and catalog publication"
            )
            return
        validate_evidence_api_grants(
            outputs, self.environment["AZURE_SUBSCRIPTION_ID"]
        )
        configure_fabric(
            args.fabric_config, outputs, self.environment, args.source_data_root
        )
        self.environment["AIOPS_FABRIC_CONFIG"] = str(args.fabric_config)
        python = [sys.executable]
        self.run(
            python
            + [
                "-m",
                "onboarding.cli",
                "fabric",
                "Publish governed remediation catalog",
                "--config",
                str(args.fabric_config),
            ],
            "publish governed remediation catalog",
        )
        contract = outputs.get("ontology_evidence_role_contract")
        if contract is not None:
            with tempfile.TemporaryDirectory(
                prefix="aiops-role-contract-"
            ) as directory:
                contract_file = Path(directory) / "contract.json"
                private_write(contract_file, json.dumps(contract))
                base = python + [
                    str(ROOT / "scripts/reconcile_onelake_data_access_roles.py"),
                    "--contract-file",
                    str(contract_file),
                    "--azure-config-dir",
                    str(cli_dir),
                ]
                self.run(
                    base + ["--output", str(args.artifact_dir / "roles-preview.json")],
                    "preview OneLake evidence roles",
                )
                self.run(
                    base
                    + [
                        "--output",
                        str(args.artifact_dir / "roles-applied.json"),
                        "--apply",
                    ],
                    "reconcile and verify OneLake evidence roles",
                )
        else:
            print(
                "setup: no validation evidence-role contract; no evidence-role writes requested"
            )
        if args.sync_inventory:
            self.run(
                python
                + [
                    "-m",
                    "onboarding.cli",
                    "fabric",
                    "Sync operational ontology",
                    "--config",
                    str(args.fabric_config),
                ],
                "sync approved source inventory and ontology",
            )
            self.run(
                python
                + [
                    "-m",
                    "onboarding.cli",
                    "fabric",
                    "Show ontology health",
                    "--config",
                    str(args.fabric_config),
                ],
                "read ontology health",
            )
        if args.publish_data_agent:
            self.run(
                python
                + [
                    str(ROOT / "scripts/deploy-relationship-suggestion-agent.py"),
                    "--fabric-config",
                    str(args.fabric_config),
                    "--publish",
                ],
                "create and publish advisory Data Agent (not query acceptance)",
            )


def parser() -> argparse.ArgumentParser:
    """Build the setup CLI; preview is deliberately offline and read-only."""
    result = argparse.ArgumentParser(
        description=__doc__,
        epilog=MANUAL_STEPS,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    result.add_argument(
        "--apply",
        action="store_true",
        help="Execute writes; otherwise only print the sequence",
    )
    result.add_argument(
        "--stage", choices=("all", "infrastructure", "fabric", "release"), default="all"
    )
    result.add_argument("--env-file", type=Path, default=ROOT / "web/.env.local")
    result.add_argument(
        "--fabric-config", type=Path, default=ROOT / "fabric.config.yaml"
    )
    result.add_argument("--artifact-dir", type=Path, default=ROOT / ".azure/setup")
    result.add_argument("--image-tag", default="")
    result.add_argument(
        "--sync-inventory",
        action="store_true",
        help="Explicitly sync real data and ontology",
    )
    result.add_argument(
        "--source-data-root",
        type=Path,
        help="Approved normalized generation, required for --sync-inventory",
    )
    result.add_argument(
        "--publish-data-agent",
        action="store_true",
        help="Opt into advisory preview Data Agent provisioning",
    )
    return result


def main(argv: list[str] | None = None) -> int:
    """Preview setup or execute selected stages without using ambient Azure login."""
    args = parser().parse_args(argv)
    if (args.sync_inventory or args.publish_data_agent) and args.stage not in {
        "all",
        "fabric",
    }:
        raise SetupError("Inventory/Data Agent options require --stage all or fabric")
    if args.sync_inventory and (
        args.source_data_root is None or not args.source_data_root.is_dir()
    ):
        raise SetupError("--sync-inventory requires an existing --source-data-root")
    if args.image_tag and not re.fullmatch(
        r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}", args.image_tag
    ):
        raise SetupError("--image-tag is not a valid container tag")
    print(MANUAL_STEPS)
    if not args.apply:
        print(
            f"\nPREVIEW ONLY: stage={args.stage}; no login, file writes or cloud calls."
        )
        if args.stage in {"all", "infrastructure"}:
            print(
                "  Terraform init/validate/plan/apply (catalog deferred until Fabric config exists)"
            )
        if args.stage in {"all", "fabric"}:
            print(
                "  Bind SPN Fabric config from outputs; publish catalog; reconcile validation roles if present"
            )
            if args.sync_inventory:
                print(
                    "  Sync approved source inventory/ontology and read ontology health"
                )
            if args.publish_data_agent:
                print("  Create/publish advisory Data Agent with --publish")
        if args.stage in {"all", "release"}:
            print(
                "  Build/verify all four images; apply deploy_images=true and the built tag"
            )
        return 0
    for name in ("az", "terraform"):
        if not shutil.which(name):
            raise SetupError(f"{name} is required")
    settings = read_env(args.env_file)
    required = [
        "AZURE_SUBSCRIPTION_ID",
        "AZURE_TENANT_ID",
        "AZURE_CLIENT_ID",
        "AZURE_CLIENT_SECRET",
    ]
    if args.stage != "fabric":
        required += [
            "NEXT_PUBLIC_ENTRA_CLIENT_ID",
            "NEXT_PUBLIC_ENTRA_TENANT_ID",
            "NEXT_PUBLIC_ENTRA_API_SCOPE",
            "AIOPS_ENTRA_API_AUDIENCE",
            "AIOPS_ENTRA_GRANTS_JSON",
        ]
    for key in required:
        if not settings.get(key):
            raise SetupError(f"{key} is required in {args.env_file}")
    for key in ("AZURE_SUBSCRIPTION_ID", "AZURE_TENANT_ID", "AZURE_CLIENT_ID"):
        identifier(settings[key], key)
    environment = {**os.environ, **settings}
    environment["AIOPS_ENV_FILE"] = str(args.env_file.resolve())
    environment["AIOPS_PYTHON"] = sys.executable
    environment["AIOPS_FABRIC_CONFIG"] = str(args.fabric_config.resolve())
    environment["PYTHONPATH"] = str(ROOT / "src")
    for key in (
        "AZURE_FEDERATED_TOKEN_FILE",
        "AIOPS_DEFER_CATALOG_PUBLICATION",
        "AIOPS_SKIP_FABRIC_PUBLISH",
    ):
        environment.pop(key, None)
    environment["AIOPS_API_AUTHORIZATION_RELEASE"] = "0"
    args.fabric_config = args.fabric_config.absolute()
    args.artifact_dir = args.artifact_dir.absolute()
    if args.source_data_root is not None:
        args.source_data_root = args.source_data_root.resolve()
    if args.artifact_dir.is_symlink():
        raise SetupError("Artifact directory must not be a symlink")
    args.artifact_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    args.artifact_dir.chmod(0o700)
    runner = Setup(environment)
    with tempfile.TemporaryDirectory(prefix="aiops-setup-az-") as directory:
        cli_dir = Path(directory)
        environment["AZURE_CONFIG_DIR"] = str(cli_dir)
        runner.run(
            [
                "az",
                "login",
                "--service-principal",
                "--username",
                settings["AZURE_CLIENT_ID"],
                "--password",
                settings["AZURE_CLIENT_SECRET"],
                "--tenant",
                settings["AZURE_TENANT_ID"],
                "--output",
                "none",
            ],
            "authenticate deployer SPN in isolated CLI context",
            capture=True,
        )
        runner.run(
            [
                "az",
                "account",
                "set",
                "--subscription",
                settings["AZURE_SUBSCRIPTION_ID"],
            ],
            "select platform subscription",
        )
        deploy = ["bash", str(ROOT / "infra/scripts/deploy.sh")]
        if args.stage in {"all", "infrastructure"}:
            runner.run(deploy + ["init"], "initialize Terraform")
            runner.run(deploy + ["validate"], "validate Terraform")
            with tempfile.TemporaryDirectory(prefix="aiops-setup-plan-") as plan_dir:
                plan_file = str(Path(plan_dir) / "infrastructure.tfplan")
                runner.run(
                    deploy + ["plan", f"-out={plan_file}"],
                    "plan infrastructure",
                )
                plan = json.loads(
                    runner.run(
                        [
                            "terraform",
                            "-chdir=infra/terraform",
                            "show",
                            "-json",
                            plan_file,
                        ],
                        "inspect semantic model bootstrap gate",
                        capture=True,
                    )
                )
                for change in plan.get("resource_changes", []):
                    if (
                        change.get("type") == "fabric_semantic_model"
                        and change.get("name") == "aiops"
                        and "create" in change["change"]["actions"]
                    ):
                        raise SetupError(
                            "The adopted semantic model cannot bootstrap a new target. "
                            "Remove the pilot-bound creation from the reviewed plan "
                            "and complete SETUP.md's manual model bootstrap."
                        )
                environment["AIOPS_DEFER_CATALOG_PUBLICATION"] = "true"
                try:
                    runner.run(
                        deploy + ["apply", "-auto-approve", plan_file],
                        "provision infrastructure",
                    )
                finally:
                    environment.pop("AIOPS_DEFER_CATALOG_PUBLICATION", None)
        outputs = runner.outputs()
        if args.stage != "release":
            runner.fabric(args, outputs, cli_dir)
        if args.stage in {"all", "release"}:
            if (
                outputs.get("fabric_workspace_id") is not None
                and not args.fabric_config.exists()
            ):
                raise SetupError(
                    "Run --stage fabric before release to create the SPN Fabric config"
                )
            if args.stage == "release" and (
                outputs.get("fabric_workspace_id") is not None
                or outputs.get("fabric_lakehouse_id") is not None
            ):
                configure_fabric(
                    args.fabric_config, outputs, environment, source_root=None
                )
            tag = (
                args.image_tag or f"setup-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"
            )
            runner.run(
                ["bash", str(ROOT / "infra/scripts/build-and-push.sh"), tag],
                "build and verify four platform images",
            )
            runner.run(
                deploy
                + [
                    "apply",
                    "-auto-approve",
                    "-var=deploy_images=true",
                    f"-var=image_tag={tag}",
                ],
                "roll out verified images",
            )
        for key in ("web_url", "api_url"):
            if outputs.get(key):
                print(f"setup: {key}={outputs[key]}")
    print(
        "setup: selected automation completed. Manual gates above still require operator acceptance."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (SetupError, OSError, ValueError) as error:
        print(f"setup: {error}", file=sys.stderr)
        raise SystemExit(1)
