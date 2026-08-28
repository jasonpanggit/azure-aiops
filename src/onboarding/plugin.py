"""Hermes plugin registration for Azure operational context."""

from __future__ import annotations

import json
import os
from pathlib import Path
from threading import RLock

_SEMANTIC_RUNTIME = None
_SEMANTIC_RUNTIME_LOCK = RLock()

OPERATIONS_AGENT_SCHEMA = {
    "name": "operations_analysis",
    "description": (
        "Primary read-only operational reasoning interface over the Semantic Knowledge Layer. "
        "Returns evidence-backed analysis, health, impact, incident context, summaries, and advisory recommendations."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "enum": [
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
                ],
            },
            "subject": {
                "type": "string",
                "description": "Authorized subject label; portfolio intelligence commands require Enterprise.",
            },
            "subject_type": {
                "type": "string",
                "description": "Patch portfolio commands require PatchPortfolio, while core Show/Analyze Patch Compliance accepts governed resource types; lifecycle commands require LifecyclePortfolio; incident-specific reasoning commands require Incident and portfolio incident commands require IncidentPortfolio; change commands require ChangePortfolio; predictive portfolio commands require PredictivePortfolio; remediation planning commands require RemediationPortfolio; Is Application At Risk? requires Application.",
            },
        },
        "required": ["command", "subject"],
        "additionalProperties": False,
    },
}


def _fabric_config_path() -> Path:
    configured = os.environ.get("HERMES_FABRIC_CONFIG")
    if not configured:
        raise ValueError("HERMES_FABRIC_CONFIG must identify the trusted Fabric configuration")
    path = Path(configured).expanduser().resolve(strict=True)
    if not path.is_file():
        raise ValueError("HERMES_FABRIC_CONFIG must be a file")
    return path

def _handle_operations(args: dict, **_kwargs) -> str:
    try:
        runtime = _get_semantic_runtime()
        result = runtime.operations_agent().analyze(
            str(args.get("command") or ""),
            str(args.get("subject") or ""),
            subject_type=str(args.get("subject_type") or ""),
        )
        return json.dumps(result, default=str)
    except LookupError:
        return json.dumps({"error": "Operational subject was not found"})
    except ValueError:
        return json.dumps({"error": "Operations analysis request is invalid or ambiguous"})
    except Exception:  # noqa: BLE001 - fail closed at the agent boundary.
        return json.dumps({"error": "Operations analysis failed"})


def _get_semantic_runtime():
    global _SEMANTIC_RUNTIME

    from fabric.config import FabricRuntimeConfig
    from fabric.runtime import build_runtime

    path = _fabric_config_path()
    key = (str(path), path.stat().st_mtime_ns)
    with _SEMANTIC_RUNTIME_LOCK:
        if _SEMANTIC_RUNTIME is None or _SEMANTIC_RUNTIME[0] != key:
            _SEMANTIC_RUNTIME = (key, build_runtime(FabricRuntimeConfig.load(path)))
        return _SEMANTIC_RUNTIME[1]


def _setup_cli(parser) -> None:
    from .cli import register_cli

    register_cli(parser)


def _handle_cli(args) -> int:
    from .cli import cli_command

    return cli_command(args)



def _fabric_tool_available() -> bool:
    try:
        return _fabric_config_path().exists()
    except (ValueError, OSError):
        return False


def register(ctx) -> None:
    ctx.register_cli_command(
        name="azure-graph",
        help="Ingest Azure Resource Graph into Fabric-aligned datasets",
        setup_fn=_setup_cli,
        handler_fn=_handle_cli,
        description="Run, schedule, and query the Azure operational context connector.",
    )
    ctx.register_tool(
        name="operations_analysis",
        toolset="azure_operational_context",
        schema=OPERATIONS_AGENT_SCHEMA,
        handler=_handle_operations,
        check_fn=_fabric_tool_available,
        emoji="🧠",
    )


