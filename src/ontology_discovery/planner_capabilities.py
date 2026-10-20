"""Server-owned planner selection and closed, non-authoritative provenance.

Native unattended proposal authoring is not established by current research.
Neither a provider receipt nor an injected client can grant that capability.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from .contracts import Curator

PlannerProvider = Literal["foundry", "native"]
ExecutionClass = Literal["live", "simulated", "imported", "provenance_unavailable"]
CapabilityReason = Literal[
    "native_public_operation_unavailable",
    "native_unattended_identity_unsupported",
    "native_structured_output_unavailable",
]
NATIVE_DENIAL_REASONS: tuple[CapabilityReason, ...] = (
    "native_public_operation_unavailable",
    "native_unattended_identity_unsupported",
    "native_structured_output_unavailable",
)
_EXECUTION_CLASSES = frozenset(
    {"live", "simulated", "imported", "provenance_unavailable"}
)
_SHA256 = re.compile(r"[0-9a-f]{64}")
_VERSION = re.compile(r"[0-9]{1,10}(?:[.-][0-9]{1,10}){0,3}")
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


class UnsupportedPlannerCapability(RuntimeError):
    """Stable denial of native planning, with no raw configuration or errors."""

    reason_code: CapabilityReason = NATIVE_DENIAL_REASONS[0]
    reason_codes: tuple[CapabilityReason, ...] = NATIVE_DENIAL_REASONS

    def __init__(self) -> None:
        super().__init__(self.reason_code)


@dataclass(frozen=True)
class PlannerSelection:
    """Trusted composition choice, never derived from model/provider metadata."""

    requested_provider: PlannerProvider
    selected_provider: PlannerProvider
    fallback_reason: CapabilityReason | None
    execution_class: ExecutionClass

    def require_supported(self) -> None:
        """Recheck selection at invocation; hand-built native choices fail closed."""
        if self.selected_provider == "native":
            raise UnsupportedPlannerCapability()
        if self.selected_provider != "foundry" or self.requested_provider not in {
            "foundry",
            "native",
        }:
            raise ValueError("invalid_planner_selection")
        expected = (
            NATIVE_DENIAL_REASONS[0] if self.requested_provider == "native" else None
        )
        if self.fallback_reason != expected:
            raise ValueError("invalid_planner_fallback")
        if self.execution_class not in _EXECUTION_CLASSES:
            raise ValueError("invalid_planner_execution_class")


def select_planner(
    *,
    requested_provider: PlannerProvider = "foundry",
    allow_foundry_fallback: bool = False,
    execution_class: ExecutionClass = "provenance_unavailable",
) -> PlannerSelection:
    """Select Foundry or deny native before transport; fallback must be explicit."""
    if type(allow_foundry_fallback) is not bool:
        raise ValueError("invalid_planner_fallback_permission")
    if requested_provider == "native" and not allow_foundry_fallback:
        raise UnsupportedPlannerCapability()
    selection = PlannerSelection(
        requested_provider=requested_provider,
        selected_provider="foundry",
        fallback_reason=(
            NATIVE_DENIAL_REASONS[0] if requested_provider == "native" else None
        ),
        execution_class=execution_class,
    )
    selection.require_supported()
    return selection


def provider_receipt(
    *,
    selection: PlannerSelection,
    curator: Curator,
    result: Mapping[str, Any],
) -> dict[str, Any]:
    """Return bounded allowlisted attribution, never raw prompts, IDs or usage.

    Hash the validated response document, not a provider-controlled response ID.
    Unknown/malformed optional attempt metadata cannot activate a capability.
    Version strings outside the numeric pinned-version grammar are hashed only.
    """
    selection.require_supported()
    raw = getattr(curator, "last_attempt", None)
    attempt = raw if isinstance(raw, Mapping) else {}
    version = attempt.get("agent_version")
    version = version if isinstance(version, str) and len(version) <= 64 else ""
    receipt: dict[str, Any] = {
        "receipt_version": "planner-receipt/v1",
        "requested_provider": selection.requested_provider,
        "selected_provider": selection.selected_provider,
        "fallback_reason": selection.fallback_reason,
        "execution_class": selection.execution_class,
        "metadata_status": "available" if attempt else "provenance_unavailable",
        "response_hash": hashlib.sha256(
            json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }
    if version:
        receipt["agent_version_hash"] = hashlib.sha256(version.encode()).hexdigest()
        if _VERSION.fullmatch(version):
            receipt["agent_version"] = version
    model = attempt.get("model")
    if isinstance(model, str) and _MODEL.fullmatch(model):
        receipt["model"] = model
    for key in ("prompt_hash", "schema_hash"):
        value = attempt.get(key)
        if isinstance(value, str) and _SHA256.fullmatch(value):
            receipt[key] = value
    return receipt
