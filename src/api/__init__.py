"""AIOps Operations API layer.

Composes the existing service layer over HTTP. Contains no business logic and
never bypasses the Semantic Knowledge Layer.
"""

__all__ = ["ApiContext", "create_app"]


def __getattr__(name: str):
    """Keep importing a leaf API module from eagerly importing the app."""
    if name == "create_app":
        from .app import create_app
        return create_app
    if name == "ApiContext":
        from .dependencies import ApiContext
        return ApiContext
    raise AttributeError(name)
