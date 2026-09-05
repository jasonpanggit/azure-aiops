"""Execution adapters for patch runs.

The adapter boundary is the single place where HOG stops observing and
starts changing Azure. It is deliberately thin and typed: a caller hands over
an already-validated :class:`PatchRun` and gets back a provider job handle.
Validation, allowlisting, and RBAC happen before this point, in
:class:`operations.patching.service.PatchingService`.

The default adapter refuses to run. A deployment must opt in by wiring a real
Azure adapter, so a misconfigured environment fails loudly instead of silently
pretending to patch.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from .models import PatchRun, PatchTarget


class PatchExecutionUnavailable(RuntimeError):
    """Raised when no execution backend is configured or reachable.

    ``provider_submitted`` and ``failure_class`` are the Phase 03.3
    submission-accounting signals (CONTEXT.md's Submission Accounting /
    Failure Classification decisions): whether the mutating call is proven
    to have reached Azure, and why it failed, from the closed six-value
    vocabulary. The defaults are deliberately fail-closed -- an unclassified
    raise still consumes the retry budget rather than silently exempting
    itself.
    """

    def __init__(
        self,
        message: str,
        *,
        capability: str = "patch_execution",
        provider_submitted: bool = True,
        failure_class: str = "submission_ambiguous",
    ) -> None:
        super().__init__(message)
        self.capability = capability
        self.provider_submitted = provider_submitted
        self.failure_class = failure_class


@dataclass(frozen=True)
class PatchExecutionResult:
    """What the upstream system returned when the run was submitted."""

    provider: str
    provider_job_id: str
    state: str
    message: str = ""
    details: dict[str, Any] | None = None


@runtime_checkable
class PatchExecutionAdapter(Protocol):
    """Submit an approved patch run to the system that actually performs it."""

    name: str

    def submit(self, run: PatchRun, target: PatchTarget) -> PatchExecutionResult:
        """Submit ``run`` and return the upstream job handle.

        Implementations must be idempotent with respect to ``run.run_id`` where
        the upstream API allows it, and must raise
        :class:`PatchExecutionUnavailable` rather than inventing a job id when
        they cannot reach the upstream service.
        """


class UnconfiguredPatchExecutionAdapter:
    """The safe default: refuses every submission.

    Wiring the real Azure adapter requires credentials, an execution identity
    with the narrow write roles Update Manager and AKS need, and a change
    window policy. Until that is configured, refusing is the correct behavior:
    the alternative is an operator believing a patch was triggered when nothing
    happened.
    """

    name = "unconfigured"

    def submit(self, run: PatchRun, target: PatchTarget) -> PatchExecutionResult:
        raise PatchExecutionUnavailable(
            "No patch execution adapter is configured for this deployment. "
            "Configure an Azure Update Manager / AKS execution identity to "
            "enable patch triggering.",
            capability=(
                "aks_node_image_upgrade"
                if run.operation == "node_image_upgrade"
                else "update_manager_install_patches"
            ),
            provider_submitted=False,
            failure_class="internal_validation",
        )


class RecordingPatchExecutionAdapter:
    """Test/dry-run adapter that records submissions instead of calling Azure."""

    name = "recording"

    def __init__(self) -> None:
        self.submissions: list[tuple[PatchRun, PatchTarget]] = []

    def submit(self, run: PatchRun, target: PatchTarget) -> PatchExecutionResult:
        self.submissions.append((run, target))
        return PatchExecutionResult(
            provider=self.name,
            provider_job_id=f"recorded-{run.run_id}",
            state="submitted",
            message="Recorded without contacting Azure",
        )
