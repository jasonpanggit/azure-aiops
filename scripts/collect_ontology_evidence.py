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
from datetime import datetime

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
FAILURE_CODES = frozenset(
    {
        "identity_binding",
        "arg_read",
        "fabric_read",
        "onelake_read",
        "api_read",
    }
)
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
    facts: Mapping[str, object] | None = None,
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
    if facts is not None:
        sanitized_facts = sanitize_closed_record(facts)
        if not isinstance(sanitized_facts, Mapping):
            raise EvidenceCollectionError("lifecycle facts are not closed")
        record["facts"] = dict(sanitized_facts)
    record["record_hash"] = _hash(record)
    record["entra_bound_record_hash"] = _hash(
        {
            "record_hash": record["record_hash"],
            "entra_signature_hash": identity["entra_signature_hash"],
        }
    )
    return sanitize_closed_record(record)  # type: ignore[return-value]


def _closed_hash(value: object) -> str:
    return _hash(value) if value not in (None, "") else ""


def summarize_lifecycle_documents(
    *,
    fixture: Mapping[str, object],
    registry: Mapping[str, object],
    state: Mapping[str, object],
) -> dict[str, object]:
    """Reduce durable lifecycle documents without retaining raw identifiers."""

    drills_value = fixture.get("drills")
    drills = (
        [row for row in drills_value if isinstance(row, Mapping)]
        if isinstance(drills_value, list)
        else []
    )
    active = [row for row in drills if row.get("status") == "prepared"]
    latest = drills[-1] if drills else {}
    connection_ids = latest.get("connection_ids")
    connection_ids = (
        [str(value) for value in connection_ids]
        if isinstance(connection_ids, list)
        else []
    )
    receipts_value = latest.get("receipts")
    receipts = (
        [row for row in receipts_value if isinstance(row, Mapping)]
        if isinstance(receipts_value, list)
        else []
    )
    receipt_events = [
        str(row.get("event") or "")
        for row in receipts
        if str(row.get("event") or "") in {"prepared", "cleaned", "swept"}
    ]
    ttl_bounded = False
    try:
        prepared_at = datetime.fromisoformat(str(latest.get("prepared_at")))
        expires_at = datetime.fromisoformat(str(latest.get("expires_at")))
        ttl_seconds = (expires_at - prepared_at).total_seconds()
        ttl_bounded = 0 < ttl_seconds <= 7200
    except (TypeError, ValueError):
        pass

    registry_rows_value = registry.get("connections")
    registry_rows = (
        [row for row in registry_rows_value if isinstance(row, Mapping)]
        if isinstance(registry_rows_value, list)
        else []
    )
    fixture_connections = [
        row
        for row in registry_rows
        if str(row.get("connection_id") or "").startswith("ontology-fixture-")
    ]

    epochs_value = state.get("eligible_epochs")
    epochs = (
        [row for row in epochs_value if isinstance(row, Mapping)]
        if isinstance(epochs_value, list)
        else []
    )
    active_epochs = [row for row in epochs if row.get("status") == "active"]
    latest_epoch = epochs[-1] if epochs else {}
    members_value = latest_epoch.get("members")
    members = members_value if isinstance(members_value, Mapping) else {}
    member_rows: list[dict[str, object]] = []
    order_value = latest_epoch.get("member_order")
    order = (
        [str(value) for value in order_value]
        if isinstance(order_value, list)
        else sorted(str(value) for value in members)
    )
    for member_id in order:
        row = members.get(member_id)
        row = row if isinstance(row, Mapping) else {}
        outcome = str(row.get("outcome") or "")
        reason = str(row.get("reason_code") or "")
        if outcome not in {
            "pending",
            "succeeded",
            "duplicate",
            "exhausted_failure",
            "excluded",
        }:
            outcome = "unknown"
        member_rows.append(
            {
                "record_hash": _hash(member_id),
                "outcome": outcome,
                "attempt_count": int(row.get("attempt_count") or 0),
                "reason_hash": _closed_hash(reason),
                "updated_at_hash": _closed_hash(row.get("updated_at")),
            }
        )

    return {
        "fixture": {
            "drill_count": len(drills),
            "active_drill_count": len(active),
            "status": str(latest.get("status") or "absent"),
            "drill_hash": _closed_hash(latest.get("drill_hash")),
            "owner_hash": _closed_hash(latest.get("owner_hash")),
            "fence_hash": _closed_hash(latest.get("fence")),
            "epoch_hash": _closed_hash(latest.get("epoch_id")),
            "record_count": len(connection_ids),
            "record_hashes": [_hash(value) for value in connection_ids],
            "ttl_bounded": ttl_bounded,
            "receipt_events": receipt_events,
        },
        "registry": {
            "revision": int(registry.get("revision") or 0),
            "active_fixture_count": len(fixture_connections),
            "fixture_record_hashes": [
                _hash(row.get("connection_id")) for row in fixture_connections
            ],
        },
        "epoch": {
            "active_epoch_count": len(active_epochs),
            "epoch_hash": _closed_hash(latest_epoch.get("epoch_id")),
            "status": str(latest_epoch.get("status") or "absent"),
            "cursor": int(latest_epoch.get("cursor") or 0),
            "revision": int(latest_epoch.get("revision") or 0),
            "member_count": len(members),
            "members": member_rows,
        },
    }


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
    is_arg_query = (
        method == "POST"
        and url.startswith(
            "https://management.azure.com/providers/"
            "Microsoft.ResourceGraph/resources?"
        )
        and json_body is not None
    )
    if method != "GET" and not is_arg_query:
        raise EvidenceCollectionError("collector permits only GET and fixed ARG query")
    if not url.startswith("https://"):
        raise EvidenceCollectionError("collector permits only HTTPS reads")
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


