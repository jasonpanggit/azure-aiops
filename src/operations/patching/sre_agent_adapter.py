"""Azure SRE Agent execution adapter for exact approved patch selections.

The adapter invokes one pre-created HTTP trigger. It does not create or
configure the trigger, discover patches, widen the approved selection, or
accept an operator credential.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from ipaddress import ip_address
from urllib.parse import quote, urlsplit

import httpx

from .adapters import PatchExecutionResult, PatchExecutionUnavailable
from .azure_adapter import TokenCredential, classify_azure_response_failure
from .models import (
    OPERATION_INSTALL_PATCHES,
    TARGET_KIND_ARC_SERVER,
    TARGET_KIND_AZURE_VM,
    PatchRun,
    PatchTarget,
)

SRE_AGENT_PROVIDER = "sre-agent"
SRE_AGENT_APPLICATION_ID = "59f0a04a-b322-4310-adc9-39ac41e9631e"
SRE_AGENT_TRIGGER_SCOPE = f"{SRE_AGENT_APPLICATION_ID}/.default"
SRE_AGENT_THREAD_SCOPE = "https://azuresre.dev/.default"
SRE_PATCH_ENVELOPE_VERSION = "1.1"
SRE_PATCH_MAXIMUM_DURATION = "PT2H"
SRE_PATCH_READ_SKILL_NAME = "aiops-read-patch-applicability-v1"
SRE_PATCH_READ_SKILL_VERSION = "1.0"
SRE_PATCH_READ_SKILL_SHA256 = (
    "890a41d4877c337cc6fa9f108c2224d66f2ef08c6a8c398decfa723824181070"
)
SRE_PATCH_READ_SKILL_TOOLS = ("RunAzCliReadCommands",)
SRE_PATCH_READ_SKILL_OPERATION = "read_patch_applicability"
SRE_PATCH_READ_OUTPUT_SCHEMA_VERSION = "1.0"
SRE_PATCH_WRITE_SKILL_NAME = "aiops-install-selected-patches-v1"
SRE_PATCH_WRITE_SKILL_VERSION = "1.0"
SRE_PATCH_WRITE_SKILL_SHA256 = (
    "f349f8473d44930b842612b29b742d6240f34b72a9872d244fdd58cad28c8473"
)
SRE_PATCH_WRITE_SKILL_TOOLS = ("RunAzCliWriteCommands",)
SRE_PATCH_WRITE_SKILL_OPERATION = "install_selected_patches"
SRE_PATCH_WRITE_OUTPUT_SCHEMA_VERSION = "1.0"
SRE_PATCH_APPLICABILITY_MAXIMUM_ROWS = 257
SRE_PATCH_APPLICABILITY_MAXIMUM_AGE = "PT24H"
SRE_PATCH_WRITE_EVIDENCE_MAXIMUM_AGE = "PT5M"
SRE_PATCH_APPROVED_SNAPSHOT_IDENTITY_FIELDS = (
    "target_id",
    "patch_ids",
    "target_kind",
    "operation",
    "action_version",
)
SRE_PATCH_APPROVED_SNAPSHOT_FIELDS = (
    *SRE_PATCH_APPROVED_SNAPSHOT_IDENTITY_FIELDS,
    "subscription_id",
    "approver",
    "snapshot_hash",
)
_TRIGGER_PATH_MARKER = "/api/v1/httptriggers/trigger/"
_MAX_PATCH_IDS = 256
_MAX_PATCH_ID_LENGTH = 256
_MAX_AUDIT_IDENTITY_LENGTH = 320
_MAX_RESOURCE_ID_LENGTH = 2048
_MAX_RUN_ID_LENGTH = 128
_MAX_TRIGGER_ID_LENGTH = 256
_TRIGGER_ID = re.compile(r"^[A-Za-z0-9._~-]+$")
_ARM_SEGMENT = re.compile(r"^[A-Za-z0-9._()\-]+$")
_PATCH_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+-]{0,255}$")
_SUBSCRIPTION_ID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _skill_contract() -> dict[str, object]:
    return {
        "sequence": ["read", "write"],
        "read": {
            "name": SRE_PATCH_READ_SKILL_NAME,
            "version": SRE_PATCH_READ_SKILL_VERSION,
            "artifact": "SKILL.md",
            "raw_sha256": SRE_PATCH_READ_SKILL_SHA256,
            "tools": list(SRE_PATCH_READ_SKILL_TOOLS),
            "operation": SRE_PATCH_READ_SKILL_OPERATION,
            "output_schema_version": SRE_PATCH_READ_OUTPUT_SCHEMA_VERSION,
            "maximum_rows": SRE_PATCH_APPLICABILITY_MAXIMUM_ROWS,
            "maximum_age": SRE_PATCH_APPLICABILITY_MAXIMUM_AGE,
        },
        "write": {
            "name": SRE_PATCH_WRITE_SKILL_NAME,
            "version": SRE_PATCH_WRITE_SKILL_VERSION,
            "artifact": "SKILL.md",
            "raw_sha256": SRE_PATCH_WRITE_SKILL_SHA256,
            "tools": list(SRE_PATCH_WRITE_SKILL_TOOLS),
            "operation": SRE_PATCH_WRITE_SKILL_OPERATION,
            "output_schema_version": SRE_PATCH_WRITE_OUTPUT_SCHEMA_VERSION,
            "required_read_evidence_maximum_age": (
                SRE_PATCH_WRITE_EVIDENCE_MAXIMUM_AGE
            ),
            "review_command_count": 1,
        },
    }


def sre_agent_patch_envelope_contract() -> dict[str, object]:
    """Return the locked JSON schema for outbound SRE Agent patch payloads."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://azure-aiops.example/schemas/sre-agent-selected-patch-run/1.1",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "run_id",
            "subscription_id",
            "target_id",
            "target_kind",
            "patch_ids",
            "approval",
            "skill_chain",
            "reboot_setting",
            "maximum_duration",
            "requested_by",
            "approved_by",
            "operation",
        ],
        "properties": {
            "schema_version": {"const": SRE_PATCH_ENVELOPE_VERSION},
            "run_id": {
                "type": "string",
                "minLength": 1,
                "maxLength": _MAX_RUN_ID_LENGTH,
            },
            "subscription_id": {"type": "string", "format": "uuid"},
            "target_id": {
                "type": "string",
                "minLength": 1,
                "maxLength": _MAX_RESOURCE_ID_LENGTH,
            },
            "target_kind": {"enum": [TARGET_KIND_AZURE_VM, TARGET_KIND_ARC_SERVER]},
            "patch_ids": {
                "type": "array",
                "minItems": 1,
                "maxItems": _MAX_PATCH_IDS,
                "uniqueItems": True,
                "items": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": _MAX_PATCH_ID_LENGTH,
                },
            },
            "approval": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "decision_id",
                    "decision",
                    "decided_at",
                    "expires_at",
                    "approved_by",
                    "execution_snapshot",
                ],
                "properties": {
                    "decision_id": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 128,
                    },
                    "decision": {"const": "approved"},
                    "decided_at": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 64,
                    },
                    "expires_at": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 64,
                    },
                    "approved_by": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": _MAX_AUDIT_IDENTITY_LENGTH,
                    },
                    "execution_snapshot": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": list(SRE_PATCH_APPROVED_SNAPSHOT_FIELDS),
                        "properties": {
                            "target_id": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": _MAX_RESOURCE_ID_LENGTH,
                            },
                            "patch_ids": {
                                "type": "array",
                                "minItems": 1,
                                "maxItems": _MAX_PATCH_IDS,
                                "uniqueItems": True,
                                "items": {
                                    "type": "string",
                                    "minLength": 1,
                                    "maxLength": _MAX_PATCH_ID_LENGTH,
                                },
                            },
                            "target_kind": {
                                "enum": [
                                    TARGET_KIND_AZURE_VM,
                                    TARGET_KIND_ARC_SERVER,
                                ]
                            },
                            "operation": {"const": OPERATION_INSTALL_PATCHES},
                            "action_version": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": 256,
                            },
                            "subscription_id": {
                                "type": "string",
                                "format": "uuid",
                            },
                            "approver": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": _MAX_AUDIT_IDENTITY_LENGTH,
                            },
                            "snapshot_hash": {
                                "type": "string",
                                "minLength": 64,
                                "maxLength": 64,
                            },
                        },
                    },
                },
            },
            "skill_chain": {"const": _skill_contract()},
            "reboot_setting": {"const": "IfRequired"},
            "maximum_duration": {"const": SRE_PATCH_MAXIMUM_DURATION},
            "requested_by": {
                "type": "string",
                "minLength": 1,
                "maxLength": _MAX_AUDIT_IDENTITY_LENGTH,
            },
            "approved_by": {
                "type": "string",
                "minLength": 1,
                "maxLength": _MAX_AUDIT_IDENTITY_LENGTH,
            },
            "operation": {"const": OPERATION_INSTALL_PATCHES},
        },
    }


