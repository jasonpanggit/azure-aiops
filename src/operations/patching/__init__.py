"""Human-approved, typed patch remediation for compute inventory.

This package owns the *action* side of patching: what can be installed on a
given host, and the bounded, auditable run record produced when an operator
triggers it. Read-side exposure analysis stays in
:mod:`intelligence.vulnerability`; Azure Update Manager and AKS remain the
systems of record for actual patch state.
"""

from .adapters import (
    PatchExecutionAdapter,
    PatchExecutionUnavailable,
    UnconfiguredPatchExecutionAdapter,
)
from .models import (
    PATCH_RUN_TERMINAL_STATES,
    PATCH_TARGET_KINDS,
    AvailablePatch,
    PatchRun,
    PatchTarget,
)
from .service import PatchingService
from .store import InMemoryPatchRunStore, PatchRunStore

__all__ = [
    "PATCH_RUN_TERMINAL_STATES",
    "PATCH_TARGET_KINDS",
    "AvailablePatch",
    "InMemoryPatchRunStore",
    "PatchExecutionAdapter",
    "PatchExecutionUnavailable",
    "PatchRun",
    "PatchRunStore",
    "PatchTarget",
    "PatchingService",
    "UnconfiguredPatchExecutionAdapter",
]
