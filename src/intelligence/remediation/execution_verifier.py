"""Post-submission verification against the real upstream source of truth.

An Azure ARM 2xx response only means *accepted*; Update Manager and AKS
remain authoritative on what actually happened (see
``operations.patching.azure_adapter``'s module docstring: "HOG does not
claim success"). ``ExecutionVerifier`` polls the ``provider_job_id``
operation URL handed back at submission time and maps the raw ARM
``status`` field to a verified outcome, never trusting the submission
response alone.

This module is read-only: it issues GET requests against the operation
URL and never calls a mutating Azure API. See the phase threat model
(T-03-09, T-03-13).
"""

from __future__ import annotations

from typing import Any

import httpx

from operations.patching.azure_adapter import ARM_SCOPE, TokenCredential

_OUTCOME_SUCCEEDED = "succeeded"
_OUTCOME_FAILED = "failed"
_OUTCOME_CANCELLED = "cancelled"
_OUTCOME_RUNNING = "running"

# ARM long-running-operation status vocabulary. "Running" is an alias some
# providers use in place of "InProgress" -- both map to the same
# not-yet-terminal outcome.
_TERMINAL_SUCCEEDED_STATUSES = frozenset({"succeeded"})
_TERMINAL_FAILED_STATUSES = frozenset({"failed"})
_TERMINAL_CANCELLED_STATUSES = frozenset({"canceled", "cancelled"})
_RUNNING_STATUSES = frozenset({"inprogress", "running", "notstarted", "accepted"})


def _nonnegative_int(value: Any) -> int:
    """Coerce ``value`` to a non-negative int, never raising on bad input."""
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _provider_error_text(value: Any) -> str:
    """Extract truncated error text from an ARM ``error``/``errorDetails`` item."""
    if isinstance(value, dict):
        text = str(value.get("message") or value.get("code") or "")
    else:
        text = str(value or "")
    return text[:500]


def _parse_patch_properties(payload: Any) -> dict[str, Any]:
    """Extract nested patch-family result detail from an ARM operation body.

    Never raises: a malformed or adversarial-shaped ``properties`` body
    (missing, not a dict, non-numeric counts, unexpected error shapes)
    resolves to safe zero/empty defaults rather than propagating an
    exception (T-03.4-01).
    """
    properties = payload.get("properties") if isinstance(payload, dict) else None
    if not isinstance(properties, dict):
        # Hybrid Compute Update Manager operation results return the patch
        # summary fields at the envelope root, while other ARM providers nest
        # the same shape under ``properties``.
        patch_result_fields = {
            "installedPatchCount",
            "failedPatchCount",
            "pendingPatchCount",
            "notSelectedPatchCount",
            "error",
            "errorDetails",
        }
        properties = (
            payload
            if isinstance(payload, dict) and patch_result_fields.intersection(payload)
            else {}
        )

    provider_errors: list[str] = []
    error = properties.get("error")
    if isinstance(error, dict):
        text = _provider_error_text(error)
        if text:
            provider_errors.append(text)
    error_details = properties.get("errorDetails")
    if isinstance(error_details, list):
        for item in error_details:
            text = _provider_error_text(item)
            if text:
                provider_errors.append(text)

    return {
        "detail_status": str(properties.get("status") or ""),
        "installed_count": _nonnegative_int(properties.get("installedPatchCount")),
        "failed_count": _nonnegative_int(properties.get("failedPatchCount")),
        "pending_count": _nonnegative_int(properties.get("pendingPatchCount")),
        "not_selected_count": _nonnegative_int(properties.get("notSelectedPatchCount")),
        "provider_errors": provider_errors,
    }


class ExecutionVerificationUnavailable(RuntimeError):
    """Raised when the operation-URL poll itself cannot be completed.

    This is distinct from a legitimately-returned failed/in-progress ARM
    status -- those are valid answers, not errors. This is raised only for
    network/HTTP failures or an unusable credential, mirroring
    :class:`operations.patching.adapters.PatchExecutionUnavailable`.
    """

    def __init__(self, message: str, *, capability: str = "execution_verification") -> None:
        super().__init__(message)
        self.capability = capability


