from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from opentelemetry import metrics

from intelligence.incident.incident_intelligence import IncidentIntelligence

from .context_router import (
    CHANGE_INTELLIGENCE_COMMANDS,
    INCIDENT_INTELLIGENCE_COMMANDS,
    LIFECYCLE_INTELLIGENCE_COMMANDS,
    PATCH_INTELLIGENCE_COMMANDS,
    PREDICTIVE_INTELLIGENCE_COMMANDS,
    REMEDIATION_PLANNING_COMMANDS,
    ContextRouter,
)
from .operational_reasoner import OperationalReasoner

_BANNED_OPERATION_FIELDS = {
    "payload_json",
    "lineage_json",
    "semantic_metadata_json",
    "tenant_id",
    "subscription_id",
    "resource_id",
    "ingestion_run_id",
    "source_run_id",
    "action_result",
    "remediation_result",
}

_CONCLUSION_FIELDS = {
    "domain",
    "evidence",
    "data_sources",
    "reasoning",
    "risk_factors",
}

_RECOMMENDATION_FIELDS = {
    "priority",
    "impact",
    "confidence",
    "rationale",
    "suggested_action",
    "evidence",
    "advisory_only",
}


class OperationsTelemetry:
    def __init__(self, meter=None) -> None:
        meter = meter or metrics.get_meter("hermes.operations_agent", "0.1.0")
        self.analysis_duration = meter.create_histogram(
            "operations.analysis.duration", unit="s"
        )
        self.recommendation_latency = meter.create_histogram(
            "operations.recommendation.latency", unit="s"
        )
        self.knowledge_retrieval_latency = meter.create_histogram(
            "operations.knowledge.retrieval.latency", unit="s"
        )
        self.summary_generation_latency = meter.create_histogram(
            "operations.summary.generation.latency", unit="s"
        )
        self.impact_duration = meter.create_histogram(
            "operations.impact.analysis.duration", unit="s"
        )
        self.context_generation_latency = meter.create_histogram(
            "operations.context.generation.latency", unit="s"
        )


