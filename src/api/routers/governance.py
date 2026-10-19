"""FinOps, identity risk, SPN governance, access review, and audit export routes.

All six deliverables share one router because they share one scoped snapshot:
resolving it once per request avoids re-reading the ontology for each concern.

Two properties hold across every route here:

* **Scope in, scope out.** Every handler filters the snapshot through
  ``ReadScope`` before any engine sees a row, so a caller can never widen
  their view by picking a governance route.
* **Absence is reported, never defaulted.** When identity data has not been
  synced the routes say so in a warning rather than returning an empty list,
  which a UI would otherwise render as "no privileged access" -- a false
  assurance on a security surface.
"""

from __future__ import annotations

import logging
import math
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query

from intelligence.governance import (
    EXPORT_KINDS,
    REVIEW_AUDIENCES,
    AccessReviewBuilder,
    AuditExportBuilder,
    SettingsValidationError,
    default_settings,
)
from intelligence.governance.campaigns import (
    AccessCampaignStore,
    CampaignCreate,
    CampaignDecision,
    CampaignNotFoundError,
    CampaignRemove,
    CampaignRequestError,
    CampaignReviewerError,
    CampaignTransition,
)
from intelligence.governance.retained_exports import (
    MAX_CAPTURES,
    AuditCaptureNotFoundError,
    AuditCaptureRemoval,
    AuditCaptureRequest,
    AuditCaptureRequestError,
    AuditKind,
    RetainedAuditExportStore,
)
from intelligence.governance.settings import MAX_SETTINGS_REVISION, SettingsChange
from intelligence.remediation.execution_store import execution_scope_attributes
from storage.onelake_documents import DocumentConflictError

from ..dependencies import Context, CurrentPrincipal, Page, ReadScope, WritePrincipal
from ..errors import ApiError, ErrorCode
from ..evidence import (
    CONFIDENCE_HIGH,
    CONFIDENCE_MEDIUM,
    CONFIDENCE_UNKNOWN,
    Evidence,
    envelope,
)
from ..governance_snapshot import GovernanceSnapshot
from ..governance_snapshot import finops_engine as _finops
from ..governance_snapshot import identity_engine as _identity
from ..governance_snapshot import identity_warnings as _identity_warnings
from ..governance_snapshot import spn_engine as _spn
from ..rbac import ACTION_WRITE
from ..scope import Scope

# Reuse the operations router's recursive scope filter so plan payloads are
# redacted by exactly the same rule everywhere, rather than a second copy.
from .operations import _HIDDEN, _filter_scoped

router = APIRouter(prefix="/api/v1/governance", tags=["governance"])
_LOGGER = logging.getLogger(__name__)

FINOPS_ENGINE = "intelligence.governance.FinOpsEngine"
IDENTITY_ENGINE = "intelligence.governance.IdentityRiskEngine"
SPN_ENGINE = "intelligence.governance.SpnGovernanceEngine"
SOURCE_TABLE = "connection_generation_entities"

def _snapshot(
    context: Context,
    scope: Scope,
    *,
    require_generation: bool = True,
) -> GovernanceSnapshot:
    """Resolve the governance snapshot already narrowed to the caller's scope."""
    return context.governance_snapshot(
        scope,
        require_generation=require_generation,
    )


def _evidence(
    snapshot: GovernanceSnapshot,
    engine: str,
    *,
    confidence: str = CONFIDENCE_HIGH,
    resource_id: str = "",
    source_table: str = SOURCE_TABLE,
) -> Evidence:
    return Evidence(
        source_engine=engine,
        source_table=source_table,
        resource_id=resource_id,
        confidence=confidence,
        timestamp=snapshot.observed_at,
    )


@router.get("/finops/summary", summary="Cost accountability summary")
def finops_summary(context: Context, scope: ReadScope) -> dict[str, Any]:
    """Identified savings and waste, with unavailable metrics named explicitly."""
    snapshot = _snapshot(context, scope)
    return envelope(
        _finops(snapshot).summary(),
        # Savings figures are Azure Advisor's own computation, not ours.
        evidence=_evidence(snapshot, FINOPS_ENGINE),
        scope=scope.to_dict(),
        warnings=snapshot.warnings,
    )


