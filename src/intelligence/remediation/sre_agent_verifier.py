"""Read-only verification of Azure SRE Agent HTTP-trigger threads."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

import httpx

from operations.patching.azure_adapter import TokenCredential
from operations.patching.models import OPERATION_INSTALL_PATCHES
from operations.patching.sre_agent_adapter import (
    SRE_AGENT_PROVIDER,
    SRE_AGENT_THREAD_SCOPE,
    SRE_PATCH_WRITE_OUTPUT_SCHEMA_VERSION,
    SRE_PATCH_WRITE_SKILL_NAME,
    SRE_PATCH_WRITE_SKILL_VERSION,
    validate_sre_agent_endpoint,
)

from .execution_verifier import ExecutionVerificationUnavailable

_PROVIDER_OPERATION_FIELDS = frozenset(
    {
        "schema_version",
        "operation_id",
        "status",
        "skill_name",
        "skill_version",
        "operation",
        "target_id",
        "patch_ids",
    }
)


def _composite_thread_status(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize the production thread status without reading message prose."""
    status = payload.get("status")
    last_message = payload.get("lastMessage")
    if not isinstance(status, dict) or not isinstance(last_message, dict):
        return None
    actions = status.get("actionsStatus")
    incident = status.get("incidentStatus")
    if not isinstance(actions, dict) or not isinstance(incident, dict):
        return None
    complete = last_message.get("isComplete")
    critical = actions.get("hasCriticalActions")
    warning = actions.get("hasWarningActions")
    incident_status = incident.get("status")
    if (
        not isinstance(complete, bool)
        or not isinstance(critical, bool)
        or not isinstance(warning, bool)
        or not isinstance(incident_status, str)
    ):
        return None
    return {
        "last_message_complete": complete,
        "has_critical_actions": critical,
        "has_warning_actions": warning,
        "incident_status": incident_status.strip(),
    }


def _composite_outcome(composite: dict[str, Any]) -> tuple[str, str, str]:
    incident = " ".join(str(composite["incident_status"]).casefold().split())
    if incident in {"failed", "failure", "error"}:
        return (
            "failed",
            "Failed",
            "Azure SRE Agent reported a terminal failed incident status.",
        )
    if incident in {"cancelled", "canceled"}:
        return (
            "cancelled",
            "Cancelled",
            "Azure SRE Agent reported a terminal cancelled incident status.",
        )
    if (
        composite["has_critical_actions"] is True
        or composite["has_warning_actions"] is True
    ):
        return ("running", "Pending Review", "")
    if composite["last_message_complete"] is True:
        return ("succeeded", "Complete", "")
    return ("running", "In Progress", "")


def _submitted_operation(
    payload: dict[str, Any],
    execution_record: dict[str, Any],
) -> dict[str, Any] | None:
    """Return exact provider-owned write-submission evidence."""
    operation = payload.get("provider_operation")
    snapshot = execution_record.get("execution_snapshot")
    if (
        not isinstance(operation, dict)
        or set(operation) != _PROVIDER_OPERATION_FIELDS
        or not isinstance(snapshot, dict)
    ):
        return None
    operation_id = operation.get("operation_id")
    status = operation.get("status")
    patch_ids = operation.get("patch_ids")
    expected_patch_ids = snapshot.get("patch_ids")
    if (
        operation.get("schema_version") != SRE_PATCH_WRITE_OUTPUT_SCHEMA_VERSION
        or not isinstance(operation_id, str)
        or not operation_id.strip()
        or not isinstance(status, str)
        or " ".join(status.casefold().split())
        not in {"submitted", "running", "succeeded", "completed"}
        or operation.get("skill_name") != SRE_PATCH_WRITE_SKILL_NAME
        or operation.get("skill_version") != SRE_PATCH_WRITE_SKILL_VERSION
        or operation.get("operation") != OPERATION_INSTALL_PATCHES
        or operation.get("operation") != snapshot.get("operation")
        or operation.get("target_id") != snapshot.get("target_id")
        or not isinstance(patch_ids, list)
        or patch_ids != expected_patch_ids
    ):
        return None
    return {
        "schema_version": SRE_PATCH_WRITE_OUTPUT_SCHEMA_VERSION,
        "operation_id": operation_id.strip(),
        "status": " ".join(status.casefold().split()),
        "skill_name": SRE_PATCH_WRITE_SKILL_NAME,
        "skill_version": SRE_PATCH_WRITE_SKILL_VERSION,
        "operation": operation["operation"],
        "target_id": operation["target_id"],
        "patch_ids": list(patch_ids),
    }


