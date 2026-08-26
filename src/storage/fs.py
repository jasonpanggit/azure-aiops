"""Filesystem abstraction so dataset storage works identically against the
local disk (development) and OneLake -- the Microsoft Fabric unified data
platform -- in production, selected purely by the shape of the configured
root:

- A plain path (``/data``, ``./data``) uses the local filesystem.
- An ``abfss://<workspace>@onelake.dfs.fabric.microsoft.com/<lakehouse>/<path>``
  URI uses OneLake through the DFS-native client in
  :mod:`storage.onelake_fs`, authenticated with
  ``azure.identity.DefaultAzureCredential`` (works with the Container Apps
  managed identity in Azure, and with ``az login``/environment SPN
  credentials locally).

Callers get back a filesystem object plus the root path to use with it, and
never need to branch on which backend is active. Both backends expose the same
small surface (``exists``/``open``/``makedirs``/``ls``/``info``/``isdir``/
``rm``/``mv``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import fsspec

ONELAKE_HOST = "onelake.dfs.fabric.microsoft.com"
REMOTE_SCHEMES = ("abfss", "abfs")


def is_onelake_uri(root: object) -> bool:
    """True when ``root`` addresses OneLake rather than the local disk."""
    parsed = urlparse(str(root))
    return parsed.scheme in REMOTE_SCHEMES


def resolve_fs(root: str) -> tuple[Any, str]:
    """Return ``(filesystem, root_path)`` for the given local path or OneLake URI."""
    parsed = urlparse(str(root))
    if parsed.scheme in REMOTE_SCHEMES:
        from azure.identity import DefaultAzureCredential

        host = parsed.netloc.split("@")[-1]
        if host.lower() != ONELAKE_HOST:
            raise ValueError(
                f"Only OneLake roots are supported ({ONELAKE_HOST}); got {root!r}. "
                "Azure Data Lake Storage Gen2 roots are no longer supported."
            )
        workspace = parsed.netloc.split("@")[0]
        # Deliberately not ``fsspec.filesystem("abfss", ...)``: adlfs falls
        # back to classic Blob Service calls (list_blobs, staged-block
        # uploads) that OneLake answers with IncorrectEndpointError. See
        # ``onelake_fs`` for the DFS-native replacement.
        from .onelake_fs import OneLakeFileSystem

        fs = OneLakeFileSystem(workspace, DefaultAzureCredential())
        path = f"{workspace}{parsed.path}"
        return fs, path.rstrip("/")

    fs = fsspec.filesystem("file", auto_mkdir=True)
    return fs, str(root).rstrip("/") or "/"


def resolve_root(root: str) -> Path | str:
    """Normalize a dataset root: keep OneLake URIs intact, resolve local paths.

    Local roots are returned as a resolved :class:`Path`; OneLake
    (``abfss://``) roots are returned as a plain string, since ``Path``
    mangles URIs (collapses "//").
    """
    text = str(root)
    if is_onelake_uri(text):
        return text.rstrip("/")
    return Path(text).expanduser().resolve()


def join_root(root: Path | str, *parts: str) -> str:
    """Join path segments onto a root produced by :func:`resolve_root`."""
    return "/".join([str(root).rstrip("/"), *[part.strip("/") for part in parts]])


__all__ = ["ONELAKE_HOST", "REMOTE_SCHEMES", "is_onelake_uri", "join_root", "resolve_fs", "resolve_root"]