def _verified_remediation_records(
    context: Context, scope: Scope
) -> list[dict[str, Any]]:
    """Return only cleanly reconciled successful executions in the read scope."""
    if context.execution_record_reader is None:
        raise ApiError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "Stored remediation evidence is unavailable",
            {"capability": "remediation_execution_records"},
        )
    try:
        records = context.execution_record_reader()
        if not isinstance(records, list) or any(
            not isinstance(record, dict) for record in records
        ):
            raise ValueError("Stored execution collection is invalid")
    except (ValueError, TypeError, RuntimeError, OSError) as exc:
        raise ApiError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "Stored remediation evidence could not be confirmed",
            {"capability": "remediation_execution_records"},
        ) from exc

    verified: list[dict[str, Any]] = []
    for record in records:
        snapshot = record.get("execution_snapshot")
        reconciliation = record.get("evidence_reconciliation")
        target_id = (
            str(snapshot.get("target_id") or "").strip()
            if isinstance(snapshot, dict)
            else ""
        )
        if (
            record.get("status") != "succeeded"
            or not isinstance(reconciliation, dict)
            or reconciliation.get("status") != "reconciled_clean"
            or not target_id
            or not scope.matches(execution_scope_attributes(record))
        ):
            continue
        successful_transition = next(
            (
                str(event.get("timestamp") or "").strip()
                for event in reversed(record.get("history") or [])
                if isinstance(event, dict)
                and event.get("status") == "succeeded"
                and event.get("timestamp")
            ),
            "",
        )
        verified_at = str(reconciliation.get("assessed_at") or "").strip()
        try:
            changed_moment = datetime.fromisoformat(successful_transition)
            verified_moment = datetime.fromisoformat(verified_at)
        except ValueError:
            continue
        if changed_moment.tzinfo is None:
            changed_moment = changed_moment.replace(tzinfo=UTC)
        if verified_moment.tzinfo is None:
            verified_moment = verified_moment.replace(tzinfo=UTC)
        changed_at = changed_moment.astimezone(UTC).isoformat().replace(
            "+00:00", "Z"
        )
        verified_at = verified_moment.astimezone(UTC).isoformat().replace(
            "+00:00", "Z"
        )
        execution_id = str(record.get("execution_id") or "")
        if not execution_id:
            continue
        verified.append(
            {
                "execution_id": execution_id,
                "target_resource_id": target_id,
                "changed_at": changed_at,
                "verified_at": verified_at,
            }
        )
    return sorted(verified, key=lambda item: item["verified_at"], reverse=True)


@router.get(
    "/finops/verified-remediations",
    summary="List cleanly verified remediation changes for cost review",
)
def finops_verified_remediations(
    context: Context, scope: ReadScope, page: Page
) -> dict[str, Any]:
    records = _verified_remediation_records(context, scope)
    limit = min(page.limit, 50)
    return envelope(
        {
            "executions": records[page.offset : page.offset + limit],
            "count": len(records),
            "read_only": True,
            "boundary": (
                "Successful execution with clean stored evidence reconciliation; "
                "not proof that the execution caused later cost movement."
            ),
        },
        evidence=Evidence(
            source_engine="intelligence.RemediationExecutionStore",
            source_table="remediation_executions",
            confidence=CONFIDENCE_HIGH,
        ),
        scope=scope.to_dict(),
        pagination={
            "offset": page.offset,
            "limit": limit,
            "total": len(records),
            "next_offset": page.offset + limit if page.offset + limit < len(records) else None,
        },
    )


