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

        raw_status = str(payload.get("status") or "")
        normalized = raw_status.casefold()

        if normalized in _TERMINAL_SUCCEEDED_STATUSES:
            return {
                "verifiable": True,
                "outcome": _OUTCOME_SUCCEEDED,
                "verified_state": raw_status,
            }
        if normalized in _TERMINAL_FAILED_STATUSES:
            return {
                "verifiable": True,
                "outcome": _OUTCOME_FAILED,
                "verified_state": raw_status,
                "failure_details": _error_message(payload, response),
            }
        if normalized in _TERMINAL_CANCELLED_STATUSES:
            return {
                "verifiable": True,
                "outcome": _OUTCOME_CANCELLED,
                "verified_state": raw_status,
                "failure_details": _error_message(payload, response),
            }
        # InProgress/Running/anything else not recognized as terminal is
        # treated as still-running rather than guessed at as a failure.
        return {
            "verifiable": True,
            "outcome": _OUTCOME_RUNNING,
            "verified_state": raw_status or "unknown",
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


__all__ = [
    "ExecutionVerificationUnavailable",
    "ExecutionVerifier",
]
