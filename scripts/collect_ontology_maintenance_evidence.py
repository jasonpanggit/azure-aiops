#!/usr/bin/env python3
"""Collect sanitized direct evidence for one ontology maintenance command.

The connection identifier is read from a bounded JSON document on stdin so it
does not appear in the process list.  The maintenance token is acquired from a
deployment-principal Azure CLI home, while the optional general-operator token
is accepted only from the environment.  This script never starts coordinator
or publisher jobs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, TextIO

GENERAL_OPERATOR_TOKEN_ENV = "AIOPS_ONTOLOGY_GENERAL_OPERATOR_TOKEN"
MAINTENANCE_REASON = "phase-13-plan-20-direct-maintenance-evidence"
MAINTENANCE_CADENCE_SECONDS = 3600
ACCEPTED_MAINTENANCE_STATUSES = frozenset({200, 201, 202})
MAX_CONTRACT_BYTES = 16_384
MAX_RESPONSE_BYTES = 1_000_000
REQUEST_TIMEOUT_SECONDS = 30
TOKEN_TIMEOUT_SECONDS = 30
MAX_REVISION = 2_147_483_647
COMMAND_TYPE = "mark_full_reconciliation_due"
COMMAND_STATUS_VALUES = frozenset({"pending", "claimed", "completed"})


class EvidenceCollectionError(RuntimeError):
    """A closed, non-sensitive failure status."""


@dataclass(frozen=True)
class CollectionConfig:
    api_url: str
    api_audience: str
    azure_config_dir: Path
    output_path: Path


@dataclass(frozen=True)
class HttpResult:
    status: int
    body: bytes = b""


class HttpTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        token: str,
        body: bytes | None = None,
    ) -> HttpResult: ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Prevent bearer credentials from crossing an HTTP redirect."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


class UrllibTransport:
    """Bounded HTTPS transport that returns bodies only to in-memory validators."""

    def __init__(self) -> None:
        self._opener = urllib.request.build_opener(_NoRedirect)

    def request(
        self,
        method: str,
        url: str,
        *,
        token: str,
        body: bytes | None = None,
    ) -> HttpResult:
        if urllib.parse.urlsplit(url).scheme != "https":
            raise EvidenceCollectionError("api_url_not_https")
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            url,
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with self._opener.open(
                request,
                timeout=REQUEST_TIMEOUT_SECONDS,
            ) as response:
                return HttpResult(
                    status=int(response.status),
                    body=_bounded_response(response.read(MAX_RESPONSE_BYTES + 1)),
                )
        except urllib.error.HTTPError as exc:
            try:
                response_body = _bounded_response(exc.read(MAX_RESPONSE_BYTES + 1))
            except (OSError, ValueError) as read_error:
                raise EvidenceCollectionError(
                    "api_response_unavailable"
                ) from read_error
            return HttpResult(status=int(exc.code), body=response_body)
        except (OSError, TimeoutError, ValueError) as exc:
            raise EvidenceCollectionError("api_request_failed") from exc


def _bounded_response(body: bytes) -> bytes:
    if len(body) > MAX_RESPONSE_BYTES:
        raise EvidenceCollectionError("api_response_too_large")
    return body


def _hash(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalized_api_url(value: str) -> str:
    text = str(value or "").strip().rstrip("/")
    parsed = urllib.parse.urlsplit(text)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise EvidenceCollectionError("api_url_invalid")
    return text


def _validated_audience(value: str) -> str:
    audience = str(value or "").strip()
    if (
        not audience
        or len(audience) > 2_048
        or any(ord(character) < 0x20 for character in audience)
    ):
        raise EvidenceCollectionError("api_audience_invalid")
    return audience


def validate_azure_config_dir(path: Path) -> Path:
    """Require the deployment principal's existing mode-0700 CLI directory."""

    try:
        resolved = path.expanduser().resolve(strict=True)
        mode = stat.S_IMODE(resolved.stat().st_mode)
    except OSError as exc:
        raise EvidenceCollectionError("azure_config_dir_unavailable") from exc
    if not resolved.is_dir():
        raise EvidenceCollectionError("azure_config_dir_not_directory")
    if mode != 0o700:
        raise EvidenceCollectionError("azure_config_dir_not_private")
    return resolved