@router.get(
    "/finops/remediation-cost-comparison",
    summary="Compare same-resource Cost Management windows around a verified change",
)
def finops_remediation_cost_comparison(
    context: Context,
    scope: ReadScope,
    execution_id: Annotated[str, Query(min_length=1, max_length=128)],
    baseline_start: date,
    baseline_end: date,
    followup_start: date,
    followup_end: date,
) -> dict[str, Any]:
    """Compare observed resource costs without claiming remediation causality."""
    baseline_days = (baseline_end - baseline_start).days + 1
    followup_days = (followup_end - followup_start).days + 1
    if (
        baseline_days < 1
        or followup_days != baseline_days
        or baseline_days > 30
        or baseline_end >= followup_start
    ):
        raise ApiError(
            ErrorCode.INVALID_REQUEST,
            "Cost comparison requires non-overlapping, equal-length windows of 1 to 30 days",
        )

    def window_days(start: date, end: date) -> list[date]:
        return [
            date.fromordinal(start.toordinal() + offset)
            for offset in range((end - start).days + 1)
        ]

    records = _verified_remediation_records(context, scope)
    execution = next(
        (item for item in records if item["execution_id"] == execution_id),
        None,
    )
    if execution is None:
        # Do not reveal whether an execution exists outside this caller's scope.
        raise ApiError(ErrorCode.NOT_FOUND, "Verified remediation not found")
    changed_date = date.fromisoformat(execution["changed_at"][:10])
    verified_date = date.fromisoformat(execution["verified_at"][:10])
    if not baseline_end < changed_date or followup_start <= verified_date:
        raise ApiError(
            ErrorCode.INVALID_REQUEST,
            "The baseline must end before execution, and the follow-up must start after clean verification",
        )

    snapshot = _snapshot(context, scope)
    observed_at = snapshot.observed_at
    try:
        observed_date = date.fromisoformat(observed_at[:10])
    except ValueError:
        observed_date = None
    if observed_date is None or observed_date < followup_end:
        return envelope(
            {
                "available": False,
                "reason": "The current Cost Management snapshot does not cover the end of the follow-up window.",
                "execution": execution,
                "coverage": {
                    "snapshot_observed_at": observed_at,
                    "expected_days_per_window": baseline_days,
                    "baseline_days_observed": 0,
                    "baseline_missing_days": [
                        current.isoformat()
                        for current in window_days(baseline_start, baseline_end)
                    ],
                    "followup_days_observed": 0,
                    "followup_missing_days": [
                        current.isoformat()
                        for current in window_days(followup_start, followup_end)
                    ],
                    "cost_record_count": 0,
                },
                "limitations": [
                    "Observed cost movement is not proof of savings or causality."
                ],
            },
            evidence=_evidence(
                snapshot,
                FINOPS_ENGINE,
                confidence=CONFIDENCE_UNKNOWN,
                source_table="CostActual+remediation_executions",
            ),
            scope=scope.to_dict(),
            warnings=snapshot.warnings,
        )

    target_id = execution["target_resource_id"].casefold()
    rows = [
        row
        for row in snapshot.rows("CostActual")
        if str(row.get("targetResourceId") or row.get("resourceId") or "")
        .strip()
        .casefold()
        == target_id
        and str(row.get("sourceSystem") or "").casefold() == "azure:costmanagement"
    ]
    totals: dict[date, float] = {}
    currencies: set[str] = set()
    row_count = 0
    invalid_cost = False
    for row in rows:
        try:
            usage_day = date.fromisoformat(str(row.get("usageDate") or "")[:10])
        except ValueError:
            continue
        if not (
            baseline_start <= usage_day <= baseline_end
            or followup_start <= usage_day <= followup_end
        ):
            continue
        currency_code = str(row.get("currency") or "").strip().upper()
        currencies.add(currency_code)
        try:
            amount = float(row.get("cost"))
        except (TypeError, ValueError):
            invalid_cost = True
            continue
        if not math.isfinite(amount):
            invalid_cost = True
            continue
        totals[usage_day] = totals.get(usage_day, 0.0) + amount
        row_count += 1

    def missing_days(start: date, end: date) -> list[str]:
        return [current.isoformat() for current in window_days(start, end) if current not in totals]

    baseline_missing = missing_days(baseline_start, baseline_end)
    followup_missing = missing_days(followup_start, followup_end)
    unavailable_reason = ""
    if invalid_cost:
        unavailable_reason = "One or more Cost Management amounts are invalid."
    elif len(currencies) != 1 or not re.fullmatch(
        r"[A-Z]{3}", next(iter(currencies), "")
    ):
        unavailable_reason = "The selected resource does not have one reported currency across both windows."
    elif baseline_missing or followup_missing:
        unavailable_reason = "Daily Cost Management coverage is incomplete for this resource and the selected windows."

    coverage = {
        "expected_days_per_window": baseline_days,
        "baseline_days_observed": baseline_days - len(baseline_missing),
        "baseline_missing_days": baseline_missing,
        "followup_days_observed": followup_days - len(followup_missing),
        "followup_missing_days": followup_missing,
        "cost_record_count": row_count,
        "snapshot_observed_at": observed_at,
    }
    limitations = [
        "This is an observed cost comparison, not realized or causally attributed savings.",
        "The comparison covers only the exact remediation target and selected dates; other cost drivers are not controlled.",
        "A clean remediation evidence reconciliation verifies the recorded change, not its financial effect.",
    ]
    if unavailable_reason:
        data: dict[str, Any] = {
            "available": False,
            "reason": unavailable_reason,
            "execution": execution,
            "baseline": {"start": baseline_start.isoformat(), "end": baseline_end.isoformat()},
            "followup": {"start": followup_start.isoformat(), "end": followup_end.isoformat()},
            "coverage": coverage,
            "limitations": limitations,
        }
    else:
        baseline_total = sum(
            totals[baseline_start.fromordinal(baseline_start.toordinal() + offset)]
            for offset in range(baseline_days)
        )
        followup_total = sum(
            totals[followup_start.fromordinal(followup_start.toordinal() + offset)]
            for offset in range(followup_days)
        )
        data = {
            "available": True,
            "execution": execution,
            "baseline": {
                "start": baseline_start.isoformat(),
                "end": baseline_end.isoformat(),
                "total_cost": baseline_total,
                "average_daily_cost": baseline_total / baseline_days,
            },
            "followup": {
                "start": followup_start.isoformat(),
                "end": followup_end.isoformat(),
                "total_cost": followup_total,
                "average_daily_cost": followup_total / followup_days,
            },
            "currency": next(iter(currencies)),
            "observed_average_daily_cost_change": (
                baseline_total / baseline_days - followup_total / followup_days
            ),
            "coverage": coverage,
            "limitations": limitations,
        }
    return envelope(
        data,
        evidence=_evidence(
            snapshot,
            FINOPS_ENGINE,
            confidence=CONFIDENCE_UNKNOWN,
            source_table="CostActual+remediation_executions",
        ),
        scope=scope.to_dict(),
        warnings=snapshot.warnings,
    )


