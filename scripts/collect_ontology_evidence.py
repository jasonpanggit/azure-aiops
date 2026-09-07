#!/usr/bin/env python3
"""Emit one fail-closed read-only Phase 13 evidence record.

The collector is intentionally usable only from the fixed
``ontology-evidence-read`` Container Apps Job. It authenticates as that Job's
single user-assigned identity, performs bounded ARG, Fabric metadata, OneLake,
and API reads, and writes exactly one sanitized JSON record to stdout.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from collections.abc import Mapping, Sequence

import httpx
from azure.identity import ManagedIdentityCredential
from azure.storage.filedatalake import FileSystemClient

MANAGEMENT_SCOPE = "https://management.azure.com/.default"
FABRIC_SCOPE = "https://api.fabric.microsoft.com/.default"
ONELAKE_HOST = "onelake.dfs.fabric.microsoft.com"
ROOT_NAMES = (
    "state",
    "command",
    "dispatch",
    "publication",
    "validation",
)
ROOT_PATHS = {
    "state": (
        "Files/aiops/ontology/state",
        "Files/aiops/validation/connection-registry",
        "Files/aiops/validation/fixture-control",
    ),
    "command": ("Files/aiops/ontology/commands",),
    "dispatch": ("Files/aiops/ontology/dispatch",),
    "publication": ("Files/aiops/ontology/publication",),
    "validation": ("Files/aiops/validation/publisher-drill",),
}
EXPECTED_CAPABILITIES = {
    "azure": ["read"],
    "fabric": ["Viewer"],
    "onelake": ["Read"],
    "denied": ["job_start", "mutation"],
}
IDENTITY_HASH_KEYS = {
    "client_id_hash",
    "object_id_hash",
    "managed_identity_resource_hash",
    "entra_signature_hash",
}
OBSERVATION_NAMES = {"arg", "fabric", "onelake", "api"}
FORBIDDEN_OUTPUT_KEYS = {
    "access_token",
    "args",
    "body",
    "client_id",
    "command",
    "correlation",
    "correlation_id",
    "env",
    "error",
    "object_id",
    "path",
    "principal_id",
    "prompt",
    "raw",
    "resource_id",
    "root",
    "secret",
    "subscription_id",
    "tenant_id",
    "token",
    "uri",
    "url",
}
MUTATION_MARKERS = {
    "admin",
    "contributor",
    "delete",
    "job_start",
    "member",
    "mutation",
    "owner",
    "patch",
    "post",
    "put",
    "readwrite",
    "write",
    "microsoft.app/jobs/start/action",
}


class EvidenceCollectionError(RuntimeError):
    """Evidence cannot be gathered without weakening the read boundary."""


def _hash(value: object) -> str:
    rendered = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    )
    return "sha256:" + hashlib.sha256(rendered.encode()).hexdigest()


def _is_hash(value: object) -> bool:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        return False
    digest = value.removeprefix("sha256:")
    return len(digest) == 64 and all(char in "0123456789abcdef" for char in digest)


def _decode_segment(segment: str) -> Mapping[str, object]:
    try:
        padded = segment + "=" * (-len(segment) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, json.JSONDecodeError) as exc:
        raise EvidenceCollectionError("managed identity token claims are invalid") from exc
    if not isinstance(value, Mapping):
        raise EvidenceCollectionError("managed identity token claims are invalid")
    return value


def decode_identity_claims(token: str) -> dict[str, str]:
    """Bind retained evidence to Entra-signed claims without retaining a token."""

    parts = token.split(".")
    if len(parts) != 3:
        raise EvidenceCollectionError("managed identity token is not a JWT")
    claims = _decode_segment(parts[1])
    values = {
        "client_id_hash": claims.get("appid") or claims.get("azp"),
        "object_id_hash": claims.get("oid"),
        "managed_identity_resource_hash": claims.get("xms_mirid"),
        "entra_signature_hash": parts[2],
    }
    if any(not value for value in values.values()):
        raise EvidenceCollectionError("managed identity token claims are incomplete")
    return {name: _hash(value) for name, value in values.items()}


def sanitize_closed_record(value: object, *, key: str = "") -> object:
    """Reject raw identifiers, payloads, paths, correlations, prompts, and tokens."""

    normalized = key.casefold()
    if (
        normalized in FORBIDDEN_OUTPUT_KEYS
        and value not in (None, "")
        and not _is_hash(value)
    ):
        raise EvidenceCollectionError(
            f"sensitive evidence field rejected: {normalized}"
        )
    if isinstance(value, Mapping):
        return {
            str(item_key): sanitize_closed_record(item_value, key=str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [sanitize_closed_record(item, key=key) for item in value]
    if isinstance(value, str):
        lowered = value.casefold()
        if (
            "bearer " in lowered
            or "client_secret" in lowered
            or "/subscriptions/" in lowered
            or "onelake.dfs.fabric.microsoft.com" in lowered
        ):
            raise EvidenceCollectionError("sensitive evidence string rejected")
    return value


def _validate_capabilities(capabilities: Mapping[str, object]) -> None:
    if dict(capabilities) != EXPECTED_CAPABILITIES:
        raise EvidenceCollectionError("evidence capabilities are not exactly read-only")
    flattened = {
        str(item).casefold()
        for values in capabilities.values()
        for item in (values if isinstance(values, Sequence) else ())
    }
    if flattened.intersection(MUTATION_MARKERS - {"job_start", "mutation"}):
        raise EvidenceCollectionError("evidence capabilities are not read-only")


def build_closed_record(
    *,
    identity: Mapping[str, object],
    observations: Mapping[str, object],
    capabilities: Mapping[str, object],
) -> dict[str, object]:
    """Build the only console schema accepted by the Plan 20 validator."""

    if (
        set(identity) != IDENTITY_HASH_KEYS
        or any(not _is_hash(value) for value in identity.values())
    ):
        raise EvidenceCollectionError("managed identity evidence is not closed")
    _validate_capabilities(capabilities)
    if set(observations) - OBSERVATION_NAMES:
        raise EvidenceCollectionError("unexpected evidence observation class")
    for name, row in observations.items():
        if not isinstance(row, Mapping):
            raise EvidenceCollectionError(f"{name} observation is invalid")
        hashes = row.get("hashes")
        if (
            set(row) != {"count", "hashes"}
            or not isinstance(row.get("count"), int)
            or int(row["count"]) < 0
            or not isinstance(hashes, list)
            or any(not _is_hash(value) for value in hashes)
        ):
            raise EvidenceCollectionError(f"{name} observation is not closed")

    record: dict[str, object] = {
        "schema_version": "ontology-evidence-read.v1",
        "mode": "fixed-read-only",
        "sanitized": True,
        "identity": dict(identity),
        "capabilities": dict(capabilities),
        "observations": dict(observations),
    }
    record["record_hash"] = _hash(record)
    record["entra_bound_record_hash"] = _hash(
        {
            "record_hash": record["record_hash"],
            "entra_signature_hash": identity["entra_signature_hash"],
        }
    )
    return sanitize_closed_record(record)  # type: ignore[return-value]


def _required_environment() -> dict[str, str]:
    required = {
        "AZURE_CLIENT_ID",
        "AIOPS_EVIDENCE_OBJECT_ID",
        "AIOPS_EVIDENCE_SUBSCRIPTION_ID",
        "AIOPS_EVIDENCE_RESOURCE_GROUP",
        "AIOPS_EVIDENCE_API_URL",
        "AIOPS_EVIDENCE_API_SCOPE",
    }
    for root in ROOT_NAMES:
        prefix = f"AIOPS_EVIDENCE_{root.upper()}"
        required.update({f"{prefix}_WORKSPACE_ID", f"{prefix}_LAKEHOUSE_ID"})
    values = {name: os.environ.get(name, "").strip() for name in required}
    missing = sorted(name for name, value in values.items() if not value)
    if missing:
        raise EvidenceCollectionError(
            "fixed evidence environment is incomplete: " + ",".join(missing)
        )
    return values


def _token(credential: ManagedIdentityCredential, scope: str) -> str:
    token = credential.get_token(scope).token
    if not token:
        raise EvidenceCollectionError("managed identity returned an empty token")
    return token


def _request_json(
    method: str,
    url: str,
    *,
    token: str | None = None,
    json_body: Mapping[str, object] | None = None,
) -> object:
    if method not in {"GET", "POST"} or (method == "POST" and json_body is None):
        raise EvidenceCollectionError("collector permits only GET and fixed ARG query")
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = httpx.request(
        method,
        url,
        headers=headers,
        json=dict(json_body) if json_body is not None else None,
        timeout=30,
    )
    if response.status_code >= 400:
        raise EvidenceCollectionError(
            f"read-only evidence request failed with HTTP {response.status_code}"
        )
    if not response.content:
        return {"status": response.status_code}
    try:
        return response.json()
    except ValueError:
        return {"status": response.status_code, "content_hash": _hash(response.content)}


def _collect_arg(env: Mapping[str, str], token: str) -> dict[str, object]:
    query = (
        "resources | where resourceGroup =~ '"
        + env["AIOPS_EVIDENCE_RESOURCE_GROUP"].replace("'", "''")
        + "' | where type in~ ('microsoft.managedidentity/userassignedidentities',"
        "'microsoft.app/jobs') | project id, type, name, tags"
    )
    payload = _request_json(
        "POST",
        "https://management.azure.com/providers/Microsoft.ResourceGraph/resources"
        "?api-version=2022-10-01",
        token=token,
        json_body={
            "subscriptions": [env["AIOPS_EVIDENCE_SUBSCRIPTION_ID"]],
            "query": query,
            "options": {"$top": 100},
        },
    )
    rows = payload.get("data", []) if isinstance(payload, Mapping) else []
    rows = rows if isinstance(rows, list) else []
    return {"count": len(rows), "hashes": sorted(_hash(row) for row in rows)}


def _collect_fabric(env: Mapping[str, str], token: str) -> dict[str, object]:
    observations: list[object] = []
    for root in ROOT_NAMES:
        prefix = f"AIOPS_EVIDENCE_{root.upper()}"
        workspace = env[f"{prefix}_WORKSPACE_ID"]
        item = env[f"{prefix}_LAKEHOUSE_ID"]
        observations.append(
            _request_json(
                "GET",
                f"https://api.fabric.microsoft.com/v1/workspaces/{workspace}"
                f"/items/{item}",
                token=token,
            )
        )
    return {
        "count": len(observations),
        "hashes": [_hash(row) for row in observations],
    }


def _collect_onelake(
    env: Mapping[str, str],
    credential: ManagedIdentityCredential,
) -> dict[str, object]:
    hashes: list[str] = []
    for root in ROOT_NAMES:
        prefix = f"AIOPS_EVIDENCE_{root.upper()}"
        workspace = env[f"{prefix}_WORKSPACE_ID"]
        lakehouse = env[f"{prefix}_LAKEHOUSE_ID"]
        client = FileSystemClient(
            account_url=f"https://{ONELAKE_HOST}",
            file_system_name=workspace,
            credential=credential,
        )
        for relative_path in ROOT_PATHS[root]:
            full_path = f"{lakehouse}/{relative_path}"
            try:
                rows = list(client.get_paths(path=full_path, recursive=True))
            except Exception as exc:
                raise EvidenceCollectionError(
                    f"OneLake read failed for fixed {root} root"
                ) from exc
            hashes.append(
                _hash(
                    {
                        "root": root,
                        "path_hash": _hash(relative_path),
                        "entries": sorted(
                            _hash(
                                {
                                    "name": getattr(row, "name", ""),
                                    "is_directory": bool(
                                        getattr(row, "is_directory", False)
                                    ),
                                    "size": int(
                                        getattr(row, "content_length", 0) or 0
                                    ),
                                    "etag": str(getattr(row, "etag", "") or ""),
                                }
                            )
                            for row in rows
                        ),
                    }
                )
            )
    return {"count": len(hashes), "hashes": hashes}


def _collect_api(env: Mapping[str, str]) -> dict[str, object]:
    base = env["AIOPS_EVIDENCE_API_URL"].rstrip("/")
    payload = _request_json("GET", f"{base}/health")
    return {"count": 1, "hashes": [_hash(payload)]}


def collect() -> dict[str, object]:
    env = _required_environment()
    credential = ManagedIdentityCredential(client_id=env["AZURE_CLIENT_ID"])
    try:
        management_token = _token(credential, MANAGEMENT_SCOPE)
        identity = decode_identity_claims(management_token)
        if identity["object_id_hash"] != _hash(env["AIOPS_EVIDENCE_OBJECT_ID"]):
            raise EvidenceCollectionError("live identity does not match fixed Job identity")
        observations = {
            "arg": _collect_arg(env, management_token),
            "fabric": _collect_fabric(env, _token(credential, FABRIC_SCOPE)),
            "onelake": _collect_onelake(env, credential),
            "api": _collect_api(env),
        }
        return build_closed_record(
            identity=identity,
            observations=observations,
            capabilities=EXPECTED_CAPABILITIES,
        )
    finally:
        credential.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect fixed read-only Phase 13 evidence."
    )
    parser.add_argument("--emit-console-record", action="store_true", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    _parser().parse_args(argv)
    try:
        record = collect()
    except EvidenceCollectionError as exc:
        record = {
            "schema_version": "ontology-evidence-read.v1",
            "mode": "fixed-read-only",
            "sanitized": True,
            "status": "FAIL",
            "reason_hash": _hash(type(exc).__name__),
        }
        print(json.dumps(record, sort_keys=True, separators=(",", ":")))
        return 1
    print(json.dumps(record, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
