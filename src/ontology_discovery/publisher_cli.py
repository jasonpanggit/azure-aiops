"""Finite production entry point for the dedicated ontology publisher."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from fabric.auth import FabricAuthConfig
from fabric.config import FabricRuntimeConfig
from fabric.dataset_mapper import ONTOLOGY_RELATIONSHIP_TYPES
from fabric.runtime import build_runtime
from onboarding.registry import ConnectionRegistry
from ontology.ontology_validator import OntologyValidator
from storage.datasets import DatasetStore
from storage.locking import MonotonicFenceAllocator
from storage.onelake_documents import OneLakeDocumentStore

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
    fabric = build_runtime(fabric_config)
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
        drill_control=(
            PublisherDrillControl(
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
            if config.drill_enabled
            else None
        ),
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ontology-publisher")
    parser.add_argument("command", choices=("run-once",))
    parser.add_argument("--limit", type=int, default=1)
    args = parser.parse_args(argv)
    config = PublisherRuntimeConfig.from_env()
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


def _required(value: object, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} must not be empty")
    return text


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
