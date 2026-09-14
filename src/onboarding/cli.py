from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC
from pathlib import Path

from onboarding.graph_normalize import Normalizer
from onboarding.ingestion_storage import DatasetStore

from .agent_queries import ContextQueryService
from .config import ConnectorConfig
from .ingestion_service import IngestionService
from .schedule import install_schedule


def register_cli(parser: argparse.ArgumentParser) -> None:
    actions = parser.add_subparsers(dest="azure_graph_action")

    sync = actions.add_parser("sync", help="Run Azure MCP discovery and ARG ingestion now")
    sync.add_argument("--config", default="config.yaml")

    refresh_parser = actions.add_parser(
        "inventory-refresh",
        help="Run the standalone resource catalog refresh",
    )
    refresh_parser.add_argument("--config", default="config.yaml")
    refresh_parser.add_argument(
        "--fabric-config",
        default="",
        help="Optional Fabric config used to publish inventory tables to OneLake",
    )
    refresh_parser.add_argument(
        "--connection-id",
        default="",
        help="Connection whose server-owned Log Analytics workspace mappings should be queried",
    )

    query = actions.add_parser("query", help="Query the normalized operational context")
    query.add_argument("question")
    query.add_argument("--output-dir", default="./data")

    schedule = actions.add_parser("schedule", help="Create a AIOps cron job for continuous ingestion")
    schedule.add_argument("--config", default="config.yaml")
    schedule.add_argument("--schedule", default="every 30m")

    sample = actions.add_parser("sample", help="Build datasets from a mock ARG response file")
    sample.add_argument("--fixture", default="tests/fixtures/mock_arg_responses.json")
    sample.add_argument("--output-dir", default="./sample-data")

    local = actions.add_parser("local", help="Seed offline local API data from a fixture")
    local.add_argument("--fixture", default="tests/fixtures/mock_arg_responses.json")
    local.add_argument("--home", default=".aiops-local")
    local.add_argument("--connection-id", default="local-demo")

    local_spn = actions.add_parser(
        "local-spn", help="Register a local SPN connection from AZURE_* env vars"
    )
    local_spn.add_argument("--home", default=".aiops-local")
    local_spn.add_argument("--connection-id", default="local-spn")
    local_spn.add_argument("--name", default="Local SPN Subscription")
    local_spn.add_argument("--sync", action="store_true", help="Run discovery after injecting the connection")

    fabric = actions.add_parser("fabric", help="Run a Microsoft Fabric command")
    fabric.add_argument("command")
    fabric.add_argument("--config", default="fabric.config.yaml")
    fabric.add_argument("--replay-source-run-id", default="")

    patch_publish = actions.add_parser(
        "patch-publish",
        help="Publish one due ARG-backed patch generation to Fabric",
    )
    patch_publish.add_argument(
        "--config",
        default="config.yaml",
    )
    patch_publish.add_argument(
        "--fabric-config",
        default="fabric.config.yaml",
    )
    patch_publish.add_argument(
        "--connection-home",
        default=os.environ.get("AIOPS_CONNECTION_HOME", ""),
    )
    patch_publish.add_argument(
        "--source-root",
        default=os.environ.get("AIOPS_PATCH_SOURCE_ROOT", ""),
    )
    patch_publish.add_argument(
        "--managed-identity-client-id",
        default=os.environ.get("AZURE_CLIENT_ID", ""),
    )

    ontology = actions.add_parser("ontology", help="Query the Fabric Operational Context Graph")
    ontology.add_argument("question")
    ontology.add_argument("--entity", default="")
    ontology.add_argument("--config", default="fabric.config.yaml")

    semantic = actions.add_parser("semantic", help="Query the Semantic Knowledge Layer")
    semantic.add_argument("question")
    semantic.add_argument("--subject", default="")
    semantic.add_argument("--config", default="fabric.config.yaml")

    operations = actions.add_parser(
        "operations", help="Run read-only Operations Agent analysis"
    )
    operations.add_argument("command")
    operations.add_argument("subject")
    operations.add_argument("--subject-type", default="")
    operations.add_argument("--config", default="fabric.config.yaml")

    activate = actions.add_parser(
        "activate",
        help="Validate subscriptions, discover, publish to Fabric, and activate ontology",
    )
    activate.add_argument("--config", default="config.yaml")
    activate.add_argument("--fabric-config", default="fabric.config.yaml")
    activate.add_argument(
        "--connection-id",
        action="append",
        default=[],
        help="Connection to activate; repeat for hub and spoke. Defaults to all active.",
    )
    activate.add_argument(
        "--replay-source-run-id",
        default="",
        help="Republish one exact persisted activation generation.",
    )

    subscriptions = actions.add_parser(
        "subscriptions", help="Onboard and operate Azure subscription connections"
    )
    register_subscription_cli(subscriptions)

    parser.set_defaults(func=cli_command)


