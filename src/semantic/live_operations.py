from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from api.evidence import classify_freshness
from intelligence.lifecycle.lifecycle_context_builder import canonical_resource_key
from intelligence.remediation.action_catalog import PATCH_RECOVERY_ACTION_FAMILY
from intelligence.remediation.action_version import action_version_for
from intelligence.remediation.approval_engine import DEFAULT_ROLE_ID, ApprovalEngine
from intelligence.remediation.plan_repository import PlanRepository
from intelligence.vulnerability.service import VulnerabilityIntelligenceService
from onboarding.query_contract import QuerySpec

from .live_provider import LiveResourceProvider


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _text(value: Any) -> str:
    return str(value or "").strip()


def _identity_subscription(row: dict[str, Any]) -> str:
    """Casefold-normalize ``subscription_id`` for stable identity hashing.

    ``canonical_resource_key`` already casefolds the target segment of the
    identity hash; the subscription segment must be normalized the same way
    (WR-03), because ARG/vulnerability-service rows are external data whose
    GUID casing this codebase does not control. Without this, the same asset
    reported with a differently-cased subscription GUID between two polls
    would silently mint a new ``plan_id``, reproducing the CR-01/WR-07
    audit-orphaning failure mode this phase exists to close.
    """
    return _text(row.get("subscription_id")).casefold()


