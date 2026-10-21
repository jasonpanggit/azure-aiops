"""Explicit finite caller and read-only authority observer; no sync runtime."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import httpx
from azure.core import MatchConditions
from azure.identity import ManagedIdentityCredential
from azure.storage.filedatalake import DataLakeServiceClient

from fabric.auth import build_delta_storage_options
from fabric.exposure_scalar_migration import (
    TABLE,
    ExposureScalarMigrationPlan,
    migrate_exposure_scalars,
    migration_rows_hash,
)
from fabric.fabric_client import FabricClient
from ontology.ontology_manager import OntologyManager
from storage.delta_writer import DeltaWriter
from storage.onelake_writer import OneLakeWriter

WORKSPACE = "2c1fea36-104d-4c26-86db-12e09e432b41"
LAKEHOUSE = "f995229d-970e-44ec-8af5-df9e25261d19"
NATIVE_ITEM = "bb479201-8ab1-4fde-ab6c-9f9a16477115"
TENANT = "262a3a77-7d74-4684-8937-897d98d2a17a"
SOURCE_POINTER = "Files/aiops/current.json"
CATALOG = "Files/ontology/metadata/catalog.json"
_EVIDENCE_PREFIX = "Files/aiops/validation/native-scalar/"
_OBSERVATION_COLUMNS = ("resource_id", "tenant_id", "subscription_id", "change_version")


def document_hash(value: Mapping[str, Any]) -> str:
    """Hash exact JSON values for reviewed authority artifacts."""
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode()).hexdigest()


class ReadOnlyLakeDocuments:
    """Read bounded JSON using explicit existing identity and conditional GETs."""

    def __init__(self, file_system: Any) -> None:
        self.file_system = file_system

    def read(self, path: str) -> dict[str, Any]:
        """Read one contained existing file without any create/list/write call."""
        if not path.startswith("Files/") or any(
            part in {"", ".", ".."} for part in path.split("/")
        ):
            raise ValueError("Authority document path is not contained")
        client = self.file_system.get_file_client(f"{LAKEHOUSE}/{path}")
        before = client.get_file_properties()
        if before.size > 8 * 1024 * 1024:
            raise ValueError("Authority document exceeds bounded read size")
        body = client.download_file(
            etag=before.etag, match_condition=MatchConditions.IfNotModified,
        ).readall()
        if len(body) != before.size or len(body) > 8 * 1024 * 1024:
            raise ValueError("Authority document body differs from bounded size")
        if client.get_file_properties().etag != before.etag:
            raise RuntimeError("Authority document changed during read")
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise TypeError("Authority document must be a JSON object")
        return {"etag": before.etag, "payload": payload}


def validate_request(request: Mapping[str, Any], env: Mapping[str, str]) -> None:
    """Reject wrong roots, targets and ambiguous identity before constructing clients."""
    plan = ExposureScalarMigrationPlan(**request["plan"])
    if (plan.workspace_id, plan.lakehouse_id, plan.table_schema) != (WORKSPACE, LAKEHOUSE, ""):
        raise ValueError("Caller supports only the existing reviewed native Lakehouse")
    for name in ("publisher_client_id", "publisher_object_id"):
        if not re.fullmatch(r"[0-9a-f-]{36}", str(request.get(name, ""))):
            raise ValueError("Caller requires explicit reviewed publisher identity")
    if (
        env.get("AIOPS_IDENTITY_CLASS") != "publisher"
        or env.get("AZURE_CLIENT_ID") != request["publisher_client_id"]
    ):
        raise ValueError("Caller must use the existing explicit publisher identity")
    if request.get("source_root") != (
        f"abfss://{WORKSPACE}@onelake.dfs.fabric.microsoft.com/{LAKEHOUSE}/Files/aiops"
    ):
        raise ValueError("Caller requires the existing combined source root")
    for name in ("consumption_evidence", "product_authority_evidence"):
        path = request.get(name, "")
        if (
            not isinstance(path, str) or not path.startswith(_EVIDENCE_PREFIX)
            or not path.endswith(".json")
            or any(part in {"", ".", ".."} for part in path.split("/"))
        ):
            raise ValueError("Caller evidence must be in the reviewed validation root")
        if not re.fullmatch(r"[0-9a-f]{64}", str(request.get(name + "_hash", ""))):
            raise ValueError("Caller requires exact reviewed evidence hashes")
    if request.get("authority_mode") != "completed_ingestion":
        raise ValueError("Version-pinned maintenance products require a different publication plan")


def validate_identity_token(token: str, request: Mapping[str, Any]) -> None:
    """Check claims of the SDK-obtained MI token without persisting its secret."""
    # This is not JWT authentication: Azure Identity obtained the token from MI.
    # Claims are a fail-closed check against the reviewed workload identity.
    encoded = token.split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    if (
        claims.get("tid") != TENANT
        or claims.get("oid") != request["publisher_object_id"]
        or (claims.get("appid") or claims.get("azp")) != request["publisher_client_id"]
        or claims.get("aud") not in (
            "https://storage.azure.com", "https://storage.azure.com/",
        )
    ):
        raise ValueError("Managed identity token does not match reviewed publisher")


class ExposureMigrationAuthorityObserver:
    """Re-read source, completed products, native binding and consumption evidence.

    No definition preview or GET-derived annotation is treated as consumption.
    The approved evidence must contain actual differing native-query observations
    matched to retained historical Delta content under the SAME definition.
    """

    def __init__(
        self, *, request: Mapping[str, Any], documents: ReadOnlyLakeDocuments,
        manager: OntologyManager, onelake: OneLakeWriter, delta: DeltaWriter,
    ) -> None:
        self.request = request
        self.plan = ExposureScalarMigrationPlan(**request["plan"])
        self.documents = documents
        self.manager = manager
        self.onelake = onelake
        self.delta = delta

    def __call__(self) -> str:
        """Return current authority fingerprint, or reject unqualified observations."""
        pointer = self.documents.read(SOURCE_POINTER)
        generation = pointer["payload"].get("generation")
        if not isinstance(generation, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", generation):
            raise ValueError("Combined source pointer has no safe generation")
        manifest_path = f"Files/aiops/generations/{generation}/manifest.json"
        manifest = self.documents.read(manifest_path)
        if (
            manifest["payload"].get("runId") != generation
            or manifest["payload"].get("status") != "completed"
            or manifest["payload"].get("queryVersion") != "combined-subscription-connections-v1"
        ):
            raise ValueError("Combined source is not a completed activation")
        marker_uri = self.onelake.table_uri("metadata", "ingestion_state")
        marker_version = self.delta.version(marker_uri)
        if marker_version is None:
            raise ValueError("Completed product marker missing")
        markers = self.delta.read(marker_uri, version=marker_version)
        completed = [
            row for row in markers if row.get("status") == "completed"
            and row.get("ontology_entity_version") is not None
            and row.get("ontology_relationship_version") is not None
        ]
        if not completed:
            raise ValueError("Completed canonical product authority missing")
        marker = max(completed, key=lambda row: str(row.get("timestamp") or ""))
        if (
            marker.get("failed_records") != 0
            or marker.get("source_run_id") != generation
            or marker.get("ontology_entity_version") != self.plan.canonical_version
            or self.delta.version(self.onelake.table_uri("ontology", "entities"))
            != self.plan.canonical_version
            or self.delta.version(self.onelake.table_uri("ontology", "relationships"))
            != marker["ontology_relationship_version"]
        ):
            raise ValueError("Completed product authority disagrees with pinned source")
        catalog = self.documents.read(CATALOG)
        products = self._evidence("product_authority_evidence")
        # This is an independently reviewed inventory of authority readers, not
        # an inference from absence of a receipt on the mutable Lakehouse.
        expected_products = {
            "authority_mode": "completed_ingestion",
            "workspace_id": WORKSPACE, "lakehouse_id": LAKEHOUSE,
            "table": TABLE, "source_generation": generation,
            "canonical_version": self.plan.canonical_version,
            "source_manifest_hash": document_hash(manifest["payload"]),
            "catalog_hash": document_hash(catalog["payload"]),
            "immutable_product_consumers": [],
        }
        if products["payload"] != expected_products:
            raise ValueError("Product authority evidence is missing, changed or version-pinned")
        definition = self.manager.get_definition(NATIVE_ITEM)
        definition_digest = document_hash(definition)
        self._binding(definition)
        consumption = self._evidence("consumption_evidence")
        self._consumption(consumption["payload"], definition_digest)
        if (
            self.documents.read(SOURCE_POINTER) != pointer
            or self.documents.read(manifest_path) != manifest
            or self.documents.read(CATALOG) != catalog
            or self._evidence("product_authority_evidence") != products
            or self._evidence("consumption_evidence") != consumption
            or document_hash(self.manager.get_definition(NATIVE_ITEM)) != definition_digest
            or self.delta.version(marker_uri) != marker_version
            or self.delta.version(self.onelake.table_uri("ontology", "entities"))
            != self.plan.canonical_version
            or self.delta.version(self.onelake.table_uri("ontology", "relationships"))
            != marker["ontology_relationship_version"]
        ):
            raise RuntimeError("Source/product authority changed during observation")
        return document_hash({
            "target": (WORKSPACE, LAKEHOUSE, NATIVE_ITEM, TABLE),
            "pointer": pointer, "manifest": manifest,
            "marker_version": marker_version, "marker": marker,
            "catalog": catalog, "products": products,
            "definition_hash": definition_digest, "consumption": consumption,
        })

    def _evidence(self, name: str) -> dict[str, Any]:
        result = self.documents.read(self.request[name])
        if document_hash(result["payload"]) != self.request[name + "_hash"]:
            raise ValueError("Reviewed authority evidence changed")
        return result

    @staticmethod
    def _binding(definition: dict[str, Any]) -> None:
        parts = {}
        for part in definition.get("parts", []):
            if part.get("payloadType") != "InlineBase64" or part["path"] in parts:
                raise ValueError("Native definition has unsupported or duplicate parts")
            parts[part["path"]] = base64.b64decode(
                part["payload"], validate=True,
            ).decode("utf-8")
        table = parts.get(f"tables/{TABLE}.tmdl", "")
        expressions = parts.get("expressions.tmdl", "")
        entity = parts.get("entities/ContainerImageExposure.tmdl", "")
        for text in (
            f"partition {TABLE} = entity", "mode: directLake",
            f"entityName: {TABLE}", "expressionSource: DirectLakeSource",
            f"annotation ONT_WorkspaceId = {WORKSPACE}",
            f"annotation ONT_ItemId = {LAKEHOUSE}", "annotation ONT_ItemKind = Lakehouse",
        ):
            if text not in table:
                raise ValueError("Native binding differs from existing reviewed table")
        if (
            f"backingTable: {TABLE}" not in entity
            or f'AzureStorage.DataLake("https://onelake.dfs.pbidedicated.windows.net/{WORKSPACE}/{LAKEHOUSE}"'
            not in expressions
        ):
            raise ValueError("Native source root or entity binding changed")

    def _consumption(self, evidence: Mapping[str, Any], definition_hash: str) -> None:
        if (
            evidence.get("kind") != "native-query-delta-head-observations/v1"
            or evidence.get("workspace_id") != WORKSPACE
            or evidence.get("lakehouse_id") != LAKEHOUSE
            or evidence.get("item_id") != NATIVE_ITEM
            or evidence.get("table") != TABLE
            or evidence.get("definition_hash") != definition_hash
        ):
            raise ValueError("Native mutable-head consumption evidence unqualified")
        observations = evidence.get("observations")
        if not isinstance(observations, list) or len(observations) != 2:
            raise ValueError("Native consumption requires two actual differing head observations")
        hashes = []
        versions = []
        uri = self.onelake.table_uri("ontology", "container_image_exposure_entities")
        for observation in observations:
            version = observation["delta_version"]
            if isinstance(version, bool) or not isinstance(version, int) or version < 0:
                raise ValueError("Consumption observation requires a pinned Delta version")
            rows = observation["native_rows"]
            if (
                observation.get("status") != "succeeded"
                or observation.get("reader") != "native_ontology_agent"
                or not observation.get("request_id") or not observation.get("observed_at")
                or observation.get("query_contract") != "all-active-exposure-keys-no-version-filter/v1"
                or not isinstance(rows, list)
                or any(set(row) != set(_OBSERVATION_COLUMNS) for row in rows)
            ):
                raise ValueError("Native query observation incomplete")
            actual = self.delta.read(
                uri, version=version, columns=(*_OBSERVATION_COLUMNS, "lifecycle_status"),
            )
            actual = [
                {column: row[column] for column in _OBSERVATION_COLUMNS}
                for row in actual if row["lifecycle_status"] == "active"
            ]
            if migration_rows_hash(rows) != migration_rows_hash(actual):
                raise ValueError("Native rows disagree with retained Delta version")
            hashes.append(migration_rows_hash(rows))
            versions.append(version)
        if (
            versions[0] >= versions[1] or versions[1] != self.plan.target_version
            or hashes[0] == hashes[1]
        ):
            raise ValueError("Native mutable-head consumption not established by differing observations")


def run_caller(
    request: Mapping[str, Any], *, observer: ExposureMigrationAuthorityObserver,
    onelake: OneLakeWriter, delta: DeltaWriter, execute: bool = False,
) -> dict[str, Any]:
    """Inspect read-only by default; execute only through the reviewed composition."""
    observed = observer()
    if observed != request["plan"]["authority_fingerprint"]:
        raise RuntimeError("Current authority differs from reviewed migration plan")
    if not execute:
        return {"status": "inspected", "authority_fingerprint": observed, "mutated": False}
    return migrate_exposure_scalars(
        onelake, delta, ExposureScalarMigrationPlan(**request["plan"]),
        observe_authority=observer,
    )


def main(argv: list[str] | None = None) -> int:
    """Run the explicitly packaged module; no production execution is implicit."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True)
    parser.add_argument("--request-sha256", required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    raw = Path(args.request).read_bytes()
    if hashlib.sha256(raw).hexdigest() != args.request_sha256:
        raise ValueError("Reviewed migration request bytes changed")
    request = json.loads(raw)
    validate_request(request, os.environ)
    with ManagedIdentityCredential(client_id=request["publisher_client_id"]) as credential:
        validate_identity_token(
            credential.get_token("https://storage.azure.com/.default").token, request,
        )
        with DataLakeServiceClient(
            OneLakeWriter.ENDPOINT, credential=credential,
        ) as service:
            onelake = OneLakeWriter(
                WORKSPACE, LAKEHOUSE, credential=credential, service_client=service,
            )
            delta = DeltaWriter(
                max_attempts=1,
                storage_options_provider=lambda: build_delta_storage_options(credential),
            )
            with httpx.Client(
                timeout=60, headers={"x-ms-fabric-skill": "fabriciq-ontology-cli"},
            ) as http:
                manager = OntologyManager(
                    FabricClient(credential, http_client=http, max_attempts=1), WORKSPACE,
                )
                observer = ExposureMigrationAuthorityObserver(
                    request=request,
                    documents=ReadOnlyLakeDocuments(service.get_file_system_client(WORKSPACE)),
                    manager=manager, onelake=onelake, delta=delta,
                )
                result = run_caller(
                    request, observer=observer, onelake=onelake, delta=delta,
                    execute=args.execute,
                )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
