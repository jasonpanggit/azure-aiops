"""Shared confidence-scoring model for discovered ontology relationships.

Confidence values used to be hardcoded magic numbers scattered across
``onboarding/graph_normalize.py`` and ``ontology/relationship_builder.py``
(0.9, 0.95, 0.98, 0.99, 1.0). This module centralizes *why* a given source
produces a given confidence so future sources get a sane default instead of
another guessed literal, while preserving every existing value as the
default output for its originating source (no behavior change on its own).

``compute_confidence`` additionally supports a small corroboration bump: a
relationship inferred from more than one independent signal (e.g. both a
resource tag and an inventory/lineage signal) is slightly more trustworthy
than one asserted by a single source.
"""

from __future__ import annotations

# Base confidence per originating source family. Keys are matched by exact
# string or, failing that, by prefix (for sources like "arg:Resources" that
# vary by dataset but share a trust level). Preserves the exact literal
# values previously hardcoded at each call site.
_BASE_CONFIDENCE_BY_SOURCE: dict[str, float] = {
    "arg:ResourceContainers": 1.0,
    "arg:Resources": 1.0,
    "azure:CostManagement": 1.0,
    "inventory": 1.0,
    "subscription_connection": 1.0,
    "arg:PatchAssessmentResources": 0.98,
    "arg:PatchInstallationResources": 0.98,
    "arg:AdvisorResources": 0.98,
    "arg:AuthorizationResources": 0.98,
    "resource_tag": 1.0,
    "dependency_tag": 1.0,
    "fabric_data_agent": 0.9,
    "fabric_data_agent_llm": 0.85,
    "patch_assessment": 0.98,
    "patch_installation": 0.98,
    "advisor": 0.98,
}

# Prefix fallbacks for source strings that are not literal keys above, e.g.
# "arg:Foo" families not explicitly listed, or "azure:Foo" telemetry sources.
_BASE_CONFIDENCE_BY_PREFIX: tuple[tuple[str, float], ...] = (
    ("arg:", 1.0),
    ("azure:", 1.0),
)

_DEFAULT_BASE_CONFIDENCE = 1.0

# Corroboration nudges confidence toward certainty without ever exceeding
# 1.0, capping the bump so already-high-confidence sources don't get an
# outsized boost relative to their room to grow.
_CORROBORATION_BUMP = 0.02


def compute_confidence(source: str, *, corroborated: bool = False, base: float | None = None) -> float:
    """Returns the confidence score for a relationship asserted by ``source``.

    Args:
        source: the originating signal/source identifier (e.g. ``"arg:Resources"``,
            ``"resource_tag"``, ``"fabric_data_agent_llm"``).
        corroborated: whether more than one independent source/signal agrees
            on this relationship. When True, confidence is nudged upward
            (capped at 1.0).
        base: optional explicit override for the base confidence instead of
            looking ``source`` up in the known-source table. Lets callers
            preserve a specific pre-existing literal (e.g. a call site that
            historically used 0.9 or 0.95 for reasons not tied to the source
            name alone) while still going through the corroboration logic.
    """
    if base is not None:
        resolved_base = base
    else:
        resolved_base = _BASE_CONFIDENCE_BY_SOURCE.get(source)
        if resolved_base is None:
            for prefix, value in _BASE_CONFIDENCE_BY_PREFIX:
                if source.startswith(prefix):
                    resolved_base = value
                    break
        if resolved_base is None:
            resolved_base = _DEFAULT_BASE_CONFIDENCE

    if not corroborated:
        return resolved_base
    return min(1.0, round(resolved_base + _CORROBORATION_BUMP, 4))
