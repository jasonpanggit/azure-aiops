"""Read-only verification of Azure SRE Agent HTTP-trigger threads."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from operations.patching.azure_adapter import ARM_ENDPOINT, ARM_SCOPE, TokenCredential
from operations.patching.models import (
    OPERATION_INSTALL_PATCHES,
    TARGET_KIND_ARC_SERVER,
    TARGET_KIND_AZURE_VM,
)
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

_TERMINAL_FAILED_INCIDENT_STATUSES = frozenset(
    {
        "failed",
        "failure",
        "error",
        "failed_without_action",
        "blocked_no_action",
    }
)

_TERMINAL_CANCELLED_INCIDENT_STATUSES = frozenset({"cancelled", "canceled"})

# Only an explicitly typed terminal-success incident status ends the thread
# without submission evidence; message-level completion never does.
_TERMINAL_SUCCEEDED_INCIDENT_STATUSES = frozenset(
    {
        "complete",
        "completed",
        "succeeded",
        "success",
        "resolved",
    }
)

_ACTIVITY_LOG_API_VERSION = "2015-04-01"
_ACTIVITY_LOG_ACCEPTED_STATUSES = frozenset({"accepted", "succeeded", "success"})
_ACTIVITY_LOG_QUERY_LOOKBACK = timedelta(minutes=2)
_ACTIVITY_LOG_QUERY_LOOKAHEAD = timedelta(minutes=5)


def _expected_review_command(execution_record: dict[str, Any]) -> str:
    """Build the only write command permitted by the approved snapshot."""
    snapshot = execution_record.get("execution_snapshot")
    if not isinstance(snapshot, dict):
        return ""
    target_id = snapshot.get("target_id")
    target_kind = snapshot.get("target_kind")
    patch_ids = snapshot.get("patch_ids")
    if (
        snapshot.get("operation") != OPERATION_INSTALL_PATCHES
        or not isinstance(target_id, str)
        or not target_id.strip()
        or not isinstance(patch_ids, list)
        or not patch_ids
        or any(not isinstance(patch_id, str) or not patch_id for patch_id in patch_ids)
    ):
        return ""
    if target_kind == "Azure VM":
        return (
            f"az vm install-patches --ids {target_id} "
            f"--kb-numbers-to-include {' '.join(patch_ids)} "
            "--maximum-duration PT2H --reboot-setting IfRequired --no-wait"
        )
    if target_kind == "Arc-enabled server":
        parameters = json.dumps(
            {"kbNumbersToInclude": patch_ids},
            separators=(",", ":"),
        )
        return (
            f"az connectedmachine install-patches --ids {target_id} "
            f"--windows-parameters '{parameters}' "
            "--maximum-duration PT2H --reboot-setting IfRequired --no-wait true"
        )
    return ""


def _pending_cli_execution(
    payload: dict[str, Any],
    execution_record: dict[str, Any],
) -> dict[str, Any] | None:
    """Project only the exact pending Review-mode CLI execution."""
    last_message = payload.get("lastMessage")
    if not isinstance(last_message, dict):
        return None
    execution = last_message.get("azCliExecution")
    expected_command = _expected_review_command(execution_record)
    if not isinstance(execution, dict) or not expected_command:
        return None
    execution_id = execution.get("id")
    command = execution.get("command")
    status = " ".join(str(execution.get("status") or "").casefold().split())
    if (
        status not in {"pending", "pending authorization", "pendingauthorization"}
        or not isinstance(execution_id, str)
        or not execution_id.strip()
        or len(execution_id) > 256
        or command != expected_command
        or execution.get("expiredByTimeout") is not False
        or execution.get("output") is not None
        or execution.get("error") is not None
        or execution.get("startedTimestamp") is not None
        or execution.get("completedTimestamp") is not None
    ):
        return None
    original_call = execution.get("originalFunctionCall")
    if not isinstance(original_call, str) or len(original_call) > 16_384:
        return None
    try:
        parsed_call = json.loads(original_call)
    except ValueError:
        return None
    if (
        not isinstance(parsed_call, dict)
        or parsed_call.get("Name") != "RunAzCliWriteCommands"
        or parsed_call.get("Arguments") != {"command": expected_command}
        or parsed_call.get("InformationalOnly") is not False
    ):
        return None
    required_scopes = execution.get("requiredScopes")
    if required_scopes is not None:
        if isinstance(required_scopes, str):
            if not required_scopes.strip() or len(required_scopes) > 2_048:
                return None
            required_scopes = required_scopes.strip()
        elif isinstance(required_scopes, list):
            if (
                not 1 <= len(required_scopes) <= 32
                or any(
                    not isinstance(scope, str)
                    or not scope.strip()
                    or len(scope) > 256
                    for scope in required_scopes
                )
            ):
                return None
            required_scopes = [scope.strip() for scope in required_scopes]
        else:
            return None
    return {
        "kind": "az_cli_execution",
        "execution_id": execution_id.strip(),
        "status": status,
        "command": expected_command,
        "required_scopes": required_scopes,
    }


def _completed_write_execution(
    payload: dict[str, Any],
    execution_record: dict[str, Any],
) -> dict[str, Any] | None:
    """Project an exact completed write-tool call without treating it as proof."""
    last_message = payload.get("lastMessage")
    if not isinstance(last_message, dict):
        return None
    execution = last_message.get("azCliExecution")
    expected_command = _expected_review_command(execution_record)
    if not isinstance(execution, dict) or not expected_command:
        return None
    execution_id = execution.get("id")
    command = execution.get("command")
    status = " ".join(str(execution.get("status") or "").casefold().split())
    if (
        status not in {"completed", "complete", "succeeded", "success"}
        or not isinstance(execution_id, str)
        or not execution_id.strip()
        or len(execution_id) > 256
        or command != expected_command
        or execution.get("expiredByTimeout") is not False
        or execution.get("error") not in {None, ""}
    ):
        return None
    original_call = execution.get("originalFunctionCall")
    if not isinstance(original_call, str) or len(original_call) > 16_384:
        return None
    try:
        parsed_call = json.loads(original_call)
    except ValueError:
        return None
    if (
        not isinstance(parsed_call, dict)
        or parsed_call.get("Name") != "RunAzCliWriteCommands"
        or parsed_call.get("Arguments") != {"command": expected_command}
        or parsed_call.get("InformationalOnly") is not False
    ):
        return None
    started_at = _parse_timestamp(execution.get("startedTimestamp"))
    completed_at = _parse_timestamp(execution.get("completedTimestamp"))
    if started_at is None:
        return None
    if completed_at is not None and completed_at < started_at:
        return None
    return {
        "kind": "az_cli_execution",
        "execution_id": execution_id.strip(),
        "status": status,
        "command": expected_command,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat() if completed_at else "",
    }


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


def _pending_user_question(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Project the typed SRE review question without parsing message prose."""
    last_message = payload.get("lastMessage")
    if not isinstance(last_message, dict):
        return None
    question = last_message.get("userQuestion")
    if not isinstance(question, dict):
        return None
    question_id = question.get("questionId")
    question_text = question.get("question")
    options = question.get("options")
    status = " ".join(str(question.get("status") or "").casefold().split())
    if (
        status != "pending"
        or not isinstance(question_id, str)
        or not question_id.strip()
        or len(question_id) > 256
        or not isinstance(question_text, str)
        or not question_text.strip()
        or len(question_text) > 1_000
        or question.get("allowFreeText") is not False
        or not isinstance(options, list)
        or not 1 <= len(options) <= 32
    ):
        return None
    labels: list[str] = []
    for option in options:
        if not isinstance(option, dict):
            return None
        label = option.get("label")
        if (
            not isinstance(label, str)
            or not label.strip()
            or len(label) > 128
        ):
            return None
        labels.append(label.strip())
    if labels != ["Approve submission", "Decline"]:
        return None
    return {
        "question_id": question_id.strip(),
        "question": question_text.strip(),
        "options": labels,
        "allow_free_text": False,
    }