def load_contract(stream: TextIO) -> dict[str, object]:
    """Load the sole retained identifier from a bounded stdin JSON contract."""

    raw = stream.read(MAX_CONTRACT_BYTES + 1)
    if len(raw.encode("utf-8")) > MAX_CONTRACT_BYTES:
        raise EvidenceCollectionError("stdin_contract_too_large")
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise EvidenceCollectionError("stdin_contract_invalid") from exc
    if not isinstance(payload, dict) or not set(payload).issubset(
        {"connection_id", "general_operator_denial"}
    ) or "connection_id" not in payload:
        raise EvidenceCollectionError("stdin_contract_fields_invalid")
    connection_id = payload.get("connection_id")
    if (
        not isinstance(connection_id, str)
        or not connection_id.strip()
        or len(connection_id.strip()) > 160
        or any(ord(character) < 0x20 for character in connection_id)
    ):
        raise EvidenceCollectionError("connection_id_invalid")
    contract: dict[str, object] = {"connection_id": connection_id.strip()}
    if "general_operator_denial" in payload:
        contract["general_operator_denial"] = payload[
            "general_operator_denial"
        ]
    return contract


def _validated_denial_proof(value: object) -> bool:
    return (
        isinstance(value, Mapping)
        and value.get("source") == "authenticated_api"
        and value.get("general_operator_status") == 403
        and isinstance(value.get("identity_hash"), str)
        and str(value["identity_hash"]).startswith("sha256:")
        and len(str(value["identity_hash"])) == 71
    )


def _isolated_azure_environment(
    azure_config_dir: Path,
    env: Mapping[str, str],
) -> dict[str, str]:
    isolated = {
        key: value
        for key, value in env.items()
        if not key.startswith(("AZURE_", "ARM_")) and key != GENERAL_OPERATOR_TOKEN_ENV
    }
    isolated["AZURE_CONFIG_DIR"] = str(azure_config_dir)
    return isolated


