"""Hermes Operations API layer.

Composes the existing service layer over HTTP. Contains no business logic and
never bypasses the Semantic Knowledge Layer.
"""

from .app import create_app
from .dependencies import ApiContext

__all__ = ["ApiContext", "create_app"]
