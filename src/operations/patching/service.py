"""Patch inventory projection and the guarded trigger path.

Reads come from the same vulnerability projection the exposure page already
trusts, so the inventory an operator patches is the inventory they were shown.
Writes are guarded: every trigger is validated against the target's own
available-patch allowlist before any adapter is called.
"""

from __future__ import annotations

import copy
import uuid
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime
from typing import Any

from intelligence.remediation.approval_gate import is_self_approval

from .adapters import (
    PatchExecutionAdapter,
    PatchExecutionUnavailable,
    UnconfiguredPatchExecutionAdapter,
)
from .models import (
    OPERATION_INSTALL_PATCHES,
    OPERATION_NODE_IMAGE_UPGRADE,
    RUN_STATE_FAILED,
    RUN_STATE_PENDING,
    TARGET_KIND_AKS_NODE,
    TARGET_KIND_ARC_SERVER,
    TARGET_KIND_AZURE_VM,
    AvailablePatch,
    PatchRun,
    PatchTarget,
    operation_for_kind,
)
from .store import InMemoryPatchRunStore, PatchRunStore

# Reboot behavior an operator may request. Anything outside this set is
# rejected rather than passed through to Azure.
REBOOT_SETTINGS: tuple[str, ...] = ("IfRequired", "Never", "Always")


