"""Operating-system lifecycle intelligence."""

from .eol_catalog import EOLCatalog, LifecycleCatalogEntry, LifecycleStatus
from .lifecycle_intelligence import LifecycleIntelligence

__all__ = [
    "EOLCatalog",
    "LifecycleCatalogEntry",
    "LifecycleIntelligence",
    "LifecycleStatus",
]