def _composite_outcome(
    composite: dict[str, Any],
    *,
    has_submitted_operation: bool,
) -> tuple[str, str, str]:
    """Map a composite thread status to an outcome without inferring terminality.

    ``lastMessage.isComplete`` only states that the *current* message finished
    streaming; the provider thread stays active and approvable afterwards (the
    agent can still read applicability, present Review commands, and type a
    terminal status). Terminality therefore requires either an explicit typed
    terminal incident status or exact typed write-submission evidence.
    """
    incident = " ".join(str(composite["incident_status"]).casefold().split())
    if incident in _TERMINAL_FAILED_INCIDENT_STATUSES:
        return (
            "failed",
            "Failed",
            "Azure SRE Agent reported a terminal failed incident status.",
        )
    if incident in _TERMINAL_CANCELLED_INCIDENT_STATUSES:
        return (
            "cancelled",
            "Cancelled",
            "Azure SRE Agent reported a terminal cancelled incident status.",
        )
    if has_submitted_operation or incident in _TERMINAL_SUCCEEDED_INCIDENT_STATUSES:
        return ("succeeded", "Complete", "")
    if (
        composite["has_critical_actions"] is True
        or composite["has_warning_actions"] is True
    ):
        return ("running", "Pending Review", "")
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


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _activity_log_operation_name(execution_record: dict[str, Any]) -> str:
    snapshot = execution_record.get("execution_snapshot")
    if not isinstance(snapshot, dict):
        return ""
    if snapshot.get("operation") != OPERATION_INSTALL_PATCHES:
        return ""
    if snapshot.get("target_kind") == TARGET_KIND_AZURE_VM:
        return "Microsoft.Compute/virtualMachines/installPatches/action"
    if snapshot.get("target_kind") == TARGET_KIND_ARC_SERVER:
        return "Microsoft.HybridCompute/machines/installPatches/action"
    return ""


