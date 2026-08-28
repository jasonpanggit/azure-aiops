"""Scope-aware inventory projections."""

from typing import TYPE_CHECKING

from .models import (
    InventoryEvidence,
    InventoryNarrativeCitation,
    InventorySourceStatus,
    MachineObservation,
    OSGroup,
    ResourceObservation,
    SoftwareGroup,
    SoftwareObservation,
    group_key,
)
from .read_port import InventoryReadPort

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
    "InventoryNarrativeCitation",
    "InventoryReadPort",
    "InventoryService",
    "InventorySnapshot",
    "InventorySourceStatus",
    "MachineObservation",
    "OSGroup",
    "ResourceObservation",
    "SoftwareGroup",
    "SoftwareObservation",
    "group_key",
]
