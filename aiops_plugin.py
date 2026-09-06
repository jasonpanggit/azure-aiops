from __future__ import annotations

import json
from typing import Any

from onboarding.plugin import OPERATIONS_AGENT_SCHEMA as TOOL_SCHEMA
from onboarding.plugin import register as _register_operations

EXPOSURE_QUERY_SCHEMA = {
    "name": "exposure_query",
    "description": (
        "Authenticated, scope-bound Exposure query over the same generation, "
        "filter, sort, evidence, and completeness contract as the API."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "generation": {"type": "string"},
            "target_kind": {
                "type": "string",
                "enum": ["server", "container_image"],
            },
            "severity": {"type": "string"},
            "source_family": {"type": "string"},
            "query": {"type": "string"},
            "sort_by": {
                "type": "string",
                "enum": [
                    "priority_score",
                    "severity",
                    "target_id",
                    "weakness_id",
                ],
            },
            "sort_direction": {
                "type": "string",
                "enum": ["asc", "desc"],
            },
        },
        "required": [],
        "additionalProperties": False,
    },
}


def _handle_exposure_query(args: dict[str, Any], **kwargs: Any) -> str:
    """Invoke the governed Copilot query only with API-derived auth context."""

    context = kwargs.get("context")
    scope = kwargs.get("scope")
    principal = kwargs.get("principal")
    if (
        context is None
        or principal is None
        or scope is None
        or not hasattr(scope, "to_dict")
        or not hasattr(scope, "matches")
    ):
        return json.dumps(
            {
                "status": "denied",
                "data": None,
                "evidence": [],
                "warning": "Exposure query requires authenticated API context",
            }
        )

    from operations.tools import call_tool

    result = call_tool(
        "cve_exposure",
        args,
        context=context,
        scope=scope,
        principal=principal,
    )
    return json.dumps(result.to_dict(), default=str)


def register(ctx: Any) -> None:
    """Preserve the legacy plugin and add the governed Exposure operation."""

    _register_operations(ctx)
    ctx.register_tool(
        name="exposure_query",
        toolset="azure_operational_context",
        schema=EXPOSURE_QUERY_SCHEMA,
        handler=_handle_exposure_query,
        check_fn=lambda: True,
        emoji="🛡️",
    )


__all__ = [
    "EXPOSURE_QUERY_SCHEMA",
    "TOOL_SCHEMA",
    "_handle_exposure_query",
    "register",
]