def _acquire_maintenance_token(
    audience: str,
    azure_config_dir: Path,
    *,
    env: Mapping[str, str],
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> str:
    command = [
        "az",
        "account",
        "get-access-token",
        "--resource",
        audience,
        "--query",
        "accessToken",
        "--output",
        "tsv",
    ]
    try:
        result = runner(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=TOKEN_TIMEOUT_SECONDS,
            env=_isolated_azure_environment(azure_config_dir, env),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise EvidenceCollectionError("maintenance_token_acquisition_failed") from exc
    token = str(result.stdout or "").strip()
    if not token or any(character.isspace() for character in token):
        raise EvidenceCollectionError("maintenance_token_invalid")
    return token


def _json_object(result: HttpResult, failure_status: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(result.body)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise EvidenceCollectionError(failure_status) from exc
    if not isinstance(payload, Mapping):
        raise EvidenceCollectionError(failure_status)
    return payload


def _non_negative_revision(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        revision = value
    elif isinstance(value, str) and value.isascii() and value.isdigit():
        revision = int(value)
    else:
        return None
    return revision if 0 <= revision <= MAX_REVISION else None


def _status_revision(payload: Mapping[str, Any]) -> int | None:
    data = payload.get("data")
    if not isinstance(data, Mapping):
        return None
    candidate_paths = (
        ("reconciliation_control", "revision"),
        ("incremental", "reconciliation_control", "revision"),
        ("incremental", "control", "revision"),
    )
    for path in candidate_paths:
        value: object = data
        for key in path:
            value = value.get(key) if isinstance(value, Mapping) else None
        revision = _non_negative_revision(value)
        if revision is not None:
            return revision
    return None


def _conflict_revision(result: HttpResult) -> int:
    payload = _json_object(result, "maintenance_conflict_invalid")
    error = payload.get("error")
    if not isinstance(error, Mapping) or error.get("code") != "conflict":
        raise EvidenceCollectionError("maintenance_conflict_invalid")
    details = error.get("details")
    revision = (
        _non_negative_revision(details.get("current_revision"))
        if isinstance(details, Mapping)
        else None
    )
    if revision is None:
        raise EvidenceCollectionError("maintenance_conflict_revision_missing")
    return revision


def _authenticated_forbidden(result: HttpResult) -> bool:
    if result.status != 403:
        return False
    try:
        payload = _json_object(result, "general_operator_denial_unverified")
    except EvidenceCollectionError:
        return False
    error = payload.get("error")
    return isinstance(error, Mapping) and error.get("code") == "forbidden"


def _verify_command(
    result: HttpResult,
    *,
    connection_id: str,
) -> tuple[str, str]:
    if result.status not in ACCEPTED_MAINTENANCE_STATUSES:
        raise EvidenceCollectionError("maintenance_not_accepted")
    payload = _json_object(result, "maintenance_response_invalid")
    command = payload.get("data")
    if not isinstance(command, Mapping):
        raise EvidenceCollectionError("maintenance_command_missing")
    command_id = command.get("command_id")
    revision = _non_negative_revision(command.get("revision"))
    if (
        not isinstance(command_id, str)
        or not command_id.strip()
        or len(command_id) > 160
        or command.get("connection_id") != connection_id
        or command.get("type") != COMMAND_TYPE
        or command.get("status") not in COMMAND_STATUS_VALUES
        or revision is None
        or not str(command.get("created_at") or "").strip()
        or not str(command.get("updated_at") or "").strip()
    ):
        raise EvidenceCollectionError("maintenance_command_not_durable")
    return command_id, str(command["status"])


def _post_body(
    *,
    expected_revision: int,
    idempotency_key: str,
) -> bytes:
    return json.dumps(
        {
            "expected_revision": expected_revision,
            "reason": MAINTENANCE_REASON,
            "idempotency_key": idempotency_key,
            "cadence_seconds": MAINTENANCE_CADENCE_SECONDS,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _base_report(
    api_url: str,
    audience: str,
    connection_id: str,
) -> dict[str, object]:
    return {
        "schema_version": "phase13-plan20-maintenance-v1",
        "status": "FAIL",
        "target_hash": _hash(api_url),
        "audience_hash": _hash(audience),
        "connection_hash": _hash(connection_id),
        "azure_context_status": "not_checked",
        "ambient_credentials_status": "not_checked",
        "token_acquisition_status": "not_attempted",
        "general_operator_evidence": "unavailable",
        "request_count": 0,
        "coordinator_job_start_count": 0,
    }


def collect_evidence(
    config: CollectionConfig,
    contract: Mapping[str, object],
    *,
    env: Mapping[str, str] | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    transport: HttpTransport | None = None,
    nonce_factory: Callable[[], str] = lambda: secrets.token_hex(12),
) -> dict[str, object]:
    """Collect direct API evidence without retaining sensitive request values."""

    environment = dict(os.environ if env is None else env)
    api_url = _normalized_api_url(config.api_url)
    audience = _validated_audience(config.api_audience)
    connection_id = contract.get("connection_id")
    if not isinstance(connection_id, str) or not connection_id.strip():
        raise EvidenceCollectionError("connection_id_invalid")
    connection_id = connection_id.strip()
    report = _base_report(api_url, audience, connection_id)
    general_token = str(environment.get(GENERAL_OPERATOR_TOKEN_ENV) or "").strip()
    denial_proof = contract.get("general_operator_denial")
    if not general_token and not _validated_denial_proof(denial_proof):
        report["failure_status"] = "general_operator_token_missing"
        return report

    request_count = 0
    try:
        azure_config_dir = validate_azure_config_dir(config.azure_config_dir)
        report["azure_context_status"] = "isolated"
        report["ambient_credentials_status"] = "removed"
        maintenance_token = _acquire_maintenance_token(
            audience,
            azure_config_dir,
            env=environment,
            runner=runner,
        )
        report["token_acquisition_status"] = "accepted"

        http = transport or UrllibTransport()
        quoted_connection = urllib.parse.quote(connection_id, safe="")
        status_url = (
            f"{api_url}/api/v1/ontology-discovery/status?"
            + urllib.parse.urlencode({"connection_id": connection_id})
        )
        maintenance_url = (
            f"{api_url}/api/v1/ontology-discovery/connections/"
            f"{quoted_connection}/maintenance/full-reconciliation-due"
        )
        status_result = http.request(
            "GET",
            status_url,
            token=maintenance_token,
        )
        request_count += 1
        if status_result.status != 200:
            raise EvidenceCollectionError("status_get_not_accepted")
        status_payload = _json_object(status_result, "status_response_invalid")
        expected_revision = _status_revision(status_payload)
        revision_source_status = (
            "status_exposed" if expected_revision is not None else "zero_fallback"
        )
        if expected_revision is None:
            expected_revision = 0

        nonce = str(nonce_factory() or "").strip()
        if (
            not nonce
            or len(nonce) > 96
            or any(
                not (character.isalnum() or character in "-_") for character in nonce
            )
        ):
            raise EvidenceCollectionError("idempotency_nonce_invalid")
        idempotency_key = f"phase13-plan20-{nonce}"
        body = _post_body(
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
        )

        if general_token:
            denial = http.request(
                "POST",
                maintenance_url,
                token=general_token,
                body=body,
            )
            request_count += 1
            if not _authenticated_forbidden(denial):
                report["general_operator_evidence"] = "unverified"
                raise EvidenceCollectionError(
                    "general_operator_denial_unverified"
                )
        report["general_operator_evidence"] = "authenticated_forbidden"
        report["general_operator_http_status"] = 403
        report["general_operator_source"] = (
            "direct_token" if general_token else "fixed_evidence_job"
        )

        maintenance_result = http.request(
            "POST",
            maintenance_url,
            token=maintenance_token,
            body=body,
        )
        request_count += 1
        maintenance_attempt_count = 1
        revision_conflict_count = 0
        if maintenance_result.status == 409:
            expected_revision = _conflict_revision(maintenance_result)
            revision_conflict_count = 1
            revision_source_status = "conflict_recovered"
            body = _post_body(
                expected_revision=expected_revision,
                idempotency_key=idempotency_key,
            )
            maintenance_result = http.request(
                "POST",
                maintenance_url,
                token=maintenance_token,
                body=body,
            )
            request_count += 1
            maintenance_attempt_count = 2

        command_id, command_status = _verify_command(
            maintenance_result,
            connection_id=connection_id,
        )
        report.update(
            {
                "status": "PASS",
                "status_get_status": status_result.status,
                "revision_source_status": revision_source_status,
                "revision_conflict_count": revision_conflict_count,
                "maintenance_attempt_count": maintenance_attempt_count,
                "maintenance_http_status": maintenance_result.status,
                "maintenance_command_status": command_status,
                "maintenance_command_hash": _hash(command_id),
                "idempotency_hash": _hash(idempotency_key),
                "durability_status": "verified",
                "authorization_status": "verified",
                "source": "authenticated_api",
                "command_authorization": "authorized",
            }
        )
    except EvidenceCollectionError as exc:
        report["failure_status"] = str(exc)
    except Exception:  # noqa: BLE001 - never serialize unexpected live errors
        report["failure_status"] = "unexpected_collection_failure"
    report["request_count"] = request_count
    return report


def _write_report(path: Path, report: Mapping[str, object]) -> None:
    parent = path.expanduser().resolve().parent
    parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=parent,
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path.expanduser())
    finally:
        if temporary.exists():
            temporary.unlink()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Collect sanitized Phase 13 Plan 20 ontology maintenance evidence; "
            "read the connection_id JSON contract from stdin."
        )
    )
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--api-audience", required=True)
    parser.add_argument("--azure-config-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        contract = load_contract(sys.stdin)
        config = CollectionConfig(
            api_url=args.api_url,
            api_audience=args.api_audience,
            azure_config_dir=args.azure_config_dir,
            output_path=args.output,
        )
        report = collect_evidence(config, contract)
    except EvidenceCollectionError as exc:
        report = {
            "schema_version": "phase13-plan20-maintenance-v1",
            "status": "FAIL",
            "failure_status": str(exc),
            "general_operator_evidence": "unavailable",
            "request_count": 0,
            "coordinator_job_start_count": 0,
        }
    _write_report(args.output, report)
    print(str(report["status"]))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