@router.get("/finops/opportunities", summary="Cost savings opportunities")
def finops_opportunities(context: Context, scope: ReadScope) -> dict[str, Any]:
    snapshot = _snapshot(context, scope)
    opportunities = _finops(snapshot).savings_opportunities()
    return envelope(
        {
            "opportunities": [item.to_dict() for item in opportunities],
            "count": len(opportunities),
        },
        evidence=_evidence(snapshot, FINOPS_ENGINE),
        scope=scope.to_dict(),
        warnings=snapshot.warnings,
    )


@router.get("/finops/waste", summary="Provisioned but unused resources")
def finops_waste(context: Context, scope: ReadScope) -> dict[str, Any]:
    snapshot = _snapshot(context, scope)
    items = _finops(snapshot).waste()
    return envelope(
        {"waste": [item.to_dict() for item in items], "count": len(items)},
        # Inventory-derived waste is inferred from resource state rather than
        # from observed utilisation, so it is a medium-confidence signal.
        evidence=_evidence(snapshot, FINOPS_ENGINE, confidence=CONFIDENCE_MEDIUM),
        scope=scope.to_dict(),
        warnings=snapshot.warnings,
    )


@router.get("/finops/attribution", summary="Savings and waste by business dimension")
def finops_attribution(
    context: Context,
    scope: ReadScope,
    dimension: Annotated[
        Literal["subscription", "application", "business_service", "owner", "environment"],
        Query(),
    ] = "subscription",
) -> dict[str, Any]:
    snapshot = _snapshot(context, scope)
    groups = _finops(snapshot).by_dimension(dimension)
    return envelope(
        {"dimension": dimension, "groups": groups, "count": len(groups)},
        evidence=_evidence(snapshot, FINOPS_ENGINE),
        scope=scope.to_dict(),
        warnings=snapshot.warnings,
    )


@router.get("/identity/summary", summary="Identity risk summary")
def identity_summary(context: Context, scope: ReadScope) -> dict[str, Any]:
    snapshot = _snapshot(context, scope)
    return envelope(
        _identity(snapshot).summary(),
        evidence=_evidence(snapshot, IDENTITY_ENGINE),
        scope=scope.to_dict(),
        warnings=_identity_warnings(snapshot),
    )


@router.get("/identity/principals", summary="Principals holding access")
def identity_principals(
    context: Context,
    scope: ReadScope,
    privileged_only: Annotated[bool, Query()] = False,
) -> dict[str, Any]:
    snapshot = _snapshot(context, scope)
    principals = _identity(snapshot).principals()
    if privileged_only:
        principals = [record for record in principals if record.privileged]
    return envelope(
        {
            "principals": [record.to_dict() for record in principals],
            "count": len(principals),
        },
        evidence=_evidence(snapshot, IDENTITY_ENGINE),
        scope=scope.to_dict(),
        warnings=_identity_warnings(snapshot),
    )


