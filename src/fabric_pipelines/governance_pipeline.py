"""Governance domain pipeline for Fabric.

Ports Hermes governance domain logic (IdentityRiskEngine, SpnGovernanceEngine, 
FinOpsEngine) to Fabric PySpark notebooks. Consumes Fabric-backed inventory and
Azure Advisor/Cost Management data; generates assessment_governance_findings output
matching Hermes engine byte-for-byte on test scenario.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Optional

# Import Hermes governance contracts to reuse existing logic
from intelligence.governance.identity import (
    CREDENTIAL_EXPIRY_WARNING_DAYS,
    STALE_ACCESS_DAYS,
    IdentityRiskEngine,
    PrincipalRisk,
    ServicePrincipalGovernance,
    SpnGovernanceEngine,
)
from intelligence.governance.finops import FinOpsEngine, SavingsOpportunity, WasteItem


@dataclass(frozen=True)
class GovernanceFinding:
    """A single governance assessment finding (identity risk, SPN, or FinOps)."""

    finding_type: str  # "identity_risk" | "spn_governance" | "savings_opportunity" | "waste_item"
    resource_id: str
    severity: str  # "critical" | "high" | "medium" | "low" | "info"
    title: str
    description: str
    finding_data: dict[str, Any] = field(default_factory=dict)
    detected_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    source: str = "governance_pipeline"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class GovernancePipeline:
    """Orchestrates governance assessment: identity risk, SPN governance, FinOps."""

    def __init__(
        self,
        *,
        role_assignments: list[Mapping[str, Any]] | None = None,
        role_definitions: list[Mapping[str, Any]] | None = None,
        connections: list[Mapping[str, Any]] | None = None,
        managed_identities: list[Mapping[str, Any]] | None = None,
        advisor_recommendations: list[Mapping[str, Any]] | None = None,
        cost_actuals: list[Mapping[str, Any]] | None = None,
        resources: list[Mapping[str, Any]] | None = None,
        now: datetime | None = None,
    ) -> None:
        """Initialize pipeline with optional data sources."""
        self._role_assignments = role_assignments or []
        self._role_definitions = role_definitions or []
        self._connections = connections or []
        self._managed_identities = managed_identities or []
        self._advisor = advisor_recommendations or []
        self._cost_actuals = cost_actuals or []
        self._resources = resources or []
        self._now = now or datetime.now(UTC)

    def assess_identity_risk(self) -> list[GovernanceFinding]:
        """Generate identity risk findings from role assignments."""
        findings: list[GovernanceFinding] = []
        engine = IdentityRiskEngine(
            role_assignments=self._role_assignments,
            role_definitions=self._role_definitions,
            managed_identities=self._managed_identities,
            now=self._now,
        )

        # Privileged principals are high-severity
        for principal in engine.principals():
            if principal.privileged:
                severity = "high" if not principal.stale else "medium"
                findings.append(
                    GovernanceFinding(
                        finding_type="identity_risk",
                        resource_id=principal.principal_id,
                        severity=severity,
                        title=f"Privileged access: {principal.principal_type}",
                        description=(
                            f"Principal holds {principal.assignment_count} assignments, "
                            f"widest scope: {principal.widest_scope_breadth}"
                        ),
                        finding_data={
                            "principal_id": principal.principal_id,
                            "principal_type": principal.principal_type,
                            "assignment_count": principal.assignment_count,
                            "widest_scope": principal.widest_scope,
                            "widest_scope_breadth": principal.widest_scope_breadth,
                            "roles": principal.roles,
                            "stale": principal.stale,
                            "last_changed": principal.last_changed,
                            "blast_radius": principal.blast_radius,
                        },
                    )
                )

        # Stale access reviews needed
        for stale_item in engine.stale_access():
            findings.append(
                GovernanceFinding(
                    finding_type="identity_risk",
                    resource_id=stale_item["assignment_id"],
                    severity="medium",
                    title=f"Stale access review needed ({STALE_ACCESS_DAYS}+ days)",
                    description=(
                        f"Principal {stale_item['principal_id']} holds {stale_item['role']} "
                        f"at {stale_item['scope']} unchanged since {stale_item['last_changed']}"
                    ),
                    finding_data=stale_item,
                )
            )

        # Non-human principals summary
        non_human = engine.non_human_identities()
        if non_human:
            findings.append(
                GovernanceFinding(
                    finding_type="identity_risk",
                    resource_id="",
                    severity="info",
                    title=f"Non-human principals: {len(non_human)} service principals/managed identities",
                    description="Review automated identity assignments for least-privilege compliance",
                    finding_data={"non_human_count": len(non_human)},
                )
            )

        return findings

    def assess_spn_governance(self) -> list[GovernanceFinding]:
        """Generate service principal credential governance findings."""
        findings: list[GovernanceFinding] = []
        engine = SpnGovernanceEngine(
            connections=self._connections,
            role_assignments=self._role_assignments,
            now=self._now,
        )

        for spn in engine.credentials():
            # Expired credentials are critical
            if spn.rotation_status == "expired":
                severity = "critical"
            elif spn.rotation_status == "expiring_soon":
                severity = "high"
            elif spn.rotation_status == "unknown":
                severity = "medium"
            else:
                severity = "info"

            if severity != "info" or spn.issues:  # Only report issues or non-healthy
                findings.append(
                    GovernanceFinding(
                        finding_type="spn_governance",
                        resource_id=spn.connection_id,
                        severity=severity,
                        title=f"SPN credential: {spn.rotation_status}",
                        description=(
                            f"Connection {spn.connection_name}: "
                            f"{'; '.join(spn.issues) if spn.issues else spn.rotation_status}"
                        ),
                        finding_data=asdict(spn),
                    )
                )

        return findings

    def assess_finops(self) -> list[GovernanceFinding]:
        """Generate FinOps findings (savings opportunities, waste)."""
        findings: list[GovernanceFinding] = []
        engine = FinOpsEngine(
            advisor_recommendations=self._advisor,
            cost_actuals=self._cost_actuals,
            resources=self._resources,
        )

        # Savings opportunities (ranked by savings amount)
        for opportunity in engine.savings_opportunities():
            if opportunity.annual_savings and opportunity.annual_savings > 0:
                severity = "high" if opportunity.annual_savings >= 10000 else "medium"
            else:
                severity = "info"

            findings.append(
                GovernanceFinding(
                    finding_type="savings_opportunity",
                    resource_id=opportunity.resource_id,
                    severity=severity,
                    title=f"Savings opportunity: {opportunity.impact}",
                    description=(
                        f"{opportunity.solution} — "
                        f"Potential annual savings: ${opportunity.annual_savings or 'unquantified'} "
                        f"{opportunity.currency or ''}"
                    ),
                    finding_data=asdict(opportunity),
                )
            )

        # Waste items (idle/unused resources)
        for waste in engine.waste():
            findings.append(
                GovernanceFinding(
                    finding_type="waste_item",
                    resource_id=waste.resource_id,
                    severity="medium",
                    title=f"Waste detected: {waste.reason}",
                    description=f"Resource {waste.resource_id} ({waste.resource_type}) is {waste.reason}",
                    finding_data=asdict(waste),
                )
            )

        # Summary metrics
        summary = engine.summary()
        if summary.get("identified_annual_savings", 0) > 0:
            findings.append(
                GovernanceFinding(
                    finding_type="finops_summary",
                    resource_id="",
                    severity="info",
                    title=f"FinOps summary: ${summary.get('identified_annual_savings', 0)} identified savings",
                    description="Cost optimization opportunities identified by Azure Advisor",
                    finding_data=summary,
                )
            )

        return findings

    def execute(self) -> list[GovernanceFinding]:
        """Execute full governance assessment pipeline."""
        findings: list[GovernanceFinding] = []
        findings.extend(self.assess_identity_risk())
        findings.extend(self.assess_spn_governance())
        findings.extend(self.assess_finops())
        return findings


__all__ = [
    "GovernanceFinding",
    "GovernancePipeline",
]
