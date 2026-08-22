"""Dependency graph routes.

The dependency graph is served from the semantic layer's traversal intents so
the UI and the CLI observe the same closure rules (including truncation).
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Query

from ..dependencies import Context, ReadScope
from ..evidence import CONFIDENCE_MEDIUM, Evidence, envelope
from .context import _authorize_subject, _scoped

router = APIRouter(prefix="/api/v1/graph", tags=["graph"])

_QUESTION_BY_DIRECTION = {
    "upstream": "upstream dependencies",
    "downstream": "downstream impact",
    "both": "dependency chains",
}


@router.get("/dependencies/{application}", summary="Application dependency graph")
def dependency_graph(
    application: str,
    context: Context,
    scope: ReadScope,
    direction: Literal["upstream", "downstream", "both"] = Query("both"),
) -> dict[str, Any]:
    subject = context.semantic().public_subject(application, types={"Application"})
    _authorize_subject({"root": subject}, scope, application)
    result = context.semantic().query(
        _QUESTION_BY_DIRECTION[direction], subject=application
    )
    return envelope(
        _scoped(result, scope),
        evidence=Evidence.from_context(
            result,
            source_engine="semantic.SemanticEngine",
            source_table="ontology_relationships",
            resource_id=application,
            # Traversal depth is bounded, so a graph answer may be partial;
            # the `truncated` flag in the payload says when.
            confidence=CONFIDENCE_MEDIUM,
        ),
        scope=scope.to_dict(),
        knowledge_version=str(result.get("knowledge_version") or ""),
    )
