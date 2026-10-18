"""Finite production entry point for the dedicated ontology publisher."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping, Sequence
from contextlib import ExitStack
from dataclasses import dataclass, replace
from datetime import UTC, datetime

import httpx

from fabric.auth import FabricAuthConfig, build_credential, build_delta_storage_options
from fabric.config import FabricRuntimeConfig
from fabric.dataset_mapper import ONTOLOGY_RELATIONSHIP_TYPES
from fabric.fabric_client import FabricClient
from fabric.lakehouse_manager import LakehouseManager
from fabric.runtime import FabricRuntimeMode, build_runtime
from onboarding.registry import ConnectionRegistry
from ontology.native_publication import NativeOntologyPublication
from ontology.ontology_manager import OntologyManager
from ontology.ontology_publisher import OntologyPublisher
from ontology.ontology_validator import OntologyValidator
from storage.datasets import DatasetStore
from storage.delta_writer import DeltaWriter
from storage.locking import MonotonicFenceAllocator
from storage.onelake_documents import OneLakeDocumentStore
from storage.onelake_writer import OneLakeWriter

from .command_intake import PublisherCommandConsumer
from .dispatch_store import PublisherDispatchStore
from .drill_control import DrillControlConfig, PublisherDrillControl
from .publisher import CONSUMER_FAMILIES, OntologyGenerationPublisher
from .publisher_worker import PublisherIntakeAdapter, PublisherWorker

PUBLISHER_CAPABILITIES = {
    "connection": frozenset({"read"}),
    "command": frozenset({"claim_rollback", "status"}),
    "state": frozenset(),
    "dispatch": frozenset(
        {"claim_publish", "claim_rollback", "status", "create_rollback"}
    ),
    "publication": frozenset({"read", "write", "stage", "pointer"}),
}


@dataclass(frozen=True)
class PublisherRuntimeConfig:
    roots: Mapping[str, str]
    fabric_config: str
    publisher_client_id: str
    runtime_mode: str
    capabilities: Mapping[str, frozenset[str]]
    drill_enabled: bool = False
    drill_root: str = ""
    environment: str = ""
    drill_connection_environment: str = ""
    drill_workspace_environment: str = ""

    @classmethod
    def from_env(
        cls, env: Mapping[str, str] | None = None
    ) -> PublisherRuntimeConfig:
        values = env if env is not None else os.environ
        if values.get("AIOPS_IDENTITY_CLASS") != "publisher":
            raise ValueError("AIOPS_IDENTITY_CLASS must be publisher")
        publisher_id = _required(
            values.get("AIOPS_ONTOLOGY_PUBLISHER_CLIENT_ID"),
            "AIOPS_ONTOLOGY_PUBLISHER_CLIENT_ID",
        )
        if values.get("AZURE_CLIENT_ID") != publisher_id:
            raise ValueError(
                "AZURE_CLIENT_ID must equal AIOPS_ONTOLOGY_PUBLISHER_CLIENT_ID"
            )
        if str(values.get("AIOPS_ONTOLOGY_STATE_HOME") or "").strip():
            raise ValueError("publisher must not receive AIOPS_ONTOLOGY_STATE_HOME")
        roots = {
            name: _required(values.get(variable), variable)
            for name, variable in (
                ("connection", "AIOPS_CONNECTION_HOME"),
                ("command", "AIOPS_ONTOLOGY_COMMAND_HOME"),
                ("dispatch", "AIOPS_ONTOLOGY_DISPATCH_HOME"),
                ("publication", "AIOPS_ONTOLOGY_PUBLICATION_HOME"),
            )
        }
        if len(set(roots.values())) != len(roots):
            raise ValueError("publisher capability roots must be pairwise distinct")
        mode = str(values.get("AIOPS_RUNTIME_MODE") or "production").casefold()
        if mode == "production" and any(
            not value.startswith("abfss://") for value in roots.values()
        ):
            raise ValueError("production publisher roots must be OneLake URIs")
        return cls(
            roots=roots,
            fabric_config=_required(
                values.get("AIOPS_FABRIC_CONFIG"), "AIOPS_FABRIC_CONFIG"
            ),
            publisher_client_id=publisher_id,
            runtime_mode=mode,
            capabilities=PUBLISHER_CAPABILITIES,
            drill_enabled=str(
                values.get("AIOPS_ONTOLOGY_DRILL_ENABLED") or ""
            ).casefold()
            in {"1", "true", "yes"},
            drill_root=str(values.get("AIOPS_ONTOLOGY_DRILL_HOME") or "").strip(),
            environment=str(values.get("AIOPS_ENVIRONMENT") or "").strip(),
            drill_connection_environment=str(
                values.get("AIOPS_DRILL_CONNECTION_ENVIRONMENT") or ""
            ).strip(),
            drill_workspace_environment=str(
                values.get("AIOPS_DRILL_WORKSPACE_ENVIRONMENT") or ""
            ).strip(),
        )


def publisher_fabric_config(
    config: FabricRuntimeConfig, publisher_client_id: str
) -> FabricRuntimeConfig:
    """Replace any YAML/API credential before constructing Fabric clients."""
    return replace(
        config,
        auth=FabricAuthConfig(
            mode="managed_identity",
            managed_identity_client_id=_required(
                publisher_client_id, "publisher_client_id"
            ),
        ),
    )


def build_publisher_runtime(config: PublisherRuntimeConfig):
    loaded = FabricRuntimeConfig.load(config.fabric_config)
    fabric_config = publisher_fabric_config(
        loaded, config.publisher_client_id
    )
    if config.runtime_mode == "production":
        roots = [*config.roots.values(), str(fabric_config.source_data_root)]
        if len(set(roots)) != len(roots):
            raise ValueError(
                "publisher and Fabric roots must be explicit and pairwise distinct"
            )
    fabric = build_runtime(fabric_config, mode=FabricRuntimeMode.PUBLISH)
    dataset = DatasetStore(config.roots["publication"])
    publication = dataset.authoritative_publisher(
        publisher_identity=config.publisher_client_id,
        approved_publisher_identity=config.publisher_client_id,
    )
    publisher = OntologyGenerationPublisher(
        publication,
        validator=OntologyValidator(
            allowed_triples={
                (str(row[0]), str(row[1]), str(row[2]))
                for row in ONTOLOGY_RELATIONSHIP_TYPES
            }
        ),
        approved_publisher_identity=config.publisher_client_id,
    )
    dispatches = PublisherDispatchStore(config.roots["dispatch"]).publisher()
    now = lambda: datetime.now(UTC)

    def check(_stage: str, generation_id: str):
        generation = publication.read_generation(generation_id)
        passed = bool(
            generation["manifest"].get("complete")
            and generation["validation"].get("passed")
        )
        return {family: passed for family in CONSUMER_FAMILIES}

    drill_control = build_drill_control(config)
    worker = PublisherWorker(
        dispatches=dispatches,
        publisher=publisher,
        publisher_identity=config.publisher_client_id,
        owner_id=f"publisher:{config.publisher_client_id}",
        fence_allocator=MonotonicFenceAllocator(
            OneLakeDocumentStore(config.roots["dispatch"])
        ),
        materialize=lambda candidate: _materialize(
            fabric.service, candidate.source_generation
        ),
        consumer_check=check,
        now=now,
        drill_control=drill_control,
    )
    intake = PublisherIntakeAdapter(
        registry=ConnectionRegistry(config.roots["connection"]),
        commands=PublisherCommandConsumer(config.roots["command"]),
        dispatches=dispatches,
        publication=publication,
        owner_id=f"publisher:{config.publisher_client_id}",
        now=now,
    )
    return worker, intake


def build_drill_control(
    config: PublisherRuntimeConfig,
) -> PublisherDrillControl | None:
    if not config.drill_enabled:
        return None
    return PublisherDrillControl(
        DrillControlConfig(
            enabled=True,
            environment=config.environment,
            connection_environment=config.drill_connection_environment,
            workspace_environment=config.drill_workspace_environment,
            publisher_client_id=config.publisher_client_id,
            azure_client_id=config.publisher_client_id,
            drill_root=config.drill_root,
            protected_roots=tuple(config.roots.values()),
        )
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ontology-publisher")
    parser.add_argument(
        "command",
        choices=(
            "run-once",
            "native-preview",
            "native-publish",
            "drill-arm",
            "drill-inspect",
            "drill-resume",
            "drill-clean",
        ),
    )
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--drill-id", default="")
    parser.add_argument("--command-hash", default="")
    parser.add_argument("--fault", default="")
    parser.add_argument("--expires-at", default="")
    parser.add_argument("--source-generation", default="")
    parser.add_argument("--preview-hash", default="")
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args(argv)
    config = PublisherRuntimeConfig.from_env()
    if args.command in {"native-preview", "native-publish"}:
        if not args.source_generation.strip():
            parser.error("--source-generation is required for native publication")
        if args.command == "native-publish" and not (args.yes and args.preview_hash):
            parser.error("native-publish requires an approved --preview-hash and --yes")
        result = run_native_publication(
            config,
            source_generation=args.source_generation,
            preview_hash=args.preview_hash if args.command == "native-publish" else "",
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    if args.command != "run-once":
        control = build_drill_control(config)
        if control is None:
            raise PermissionError("publisher drill control is disabled")
        moment = datetime.now(UTC)
        if args.command == "drill-arm":
            result = control.arm(
                drill_id=args.drill_id,
                target_command_hash=args.command_hash,
                fault=args.fault,
                issued_at=moment,
                expires_at=datetime.fromisoformat(args.expires_at),
            )
        elif args.command == "drill-inspect":
            result = control.inspect(now=moment)
        elif args.command == "drill-resume":
            control.resume(
                drill_id=args.drill_id,
                actor_client_id=config.publisher_client_id,
                now=moment,
            )
            result = control.inspect(now=moment)
        else:
            result = {
                "cleaned": control.clean(
                    actor_client_id=config.publisher_client_id,
                    now=moment,
                )
            }
        print(json.dumps(result, sort_keys=True))
        return 0
    worker, intake = build_publisher_runtime(config)
    intake_result = intake.process_one()
    worker_result = worker.run_once(limit=max(1, args.limit))
    print(json.dumps({"intake": intake_result, "worker": worker_result}, sort_keys=True))
    return 0 if worker_result["failed"] == 0 else 1


def _materialize(service, source_generation: str) -> dict[str, object]:
    result = service.sync(replay_source_run_id=source_generation)
    return {
        "status": result.status,
        "run_id": result.run_id,
        "tables": list(result.tables),
    }


def run_native_publication(
    config: PublisherRuntimeConfig, *, source_generation: str, preview_hash: str = ""
) -> dict[str, object]:
    """Read verified existing tables and optionally publish only their native definition."""
    if (
        config.runtime_mode != "production"
        or config.environment != "production"
        or config.drill_enabled
    ):
        raise PermissionError("Native publication requires a non-drill production publisher")
    loaded = publisher_fabric_config(
        FabricRuntimeConfig.load(config.fabric_config), config.publisher_client_id
    )
    if not loaded.ontology.enabled or loaded.create_lakehouse_if_missing:
        raise PermissionError("Native publication must be explicitly enabled without lakehouse creation")
    if len({*config.roots.values(), str(loaded.source_data_root)}) != 5:
        raise ValueError("Publisher and Fabric capability roots must be pairwise distinct")
    with ExitStack() as stack:
        credential = stack.enter_context(build_credential(loaded.auth))
        http = stack.enter_context(httpx.Client(
            timeout=60, headers={"x-ms-fabric-skill": "fabriciq-ontology-cli"}
        ))
        client = FabricClient(credential, http_client=http, max_attempts=1)
        lakehouse = LakehouseManager(client, loaded.workspace_id)
        lakehouse.resolve(lakehouse_id=loaded.lakehouse_id)
        onelake = OneLakeWriter(
            loaded.workspace_id, loaded.lakehouse_id,
            table_schema=loaded.table_schema, credential=credential,
        )
        if onelake.service is not None:
            stack.callback(onelake.service.close)
        native = NativeOntologyPublication(
            delta=DeltaWriter(
                storage_options_provider=lambda: build_delta_storage_options(credential)
            ),
            onelake=onelake,
            lakehouse=lakehouse,
            publisher=OntologyPublisher(
                OntologyManager(client, loaded.workspace_id),
                workspace_id=loaded.workspace_id,
                lakehouse_id=loaded.lakehouse_id,
                source_schema=loaded.table_schema,
            ),
            ontology_id=loaded.ontology.ontology_id,
            ontology_name=loaded.ontology.ontology_name,
        )
        if preview_hash:
            return native.publish(
                source_generation=source_generation, expected_preview_hash=preview_hash
            )
        return native.preview(source_generation=source_generation)


def _required(value: object, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} must not be empty")
    return text


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