def _resource_id_equal(left: Any, right: Any) -> bool:
    left_text = str(left or "").strip().rstrip("/").casefold()
    right_text = str(right or "").strip().rstrip("/").casefold()
    return bool(left_text and left_text == right_text)


def _subscription_id(execution_record: dict[str, Any]) -> str:
    scope = execution_record.get("scope_attributes")
    if isinstance(scope, dict):
        value = str(scope.get("subscription") or "").strip()
        if value:
            return value
    snapshot = execution_record.get("execution_snapshot")
    target_id = str(
        snapshot.get("target_id") if isinstance(snapshot, dict) else ""
    ).strip()
    parts = [part for part in target_id.split("/") if part]
    for index, part in enumerate(parts):
        if part.casefold() == "subscriptions" and index + 1 < len(parts):
            return parts[index + 1]
    return ""


def _activity_log_rows(payload: object) -> list[object] | None:
    if isinstance(payload, dict) and set(payload).issubset({"value", "nextLink"}):
        rows = payload.get("value")
        if isinstance(rows, list):
            return rows
    return None


def _activity_log_event_time(row: dict[str, Any]) -> datetime | None:
    return _parse_timestamp(
        row.get("eventTimestamp")
        or row.get("eventSubmissionTimestamp")
        or row.get("submissionTimestamp")
    )


def _activity_log_field(row: dict[str, Any], name: str) -> str:
    value = row.get(name)
    if isinstance(value, dict):
        value = value.get("value") or value.get("localizedValue")
    return str(value or "").strip()


