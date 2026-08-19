"""Authoritative operational knowledge interface over Fabric Ontology."""

from .semantic_engine import SemanticEngine
from .semantic_models import SemanticContext, SemanticEntity

__all__ = ["SemanticContext", "SemanticEngine", "SemanticEntity"]