def _build_sre_agent_patch_envelope(
    *,
    run: PatchRun,
    target: PatchTarget,
    subscription_id: str,
    patch_ids: Sequence[str],
    approval: Mapping[str, object],
) -> dict[str, object]:
    return {
        "schema_version": SRE_PATCH_ENVELOPE_VERSION,
        "run_id": run.run_id,
        "subscription_id": subscription_id,
        "target_id": target.target_id,
        "target_kind": target.inventory_kind,
        "patch_ids": list(patch_ids),
        "approval": dict(approval),
        "skill_chain": _skill_contract(),
        "reboot_setting": run.reboot_setting,
        "maximum_duration": SRE_PATCH_MAXIMUM_DURATION,
        "requested_by": run.requested_by,
        "approved_by": run.approved_by,
        "operation": run.operation,
    }


def _raise_envelope_drift() -> None:
    raise PatchExecutionUnavailable(
        "The SRE Agent outbound patch envelope drifted from its locked contract.",
        capability="sre_agent_patch_execution",
        provider_submitted=False,
        failure_class="internal_validation",
    )


def _validate_sre_agent_patch_envelope(payload: Mapping[str, object]) -> None:
    contract = sre_agent_patch_envelope_contract()
    required = contract.get("required")
    properties = contract.get("properties")
    if not isinstance(required, list) or not isinstance(properties, dict):
        _raise_envelope_drift()
    if set(payload) != set(required):
        _raise_envelope_drift()
    for field, raw_schema in properties.items():
        if not isinstance(raw_schema, Mapping):
            _raise_envelope_drift()
        _validate_contract_value(payload.get(field), raw_schema)
    approval = payload.get("approval")
    if not isinstance(approval, Mapping):
        _raise_envelope_drift()
    snapshot = approval.get("execution_snapshot")
    if not isinstance(snapshot, Mapping):
        _raise_envelope_drift()
    if (
        approval.get("approved_by") != payload.get("approved_by")
        or snapshot.get("target_id") != payload.get("target_id")
        or snapshot.get("target_kind") != payload.get("target_kind")
        or snapshot.get("patch_ids") != payload.get("patch_ids")
        or snapshot.get("operation") != payload.get("operation")
        or snapshot.get("subscription_id") != payload.get("subscription_id")
        or snapshot.get("approver") != payload.get("approved_by")
        or snapshot.get("snapshot_hash") != _approved_snapshot_hash(snapshot)
    ):
        _raise_envelope_drift()


