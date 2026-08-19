from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

SUPPORTED_COMMANDS = (
    "Analyze VM",
    "Analyze Application",
    "Analyze Subscription",
    "Analyze Business Service",
    "Find Resources With Missing Ownership",
    "Analyze Operational Risk",
    "Show Operational Risk",
    "Analyze Patch Compliance",
    "Show Patch Compliance",
    "Show Health Summary",
    "Show Impact Summary",
    "Generate Executive Summary",
    "Executive Summary",
    "Generate Incident Context",
    "Analyze Security Exposure",
    "Show Security Exposure",
    "Show Critical Patch Failures",
    "Show High Risk Applications",
    "Show Business Risk",
    "Generate Patch Report",
    "Generate Executive Brief",
    "Executive Brief",
    "Show Priority Remediation Candidates",
    "Analyze Lifecycle Risk",
    "Show EOL Systems",
    "Show High Risk Systems",
    "Show Modernization Candidates",
    "Show Business Services At Risk",
    "Generate Lifecycle Report",
    "Generate Executive Modernization Brief",
    "Show Lifecycle Trends",
    "Analyze Incident Causality",
    "Show Probable Root Causes",
    "Show Incident Blast Radius",
    "Show Correlated Incidents",
    "Show Recurring Incident Patterns",
    "Generate Incident Correlation Report",
    "Generate Incident Executive Brief",
    "Analyze Incident",
    "Explain Root Cause",
    "Show Blast Radius",
    "Show Dependency Chain",
    "Show Operational Timeline",
    "Show Recent Causes",
    "Show Repeated Operational Risks",
    "Generate Incident Report",
    "Analyze Change Risk",
    "Show Recent Changes",
    "Show Configuration Drift",
    "Show Policy Deviations",
    "Show Security Baseline Deviations",
    "Show Incident Contributing Changes",
    "Generate Change Intelligence Report",
    "Generate Executive Change Brief",
    "Analyze Changes",
    "Show Resource Changes",
    "Show Policy Violations",
    "Show High Risk Changes",
    "Show Unapproved Changes",
    "Generate Change Report",
    "Show Change Timeline",
    "Explain Incident Changes",
    "Generate Risk Report",
    "Analyze Predictive Risk",
    "What Is Likely To Fail Next",
    "Show Unstable Applications",
    "Show Services Accumulating Debt",
    "Forecast Incidents",
    "Show Workloads Requiring Intervention",
    "Generate Predictive Operations Report",
    "Generate Executive Predictive Brief",
    "Predict Operational Risk",
    "Service Stability Forecast",
    "Show Compliance Trends",
    "Show Operational Debt",
    "Show High Risk Resources",
    "Show Risk Drivers",
    "Predictive Risk Report",
    "Executive Forecast",
    "Is Application At Risk?",
    "Generate Remediation Plan",
    "Show High Priority Plans",
    "Simulate Remediation",
    "Show Risk Reduction",
    "Show Required Approvals",
    "Show Rollback Plan",
    "Generate Modernization Roadmap",
    "Generate Operational Debt Reduction Plan",
    "Generate Executive Remediation Report",
    "Should This Plan Be Recommended?",
)

PATCH_INTELLIGENCE_COMMANDS = {
    "Analyze Patch Compliance",
    "Analyze Security Exposure",
    "Show Security Exposure",
    "Show Critical Patch Failures",
    "Show High Risk Applications",
    "Show Business Risk",
    "Generate Patch Report",
    "Generate Executive Brief",
    "Executive Brief",
    "Show Priority Remediation Candidates",
}

LIFECYCLE_INTELLIGENCE_COMMANDS = {
    "Analyze Lifecycle Risk",
    "Show EOL Systems",
    "Show High Risk Systems",
    "Show Modernization Candidates",
    "Show Business Services At Risk",
    "Generate Lifecycle Report",
    "Generate Executive Modernization Brief",
    "Show Lifecycle Trends",
}

INCIDENT_INTELLIGENCE_COMMANDS = {
    "Analyze Incident Causality",
    "Show Probable Root Causes",
    "Show Incident Blast Radius",
    "Show Correlated Incidents",
    "Show Recurring Incident Patterns",
    "Generate Incident Correlation Report",
    "Generate Incident Executive Brief",
    "Analyze Incident",
    "Explain Root Cause",
    "Show Blast Radius",
    "Show Dependency Chain",
    "Show Operational Timeline",
    "Show Recent Causes",
    "Show Repeated Operational Risks",
    "Generate Incident Report",
}

CHANGE_INTELLIGENCE_COMMANDS = {
    "Analyze Change Risk",
    "Show Recent Changes",
    "Show Configuration Drift",
    "Show Policy Deviations",
    "Show Security Baseline Deviations",
    "Show Incident Contributing Changes",
    "Generate Change Intelligence Report",
    "Generate Executive Change Brief",
    "Analyze Changes",
    "Show Resource Changes",
    "Show Policy Violations",
    "Show High Risk Changes",
    "Show Unapproved Changes",
    "Generate Change Report",
    "Show Change Timeline",
    "Explain Incident Changes",
    "Generate Risk Report",
}

