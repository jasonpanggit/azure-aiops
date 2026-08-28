"""Neutral query contracts shared by API discovery consumers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QuerySpec:
    """Versioned query definition and its source scope."""

    name: str
    table: str
    query: str
    incremental: bool
    scope: str = "subscriptions"
    version: str = "1.0.0"