def register_subscription_cli(parser: argparse.ArgumentParser) -> None:
    commands = parser.add_subparsers(dest="subscriptions_command")

    def with_config(sub: argparse.ArgumentParser) -> argparse.ArgumentParser:
        sub.add_argument("--config", default="config.yaml")
        return sub

    add = with_config(commands.add_parser("add", help="Onboard a subscription using a dedicated SPN"))
    add.add_argument("connection_id")
    add.add_argument("--name", default="")
    add.add_argument("--tenant-id", required=True)
    add.add_argument("--subscription-id", required=True)
    add.add_argument("--client-id", required=True)
    add.add_argument(
        "--secret-ref",
        required=True,
        help="Secret pointer, e.g. keyvault://<vault>/secrets/<name> or env://VAR",
    )
    add.add_argument("--credential-id", default="")
    _add_metadata_arguments(add)

    listing = with_config(commands.add_parser("list", help="List registered subscription connections"))
    listing.add_argument("--active-only", action="store_true")

    detail = with_config(commands.add_parser("detail", help="Show one connection in full"))
    detail.add_argument("connection_id")

    update = with_config(commands.add_parser("update", help="Update connection name or credential"))
    update.add_argument("connection_id")
    update.add_argument("--name", default="")
    update.add_argument("--client-id", default="")
    update.add_argument("--secret-ref", default="")
    update.add_argument("--credential-id", default="")

    validate = with_config(commands.add_parser("validate", help="Validate SPN access for a connection"))
    validate.add_argument("connection_id")
    validate.add_argument("--check", action="append", default=[])

    sync = with_config(commands.add_parser("sync", help="Run a connection-scoped ingestion sync"))
    sync.add_argument("connection_id")
    sync.add_argument("--mode", default="initial", choices=("initial", "scheduled", "manual"))

    health = with_config(commands.add_parser("health", help="Show connection health and freshness"))
    health.add_argument("connection_id", nargs="?", default="")

    mapping = with_config(commands.add_parser("map", help="Assign business metadata to a connection"))
    mapping.add_argument("connection_id")
    _add_metadata_arguments(mapping)

    disable = with_config(commands.add_parser("disable", help="Disable a connection"))
    disable.add_argument("connection_id")

    enable = with_config(commands.add_parser("enable", help="Re-enable a disabled connection"))
    enable.add_argument("connection_id")


def _add_metadata_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--business-service", default="")
    parser.add_argument("--application", default="")
    parser.add_argument("--environment", default="")
    parser.add_argument("--project-owner", default="")
    parser.add_argument("--support-team", default="")
    parser.add_argument("--criticality", default="")
    parser.add_argument("--region", default="")
    parser.add_argument("--cost-center", default="")