@router.get("/identity/least-privilege", summary="Least-privilege review candidates")
def identity_least_privilege(
    context: Context,
    scope: ReadScope,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    """Return scoped, advisory assignment candidates without evaluating effective access."""
    snapshot = _snapshot(context, scope)
    review = _identity(snapshot).least_privilege_review(offset=offset, limit=limit)
    return envelope(
        review,
        evidence=_evidence(snapshot, IDENTITY_ENGINE),
        scope=scope.to_dict(),
        warnings=_identity_warnings(snapshot),
    )


@router.get("/identity/subscription-owners", summary="Subscription owners")
def identity_subscription_owners(context: Context, scope: ReadScope) -> dict[str, Any]:
    snapshot = _snapshot(context, scope)
    owners = _identity(snapshot).subscription_owners()
    return envelope(
        {"owners": owners, "count": len(owners)},
        evidence=_evidence(snapshot, IDENTITY_ENGINE),
        scope=scope.to_dict(),
        warnings=_identity_warnings(snapshot),
    )


@router.get("/identity/stale-access", summary="Stale role assignments")
def identity_stale_access(context: Context, scope: ReadScope) -> dict[str, Any]:
    snapshot = _snapshot(context, scope)
    stale = _identity(snapshot).stale_access()
    return envelope(
        {"assignments": stale, "count": len(stale)},
        # Staleness is derived from the assignment's own change timestamp,
        # which is an observed fact rather than an inference.
        evidence=_evidence(snapshot, IDENTITY_ENGINE),
        scope=scope.to_dict(),
        warnings=_identity_warnings(snapshot),
    )


@router.get("/identity/non-human", summary="Service principals and managed identities")
def identity_non_human(context: Context, scope: ReadScope) -> dict[str, Any]:
    snapshot = _snapshot(context, scope)
    identities = _identity(snapshot).non_human_identities()
    return envelope(
        {"identities": identities, "count": len(identities)},
        evidence=_evidence(snapshot, IDENTITY_ENGINE),
        scope=scope.to_dict(),
        warnings=_identity_warnings(snapshot),
    )


@router.get("/spn/credentials", summary="Onboarding service principal governance")
def spn_credentials(context: Context, scope: ReadScope) -> dict[str, Any]:
    """Rotation posture for the credentials the platform itself holds."""
    snapshot = _snapshot(context, scope, require_generation=False)
    engine = _spn(snapshot)
    credentials = engine.credentials()
    return envelope(
        {
            "credentials": [record.to_dict() for record in credentials],
            "count": len(credentials),
            "summary": engine.summary(),
        },
        # Sourced from the connection registry the platform owns, so this is
        # a complete record rather than a sampled one.
        evidence=_evidence(
            snapshot,
            SPN_ENGINE,
            source_table="connection_registry",
        ),
        scope=scope.to_dict(),
        warnings=snapshot.warnings,
    )


def _can_manage_campaigns(context: Context, principal: CurrentPrincipal, scope: Scope) -> bool:
    try:
        writable = context.authorizer.effective_scope(principal, ACTION_WRITE, scope)
    except ApiError as exc:
        if exc.code == ErrorCode.FORBIDDEN:
            return False
        raise
    return writable.to_dict() == scope.to_dict()


def _require_campaign_manager(context: Context, principal: CurrentPrincipal, scope: Scope) -> None:
    if not _can_manage_campaigns(context, principal, scope):
        raise ApiError(ErrorCode.FORBIDDEN, "Managing campaigns requires write authority over the entire selected read scope")


@contextmanager
def _campaigns(context: Context) -> Iterator[AccessCampaignStore]:
    store = context.access_campaign_store
    if store is None:
        raise ApiError(ErrorCode.PROVIDER_UNAVAILABLE, "Access campaign storage is unavailable")
    try:
        yield store
    except ApiError:
        raise
    except DocumentConflictError as exc:
        raise ApiError(ErrorCode.CONFLICT, "Access campaigns changed; reload before another action") from exc
    except CampaignNotFoundError as exc:
        raise ApiError(ErrorCode.NOT_FOUND, "Access campaign not found") from exc
    except CampaignReviewerError as exc:
        raise ApiError(ErrorCode.FORBIDDEN, str(exc)) from exc
    except CampaignRequestError as exc:
        raise ApiError(ErrorCode.INVALID_REQUEST, str(exc)) from exc
    except Exception as exc:
        _LOGGER.warning("Access campaign operation unavailable (%s)", type(exc).__name__)
        raise ApiError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "Access campaign operation could not be confirmed; reload before another action",
        ) from exc


def _campaign_envelope(data: dict[str, Any], context: Context, principal: CurrentPrincipal, scope: Scope) -> dict[str, Any]:
    return envelope(
        {**data, "current_subject": principal.subject,
         "can_manage": _can_manage_campaigns(context, principal, scope)},
        scope=scope.to_dict(),
        evidence=Evidence(
            source_engine="intelligence.governance.AccessCampaignStore",
            source_table="access_campaigns", confidence=CONFIDENCE_UNKNOWN,
        ),
    )


@router.get("/access-campaigns", summary="Shared exact-scope advisory access campaigns")
def access_campaigns(context: Context, principal: CurrentPrincipal, scope: ReadScope) -> dict[str, Any]:
    with _campaigns(context) as store:
        data = store.read(scope.to_dict())
    return _campaign_envelope(data, context, principal, scope)


@router.post("/access-campaigns", status_code=201, summary="Create a frozen-source assigned access campaign")
def create_access_campaign(
    payload: CampaignCreate, context: Context, principal: CurrentPrincipal, scope: ReadScope,
) -> dict[str, Any]:
    _require_campaign_manager(context, principal, scope)
    with _campaigns(context) as store:
        store.preflight_create(scope.to_dict(), payload)
        document = access_review(payload.audience, context, scope)
        data = store.create(scope.to_dict(), payload, principal.subject, document)
    return _campaign_envelope(data, context, principal, scope)


@router.get("/access-campaigns/{campaign_id}", summary="Recover frozen access campaign evidence and recommendations")
def access_campaign(
    campaign_id: str, context: Context, principal: CurrentPrincipal, scope: ReadScope,
) -> dict[str, Any]:
    with _campaigns(context) as store:
        data = store.detail(scope.to_dict(), campaign_id)
    return _campaign_envelope(data, context, principal, scope)


@router.post("/access-campaigns/decisions", summary="Record the assigned reviewer's source-bound recommendation")
def decide_access_campaign(
    payload: CampaignDecision, context: Context, principal: CurrentPrincipal, scope: ReadScope,
) -> dict[str, Any]:
    with _campaigns(context) as store:
        data = store.decide(scope.to_dict(), payload, principal.subject)
    return _campaign_envelope(data, context, principal, scope)


