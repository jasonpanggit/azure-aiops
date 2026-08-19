"""Microsoft Fabric connectivity package."""

from .auth import FabricAuthConfig, build_credential
from .fabric_client import FabricClient

__all__ = ["FabricAuthConfig", "FabricClient", "build_credential"]
