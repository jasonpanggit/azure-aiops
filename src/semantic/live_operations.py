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
        opportunities = [self._opportunity(row) for row in self._exposures()]
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
        plans = [self._plan(row) for row in self._exposures()]
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

    def _opportunity(self, row: dict[str, Any]) -> dict[str, Any]:
        resource = {
            "resource_key": row.get("server_id", ""),
            "name": row.get("server_name") or row.get("server_id", ""),
            "business_service": row.get("business_service", ""),
            "application": row.get("application", ""),
            "environment": row.get("environment", ""),
            "subscription_id": row.get("subscription_id", ""),
        }
        return {
            "opportunity_id": f"live-patch-{row.get('server_id', '')}-{row.get('missing_kb', '')}",
            "opportunity_type": "Patch and vulnerability debt",
            "resource": resource,
            "priority": row.get("priority", "Priority 2"),
            "risk_score": row.get("risk_score", 0),
            "recommended_action": f"Install {row.get('recommended_patch') or row.get('missing_kb')}",
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
            "opportunity_type": opportunity["opportunity_type"],
            "resource": opportunity["resource"],
            "application": opportunity["resource"].get("application", ""),
            "business_service": opportunity["resource"].get("business_service", ""),
            "priority": opportunity["priority"],
            "priority_score": row.get("risk_score", 0),
            "recommended_action": opportunity["recommended_action"],
            "simulation_result": {
                "risk_reduction_percent": min(int(row.get("risk_score") or 0), 100),
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
                    "level": str(row.get("priority", "Priority 2")),
                    "drivers": [],
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
            "read_only": True,
            "execution_authorized": False,
            "execution_performed": False,
        }
