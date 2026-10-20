"""Native interactive capabilities, not evidence that an agent was executed."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID


def native_agent_capabilities(environ: Mapping[str, str]) -> dict[str, Any]:
    """Describe the supported native entry point without credentials or I/O.

    The explicit native target is independent of the legacy JSON publisher.
    Configuration is not a live availability, permission or execution receipt.
    """

    workspace = str(environ.get("AIOPS_ONTOLOGY_NATIVE_WORKSPACE_ID") or "").strip()
    item = str(environ.get("AIOPS_ONTOLOGY_NATIVE_ITEM_ID") or "").strip()
    status = "not_configured"
    portal_url = None
    if workspace or item:
        try:
            workspace = str(UUID(workspace))
            item = str(UUID(item))
        except ValueError:
            status = "invalid_configuration"
        else:
            status = "configured_unverified"
            portal_url = (
                f"https://app.fabric.microsoft.com/groups/{workspace}/ontologies/{item}"
            )
    return {
        "primary_mode": "native_interactive",
        "native_interactive": {
            "status": status,
            "portal_url": portal_url,
            "authentication": "delegated_user",
            "default_mode": "plan",
            "plan_operations": ["discover", "draft", "validate", "preview", "query"],
            "apply_requires_review": True,
            "unattended_authoring": "unavailable",
            "execution_verified": False,
        },
        "foundry_fallback": {"selection_required": True, "selected": False},
    }