def _validate_contract_value(value: object, schema: Mapping[str, object]) -> None:
    if "const" in schema and value != schema["const"]:
        _raise_envelope_drift()
    enum = schema.get("enum")
    if isinstance(enum, list) and value not in enum:
        _raise_envelope_drift()
    schema_type = schema.get("type")
    if schema_type == "string":
        if not isinstance(value, str):
            _raise_envelope_drift()
        minimum = schema.get("minLength")
        maximum = schema.get("maxLength")
        if isinstance(minimum, int) and len(value) < minimum:
            _raise_envelope_drift()
        if isinstance(maximum, int) and len(value) > maximum:
            _raise_envelope_drift()
    elif schema_type == "array":
        if not isinstance(value, list):
            _raise_envelope_drift()
        minimum = schema.get("minItems")
        maximum = schema.get("maxItems")
        if isinstance(minimum, int) and len(value) < minimum:
            _raise_envelope_drift()
        if isinstance(maximum, int) and len(value) > maximum:
            _raise_envelope_drift()
        if schema.get("uniqueItems") is True and len(set(value)) != len(value):
            _raise_envelope_drift()
        items = schema.get("items")
        if not isinstance(items, Mapping):
            _raise_envelope_drift()
        for item in value:
            _validate_contract_value(item, items)
    elif schema_type == "object":
        if not isinstance(value, Mapping):
            _raise_envelope_drift()
        required = schema.get("required")
        properties = schema.get("properties")
        if (
            not isinstance(required, list)
            or not isinstance(properties, Mapping)
            or schema.get("additionalProperties") is not False
            or set(value) != set(required)
            or set(properties) != set(required)
        ):
            _raise_envelope_drift()
        for field, child_schema in properties.items():
            if not isinstance(child_schema, Mapping):
                _raise_envelope_drift()
            _validate_contract_value(value.get(field), child_schema)


