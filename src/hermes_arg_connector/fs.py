"""Filesystem abstraction so dataset storage works identically against the
local disk (development) and Azure Data Lake Storage Gen2 (production),
selected purely by the shape of the configured root:

- A plain path (``/data``, ``./data``) uses the local filesystem.
- An ``abfss://<container>@<account>.dfs.core.windows.net/<path>`` URI uses
  ADLS Gen2 via ``adlfs``/``fsspec``, authenticated with
  ``azure.identity.DefaultAzureCredential`` (works with the Container Apps
  managed identity in Azure, and with ``az login``/environment SPN
  credentials locally).

Callers get back an :class:`fsspec.AbstractFileSystem` plus the root path to
use with it, and never need to branch on which backend is active.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import fsspec


def resolve_fs(root: str) -> tuple[fsspec.AbstractFileSystem, str]:
    """Return ``(filesystem, root_path)`` for the given root path or URI."""
    parsed = urlparse(str(root))
    if parsed.scheme in ("abfss", "abfs", "az"):
        from azure.identity import DefaultAzureCredential

        account = parsed.netloc.split("@")[-1].split(".")[0]
        container = parsed.netloc.split("@")[0]
        fs = fsspec.filesystem(
            "abfss",
            account_name=account,
            credential=DefaultAzureCredential(),
        )
        path = f"{container}{parsed.path}"
        return fs, path.rstrip("/")

    fs = fsspec.filesystem("file", auto_mkdir=True)
    return fs, str(root).rstrip("/") or "/"


def resolve_root(root: str) -> Path | str:
    """Normalize a dataset root: keep remote URIs intact, resolve local paths.

    Local roots are returned as a resolved :class:`Path` (matching the
    original, pre-fsspec behaviour so existing equality checks/tests keep
    working); remote (``abfss://``/``abfs://``/``az://``) roots are returned
    as a plain string, since ``Path`` mangles URIs (collapses "//").
    """
    from urllib.parse import urlparse

    text = str(root)
    if urlparse(text).scheme in ("abfss", "abfs", "az"):
        return text.rstrip("/")
    return Path(text).expanduser().resolve()


def join_root(root: Path | str, *parts: str) -> str:
    """Join path segments onto a root produced by :func:`resolve_root`."""
    return "/".join([str(root).rstrip("/"), *[part.strip("/") for part in parts]])


__all__ = ["resolve_fs"]
