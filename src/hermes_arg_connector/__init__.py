"""Azure Resource Graph connector for Hermes Operations Graph.

Heavy connector dependencies are loaded lazily so Hermes can inspect and
register the read-only plugin tool without importing PyArrow or PyYAML.
"""

__all__ = ["ConnectorConfig", "IngestionService"]
__version__ = "0.1.0"


def __getattr__(name: str):
    if name == "ConnectorConfig":
        from .config import ConnectorConfig

        return ConnectorConfig
    if name == "IngestionService":
        from .service import IngestionService

        return IngestionService
    raise AttributeError(name)