def _latest_attempt_timestamp(execution_record: dict[str, Any]) -> datetime | None:
    attempts = execution_record.get("attempts")
    if not isinstance(attempts, list) or not attempts:
        return _parse_timestamp(execution_record.get("created_at"))
    latest = attempts[-1]
    if not isinstance(latest, dict):
        return _parse_timestamp(execution_record.get("created_at"))
    transitions = latest.get("transitions")
    candidates: list[datetime] = []
    if isinstance(transitions, list):
        for transition in transitions:
            if not isinstance(transition, dict):
                continue
            status = str(transition.get("status") or "").casefold()
            if status not in {"running", "retrying"}:
                continue
            parsed = _parse_timestamp(transition.get("timestamp"))
            if parsed is not None:
                candidates.append(parsed)
    if candidates:
        return max(candidates)
    return _parse_timestamp(latest.get("created_at")) or _parse_timestamp(
        execution_record.get("created_at")
    )


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
        arm_scope: str = ARM_SCOPE,
        arm_endpoint: str = ARM_ENDPOINT,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._credential = credential
        self._agent_endpoint = self._validate_endpoint(agent_endpoint)
        self._thread_scope = str(thread_scope or "").strip()
        self._arm_scope = str(arm_scope or "").strip()
        self._arm_endpoint = str(arm_endpoint or "").rstrip("/")
        self._client = client
        self._timeout = timeout
        if not self._thread_scope:
            raise ValueError("A configured SRE Agent thread token scope is required.")
        if not self._arm_scope:
            raise ValueError("A configured Azure ARM token scope is required.")
        if urlsplit(self._arm_endpoint).scheme != "https":
            raise ValueError("Azure ARM endpoint must be HTTPS.")

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

    def _arm_token(self) -> str:
        try:
            token = self._credential.get_token(self._arm_scope)
        except Exception as exc:
            raise ExecutionVerificationUnavailable(
                "Could not acquire an Azure management token.",
                capability="sre_agent_activity_log_token",
            ) from exc
        value = str(getattr(token, "token", "") or "")
        if not value:
            raise ExecutionVerificationUnavailable(
                "Azure credential returned an empty management token.",
                capability="sre_agent_activity_log_token",
            )
        return value

    def _thread_id(self, execution_record: dict[str, Any]) -> tuple[str, str]:
        """Return the validated persisted thread URL and its provider ID."""
        if str(execution_record.get("provider") or "") != SRE_AGENT_PROVIDER:
            raise ExecutionVerificationUnavailable(
                "The execution is not an Azure SRE Agent request.",
                capability="sre_agent_thread_validation",
            )
        thread_url = str(execution_record.get("provider_job_id") or "").strip()
        if not thread_url:
            raise ExecutionVerificationUnavailable(
                "The Azure SRE Agent execution has no thread handle.",
                capability="sre_agent_thread_validation",
            )
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
        return thread_url, thread_id

    @staticmethod
    def _approval_rows(payload: object) -> list[object] | None:
        """Normalize documented list responses and common collection envelopes."""
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for field in ("approvals", "items", "value"):
                if set(payload) == {field} and isinstance(payload[field], list):
                    return payload[field]
        return None

    @classmethod
    def _pending_approval_ids(cls, payload: object) -> list[str]:
        """Read only bounded provider-owned approval IDs from the pending list."""
        rows = cls._approval_rows(payload)
        if rows is None or not rows or len(rows) > 32:
            return []
        approval_ids: list[str] = []
        for row in rows:
            if not isinstance(row, dict):
                return []
            raw_id = row.get("id", row.get("approvalId"))
            approval_id = raw_id.strip() if isinstance(raw_id, str) else ""
            status = str(row.get("status") or row.get("state") or "pending")
            normalized_status = " ".join(status.casefold().split())
            if (
                not approval_id
                or len(approval_id) > 256
                or normalized_status
                not in {
                    "pending",
                    "pending user input",
                    "requested",
                    "waiting for approval",
                }
            ):
                return []
            approval_ids.append(approval_id)
        return approval_ids

    def _recover_provider_operation_from_activity_log(
        self,
        execution_record: dict[str, Any],
        *,
        completed_write: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        snapshot = execution_record.get("execution_snapshot")
        if not isinstance(snapshot, dict):
            return None
        target_id = str(snapshot.get("target_id") or "").strip()
        operation_name = _activity_log_operation_name(execution_record)
        subscription_id = _subscription_id(execution_record)
        attempt_time = (
            _parse_timestamp(completed_write.get("started_at"))
            if isinstance(completed_write, dict)
            else None
        )
        if attempt_time is None:
            attempt_time = _latest_attempt_timestamp(execution_record)
        if not target_id or not operation_name or not subscription_id or attempt_time is None:
            return None

        start_time = attempt_time - _ACTIVITY_LOG_QUERY_LOOKBACK
        end_time = attempt_time + _ACTIVITY_LOG_QUERY_LOOKAHEAD
        filter_text = (
            f"eventTimestamp ge '{start_time.isoformat().replace('+00:00', 'Z')}' "
            f"and eventTimestamp le '{end_time.isoformat().replace('+00:00', 'Z')}' "
            f"and resourceUri eq '{target_id}'"
        )
        activity_url = (
            f"{self._arm_endpoint}/subscriptions/{quote(subscription_id, safe='')}"
            "/providers/microsoft.insights/eventtypes/management/values"
        )
        access_token = self._arm_token()
        headers = {"Authorization": "Bearer " + access_token}
        client = self._client or httpx.Client(
            timeout=self._timeout,
            follow_redirects=False,
        )
        response: httpx.Response | None = None
        try:
            response = client.get(
                activity_url,
                headers=headers,
                params={
                    "api-version": _ACTIVITY_LOG_API_VERSION,
                    "$filter": filter_text,
                },
                follow_redirects=False,
            )
        except httpx.HTTPError:
            _scrub_authorization(response, headers)
            access_token = ""
            return None
        finally:
            if self._client is None:
                client.close()
        if response.status_code != 200:
            _scrub_authorization(response, headers)
            access_token = ""
            return None
        try:
            rows = _activity_log_rows(response.json())
        except ValueError:
            rows = None
        _scrub_authorization(response, headers)
        access_token = ""
        if rows is None or not 1 <= len(rows) <= 256:
            return None

        matches: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                return None
            event_time = _activity_log_event_time(row)
            resource_id = _activity_log_field(row, "resourceId") or _activity_log_field(
                row, "resourceUri"
            )
            row_operation = _activity_log_field(row, "operationName")
            status = _activity_log_field(row, "status").casefold()
            correlation_id = str(row.get("correlationId") or "").strip()
            operation_id = (
                str(row.get("operationId") or row.get("eventDataId") or "").strip()
            )
            if (
                event_time is not None
                and start_time <= event_time <= end_time
                and _resource_id_equal(resource_id, target_id)
                and row_operation.casefold() == operation_name.casefold()
                and status in _ACTIVITY_LOG_ACCEPTED_STATUSES
                and correlation_id
            ):
                matches.append(
                    {
                        "event_time": event_time,
                        "operation_id": operation_id or correlation_id,
                        "correlation_id": correlation_id,
                        "status": status,
                    }
                )
        correlation_ids = {match["correlation_id"] for match in matches}
        if len(matches) != 1 or len(correlation_ids) != 1:
            return None
        match = matches[0]
        provider_operation = {
            "schema_version": SRE_PATCH_WRITE_OUTPUT_SCHEMA_VERSION,
            "operation_id": match["operation_id"],
            "status": "submitted",
            "skill_name": SRE_PATCH_WRITE_SKILL_NAME,
            "skill_version": SRE_PATCH_WRITE_SKILL_VERSION,
            "operation": OPERATION_INSTALL_PATCHES,
            "target_id": target_id,
            "patch_ids": list(snapshot.get("patch_ids") or []),
        }
        activity_log_recovery = {
            "source": "azure_activity_log",
            "correlation_id": match["correlation_id"],
            "operation_id": match["operation_id"],
            "operation_name": operation_name,
            "target_id": target_id,
            "status": match["status"],
            "event_time": match["event_time"].isoformat(),
            "query_start": start_time.isoformat(),
            "query_end": end_time.isoformat(),
        }
        return provider_operation, activity_log_recovery

    def cancel(
        self,
        execution_record: dict[str, Any],
        *,
        requested_by: str = "",
    ) -> dict[str, Any]:
        """Reject every pending approval for the exact persisted SRE thread."""
        _thread_url, thread_id = self._thread_id(execution_record)
        current = self.verify(execution_record)
        current_evidence = current.get("verification_evidence") or {}
        if (
            current.get("outcome") != "running"
            or current.get("provider_active") is not True
            or current_evidence.get("approval_pending") is not True
            or current_evidence.get("provider_operation")
        ):
            raise ExecutionVerificationUnavailable(
                "Azure SRE Agent did not confirm that this thread is awaiting "
                "approval without a submitted patch operation.",
                capability="sre_agent_approval_cancel",
            )
        provider_review = current_evidence.get("provider_review")
        if isinstance(provider_review, dict):
            review_execution_id = str(provider_review.get("execution_id") or "")
            self._post_review_action(
                execution_record,
                provider_review=provider_review,
                action="cancel",
                actor=requested_by,
            )
            refreshed = self.verify(execution_record)
            refreshed_evidence = refreshed.get("verification_evidence") or {}
            if (
                refreshed.get("outcome") == "succeeded"
                or refreshed_evidence.get("provider_operation")
                or refreshed_evidence.get("provider_review") == provider_review
            ):
                raise ExecutionVerificationUnavailable(
                    "Azure SRE Agent did not confirm cancellation of the exact "
                    "pending CLI review.",
                    capability="sre_agent_approval_cancel",
                )
            return {
                "cancelled": True,
                "thread_id": thread_id,
                "approval_ids": [review_execution_id],
                "thread_state": refreshed.get("verified_state") or "unknown",
            }
        access_token = self._token()
        headers = {
            "Authorization": "Bearer " + access_token,
            "Content-Type": "application/json",
        }
        approvals_url = (
            f"{self._agent_endpoint}/api/v1/approvals/{quote(thread_id, safe='')}"
        )
        client = self._client or httpx.Client(
            timeout=self._timeout,
            follow_redirects=False,
        )
        response: httpx.Response | None = None
        try:
            response = client.get(
                approvals_url,
                headers=headers,
                follow_redirects=False,
            )
            if response.status_code != 200:
                raise ExecutionVerificationUnavailable(
                    f"Azure SRE Agent approval lookup returned HTTP {response.status_code}.",
                    capability="sre_agent_approval_cancel",
                )
            try:
                pending_ids = self._pending_approval_ids(response.json())
            except ValueError:
                pending_ids = []
            if not pending_ids:
                raise ExecutionVerificationUnavailable(
                    "Azure SRE Agent did not return a typed pending approval to cancel.",
                    capability="sre_agent_approval_cancel",
                )
            for approval_id in pending_ids:
                decision_url = (
                    f"{approvals_url}/{quote(approval_id, safe='')}/decision"
                )
                response = client.post(
                    decision_url,
                    headers=headers,
                    json={"decision": "reject"},
                    follow_redirects=False,
                )
                if response.status_code not in {200, 202, 204}:
                    raise ExecutionVerificationUnavailable(
                        "Azure SRE Agent did not confirm the approval rejection "
                        f"(HTTP {response.status_code}).",
                        capability="sre_agent_approval_cancel",
                    )
            response = client.get(
                approvals_url,
                headers=headers,
                follow_redirects=False,
            )
            if response.status_code != 200:
                raise ExecutionVerificationUnavailable(
                    "Azure SRE Agent could not confirm cancellation.",
                    capability="sre_agent_approval_cancel",
                )
            try:
                remaining = response.json()
            except ValueError:
                remaining = None
            remaining_rows = self._approval_rows(remaining)
            if remaining_rows != []:
                raise ExecutionVerificationUnavailable(
                    "Azure SRE Agent still reports an approvable action for this thread.",
                    capability="sre_agent_approval_cancel",
                )
            terminal = self.verify(execution_record)
            terminal_evidence = terminal.get("verification_evidence") or {}
            if (
                terminal.get("outcome") == "succeeded"
                or terminal_evidence.get("provider_operation")
            ):
                raise ExecutionVerificationUnavailable(
                    "Azure SRE Agent reported patch submission while cancellation "
                    "was being confirmed.",
                    capability="sre_agent_approval_cancel",
                )
            return {
                "cancelled": True,
                "thread_id": thread_id,
                "approval_ids": pending_ids,
                "thread_state": terminal.get("verified_state") or "unknown",
            }
        except httpx.HTTPError:
            _scrub_authorization(response, headers)
            access_token = ""
            raise ExecutionVerificationUnavailable(
                "Azure SRE Agent was unreachable while cancelling the pending approval.",
                capability="sre_agent_approval_cancel",
            ) from None
        finally:
            _scrub_authorization(response, headers)
            access_token = ""
            if self._client is None:
                client.close()

    def approve_review(
        self,
        execution_record: dict[str, Any],
        *,
        requested_by: str,
    ) -> dict[str, Any]:
        """Approve the exact typed SRE CLI review, never a prose instruction."""
        current = self.verify(execution_record)
        evidence = current.get("verification_evidence") or {}
        provider_review = evidence.get("provider_review")
        if (
            current.get("outcome") != "running"
            or current.get("provider_active") is not True
            or evidence.get("approval_pending") is not True
            or not isinstance(provider_review, dict)
            or evidence.get("provider_operation")
        ):
            raise ExecutionVerificationUnavailable(
                "Azure SRE Agent did not return an exact pending CLI review.",
                capability="sre_agent_review_approve",
            )
        return self._post_review_action(
            execution_record,
            provider_review=provider_review,
            action="run",
            actor=requested_by,
        )

    def _post_review_action(
        self,
        execution_record: dict[str, Any],
        *,
        provider_review: dict[str, Any],
        action: str,
        actor: str,
    ) -> dict[str, Any]:
        """Submit one action against the freshly verified Review object."""
        if action not in {"run", "cancel"}:
            raise ValueError("Unsupported SRE Agent review action.")
        _thread_url, thread_id = self._thread_id(execution_record)
        execution_id = str(provider_review.get("execution_id") or "").strip()
        required_scopes = provider_review.get("required_scopes")
        if not execution_id or provider_review.get("kind") != "az_cli_execution":
            raise ExecutionVerificationUnavailable(
                "Azure SRE Agent CLI review identity is invalid.",
                capability="sre_agent_review_action",
            )
        access_token = self._token()
        headers = {
            "Authorization": "Bearer " + access_token,
            "Content-Type": "application/json",
        }
        if isinstance(required_scopes, str) and required_scopes:
            headers["x-sreagent-obo-scope"] = required_scopes
        elif isinstance(required_scopes, list) and required_scopes:
            headers["x-sreagent-obo-scope"] = " ".join(required_scopes)
        action_url = (
            f"{self._agent_endpoint}/api/v1/azCliExecution/"
            f"{quote(thread_id, safe='')}/{quote(execution_id, safe='')}/action"
        )
        client = self._client or httpx.Client(
            timeout=self._timeout,
            follow_redirects=False,
        )
        response: httpx.Response | None = None
        try:
            response = client.post(
                action_url,
                headers=headers,
                json={
                    "action": action,
                    "user": actor,
                    "ApproveScope": "none",
                },
                follow_redirects=False,
            )
            if response.status_code not in {200, 202, 204}:
                raise ExecutionVerificationUnavailable(
                    "Azure SRE Agent did not accept the exact CLI review action "
                    f"(HTTP {response.status_code}).",
                    capability="sre_agent_review_action",
                )
            return {
                "accepted": True,
                "thread_id": thread_id,
                "execution_id": execution_id,
                "action": action,
            }
        except httpx.HTTPError:
            _scrub_authorization(response, headers)
            access_token = ""
            raise ExecutionVerificationUnavailable(
                "Azure SRE Agent was unreachable while submitting the CLI review action.",
                capability="sre_agent_review_action",
            ) from None
        finally:
            _scrub_authorization(response, headers)
            access_token = ""
            if self._client is None:
                client.close()

    def read_approvals(self, execution_record: dict[str, Any]) -> list[object]:
        """Read-only listing of every approval record for this thread.

        Distinct from :meth:`cancel`: never posts a decision and never
        requires a *pending* approval. Used by abandon eligibility to fail
        closed when any approval row exists for the thread -- including an
        already-decided, rejected, or expired one -- that the composite
        thread-status summary alone does not surface. Fails closed (raises
        :class:`ExecutionVerificationUnavailable`) on any transport error,
        non-200 response, unparseable body, or unrecognized collection
        shape; never returns a permissive "no approvals" default in those
        cases.
        """
        _thread_url, thread_id = self._thread_id(execution_record)
        access_token = self._token()
        headers = {"Authorization": "Bearer " + access_token}
        approvals_url = (
            f"{self._agent_endpoint}/api/v1/approvals/{quote(thread_id, safe='')}"
        )
        client = self._client or httpx.Client(
            timeout=self._timeout,
            follow_redirects=False,
        )
        response: httpx.Response | None = None
        try:
            response = client.get(
                approvals_url,
                headers=headers,
                follow_redirects=False,
            )
            if response.status_code != 200:
                raise ExecutionVerificationUnavailable(
                    f"Azure SRE Agent approval lookup returned HTTP {response.status_code}.",
                    capability="sre_agent_approval_read",
                )
            try:
                payload = response.json()
            except ValueError:
                raise ExecutionVerificationUnavailable(
                    "Azure SRE Agent returned an unparseable approval list.",
                    capability="sre_agent_approval_read",
                ) from None
            rows = self._approval_rows(payload)
            if rows is None:
                raise ExecutionVerificationUnavailable(
                    "Azure SRE Agent returned an unrecognized approval list shape.",
                    capability="sre_agent_approval_read",
                )
            return rows
        except httpx.HTTPError:
            _scrub_authorization(response, headers)
            access_token = ""
            raise ExecutionVerificationUnavailable(
                "Azure SRE Agent was unreachable while reading approvals.",
                capability="sre_agent_approval_read",
            ) from None
        finally:
            _scrub_authorization(response, headers)
            access_token = ""
            if self._client is None:
                client.close()

    def verify(self, execution_record: dict[str, Any]) -> dict[str, Any]:
        """Map the documented thread status to the remediation outcome model."""
        if str(execution_record.get("provider") or "") != SRE_AGENT_PROVIDER:
            return {"verifiable": False, "reason": "not an SRE Agent execution"}
        if not str(execution_record.get("provider_job_id") or "").strip():
            return {"verifiable": False, "reason": "no provider job id"}
        thread_url, _thread_id = self._thread_id(execution_record)

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
        pending_question = (
            _pending_user_question(payload) if isinstance(payload, dict) else None
        )
        pending_cli_execution = (
            _pending_cli_execution(payload, execution_record)
            if isinstance(payload, dict)
            else None
        )
        submitted_operation = (
            _submitted_operation(payload, execution_record)
            if isinstance(payload, dict)
            else None
        )
        completed_write = (
            _completed_write_execution(payload, execution_record)
            if isinstance(payload, dict)
            else None
        )
        evidence = {"thread_status": composite or raw_status or "unknown"}
        if pending_question is not None:
            evidence["approval_pending"] = True
            evidence["user_question"] = pending_question
        if pending_cli_execution is not None:
            evidence["approval_pending"] = True
            evidence["provider_review"] = pending_cli_execution
        if submitted_operation is not None:
            evidence["provider_operation"] = submitted_operation
        if completed_write is not None:
            evidence["completed_write_execution"] = completed_write
        if composite is not None:
            outcome, verified_state, failure_details = _composite_outcome(
                composite,
                has_submitted_operation=submitted_operation is not None,
            )
            if outcome == "running" and (
                pending_question is not None or pending_cli_execution is not None
            ):
                verified_state = "Pending Review"
            if outcome == "succeeded" and submitted_operation is None:
                recovered = self._recover_provider_operation_from_activity_log(
                    execution_record,
                    completed_write=completed_write,
                )
                if recovered is None:
                    return _completion_without_submission(
                        verified_state="CompleteWithoutSubmissionProof",
                        evidence=evidence,
                    )
                provider_operation, activity_log_recovery = recovered
                evidence["provider_operation"] = provider_operation
                evidence["activity_log_recovery"] = activity_log_recovery
            result = {
                "verifiable": True,
                "outcome": outcome,
                "verified_state": verified_state,
                "verification_evidence": evidence,
            }
            if outcome == "running":
                result["provider_active"] = True
                if verified_state == "Pending Review":
                    evidence["approval_pending"] = True
            if failure_details:
                result["failure_details"] = failure_details
            return result
        if normalized in {"complete", "success", "succeeded"}:
            if submitted_operation is None:
                recovered = self._recover_provider_operation_from_activity_log(
                    execution_record,
                    completed_write=completed_write,
                )
                if recovered is None:
                    return _completion_without_submission(
                        verified_state=raw_status,
                        evidence=evidence,
                    )
                submitted_operation, activity_log_recovery = recovered
                evidence["provider_operation"] = submitted_operation
                evidence["activity_log_recovery"] = activity_log_recovery
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
        if normalized == "submission_ambiguous":
            recovered = self._recover_provider_operation_from_activity_log(
                execution_record,
                completed_write=completed_write,
            )
            if recovered is not None:
                provider_operation, activity_log_recovery = recovered
                evidence["provider_operation"] = provider_operation
                evidence["activity_log_recovery"] = activity_log_recovery
                return {
                    "verifiable": True,
                    "outcome": "succeeded",
                    "verified_state": "RecoveredFromActivityLog",
                    "verification_evidence": evidence,
                }
            return {
                "verifiable": True,
                "outcome": "failed",
                "verified_state": raw_status,
                "failure_class": "submission_ambiguous",
                "failure_details": (
                    "Azure SRE Agent could not prove whether the exact approved "
                    "patch operation crossed the provider boundary."
                ),
                "verification_evidence": evidence,
            }
        if normalized == "pending user input":
            evidence["approval_pending"] = True
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
