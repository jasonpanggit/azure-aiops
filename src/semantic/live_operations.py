from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

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


class LiveRemediationPlanner:
    """Read-only remediation proposals derived from live vulnerability exposure."""

    def __init__(
        self,
        vulnerability_service: VulnerabilityIntelligenceService | None,
        *,
        repository: PlanRepository | None = None,
    ) -> None:
        self.vulnerability_service = vulnerability_service
        self.freshness = getattr(vulnerability_service, "freshness", "") or _now()
        self.repository = repository or PlanRepository()

    def identify_opportunities(self) -> dict[str, Any]:
        opportunities = list(
            {
                opportunity["opportunity_id"]: opportunity
                for row in self._patch_targets()
                for opportunity in (self._opportunity(row),)
            }.values()
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

    def _opportunity(self, row: dict[str, Any]) -> dict[str, Any]:
        target_id = _first(row.get("asset_id"), row.get("server_id"))
        missing_kbs = _strings(
            row.get("missing_kbs")
            or ([row.get("missing_kb")] if row.get("missing_kb") else [])
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
            "opportunity_id": f"live-patch-{_hash({'target': target_id, 'patches': sorted(missing_kbs)})[:16]}",
            "opportunity_type": "Patch and vulnerability debt",
            "resource": resource,
            "priority": _priority_from_score(
                row.get("priority_score", row.get("risk_score", 0))
            ),
            "risk_score": _numeric(row.get("priority_score", row.get("risk_score", 0))),
            "recommended_action": f"Install {patch_label}",
            "read_only": True,
        }

    def _plan(self, row: dict[str, Any]) -> dict[str, Any]:
        opportunity = self._opportunity(row)
        action_version = _hash(
            {
                "action": opportunity["recommended_action"],
                "rollback": ["Uninstall patch if rollback is required"],
            }
        )[:16]
        return {
            "plan_id": opportunity["opportunity_id"],
            "action_version": action_version,
            "action_id": "controlled-patch-recovery",
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
            "simulation_result": {
                "risk_reduction_percent": min(int(opportunity["risk_score"]), 100),
                "operational_debt_reduction_percent": 25,
            },
            "approval_requirements": [
                {
                    "role": "Change approver",
                    "reason": "Change approval required before execution",
                }
            ],
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
                    "description": opportunity["recommended_action"],
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
            "evidence_citations": [
                {
                    "source_type": "assessment",
                    "source_id": str(finding_id),
                    "resource_id": opportunity["resource"].get("id", ""),
                    "summary": "Open patch finding from live vulnerability exposure",
                    "observed_at": self.freshness,
                    "freshness": "current",
                }
                for finding_id in row.get("finding_ids", [])[:10]
            ],
            "read_only": True,
            "execution_authorized": False,
            "execution_performed": False,
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
