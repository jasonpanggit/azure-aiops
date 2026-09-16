"""Review prioritization for non-authoritative Data Agent suggestions."""

from __future__ import annotations

from .relationship_suggestions_contract import RelationshipSuggestion


def prioritize_suggestions(
    suggestions: list[RelationshipSuggestion],
) -> list[RelationshipSuggestion]:
    """Order advisory suggestions by confidence without promoting any edge."""
    return [
        suggestion
        for _, suggestion in sorted(
            enumerate(suggestions),
            key=lambda item: (-float(item[1].confidence), item[0]),
        )
    ]


__all__ = ["prioritize_suggestions"]