def _properties(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("properties")
    return dict(value) if isinstance(value, dict) else {}


def _first(*values: Any) -> str:
    for value in values:
        text = _text(value)
        if text:
            return text
    return ""


def _kb(value: Any) -> str:
    text = _text(value)
    return text[2:] if text.upper().startswith("KB") else text


def _patch_evidence_source_ids(values: Any) -> list[str]:
    """Return stable source-owned patch finding ids before applying the UI cap.

    ``_build_vulnerability_service`` expands one ARG patch-assessment row into
    one finding per resolved CVE by appending ``|CVE-*`` (or a ``|KB-*`` proxy)
    to the source row id. Those optional enrichment suffixes are not part of
    the governed patch action and can differ across independent provider
    generations. Strip only those known synthetic suffixes, normalize the
    case-insensitive ARM identity, deduplicate, and sort before limiting.
    """
    source_ids: set[str] = set()
    for value in values or ():
        source_id = _text(value)
        stem, separator, derived_id = source_id.rpartition("|")
        if separator and derived_id.casefold().startswith(("cve-", "kb-")):
            source_id = stem
        if source_id:
            source_ids.add(source_id.casefold())
    return sorted(source_ids)[:10]


def _target_from_patch_row(row: dict[str, Any]) -> str:
    props = _properties(row)
    explicit = _first(
        props.get("targetResourceId"),
        props.get("target_resource_id"),
        row.get("targetResourceId"),
        row.get("target_resource_id"),
    )
    if explicit:
        return explicit
    resource_id = _text(row.get("id"))
    marker = "/providers/microsoft.guestconfiguration/"
    if marker in resource_id.casefold():
        return resource_id[: resource_id.casefold().index(marker)]
    return resource_id.rsplit("/patchAssessmentResults/", 1)[0].rsplit(
        "/patchInstallationResults/", 1
    )[0]


def _patch_finding(row: dict[str, Any], *, installed: bool) -> dict[str, Any] | None:
    props = _properties(row)
    kb_id = _kb(
        _first(
            props.get("kbId"),
            props.get("kbID"),
            props.get("kb_id"),
            row.get("kbId"),
            row.get("name"),
        )
    )
    target = _target_from_patch_row(row)
    if not kb_id or not target:
        return None
    return {
        "resource_id": _first(row.get("id"), f"{target}|{kb_id}"),
        "target_resource_id": target,
        # Keep the ARG scope identity with the finding.  Optional semantic
        # resource metadata may be unavailable for a live target, but the
        # subscription is still the authoritative join key for onboarding
        # metadata.
        "subscription_id": _first(
            row.get("subscriptionId"),
            row.get("subscription_id"),
            _subscription_id_from_resource_id(target),
        ),
        "kb_id": kb_id,
        "status": "installed" if installed else "missing",
        "severity": _first(
            props.get("classification"),
            props.get("classifications"),
            props.get("severity"),
            "Unknown",
        ),
        "update_name": _first(props.get("patchName"), props.get("title"), kb_id),
        "published_at": _first(
            props.get("publishedDateTime"),
            props.get("published_at"),
            props.get("lastModifiedDateTime"),
            row.get("observed_at"),
        ),
        "timestamp": _first(row.get("observed_at"), _now()),
    }


def _subscription_id_from_resource_id(resource_id: str) -> str:
    """Extract the subscription segment from a canonical ARM resource id."""
    parts = [part for part in resource_id.strip("/").split("/") if part]
    for index, part in enumerate(parts[:-1]):
        if part.casefold() == "subscriptions":
            return parts[index + 1]
    return ""


def live_vulnerability_service(
    live_resources: LiveResourceProvider,
    *,
    subscription_ids: list[str],
    semantic: Any = None,
    network: Any = None,
    build_service: Any,
) -> VulnerabilityIntelligenceService | None:
    """Build vulnerability intelligence from request-time Update Manager ARG rows."""
    projection = (
        "project id, name, type, tenantId, subscriptionId, resourceGroup, "
        "location, tags, properties, observed_at=now()"
    )
    assessments = live_resources.query(
        QuerySpec(
            "live_patch_assessment_details",
            "PatchAssessmentResources",
            "patchassessmentresources "
            "| where type endswith '/softwarepatches' "
            f"| {projection}",
            False,
        ),
        subscription_ids=subscription_ids,
    )
    installations = live_resources.query(
        QuerySpec(
            "live_patch_installations",
            "PatchInstallationResources",
            "patchinstallationresources "
            "| where type endswith '/softwarepatches' "
            f"| {projection}",
            False,
        ),
        subscription_ids=subscription_ids,
    )
    findings = [
        item
        for row in assessments.rows
        if (item := _patch_finding(row, installed=False)) is not None
    ]
    findings.extend(
        item
        for row in installations.rows
        if (item := _patch_finding(row, installed=True)) is not None
    )
    observed_at = max(assessments.observed_at, installations.observed_at)
    return build_service(
        [{"silver_patch_findings": findings}],
        observed_at,
        semantic=semantic,
        network=network,
    )


class LiveIncidentEngine:
    """Incident facade over request-time Azure Monitor alert rows."""

    def __init__(self, rows: tuple[dict[str, Any], ...], observed_at: str) -> None:
        self.rows = rows
        self.freshness = observed_at

    def report(self) -> dict[str, Any]:
        return {
            "report_type": "live_alert_incident_report",
            "audience_summaries": [],
            "incidents": [self._incident(row) for row in self.rows],
            "operational_patterns": [],
            "freshness": self.freshness,
            "read_only": True,
            "source_status": {"azure-monitor-alerts": "ok"},
        }

    def incident(self, incident_id: str) -> dict[str, Any] | None:
        target = incident_id.casefold()
        for row in self.rows:
            public = self._incident(row)
            if public["incident"]["incident_id"].casefold() == target:
                return {
                    "finding": public,
                    "freshness": self.freshness,
                    "read_only": True,
                    "source_status": {"azure-monitor-alerts": "ok"},
                }
        return None

    def _incident(self, row: dict[str, Any]) -> dict[str, Any]:
        props = _properties(row)
        essentials = (
            dict(props.get("essentials"))
            if isinstance(props.get("essentials"), dict)
            else props
        )
        alert_id = _first(
            essentials.get("alertId"),
            essentials.get("monitorCondition"),
            row.get("id"),
        )
        started_at = _first(
            essentials.get("startDateTime"),
            essentials.get("firedDateTime"),
            essentials.get("lastModifiedDateTime"),
            self.freshness,
        )
        resource_id = _first(
            essentials.get("targetResource"),
            essentials.get("targetResourceId"),
            row.get("id"),
        )
        severity = _first(essentials.get("severity"), "Sev3")
        return {
            "incident": {
                "incident_id": alert_id,
                "title": _first(
                    essentials.get("alertRule"),
                    essentials.get("description"),
                    row.get("name"),
                    "Azure Monitor alert",
                ),
                "severity": severity,
                "status": _first(
                    essentials.get("monitorCondition"),
                    essentials.get("alertState"),
                    "active",
                ),
                "started_at": started_at,
                "resource_id": resource_id,
            },
            "root_cause_analysis": {
                "probable_causes": [],
                "contributing_factors": [],
                "reasoning_chain": [
                    "Live alert surfaced from Azure Monitor; root-cause inference requires correlated logs and metrics."
                ],
            },
            "blast_radius": {"dependency_tree": [], "applications": [], "services": []},
            "timeline": [
                {
                    "event_id": alert_id,
                    "timestamp": started_at,
                    "event_type": "Azure Monitor Alert",
                    "title": _first(essentials.get("alertRule"), row.get("name")),
                    "resource_id": resource_id,
                }
            ],
            "business_impact": {
                "applications": [],
                "services": [],
                "business_services": [],
                "owners": [],
                "support_teams": [],
                "risk_score": _severity_score(severity),
            },
            "subscription_id": _first(row.get("subscriptionId")),
        }


def _severity_score(severity: str) -> int:
    mapping = {"sev0": 100, "sev1": 90, "sev2": 75, "sev3": 50, "sev4": 25}
    return mapping.get(severity.casefold(), 50)


def live_incident_engine(
    live_resources: LiveResourceProvider, *, subscription_ids: list[str]
) -> LiveIncidentEngine:
    observation = live_resources.query(
        QuerySpec(
            "live_alerts",
            "AlertsManagementResources",
            "alertsmanagementresources "
            "| where type =~ 'microsoft.alertsmanagement/alerts' "
            "| project id, name, type, tenantId, subscriptionId, resourceGroup, "
            "location, tags, properties, observed_at=now()",
            False,
        ),
        subscription_ids=subscription_ids,
    )
    return LiveIncidentEngine(observation.rows, observation.observed_at)


# These two shipped, single-role live policies explicitly opt their one
# role into the RBAC-capacity-compatible ``DEFAULT_ROLE_ID`` ("approver")
# via ``role_ids`` (Phase 03.5 CR-05 fix) -- deliberately, for backward
# compatibility with every deployment that has not configured a directory
# -backed per-role identity: any principal who reaches
# ``record_remediation_decision`` already holds the RBAC ``approve``
# capacity, so a single-role live policy remains satisfiable out of the
# box exactly as before. This is a narrow, explicit exception -- it does
# NOT apply to the multi-role Fabric/catalog production policy catalog
# (``remediation_approval_policies`` Silver table), whose distinct
# organizational roles must remain distinct (unmapped roles there fall
# through to ``ApprovalEngine``'s deterministic per-policy/role identity
# instead).
_DEFAULT_PATCH_APPROVAL_POLICIES: list[dict[str, Any]] = [
    {
        "policy_id": "live-patch-change-approval",
        "roles": ["Change approver"],
        "role_ids": {"Change approver": DEFAULT_ROLE_ID},
        "conditions": {},
    }
]
_DEFAULT_CONFIGURATION_APPROVAL_POLICIES: list[dict[str, Any]] = [
    {
        "policy_id": "live-defender-configuration-approval",
        "roles": ["Security Response Owner"],
        "role_ids": {"Security Response Owner": DEFAULT_ROLE_ID},
        "conditions": {},
    }
]


class LiveRemediationPlanner:
    """Read-only remediation proposals derived from live vulnerability exposure."""

    def __init__(
        self,
        vulnerability_service: VulnerabilityIntelligenceService | None,
        *,
        repository: PlanRepository | None = None,
        patch_approval_engine: ApprovalEngine | None = None,
        configuration_approval_engine: ApprovalEngine | None = None,
    ) -> None:
        self.vulnerability_service = vulnerability_service
        self.freshness = getattr(vulnerability_service, "freshness", "") or _now()
        self.repository = repository or PlanRepository()
        # Two separate single-policy engines (rather than one shared
        # multi-policy engine with unconditional conditions on both
        # policies) so a patch plan can never pick up the Defender
        # configuration policy's role or vice versa (Phase 03.5, D-01;
        # avoids cross-family policy bleed since ApprovalEngine has no
        # action-id filter of its own).
        self._patch_approvals = patch_approval_engine or ApprovalEngine(
            _DEFAULT_PATCH_APPROVAL_POLICIES
        )
        self._configuration_approvals = configuration_approval_engine or ApprovalEngine(
            _DEFAULT_CONFIGURATION_APPROVAL_POLICIES
        )

    def identify_opportunities(self) -> dict[str, Any]:
        opportunities = list(
            {
                opportunity["opportunity_id"]: opportunity
                for row in self._patch_targets()
                for opportunity in (self._opportunity(row),)
            }.values()
        )
        opportunities.extend(
            self._configuration_opportunity(row)
            for row in self._configuration_assessments()
        )
        return {
            "opportunities": opportunities,
            "collection_metadata": {
                "opportunities": {
                    "total": len(opportunities),
                    "returned": len(opportunities),
                    "truncated": False,
                }
            },
            "freshness": self.freshness,
            "read_only": True,
            "execution_performed": False,
            "source_status": {"live-vulnerability": "ok"},
        }

    def generate_plans(self) -> dict[str, Any]:
        plans = list(
            {
                plan["plan_id"]: plan
                for row in self._patch_targets()
                for plan in (self._plan(row),)
            }.values()
        )
        plans.extend(
            self._configuration_plan(row)
            for row in self._configuration_assessments()
        )
        self.repository.replace_generation(plans)
        return {
            "plans": plans,
            "collection_metadata": {
                "plans": {
                    "total": len(plans),
                    "returned": len(plans),
                    "truncated": False,
                }
            },
            "summary": {
                "plan_count": len(plans),
                "read_only": True,
                "source": "live-vulnerability",
            },
            "freshness": self.freshness,
            "approval_required": True,
            "execution_performed": False,
            "read_only": True,
            "source_status": {"live-vulnerability": "ok"},
        }

    def _exposures(self) -> list[dict[str, Any]]:
        if self.vulnerability_service is None:
            return []
        return self.vulnerability_service.exposures()

    def _patch_targets(self) -> list[dict[str, Any]]:
        if self.vulnerability_service is None:
            return []
        return self.vulnerability_service.asset_exposures()

    def _configuration_assessments(self) -> list[dict[str, Any]]:
        if self.vulnerability_service is None:
            return []
        from operations.defender_configuration import (
            is_defender_configuration_recommendation,
        )

        posture = getattr(self.vulnerability_service, "defender_posture", None)
        if not callable(posture):
            return []
        return [
            row
            for row in posture()
            if is_defender_configuration_recommendation(row.get("recommendation"))
        ]

    def _configuration_opportunity(self, row: dict[str, Any]) -> dict[str, Any]:
        from operations.defender_configuration import (
            supported_recommendation_action_id,
        )

        target_id = _text(row.get("asset_id"))
        recommendation = _text(row.get("recommendation"))
        action_id = (
            supported_recommendation_action_id(recommendation, target_id)
            or "defender-manual-review"
        )
        if action_id != "defender-manual-review":
            # A concrete governed action is mapped: identity is stable facts
            # only (target + subscription + action family), so a successful
            # run's audit trail survives evidence refresh (D-01). Manual
            # review has no governed action to key on, so it keeps the
            # recommendation-sensitive hash below -- those plans are never
            # executed, so audit continuity does not apply to them.
            opportunity_id = (
                "live-defender-config-"
                f"{_hash({'target': canonical_resource_key(target_id), 'subscription': _identity_subscription(row), 'action': action_id})[:16]}"
            )
        else:
            opportunity_id = (
                f"live-defender-config-{_hash({'target': target_id, 'recommendation': recommendation})[:16]}"
            )
        return {
            "opportunity_id": opportunity_id,
            "opportunity_type": "Defender configuration",
            "action_id": action_id,
            "resource": {
                "id": target_id,
                "resource_key": target_id,
                "name": _first(row.get("asset_name"), target_id),
                "entity_type": _first(
                    row.get("inventory_kind"), row.get("resource_type"), "Resource"
                ),
                "subscription_id": _text(row.get("subscription_id")),
                "subscription_connection": _text(
                    row.get("subscription_connection")
                ),
            },
            "priority": _priority_from_score(
                _severity_score(_text(row.get("severity")))
            ),
            "risk_score": _severity_score(_text(row.get("severity"))),
            "recommended_action": recommendation,
            "defender_mapping": {
                "status": "mapped" if action_id != "defender-manual-review" else "manual_review",
                "action_id": action_id if action_id != "defender-manual-review" else None,
                "recommendations": [recommendation],
                "reason": (
                    "Mapped to an explicit code-authored Defender configuration action."
                    if action_id != "defender-manual-review"
                    else "No explicit supported Defender configuration action matches this recommendation."
                ),
            },
            "read_only": True,
        }

    def _configuration_plan(self, row: dict[str, Any]) -> dict[str, Any]:
        opportunity = self._configuration_opportunity(row)
        resource = opportunity["resource"]
        recommendation = opportunity["recommended_action"]
        assessment_id = _text(row.get("assessment_id"))
        business_service = _text(row.get("business_service"))
        application = _text(row.get("application"))
        mapped = opportunity["action_id"] != "defender-manual-review"
        evidence_citations = (
            [
                {
                    "source_type": "assessment",
                    "source_id": assessment_id,
                    "resource_id": resource["id"],
                    "summary": recommendation,
                    "observed_at": _text(row.get("last_assessed_at")),
                    "freshness": classify_freshness(_text(row.get("last_assessed_at"))),
                }
            ]
            if assessment_id
            else []
        )
        action_version = action_version_for(
            action_id=opportunity["action_id"],
            target_id=resource["id"],
            scope=recommendation,
            evidence_citations=evidence_citations,
        )
        approval_requirements = self._configuration_approvals.requirements(
            {**resource, "business_criticality": resource.get("criticality", "")},
            {"deployment_stages": ["Planning"]},
            {"execution_risk": {"score": int(opportunity["risk_score"])}},
        )
        return {
            "plan_id": opportunity["opportunity_id"],
            "action_version": action_version,
            "action_id": opportunity["action_id"],
            "title": recommendation or "Review Defender configuration",
            "status": "Draft - Approval Required",
            "opportunity_type": "Defender configuration",
            "resource": resource,
            "resource_key": resource["id"],
            "application": application,
            "business_service": business_service,
            "environment": _text(row.get("environment")),
            "owner": _text(row.get("owner")),
            "subscription_id": _text(row.get("subscription_id")),
            "subscription_connection": _text(row.get("subscription_connection")),
            "priority": opportunity["priority"],
            "priority_score": opportunity["risk_score"],
            "recommended_action": recommendation,
            "defender_mapping": opportunity["defender_mapping"],
            "defender_recommendations": [recommendation],
            "simulation_result": {
                "risk_reduction_percent": min(int(opportunity["risk_score"]), 100),
                "compliance_improvement_percent": 50 if mapped else 0,
                "operational_debt_reduction_percent": 25 if mapped else 0,
            },
            "approval_requirements": approval_requirements,
            "rollback_plan": {
                "reversible": False,
                "rollback_actions": [
                    "Manually restore the pre-action Microsoft.Security pricing configuration from the audit snapshot."
                ],
            },
            "risk_assessment": {
                "overall_risk": {
                    "level": opportunity["priority"],
                    "drivers": [f"Defender recommendation severity: {_text(row.get('severity')) or 'unknown'}"],
                }
            },
            "execution_steps": [
                {
                    "step_number": 1,
                    "description": (
                        recommendation
                        if mapped
                        else opportunity["defender_mapping"]["reason"]
                    ),
                    "stage": "Planning",
                    "requires_approval": True,
                    "execution_status": "Not Executed",
                }
            ],
            "business_decision": {
                "disposition": "schedule" if mapped else "escalate",
                "business_impact": {
                    "status": "known" if business_service or application else "unknown"
                },
                "review_requirements": [] if mapped else ["Platform security review"],
                "unknowns": (
                    []
                    if business_service or application
                    else ["Business ownership is unknown for this target."]
                ),
                "urgency_rationale": {
                    "evidence_citations": (
                        [f"assessment:{assessment_id}"] if assessment_id else []
                    )
                },
            },
            "evidence": [recommendation],
            "evidence_citations": evidence_citations,
            "read_only": True,
            "execution_authorized": False,
            "execution_performed": False,
        }

    def _opportunity(self, row: dict[str, Any]) -> dict[str, Any]:
        target_id = _first(row.get("asset_id"), row.get("server_id"))
        missing_kbs = _strings(
            row.get("missing_kbs")
            or ([row.get("missing_kb")] if row.get("missing_kb") else [])
        )
        defender_recommendations = _strings(row.get("defender_recommendations"))
        defender_mapping = self._defender_mapping(
            row,
            missing_kbs=missing_kbs,
            defender_recommendations=defender_recommendations,
        )
        patch_label = (
            ", ".join(missing_kbs)
            or _text(row.get("recommended_patch"))
            or "available updates"
        )
        resource = {
            "id": target_id,
            "resource_key": target_id,
            "name": _first(row.get("name"), row.get("server_name"), target_id),
            "entity_type": _first(
                row.get("inventory_kind"), row.get("resource_type"), "Resource"
            ),
            "business_service": _text(row.get("business_service")),
            "application": _text(row.get("application")),
            "environment": _text(row.get("environment")),
            "subscription_id": _text(row.get("subscription_id")),
            "subscription_connection": _text(row.get("subscription_connection")),
            "resource_type": _text(row.get("resource_type")),
            "region": _text(row.get("region")),
            "criticality": _text(row.get("criticality")),
        }
        return {
            # Stable identity: canonical target + subscription + the governed
            # action family only (D-01). Every row this method sees belongs
            # to the patch-recovery opportunity family regardless of which
            # concrete missing_kbs set is currently observed, so a
            # successful run's audit trail survives evidence refresh instead
            # of being orphaned by a hash-of-evidence identity (CR-01).
            "opportunity_id": (
                "live-patch-"
                f"{_hash({'target': canonical_resource_key(target_id), 'subscription': _identity_subscription(row), 'action': PATCH_RECOVERY_ACTION_FAMILY})[:16]}"
            ),
            "opportunity_type": "Patch and vulnerability debt",
            "resource": resource,
            "priority": _priority_from_score(
                row.get("priority_score", row.get("risk_score", 0))
            ),
            "risk_score": _numeric(row.get("priority_score", row.get("risk_score", 0))),
            "recommended_action": f"Install {patch_label}",
            "defender_mapping": defender_mapping,
            "read_only": True,
        }

    def _plan(self, row: dict[str, Any]) -> dict[str, Any]:
        opportunity = self._opportunity(row)
        defender_mapping = opportunity["defender_mapping"]
        action_id = (
            PATCH_RECOVERY_ACTION_FAMILY
            if defender_mapping["status"] in {"mapped", "not_applicable"}
            else "defender-manual-review"
        )
        target_id = opportunity["resource"].get("id", "")
        missing_kbs = _strings(
            row.get("missing_kbs")
            or ([row.get("missing_kb")] if row.get("missing_kb") else [])
        )
        evidence_observed_at = _text(row.get("evidence_observed_at"))
        evidence_citations = [
            {
                "source_type": "assessment",
                "source_id": str(finding_id),
                "resource_id": opportunity["resource"].get("id", ""),
                "summary": "Open patch finding from live vulnerability exposure",
                # The live provider's freshness is the ARG collection time, not
                # a source-owned evidence timestamp. Including it in the action
                # version invalidates an unchanged plan on every cache refresh.
                "observed_at": evidence_observed_at,
                "freshness": classify_freshness(self.freshness),
            }
            for finding_id in _patch_evidence_source_ids(row.get("finding_ids"))
        ]
        action_version = action_version_for(
            action_id=action_id,
            target_id=canonical_resource_key(target_id),
            scope=sorted(missing_kbs),
            evidence_citations=evidence_citations,
        )
        approval_requirements = self._patch_approvals.requirements(
            {
                **opportunity["resource"],
                "business_criticality": opportunity["resource"].get("criticality", ""),
            },
            {"deployment_stages": ["Planning"]},
            {"execution_risk": {"score": int(opportunity["risk_score"])}},
        )
        return {
            "plan_id": opportunity["opportunity_id"],
            "action_version": action_version,
            "action_id": action_id,
            "title": f"Patch {opportunity['resource']['name']}",
            "status": "Draft - Approval Required",
            "opportunity_type": opportunity["opportunity_type"],
            "resource": opportunity["resource"],
            "application": opportunity["resource"].get("application", ""),
            "business_service": opportunity["resource"].get("business_service", ""),
            "environment": opportunity["resource"].get("environment", ""),
            "owner": _text(row.get("owner")),
            "subscription_id": opportunity["resource"].get("subscription_id", ""),
            "subscription_connection": opportunity["resource"].get(
                "subscription_connection", ""
            ),
            "priority": opportunity["priority"],
            "priority_score": opportunity["risk_score"],
            "recommended_action": opportunity["recommended_action"],
            "defender_mapping": defender_mapping,
            "defender_recommendations": defender_mapping["recommendations"],
            "simulation_result": {
                "risk_reduction_percent": min(int(opportunity["risk_score"]), 100),
                "operational_debt_reduction_percent": 25,
            },
            "approval_requirements": approval_requirements,
            "rollback_plan": {"reversible": True, "steps": ["Uninstall patch if rollback is required"]},
            "risk_assessment": {
                "overall_risk": {
                    "level": opportunity["priority"],
                    "drivers": [
                        f"{row.get('cve_count', 0)} open CVE(s)",
                        f"{row.get('finding_count', 0)} unresolved patch finding(s)",
                    ],
                }
            },
            "execution_steps": [
                {
                    "step_number": 1,
                    "description": (
                        opportunity["recommended_action"]
                        if defender_mapping["status"] != "manual_review"
                        else defender_mapping["reason"]
                    ),
                    "stage": "Planning",
                    "requires_approval": True,
                    "execution_status": "Not Executed",
                }
            ],
            "business_impact": {
                "affected_services": [row.get("business_service")] if row.get("business_service") else [],
                "affected_applications": [row.get("application")] if row.get("application") else [],
                "blast_radius": row.get("finding_count", 0),
                "expected_risk_reduction_percent": row.get("expected_risk_reduction", 0),
            },
            "business_decision": {
                "disposition": "schedule",
                "business_impact": {
                    "status": "known" if row.get("business_service") or row.get("application") else "unknown"
                },
                "review_requirements": [],
                "unknowns": [] if row.get("business_service") or row.get("application") else ["Business ownership is unknown for this target."],
                "urgency_rationale": {
                    "evidence_citations": [
                        f"patch-finding:{finding_id}"
                        for finding_id in row.get("finding_ids", [])[:10]
                    ]
                },
            },
            "evidence": [
                f"{row.get('finding_count', 0)} unresolved patch finding(s)",
                f"Missing updates: {', '.join(_strings(row.get('missing_kbs')))}",
            ],
            "evidence_citations": evidence_citations,
            "read_only": True,
            "execution_authorized": False,
            "execution_performed": False,
        }

    @staticmethod
    def _defender_mapping(
        row: dict[str, Any],
        *,
        missing_kbs: list[str],
        defender_recommendations: list[str],
    ) -> dict[str, Any]:
        """Describe whether Defender evidence can safely map to a patch plan."""
        if not defender_recommendations:
            return {
                "status": "not_applicable",
                "recommendations": [],
                "missing_kbs": missing_kbs,
                "reason": "No Defender recommendation is associated with this exposure.",
            }
        if not missing_kbs:
            return {
                "status": "manual_review",
                "recommendations": defender_recommendations,
                "missing_kbs": [],
                "reason": "Defender recommendation has no concrete missing KB to map.",
            }
        if not bool(row.get("defender_patchable")):
            return {
                "status": "manual_review",
                "recommendations": defender_recommendations,
                "missing_kbs": missing_kbs,
                "reason": "Defender finding is not marked patchable.",
            }
        return {
            "status": "mapped",
            "action_id": PATCH_RECOVERY_ACTION_FAMILY,
            "recommendations": defender_recommendations,
            "missing_kbs": missing_kbs,
            "reason": "Patchable Defender recommendation mapped to the governed patch action.",
        }


def _priority_from_score(value: Any) -> str:
    score = _numeric(value)
    if score >= 90:
        return "Priority 1"
    if score >= 60:
        return "Priority 2"
    if score >= 30:
        return "Priority 3"
    return "Priority 4"


def _numeric(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0


def _strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple, set)):
        values = list(value)
    else:
        values = [value]
    return [text for item in values if (text := _text(item))]
