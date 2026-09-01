from __future__ import annotations

from typing import Any

from intelligence.predictive.predictive_context_builder import PredictiveContextBuilder


class RemediationOpportunityEngine:
    """Matches governed evidence to declarative remediation catalog entries."""

    def __init__(self, action_catalog: list[dict[str, Any]], *, max_actions: int = 100) -> None:
        if len(action_catalog) > max_actions:
            raise ValueError("Remediation action catalog exceeds configured bound")
        identities: set[str] = set()
        self.catalog = []
        for source in action_catalog:
            action = dict(source)
            action_id = str(action.get("action_id") or "").strip()
            if not action_id or action_id in identities:
                raise ValueError("Remediation catalog requires unique action_id")
            self._validate_action(action)
            identities.add(action_id)
            self.catalog.append(action)

    def identify(self, resources: list[dict[str, Any]]) -> list[dict[str, Any]]:
        opportunities = []
        seen: set[tuple[str, str]] = set()
        for source in resources:
            resource = dict(source)
            resource_key = PredictiveContextBuilder.canonical_key(
                resource.get("resource_key")
            )
            if not resource_key:
                raise ValueError("Remediation resources require canonical resource_key")
            for action in self.catalog:
                matched = self._matches(action["trigger"], resource)
                if not matched:
                    continue
                identity = (resource_key, str(action["action_id"]))
                if identity in seen:
                    raise ValueError("Duplicate remediation opportunity identity")
                seen.add(identity)
                citations = self._evidence_citations(resource, matched)
                opportunities.append(
                    {
                        "_resource_key": resource_key,
                        "_resource": resource,
                        "_action": action,
                        "resource": {
                            "name": str(resource.get("name") or "Unknown")[:512],
                            "entity_type": str(
                                resource.get("entity_type") or "Resource"
                            )[:128],
                        },
                        "application": str(resource.get("application") or "Unknown")[:512],
                        "business_service": str(
                            resource.get("business_service") or "Unknown"
                        )[:512],
                        "environment": str(resource.get("environment") or "")[:128],
                        "owner": str(resource.get("owner") or "")[:512],
                        "subscription_id": str(
                            resource.get("subscription_id") or ""
                        )[:128],
                        "subscription_connection": str(
                            resource.get("subscription_connection") or ""
                        )[:128],
                        "opportunity_type": str(action.get("opportunity_type") or "Operational debt")[:256],
                        "action_id": str(action["action_id"]),
                        "evidence": matched,
                        "evidence_citations": citations,
                        "patch_risk_score": self._score(resource, "patch_risk_score"),
                        "lifecycle_risk_score": self._score(
                            resource, "lifecycle_risk_score"
                        ),
                        "predictive_risk_score": self._score(
                            resource, "predictive_risk_score"
                        ),
                        "operational_debt_score": self._score(
                            resource, "operational_debt_score"
                        ),
                        "read_only": True,
                    }
                )
        return sorted(
            opportunities,
            key=lambda row: (
                -max(
                    row["predictive_risk_score"],
                    row["patch_risk_score"],
                    row["lifecycle_risk_score"],
                ),
                row["resource"]["name"],
                row["action_id"],
            ),
        )

    @staticmethod
    def _validate_action(action: dict[str, Any]) -> None:
        clauses = (action.get("trigger") or {}).get("any")
        if not isinstance(clauses, list) or not clauses:
            raise ValueError("Remediation trigger requires a non-empty any list")
        for clause in clauses:
            if not isinstance(clause, dict) or not str(clause.get("field") or ""):
                raise ValueError("Remediation trigger requires field")
            operators = {name for name in ("equals", "gte") if name in clause}
            if len(operators) != 1:
                raise ValueError("Remediation trigger requires one operator")
            if "gte" in clause and (
                isinstance(clause["gte"], bool)
                or not isinstance(clause["gte"], int)
                or clause["gte"] < 0
            ):
                raise ValueError(
                    "Remediation trigger threshold must be a nonnegative integer"
                )
            if "equals" in clause and isinstance(
                clause["equals"], (dict, list, tuple, set)
            ):
                raise ValueError("Remediation trigger equality requires a scalar")
        for field in (
            "execution_steps",
            "preconditions",
            "rollback_actions",
            "success_criteria",
            "failure_criteria",
            "deployment_stages",
        ):
            values = action.get(field)
            if (
                not isinstance(values, list)
                or not values
                or len(values) > 50
                or any(not str(value).strip() for value in values)
            ):
                raise ValueError(f"Remediation action requires valid {field}")
        if not isinstance(action.get("effectiveness"), dict):
            raise TypeError("Remediation action requires effectiveness")

    def _matches(self, trigger: dict[str, Any], resource: dict[str, Any]) -> list[str]:
        clauses = trigger.get("any")
        if not isinstance(clauses, list) or not clauses:
            raise ValueError("Remediation trigger requires a non-empty any list")
        evidence = []
        for clause in clauses:
            field = str(clause.get("field") or "")
            if not field or field not in resource:
                continue
            actual = resource[field]
            matched = (
                actual == clause["equals"]
                if "equals" in clause
                else self._numeric(actual) >= self._numeric(clause.get("gte"))
                if "gte" in clause
                else False
            )
            if matched:
                evidence.append(f"{field.replace('_', ' ')}: {actual}"[:1024])
        return evidence

    @staticmethod
    def _evidence_citations(resource: dict[str, Any], matched: list[str]) -> list[dict[str, Any]]:
        if not matched:
            return []
        recommendation = str(resource.get("defender_recommendation") or "").casefold()
        citations = []
        for citation in resource.get("evidence_citations") or ():
            if not isinstance(citation, dict):
                continue
            summary = str(citation.get("summary") or "").casefold()
            if recommendation and recommendation not in summary:
                continue
            citations.append(dict(citation))
        return citations

    @staticmethod
    def _numeric(value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return 0
        return int(value)

    @classmethod
    def _score(cls, row: dict[str, Any], field: str) -> int:
        return min(max(cls._numeric(row.get(field)), 0), 100)
