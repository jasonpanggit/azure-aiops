"""Scope-aware inventory projections."""

from .models import (
    InventoryEvidence,
    InventorySourceStatus,
    MachineObservation,
    OSGroup,
    SoftwareGroup,
    SoftwareObservation,
    group_key,
)
from .service import InventoryService, InventorySnapshot

__all__ = [
    "InventoryEvidence",
    "InventoryService",
    "InventorySnapshot",
    "InventorySourceStatus",
    "MachineObservation",
    "OSGroup",
    "SoftwareGroup",
    "SoftwareObservation",
    "group_key",
]