@router.post("/access-campaigns/remove", summary="Explicitly remove a terminal campaign stored copy")
def remove_access_campaign(
    payload: CampaignRemove, context: Context, principal: CurrentPrincipal, scope: ReadScope,
) -> dict[str, Any]:
    _require_campaign_manager(context, principal, scope)
    with _campaigns(context) as store:
        data = store.remove(scope.to_dict(), payload)
    return _campaign_envelope(data, context, principal, scope)


@router.post("/access-campaigns/{action}", summary="Explicitly complete or cancel an advisory campaign")
def close_access_campaign(
    action: Literal["complete", "cancel"], payload: CampaignTransition,
    context: Context, principal: CurrentPrincipal, scope: ReadScope,
) -> dict[str, Any]:
    _require_campaign_manager(context, principal, scope)
    with _campaigns(context) as store:
        data = store.transition(scope.to_dict(), payload, principal.subject, action)
    return _campaign_envelope(data, context, principal, scope)


@router.get("/access-reviews/{audience}", summary="Access review pack")
def access_review(
    audience: Literal["service_owner", "security", "auditor"],
    context: Context,
    scope: ReadScope,
) -> dict[str, Any]:
    snapshot = _snapshot(context, scope)
    builder = AccessReviewBuilder(
        identity_engine=_identity(snapshot),
        spn_engine=_spn(snapshot),
        scope=scope.to_dict(),
        observed_at=snapshot.observed_at,
    )
    return envelope(
        builder.build(audience),
        evidence=_evidence(snapshot, IDENTITY_ENGINE),
        scope=scope.to_dict(),
        warnings=_identity_warnings(snapshot),
    )


@router.get("/access-reviews", summary="Available access review packs")
def access_review_kinds() -> dict[str, Any]:
    return envelope(
        {"audiences": list(REVIEW_AUDIENCES)},
        evidence=Evidence(source_engine=IDENTITY_ENGINE, confidence=CONFIDENCE_HIGH),
    )


@router.get("/exports", summary="Available audit evidence packs")
def export_kinds() -> dict[str, Any]:
    return envelope(
        {"kinds": list(EXPORT_KINDS)},
        evidence=Evidence(source_engine=IDENTITY_ENGINE, confidence=CONFIDENCE_HIGH),
    )


@contextmanager
def _retained_exports(context: Context) -> Iterator[RetainedAuditExportStore]:
    store = context.retained_audit_export_store
    if store is None:
        raise ApiError(ErrorCode.PROVIDER_UNAVAILABLE, "Retained audit export storage is unavailable")
    try:
        yield store
    except ApiError:
        raise
    except DocumentConflictError as exc:
        raise ApiError(ErrorCode.CONFLICT, "Audit exports changed; reload before another action") from exc
    except AuditCaptureNotFoundError as exc:
        raise ApiError(ErrorCode.NOT_FOUND, "Retained audit export not found") from exc
    except AuditCaptureRequestError as exc:
        raise ApiError(ErrorCode.INVALID_REQUEST, str(exc)) from exc
    except Exception as exc:
        _LOGGER.warning("Retained audit export operation unavailable (%s)", type(exc).__name__)
        raise ApiError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "Retained audit export operation could not be confirmed; reload before another action",
        ) from exc


def _retained_envelope(data: dict[str, Any], scope: Scope) -> dict[str, Any]:
    return envelope(
        data, scope=scope.to_dict(),
        evidence=Evidence(
            source_engine="intelligence.governance.RetainedAuditExportStore",
            source_table="retained_audit_exports", confidence=CONFIDENCE_UNKNOWN,
        ),
    )


@router.get("/exports/retained", summary="Recover personal exact-scope audit captures")
def retained_audit_exports(
    context: Context, principal: CurrentPrincipal, scope: ReadScope,
) -> dict[str, Any]:
    with _retained_exports(context) as store:
        result = store.read(principal.subject, scope.to_dict())
    return _retained_envelope(result, scope)


@router.post("/exports/retained", status_code=201, summary="Generate and retain current audit evidence")
def capture_audit_export(
    payload: AuditCaptureRequest, context: Context,
    principal: CurrentPrincipal, scope: ReadScope,
) -> dict[str, Any]:
    with _retained_exports(context) as store:
        current = store.read(principal.subject, scope.to_dict())
        if current["revision"] != payload.expected_revision:
            raise DocumentConflictError("Audit exports changed")
        if len(current["captures"]) >= MAX_CAPTURES:
            raise AuditCaptureRequestError("Audit export collection is full; explicitly remove a capture")
        document = audit_export(payload.kind, context, scope)
        result = store.capture(
            principal.subject, scope.to_dict(), payload.expected_revision,
            document=document,
        )
    return _retained_envelope(result, scope)


