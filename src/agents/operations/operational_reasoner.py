from __future__ import annotations

from copy import deepcopy
from typing import Any

from .compliance_analyzer import ComplianceAnalyzer
from .health_analyzer import HealthAnalyzer
from .impact_analyzer import ImpactAnalyzer
from .incident_analyzer import IncidentAnalyzer
from .operational_summary import OperationalSummary
from .ownership_analyzer import OwnershipAnalyzer
from .recommendation_engine import RecommendationEngine


class OperationalReasoner:
    """Correlates only governed Semantic Layer outputs; never queries Azure."""

    def __init__(self, semantic_engine) -> None:
        self.semantic = semantic_engine
        self.health = HealthAnalyzer()
        self.compliance = ComplianceAnalyzer()
        self.ownership = OwnershipAnalyzer()
        self.impact = ImpactAnalyzer(semantic_engine)
        self.incident = IncidentAnalyzer(self.impact)
        self.recommendations = RecommendationEngine()
        self.summaries = OperationalSummary()

    def context(
        self, kind: str, subject: str, *, subject_type: str = ""
    ) -> dict[str, Any]:
        if kind == "resource":
            return self.semantic.get_resource_context(
                subject, subject_type=subject_type
            )
        if kind == "application":
            return self.semantic.get_application_context(subject)
        if kind == "service":
            return self.semantic.get_service_context(
                subject, subject_type=subject_type
            )
        if kind == "subscription":
            return self.semantic.get_subscription_context(subject)
        if kind == "environment":
            return self.semantic.get_environment_context(subject)
        raise ValueError(f"Unsupported operational context kind: {kind}")

    def analyze_context(self, context: dict[str, Any], *, command: str) -> dict[str, Any]:
        context = self._correlate_context(context)
        if "risk" not in context or context["risk"] is None:
            risk = {
                "score": None,
                "level": "Unknown",
                "factors": {},
                "evidence_available": False,
            }
        else:
            risk = context["risk"]
        self._validate_risk(risk)
        health = self.health.analyze(context)
        compliance = self.compliance.analyze(context)
        ownership = self.ownership.analyze(context)
        recommendations = self.recommendations.generate(
            risk=risk,
            health=health,
            compliance=compliance,
            ownership=ownership,
            context=context,
        )
        conclusions = self._conclusions(
            context=context,
            risk=risk,
            health=health,
            compliance=compliance,
            ownership=ownership,
        )
        section_metadata = context.get("section_metadata") or {}
        evidence_metadata = {
            "sections": section_metadata,
            "truncated": any(
                bool(item.get("truncated"))
                for item in section_metadata.values()
                if isinstance(item, dict)
            ),
        }
        result = {
            "command": command,
            "subject": context.get("subject", {}),
            "operational_domains": [
                "Application Dependencies",
                "Business Impact",
                "Cost Optimization",
                "Governance",
                "Infrastructure Health",
                "Lifecycle Management",
                "Operational Risk",
                "Ownership Coverage",
                "Patch Compliance",
                "Security Exposure",
            ],
            "risk": risk,
            "health": health,
            "compliance": compliance,
            "ownership": ownership,
            "conclusions": conclusions,
            "recommendations": recommendations,
            "evidence_metadata": evidence_metadata,
            "freshness": context.get("freshness", ""),
            "knowledge_version": context.get("knowledge_version", ""),
            "read_only": True,
        }
        result["summary"] = self.summaries.generate(result)
        return result

    def analyze_patch_failure(
        self, subject: str, *, subject_type: str = ""
    ) -> dict[str, Any]:
        context = self.context("resource", subject, subject_type=subject_type)
        result = self.analyze_context(context, command="Show Patch Compliance")
        result["impact"] = self.impact.analyze(subject, subject_type=subject_type)
        result["read_only"] = True
        return result

    def analyze_ownership(
        self, subject: str, *, subject_type: str = ""
    ) -> dict[str, Any]:
        context = self.context("resource", subject, subject_type=subject_type)
        return {
            "subject": context.get("subject", {}),
            **self.ownership.analyze(context),
            "freshness": context.get("freshness", ""),
            "knowledge_version": context.get("knowledge_version", ""),
            "read_only": True,
        }

    def analyze_dependencies(
        self, subject: str, *, subject_type: str = ""
    ) -> dict[str, Any]:
        return {
            **self.impact.analyze(subject, subject_type=subject_type),
            "read_only": True,
        }

    def analyze_risk(
        self, subject: str, *, subject_type: str = ""
    ) -> dict[str, Any]:
        return {
            **self.semantic.get_risk_context(subject, subject_type=subject_type),
            "read_only": True,
        }

    def _correlate_context(self, context: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(context, dict):
            raise TypeError("Operational context must be a mapping")
        correlated = deepcopy(context)
        sections = correlated.setdefault("sections", {})
        metadata = correlated.setdefault("section_metadata", {})
        if not isinstance(sections, dict) or not isinstance(metadata, dict):
            raise TypeError("Operational sections and metadata must be mappings")
        list_sections = (
            "infrastructure",
            "resources",
            "applications",
            "business_services",
            "services",
            "ownership",
            "support_teams",
            "advisor_findings",
            "cost_context",
            "upstream_dependencies",
            "downstream_dependents",
            "dependencies",
            "security_findings",
        )
        for key in list_sections:
            if key not in sections:
                continue
            rows = sections[key]
            if not isinstance(rows, list) or any(
                not isinstance(item, dict) for item in rows
            ):
                raise TypeError(f"Operational {key} must be a list of mappings")
        context_type = str(correlated.get("context_type") or "")
        resource_rows = self._merge_rows(
            sections.get("infrastructure") or [],
            sections.get("resources") or [],
        )
        resource_contexts: list[dict[str, Any]] = []
        if context_type == "resource":
            resource_contexts.append(correlated)
        else:
            for row in resource_rows[:50]:
                resource_contexts.append(
                    self.semantic.get_resource_context(
                        str(row.get("name") or ""),
                        subject_type=str(row.get("entity_type") or ""),
                    )
                )
        application_rows = self._merge_rows(
            sections.get("applications") or [],
            *[
                (item.get("sections") or {}).get("applications") or []
                for item in resource_contexts
            ],
        )
        application_contexts: list[dict[str, Any]] = []
        if context_type == "application":
            application_contexts.append(correlated)
        for row in application_rows[:50]:
            if (
                context_type == "application"
                and row.get("name") == (correlated.get("subject") or {}).get("name")
            ):
                continue
            application_contexts.append(
                self.semantic.get_application_context(str(row.get("name") or ""))
            )

        related_contexts = [*resource_contexts, *application_contexts]
        merged_applications = self._merge_rows(
            sections.get("applications") or [], application_rows
        )
        sections["applications"] = merged_applications[:50]
        self._set_metadata(
            metadata,
            "applications",
            len(merged_applications),
            len(sections["applications"]),
            sources=[
                (item.get("section_metadata") or {}).get("applications") or {}
                for item in resource_contexts
            ],
        )
        for key in (
            "business_services",
            "services",
            "ownership",
            "support_teams",
            "advisor_findings",
            "cost_context",
        ):
            merged = self._merge_rows(
                sections.get(key) or [],
                *[
                    (item.get("sections") or {}).get(key) or []
                    for item in related_contexts
                ],
            )
            if merged:
                sections[key] = merged[:50]
                self._set_metadata(
                    metadata,
                    key,
                    len(merged),
                    len(sections[key]),
                    sources=[
                        (item.get("section_metadata") or {}).get(key) or {}
                        for item in related_contexts
                    ],
                )
        for key in ("upstream_dependencies", "downstream_dependents", "dependencies"):
            merged = self._merge_rows(
                sections.get(key) or [],
                *[
                    (item.get("sections") or {}).get(key) or []
                    for item in application_contexts
                ],
            )
            if merged or application_contexts:
                sections[key] = merged[:50]
                self._set_metadata(
                    metadata,
                    key,
                    len(merged),
                    len(sections[key]),
                    sources=[
                        (item.get("section_metadata") or {}).get(key) or {}
                        for item in application_contexts
                    ],
                )

        compliance_rows = [
            {
                "resource": item.get("subject", {}),
                **((item.get("sections") or {}).get("compliance") or {}),
            }
            for item in resource_contexts
            if isinstance((item.get("sections") or {}).get("compliance"), dict)
        ]
        if compliance_rows and "compliance" not in sections:
            sections["compliance"] = compliance_rows[:50]
            self._set_metadata(
                metadata,
                "compliance",
                len(compliance_rows),
                len(sections["compliance"]),
            )
        lifecycle_rows = [
            (item.get("sections") or {}).get("lifecycle") or {}
            for item in resource_contexts
            if (item.get("sections") or {}).get("lifecycle")
        ]
        if lifecycle_rows and "lifecycle" not in sections:
            statuses = sorted(
                {
                    str(item.get("status") or "unknown")
                    for item in lifecycle_rows
                }
            )
            sections["lifecycle"] = {
                "statuses": statuses,
                "resource_count": len(lifecycle_rows),
            }
        security_rows = [
            {
                "resource": item.get("subject", {}),
                "findings": (item.get("sections") or {}).get("security_findings") or [],
            }
            for item in resource_contexts
            if (item.get("sections") or {}).get("security_findings")
        ]
        if security_rows and "security_findings" not in sections:
            sections["security_findings"] = security_rows[:50]
            self._set_metadata(
                metadata,
                "security_findings",
                len(security_rows),
                len(sections["security_findings"]),
            )
        health_rows = [
            {
                "resource": item.get("subject", {}),
                **((item.get("sections") or {}).get("resource_health") or {}),
            }
            for item in resource_contexts
            if isinstance((item.get("sections") or {}).get("resource_health"), dict)
        ]
        if health_rows and "resource_health" not in sections:
            sections["resource_health"] = health_rows[:50]
            self._set_metadata(
                metadata,
                "resource_health",
                len(health_rows),
                len(sections["resource_health"]),
            )

        for key, value in sections.items():
            if isinstance(value, list) and key not in metadata:
                metadata[key] = {
                    "count": len(value),
                    "returned": len(value),
                    "truncated": False,
                }
        return correlated

    @staticmethod
    def _validate_risk(risk: Any) -> None:
        if not isinstance(risk, dict):
            raise TypeError("Operational risk must be a mapping")
        score = risk.get("score")
        if score is not None and (
            isinstance(score, bool)
            or not isinstance(score, int)
            or not 0 <= score <= 100
        ):
            raise ValueError("Operational risk score must be an integer from 0 to 100")
        level = risk.get("level", "Unknown")
        if not isinstance(level, str) or level not in {
            "Unknown",
            "Low",
            "Moderate",
            "Medium",
            "High",
            "Critical",
        }:
            raise ValueError("Operational risk level is invalid")
        factors = risk.get("factors")
        if factors is None:
            factors = {}
        if not isinstance(factors, dict) or any(
            not isinstance(key, str)
            or isinstance(value, bool)
            or not isinstance(value, int)
            or value < 0
            for key, value in factors.items()
        ):
            raise TypeError("Operational risk factors must be non-negative integer mappings")
        if "evidence_available" in risk and not isinstance(
            risk["evidence_available"], bool
        ):
            raise TypeError("Operational risk evidence_available must be boolean")

    @staticmethod
    def _set_metadata(
        metadata: dict[str, Any],
        key: str,
        count: int,
        returned: int,
        *,
        sources: list[dict[str, Any]] | None = None,
    ) -> None:
        existing = metadata.get(key) or {}
        source_rows = sources or []
        source_count = max(
            (int(item.get("count") or 0) for item in source_rows), default=0
        )
        source_truncated = any(bool(item.get("truncated")) for item in source_rows)
        total = max(int(existing.get("count") or 0), count, source_count)
        metadata[key] = {
            "count": total,
            "returned": returned,
            "truncated": (
                bool(existing.get("truncated"))
                or source_truncated
                or returned < total
            ),
        }

    @staticmethod
    def _merge_rows(*collections: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows: dict[tuple[str, str], dict[str, Any]] = {}
        for collection in collections:
            for row in collection:
                if not isinstance(row, dict):
                    continue
                key = (
                    str(row.get("entity_type") or ""),
                    str(row.get("name") or ""),
                )
                if key != ("", ""):
                    rows[key] = row
        return [rows[key] for key in sorted(rows)]

    @classmethod
    def _conclusions(
        cls,
        *,
        context: dict[str, Any],
        risk: dict[str, Any],
        health: dict[str, Any],
        compliance: dict[str, Any],
        ownership: dict[str, Any],
    ) -> list[dict[str, Any]]:
        sections = context.get("sections") or {}
        metadata = context.get("section_metadata") or {}
        security = sections.get("security_findings")
        security_evidence = (
            security
            if security
            else {
                "finding_count": 0,
                "status": (
                    "No governed security findings are present in this snapshot; this is not proof of safety."
                    if "security_findings" in sections
                    else "Security exposure is not established by the available context."
                ),
            }
        )
        dependencies_present = any(
            key in sections
            for key in (
                "upstream_dependencies",
                "downstream_dependents",
                "dependencies",
            )
        )
        dependencies = (
            {
                "upstream": sections.get("upstream_dependencies", []),
                "downstream": sections.get("downstream_dependents", []),
                "dependencies": sections.get("dependencies", []),
            }
            if dependencies_present
            else cls._unknown("Dependency evidence is not available for this context.")
        )
        business_present = any(
            key in sections for key in ("business_services", "services", "applications")
        )
        business_impact = (
            {
                "business_services": sections.get("business_services", []),
                "services": sections.get("services", []),
                "applications": sections.get("applications", []),
            }
            if business_present
            else cls._unknown("Business-impact evidence is not available for this context.")
        )
        cost = sections.get("cost") or sections.get("cost_context")
        cost_evidence = cost or cls._unknown(
            "Cost and cost-allocation evidence are not available for this context."
        )
        lifecycle_advisors = [
            item
            for item in sections.get("advisor_findings") or []
            if isinstance(item, dict)
            and any(
                marker in str(item.get("name") or "").casefold()
                for marker in (
                    "obsolete",
                    "deprecated",
                    "retire",
                    "end of life",
                    "eol",
                    "modernize",
                )
            )
        ]
        lifecycle = sections.get("lifecycle")
        lifecycle_evidence = (
            {"lifecycle": lifecycle, "advisor_findings": lifecycle_advisors}
            if lifecycle or lifecycle_advisors
            else cls._unknown("Lifecycle evidence is not available for this context.")
        )
        truncated = any(
            bool(item.get("truncated"))
            for item in metadata.values()
            if isinstance(item, dict)
        )
        governance = {
            "ownership_coverage": ownership.get("coverage", "Unknown"),
            "evidence_truncated": truncated,
            "freshness": context.get("freshness", ""),
        }
        return [
            cls._conclusion(
                "Infrastructure Health",
                health,
                str(health.get("reasoning") or "Health is derived from governed operational evidence."),
                list((health.get("deductions") or {}).keys()),
                health.get("data_sources") or ["Semantic Knowledge Layer"],
            ),
            cls._conclusion(
                "Patch Compliance",
                compliance.get("evidence") or compliance,
                "Patch compliance reflects governed patch-assessment evidence; unknown is not treated as compliant.",
                ["patch_noncompliance"] if not compliance.get("compliant") and compliance.get("status") != "unknown" else [],
                compliance.get("data_sources") or ["Semantic Knowledge Layer"],
            ),
            cls._conclusion(
                "Security Exposure",
                security_evidence,
                "Security exposure is reported only from governed findings present in the semantic context.",
                ["security_findings"] if security else [],
                ["Semantic Knowledge Layer", "OneLake security facts"],
            ),
            cls._conclusion(
                "Ownership Coverage",
                ownership.get("evidence") or ownership,
                "Ownership and escalation coverage follow discovered Fabric Ontology relationships.",
                ["missing_owner"] if ownership.get("coverage") == "Missing" else [],
                ownership.get("data_sources") or ["Semantic Knowledge Layer"],
            ),
            cls._conclusion(
                "Application Dependencies",
                dependencies,
                "Dependencies preserve the direction of governed application relationships; empty evidence is not proof of independence.",
                [],
                ["Semantic Knowledge Layer", "Fabric Ontology relationships"],
            ),
            cls._conclusion(
                "Business Impact",
                business_impact,
                "Business impact is limited to discovered application, service, and business-service relationships.",
                [],
                ["Semantic Knowledge Layer", "Fabric Ontology relationships"],
            ),
            cls._conclusion(
                "Operational Risk",
                risk.get("factors") or cls._unknown("Risk factors are not available."),
                "Operational risk uses the explainable Semantic Layer score and factor map.",
                list((risk.get("factors") or {}).keys()),
                ["Semantic Knowledge Layer"],
            ),
            cls._conclusion(
                "Cost Optimization",
                cost_evidence,
                "Cost conclusions identify governed cost or allocation context only; no savings amount is inferred.",
                [],
                ["Semantic Knowledge Layer", "OneLake governed cost facts"],
            ),
            cls._conclusion(
                "Lifecycle Management",
                lifecycle_evidence,
                "Lifecycle conclusions use explicit lifecycle state or Advisor modernization/end-of-life evidence.",
                ["advisor_findings"] if lifecycle_advisors else [],
                ["Semantic Knowledge Layer", "Fabric Ontology"],
            ),
            cls._conclusion(
                "Governance",
                governance,
                "Governance combines ownership coverage, knowledge completeness, and freshness without inferring missing facts.",
                ["missing_owner"] if ownership.get("coverage") == "Missing" else [],
                ["Semantic Knowledge Layer"],
            ),
        ]

    @staticmethod
    def _unknown(reason: str) -> dict[str, str]:
        return {"status": "unknown", "reason": reason}

    @staticmethod
    def _conclusion(
        domain: str,
        evidence: Any,
        reasoning: str,
        risk_factors: list[str],
        data_sources: list[str],
    ) -> dict[str, Any]:
        return {
            "domain": domain,
            "evidence": [evidence],
            "data_sources": data_sources,
            "reasoning": reasoning,
            "risk_factors": risk_factors,
        }