PREDICTIVE_INTELLIGENCE_COMMANDS = {
    "Analyze Predictive Risk",
    "What Is Likely To Fail Next",
    "Show Unstable Applications",
    "Show Services Accumulating Debt",
    "Forecast Incidents",
    "Show Workloads Requiring Intervention",
    "Generate Predictive Operations Report",
    "Generate Executive Predictive Brief",
    "Predict Operational Risk",
    "Show High Risk Applications",
    "Service Stability Forecast",
    "Show Compliance Trends",
    "Show Operational Debt",
    "Show High Risk Resources",
    "Show Risk Drivers",
    "Predictive Risk Report",
    "Executive Forecast",
    "Is Application At Risk?",
}

REMEDIATION_PLANNING_COMMANDS = {
    "Generate Remediation Plan",
    "Show High Priority Plans",
    "Simulate Remediation",
    "Show Risk Reduction",
    "Show Required Approvals",
    "Show Rollback Plan",
    "Generate Modernization Roadmap",
    "Generate Operational Debt Reduction Plan",
    "Generate Executive Remediation Report",
    "Should This Plan Be Recommended?",
}


@dataclass(frozen=True)
class RoutedContext:
    command: str
    context_kind: str
    subject_type: str = ""


class ContextRouter:
    """Maps the bounded command contract to Semantic Layer views."""

    _ROUTES: ClassVar[dict[str, RoutedContext]] = {
        "Analyze VM": RoutedContext("Analyze VM", "resource", "VirtualMachine"),
        "Analyze Application": RoutedContext("Analyze Application", "application", "Application"),
        "Analyze Subscription": RoutedContext("Analyze Subscription", "subscription", "Subscription"),
        "Analyze Business Service": RoutedContext(
            "Analyze Business Service", "service", "BusinessService"
        ),
        "Find Resources With Missing Ownership": RoutedContext(
            "Find Resources With Missing Ownership", "search", "OperationalPortfolio"
        ),
        "Analyze Operational Risk": RoutedContext("Analyze Operational Risk", "risk"),
        "Show Operational Risk": RoutedContext("Show Operational Risk", "risk"),
        "Analyze Patch Compliance": RoutedContext("Analyze Patch Compliance", "compliance"),
        "Show Patch Compliance": RoutedContext("Show Patch Compliance", "compliance"),
        "Show Health Summary": RoutedContext("Show Health Summary", "health"),
        "Show Impact Summary": RoutedContext("Show Impact Summary", "impact"),
        "Generate Executive Summary": RoutedContext(
            "Generate Executive Summary", "executive"
        ),
        "Executive Summary": RoutedContext("Executive Summary", "executive"),
        "Generate Incident Context": RoutedContext(
            "Generate Incident Context", "incident"
        ),
        **{
            command: RoutedContext(command, "patch_intelligence", "PatchPortfolio")
            for command in PATCH_INTELLIGENCE_COMMANDS
            if command != "Analyze Patch Compliance"
        },
        **{
            command: RoutedContext(
                command, "lifecycle_intelligence", "LifecyclePortfolio"
            )
            for command in LIFECYCLE_INTELLIGENCE_COMMANDS
        },
        **{
            command: RoutedContext(
                command, "incident_intelligence", "IncidentPortfolio"
            )
            for command in INCIDENT_INTELLIGENCE_COMMANDS
        },
        **{
            command: RoutedContext(command, "change_intelligence", "ChangePortfolio")
            for command in CHANGE_INTELLIGENCE_COMMANDS
        },
        **{
            command: RoutedContext(
                command, "predictive_intelligence", "PredictivePortfolio"
            )
            for command in PREDICTIVE_INTELLIGENCE_COMMANDS
        },
        **{
            command: RoutedContext(
                command, "remediation_planning", "RemediationPortfolio"
            )
            for command in REMEDIATION_PLANNING_COMMANDS
        },
    }

    def route(self, command: str, *, subject_type: str = "") -> RoutedContext:
        try:
            routed = self._ROUTES[command]
        except KeyError as exc:
            raise ValueError(
                "Unsupported Operations Agent command; supported commands: "
                + "; ".join(SUPPORTED_COMMANDS)
            ) from exc
        if routed.context_kind in {"health", "executive"}:
            normalized = subject_type.casefold()
            kind = {
                "virtualmachine": "resource",
                "arcserver": "resource",
                "resource": "resource",
                "application": "application",
                "subscription": "subscription",
                "businessservice": "service",
                "service": "service",
                "environment": "environment",
            }.get(normalized)
            if not kind:
                raise ValueError(
                    f"{command} requires subject_type: VirtualMachine, Application, "
                    "Subscription, BusinessService, Service, or Environment"
                )
            return RoutedContext(command, kind, subject_type)
        return routed
