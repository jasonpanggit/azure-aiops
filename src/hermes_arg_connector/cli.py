from __future__ import annotations

import argparse
import json
from datetime import UTC
from pathlib import Path

from .agent_queries import ContextQueryService
from .config import ConnectorConfig
from .normalize import Normalizer
from .schedule import install_schedule
from .service import IngestionService
from .storage import DatasetStore


def register_cli(parser: argparse.ArgumentParser) -> None:
    actions = parser.add_subparsers(dest="azure_graph_action")

    sync = actions.add_parser("sync", help="Run Azure MCP discovery and ARG ingestion now")
    sync.add_argument("--config", default="config.yaml")

    query = actions.add_parser("query", help="Query the normalized operational context")
    query.add_argument("question")
    query.add_argument("--output-dir", default="./data")

    schedule = actions.add_parser("schedule", help="Create a Hermes cron job for continuous ingestion")
    schedule.add_argument("--config", default="config.yaml")
    schedule.add_argument("--schedule", default="every 30m")

    sample = actions.add_parser("sample", help="Build datasets from a mock ARG response file")
    sample.add_argument("--fixture", default="tests/fixtures/mock_arg_responses.json")
    sample.add_argument("--output-dir", default="./sample-data")

    fabric = actions.add_parser("fabric", help="Run a Microsoft Fabric inventory command")
    fabric.add_argument("command")
    fabric.add_argument("--config", default="fabric.config.yaml")
    fabric.add_argument("--replay-source-run-id", default="")

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

    parser.set_defaults(func=cli_command)


def cli_command(args: argparse.Namespace) -> int:
    action = getattr(args, "azure_graph_action", None)
    if action == "sync":
        manifest = IngestionService(ConnectorConfig.load(args.config)).run()
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
    print(
        "Usage: hermes azure-graph "
        "{sync|query|schedule|sample|fabric|ontology|semantic|operations}"
    )
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hermes-arg")
    register_cli(parser)
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    return int(func(args) if func else 2)


if __name__ == "__main__":
    raise SystemExit(main())