class ExecutionVerifier:
    """Polls an ARM long-running-operation URL to learn the real outcome.

    Safely callable multiple times: a still-running ARM status simply
    yields a ``"running"`` outcome, so a caller may poll repeatedly until a
    terminal outcome is reported.
    """

    def __init__(
        self,
        *,
        credential: TokenCredential,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._credential = credential
        self._client = client
        self._timeout = timeout

    def verify(self, execution_record: dict[str, Any]) -> dict[str, Any]:
        """Return the verified outcome for ``execution_record``.

        Reads ``provider_job_id`` from the record. If absent, this
        execution cannot be verified against an upstream operation
        (e.g. a dry-run or a submission that never reached Azure), and
        ``{"verifiable": False, "reason": "no provider job id"}`` is
        returned rather than guessing at an outcome.
        """
        operation_url = str(execution_record.get("provider_job_id") or "").strip()
        if not operation_url:
            return {"verifiable": False, "reason": "no provider job id"}

        response = self._poll(operation_url)
        payload: dict[str, Any] = {}
        try:
            parsed = response.json()
            if isinstance(parsed, dict):
                payload = parsed
        except ValueError:
            payload = {}

        snapshot = execution_record.get("execution_snapshot") or {}
        if snapshot.get("snapshot_kind") == "defender_configuration":
            # WR-02: the ARM envelope's own status must be interpreted
            # before falling back to the properties-match heuristic -- a
            # terminally-failed/cancelled ARM operation is never "still
            # running" just because the desired properties happen not to
            # match yet (CONTEXT.md's "interpret both envelope and nested
            # properties.status" decision).
            raw_status = str(payload.get("status") or "").casefold()
            if raw_status in _TERMINAL_FAILED_STATUSES:
                return {
                    "verifiable": True,
                    "outcome": _OUTCOME_FAILED,
                    "verified_state": str(payload.get("status") or ""),
                    "failure_details": _error_message(payload, response),
                }
            if raw_status in _TERMINAL_CANCELLED_STATUSES:
                return {
                    "verifiable": True,
                    "outcome": _OUTCOME_CANCELLED,
                    "verified_state": str(payload.get("status") or ""),
                    "failure_details": _error_message(payload, response),
                }
            properties = payload.get("properties") if isinstance(payload, dict) else {}
            desired = snapshot.get("desired_properties") or {}
            matched = _contains(properties, desired)
            return {
                "verifiable": True,
                "outcome": _OUTCOME_SUCCEEDED if matched else _OUTCOME_RUNNING,
                "verified_state": (
                    "configuration_matches_approved_snapshot"
                    if matched
                    else "configuration_pending"
                ),
            }

        detail = _parse_patch_properties(payload)
        raw_status = str(payload.get("status") or "")
        normalized = raw_status.casefold()

        # CR-03: a non-terminal ARM envelope status (e.g. "InProgress") must
        # never be reinterpreted as a terminal failure just because Update
        # Manager's progressive counts happen to show pending/failed patches
        # -- pendingPatchCount > 0 (and, weaker but for consistency,
        # failedPatchCount > 0) is completely ordinary mid-flight shape for a
        # genuinely still-running multi-patch installation (03.4-01-PLAN.md:
        # these counts are extracted "on every parseable patch-family poll
        # (running, succeeded, or failed)"). Only once the envelope itself
        # has reached a terminal state (mirroring WR-02's own
        # envelope-status-first pattern immediately above) may remaining
        # pending/failed counts be interpreted as partial/failed. Reporting
        # a still-running operation as terminally "failed" would make it
        # eligible for retry() while Azure is still actively working,
        # risking a second concurrent submission against the same target.
        is_terminal_envelope = normalized in (
            _TERMINAL_SUCCEEDED_STATUSES | _TERMINAL_FAILED_STATUSES | _TERMINAL_CANCELLED_STATUSES
        )
        nested_failed = is_terminal_envelope and (
            detail["detail_status"].casefold()
            in {"completedwithwarnings", "partialsuccess", "timedout"}
            or detail["failed_count"] > 0
            # WR-01/CONTEXT.md's "partial success ... never clean success"
            # decision: patches still pending (selected but neither
            # installed nor failed) are material incompleteness, not a
            # clean result, even when the envelope/nested status otherwise
            # reads "Succeeded".
            or detail["pending_count"] > 0
        )
        if nested_failed:
            failure_details = (
                "; ".join(detail["provider_errors"])
                if detail["provider_errors"]
                else _error_message(payload, response)
            )
            # A pending-only result (no failed_count, no explicit
            # warnings/partial-success/timeout detail status) still needs a
            # verified_state distinct from an unqualified terminal
            # "Succeeded"/"CompletedWithWarnings" label, so a consumer
            # reading the raw outcome cannot mistake a partially-completed
            # patch run for a fully clean one (WR-01).
            if (
                detail["failed_count"] == 0
                and detail["pending_count"] > 0
                and detail["detail_status"].casefold()
                not in {"completedwithwarnings", "partialsuccess", "timedout"}
            ):
                verified_state = "succeeded_with_pending_patches"
            else:
                verified_state = raw_status or detail["detail_status"]
            return {
                "verifiable": True,
                "outcome": _OUTCOME_FAILED,
                "verified_state": verified_state,
                "failure_details": failure_details,
                "verification_evidence": detail,
            }
        if normalized in _TERMINAL_SUCCEEDED_STATUSES:
            return {
                "verifiable": True,
                "outcome": _OUTCOME_SUCCEEDED,
                "verified_state": raw_status,
                "verification_evidence": detail,
            }
        if normalized in _TERMINAL_FAILED_STATUSES:
            failure_details = (
                "; ".join(detail["provider_errors"])
                if detail["provider_errors"]
                else _error_message(payload, response)
            )
            return {
                "verifiable": True,
                "outcome": _OUTCOME_FAILED,
                "verified_state": raw_status,
                "failure_details": failure_details,
                "verification_evidence": detail,
            }
        if normalized in _TERMINAL_CANCELLED_STATUSES:
            failure_details = (
                "; ".join(detail["provider_errors"])
                if detail["provider_errors"]
                else _error_message(payload, response)
            )
            return {
                "verifiable": True,
                "outcome": _OUTCOME_CANCELLED,
                "verified_state": raw_status,
                "failure_details": failure_details,
                "verification_evidence": detail,
            }
        # InProgress/Running/anything else not recognized as terminal is
        # treated as still-running rather than guessed at as a failure.
        return {
            "verifiable": True,
            "outcome": _OUTCOME_RUNNING,
            "verified_state": raw_status or "unknown",
            "verification_evidence": detail,
        }

    # -- HTTP ---------------------------------------------------------

    def _token(self) -> str:
        try:
            token = self._credential.get_token(ARM_SCOPE)
        except Exception as exc:  # surfaced as a typed refusal below
            raise ExecutionVerificationUnavailable(
                f"Could not acquire an Azure management token: {exc}",
                capability="azure_arm_token",
            ) from exc
        value = getattr(token, "token", "") or ""
        if not value:
            raise ExecutionVerificationUnavailable(
                "Azure credential returned an empty management token.",
                capability="azure_arm_token",
            )
        return str(value)

    def _poll(self, operation_url: str) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self._token()}"}
        client = self._client or httpx.Client(timeout=self._timeout)
        try:
            response = client.get(operation_url, headers=headers)
            response.raise_for_status()
            return response
        except httpx.HTTPError as exc:
            raise ExecutionVerificationUnavailable(
                f"Azure Resource Manager was unreachable while polling for verification: {exc}",
                capability="execution_verification_poll",
            ) from exc
        finally:
            if self._client is None:
                client.close()


def _error_message(payload: dict[str, Any], response: httpx.Response) -> str:
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or error.get("code") or payload)[:500]
    if payload:
        return str(payload)[:500]
    return response.text[:500]


def _contains(actual: Any, expected: Any) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and _contains(actual[key], value)
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        return isinstance(actual, list) and all(
            any(_contains(item, expected_item) for item in actual)
            for expected_item in expected
        )
    return actual == expected


__all__ = [
    "ExecutionVerificationUnavailable",
    "ExecutionVerifier",
]
