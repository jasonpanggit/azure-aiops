"""Typed records for patch targets, available patches, and patch runs.

The action surface is deliberately narrow. A patch run names exactly one
target, one operation kind, and (for guest OS patching) an explicit
allowlist of patch identifiers the operator selected. Nothing here infers
intent: if it wasn't selected, it isn't installed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# Compute inventory HOG can act on. Anything else is read-only exposure data.
TARGET_KIND_AZURE_VM = "Azure VM"
TARGET_KIND_ARC_SERVER = "Arc-enabled server"
TARGET_KIND_AKS_NODE = "AKS node"

PATCH_TARGET_KINDS: tuple[str, ...] = (
    TARGET_KIND_AZURE_VM,
    TARGET_KIND_ARC_SERVER,
    TARGET_KIND_AKS_NODE,
)

# Guest OS patching goes through Update Manager; AKS nodes are immutable and
# are remediated by rolling the node image instead of installing packages.
OPERATION_INSTALL_PATCHES = "install_patches"
OPERATION_NODE_IMAGE_UPGRADE = "node_image_upgrade"

PATCH_OPERATIONS: tuple[str, ...] = (
    OPERATION_INSTALL_PATCHES,
    OPERATION_NODE_IMAGE_UPGRADE,
)

_OPERATION_BY_KIND: dict[str, str] = {
    TARGET_KIND_AZURE_VM: OPERATION_INSTALL_PATCHES,
    TARGET_KIND_ARC_SERVER: OPERATION_INSTALL_PATCHES,
    TARGET_KIND_AKS_NODE: OPERATION_NODE_IMAGE_UPGRADE,
}

RUN_STATE_PENDING = "pending"
RUN_STATE_SUBMITTED = "submitted"
RUN_STATE_RUNNING = "running"
RUN_STATE_SUCCEEDED = "succeeded"
RUN_STATE_FAILED = "failed"
RUN_STATE_REJECTED = "rejected"

PATCH_RUN_STATES: tuple[str, ...] = (
    RUN_STATE_PENDING,
    RUN_STATE_SUBMITTED,
    RUN_STATE_RUNNING,
    RUN_STATE_SUCCEEDED,
    RUN_STATE_FAILED,
    RUN_STATE_REJECTED,
)

PATCH_RUN_TERMINAL_STATES: frozenset[str] = frozenset(
    {RUN_STATE_SUCCEEDED, RUN_STATE_FAILED, RUN_STATE_REJECTED}
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _strings(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,) if value else ()
    if not isinstance(value, (list, tuple, set)):
        return ()
    return tuple(sorted({_text(item) for item in value if _text(item)}))


def operation_for_kind(inventory_kind: str) -> str:
    """The only operation permitted for a given inventory kind."""
    return _OPERATION_BY_KIND.get(_text(inventory_kind), OPERATION_INSTALL_PATCHES)


class _Serializable:
    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        for key, value in list(result.items()):
            if isinstance(value, tuple):
                result[key] = list(value)
        return result


@dataclass(frozen=True)
class AvailablePatch(_Serializable):
    """One installable unit on a specific target.

    For guest OS targets this is a KB/package; for AKS node pools it is the
    node image version the pool can be upgraded to. ``patch_id`` is what an
    operator selects and what the execution adapter is allowed to act on.
    """

    patch_id: str
    title: str = ""
    classification: str = ""
    severity: str = "Unknown"
    cve_ids: tuple[str, ...] = ()
    reboot_required: bool | None = None
    published_at: str = ""
    # Where the availability claim comes from (e.g. Update Manager assessment
    # vs. inferred from an open finding), so the UI never presents a derived
    # claim as an observed one.
    source: str = ""
    # AKS only: the node pool this image upgrade applies to.
    node_pool: str = ""
    current_version: str = ""
    target_version: str = ""

    @classmethod
    def from_mapping(cls, row: dict[str, Any]) -> AvailablePatch:
        return cls(
            patch_id=_text(row.get("patch_id") or row.get("id") or row.get("kb")),
            title=_text(row.get("title") or row.get("name")),
            classification=_text(row.get("classification")),
            severity=_text(row.get("severity")) or "Unknown",
            cve_ids=_strings(row.get("cve_ids")),
            reboot_required=row.get("reboot_required") if isinstance(row.get("reboot_required"), bool) else None,
            published_at=_text(row.get("published_at")),
            source=_text(row.get("source")),
            node_pool=_text(row.get("node_pool")),
            current_version=_text(row.get("current_version")),
            target_version=_text(row.get("target_version")),
        )


@dataclass(frozen=True)
class PatchTarget(_Serializable):
    """A patchable host plus the patches currently available for it."""

    target_id: str
    name: str = ""
    inventory_kind: str = ""
    resource_type: str = ""
    subscription_id: str = ""
    subscription_connection: str = ""
    resource_group: str = ""
    environment: str = ""
    business_service: str = ""
    application: str = ""
    owner: str = ""
    region: str = ""
    criticality: str = ""
    os_family: str = ""
    reachable: bool = False
    internet_exposed: bool = False
    cve_count: int = 0
    critical_count: int = 0
    overdue_count: int = 0
    max_days_open: int = 0
    available_patches: tuple[AvailablePatch, ...] = ()
    # A target may be visible but not actionable (e.g. Update Manager is not
    # enabled on it). Stating that explicitly beats an unexplained disabled
    # button.
    patchable: bool = True
    blocked_reason: str = ""
    # ARM upgrades one AKS agent pool at a time. When inventory cannot tell us
    # which pool a node belongs to, the operator must name it on the run so the
    # upgrade stays scoped to a single pool.
    requires_node_pool: bool = False

    @property
    def operation(self) -> str:
        return operation_for_kind(self.inventory_kind)

    @property
    def available_patch_ids(self) -> frozenset[str]:
        return frozenset(patch.patch_id for patch in self.available_patches)

    def scope_attributes(self) -> dict[str, str]:
        return {
            "subscription": self.subscription_id,
            "subscription_connection": self.subscription_connection,
            "environment": self.environment,
            "business_service": self.business_service,
            "application": self.application,
            "owner": self.owner,
            "region": self.region,
            "criticality": self.criticality,
        }

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result["available_patches"] = [patch.to_dict() for patch in self.available_patches]
        result["operation"] = self.operation
        return result


@dataclass
class PatchRun(_Serializable):
    """An auditable record of one operator-approved patch action.

    The run is the unit of audit: it records who approved it, what was
    selected, which adapter executed it, and where the authoritative status
    lives upstream. HOG never claims a patch succeeded on its own authority --
    ``provider_job_id`` points back at the system of record.
    """

    run_id: str
    target_id: str
    inventory_kind: str
    operation: str
    patch_ids: tuple[str, ...] = ()
    state: str = RUN_STATE_PENDING
    requested_by: str = ""
    approved_by: str = ""
    reason: str = ""
    reboot_setting: str = "IfRequired"
    dry_run: bool = False
    created_at: str = ""
    updated_at: str = ""
    provider: str = ""
    provider_job_id: str = ""
    message: str = ""
    subscription_id: str = ""
    subscription_connection: str = ""
    business_service: str = ""
    environment: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def scope_attributes(self) -> dict[str, str]:
        return {
            "subscription": self.subscription_id,
            "subscription_connection": self.subscription_connection,
            "environment": self.environment,
            "business_service": self.business_service,
        }

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result["patch_ids"] = list(self.patch_ids)
        result["terminal"] = self.state in PATCH_RUN_TERMINAL_STATES
        return result

    @classmethod
    def from_mapping(cls, row: dict[str, Any]) -> PatchRun:
        return cls(
            run_id=_text(row.get("run_id")),
            target_id=_text(row.get("target_id")),
            inventory_kind=_text(row.get("inventory_kind")),
            operation=_text(row.get("operation")),
            patch_ids=_strings(row.get("patch_ids")),
            state=_text(row.get("state")) or RUN_STATE_PENDING,
            requested_by=_text(row.get("requested_by")),
            approved_by=_text(row.get("approved_by")),
            reason=_text(row.get("reason")),
            reboot_setting=_text(row.get("reboot_setting")) or "IfRequired",
            dry_run=bool(row.get("dry_run")),
            created_at=_text(row.get("created_at")),
            updated_at=_text(row.get("updated_at")),
            provider=_text(row.get("provider")),
            provider_job_id=_text(row.get("provider_job_id")),
            message=_text(row.get("message")),
            subscription_id=_text(row.get("subscription_id")),
            subscription_connection=_text(row.get("subscription_connection")),
            business_service=_text(row.get("business_service")),
            environment=_text(row.get("environment")),
            details=dict(row.get("details") or {}),
        )
