"""Fail-closed live authorization matrix for ontology publication identities.

The validator writes only beneath a unique non-production canary prefix. It
uses independently selected managed identities for the API, coordinator, and
publisher; verifies their token claims; accepts only explicit 401/403 write
denials; proves the publisher's create/CAS/rollback/delete sequence; and emits
no token, URL, principal identifier, payload, or response body.

Foundry does not expose a safe way for this Job to impersonate the prompt
agent project's managed identity. Curator denial is therefore structural live
evidence: the curator principal must have no Fabric writer role and the
deployed prompt agent must expose exactly four reviewed read-only tools.
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

STORAGE_TOKEN_SCOPE = "https://storage.azure.com/.default"
FABRIC_TOKEN_SCOPE = "https://api.fabric.microsoft.com/.default"
FOUNDRY_TOKEN_SCOPE = "https://ai.azure.com/.default"
API_VERSION = "2023-11-03"
IDENTITY_CLASSES = ("api", "coordinator", "curator", "publisher")
LIVE_WRITE_IDENTITIES = ("api", "coordinator", "publisher")
DENIED_WRITE_IDENTITIES = ("api", "coordinator")
EXPECTED_CURATOR_TOOLS = (
    "list_changed_entities",
    "get_entity_evidence",
    "get_ontology_vocabulary",
    "search_relationship_history",
)
EXPECTED_PUBLISHER_ROLE = {
    "platform": "microsoft_fabric_workspace",
    "role": "Contributor",
    "scope": "workspace",
    "granularity": "platform_minimum_write_role",
}
FABRIC_WRITER_ROLES = frozenset({"admin", "member", "contributor"})


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
    body: bytes = b""
    client_request_id: str = ""


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
        client_request_id = str(uuid.uuid4())
        request_headers = {
            "Authorization": f"Bearer {token}",
            "x-ms-version": API_VERSION,
            "x-ms-date": datetime.now(UTC).strftime("%a, %d %b %Y %H:%M:%S GMT"),
            "Content-Length": str(len(body)),
            **headers,
            "x-ms-client-request-id": client_request_id,
            "x-ms-return-client-request-id": "true",
        }
        request = urllib.request.Request(
            url,
            data=body if method in {"PUT", "PATCH"} else None,
            headers=request_headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                response_body = response.read(1_000_001)
                if len(response_body) > 1_000_000:
                    raise AuthorizationEvidenceError(
                        "live authorization response exceeded size limit"
                    )
                return HttpResult(
                    status=response.status,
                    headers={key.casefold(): value for key, value in response.headers.items()},
                    body=response_body,
                    client_request_id=client_request_id,
                )
        except urllib.error.HTTPError as exc:
            # Bodies can contain tenant, path, and policy details.  Discard
            # them and retain only status plus allowlisted correlation headers.
            return HttpResult(
                status=exc.code,
                headers={key.casefold(): value for key, value in exc.headers.items()},
                client_request_id=client_request_id,
            )
        except (OSError, TimeoutError) as exc:
            raise AuthorizationEvidenceError("live authorization request failed") from exc


def _required(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValidationBlocked(f"missing {name}")
    return text


def _load_config(
    path: Path,
    *,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValidationBlocked("Fabric configuration is unavailable or invalid") from exc
    if not isinstance(loaded, dict) or not isinstance(loaded.get("fabric"), dict):
        raise ValidationBlocked("Fabric configuration has no fabric section")
    fabric = loaded["fabric"]
    configured = fabric.get("ontology_publisher_validation")
    validation = dict(configured) if isinstance(configured, dict) else {}
    environment = dict(os.environ if env is None else env)
    if environment.get("AIOPS_ONTOLOGY_API_CLIENT_ID"):
        validation.update(
            {
                "non_production": environment.get(
                    "AIOPS_ONTOLOGY_NON_PRODUCTION", ""
                ).casefold()
                == "true",
                "workspace_id": environment.get("AIOPS_ONTOLOGY_WORKSPACE_ID")
                or fabric.get("workspace_id"),
                "lakehouse_id": environment.get("AIOPS_ONTOLOGY_LAKEHOUSE_ID")
                or fabric.get("lakehouse_id"),
                "publisher_role": dict(EXPECTED_PUBLISHER_ROLE),
                "foundry_project_endpoint": environment.get(
                    "FOUNDRY_PROJECT_ENDPOINT", ""
                ),
                "curator_agent_name": environment.get(
                    "FOUNDRY_ONTOLOGY_CURATOR_AGENT_NAME", ""
                ),
                "curator_prompt_sha256": environment.get(
                    "FOUNDRY_ONTOLOGY_CURATOR_PROMPT_SHA256", ""
                ),
                "curator_model": environment.get(
                    "FOUNDRY_ONTOLOGY_CURATOR_MODEL", ""
                ),
                "identities": {
                    "api": {
                        "mode": "managed_identity",
                        "client_id": environment.get(
                            "AIOPS_ONTOLOGY_API_CLIENT_ID", ""
                        ),
                        "object_id": environment.get(
                            "AIOPS_ONTOLOGY_API_OBJECT_ID", ""
                        ),
                    },
                    "coordinator": {
                        "mode": "managed_identity",
                        "client_id": environment.get(
                            "AIOPS_ONTOLOGY_COORDINATOR_CLIENT_ID", ""
                        ),
                        "object_id": environment.get(
                            "AIOPS_ONTOLOGY_COORDINATOR_OBJECT_ID", ""
                        ),
                    },
                    "publisher": {
                        "mode": "managed_identity",
                        "client_id": environment.get(
                            "AIOPS_ONTOLOGY_PUBLISHER_CLIENT_ID", ""
                        ),
                        "object_id": environment.get(
                            "AIOPS_ONTOLOGY_PUBLISHER_OBJECT_ID", ""
                        ),
                    },
                },
            }
        )
    return validation


def _identity_specs(
    config: dict[str, Any],
    *,
    require_curator: bool = True,
) -> dict[str, IdentitySpec]:
    raw = config.get("identities")
    expected = set(IDENTITY_CLASSES if require_curator else LIVE_WRITE_IDENTITIES)
    if not isinstance(raw, dict) or not expected.issubset(raw):
        raise ValidationBlocked(
            "required identity configurations are unavailable"
        )
    specs: dict[str, IdentitySpec] = {}
    for identity_class in IDENTITY_CLASSES:
        if identity_class == "curator" and not require_curator:
            continue
        entry = raw.get(identity_class)
        if not isinstance(entry, dict):
            raise ValidationBlocked(f"missing {identity_class} identity configuration")
        mode = _required(entry.get("mode"), f"{identity_class}.mode")
        if identity_class == "curator":
            if mode != "structural":
                raise ValidationBlocked("curator identity must use structural evidence")
            specs[identity_class] = IdentitySpec(
                identity_class=identity_class,
                mode=mode,
                tenant_id="",
                client_id="",
                object_id=_required(
                    entry.get("object_id"), f"{identity_class}.object_id"
                ),
            )
            continue
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
    if len({spec.object_id.casefold() for spec in specs.values()}) != len(specs):
        raise ValidationBlocked("identity object IDs must be distinct")
    return specs


def _structural_identity_specs(
    config: dict[str, Any],
) -> dict[str, IdentitySpec]:
    raw = config.get("identities")
    if not isinstance(raw, dict) or set(raw) != set(IDENTITY_CLASSES):
        raise ValidationBlocked("exactly four structural identities are required")
    specs = {
        identity_class: IdentitySpec(
            identity_class=identity_class,
            mode="structural",
            tenant_id="",
            client_id="",
            object_id=_required(
                raw.get(identity_class, {}).get("object_id")
                if isinstance(raw.get(identity_class), dict)
                else "",
                f"{identity_class}.object_id",
            ),
        )
        for identity_class in IDENTITY_CLASSES
    }
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


def _deployer_credential(env: dict[str, str] | None = None) -> TokenCredential:
    environment = dict(os.environ if env is None else env)
    return ClientSecretCredential(
        tenant_id=_required(environment.get("AZURE_TENANT_ID"), "AZURE_TENANT_ID"),
        client_id=_required(environment.get("AZURE_CLIENT_ID"), "AZURE_CLIENT_ID"),
        client_secret=_required(
            environment.get("AZURE_CLIENT_SECRET"), "AZURE_CLIENT_SECRET"
        ),
    )


def _state_attributes(
    state: dict[str, Any],
    resource_type: str,
    name: str,
) -> dict[str, Any]:
    resources = state.get("resources")
    if not isinstance(resources, list):
        raise ValidationBlocked("Terraform state has no resources")
    matches = [
        resource
        for resource in resources
        if isinstance(resource, dict)
        and resource.get("type") == resource_type
        and resource.get("name") == name
    ]
    if len(matches) != 1:
        raise ValidationBlocked("required Terraform state resource is unavailable")
    instances = matches[0].get("instances")
    if not isinstance(instances, list) or len(instances) != 1:
        raise ValidationBlocked("required Terraform state instance is unavailable")
    attributes = instances[0].get("attributes")
    if not isinstance(attributes, dict):
        raise ValidationBlocked("required Terraform state attributes are unavailable")
    return attributes


def _config_from_terraform_state(
    config: dict[str, Any],
    state_path: Path,
    *,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationBlocked("Terraform state is unavailable or invalid") from exc
    if not isinstance(state, dict):
        raise ValidationBlocked("Terraform state is invalid")

    api = _state_attributes(state, "azurerm_user_assigned_identity", "apps")
    coordinator = _state_attributes(
        state,
        "azurerm_user_assigned_identity",
        "ontology_coordinator",
    )
    publisher = _state_attributes(
        state,
        "azurerm_user_assigned_identity",
        "ontology_publisher",
    )
    project = _state_attributes(
        state,
        "azurerm_cognitive_account_project",
        "ops",
    )
    workspace = _state_attributes(
        state,
        "fabric_workspace",
        "ontology_rbac_validation",
    )
    lakehouse = _state_attributes(
        state,
        "fabric_lakehouse",
        "ontology_rbac_validation",
    )
    curator = _state_attributes(
        state,
        "terraform_data",
        "foundry_ontology_curator_agent",
    )
    project_identity = project.get("identity")
    if not isinstance(project_identity, list) or len(project_identity) != 1:
        raise ValidationBlocked("Foundry project identity is unavailable in state")
    triggers = curator.get("triggers_replace")
    if (
        isinstance(triggers, dict)
        and set(triggers) == {"value", "type"}
        and isinstance(triggers.get("value"), dict)
    ):
        triggers = triggers["value"]
    if not isinstance(triggers, dict):
        raise ValidationBlocked("curator deployment metadata is unavailable in state")

    environment = dict(os.environ if env is None else env)
    merged = dict(config)
    merged.update(
        {
            "non_production": True,
            "workspace_id": _required(workspace.get("id"), "validation workspace ID"),
            "lakehouse_id": _required(lakehouse.get("id"), "validation lakehouse ID"),
            "publisher_role": dict(EXPECTED_PUBLISHER_ROLE),
            "foundry_project_endpoint": _required(
                triggers.get("endpoint"), "curator endpoint"
            ),
            "curator_agent_name": _required(
                triggers.get("agent_name"), "curator agent name"
            ),
            "curator_model": _required(triggers.get("model"), "curator model"),
            "curator_prompt_sha256": _required(
                triggers.get("instructions"), "curator prompt hash"
            ),
            "deployer_client_id": _required(
                environment.get("AZURE_CLIENT_ID"), "AZURE_CLIENT_ID"
            ),
            "identities": {
                "api": {
                    "mode": "managed_identity",
                    "client_id": _required(api.get("client_id"), "API client ID"),
                    "object_id": _required(api.get("principal_id"), "API object ID"),
                },
                "coordinator": {
                    "mode": "managed_identity",
                    "client_id": _required(
                        coordinator.get("client_id"), "coordinator client ID"
                    ),
                    "object_id": _required(
                        coordinator.get("principal_id"), "coordinator object ID"
                    ),
                },
                "curator": {
                    "mode": "structural",
                    "object_id": _required(
                        project_identity[0].get("principal_id"),
                        "curator object ID",
                    ),
                },
                "publisher": {
                    "mode": "managed_identity",
                    "client_id": _required(
                        publisher.get("client_id"), "publisher client ID"
                    ),
                    "object_id": _required(
                        publisher.get("principal_id"), "publisher object ID"
                    ),
                },
            },
        }
    )
    return merged


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


def _verified_token(
    credential: TokenCredential,
    spec: IdentitySpec,
    *,
    scope: str,
) -> str:
    try:
        token = credential.get_token(scope).token
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


def _verified_deployer_token(
    credential: TokenCredential,
    *,
    client_id: str,
    scope: str,
) -> str:
    try:
        token = credential.get_token(scope).token
    except Exception as exc:
        raise ValidationBlocked("deployer identity token is unavailable") from exc
    claims = _token_claims(token)
    application_claims = {
        str(claims.get(name) or "").casefold() for name in ("appid", "azp")
    }
    if client_id.casefold() not in application_claims:
        raise AuthorizationEvidenceError("deployer token client identity mismatch")
    return token


def _role_hash(config: dict[str, Any]) -> str:
    role = config.get("publisher_role")
    if not isinstance(role, dict):
        raise ValidationBlocked("publisher_role must be an object")
    if role != EXPECTED_PUBLISHER_ROLE:
        raise AuthorizationEvidenceError("publisher role definition does not match contract")
    canonical = json.dumps(
        role,
        separators=(",", ":"),
        ensure_ascii=True,
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _correlation(result: HttpResult) -> str:
    values = [
        result.headers.get(name, "")
        for name in ("x-ms-request-id", "request-id", "traceparent")
    ]
    evidence = "|".join(value for value in values if value)
    if not evidence:
        candidate = result.client_request_id.strip()
        try:
            parsed = uuid.UUID(candidate)
        except (AttributeError, ValueError) as exc:
            raise AuthorizationEvidenceError(
                "operation lacks correlation evidence"
            ) from exc
        if parsed.version != 4 or str(parsed) != candidate.casefold():
            raise AuthorizationEvidenceError("operation lacks correlation evidence")
        evidence = candidate
    return "sha256:" + hashlib.sha256(evidence.encode()).hexdigest()


def _evidence(
    *,
    identity_class: str,
    operation: str,
    result: str,
    role_hash: str,
    correlation: str,
    evidence_kind: str = "operation_live",
) -> dict[str, str]:
    return {
        "operation": operation,
        "identity_class": identity_class,
        "result": result,
        "timestamp": datetime.now(UTC).isoformat(),
        "role_definition_hash": role_hash,
        "correlation_evidence": correlation,
        "evidence_kind": evidence_kind,
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


def _json_object(result: HttpResult, operation: str) -> dict[str, Any]:
    if result.status != 200:
        raise AuthorizationEvidenceError(f"{operation} live read failed")
    try:
        payload = json.loads(result.body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuthorizationEvidenceError(
            f"{operation} live response is invalid"
        ) from exc
    if not isinstance(payload, dict):
        raise AuthorizationEvidenceError(f"{operation} live response is invalid")
    return payload


def _workspace_role_evidence(
    config: dict[str, Any],
    *,
    specs: dict[str, IdentitySpec],
    transport: HttpTransport,
    token: str,
) -> str:
    workspace_id = _required(config.get("workspace_id"), "workspace_id")
    url = (
        "https://api.fabric.microsoft.com/v1/workspaces/"
        f"{urllib.parse.quote(workspace_id, safe='')}/roleAssignments"
    )
    response = transport.request("GET", url, token=token, headers={})
    payload = _json_object(response, "workspace role assignment")
    assignments = payload.get("value")
    if not isinstance(assignments, list):
        raise AuthorizationEvidenceError(
            "workspace role assignment response has no value list"
        )

    roles_by_principal: dict[str, set[str]] = {}
    for assignment in assignments:
        if not isinstance(assignment, dict):
            raise AuthorizationEvidenceError(
                "workspace role assignment entry is invalid"
            )
        principal = assignment.get("principal")
        principal_id = (
            principal.get("id")
            if isinstance(principal, dict)
            else assignment.get("principalId")
        )
        role = assignment.get("role") or assignment.get("roleName")
        if not isinstance(principal_id, str) or not isinstance(role, str):
            raise AuthorizationEvidenceError(
                "workspace role assignment entry is incomplete"
            )
        roles_by_principal.setdefault(principal_id.casefold(), set()).add(
            role.casefold()
        )

    publisher_roles = roles_by_principal.get(
        specs["publisher"].object_id.casefold(), set()
    )
    if publisher_roles != {"contributor"}:
        raise AuthorizationEvidenceError(
            "publisher does not have exactly the Contributor workspace role"
        )
    for identity_class in ("api", "coordinator", "curator"):
        roles = roles_by_principal.get(specs[identity_class].object_id.casefold(), set())
        if roles & FABRIC_WRITER_ROLES:
            raise AuthorizationEvidenceError(
                f"{identity_class} has a Fabric workspace writer role"
            )
    return _correlation(response)


def _curator_agent_evidence(
    config: dict[str, Any],
    *,
    transport: HttpTransport,
    token: str,
) -> str:
    endpoint = _required(
        config.get("foundry_project_endpoint"), "foundry_project_endpoint"
    ).rstrip("/")
    parsed = urllib.parse.urlsplit(endpoint)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValidationBlocked("Foundry project endpoint must use HTTPS")
    agent_name = _required(config.get("curator_agent_name"), "curator_agent_name")
    expected_model = _required(config.get("curator_model"), "curator_model")
    expected_prompt_hash = _required(
        config.get("curator_prompt_sha256"), "curator_prompt_sha256"
    )
    url = (
        f"{endpoint}/agents/{urllib.parse.quote(agent_name, safe='')}/versions"
        "?api-version=v1"
    )
    response = transport.request("GET", url, token=token, headers={})
    payload = _json_object(response, "deployed curator")
    versions = payload.get("value")
    if not isinstance(versions, list) or not versions:
        raise AuthorizationEvidenceError("deployed curator has no versions")

    for version in versions:
        if not isinstance(version, dict) or not isinstance(
            version.get("definition"), dict
        ):
            raise AuthorizationEvidenceError("deployed curator version is invalid")
        definition = version["definition"]
        if definition.get("model") != expected_model:
            raise AuthorizationEvidenceError("deployed curator model mismatch")
        instructions = definition.get("instructions")
        if not isinstance(instructions, str) or (
            hashlib.sha256(instructions.encode()).hexdigest()
            != expected_prompt_hash
        ):
            raise AuthorizationEvidenceError("deployed curator prompt mismatch")
        tools = definition.get("tools")
        if not isinstance(tools, list) or len(tools) != 1:
            raise AuthorizationEvidenceError("deployed curator tool allowlist mismatch")
        tool = tools[0]
        if (
            not isinstance(tool, dict)
            or tool.get("type") != "mcp"
            or tool.get("server_label") != "operations-mcp"
            or tuple(tool.get("allowed_tools") or ()) != EXPECTED_CURATOR_TOOLS
        ):
            raise AuthorizationEvidenceError("deployed curator tool allowlist mismatch")
    return _correlation(response)


def validate_write_matrix(
    config: dict[str, Any],
    *,
    transport: HttpTransport | None = None,
    credential_factory=_credential,
) -> dict[str, Any]:
    """Execute only the three-UAI OneLake write matrix."""
    role_hash = _role_hash(config)
    specs = _identity_specs(config, require_curator=False)
    http = transport or UrllibTransport()
    credentials: dict[str, TokenCredential] = {}
    tokens: dict[str, str] = {}
    cleanup_urls: list[str] = []
    cleanup_completed = False
    try:
        for identity_class in LIVE_WRITE_IDENTITIES:
            spec = specs[identity_class]
            credential = credential_factory(spec)
            credentials[identity_class] = credential
            tokens[identity_class] = _verified_token(
                credential,
                spec,
                scope=STORAGE_TOKEN_SCOPE,
            )

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
        for identity_class in DENIED_WRITE_IDENTITIES:
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
            "mode": "write-matrix-only",
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


def validate_control_plane_audit(
    config: dict[str, Any],
    *,
    transport: HttpTransport | None = None,
    credential: TokenCredential | None = None,
    credential_factory=_deployer_credential,
) -> dict[str, Any]:
    """Audit Fabric roles and the deployed curator under the deployer."""
    role_hash = _role_hash(config)
    specs = _structural_identity_specs(config)
    http = transport or UrllibTransport()
    deployer = credential or credential_factory()
    deployer_client_id = _required(
        config.get("deployer_client_id"), "deployer_client_id"
    )
    try:
        fabric_token = _verified_deployer_token(
            deployer,
            client_id=deployer_client_id,
            scope=FABRIC_TOKEN_SCOPE,
        )
        role_correlation = _workspace_role_evidence(
            config,
            specs=specs,
            transport=http,
            token=fabric_token,
        )
        foundry_token = _verified_deployer_token(
            deployer,
            client_id=deployer_client_id,
            scope=FOUNDRY_TOKEN_SCOPE,
        )
        tool_correlation = _curator_agent_evidence(
            config,
            transport=http,
            token=foundry_token,
        )
    finally:
        deployer.close()

    records = [
        _evidence(
            identity_class=identity_class,
            operation="workspace_writer_role",
            result="contributor" if identity_class == "publisher" else "absent",
            role_hash=role_hash,
            correlation=role_correlation,
            evidence_kind="control_plane_live",
        )
        for identity_class in IDENTITY_CLASSES
    ]
    records.append(
        _evidence(
            identity_class="curator",
            operation="deployed_tool_allowlist",
            result="read_only",
            role_hash=role_hash,
            correlation=tool_correlation,
            evidence_kind="control_plane_live",
        )
    )
    return {
        "status": "passed",
        "mode": "control-plane-audit",
        "non_production": True,
        "evidence": records,
    }


def validate_live_authorization(
    config: dict[str, Any],
    *,
    transport: HttpTransport | None = None,
    credential_factory=_credential,
    deployer_credential: TokenCredential | None = None,
) -> dict[str, Any]:
    """Aggregate both evidence passes only when all credentials are available."""
    write_report = validate_write_matrix(
        config,
        transport=transport,
        credential_factory=credential_factory,
    )
    audit_report = validate_control_plane_audit(
        config,
        transport=transport,
        credential=deployer_credential,
    )
    return {
        "status": "passed",
        "mode": "full",
        "non_production": True,
        "evidence": write_report["evidence"] + audit_report["evidence"],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate live non-production ontology publisher authorization"
    )
    parser.add_argument("--non-production", action="store_true")
    parser.add_argument("--fail-on-missing-evidence", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write-matrix-only", action="store_true")
    mode.add_argument("--control-plane-audit", action="store_true")
    parser.add_argument(
        "--config",
        default=os.environ.get("AIOPS_FABRIC_CONFIG", ""),
        help="Fabric YAML path (defaults to AIOPS_FABRIC_CONFIG)",
    )
    parser.add_argument(
        "--terraform-state",
        default=os.environ.get("AIOPS_TERRAFORM_STATE", ""),
        help="Terraform state used to resolve deployed control-plane identities",
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
        config = _load_config(config_path)
        if args.control_plane_audit:
            state_path = Path(
                _required(args.terraform_state, "AIOPS_TERRAFORM_STATE")
            ).expanduser()
            config = _config_from_terraform_state(config, state_path)
            report = validate_control_plane_audit(config)
        elif args.write_matrix_only:
            report = validate_write_matrix(config)
        else:
            state_path = Path(
                _required(args.terraform_state, "AIOPS_TERRAFORM_STATE")
            ).expanduser()
            config = _config_from_terraform_state(config, state_path)
            report = validate_live_authorization(config)
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
