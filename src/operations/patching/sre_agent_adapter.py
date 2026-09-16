"""Azure SRE Agent execution adapter for exact approved patch selections.

The adapter invokes one pre-created HTTP trigger. It does not create or
configure the trigger, discover patches, widen the approved selection, or
accept an operator credential.
"""

from __future__ import annotations

import re
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
SRE_PATCH_ENVELOPE_VERSION = "1.0"
_TRIGGER_PATH_MARKER = "/api/v1/httptriggers/trigger/"
_MAX_PATCH_IDS = 256
_MAX_PATCH_ID_LENGTH = 256
_MAX_AUDIT_IDENTITY_LENGTH = 320
_MAX_RESOURCE_ID_LENGTH = 2048
_MAX_RUN_ID_LENGTH = 128
_MAX_TRIGGER_ID_LENGTH = 256
_REBOOT_SETTINGS = frozenset({"IfRequired", "Never", "Always"})
_TRIGGER_ID = re.compile(r"^[A-Za-z0-9._~-]+$")
_SUBSCRIPTION_ID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


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
        raise ValueError("The SRE Agent trigger URL must use the documented trigger path.")
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
        "virtualmachines"
        if inventory_kind == TARGET_KIND_AZURE_VM
        else "machines"
    )
    return (
        len(parts) == 8
        and parts[0].casefold() == "subscriptions"
        and parts[2].casefold() == "resourcegroups"
        and parts[4].casefold() == "providers"
        and parts[5].casefold() == expected_provider
        and parts[6].casefold() == expected_type
        and all(parts[index] for index in (1, 3, 7))
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
        self._validate_configuration()

    def _validate_configuration(self) -> None:
        if not _SUBSCRIPTION_ID.fullmatch(self._subscription_id):
            raise ValueError("A valid SRE Agent subscription GUID is required.")
        if not self._trigger_scope:
            raise ValueError("A configured SRE Agent trigger token scope is required.")
        if not self._target_prefix.startswith("/subscriptions/"):
            raise ValueError("The SRE Agent target prefix must be an Azure resource ID.")
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
        if _arm_subscription_id(self._target_prefix).casefold() != self._subscription_id.casefold():
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
        payload = {
            "schema_version": SRE_PATCH_ENVELOPE_VERSION,
            "run_id": run.run_id,
            "subscription_id": self._subscription_id,
            "target_id": target.target_id,
            "target_kind": target.inventory_kind,
            "patch_ids": patch_ids,
            "reboot_setting": run.reboot_setting,
            "requested_by": run.requested_by,
            "approved_by": run.approved_by,
            "operation": run.operation,
        }
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
        if run.inventory_kind != target.inventory_kind or run.target_id != target.target_id:
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
        if run.reboot_setting not in _REBOOT_SETTINGS:
            raise PatchExecutionUnavailable(
                "The immutable patch run contains an unsupported reboot setting.",
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
        if normalized_target != prefix and not normalized_target.startswith(f"{prefix}/"):
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


__all__ = [
    "SRE_AGENT_APPLICATION_ID",
    "SRE_AGENT_PROVIDER",
    "SRE_AGENT_THREAD_SCOPE",
    "SRE_AGENT_TRIGGER_SCOPE",
    "SreAgentPatchExecutionAdapter",
    "sre_agent_endpoint",
    "sre_agent_trigger_identity",
    "validate_sre_agent_endpoint",
]