class OperationsAgent:
    """Primary read-only operational reasoning interface over SemanticEngine."""

    def __init__(
        self,
        semantic_engine,
        *,
        router: ContextRouter | None = None,
        reasoner: OperationalReasoner | None = None,
        telemetry: OperationsTelemetry | None = None,
        patch_intelligence=None,
        lifecycle_intelligence=None,
        incident_intelligence=None,
        change_intelligence=None,
        predictive_intelligence=None,
        remediation_planner=None,
        clock: Callable[[], float] = time.monotonic,
        max_output_items: int = 100,
        max_serialized_bytes: int = 1_000_000,
    ) -> None:
        if (
            isinstance(max_output_items, bool)
            or not isinstance(max_output_items, int)
            or max_output_items < 1
        ):
            raise ValueError("Operations max_output_items must be a positive integer")
        if (
            isinstance(max_serialized_bytes, bool)
            or not isinstance(max_serialized_bytes, int)
            or max_serialized_bytes < 1024
        ):
            raise ValueError(
                "Operations max_serialized_bytes must be an integer of at least 1024"
            )
        self.semantic = semantic_engine
        self.router = router or ContextRouter()
        self.reasoner = reasoner or OperationalReasoner(semantic_engine)
        self.telemetry = telemetry or OperationsTelemetry()
        self.patch_intelligence = patch_intelligence
        self.lifecycle_intelligence = lifecycle_intelligence
        self.incident_intelligence = incident_intelligence
        self.change_intelligence = change_intelligence
        self.predictive_intelligence = predictive_intelligence
        self.remediation_planner = remediation_planner
        self.clock = clock
        self.max_output_items = max_output_items
        self.max_serialized_bytes = max_serialized_bytes

    def analyze(
        self,
        command: str,
        subject: str,
        *,
        subject_type: str = "",
    ) -> dict[str, Any]:
        started = self.clock()
        if (
            command in PATCH_INTELLIGENCE_COMMANDS
            and self.patch_intelligence is not None
            and not (
                command in PREDICTIVE_INTELLIGENCE_COMMANDS
                and subject_type in {"PredictivePortfolio", "Application"}
            )
            and not (
                command == "Analyze Patch Compliance"
                and subject_type != "PatchPortfolio"
            )
        ):
            result = self._patch_analysis(
                command, subject, subject_type=subject_type
            )
            return self._complete(result, command=command, started=started)
        if (
            command in LIFECYCLE_INTELLIGENCE_COMMANDS
            and self.lifecycle_intelligence is not None
        ):
            result = self._lifecycle_analysis(
                command, subject, subject_type=subject_type
            )
            return self._complete(result, command=command, started=started)
        if (
            command in INCIDENT_INTELLIGENCE_COMMANDS
            and self.incident_intelligence is not None
        ):
            result = self._incident_causality_analysis(
                command, subject, subject_type=subject_type
            )
            return self._complete(result, command=command, started=started)
        if (
            command in CHANGE_INTELLIGENCE_COMMANDS
            and self.change_intelligence is not None
        ):
            result = self._change_intelligence_analysis(
                command, subject, subject_type=subject_type
            )
            return self._complete(result, command=command, started=started)
        if (
            command in PREDICTIVE_INTELLIGENCE_COMMANDS
            and self.predictive_intelligence is not None
        ):
            result = self._predictive_intelligence_analysis(
                command, subject, subject_type=subject_type
            )
            return self._complete(result, command=command, started=started)
        if (
            command in REMEDIATION_PLANNING_COMMANDS
            and self.remediation_planner is not None
        ):
            result = self._remediation_planning_analysis(
                command, subject, subject_type=subject_type
            )
            return self._complete(result, command=command, started=started)
        route = self.router.route(command, subject_type=subject_type)
        if route.context_kind == "risk":
            result = self._risk_analysis(
                command, subject, subject_type=subject_type
            )
        elif route.context_kind == "search":
            result = self._search_analysis(command, subject)
        elif route.context_kind == "impact":
            result = self._impact_analysis(command, subject, subject_type=subject_type)
        elif route.context_kind == "incident":
            result = self._incident_analysis(command, subject, subject_type=subject_type)
        elif route.context_kind == "compliance":
            context = self.reasoner.context(
                "resource", subject, subject_type=subject_type
            )
            recommendation_started = self.clock()
            result = self.reasoner.analyze_context(context, command=command)
            self.telemetry.recommendation_latency.record(
                self.clock() - recommendation_started, {"command": command}
            )
            impact_started = self.clock()
            result["impact"] = self.reasoner.impact.analyze(
                subject, subject_type=subject_type
            )
            self.telemetry.impact_duration.record(
                self.clock() - impact_started, {"command": command}
            )
            result["severity"] = str(result.get("risk", {}).get("level") or "Low")
        else:
            context_started = self.clock()
            context = self.reasoner.context(
                route.context_kind,
                subject,
                subject_type=route.subject_type or subject_type,
            )
            self.telemetry.knowledge_retrieval_latency.record(
                self.clock() - context_started, {"context_kind": route.context_kind}
            )
            recommendation_started = self.clock()
            result = self.reasoner.analyze_context(context, command=command)
            self.telemetry.recommendation_latency.record(
                self.clock() - recommendation_started, {"command": command}
            )
            if command in {"Generate Executive Summary", "Executive Summary"}:
                result["summary"] = self._generate_summary(
                    result, command=command, executive=True
                )
        if command not in {"Generate Executive Summary", "Executive Summary"}:
            result["summary"] = self._generate_summary(result, command=command)
        return self._complete(result, command=command, started=started)

    def _complete(
        self, result: dict[str, Any], *, command: str, started: float
    ) -> dict[str, Any]:
        bounded = self._bounded_public(result)
        _validate_operations_result(bounded)
        self.telemetry.analysis_duration.record(
            self.clock() - started, {"command": command}
        )
        return bounded

    def _generate_summary(
        self, result: dict[str, Any], *, command: str, executive: bool = False
    ) -> dict[str, Any]:
        started = self.clock()
        summary = self.reasoner.summaries.generate(result, executive=executive)
        self.telemetry.summary_generation_latency.record(
            self.clock() - started, {"command": command}
        )
        return summary

    def _bounded_public(self, value: Any) -> Any:
        def annotate(item: Any) -> Any:
            if isinstance(item, dict):
                result = {}
                for key, child in item.items():
                    safe_key = IncidentIntelligence._safe_identifier(key, "field")
                    if safe_key in result:
                        raise ValueError(
                            "Operations Agent public mapping key collision"
                        )
                    result[safe_key] = annotate(child)
                for key, child in item.items():
                    safe_key = IncidentIntelligence._safe_identifier(key, "field")
                    if isinstance(child, (list, tuple)) and len(child) > self.max_output_items:
                        metadata_key = f"{safe_key}_metadata"
                        if metadata_key in result:
                            raise ValueError(
                                "Operations Agent public mapping key collision"
                            )
                        result[metadata_key] = {
                            "count": len(child),
                            "returned": self.max_output_items,
                            "truncated": True,
                        }
                return result
            if isinstance(item, (list, tuple)):
                return [annotate(child) for child in item]
            return item

        def bounded(item: Any) -> Any:
            if isinstance(item, dict):
                return {key: bounded(child) for key, child in item.items()}
            if isinstance(item, (list, tuple)):
                return [bounded(child) for child in item[: self.max_output_items]]
            if isinstance(item, str):
                return IncidentIntelligence._safe_text(item)
            return item

        result = bounded(annotate(value))
        if (
            len(json.dumps(result, sort_keys=True, separators=(",", ":")).encode())
            > self.max_serialized_bytes
        ):
            raise ValueError("Operations Agent output exceeds configured bound")
        return result

    def _lifecycle_analysis(
        self, command: str, subject: str, *, subject_type: str
    ) -> dict[str, Any]:
        if subject.casefold() != "enterprise" or subject_type != "LifecyclePortfolio":
            raise ValueError(
                "Lifecycle intelligence commands are restricted to the pre-authorized enterprise lifecycle portfolio"
            )
        queries = {
            "Analyze Lifecycle Risk": "Show high risk systems",
            "Show EOL Systems": "Show eol systems",
            "Show High Risk Systems": "Show high risk systems",
            "Show Modernization Candidates": "Show modernization candidates",
            "Show Business Services At Risk": "Show business services at risk",
            "Show Lifecycle Trends": "Show lifecycle trends",
        }
        if command == "Generate Lifecycle Report":
            payload = self.lifecycle_intelligence.report(
                "Executive Lifecycle Summary"
            )
        elif command == "Generate Executive Modernization Brief":
            payload = self.lifecycle_intelligence.report(
                "Executive Modernization Brief"
            )
        else:
            payload = self.lifecycle_intelligence.query(queries[command])
        analysis = self.lifecycle_intelligence.analyze()
        findings = analysis["findings"]
        recommendations = [
            {
                "priority": item["modernization_recommendation"]["priority"],
                "impact": item["business_impact"],
                "confidence": item["confidence"],
                "rationale": item["risk_justification"],
                "suggested_action": item["modernization_recommendation"][
                    "recommended_action"
                ],
                "evidence": item["evidence"],
                "advisory_only": True,
            }
            for item in findings[:5]
            if item["modernization_recommendation"]["priority"]
            in {"Priority 1", "Priority 2", "Priority 3"}
        ]
        return {
            "command": command,
            "subject": {
                "name": "Enterprise",
                "entity_type": "LifecyclePortfolio",
            },
            "lifecycle_intelligence": payload,
            "conclusions": [
                {
                    "domain": "Operating System Lifecycle Intelligence",
                    "evidence": [
                        {
                            "finding_count": len(findings),
                            "eol_asset_count": analysis["exposure"][
                                "total_eol_assets"
                            ],
                            "business_services_at_risk": analysis["exposure"][
                                "business_services_at_risk"
                            ],
                        }
                    ],
                    "data_sources": [
                        "Azure Resource Graph inventory",
                        "Arc-enabled server inventory",
                        "Metadata Lakehouse lifecycle catalog",
                        "Fabric Ontology",
                        "Semantic Knowledge Layer",
                        "Patch Intelligence",
                    ],
                    "reasoning": "Lifecycle status is matched to authoritative catalog dates and correlated through governed operational relationships; no upgrade or remediation is executed.",
                    "risk_factors": sorted(
                        {
                            driver
                            for item in findings
                            for driver in item["risk_drivers"]
                        }
                    ),
                }
            ],
            "recommendations": recommendations,
            "freshness": analysis["freshness"],
            "read_only": True,
        }

    def _remediation_planning_analysis(
        self, command: str, subject: str, *, subject_type: str
    ) -> dict[str, Any]:
        if subject.casefold() != "enterprise" or subject_type != "RemediationPortfolio":
            raise ValueError(
                "Remediation planning commands are restricted to the pre-authorized enterprise remediation portfolio"
            )
        queries = {
            "Show High Priority Plans": "Show high priority plans",
            "Simulate Remediation": "Simulate remediation",
            "Show Risk Reduction": "Show risk reduction",
            "Show Required Approvals": "Show required approvals",
            "Show Rollback Plan": "Show rollback plan",
            "Should This Plan Be Recommended?": "Should this plan be recommended",
        }
        reports = {
            "Generate Modernization Roadmap": "Modernization Roadmap",
            "Generate Operational Debt Reduction Plan": "Technology Debt Reduction Plan",
            "Generate Executive Remediation Report": "Executive Risk Reduction Strategy",
        }
        if command == "Generate Remediation Plan":
            payload = self.remediation_planner.generate_plans()
        elif command in reports:
            payload = self.remediation_planner.report(reports[command])
        else:
            payload = self.remediation_planner.query(queries[command])
        analysis = self.remediation_planner.generate_plans()
        plans = analysis["plans"]
        recommendations = [
            {
                "priority": plan["priority"],
                "impact": plan["business_impact"],
                "confidence": plan["confidence"],
                "rationale": plan["objective"],
                "suggested_action": plan["recommended_action"]["suggested_action"],
                "evidence": plan["evidence"],
                "advisory_only": True,
            }
            for plan in plans[:5]
            if plan["priority"] in {"Priority 1", "Priority 2"}
        ]
        return {
            "command": command,
            "subject": {
                "name": "Enterprise",
                "entity_type": "RemediationPortfolio",
            },
            "remediation_planning": payload,
            "conclusions": [
                {
                    "domain": "Autonomous Remediation Planning",
                    "evidence": [analysis["summary"]],
                    "data_sources": [
                        "Operational Context Graph",
                        "Fabric Ontology",
                        "Patch Intelligence",
                        "Lifecycle Intelligence",
                        "Incident Correlation",
                        "Change and Configuration Intelligence",
                        "Predictive Operations Intelligence",
                    ],
                    "reasoning": "Draft plans are generated from governed evidence and configurable action and approval catalogs. Every plan requires approval and rollback readiness; no action is executed.",
                    "risk_factors": sorted(
                        {
                            driver
                            for plan in plans
                            for driver in plan["risk_drivers"]
                        }
                    ),
                }
            ],
            "recommendations": recommendations,
            "freshness": analysis["freshness"],
            "read_only": True,
        }

    def _predictive_intelligence_analysis(
        self, command: str, subject: str, *, subject_type: str
    ) -> dict[str, Any]:
        application_query = command == "Is Application At Risk?"
        if application_query:
            if subject_type != "Application" or not subject.strip():
                raise ValueError(
                    "Is Application At Risk? requires a governed Application subject"
                )
        elif subject.casefold() != "enterprise" or subject_type != "PredictivePortfolio":
            raise ValueError(
                "Predictive operations commands are restricted to the pre-authorized enterprise predictive portfolio"
            )
        queries = {
            "Analyze Predictive Risk": "What is likely to fail next",
            "What Is Likely To Fail Next": "What is likely to fail next",
            "Show Unstable Applications": "Show unstable applications",
            "Show Services Accumulating Debt": "Show services accumulating debt",
            "Forecast Incidents": "Forecast incidents",
            "Show Workloads Requiring Intervention": "Show workloads requiring intervention",
            "Predict Operational Risk": "Predict operational risk",
            "Show High Risk Applications": "Show high risk applications",
            "Service Stability Forecast": "Service stability forecast",
            "Show Compliance Trends": "Show compliance trends",
            "Show Operational Debt": "Show operational debt",
            "Show High Risk Resources": "Show high risk resources",
            "Show Risk Drivers": "Show risk drivers",
        }
        if application_query:
            payload = self.predictive_intelligence.application_risk(subject)
        elif command in {"Generate Predictive Operations Report", "Predictive Risk Report"}:
            payload = self.predictive_intelligence.report(
                "Predictive Operations Summary"
            )
        elif command in {"Generate Executive Predictive Brief", "Executive Forecast"}:
            payload = self.predictive_intelligence.report(
                "Executive Predictive Brief"
            )
        else:
            payload = self.predictive_intelligence.query(queries[command])
        analysis = self.predictive_intelligence.analyze()
        predictions = analysis["predictions"]
        recommendations = [
            {
                "priority": "Priority 1"
                if item["forecast_30_day"]["score"] >= 75
                else "Priority 2",
                "impact": item["business_criticality"],
                "confidence": item["confidence"],
                "rationale": item["explanation"],
                "suggested_action": item["recommended_action"]["suggested_action"],
                "evidence": item["evidence"],
                "advisory_only": True,
            }
            for item in predictions[:5]
            if item["forecast_30_day"]["score"] >= 50
        ]
        return {
            "command": command,
            "subject": {
                "name": subject if application_query else "Enterprise",
                "entity_type": "Application" if application_query else "PredictivePortfolio",
            },
            "predictive_intelligence": payload,
            "conclusions": [
                {
                    "domain": "Predictive Operations Intelligence",
                    "evidence": [analysis["summary"]],
                    "data_sources": [
                        "Patch Intelligence",
                        "Lifecycle Intelligence",
                        "Incident Correlation",
                        "Change and Configuration Intelligence",
                        "Semantic Knowledge Layer",
                        "Fabric Ontology",
                    ],
                    "reasoning": "Forecasts combine current posture, recurring incidents, operational debt, ownership, business context, and observed growth. They are evidence-backed estimates, not guaranteed outcomes.",
                    "risk_factors": sorted(
                        {
                            driver
                            for item in predictions
                            for driver in item["risk_drivers"]
                        }
                    ),
                }
            ],
            "recommendations": recommendations,
            "freshness": analysis["freshness"],
            "read_only": True,
        }

    def _change_intelligence_analysis(
        self, command: str, subject: str, *, subject_type: str
    ) -> dict[str, Any]:
        if subject.casefold() != "enterprise" or subject_type != "ChangePortfolio":
            raise ValueError(
                "Change intelligence commands are restricted to the pre-authorized enterprise change portfolio"
            )
        queries = {
            "Analyze Change Risk": "Show high risk changes",
            "Show Recent Changes": "Show recent changes",
            "Show Configuration Drift": "Show configuration drift",
            "Show Policy Deviations": "Show policy deviations",
            "Show Security Baseline Deviations": "Show security baseline deviations",
            "Show Incident Contributing Changes": "Show incident contributing changes",
            "Analyze Changes": "Analyze changes",
            "Show Resource Changes": "Show resource changes",
            "Show Policy Violations": "Show policy violations",
            "Show High Risk Changes": "Show high risk changes",
            "Show Unapproved Changes": "Show unapproved changes",
            "Show Change Timeline": "Show change timeline",
            "Explain Incident Changes": "Explain incident changes",
        }
        if command in {"Generate Change Intelligence Report", "Generate Change Report"}:
            payload = self.change_intelligence.report("Change Intelligence Summary")
        elif command == "Generate Risk Report":
            payload = self.change_intelligence.report("Change Risk Report")
        elif command == "Generate Executive Change Brief":
            payload = self.change_intelligence.report("Executive Change Brief")
        else:
            payload = self.change_intelligence.query(queries[command])
        analysis = self.change_intelligence.analyze()
        findings = analysis["findings"]
        recommendations = [
            {
                "priority": "Priority 1" if item["risk_score"] >= 75 else "Priority 2",
                "impact": item["business_criticality"],
                "confidence": item["confidence"],
                "rationale": item["risk_justification"],
                "suggested_action": item["recommended_action"]["suggested_action"],
                "evidence": item["evidence"],
                "advisory_only": True,
            }
            for item in findings[:5]
        ]
        return {
            "command": command,
            "subject": {"name": "Enterprise", "entity_type": "ChangePortfolio"},
            "change_intelligence": payload,
            "conclusions": [
                {
                    "domain": "Change and Configuration Intelligence",
                    "evidence": [analysis["summary"]],
                    "data_sources": [
                        "ARG ResourceChanges",
                        "Governed policy and security deviations",
                        "Network and identity change projections",
                        "Infrastructure-as-Code evidence",
                        "Incident Correlation",
                        "Semantic Knowledge Layer",
                        "Fabric Ontology",
                    ],
                    "reasoning": "Change risk combines actor, time, scope, drift, deviations, operational context, and temporal incident correlation; contribution remains probabilistic.",
                    "risk_factors": sorted(
                        {
                            factor
                            for item in findings
                            for factor, points in item["risk_factors"].items()
                            if points
                        }
                    ),
                }
            ],
            "recommendations": recommendations,
            "freshness": analysis["freshness"],
            "read_only": True,
        }

    def _incident_causality_analysis(
        self, command: str, subject: str, *, subject_type: str
    ) -> dict[str, Any]:
        incident_commands = {
            "Analyze Incident",
            "Explain Root Cause",
            "Show Blast Radius",
            "Show Dependency Chain",
            "Show Operational Timeline",
        }
        incident_scope = command in incident_commands
        if incident_scope:
            if subject_type != "Incident" or not subject.strip():
                raise ValueError("Incident command requires a governed Incident subject")
        elif subject.casefold() != "enterprise" or subject_type != "IncidentPortfolio":
            raise ValueError(
                "Incident intelligence commands are restricted to the pre-authorized enterprise incident portfolio"
            )
        queries = {
            "Analyze Incident Causality": "Show probable root causes",
            "Show Probable Root Causes": "Show probable root causes",
            "Show Incident Blast Radius": "Show incident blast radius",
            "Show Correlated Incidents": "Show correlated incidents",
            "Show Recurring Incident Patterns": "Show recurring incident patterns",
            "Show Recent Causes": "Show probable root causes",
        }
        if incident_scope:
            from intelligence.incidents import IncidentEngine

            scoped = IncidentEngine.from_intelligence(
                self.incident_intelligence
            ).incident(subject)["finding"]
            payload = {
                "Analyze Incident": scoped,
                "Explain Root Cause": scoped["root_cause_analysis"],
                "Show Blast Radius": scoped["blast_radius"],
                "Show Dependency Chain": scoped["dependency_chain"],
                "Show Operational Timeline": scoped["timeline"],
            }[command]
            payload = {"result": payload, "read_only": True}
        elif command == "Generate Incident Report":
            from intelligence.incidents import IncidentEngine

            payload = IncidentEngine.from_intelligence(
                self.incident_intelligence
            ).report()
        elif command == "Generate Incident Correlation Report":
            payload = self.incident_intelligence.report(
                "Incident Correlation Summary"
            )
        elif command == "Generate Incident Executive Brief":
            payload = self.incident_intelligence.report("Executive Incident Brief")
        elif command == "Show Repeated Operational Risks":
            from intelligence.incidents import IncidentEngine

            payload = {
                "result": IncidentEngine.from_intelligence(
                    self.incident_intelligence
                ).analyze()["operational_patterns"],
                "read_only": True,
            }
        else:
            payload = self.incident_intelligence.query(queries[command])
        analysis = self.incident_intelligence.analyze()
        findings = analysis["findings"]
        recommendations = [
            {
                "priority": item["recommended_action"]["priority"],
                "impact": item["recommended_action"]["impact"],
                "confidence": item["recommended_action"]["confidence"],
                "rationale": item["recommended_action"]["rationale"],
                "suggested_action": item["recommended_action"]["suggested_action"],
                "evidence": (
                    item["probable_causes"][0]["evidence"]
                    if item["probable_causes"]
                    else ["No probable cause reached the configured threshold."]
                ),
                "advisory_only": True,
            }
            for item in findings[:5]
        ]
        return {
            "command": command,
            "subject": {
                "name": subject if incident_scope else "Enterprise",
                "entity_type": "Incident" if incident_scope else "IncidentPortfolio",
            },
            "incident_intelligence": payload,
            "conclusions": [
                {
                    "domain": "Incident Correlation and Operational Causality",
                    "evidence": [analysis["summary"]],
                    "data_sources": [
                        "Governed incident and alert facts",
                        "Azure Resource Graph resource changes",
                        "Patch Intelligence",
                        "Lifecycle Intelligence",
                        "Semantic Knowledge Layer",
                        "Fabric Ontology",
                    ],
                    "reasoning": "Ranked causes combine target identity, temporal proximity, signal strength, and causal relevance. They remain probabilistic and require operator validation.",
                    "risk_factors": sorted(
                        {
                            cause["evidence_type"]
                            for item in findings
                            for cause in item["probable_causes"]
                        }
                    ),
                }
            ],
            "recommendations": recommendations,
            "freshness": analysis["freshness"],
            "read_only": True,
        }

    def _patch_analysis(
        self, command: str, subject: str, *, subject_type: str
    ) -> dict[str, Any]:
        if subject.casefold() != "enterprise" or subject_type != "PatchPortfolio":
            raise ValueError(
                "Patch intelligence commands are restricted to the pre-authorized enterprise portfolio"
            )
        queries = {
            "Analyze Patch Compliance": "Show patch compliance",
            "Analyze Security Exposure": "Show security exposure",
            "Show Security Exposure": "Show security exposure",
            "Show Critical Patch Failures": "Show critical patch failures",
            "Show High Risk Applications": "Show vulnerable applications",
            "Show Business Risk": "Show business impact",
            "Show Priority Remediation Candidates": "Show patch priority list",
        }
        if command in {"Generate Executive Brief", "Executive Brief"}:
            payload = self.patch_intelligence.report("Executive Brief")
        elif command == "Generate Patch Report":
            payload = self.patch_intelligence.report("Executive Patch Summary")
        else:
            payload = self.patch_intelligence.query(queries[command])
        findings = self.patch_intelligence.analyze()["findings"]
        recommendations = [
            {
                "priority": item["priority"],
                "impact": item["business_impact"],
                "confidence": item["confidence_score"],
                "rationale": item["priority_reasoning"],
                "suggested_action": item["recommended_action"],
                "evidence": item["evidence"],
                "advisory_only": True,
            }
            for item in findings[:5]
            if item["priority"] in {"Priority 1", "Priority 2", "Priority 3"}
        ]
        return {
            "command": command,
            "subject": {
                "name": subject or "Enterprise",
                "entity_type": "PatchPortfolio",
            },
            "patch_intelligence": payload,
            "conclusions": [
                {
                    "domain": "Patch and Vulnerability Intelligence",
                    "evidence": [
                        {
                            "finding_count": len(findings),
                            "priority_1_count": sum(
                                item["priority"] == "Priority 1" for item in findings
                            ),
                        }
                    ],
                    "data_sources": [
                        "ARG PatchAssessmentResources",
                        "ARG PatchInstallationResources",
                        "Advisor Recommendations",
                        "Semantic Knowledge Layer",
                        "Fabric Ontology",
                    ],
                    "reasoning": "Patch evidence is correlated through governed semantic and business relationships; no remediation is executed.",
                    "risk_factors": sorted(
                        {
                            factor
                            for item in findings
                            for factor, points in item["risk_factors"].items()
                            if points
                        }
                    ),
                }
            ],
            "recommendations": recommendations,
            "freshness": self.patch_intelligence.freshness_value,
            "read_only": True,
        }

    def _search_analysis(self, command: str, subject: str) -> dict[str, Any]:
        started = self.clock()
        search = self.semantic.search("resources missing ownership")
        self.telemetry.knowledge_retrieval_latency.record(
            self.clock() - started, {"context_kind": "search"}
        )
        evidence = {
            "count": search.get("count", 0),
            "returned": len(search.get("items") or []),
            "truncated": bool(search.get("truncated")),
            "items": search.get("items") or [],
        }
        return {
            "command": command,
            "subject": {
                "name": subject or "Enterprise",
                "entity_type": "OperationalPortfolio",
            },
            "conclusions": [
                {
                    "domain": "Ownership Coverage",
                    "evidence": [evidence],
                    "data_sources": [
                        "Semantic Knowledge Layer",
                        "Fabric Ontology",
                    ],
                    "reasoning": "Resources are listed only when governed ontology relationships contain no owner assertion.",
                    "risk_factors": ["missing_ownership"] if evidence["count"] else [],
                }
            ],
            "recommendations": [],
            "freshness": search.get("freshness", ""),
            "knowledge_version": search.get("knowledge_version", ""),
            "read_only": True,
        }

    def _risk_analysis(
        self, command: str, subject: str, *, subject_type: str = ""
    ) -> dict[str, Any]:
        retrieval_started = self.clock()
        risk = self.semantic.get_risk_context(
            subject, subject_type=subject_type
        )
        self.telemetry.knowledge_retrieval_latency.record(
            self.clock() - retrieval_started, {"context_kind": "risk"}
        )
        recommendation_started = self.clock()
        recommendations = self.reasoner.recommendations.generate(
            risk=risk.get("risk") or {},
            health={},
            compliance={"status": "unknown", "compliant": False},
            ownership={"coverage": "Unknown"},
            context={"sections": {}},
        )
        self.telemetry.recommendation_latency.record(
            self.clock() - recommendation_started, {"command": command}
        )
        result = {
            "command": command,
            **risk,
            "conclusions": [
                {
                    "domain": "Operational Risk",
                    "evidence": [risk.get("risk", {}).get("factors", {})],
                    "data_sources": ["Semantic Knowledge Layer"],
                    "reasoning": "The risk score and level are taken from the explainable Semantic Layer risk model.",
                    "risk_factors": list(
                        risk.get("risk", {}).get("factors", {}).keys()
                    ),
                }
            ],
            "recommendations": recommendations,
            "read_only": True,
        }
        result["summary"] = self.reasoner.summaries.generate(result)
        return result

    def _impact_analysis(
        self, command: str, subject: str, *, subject_type: str
    ) -> dict[str, Any]:
        started = self.clock()
        impact = self.reasoner.impact.analyze(subject, subject_type=subject_type)
        self.telemetry.impact_duration.record(self.clock() - started)
        result = {
            "command": command,
            "subject": impact["subject"],
            "impact": impact,
            "conclusions": [
                {
                    "domain": "Business Impact",
                    "evidence": [impact["evidence"]],
                    "data_sources": impact["data_sources"],
                    "reasoning": "Impact follows direction-aware dependency and business-service relationships.",
                    "risk_factors": [],
                }
            ],
            "recommendations": [],
            "freshness": impact.get("freshness", ""),
            "knowledge_version": impact.get("knowledge_version", ""),
            "read_only": True,
        }
        result["summary"] = self.reasoner.summaries.generate(result)
        return result

    def _incident_analysis(
        self, command: str, subject: str, *, subject_type: str
    ) -> dict[str, Any]:
        context_started = self.clock()
        context = self.reasoner.context(
            "resource", subject, subject_type=subject_type
        )
        self.telemetry.knowledge_retrieval_latency.record(
            self.clock() - context_started, {"context_kind": "incident"}
        )
        incident = self.reasoner.incident.build(
            subject, context, subject_type=subject_type
        )
        self.telemetry.context_generation_latency.record(
            self.clock() - context_started
        )
        recommendation_started = self.clock()
        analysis = self.reasoner.analyze_context(context, command=command)
        incident["risk"] = analysis["risk"]
        incident["health"] = analysis["health"]
        self.telemetry.recommendation_latency.record(
            self.clock() - recommendation_started, {"command": command}
        )
        return {
            "command": command,
            "subject": context.get("subject", {}),
            "incident_context": incident,
            "risk": analysis["risk"],
            "health": analysis["health"],
            "conclusions": [
                {
                    "domain": "Incident Context",
                    "evidence": [incident.get("evidence", {})],
                    "data_sources": incident["data_sources"],
                    "reasoning": "Incident context correlates governed resource, risk, ownership, patch, and impact evidence.",
                    "risk_factors": list(
                        (incident.get("open_risks", {}).get("factors") or {}).keys()
                    ),
                }
            ],
            "recommendations": analysis["recommendations"],
            "freshness": context.get("freshness", ""),
            "knowledge_version": context.get("knowledge_version", ""),
            "read_only": True,
        }


