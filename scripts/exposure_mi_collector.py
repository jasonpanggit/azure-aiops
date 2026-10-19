"""Fixed corrected-target, read-only Exposure evidence collection candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from azure.core.exceptions import AzureError
from azure.identity import ManagedIdentityCredential
from azure.storage.filedatalake import FileSystemClient

from fabric.sql_endpoint import FabricSqlReader, SqlEndpoint, probe_exposure_readiness
from ontology.subscription_connection import SubscriptionConnection
from scripts.benchmark_exposure_read_model import (
    derive_benchmark_authorization,
    run_fabric_sql_benchmark,
)

TENANT = "262a3a77-7d74-4684-8937-897d98d2a17a"
SUBSCRIPTION = "890c9bfc-d09c-4143-9ce5-465e75e3eecc"
CLIENT = "5d4d603a-343c-4b92-b43a-cd1ebe771ab6"
WORKSPACE = "2c1fea36-104d-4c26-86db-12e09e432b41"
LAKEHOUSE = "f995229d-970e-44ec-8af5-df9e25261d19"
ROOT = f"abfss://{WORKSPACE}@onelake.dfs.fabric.microsoft.com/{LAKEHOUSE}/Files/aiops"
ENDPOINT = {
    "server": (
        "o45cujtupwcencjxrf6zruvbpi-g3vb6lcncatezbw3clqj4qzlie"
        ".datawarehouse.fabric.microsoft.com"
    ),
    "database": "50b886f9-d05a-4881-92db-331c5cf46014",
    "schema": "dbo",
}
MAX_DOCUMENT_BYTES = 4 * 1024 * 1024


def digest(value: bytes) -> str:
    """Return a stable content reference without exporting source payloads."""
    return "sha256:" + hashlib.sha256(value).hexdigest()


def validate_runtime(environment: dict[str, str]) -> None:
    """Reject stale targets, identity overrides, or incomplete release bindings."""
    expected = {
        "AIOPS_HOME": ROOT,
        "AIOPS_CONNECTION_HOME": ROOT + "/connections",
        "AZURE_CLIENT_ID": CLIENT,
    }
    if any(
        environment.get(key, "").strip() != value for key, value in expected.items()
    ):
        raise ValueError("runtime_root_or_identity_mismatch")
    release = environment.get("AIOPS_SOURCE_REVISION", "")
    if len(release) != 40 or any(c not in "0123456789abcdef" for c in release):
        raise ValueError("immutable_source_revision_missing")
    config = json.loads(environment.get("AIOPS_FABRIC_CONFIG_JSON", "{}"))
    fabric = config.get("fabric", {})
    auth = fabric.get("auth", {})
    if (
        fabric.get("workspace_id") != WORKSPACE
        or fabric.get("lakehouse_id") != LAKEHOUSE
        or fabric.get("sql_endpoint") != ENDPOINT
        or auth.get("tenant_id") != TENANT
        or auth.get("mode") != "managed_identity"
        or auth.get("managed_identity_client_id") != CLIENT
    ):
        raise ValueError("runtime_fabric_binding_mismatch")


def read_document(fs: Any, name: str) -> tuple[dict[str, Any], str]:
    """Read one fixed document with a hard size bound and no write capability."""
    client = fs.get_file_client(f"{LAKEHOUSE}/Files/aiops/{name}")
    if client.get_file_properties().size > MAX_DOCUMENT_BYTES:
        raise ValueError("document_size_bound_exceeded")
    body = client.download_file(
        length=MAX_DOCUMENT_BYTES + 1, max_concurrency=1
    ).readall()
    if len(body) > MAX_DOCUMENT_BYTES:
        raise ValueError("document_size_bound_exceeded")
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise TypeError("document_shape_invalid")
    return payload, digest(body)


class BoundedBenchmarkReader:
    """Limit aggregate/page transfers and the total SQL walk query count."""

    def __init__(self, reader: Any) -> None:
        self.reader = reader
        self.calls = 0

    def query(
        self,
        sql: str,
        parameters: tuple[Any, ...] = (),
        *,
        max_rows: int | None = None,
    ) -> list[dict[str, Any]]:
        if (
            not sql.lstrip().upper().startswith(("SELECT", "WITH [SCOPED] AS (SELECT"))
            or type(max_rows) is not int
            or not 1 <= max_rows <= 101
            or self.calls >= 6000
        ):
            raise ValueError("benchmark_query_bound_exceeded")
        self.calls += 1
        return self.reader.query(sql, parameters, max_rows=max_rows)


def collect(credential: Any, *, benchmark: bool) -> dict[str, Any]:
    """Collect real observations; never manufacture an acceptance manifest."""
    import pyodbc

    if not isinstance(credential, ManagedIdentityCredential):
        raise TypeError("application_managed_identity_required")
    fs = FileSystemClient(
        account_url="https://onelake.dfs.fabric.microsoft.com",
        file_system_name=WORKSPACE,
        credential=credential,
        retry_total=0,
        connection_timeout=10,
        read_timeout=20,
    )
    registry, registry_hash = read_document(
        fs, "connections/state/subscription_connections.json"
    )
    pointer, pointer_hash = read_document(fs, "exposure/gold-generation-pointer.json")
    connections = []
    for row in registry.get("connections") or []:
        connection = SubscriptionConnection.from_mapping(row)
        if connection is not None and connection.is_active:
            connections.append(connection)
    authorization = derive_benchmark_authorization(connections)
    if (
        authorization.tenant_id != TENANT
        or authorization.scope.get("subscription") != (SUBSCRIPTION,)
        or len(authorization.connection_ids) != 1
    ):
        raise ValueError("registered_scope_does_not_match_fixed_target")
    generation = str(pointer.get("readable_generation_id") or "").strip()
    if not generation:
        raise ValueError("readable_generation_missing")
    scope = (TENANT, SUBSCRIPTION, authorization.connection_ids[0])
    report: dict[str, Any] = {
        "captured_at": datetime.now(UTC).isoformat(),
        "identity_kind": "application_managed_identity",
        "identity_client_id": CLIENT,
        "release_id": os.environ["AIOPS_SOURCE_REVISION"],
        "collector_sha256": digest(Path(__file__).read_bytes()),
        "generation_id": generation,
        "registry_sha256": registry_hash,
        "pointer_sha256": pointer_hash,
        "scope_sha256": digest(json.dumps(scope).encode()),
        "previous_generation_id": pointer.get("previous_generation_id"),
        "production_certified": False,
        "phase4_ready": False,
        "evidence_kind": "observations_not_acceptance_or_provider_attestation",
        "queries": {},
    }
    report["readiness"] = probe_exposure_readiness(
        ENDPOINT, credential, endpoint_source="validated_corrected_runtime_json"
    ).to_dict()
    if not report["readiness"]["ready"]:
        report["status"] = "blocked_sql_readiness"
        return report
    reader = FabricSqlReader(SqlEndpoint(**ENDPOINT), credential, timeout_seconds=20)
    queries = {
        "publication": (
            (
                "SELECT read_model_generation_id, previous_generation_id, "
                "ingestion_run_id, reconciliation_status, reconciliation_hash, "
                "published_at, retain_until FROM dbo.metadata_exposure_gold_generations "
                "WHERE read_model_generation_id = ?"
            ),
            (generation,),
            1,
        ),
        "gold_counts": (
            (
                "SELECT target_kind, source_family, source_generation_id, "
                "COUNT_BIG(*) AS row_count, "
                "SUM(represented_workload_count) AS represented_per_fact_sum, "
                "SUM(unknown_workload_count) AS unknown_per_fact_sum "
                "FROM dbo.gold_exposure_facts WHERE tenant_id = ? "
                "AND subscription_id = ? AND connection_id = ? "
                "AND read_model_generation_id = ? "
                "GROUP BY target_kind, source_family, source_generation_id"
            ),
            (*scope, generation),
            32,
        ),
        "workload_checkpoint_sources": (
            (
                "SELECT source_family, status, effective_generation, "
                "COUNT_BIG(*) AS checkpoint_count, SUM(row_count) AS row_count "
                "FROM dbo.metadata_workload_source_checkpoints WHERE tenant_id = ? "
                "AND subscription_id = ? AND connection_id = ? "
                "GROUP BY source_family, status, effective_generation"
            ),
            scope,
            64,
        ),
        "silver_deployment_sources": (
            (
                "SELECT effective_generation, COUNT_BIG(*) AS row_count "
                "FROM dbo.silver_workload_deployments WHERE tenant_id = ? "
                "AND subscription_id = ? AND connection_id = ? "
                "GROUP BY effective_generation"
            ),
            scope,
            32,
        ),
        "generation_typed_traversal_edges": (
            (
                "SELECT predicate, COUNT_BIG(*) AS edge_count "
                "FROM dbo.ontology_relationships WHERE tenant_id = ? "
                "AND subscription_id = ? AND source = 'container_insights' "
                "AND lifecycle_status = 'active' "
                "AND JSON_VALUE(payload_json, '$.read_model_generation_id') = ? "
                "AND ((subject_type = 'ImageDigest' AND predicate = 'deployedAs' "
                "AND object_type = 'WorkloadDeployment') "
                "OR (subject_type = 'WorkloadDeployment' AND predicate = 'runsApplication' "
                "AND object_type = 'Application')) GROUP BY predicate"
            ),
            (TENANT, SUBSCRIPTION, generation),
            2,
        ),
    }
    failed = False
    for name, (sql, parameters, maximum) in queries.items():
        try:
            rows = reader.query(sql, parameters, max_rows=maximum)
        except pyodbc.Error as exc:
            failed = True
            report["queries"][name] = {
                "status": "provider_query_failed",
                "sqlstate": str(exc.args[0]) if exc.args else "unknown",
            }
            continue
        for row in rows:
            for key in (
                "source_generation_id",
                "effective_generation",
                "ingestion_run_id",
            ):
                if key in row:
                    value = str(row.pop(key) or "")
                    row[key + "_hash"] = digest(value.encode()) if value else ""
        report["queries"][name] = {"status": "read", "rows": rows}
    if benchmark:
        counts = report["queries"]["gold_counts"]
        total = sum(int(row["row_count"]) for row in counts.get("rows", []))
        if counts["status"] == "read" and 0 < total <= 100_000:
            report["benchmark"] = run_fabric_sql_benchmark(
                BoundedBenchmarkReader(reader),
                authorization,
                generation_id=generation,
                expected_rows=100_000,
                page_size=100,
                warmups=5,
                measurements=20,
            )
        else:
            report["benchmark"] = {"status": "blocked_corpus_outside_fixed_walk_bound"}
    _, final_pointer_hash = read_document(fs, "exposure/gold-generation-pointer.json")
    _, final_registry_hash = read_document(
        fs, "connections/state/subscription_connections.json"
    )
    report["metadata_unchanged_during_collection"] = (
        pointer_hash == final_pointer_hash and registry_hash == final_registry_hash
    )
    report["source_binding_complete"] = False
    report["remaining_binding_requirement"] = (
        "publication/source receipts and source-bound Silver-to-ontology "
        "identity reconciliation; per-fact sums are not unique workload counts"
    )
    report["status"] = (
        "observations_collected"
        if not failed and report["metadata_unchanged_during_collection"]
        else "blocked_incomplete_or_changed_evidence"
    )
    if benchmark and report["benchmark"].get("status") != "pass":
        report["status"] = "blocked_benchmark_not_qualified"
    return report


def main() -> int:
    """Run only inside the reviewed fixed Job, with a bounded wall-clock budget."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", action="store_true")
    args = parser.parse_args()

    def deadline(_signal: int, _frame: Any) -> None:
        raise TimeoutError("collector_deadline_exceeded")

    signal.signal(signal.SIGALRM, deadline)
    signal.alarm(900)
    try:
        validate_runtime(dict(os.environ))
        with ManagedIdentityCredential(client_id=CLIENT) as credential:
            report = collect(credential, benchmark=args.benchmark)
    except (AzureError, OSError, RuntimeError, ValueError, TypeError) as exc:
        report = {
            "status": "blocked_collection_error",
            "exception_type": type(exc).__name__,
            "production_certified": False,
            "phase4_ready": False,
        }
    finally:
        signal.alarm(0)
    print(json.dumps(report, sort_keys=True, separators=(",", ":")), flush=True)
    return 0 if report["status"] == "observations_collected" else 2


if __name__ == "__main__":
    sys.exit(main())