def _approved_snapshot_hash(snapshot: Mapping[str, object]) -> str:
    canonical = {
        field: snapshot.get(field)
        for field in SRE_PATCH_APPROVED_SNAPSHOT_IDENTITY_FIELDS
    }
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _approval_time(value: object, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value or ""))
    except ValueError as exc:
        raise PatchExecutionUnavailable(
            f"The upstream approval {label} is invalid.",
            capability="sre_agent_patch_execution",
            provider_submitted=False,
            failure_class="internal_validation",
        ) from exc
    if parsed.tzinfo is None:
        raise PatchExecutionUnavailable(
            f"The upstream approval {label} must include a timezone.",
            capability="sre_agent_patch_execution",
            provider_submitted=False,
            failure_class="internal_validation",
        )
    return parsed


def validate_sre_agent_endpoint(endpoint: str) -> str:
    """Validate one independently configured public HTTPS agent endpoint."""
    normalized = str(endpoint or "").strip().rstrip("/")
    parsed = urlsplit(normalized)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("The SRE Agent endpoint contains an invalid port.") from exc
    hostname = str(parsed.hostname or "").strip()
    if (
        parsed.scheme.casefold() != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or port is not None
        or hostname.casefold() == "localhost"
        or parsed.path not in {"", "/"}
    ):
        raise ValueError(
            "The SRE Agent endpoint must be public HTTPS without credentials, "
            "ports, query parameters, or fragments."
        )
    try:
        ip_address(hostname.strip("[]"))
    except ValueError:
        pass
    else:
        raise ValueError("The SRE Agent endpoint must use a configured DNS hostname.")
    return normalized


def sre_agent_trigger_identity(trigger_url: str) -> tuple[str, str]:
    """Return the validated trigger origin and exact trigger ID."""
    parsed = urlsplit(str(trigger_url or "").strip())
    if parsed.query or parsed.fragment or _TRIGGER_PATH_MARKER not in parsed.path:
        raise ValueError(
            "The SRE Agent trigger URL must use the documented trigger path."
        )
    prefix, trigger_id = parsed.path.split(_TRIGGER_PATH_MARKER, 1)
    if (
        not trigger_id
        or len(trigger_id) > _MAX_TRIGGER_ID_LENGTH
        or not _TRIGGER_ID.fullmatch(trigger_id)
    ):
        raise ValueError("The SRE Agent trigger URL must name exactly one trigger.")
    return (
        validate_sre_agent_endpoint(
            f"{parsed.scheme}://{parsed.netloc}{prefix}".rstrip("/")
        ),
        trigger_id,
    )


def sre_agent_endpoint(trigger_url: str) -> str:
    """Return the validated trigger origin encoded in a trigger URL."""
    return sre_agent_trigger_identity(trigger_url)[0]


def _arm_subscription_id(resource_id: str) -> str:
    parts = [part for part in resource_id.strip("/").split("/") if part]
    for index, part in enumerate(parts[:-1]):
        if part.casefold() == "subscriptions":
            return parts[index + 1]
    return ""


def _normalize_arm_id(resource_id: str) -> str:
    return str(resource_id or "").strip().rstrip("/")


def _scrub_authorization(
    response: httpx.Response | None,
    headers: dict[str, str],
) -> None:
    """Remove bearer material before raising a sanitized domain exception."""
    headers.pop("Authorization", None)
    request = getattr(response, "request", None)
    if request is not None:
        request.headers.pop("Authorization", None)