def _validate_operations_result(result: dict[str, Any]) -> None:
    required = {"command", "subject", "conclusions", "recommendations", "read_only"}
    if not required <= set(result) or result.get("read_only") is not True:
        raise ValueError("Invalid Operations Agent response contract")
    subject = result.get("subject") or {}
    if not isinstance(subject, dict) or not subject.get("name") or not subject.get(
        "entity_type"
    ):
        raise ValueError("Invalid Operations Agent subject contract")
    unsafe = _find_unsafe_fields(result)
    if unsafe:
        raise ValueError("Operations Agent response has unsafe fields: " + ",".join(unsafe))
    for conclusion in result.get("conclusions") or []:
        if not isinstance(conclusion, dict) or not _CONCLUSION_FIELDS <= set(
            conclusion
        ):
            raise ValueError("Invalid Operations Agent conclusion contract")
        if (
            not conclusion.get("evidence")
            or not conclusion.get("data_sources")
            or not str(conclusion.get("reasoning") or "").strip()
        ):
            raise ValueError("Invalid Operations Agent conclusion contract")
    for recommendation in result.get("recommendations") or []:
        if not isinstance(recommendation, dict) or not _RECOMMENDATION_FIELDS <= set(
            recommendation
        ):
            raise ValueError("Invalid Operations Agent recommendation contract")
        confidence = recommendation.get("confidence")
        if (
            recommendation.get("advisory_only") is not True
            or isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0 <= float(confidence) <= 1
            or not recommendation.get("evidence")
        ):
            raise ValueError("Invalid Operations Agent recommendation contract")
    try:
        json.dumps(result)
    except (TypeError, ValueError) as exc:
        raise ValueError("Operations Agent response is not JSON serializable") from exc


def _find_unsafe_fields(value: Any) -> list[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        found.update(set(value) & _BANNED_OPERATION_FIELDS)
        for item in value.values():
            found.update(_find_unsafe_fields(item))
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            found.update(_find_unsafe_fields(item))
    return sorted(found)