def _read_json_document(
    client: FileSystemClient,
    path: str,
) -> Mapping[str, object]:
    """Read one bounded JSON document without exposing its body."""

    try:
        body = client.get_file_client(path).download_file().readall()
    except Exception as exc:
        status_code = getattr(exc, "status_code", None)
        if status_code == 404:
            return {}
        raise EvidenceCollectionError("fixed OneLake document read failed") from exc
    if len(body) > 2_000_000:
        raise EvidenceCollectionError("fixed OneLake document exceeds evidence bound")
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceCollectionError("fixed OneLake document is not JSON") from exc
    if not isinstance(payload, Mapping):
        raise EvidenceCollectionError("fixed OneLake document is not an object")
    return payload


def _collect_onelake(
    env: Mapping[str, str],
    credential: ManagedIdentityCredential,
) -> tuple[dict[str, object], dict[str, object]]:
    hashes: list[str] = []
    clients: dict[str, FileSystemClient] = {}
    for root in ROOT_NAMES:
        prefix = f"AIOPS_EVIDENCE_{root.upper()}"
        workspace = env[f"{prefix}_WORKSPACE_ID"]
        lakehouse = env[f"{prefix}_LAKEHOUSE_ID"]
        client = FileSystemClient(
            account_url=f"https://{ONELAKE_HOST}",
            file_system_name=workspace,
            credential=credential,
        )
        clients[root] = client
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
    state_lakehouse = env["AIOPS_EVIDENCE_STATE_LAKEHOUSE_ID"]
    fixture = _read_json_document(
        clients["state"],
        f"{state_lakehouse}/Files/aiops/validation/fixture-control/"
        "ontology/validation-fixtures.json",
    )
    registry = _read_json_document(
        clients["state"],
        f"{state_lakehouse}/Files/aiops/validation/connection-registry/"
        "state/subscription_connections.json",
    )
    state = _read_json_document(
        clients["state"],
        f"{state_lakehouse}/Files/aiops/ontology/state/"
        "ontology/coordinator-state.json",
    )
    facts = summarize_lifecycle_documents(
        fixture=fixture,
        registry=registry,
        state=state,
    )
    return {"count": len(hashes), "hashes": hashes}, facts


def _collect_api(
    env: Mapping[str, str],
    token: str,
) -> dict[str, object]:
    base = env["AIOPS_EVIDENCE_API_URL"].rstrip("/")
    payload = _request_json(
        "GET",
        f"{base}/api/v1/connections?limit=1",
        token=token,
    )
    return {"count": 1, "hashes": [_hash(payload)]}


def collect() -> dict[str, object]:
    env = _required_environment()
    credential = ManagedIdentityCredential(client_id=env["AZURE_CLIENT_ID"])
    try:
        management_token = _token(credential, MANAGEMENT_SCOPE)
        identity = decode_identity_claims(management_token)
        if identity["object_id_hash"] != _hash(env["AIOPS_EVIDENCE_OBJECT_ID"]):
            raise EvidenceCollectionError("identity_binding")
        try:
            onelake_observation, facts = _collect_onelake(env, credential)
        except EvidenceCollectionError as exc:
            raise EvidenceCollectionError("onelake_read") from exc
        try:
            arg_observation = _collect_arg(env, management_token)
        except EvidenceCollectionError as exc:
            raise EvidenceCollectionError("arg_read") from exc
        try:
            fabric_observation = _collect_fabric(
                env,
                _token(credential, FABRIC_SCOPE),
            )
        except EvidenceCollectionError as exc:
            raise EvidenceCollectionError("fabric_read") from exc
        try:
            api_observation = _collect_api(
                env,
                _token(credential, env["AIOPS_EVIDENCE_API_SCOPE"]),
            )
        except EvidenceCollectionError as exc:
            raise EvidenceCollectionError("api_read") from exc
        observations = {
            "arg": arg_observation,
            "fabric": fabric_observation,
            "onelake": onelake_observation,
            "api": api_observation,
        }
        return build_closed_record(
            identity=identity,
            observations=observations,
            capabilities=EXPECTED_CAPABILITIES,
            facts=facts,
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
        reason_code = (
            str(exc)
            if str(exc) in FAILURE_CODES
            else "evidence_contract"
        )
        record = {
            "schema_version": "ontology-evidence-read.v1",
            "mode": "fixed-read-only",
            "sanitized": True,
            "status": "FAIL",
            "reason_code": reason_code,
            "reason_hash": _hash(
                {"type": type(exc).__name__, "code": reason_code}
            ),
        }
        print(json.dumps(record, sort_keys=True, separators=(",", ":")))
        return 1
    print(json.dumps(record, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