@router.get("/exports/retained/{export_id}", summary="Recover exact retained audit JSON")
def retained_audit_export(
    export_id: str, context: Context, principal: CurrentPrincipal, scope: ReadScope,
) -> dict[str, Any]:
    with _retained_exports(context) as store:
        result = store.detail(principal.subject, scope.to_dict(), export_id)
    return _retained_envelope(result, scope)


@router.post("/exports/retained/remove", summary="Remove one reviewed personal audit capture")
def remove_audit_export(
    payload: AuditCaptureRemoval, context: Context,
    principal: CurrentPrincipal, scope: ReadScope,
) -> dict[str, Any]:
    with _retained_exports(context) as store:
        result = store.remove(
            principal.subject, scope.to_dict(), payload.expected_revision, payload.export_id,
        )
    return _retained_envelope(result, scope)


@router.get("/exports/{kind}", summary="Generate an audit evidence pack")
def audit_export(
    kind: AuditKind,
    context: Context,
    scope: ReadScope,
) -> dict[str, Any]:
    """Assemble an evidence pack from whichever engines the pack requires.

    Each section is resolved independently and a failure degrades that section
    to a warning rather than failing the whole pack: a partial pack with its
    gaps stated is more useful to an auditor than no pack at all.
    """
    snapshot = _snapshot(
        context,
        scope,
        require_generation=kind != "subscription_onboarding",
    )
    builder = AuditExportBuilder(
        scope=scope.to_dict(), observed_at=snapshot.observed_at
    )
    sections: dict[str, Any] = {}
    engines: list[str] = []
    warnings: list[str] = list(snapshot.warnings)

    if kind == "subscription_onboarding":
        engines.append(SPN_ENGINE)
        spn_engine = _spn(snapshot)
        sections["connections"] = [
            {
                "connection_id": connection.get("connection_id", ""),
                "name": connection.get("name", ""),
                "subscription_id": connection.get("subscription_id", ""),
                "tenant_id": connection.get("tenant_id", ""),
                "is_active": connection.get("is_active", True),
            }
            for connection in snapshot.connections
        ]
        sections["credentials"] = [
            record.to_dict() for record in spn_engine.credentials()
        ]
        sections["credential_summary"] = spn_engine.summary()
    elif kind == "identity":
        engines.append(IDENTITY_ENGINE)
        identity_engine = _identity(snapshot)
        sections["principals"] = [
            record.to_dict() for record in identity_engine.principals()
        ]
        sections["subscription_owners"] = identity_engine.subscription_owners()
        sections["stale_access"] = identity_engine.stale_access()
        sections["non_human_identities"] = identity_engine.non_human_identities()
        sections["summary"] = identity_engine.summary()
        warnings.extend(_identity_warnings(snapshot))
    elif kind in {"network_design", "firewall_nsg"}:
        engines.append("network.NetworkIntelligenceService")
        sections.update(_network_sections(context, scope, kind, warnings))
    elif kind == "vulnerability_exposure":
        engines.append("intelligence.vulnerability.VulnerabilityIntelligenceService")
        sections.update(_vulnerability_sections(context, scope, warnings))
    elif kind == "remediation":
        engines.append("intelligence.remediation.RemediationPlanner")
        sections.update(_remediation_sections(context, scope, warnings))
    else:
        engines.extend([FINOPS_ENGINE, IDENTITY_ENGINE, SPN_ENGINE])
        identity_engine = _identity(snapshot)
        sections["finops"] = _finops(snapshot).summary()
        sections["identity"] = identity_engine.summary()
        sections["service_principals"] = _spn(snapshot).summary()
        sections["subscription_count"] = len(
            {
                connection.get("subscription_id", "")
                for connection in snapshot.connections
            }
        )
        warnings.extend(_identity_warnings(snapshot))

    evidence: list[Evidence]
    independent_sources = {
        "network_design": (
            "network.NetworkIntelligenceService",
            "network_provider",
        ),
        "firewall_nsg": (
            "network.NetworkIntelligenceService",
            "network_provider",
        ),
        "vulnerability_exposure": (
            "intelligence.vulnerability.VulnerabilityIntelligenceService",
            "vulnerability_provider",
        ),
        "remediation": (
            "intelligence.remediation.RemediationPlanner",
            "remediation_provider",
        ),
    }
    if kind in independent_sources:
        engine, source_table = independent_sources[kind]
        evidence = [
            Evidence(
                source_engine=engine,
                source_table=source_table,
                confidence=CONFIDENCE_UNKNOWN,
            )
        ]
    else:
        evidence = [
            _evidence(snapshot, engines[0] if engines else IDENTITY_ENGINE)
        ]
    if kind == "subscription_onboarding":
        evidence = [
            _evidence(
                snapshot,
                SPN_ENGINE,
                source_table="connection_registry",
            )
        ]
    elif kind == "executive":
        evidence.append(
            _evidence(
                snapshot,
                SPN_ENGINE,
                source_table="connection_registry",
            )
        )
    return envelope(
        builder.build(kind, sections, engines=engines, warnings=warnings),
        evidence=evidence,
        scope=scope.to_dict(),
        warnings=warnings,
    )


