"""Scope-aware inventory projections."""

from typing import TYPE_CHECKING

from .models import (
    InventoryEvidence,
    InventorySourceStatus,
    MachineObservation,
    OSGroup,
    SoftwareGroup,
    SoftwareObservation,
    group_key,
)

if TYPE_CHECKING:
    from .service import InventoryService, InventorySnapshot


def __getattr__(name: str):
    """Load the service lazily so source normalizers can import model contracts."""
    if name in {"InventoryService", "InventorySnapshot"}:
        from .service import InventoryService, InventorySnapshot

        return {"InventoryService": InventoryService, "InventorySnapshot": InventorySnapshot}[name]
    raise AttributeError(name)

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
