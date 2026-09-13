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

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Query

from intelligence.governance import (
    EXPORT_KINDS,
    REVIEW_AUDIENCES,
    AccessReviewBuilder,
    AuditExportBuilder,
    FinOpsEngine,
    IdentityRiskEngine,
    SettingsValidationError,
    SpnGovernanceEngine,
    default_settings,
)

from ..dependencies import Context, ReadScope, WritePrincipal
from ..errors import ApiError, ErrorCode
from ..evidence import (
    CONFIDENCE_HIGH,
    CONFIDENCE_MEDIUM,
    CONFIDENCE_UNKNOWN,
    Evidence,
    envelope,
)
from ..governance_snapshot import GovernanceSnapshot
from ..scope import Scope

# Reuse the operations router's recursive scope filter so plan payloads are
# redacted by exactly the same rule everywhere, rather than a second copy.
from .operations import _HIDDEN, _filter_scoped

router = APIRouter(prefix="/api/v1/governance", tags=["governance"])

FINOPS_ENGINE = "intelligence.governance.FinOpsEngine"
IDENTITY_ENGINE = "intelligence.governance.IdentityRiskEngine"
SPN_ENGINE = "intelligence.governance.SpnGovernanceEngine"
SOURCE_TABLE = "connection_generation_entities"

_NO_IDENTITY_DATA = (
    "No role assignment data has been synced for this scope. This is not a "
    "statement that no privileged access exists -- run a connection sync to "
    "collect it."
)


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


def _finops(snapshot: GovernanceSnapshot) -> FinOpsEngine:
    return FinOpsEngine(
        advisor_recommendations=snapshot.rows("AdvisorRecommendation"),
        cost_actuals=snapshot.rows("CostActual"),
        resources=[
            *snapshot.rows("Resource"),
            *snapshot.rows("VirtualMachine"),
            *snapshot.rows("ArcServer"),
        ],
    )


def _identity(snapshot: GovernanceSnapshot) -> IdentityRiskEngine:
    return IdentityRiskEngine(
        role_assignments=snapshot.rows("RoleAssignment"),
        role_definitions=snapshot.rows("RoleDefinition"),
        managed_identities=snapshot.rows("ManagedIdentity"),
    )


def _spn(snapshot: GovernanceSnapshot) -> SpnGovernanceEngine:
    return SpnGovernanceEngine(
        snapshot.connections,
        role_assignments=snapshot.rows("RoleAssignment"),
    )


def _identity_warnings(snapshot: GovernanceSnapshot) -> list[str]:
    warnings = list(snapshot.warnings)
    if not snapshot.has_identity_data:
        warnings.append(_NO_IDENTITY_DATA)
    return list(dict.fromkeys(warnings))


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


@router.get("/exports/{kind}", summary="Generate an audit evidence pack")
def audit_export(
    kind: Literal[
        "subscription_onboarding",
        "network_design",
        "firewall_nsg",
        "vulnerability_exposure",
        "identity",
        "remediation",
        "executive",
    ],
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

    service = service.scoped(
        NetworkScope(
            connection_ids=tuple(scope.dimensions.get("subscription_connection", ())),
            subscription_ids=tuple(scope.dimensions.get("subscription", ())),
            environments=tuple(scope.dimensions.get("environment", ())),
            business_services=tuple(scope.dimensions.get("business_service", ())),
            applications=tuple(scope.dimensions.get("application", ())),
            owners=tuple(scope.dimensions.get("owner", ())),
        )
    )
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
def read_settings(context: Context, scope: ReadScope) -> dict[str, Any]:
    store = context.settings_store
    settings = store.read() if store is not None else default_settings()
    return envelope(
        settings,
        evidence=Evidence(
            source_engine="intelligence.governance.EnterpriseSettingsStore",
            source_table="enterprise_settings",
            confidence=CONFIDENCE_HIGH,
        ),
        scope=scope.to_dict(),
        warnings=[]
        if store is not None
        else ["Settings are not persisted in this deployment; defaults are shown"],
    )


@router.patch("/settings", summary="Update enterprise administration settings")
def update_settings(
    principal: WritePrincipal,
    context: Context,
    scope: ReadScope,
    changes: Annotated[dict[str, Any], Body()],
) -> dict[str, Any]:
    store = context.settings_store
    if store is None:
        raise ApiError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "Settings cannot be updated because no settings store is configured",
            {"capability": "settings", "provider_state": "unavailable"},
        )
    try:
        settings = store.update(changes)
    except SettingsValidationError as exc:
        raise ApiError(
            ErrorCode.INVALID_REQUEST, str(exc), {"section": sorted(changes)}
        ) from exc
    return envelope(
        settings,
        evidence=Evidence(
            source_engine="intelligence.governance.EnterpriseSettingsStore",
            source_table="enterprise_settings",
            confidence=CONFIDENCE_HIGH,
        ),
        scope=scope.to_dict(),
    )