def _is_exact_target_resource_id(resource_id: str, inventory_kind: str) -> bool:
    if (
        "?" in resource_id
        or "#" in resource_id
        or "//" in resource_id
        or any(ord(character) < 32 for character in resource_id)
    ):
        return False
    parts = [part for part in resource_id.strip("/").split("/") if part]
    expected_provider = (
        "microsoft.compute"
        if inventory_kind == TARGET_KIND_AZURE_VM
        else "microsoft.hybridcompute"
    )
    expected_type = (
        "virtualmachines" if inventory_kind == TARGET_KIND_AZURE_VM else "machines"
    )
    return (
        len(parts) == 8
        and parts[0].casefold() == "subscriptions"
        and parts[2].casefold() == "resourcegroups"
        and parts[4].casefold() == "providers"
        and parts[5].casefold() == expected_provider
        and parts[6].casefold() == expected_type
        and all(parts[index] for index in (1, 3, 7))
        and all(_ARM_SEGMENT.fullmatch(part) for part in parts)
    )


class SreAgentPatchExecutionAdapter:
    """Submit one immutable VM or Arc patch selection to Azure SRE Agent."""

    name = SRE_AGENT_PROVIDER

    def __init__(
        self,
        credential: TokenCredential,
        *,
        trigger_url: str,
        trigger_id: str,
        trigger_origin: str,
        agent_endpoint: str,
        subscription_id: str,
        target_prefix: str,
        trigger_scope: str = SRE_AGENT_TRIGGER_SCOPE,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._credential = credential
        self._trigger_url = str(trigger_url or "").strip()
        observed_trigger_origin, observed_trigger_id = sre_agent_trigger_identity(
            self._trigger_url
        )
        self._trigger_id = str(trigger_id or "")
        self._trigger_origin = validate_sre_agent_endpoint(trigger_origin)
        self._agent_endpoint = validate_sre_agent_endpoint(agent_endpoint)
        if observed_trigger_origin != self._trigger_origin:
            raise ValueError(
                "The secret SRE Agent trigger URL does not match the configured "
                "trigger origin."
            )
        if (
            not self._trigger_id
            or len(self._trigger_id) > _MAX_TRIGGER_ID_LENGTH
            or not _TRIGGER_ID.fullmatch(self._trigger_id)
            or observed_trigger_id != self._trigger_id
        ):
            raise ValueError(
                "The secret SRE Agent trigger URL does not match the configured "
                "trigger ID."
            )
        self._subscription_id = str(subscription_id or "").strip()
        self._target_prefix = _normalize_arm_id(target_prefix)
        self._trigger_scope = str(trigger_scope or "").strip()
        self._client = client
        self._timeout = timeout
        self._now = now
        self._validate_configuration()

    def _validate_configuration(self) -> None:
        if not _SUBSCRIPTION_ID.fullmatch(self._subscription_id):
            raise ValueError("A valid SRE Agent subscription GUID is required.")
        if not self._trigger_scope:
            raise ValueError("A configured SRE Agent trigger token scope is required.")
        if not self._target_prefix.startswith("/subscriptions/"):
            raise ValueError(
                "The SRE Agent target prefix must be an Azure resource ID."
            )
        if (
            "?" in self._target_prefix
            or "#" in self._target_prefix
            or len(self._target_prefix) > _MAX_RESOURCE_ID_LENGTH
        ):
            raise ValueError("The SRE Agent target prefix is not a bounded ARM prefix.")
        if "/resourcegroups/" not in self._target_prefix.casefold():
            raise ValueError(
                "The SRE Agent target prefix must be narrower than a subscription."
            )
        if (
            _arm_subscription_id(self._target_prefix).casefold()
            != self._subscription_id.casefold()
        ):
            raise ValueError(
                "The SRE Agent target prefix must be inside the configured subscription."
            )

    def _token(self) -> str:
        try:
            token = self._credential.get_token(self._trigger_scope)
        except Exception as exc:
            raise PatchExecutionUnavailable(
                "Could not acquire an Azure SRE Agent trigger token.",
                capability="sre_agent_token",
                provider_submitted=False,
                failure_class="provider_authorization",
            ) from exc
        value = str(getattr(token, "token", "") or "")
        if not value:
            raise PatchExecutionUnavailable(
                "Azure credential returned an empty SRE Agent trigger token.",
                capability="sre_agent_token",
                provider_submitted=False,
                failure_class="provider_authorization",
            )
        return value

    def submit(self, run: PatchRun, target: PatchTarget) -> PatchExecutionResult:
        """Submit the exact validated selection to the configured HTTP trigger."""
        patch_ids = self._validate_submission(run, target)
        approval = self._validate_approval(run, target, patch_ids)
        payload = _build_sre_agent_patch_envelope(
            run=run,
            target=target,
            subscription_id=self._subscription_id,
            patch_ids=patch_ids,
            approval=approval,
        )
        _validate_sre_agent_patch_envelope(payload)
        access_token = self._token()
        headers = {
            "Authorization": "Bearer " + access_token,
            "Content-Type": "application/json",
        }
        client = self._client or httpx.Client(
            timeout=self._timeout,
            follow_redirects=False,
        )
        response: httpx.Response | None = None
        transport_failed = False
        try:
            response = client.post(
                self._trigger_url,
                headers=headers,
                json=payload,
                follow_redirects=False,
            )
        except httpx.HTTPError:
            transport_failed = True
        finally:
            if self._client is None:
                client.close()
        if transport_failed or response is None:
            _scrub_authorization(response, headers)
            access_token = ""
            raise PatchExecutionUnavailable(
                "Azure SRE Agent trigger submission could not be confirmed.",
                capability="sre_agent_trigger",
                provider_submitted=True,
                failure_class="submission_ambiguous",
            )

        if response.status_code != 202:
            failure_class = (
                "submission_ambiguous"
                if response.status_code == 408 or response.status_code >= 500
                else classify_azure_response_failure(response.status_code)
            )
            _scrub_authorization(response, headers)
            access_token = ""
            raise PatchExecutionUnavailable(
                f"Azure SRE Agent rejected the trigger request ({response.status_code}).",
                capability="sre_agent_trigger",
                provider_submitted=True,
                failure_class=failure_class,
            )
        response_payload: object = {}
        response_unreadable = False
        try:
            response_payload = response.json()
        except ValueError:
            response_unreadable = True
        if response_unreadable:
            _scrub_authorization(response, headers)
            access_token = ""
            raise PatchExecutionUnavailable(
                "Azure SRE Agent returned an unreadable accepted response.",
                capability="sre_agent_trigger",
                provider_submitted=True,
                failure_class="submission_ambiguous",
            )
        success = (
            response_payload.get("success")
            if isinstance(response_payload, dict)
            else None
        )
        raw_thread_id = (
            response_payload.get("threadId")
            if isinstance(response_payload, dict)
            else None
        )
        thread_id = raw_thread_id.strip() if isinstance(raw_thread_id, str) else ""
        if success is not True or not thread_id or len(thread_id) > 256:
            _scrub_authorization(response, headers)
            access_token = ""
            raise PatchExecutionUnavailable(
                "Azure SRE Agent did not return a confirmed thread handle.",
                capability="sre_agent_trigger",
                provider_submitted=True,
                failure_class="submission_ambiguous",
            )

        thread_url = (
            f"{self._agent_endpoint}/api/v1/threads/{quote(thread_id, safe='')}"
        )
        return PatchExecutionResult(
            provider=self.name,
            provider_job_id=thread_url,
            state="submitted",
            message=(
                "Accepted by Azure SRE Agent; provider completion remains subject "
                "to refreshed patch evidence reconciliation."
            ),
            details={
                "http_status": response.status_code,
                "thread_id": thread_id,
                "resource_id": target.target_id,
                "subscription_id": self._subscription_id,
                "schema_version": SRE_PATCH_ENVELOPE_VERSION,
            },
        )

    def _validate_submission(
        self,
        run: PatchRun,
        target: PatchTarget,
    ) -> list[str]:
        if run.operation != OPERATION_INSTALL_PATCHES:
            raise PatchExecutionUnavailable(
                "Azure SRE Agent patch execution supports install_patches only.",
                capability="sre_agent_patch_execution",
                provider_submitted=False,
                failure_class="target_precondition",
            )
        if target.inventory_kind not in {
            TARGET_KIND_AZURE_VM,
            TARGET_KIND_ARC_SERVER,
        }:
            raise PatchExecutionUnavailable(
                "Azure SRE Agent patch execution supports Azure VM and Arc targets only.",
                capability="sre_agent_patch_execution",
                provider_submitted=False,
                failure_class="target_precondition",
            )
        if (
            run.inventory_kind != target.inventory_kind
            or run.target_id != target.target_id
        ):
            raise PatchExecutionUnavailable(
                "The immutable patch run does not match the resolved target.",
                capability="sre_agent_patch_execution",
                provider_submitted=False,
                failure_class="internal_validation",
            )
        if not run.run_id or len(run.run_id) > _MAX_RUN_ID_LENGTH:
            raise PatchExecutionUnavailable(
                "The immutable patch run ID is missing or exceeds the supported bound.",
                capability="sre_agent_patch_execution",
                provider_submitted=False,
                failure_class="internal_validation",
            )
        if run.reboot_setting != "IfRequired":
            raise PatchExecutionUnavailable(
                "SRE Agent patch execution requires reboot setting IfRequired.",
                capability="sre_agent_patch_execution",
                provider_submitted=False,
                failure_class="internal_validation",
            )
        if (
            not run.requested_by
            or not run.approved_by
            or len(run.requested_by) > _MAX_AUDIT_IDENTITY_LENGTH
            or len(run.approved_by) > _MAX_AUDIT_IDENTITY_LENGTH
        ):
            raise PatchExecutionUnavailable(
                "The immutable patch run requires bounded requester and approver identities.",
                capability="sre_agent_patch_execution",
                provider_submitted=False,
                failure_class="internal_validation",
            )

        run_subscription = str(run.subscription_id or "").strip()
        target_subscription = str(target.subscription_id or "").strip()
        resource_subscription = _arm_subscription_id(target.target_id)
        configured = self._subscription_id.casefold()
        if (
            not run_subscription
            or not target_subscription
            or not resource_subscription
            or run_subscription.casefold() != configured
            or target_subscription.casefold() != configured
            or resource_subscription.casefold() != configured
        ):
            raise PatchExecutionUnavailable(
                "The run, target, and resource ID must match the configured subscription.",
                capability="sre_agent_patch_execution",
                provider_submitted=False,
                failure_class="target_precondition",
            )

        raw_target_id = str(target.target_id or "")
        target_id = _normalize_arm_id(raw_target_id)
        if raw_target_id != target_id:
            raise PatchExecutionUnavailable(
                "The target must use a canonical ARM resource ID without "
                "surrounding whitespace or a trailing slash.",
                capability="sre_agent_patch_execution",
                provider_submitted=False,
                failure_class="target_precondition",
            )
        if len(target_id) > _MAX_RESOURCE_ID_LENGTH:
            raise PatchExecutionUnavailable(
                "The target resource ID exceeds the supported bound.",
                capability="sre_agent_patch_execution",
                provider_submitted=False,
                failure_class="target_precondition",
            )
        prefix = self._target_prefix.casefold()
        normalized_target = target_id.casefold()
        if normalized_target != prefix and not normalized_target.startswith(
            f"{prefix}/"
        ):
            raise PatchExecutionUnavailable(
                "The target is outside the configured SRE Agent resource prefix.",
                capability="sre_agent_patch_execution",
                provider_submitted=False,
                failure_class="target_precondition",
            )
        if not _is_exact_target_resource_id(target_id, target.inventory_kind):
            raise PatchExecutionUnavailable(
                "The target must be an exact VM or Arc machine ARM resource ID "
                "without child resources.",
                capability="sre_agent_patch_execution",
                provider_submitted=False,
                failure_class="target_precondition",
            )

        patch_ids = [str(patch_id) for patch_id in run.patch_ids]
        if (
            not patch_ids
            or len(patch_ids) > _MAX_PATCH_IDS
            or len(set(patch_ids)) != len(patch_ids)
            or any(
                not patch_id
                or patch_id != patch_id.strip()
                or len(patch_id) > _MAX_PATCH_ID_LENGTH
                or _PATCH_ID.fullmatch(patch_id) is None
                for patch_id in patch_ids
            )
        ):
            raise PatchExecutionUnavailable(
                "Azure SRE Agent patch execution requires a bounded set of exact "
                "non-empty patch IDs.",
                capability="sre_agent_patch_execution",
                provider_submitted=False,
                failure_class="internal_validation",
            )
        if not set(patch_ids).issubset(target.available_patch_ids):
            raise PatchExecutionUnavailable(
                "The immutable patch selection is not available on the resolved target.",
                capability="sre_agent_patch_execution",
                provider_submitted=False,
                failure_class="target_precondition",
            )
        return patch_ids

    def _validate_approval(
        self,
        run: PatchRun,
        target: PatchTarget,
        patch_ids: Sequence[str],
    ) -> dict[str, object]:
        raw = run.details.get("approval_context")
        if not isinstance(raw, Mapping):
            _raise_envelope_drift()
        required = {
            "decision_id",
            "decision",
            "decided_at",
            "expires_at",
            "approved_by",
            "execution_snapshot",
        }
        if set(raw) != required:
            _raise_envelope_drift()
        snapshot = raw.get("execution_snapshot")
        if not isinstance(snapshot, Mapping):
            _raise_envelope_drift()
        if set(snapshot) != set(SRE_PATCH_APPROVED_SNAPSHOT_FIELDS):
            _raise_envelope_drift()
        decided_at = _approval_time(raw.get("decided_at"), "decided_at")
        expires_at = _approval_time(raw.get("expires_at"), "expires_at")
        now = self._now()
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        if (
            raw.get("decision") != "approved"
            or not str(raw.get("decision_id") or "")
            or raw.get("approved_by") != run.approved_by
            or not run.approved_by
            or decided_at > now
            or expires_at <= now
            or snapshot.get("target_id") != target.target_id
            or snapshot.get("patch_ids") != list(patch_ids)
            or snapshot.get("target_kind") != target.inventory_kind
            or snapshot.get("operation") != run.operation
            or not str(snapshot.get("action_version") or "")
            or snapshot.get("subscription_id") != run.subscription_id
            or snapshot.get("approver") != run.approved_by
            or snapshot.get("snapshot_hash") != _approved_snapshot_hash(snapshot)
        ):
            _raise_envelope_drift()
        return {
            "decision_id": str(raw["decision_id"]),
            "decision": "approved",
            "decided_at": str(raw["decided_at"]),
            "expires_at": str(raw["expires_at"]),
            "approved_by": str(raw["approved_by"]),
            "execution_snapshot": dict(snapshot),
        }


__all__ = [
    "SRE_AGENT_APPLICATION_ID",
    "SRE_AGENT_PROVIDER",
    "SRE_AGENT_THREAD_SCOPE",
    "SRE_AGENT_TRIGGER_SCOPE",
    "SRE_PATCH_APPLICABILITY_MAXIMUM_AGE",
    "SRE_PATCH_APPLICABILITY_MAXIMUM_ROWS",
    "SRE_PATCH_MAXIMUM_DURATION",
    "SRE_PATCH_READ_OUTPUT_SCHEMA_VERSION",
    "SRE_PATCH_READ_SKILL_NAME",
    "SRE_PATCH_READ_SKILL_OPERATION",
    "SRE_PATCH_READ_SKILL_SHA256",
    "SRE_PATCH_READ_SKILL_TOOLS",
    "SRE_PATCH_READ_SKILL_VERSION",
    "SRE_PATCH_WRITE_EVIDENCE_MAXIMUM_AGE",
    "SRE_PATCH_WRITE_OUTPUT_SCHEMA_VERSION",
    "SRE_PATCH_WRITE_SKILL_NAME",
    "SRE_PATCH_WRITE_SKILL_OPERATION",
    "SRE_PATCH_WRITE_SKILL_SHA256",
    "SRE_PATCH_WRITE_SKILL_TOOLS",
    "SRE_PATCH_WRITE_SKILL_VERSION",
    "SreAgentPatchExecutionAdapter",
    "sre_agent_endpoint",
    "sre_agent_patch_envelope_contract",
    "sre_agent_trigger_identity",
    "validate_sre_agent_endpoint",
]