def cli_command(args: argparse.Namespace) -> int:
    """Dispatch one CLI action while preserving its documented output streams."""
    action = getattr(args, "azure_graph_action", None)
    if action == "sync":
        manifest = IngestionService(ConnectorConfig.load(args.config)).run()
        print(json.dumps(manifest, indent=2, sort_keys=True))
        return 0
    if action == "inventory-refresh":
        from .inventory_refresh import run_inventory_refresh

        manifest = run_inventory_refresh(
            args.config,
            fabric_config_path=args.fabric_config,
            connection_id=args.connection_id,
        )
        print(json.dumps(manifest, indent=2, sort_keys=True))
        return 0
    if action == "query":
        result = ContextQueryService(Path(args.output_dir).expanduser().resolve()).answer(args.question)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if action == "schedule":
        config_path = Path(args.config).expanduser().resolve()
        install_schedule(args.schedule, config_path, config_path.parent)
        return 0
    if action == "sample":
        from datetime import datetime

        payload = json.loads(Path(args.fixture).read_text())
        graph = Normalizer().normalize(payload, datetime.now(UTC))
        manifest = DatasetStore(Path(args.output_dir).expanduser().resolve()).publish(
            graph,
            payload,
            {"runId": "sample", "status": "completed", "queryVersion": "1.0.0"},
        )
        print(json.dumps(manifest, indent=2, sort_keys=True))
        return 0
    if action == "local":
        from .local_seed import seed_local_environment

        result = seed_local_environment(
            root=args.home,
            fixture=args.fixture,
            connection_id=args.connection_id,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if action == "local-spn":
        from .local_seed import inject_local_spn_connection

        result = inject_local_spn_connection(
            root=args.home,
            connection_id=args.connection_id,
            name=args.name,
            sync=args.sync,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if action == "fabric":
        from fabric.commands import FabricCommandService
        from fabric.config import FabricRuntimeConfig
        from fabric.runtime import build_runtime

        runtime = build_runtime(FabricRuntimeConfig.load(args.config))
        result = FabricCommandService(runtime.service).execute(
            args.command,
            replay_source_run_id=args.replay_source_run_id,
        )
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        return 0
    if action == "patch-publish":
        from fabric.patch_publication import run_patch_publication

        try:
            result = run_patch_publication(
                args.config,
                args.fabric_config,
                connection_home=args.connection_home,
                source_root=args.source_root,
                managed_identity_client_id=args.managed_identity_client_id,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            reason_code = (
                "writer_lock_unavailable"
                if "already running" in str(exc).casefold()
                else "patch_publication_failed"
            )
            print(
                json.dumps(
                    {"status": "failed", "reason_code": reason_code},
                    sort_keys=True,
                ),
                file=sys.stderr,
            )
            return 1
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if action == "ontology":
        from fabric.config import FabricRuntimeConfig
        from fabric.runtime import build_runtime

        runtime = build_runtime(FabricRuntimeConfig.load(args.config))
        result = runtime.service.ontology_query(args.question, entity=args.entity)
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        return 0
    if action == "semantic":
        from fabric.config import FabricRuntimeConfig
        from fabric.runtime import build_runtime

        runtime = build_runtime(FabricRuntimeConfig.load(args.config))
        result = runtime.semantic_engine().query(args.question, subject=args.subject)
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        return 0
    if action == "operations":
        from fabric.config import FabricRuntimeConfig
        from fabric.runtime import build_runtime

        runtime = build_runtime(FabricRuntimeConfig.load(args.config))
        result = runtime.operations_agent().analyze(
            args.command,
            args.subject,
            subject_type=args.subject_type,
        )
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        return 0
    if action == "activate":
        from onboarding.activation import ActivationFailure, activate_runtime
        from onboarding.runtime import build_onboarding_service

        try:
            result = activate_runtime(
                build_onboarding_service(ConnectorConfig.load(args.config)),
                fabric_config=args.fabric_config,
                connection_ids=args.connection_id or None,
                enrichment_root=os.environ.get("AIOPS_HOME", "").strip() or None,
                progress_callback=lambda event: print(
                    json.dumps(event, separators=(",", ":"), sort_keys=True),
                    file=sys.stderr,
                    flush=True,
                ),
                **(
                    {"replay_source_run_id": args.replay_source_run_id}
                    if args.replay_source_run_id
                    else {}
                ),
            )
        except ActivationFailure as exc:
            print(
                json.dumps(
                    {
                        "status": "error",
                        "stage": exc.stage,
                        "error_code": exc.error_code,
                        "elapsed_seconds": exc.elapsed_seconds,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 1
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            print(
                json.dumps(
                    {"status": "error", "message": str(exc)},
                    indent=2,
                    sort_keys=True,
                )
            )
            return 1
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        return 0
    if action == "subscriptions":
        return subscriptions_command(args)
    print(
        "Usage: aiops azure-graph "
        "{sync|query|schedule|sample|local|local-spn|fabric|patch-publish|ontology|semantic|operations|activate|subscriptions}"
    )
    return 2


def subscriptions_command(args: argparse.Namespace) -> int:
    from onboarding.metadata import BusinessMetadata
    from onboarding.registry import (
        ConnectionNotFoundError,
        DuplicateConnectionError,
        RegistryConflictError,
    )
    from onboarding.runtime import build_onboarding_service
    from onboarding.service import OnboardingError

    command = getattr(args, "subscriptions_command", None)
    if not command:
        print(
            "Usage: aiops-inventory subscriptions "
            "{add|list|detail|update|validate|sync|health|map|disable|enable}"
        )
        return 2

    service = build_onboarding_service(ConnectorConfig.load(args.config))
    try:
        result = _dispatch_subscriptions(service, command, args, BusinessMetadata)
    except (
        ConnectionNotFoundError,
        DuplicateConnectionError,
        RegistryConflictError,
        OnboardingError,
        ValueError,
    ) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, indent=2, sort_keys=True))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    if command == "validate" and not result.get("passed"):
        return 1
    if command == "sync" and result.get("status") != "succeeded":
        return 1
    return 0


def _dispatch_subscriptions(service, command: str, args: argparse.Namespace, metadata_cls):
    if command == "add":
        return service.add(
            connection_id=args.connection_id,
            name=args.name or None,
            tenant_id=args.tenant_id,
            subscription_id=args.subscription_id,
            client_id=args.client_id,
            secret_ref=args.secret_ref,
            credential_id=args.credential_id or None,
            metadata=_metadata_from_args(args, metadata_cls),
        )
    if command == "list":
        return service.list(include_disabled=not args.active_only)
    if command == "detail":
        return service.detail(args.connection_id)
    if command == "update":
        return service.update(
            args.connection_id,
            name=args.name or None,
            client_id=args.client_id or None,
            secret_ref=args.secret_ref or None,
            credential_id=args.credential_id or None,
        )
    if command == "validate":
        return service.validate(
            args.connection_id, checks=tuple(args.check) if args.check else None
        )
    if command == "sync":
        return service.sync(args.connection_id, mode=args.mode)
    if command == "health":
        return service.health_report(args.connection_id or None)
    if command == "map":
        return service.map_metadata(args.connection_id, _metadata_from_args(args, metadata_cls))
    if command == "disable":
        return service.disable(args.connection_id)
    if command == "enable":
        return service.enable(args.connection_id)
    raise ValueError(f"Unknown subscriptions command: {command}")


def _metadata_from_args(args: argparse.Namespace, metadata_cls):
    return metadata_cls(
        business_service=getattr(args, "business_service", "") or None,
        application=getattr(args, "application", "") or None,
        environment=getattr(args, "environment", "") or None,
        project_owner=getattr(args, "project_owner", "") or None,
        support_team=getattr(args, "support_team", "") or None,
        criticality=getattr(args, "criticality", "") or None,
        region=getattr(args, "region", "") or None,
        cost_center=getattr(args, "cost_center", "") or None,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aiops-inventory")
    register_cli(parser)
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    return int(func(args) if func else 2)


if __name__ == "__main__":
    raise SystemExit(main())