def _network_sections(
    context: Context, scope: Scope, kind: str, warnings: list[str]
) -> dict[str, Any]:
    service = context.resolve_provider("network", optional=True)
    if service is None:
        warnings.append("Network data is unavailable; network sections are empty")
        return {"topology": {}, "design_gaps": []}
    from network.service import NetworkScope

    service = service.scoped(NetworkScope.from_dimensions(scope.dimensions))
    if kind == "firewall_nsg":
        gaps = service.firewall_bypass_spokes()
        return {
            "firewall_bypass": [gap.to_dict() for gap in gaps],
            "summary": service.analyze().summary(),
        }
    analysis = service.analyze()
    return {
        "topology": analysis.topology.to_dict(),
        "summary": analysis.summary(),
    }


def _vulnerability_sections(
    context: Context, scope: Scope, warnings: list[str]
) -> dict[str, Any]:
    service = context.resolve_provider("vulnerability", optional=True)
    if service is None:
        warnings.append(
            "Vulnerability data is unavailable; exposure sections are empty"
        )
        return {"summary": {}, "exposures": []}
    # The vulnerability service applies the caller's scope itself, so the
    # pack cannot widen beyond what the principal may already read.
    exposures = [item.to_dict() for item in service.exposures(scope)]
    return {"summary": service.summary(scope), "exposures": exposures}


def _remediation_sections(
    context: Context, scope: Scope, warnings: list[str]
) -> dict[str, Any]:
    planner = context.resolve_provider("remediation", optional=True)
    if planner is None:
        warnings.append("Remediation data is unavailable; plan sections are empty")
        return {"plans": []}
    generated = planner.generate_plans()
    plans = _filter_scoped(generated.get("plans"), scope)
    if plans is _HIDDEN or not isinstance(plans, list):
        plans = []
    return {"plans": plans, "generated_at": generated.get("generated_at", "")}


@router.get("/settings", summary="Enterprise administration settings")
def read_settings(context: Context, scope: ReadScope, principal: CurrentPrincipal) -> dict[str, Any]:
    store = context.settings_store
    try:
        settings = store.read_versioned() if store is not None else {
            **default_settings(), "revision": 0, "last_change": None, "persistent": False,
        }
    except Exception as exc:
        _LOGGER.warning("Enterprise settings read unavailable (%s)", type(exc).__name__)
        raise ApiError(ErrorCode.PROVIDER_UNAVAILABLE, "Enterprise settings could not be read") from exc
    settings["can_write"] = settings["persistent"] and settings["revision"] < MAX_SETTINGS_REVISION and any(
        grant.scope.is_unrestricted() for grant in principal.grants_for("write")
    )
    return envelope(
        settings,
        evidence=Evidence(
            source_engine="intelligence.governance.EnterpriseSettingsStore",
            source_table="enterprise_settings",
            confidence=CONFIDENCE_HIGH,
        ),
        scope=scope.to_dict(),
        warnings=[]
        if settings["persistent"]
        else ["Settings persistence is unavailable; this is not a durable policy"],
    )


@router.patch("/settings", summary="Update enterprise administration settings")
def update_settings(
    principal: WritePrincipal,
    context: Context,
    scope: ReadScope,
    change: SettingsChange,
) -> dict[str, Any]:
    if not any(grant.scope.is_unrestricted() for grant in principal.grants_for("write")):
        raise ApiError(
            ErrorCode.FORBIDDEN,
            "Enterprise-wide settings require an unrestricted administrator grant",
        )
    store = context.settings_store
    if store is None:
        raise ApiError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "Settings cannot be updated because no settings store is configured",
            {"capability": "settings", "provider_state": "unavailable"},
        )
    try:
        settings = store.update(
            change.changes, expected_revision=change.expected_revision,
            reason=change.reason, actor=principal.subject,
        )
    except DocumentConflictError as exc:
        raise ApiError(ErrorCode.CONFLICT, "Settings changed; reload and review again") from exc
    except SettingsValidationError as exc:
        raise ApiError(
            ErrorCode.INVALID_REQUEST, str(exc), {"section": sorted(change.changes)}
        ) from exc
    except Exception as exc:
        _LOGGER.warning("Enterprise settings write unavailable (%s)", type(exc).__name__)
        raise ApiError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "Settings save could not be confirmed; reload before reviewing another change",
        ) from exc
    settings["can_write"] = settings["persistent"] and settings["revision"] < MAX_SETTINGS_REVISION
    return envelope(
        settings,
        evidence=Evidence(
            source_engine="intelligence.governance.EnterpriseSettingsStore",
            source_table="enterprise_settings",
            confidence=CONFIDENCE_HIGH,
        ),
        scope=scope.to_dict(),
    )
