"""Fail-closed live authorization matrix for ontology publication identities.

The validator writes only beneath a unique non-production canary prefix.  It
requires an independently acquired token for every identity, verifies the
token's identity claims, accepts only explicit 401/403 denials, proves the
publisher's create/CAS/rollback/delete sequence, and emits no token, URL,
principal identifier, payload, or response body.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import yaml
from azure.core.credentials import AccessToken
from azure.identity import (
    ClientSecretCredential,
    ManagedIdentityCredential,
    WorkloadIdentityCredential,
)

TOKEN_SCOPE = "https://storage.azure.com/.default"
API_VERSION = "2023-11-03"
IDENTITY_CLASSES = ("api", "coordinator", "curator", "publisher")
NON_PUBLISHERS = IDENTITY_CLASSES[:-1]
EXPECTED_ROLE_ACTIONS = (
    "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read",
    "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/add/action",
    "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/write",
    "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/delete",
)


class ValidationBlocked(RuntimeError):
    """Required live configuration or identity evidence is unavailable."""


class AuthorizationEvidenceError(RuntimeError):
    """Observed authorization behavior does not prove the required boundary."""


class TokenCredential(Protocol):
    def get_token(self, *scopes: str, **kwargs: Any) -> AccessToken: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class IdentitySpec:
    identity_class: str
    mode: str
    tenant_id: str
    client_id: str
    object_id: str
    secret_env: str = ""
    token_file: str = ""


@dataclass(frozen=True)
class HttpResult:
    status: int
    headers: dict[str, str]


class HttpTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        token: str,
        headers: dict[str, str],
        body: bytes = b"",
    ) -> HttpResult: ...


class UrllibTransport:
    """Minimal body-discarding HTTPS transport."""

    def request(
        self,
        method: str,
        url: str,
        *,
        token: str,
        headers: dict[str, str],
        body: bytes = b"",
    ) -> HttpResult:
        if urllib.parse.urlsplit(url).scheme != "https":
            raise ValidationBlocked("validation target must use HTTPS")
        request_headers = {
            "Authorization": f"Bearer {token}",
            "x-ms-version": API_VERSION,
            "x-ms-date": datetime.now(UTC).strftime("%a, %d %b %Y %H:%M:%S GMT"),
            "Content-Length": str(len(body)),
            **headers,
        }
        request = urllib.request.Request(
            url,
            data=body if method in {"PUT", "PATCH"} else None,
            headers=request_headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return HttpResult(
                    status=response.status,
                    headers={key.casefold(): value for key, value in response.headers.items()},
                )
        except urllib.error.HTTPError as exc:
            # Bodies can contain tenant, path, and policy details.  Discard
            # them and retain only status plus allowlisted correlation headers.
            return HttpResult(
                status=exc.code,
                headers={key.casefold(): value for key, value in exc.headers.items()},
            )
        except (OSError, TimeoutError) as exc:
            raise AuthorizationEvidenceError("live authorization request failed") from exc


def _required(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValidationBlocked(f"missing {name}")
    return text


def _load_config(path: Path) -> dict[str, Any]:
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValidationBlocked("Fabric configuration is unavailable or invalid") from exc
    if not isinstance(loaded, dict) or not isinstance(loaded.get("fabric"), dict):
        raise ValidationBlocked("Fabric configuration has no fabric section")
    validation = loaded["fabric"].get("ontology_publisher_validation")
    if not isinstance(validation, dict):
        raise ValidationBlocked(
            "Fabric configuration has no ontology_publisher_validation section"
        )
    return validation


def _identity_specs(config: dict[str, Any]) -> dict[str, IdentitySpec]:
    raw = config.get("identities")
    if not isinstance(raw, dict) or set(raw) != set(IDENTITY_CLASSES):
        raise ValidationBlocked("exactly four identity configurations are required")
    specs: dict[str, IdentitySpec] = {}
    for identity_class in IDENTITY_CLASSES:
        entry = raw.get(identity_class)
        if not isinstance(entry, dict):
            raise ValidationBlocked(f"missing {identity_class} identity configuration")
        mode = _required(entry.get("mode"), f"{identity_class}.mode")
        if mode not in {"managed_identity", "workload_identity", "client_secret"}:
            raise ValidationBlocked(f"unsupported {identity_class} credential mode")
        spec = IdentitySpec(
            identity_class=identity_class,
            mode=mode,
            tenant_id=str(entry.get("tenant_id") or "").strip(),
            client_id=_required(entry.get("client_id"), f"{identity_class}.client_id"),
            object_id=_required(entry.get("object_id"), f"{identity_class}.object_id"),
            secret_env=str(entry.get("client_secret_env") or "").strip(),
            token_file=str(entry.get("token_file") or "").strip(),
        )
        if mode in {"workload_identity", "client_secret"} and not spec.tenant_id:
            raise ValidationBlocked(f"missing {identity_class}.tenant_id")
        if mode == "workload_identity" and not spec.token_file:
            raise ValidationBlocked(f"missing {identity_class}.token_file")
        if mode == "client_secret" and not spec.secret_env:
            raise ValidationBlocked(f"missing {identity_class}.client_secret_env")
        specs[identity_class] = spec
    if len({spec.object_id.casefold() for spec in specs.values()}) != 4:
        raise ValidationBlocked("identity object IDs must be distinct")
    return specs


def _credential(spec: IdentitySpec) -> TokenCredential:
    if spec.mode == "managed_identity":
        return ManagedIdentityCredential(client_id=spec.client_id)
    if spec.mode == "workload_identity":
        token_path = Path(spec.token_file).expanduser()
        if not token_path.is_file():
            raise ValidationBlocked(
                f"{spec.identity_class} workload identity token file is unavailable"
            )
        return WorkloadIdentityCredential(
            tenant_id=spec.tenant_id,
            client_id=spec.client_id,
            token_file_path=str(token_path),
        )
    secret = os.environ.get(spec.secret_env)
    if not secret:
        raise ValidationBlocked(
            f"{spec.identity_class} client secret environment variable is unset"
        )
    return ClientSecretCredential(
        tenant_id=spec.tenant_id,
        client_id=spec.client_id,
        client_secret=secret,
    )


def _token_claims(token: str) -> dict[str, Any]:
    try:
        encoded = token.split(".")[1]
        encoded += "=" * (-len(encoded) % 4)
        claims = json.loads(base64.urlsafe_b64decode(encoded))
    except (IndexError, ValueError, json.JSONDecodeError) as exc:
        raise AuthorizationEvidenceError("identity token claims are unavailable") from exc
    if not isinstance(claims, dict):
        raise AuthorizationEvidenceError("identity token claims are invalid")
    return claims


def _verified_token(credential: TokenCredential, spec: IdentitySpec) -> str:
    try:
        token = credential.get_token(TOKEN_SCOPE).token
    except Exception as exc:
        raise ValidationBlocked(
            f"{spec.identity_class} identity token is unavailable"
        ) from exc
    claims = _token_claims(token)
    application_claims = {
        str(claims.get(name) or "").casefold() for name in ("appid", "azp")
    }
    if spec.client_id.casefold() not in application_claims:
        raise AuthorizationEvidenceError(
            f"{spec.identity_class} token client identity mismatch"
        )
    if str(claims.get("oid") or "").casefold() != spec.object_id.casefold():
        raise AuthorizationEvidenceError(
            f"{spec.identity_class} token object identity mismatch"
        )
    return token


def _role_hash(config: dict[str, Any]) -> str:
    actions = config.get("publisher_role_actions")
    if not isinstance(actions, list) or any(not isinstance(item, str) for item in actions):
        raise ValidationBlocked("publisher_role_actions must be a string list")
    if tuple(actions) != EXPECTED_ROLE_ACTIONS:
        raise AuthorizationEvidenceError("publisher role definition does not match contract")
    canonical = json.dumps(actions, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _correlation(result: HttpResult) -> str:
    values = [
        result.headers.get(name, "")
        for name in ("x-ms-request-id", "request-id", "traceparent")
    ]
    evidence = "|".join(value for value in values if value)
    if not evidence:
        raise AuthorizationEvidenceError("operation lacks correlation evidence")
    return "sha256:" + hashlib.sha256(evidence.encode()).hexdigest()


def _evidence(
    *,
    identity_class: str,
    operation: str,
    result: str,
    role_hash: str,
    correlation: str,
) -> dict[str, str]:
    return {
        "operation": operation,
        "identity_class": identity_class,
        "result": result,
        "timestamp": datetime.now(UTC).isoformat(),
        "role_definition_hash": role_hash,
        "correlation_evidence": correlation,
    }


def _blob_url(config: dict[str, Any], relative_path: str) -> str:
    workspace = _required(config.get("workspace_id"), "workspace_id")
    lakehouse = _required(config.get("lakehouse_id"), "lakehouse_id")
    if not config.get("non_production"):
        raise ValidationBlocked("target is not explicitly marked non-production")
    quoted = "/".join(
        urllib.parse.quote(part, safe="") for part in relative_path.split("/")
    )
    return (
        "https://onelake.blob.fabric.microsoft.com/"
        f"{urllib.parse.quote(workspace, safe='')}/"
        f"{urllib.parse.quote(lakehouse, safe='')}/{quoted}"
    )


def _put(
    transport: HttpTransport,
    url: str,
    token: str,
    body: bytes,
    *,
    if_none_match: bool = False,
    etag: str = "",
) -> HttpResult:
    headers = {"x-ms-blob-type": "BlockBlob", "Content-Type": "application/json"}
    if if_none_match:
        headers["If-None-Match"] = "*"
    if etag:
        headers["If-Match"] = etag
    return transport.request("PUT", url, token=token, headers=headers, body=body)


def _delete(
    transport: HttpTransport,
    url: str,
    token: str,
    *,
    etag: str = "",
) -> HttpResult:
    headers = {"If-Match": etag} if etag else {}
    return transport.request("DELETE", url, token=token, headers=headers)


def _require_success(result: HttpResult, operation: str) -> str:
    if result.status not in {200, 201, 202}:
        raise AuthorizationEvidenceError(f"publisher {operation} was not authorized")
    return _correlation(result)


def _require_denial(result: HttpResult, identity_class: str, operation: str) -> str:
    if result.status not in {401, 403}:
        raise AuthorizationEvidenceError(
            f"{identity_class} {operation} did not produce an unambiguous denial"
        )
    return _correlation(result)


def validate_live_authorization(
    config: dict[str, Any],
    *,
    transport: HttpTransport | None = None,
    credential_factory=_credential,
) -> dict[str, Any]:
    """Execute the four-identity canary matrix and return a sanitized report."""
    role_hash = _role_hash(config)
    specs = _identity_specs(config)
    http = transport or UrllibTransport()
    credentials: dict[str, TokenCredential] = {}
    tokens: dict[str, str] = {}
    cleanup_urls: list[str] = []
    cleanup_completed = False
    try:
        for identity_class, spec in specs.items():
            credential = credential_factory(spec)
            credentials[identity_class] = credential
            tokens[identity_class] = _verified_token(credential, spec)

        run_id = uuid.uuid4().hex
        prefix = f"Files/aiops/validation/ontology-rbac/{run_id}"
        pointer_url = _blob_url(config, f"{prefix}/active.json")
        publisher_stage_url = _blob_url(config, f"{prefix}/publisher-stage.json")
        previous = json.dumps({"generation": "before"}, sort_keys=True).encode()
        candidate = json.dumps({"generation": "canary"}, sort_keys=True).encode()
        records: list[dict[str, str]] = []

        baseline = _put(
            http,
            pointer_url,
            tokens["publisher"],
            previous,
            if_none_match=True,
        )
        baseline_correlation = _require_success(baseline, "pointer_baseline")
        baseline_etag = _required(baseline.headers.get("etag"), "pointer baseline ETag")
        records.append(
            _evidence(
                identity_class="publisher",
                operation="pointer_baseline",
                result="authorized",
                role_hash=role_hash,
                correlation=baseline_correlation,
            )
        )

        cleanup_urls = [pointer_url, publisher_stage_url]
        for identity_class in NON_PUBLISHERS:
            stage_url = _blob_url(config, f"{prefix}/{identity_class}-stage.json")
            cleanup_urls.append(stage_url)
            denied_stage = _put(
                http,
                stage_url,
                tokens[identity_class],
                candidate,
                if_none_match=True,
            )
            records.append(
                _evidence(
                    identity_class=identity_class,
                    operation="stage_create_only",
                    result="denied",
                    role_hash=role_hash,
                    correlation=_require_denial(
                        denied_stage, identity_class, "stage_create_only"
                    ),
                )
            )
            denied_pointer = _put(
                http,
                pointer_url,
                tokens[identity_class],
                candidate,
                etag=baseline_etag,
            )
            records.append(
                _evidence(
                    identity_class=identity_class,
                    operation="pointer_cas",
                    result="denied",
                    role_hash=role_hash,
                    correlation=_require_denial(
                        denied_pointer, identity_class, "pointer_cas"
                    ),
                )
            )

        staged = _put(
            http,
            publisher_stage_url,
            tokens["publisher"],
            candidate,
            if_none_match=True,
        )
        records.append(
            _evidence(
                identity_class="publisher",
                operation="stage_create_only",
                result="authorized",
                role_hash=role_hash,
                correlation=_require_success(staged, "stage_create_only"),
            )
        )

        promoted = _put(
            http,
            pointer_url,
            tokens["publisher"],
            candidate,
            etag=baseline_etag,
        )
        promoted_correlation = _require_success(promoted, "pointer_cas")
        promoted_etag = _required(promoted.headers.get("etag"), "promoted pointer ETag")
        records.append(
            _evidence(
                identity_class="publisher",
                operation="pointer_cas",
                result="authorized",
                role_hash=role_hash,
                correlation=promoted_correlation,
            )
        )

        rolled_back = _put(
            http,
            pointer_url,
            tokens["publisher"],
            previous,
            etag=promoted_etag,
        )
        rollback_correlation = _require_success(rolled_back, "rollback_cas")
        rollback_etag = _required(rolled_back.headers.get("etag"), "rollback pointer ETag")
        records.append(
            _evidence(
                identity_class="publisher",
                operation="rollback_cas",
                result="authorized",
                role_hash=role_hash,
                correlation=rollback_correlation,
            )
        )

        for url in cleanup_urls:
            deleted = _delete(
                http,
                url,
                tokens["publisher"],
                etag=rollback_etag if url == pointer_url else "",
            )
            # A denied non-publisher create leaves no artifact, so 404 is the
            # expected cleanup result for those three paths.
            if deleted.status == 404 and url not in {pointer_url, publisher_stage_url}:
                correlation = _correlation(deleted)
                result = "absent"
            else:
                correlation = _require_success(deleted, "canary_cleanup")
                result = "authorized"
            records.append(
                _evidence(
                    identity_class="publisher",
                    operation="canary_cleanup",
                    result=result,
                    role_hash=role_hash,
                    correlation=correlation,
                )
            )
        cleanup_completed = True
        return {
            "status": "passed",
            "non_production": True,
            "evidence": records,
        }
    finally:
        # Authorization failure is itself important evidence, but it must not
        # strand the publisher-created pointer baseline or an unexpectedly
        # successful non-publisher stage.  Best-effort unconditional cleanup
        # runs under the publisher token before the original fail-closed error
        # is propagated.  The successful path above separately requires and
        # records every cleanup result.
        if cleanup_urls and not cleanup_completed and tokens.get("publisher"):
            for url in cleanup_urls:
                with suppress(AuthorizationEvidenceError, ValidationBlocked):
                    _delete(http, url, tokens["publisher"])
        for credential in credentials.values():
            credential.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate live non-production ontology publisher authorization"
    )
    parser.add_argument("--non-production", action="store_true")
    parser.add_argument("--fail-on-missing-evidence", action="store_true")
    parser.add_argument(
        "--config",
        default=os.environ.get("AIOPS_FABRIC_CONFIG", ""),
        help="Fabric YAML path (defaults to AIOPS_FABRIC_CONFIG)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if not args.non_production:
            raise ValidationBlocked("--non-production is required")
        if not args.fail_on_missing_evidence:
            raise ValidationBlocked("--fail-on-missing-evidence is required")
        config_path = Path(_required(args.config, "AIOPS_FABRIC_CONFIG")).expanduser()
        report = validate_live_authorization(_load_config(config_path))
    except (ValidationBlocked, AuthorizationEvidenceError) as exc:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "reason": str(exc),
                    "evidence": [],
                },
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
