from __future__ import annotations

from datetime import datetime
from typing import Any

from .patch_compliance_engine import PatchComplianceEngine
from .patch_context_builder import PatchContextBuilder
from .patch_correlator import PatchCorrelator
from .patch_priority_engine import PatchPriorityEngine
from .patch_risk_engine import PatchRiskEngine


class PatchAnalyzer:
    """Runs one explainable analysis pass across the semantic patch snapshot."""

    def __init__(
        self,
        context_builder: PatchContextBuilder,
        *,
        compliance: PatchComplianceEngine | None = None,
        risk: PatchRiskEngine | None = None,
        priority: PatchPriorityEngine | None = None,
        correlator: PatchCorrelator | None = None,
    ) -> None:
        self.context_builder = context_builder
        self.compliance = compliance or PatchComplianceEngine()
        self.risk = risk or PatchRiskEngine()
        self.priority = priority or PatchPriorityEngine()
        self.correlator = correlator or PatchCorrelator()

    def analyze(
        self,
        *,
        assessments: list[dict[str, Any]],
        installations: list[dict[str, Any]],
        security_findings: list[dict[str, Any]],
        advisor_recommendations: list[dict[str, Any]],
        policies: list[dict[str, Any]],
        now: datetime,
    ) -> list[dict[str, Any]]:
        assessment_rows = self._index(assessments)
        latest = self._latest_assessments(assessment_rows)
        installations_by_resource = self._index(installations)
        security_by_resource = self._index(security_findings)
        advisors_by_resource = self._index(advisor_recommendations)
        findings = []
        for context in self.context_builder.all():
            resource_key = str(context["_resource_key"])
            resource_installations = installations_by_resource.get(resource_key, [])
            resource_security = security_by_resource.get(resource_key, [])
            resource_advisor = advisors_by_resource.get(resource_key, [])
            policy = next(
                (
                    item
                    for item in policies
                    if str(item.get("environment") or "").casefold()
                    == str(context.get("environment") or "").casefold()
                ),
                None,
            )
            compliance = self.compliance.resource_compliance(
                latest.get(resource_key),
                resource_installations,
                now=now,
                policy=policy,
            )
            risk = self.risk.calculate(
                context=context,
                compliance=compliance,
                security_findings=resource_security,
                advisor_recommendations=resource_advisor,
            )
            priority = self.priority.prioritize(
                context=context, compliance=compliance, risk=risk
            )
            findings.append(
                self.correlator.enrich(
                    context=context,
                    compliance=compliance,
                    risk=risk,
                    priority=priority,
                    security_findings=resource_security,
                    advisor_recommendations=resource_advisor,
                )
            )
        priority_rank = {"Priority 1": 1, "Priority 2": 2, "Priority 3": 3, "Priority 4": 4}
        return sorted(
            findings,
            key=lambda item: (
                priority_rank[str(item["priority"])],
                -int(item["risk_score"]),
                str((item.get("resource") or {}).get("name") or ""),
            ),
        )

    def _index(
        self, rows: list[dict[str, Any]]
    ) -> dict[str, list[dict[str, Any]]]:
        indexed: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            try:
                key = self.context_builder.key_for(row)
            except LookupError:
                # Evidence referencing a resource no longer present in the
                # current semantic snapshot (e.g. decommissioned resource, or
                # a sync timing gap between Defender data and inventory).
                # Excluding stale evidence is correct; it must not fail the
                # whole analysis pass.
                continue
            indexed.setdefault(key, []).append(dict(row))
        return indexed

    @staticmethod
    def _latest_assessments(
        rows: dict[str, list[dict[str, Any]]]
    ) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for resource_key, resource_rows in rows.items():
            result[resource_key] = max(
                resource_rows, key=lambda row: str(row.get("assessed_at") or "")
            )
        return result