def _completion_without_submission(
    *,
    verified_state: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    return {
        "verifiable": True,
        "outcome": "failed",
        "verified_state": verified_state,
        "failure_class": "submission_ambiguous",
        "failure_details": (
            "The SRE Agent thread completed without typed evidence that the "
            "exact approved write operation was submitted."
        ),
        "verification_evidence": evidence,
    }


def _scrub_authorization(
    response: httpx.Response | None,
    headers: dict[str, str],
) -> None:
    """Remove bearer material before raising a sanitized domain exception."""
    headers.pop("Authorization", None)
    request = getattr(response, "request", None)
    if request is not None:
        request.headers.pop("Authorization", None)


class SreAgentExecutionVerifier:
    """Poll one SRE Agent thread without treating model prose as evidence."""

    def __init__(
        self,
        *,
        credential: TokenCredential,
        agent_endpoint: str,
        thread_scope: str = SRE_AGENT_THREAD_SCOPE,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._credential = credential
        self._agent_endpoint = self._validate_endpoint(agent_endpoint)
        self._thread_scope = str(thread_scope or "").strip()
        self._client = client
        self._timeout = timeout
        if not self._thread_scope:
            raise ValueError("A configured SRE Agent thread token scope is required.")

    @staticmethod
    def _validate_endpoint(endpoint: str) -> str:
        return validate_sre_agent_endpoint(endpoint)

    def _token(self) -> str:
        try:
            token = self._credential.get_token(self._thread_scope)
        except Exception as exc:
            raise ExecutionVerificationUnavailable(
                "Could not acquire an Azure SRE Agent data-plane token.",
                capability="sre_agent_token",
            ) from exc
        value = str(getattr(token, "token", "") or "")
        if not value:
            raise ExecutionVerificationUnavailable(
                "Azure credential returned an empty SRE Agent data-plane token.",
                capability="sre_agent_token",
            )
        return value

    def verify(self, execution_record: dict[str, Any]) -> dict[str, Any]:
        """Map the documented thread status to the remediation outcome model."""
        if str(execution_record.get("provider") or "") != SRE_AGENT_PROVIDER:
            return {"verifiable": False, "reason": "not an SRE Agent execution"}
        thread_url = str(execution_record.get("provider_job_id") or "").strip()
        if not thread_url:
            return {"verifiable": False, "reason": "no provider job id"}
        expected_prefix = f"{self._agent_endpoint}/api/v1/threads/"
        parsed_thread = urlsplit(thread_url)
        parsed_endpoint = urlsplit(self._agent_endpoint)
        thread_id = (
            parsed_thread.path.removeprefix(f"{parsed_endpoint.path}/api/v1/threads/")
            if parsed_thread.path.startswith(
                f"{parsed_endpoint.path}/api/v1/threads/"
            )
            else ""
        )
        if (
            parsed_thread.scheme != parsed_endpoint.scheme
            or parsed_thread.netloc != parsed_endpoint.netloc
            or not thread_id
            or "/" in thread_id
            or parsed_thread.query
            or parsed_thread.fragment
            or not thread_url.startswith(expected_prefix)
        ):
            raise ExecutionVerificationUnavailable(
                "The SRE Agent thread handle is outside the configured agent endpoint.",
                capability="sre_agent_thread_validation",
            )

        access_token = self._token()
        headers = {"Authorization": "Bearer " + access_token}
        client = self._client or httpx.Client(
            timeout=self._timeout,
            follow_redirects=False,
        )
        response: httpx.Response | None = None
        transport_failed = False
        try:
            response = client.get(
                thread_url,
                headers=headers,
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
            raise ExecutionVerificationUnavailable(
                "Azure SRE Agent was unreachable while polling the execution thread.",
                capability="sre_agent_thread_poll",
            )
        if response.status_code != 200:
            status_code = response.status_code
            _scrub_authorization(response, headers)
            access_token = ""
            raise ExecutionVerificationUnavailable(
                f"Azure SRE Agent thread polling returned HTTP {status_code}.",
                capability="sre_agent_thread_poll",
            )

        try:
            payload = response.json()
        except ValueError:
            payload = {}
        raw_status = (
            str(payload.get("status") or "").strip()
            if isinstance(payload, dict) and isinstance(payload.get("status"), str)
            else ""
        )
        normalized = " ".join(raw_status.casefold().split())
        composite = (
            _composite_thread_status(payload) if isinstance(payload, dict) else None
        )
        submitted_operation = (
            _submitted_operation(payload, execution_record)
            if isinstance(payload, dict)
            else None
        )
        evidence = {"thread_status": composite or raw_status or "unknown"}
        if submitted_operation is not None:
            evidence["provider_operation"] = submitted_operation
        if composite is not None:
            outcome, verified_state, failure_details = _composite_outcome(composite)
            if outcome == "succeeded" and submitted_operation is None:
                return _completion_without_submission(
                    verified_state="CompleteWithoutSubmissionProof",
                    evidence=evidence,
                )
            result = {
                "verifiable": True,
                "outcome": outcome,
                "verified_state": verified_state,
                "verification_evidence": evidence,
            }
            if outcome == "running":
                result["provider_active"] = True
            if failure_details:
                result["failure_details"] = failure_details
            return result
        if normalized in {"complete", "success", "succeeded"}:
            if submitted_operation is None:
                return _completion_without_submission(
                    verified_state=raw_status,
                    evidence=evidence,
                )
            return {
                "verifiable": True,
                "outcome": "succeeded",
                "verified_state": raw_status,
                "verification_evidence": evidence,
            }
        if normalized in {"failed_without_action", "blocked_no_action"}:
            return {
                "verifiable": True,
                "outcome": "failed",
                "verified_state": raw_status,
                "failure_class": "provider_rejected",
                "failure_details": (
                    "Azure SRE Agent completed without submitting the approved "
                    "patch operation."
                ),
                "verification_evidence": evidence,
            }
        if normalized == "pending user input":
            return {
                "verifiable": True,
                "outcome": "running",
                "verified_state": "Pending Review",
                "provider_active": True,
                "verification_evidence": evidence,
            }
        return {
            "verifiable": True,
            "outcome": "running",
            "verified_state": raw_status or "unknown",
            "verification_evidence": evidence,
        }


__all__ = ["SreAgentExecutionVerifier"]