class PatchValidationError(ValueError):
    """A trigger request that must not reach the execution adapter."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _resource_group(resource_id: str) -> str:
    parts = [part for part in str(resource_id or "").split("/") if part]
    for index, part in enumerate(parts):
        if part.casefold() == "resourcegroups" and index + 1 < len(parts):
            return parts[index + 1]
    return ""


def _canonical_inventory_kind(row: dict[str, Any]) -> str:
    """Normalize source-specific compute labels before applying the action gate."""
    raw = str(row.get("inventory_kind") or "").strip()
    if raw in {TARGET_KIND_AZURE_VM, TARGET_KIND_ARC_SERVER, TARGET_KIND_AKS_NODE}:
        return raw

    resource_type = str(
        row.get("resource_type")
        or row.get("target_resource_type")
        or row.get("type")
        or row.get("asset_id")
        or row.get("resource_id")
        or ""
    ).casefold()
    identity = "".join(
        character
        for character in f"{raw} {resource_type}".casefold()
        if character.isalnum()
    )
    if "hybridcompute" in identity or "arcserver" in identity:
        return TARGET_KIND_ARC_SERVER
    if "managedcluster" in identity or "containerservice" in identity or "aksnode" in identity:
        return TARGET_KIND_AKS_NODE
    if "virtualmachine" in identity or identity in {"vm", "azurevm"}:
        return TARGET_KIND_AZURE_VM
    return raw


class PatchingService:
    """Projects patchable inventory and executes approved patch runs."""

    def __init__(
        self,
        vulnerability_service: Any,
        *,
        store: PatchRunStore | None = None,
        adapter: PatchExecutionAdapter | None = None,
        patch_assessments: Iterable[dict[str, Any]] | None = None,
        require_human_approval: Callable[[], bool] | bool = True,
        allow_self_approval: Callable[[], bool] | bool = False,
    ) -> None:
        self._vulnerability = vulnerability_service
        self._store: PatchRunStore = store or InMemoryPatchRunStore()
        self._adapter: PatchExecutionAdapter = adapter or UnconfiguredPatchExecutionAdapter()
        # Resolved per call, not captured at construction: an administrator who
        # turns approval back on must not have to wait for a replica restart.
        # Defaults to True so a service built without the policy fails closed.
        self._require_human_approval: Callable[[], bool] = (
            require_human_approval
            if callable(require_human_approval)
            else (lambda value=require_human_approval: bool(value))
        )
        # Separation of duties (approver != requester) stays on by default.
        # Demo/single-operator environments may explicitly opt out via
        # agent_policy.allow_self_approval; defaults to False so production
        # deployments fail closed unless an administrator opts in.
        self._allow_self_approval: Callable[[], bool] = (
            allow_self_approval
            if callable(allow_self_approval)
            else (lambda value=allow_self_approval: bool(value))
        )
        # Optional Update Manager assessment rows, keyed by target id. When
        # present they are authoritative for what is installable; without them
        # the projection falls back to the KBs implied by open findings, which
        # is a weaker claim and is labelled as such via AvailablePatch.source.
        self._assessments: dict[str, list[dict[str, Any]]] = {}
        for row in patch_assessments or []:
            target_id = str(row.get("target_id") or row.get("server_id") or "").strip()
            if target_id:
                self._assessments.setdefault(target_id, []).append(dict(row))

    @property
    def adapter_name(self) -> str:
        return getattr(self._adapter, "name", "unknown")

    @property
    def freshness(self) -> str:
        return str(getattr(self._vulnerability, "freshness", "") or "")

    # -- read ------------------------------------------------------------

    def targets(self, scope: Any = None) -> list[PatchTarget]:
        """Patchable compute inventory in scope, with available patches."""
        supported_kinds = {
            TARGET_KIND_AKS_NODE,
            TARGET_KIND_ARC_SERVER,
            TARGET_KIND_AZURE_VM,
        }
        rows = self._vulnerability.asset_exposures(scope)
        return [
            self._target_from_exposure(row)
            for row in rows
            if _canonical_inventory_kind(row) in supported_kinds
        ]

    def target(self, target_id: str, scope: Any = None) -> PatchTarget | None:
        normalized = str(target_id or "").strip()
        for candidate in self.targets(scope):
            if candidate.target_id == normalized:
                return candidate
        return None

    def _target_from_exposure(self, row: dict[str, Any]) -> PatchTarget:
        target_id = str(row.get("asset_id") or "")
        inventory_kind = _canonical_inventory_kind(row)
        patches = self._available_patches(target_id, inventory_kind, row)
        is_node_image = operation_for_kind(inventory_kind) == OPERATION_NODE_IMAGE_UPGRADE
        patchable = bool(patches)
        blocked_reason = ""
        if not patchable:
            blocked_reason = (
                "No node image upgrade is available for this pool"
                if is_node_image
                else "No installable update was observed for this host"
            )
        # ARM upgrades one agent pool at a time. When the feed does not tell us
        # which pool this node belongs to, the operator must name it rather
        # than HOG implicitly rolling every pool in the cluster.
        requires_node_pool = is_node_image and not any(patch.node_pool for patch in patches)
        return PatchTarget(
            target_id=target_id,
            name=str(row.get("name") or target_id),
            inventory_kind=inventory_kind,
            resource_type=str(row.get("resource_type") or ""),
            subscription_id=str(row.get("subscription_id") or ""),
            subscription_connection=str(row.get("subscription_connection") or ""),
            resource_group=_resource_group(target_id),
            environment=str(row.get("environment") or ""),
            business_service=str(row.get("business_service") or ""),
            application=str(row.get("application") or ""),
            owner=str(row.get("owner") or ""),
            region=str(row.get("region") or ""),
            criticality=str(row.get("criticality") or ""),
            os_family=str(row.get("os_family") or ""),
            reachable=bool(row.get("reachable")),
            internet_exposed=bool(row.get("internet_exposed")),
            cve_count=int(row.get("cve_count") or 0),
            critical_count=int(row.get("critical_count") or 0),
            overdue_count=int(row.get("overdue_count") or 0),
            max_days_open=int(row.get("max_days_open") or 0),
            available_patches=patches,
            patchable=patchable,
            blocked_reason=blocked_reason,
            requires_node_pool=requires_node_pool,
        )

    def _available_patches(
        self, target_id: str, inventory_kind: str, row: dict[str, Any]
    ) -> tuple[AvailablePatch, ...]:
        observed = self._assessments.get(target_id)
        if observed:
            return tuple(
                sorted(
                    (AvailablePatch.from_mapping(item) for item in observed),
                    key=lambda patch: patch.patch_id,
                )
            )
        if operation_for_kind(inventory_kind) == OPERATION_NODE_IMAGE_UPGRADE:
            # Without an assessment feed there is no observed target image, so
            # offering a specific version would be a fabrication. "latest" is
            # the one honest option: it is exactly what the AKS API accepts and
            # it makes no claim about which build will land.
            return (
                AvailablePatch(
                    patch_id="latest",
                    title="Upgrade node pool to the latest available node image",
                    classification="NodeImage",
                    severity=self._worst_severity(row),
                    cve_ids=tuple(row.get("cve_ids") or ()),
                    reboot_required=True,
                    source="derived:open-findings",
                    node_pool=str(row.get("node_pool") or ""),
                    target_version="latest",
                ),
            )
        severity = self._worst_severity(row)
        cve_ids = tuple(row.get("cve_ids") or ())
        return tuple(
            AvailablePatch(
                patch_id=str(kb),
                title=f"Missing update {kb}",
                classification="Security",
                severity=severity,
                cve_ids=cve_ids,
                source="derived:open-findings",
            )
            for kb in sorted({str(kb) for kb in (row.get("missing_kbs") or []) if kb})
        )

    @staticmethod
    def _worst_severity(row: dict[str, Any]) -> str:
        severities = [str(item) for item in (row.get("severities") or []) if item]
        for candidate in ("Critical", "High", "Medium", "Low"):
            if any(item.casefold() == candidate.casefold() for item in severities):
                return candidate
        return severities[0] if severities else "Unknown"

    # -- runs ------------------------------------------------------------

    def runs(self, scope: Any = None) -> list[PatchRun]:
        rows = self._store.list()
        if scope is None or getattr(scope, "is_unrestricted", lambda: True)():
            return rows
        return [run for run in rows if scope.matches(run.scope_attributes())]

    def run(self, run_id: str) -> PatchRun | None:
        return self._store.get(str(run_id or "").strip())

    def _authorize_approval(
        self, *, requested_by: str, approved_by: str, dry_run: bool
    ) -> str:
        """Return the validated approver, or raise before Azure is touched.

        ``approved_by`` arrives from the request body, so it is a claim by the
        caller rather than a verified identity. Enforcing two things closes the
        gap that made it decorative:

        - When ``agent_policy.require_human_approval`` is on (the default), a
          named approver is mandatory. Previously it defaulted to the
          requester, so the field could simply be omitted.
        - The approver may never be the requester, unless an administrator has
          explicitly set ``agent_policy.allow_self_approval`` (default off).
          Separation of duties is the entire point of recording an approver;
          self-approval records an audit trail that asserts something nobody
          actually did. The opt-out exists only for single-operator/demo
          environments where a second approver identity is not provisioned.

        ``dry_run`` is exempt: it validates and short-circuits before
        ``adapter.submit`` and changes nothing.

        This is an authorization check on a claimed identity, not proof of it.
        Verifying the approver against Entra, and capturing their consent
        rather than the requester's assertion of it, is a separate step.
        """
        requester = str(requested_by or "").strip()
        approver = str(approved_by or "").strip()
        if dry_run:
            return approver or requester
        if not self._require_human_approval():
            return approver or requester
        if not approver:
            raise PatchValidationError(
                "This patch run needs a named approver: enterprise settings "
                "require human approval before changing a host",
                details={
                    "requested_by": requester,
                    "setting": "agent_policy.require_human_approval",
                },
            )
        if is_self_approval(requester, approver) and not self._allow_self_approval():
            raise PatchValidationError(
                "The approver must be someone other than the requester",
                details={"requested_by": requester, "approved_by": approver},
            )
        return approver

    def trigger(
        self,
        *,
        target: PatchTarget,
        patch_ids: Sequence[str],
        requested_by: str,
        approved_by: str = "",
        reason: str = "",
        reboot_setting: str = "IfRequired",
        node_pool: str = "",
        dry_run: bool = False,
        approval_context: dict[str, Any] | None = None,
    ) -> PatchRun:
        """Validate and submit one patch run. Raises before touching Azure."""
        if not target.patchable:
            raise PatchValidationError(
                target.blocked_reason or "Target is not patchable",
                details={"target_id": target.target_id},
            )
        if reboot_setting not in REBOOT_SETTINGS:
            raise PatchValidationError(
                f"Unsupported reboot setting {reboot_setting!r}",
                details={"allowed": list(REBOOT_SETTINGS)},
            )
        selected = tuple(dict.fromkeys(str(item).strip() for item in patch_ids if str(item).strip()))
        if not selected:
            raise PatchValidationError("Select at least one patch to install")
        allowed = target.available_patch_ids
        unknown = sorted(patch_id for patch_id in selected if patch_id not in allowed)
        if unknown:
            # The allowlist is the whole point: an operator can only install
            # what the platform observed as available on this specific host.
            raise PatchValidationError(
                "One or more selected patches are not available on this target",
                details={"target_id": target.target_id, "unknown_patch_ids": unknown},
            )
        if target.operation == OPERATION_NODE_IMAGE_UPGRADE and len(selected) > 1:
            raise PatchValidationError(
                "A node image upgrade targets exactly one image version",
                details={"selected": list(selected)},
            )
        pool = str(node_pool or "").strip()
        if target.requires_node_pool and not pool:
            raise PatchValidationError(
                "Name the AKS agent pool to upgrade; HOG will not roll every "
                "pool in the cluster implicitly",
                details={"target_id": target.target_id},
            )

        approver = self._authorize_approval(
            requested_by=requested_by, approved_by=approved_by, dry_run=dry_run
        )

        timestamp = _now()
        run = PatchRun(
            run_id=str(uuid.uuid4()),
            target_id=target.target_id,
            inventory_kind=target.inventory_kind,
            operation=target.operation,
            patch_ids=selected,
            state=RUN_STATE_PENDING,
            requested_by=requested_by,
            approved_by=approver,
            reason=reason,
            reboot_setting=reboot_setting,
            dry_run=dry_run,
            created_at=timestamp,
            updated_at=timestamp,
            subscription_id=target.subscription_id,
            subscription_connection=target.subscription_connection,
            business_service=target.business_service,
            environment=target.environment,
            details={
                "target_name": target.name,
                "resource_group": target.resource_group,
                **({"node_pool": pool} if pool else {}),
                **(
                    {"approval_context": copy.deepcopy(approval_context)}
                    if approval_context is not None
                    else {}
                ),
            },
        )

        if dry_run:
            run.state = "submitted"
            run.provider = "dry-run"
            run.message = "Validated without submitting to Azure"
            self._store.add(run)
            return run

        self._store.add(run)
        try:
            result = self._adapter.submit(run, target)
        except PatchExecutionUnavailable as exc:
            run.state = RUN_STATE_FAILED
            run.updated_at = _now()
            run.message = str(exc)
            run.details["capability"] = getattr(exc, "capability", "patch_execution")
            self._store.update(run)
            raise
        run.state = result.state or "submitted"
        run.provider = result.provider
        run.provider_job_id = result.provider_job_id
        run.message = result.message
        run.updated_at = _now()
        if result.details:
            run.details.update(result.details)
        self._store.update(run)
        return run


__all__ = [
    "OPERATION_INSTALL_PATCHES",
    "OPERATION_NODE_IMAGE_UPGRADE",
    "REBOOT_SETTINGS",
    "RUN_STATE_PENDING",
    "PatchValidationError",
    "PatchingService",
]
