"""Manages the Fabric Environment item that gives the topology-pipeline
notebook (``fabric_pipelines.notebook_manager``) a Spark session with this
repo's own packages (``fabric_pipelines``, ``hermes_arg_connector``,
``storage``, ...) installed.

Mirrors ``LakehouseManager``/``WorkspaceManager``'s resolve-by-name-or-id,
create-if-missing pattern (Don't Hand-Roll) via Fabric's generic Items API
for the Environment item itself, but Environment *custom libraries* are a
distinct Fabric REST surface (staging upload + explicit publish), not
covered by the generic Items API used for lakehouses/notebooks:

- ``POST /workspaces/{id}/environments/{envId}/staging/libraries/{name}``
  uploads one file (``.whl``/``.jar``/``.py``/``.tar.gz``) at a time as raw
  ``application/octet-stream`` -- not JSON, so this manager bypasses
  ``FabricClient.request``'s JSON body handling for that one call.
- ``POST /workspaces/{id}/environments/{envId}/staging/publish?beta=false``
  triggers publish (a genuinely slow, multi-minute operation, verified live
  at ~6 minutes); ``FabricClient.request``'s existing 202/Location
  long-running-operation polling already waits for it to complete, so this
  manager reuses that rather than adding a second polling loop.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .fabric_client import FabricClient

#: Fabric's environment publish endpoint is a released (non-preview) API
#: variant, but still requires this to be explicitly set (see the beta/GA
#: publish-environment API note): "false" selects the stable, non-deprecated
#: contract rather than the beta one due for removal 2026-08-31.
_PUBLISH_PARAMS = {"beta": "false"}


class EnvironmentManager:
    """Thin manager over Fabric's Environment item + staging library APIs,
    scoped the same way ``LakehouseManager``/``NotebookManager`` are scoped
    to their respective item types."""

    ITEM_TYPE = "Environment"

    def __init__(self, client: FabricClient, workspace_id: str) -> None:
        self.client = client
        self.workspace_id = workspace_id
        self.base_path = f"/workspaces/{workspace_id}/items"

    def resolve(self, *, item_id: str = "", display_name: str = "") -> dict[str, Any] | None:
        if item_id:
            return self.client.request("GET", f"{self.base_path}/{item_id}")
        matches = [
            item
            for item in self.client.iter_items(self.base_path, params={"type": self.ITEM_TYPE})
            if str(item.get("displayName") or "") == display_name
        ]
        if len(matches) > 1:
            raise ValueError(f"Multiple Fabric environments named {display_name!r}; configure item_id")
        return matches[0] if matches else None

    def create(self, display_name: str, *, description: str = "") -> dict[str, Any]:
        return self.client.request(
            "POST",
            self.base_path,
            json_body={
                "displayName": display_name,
                "description": description or "Custom-library Spark environment for Fabric-hosted pipelines",
                "type": self.ITEM_TYPE,
            },
        )

    @property
    def _environment_base(self) -> str:
        return f"/workspaces/{self.workspace_id}/environments"

    def upload_library(self, environment_id: str, wheel_path: Path) -> None:
        """Uploads a single ``.whl`` (or other supported) file as a Spark
        custom library into the environment's staging area.

        This is a raw-binary upload distinct from ``FabricClient.request``'s
        JSON-body contract, so it authenticates and calls ``httpx`` directly
        rather than stretching that method to cover a non-JSON payload type.
        """
        wheel_path = Path(wheel_path)
        if not wheel_path.is_file():
            raise FileNotFoundError(f"Wheel not found: {wheel_path}")
        url = (
            f"{self.client.base_url}/workspaces/{self.workspace_id}/environments/"
            f"{environment_id}/staging/libraries/{wheel_path.name}"
        )
        token = self.client.credential.get_token(FabricClient.SCOPE).token
        response = self.client.http.request(
            "POST",
            url,
            content=wheel_path.read_bytes(),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/octet-stream",
            },
        )
        response.raise_for_status()

    def import_public_libraries(self, environment_id: str, environment_yml: str) -> None:
        """Uploads a conda-style ``environment.yml`` describing PyPI/conda
        packages to install into the Spark session, via the distinct
        "import external libraries" staging endpoint (separate from the
        custom-library upload endpoint above, and separate from
        ``publish()``): ``POST .../staging/libraries/importExternalLibraries``.

        This is required because ``upload_library()`` only installs this
        repo's own wheel; the wheel's own PyPI dependencies (``deltalake``,
        ``pyarrow``, ``azure-storage-file-datalake``, etc., per
        ``pyproject.toml``) are not resolved/installed by Fabric unless
        declared here too -- omitting this step is what caused notebook runs
        to fail with ``ModuleNotFoundError`` for those transitive imports."""
        url = (
            f"{self.client.base_url}/workspaces/{self.workspace_id}/environments/"
            f"{environment_id}/staging/libraries/importExternalLibraries"
        )
        token = self.client.credential.get_token(FabricClient.SCOPE).token
        response = self.client.http.request(
            "POST",
            url,
            content=environment_yml.encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/octet-stream",
            },
        )
        response.raise_for_status()

    def publish(self, environment_id: str) -> dict[str, Any]:
        """Triggers a staging publish and waits for it to complete.

        Fabric's publish endpoint returns a 202 with a ``Location`` header
        that ``FabricClient.request``'s built-in long-running-operation
        polling already follows to completion (verified live: a real
        publish took ~6 minutes and ``request()`` blocked correctly until
        the operation resource reported ``Succeeded``) -- no separate
        polling loop is needed on top of it. This method then re-fetches
        the environment item so callers can inspect its final
        ``publishDetails`` state, and raises if that state is not success.
        """
        self.client.request(
            "POST",
            f"{self._environment_base}/{environment_id}/staging/publish",
            params=_PUBLISH_PARAMS,
        )
        item = self.client.request("GET", f"{self._environment_base}/{environment_id}")
        state = _publish_state(item)
        if state not in {"success", "succeeded"}:
            raise RuntimeError(f"Fabric environment publish did not report success: {item}")
        return item


def _publish_state(item: dict[str, Any]) -> str:
    properties = item.get("properties") or {}
    publish_info = properties.get("publishDetails") or properties.get("publishInfo") or {}
    return str(publish_info.get("state") or "").lower()


def ensure_environment(
    manager: EnvironmentManager,
    *,
    display_name: str,
    item_id: str = "",
) -> dict[str, Any]:
    """Idempotent resolve-or-create of the Environment item itself (library
    upload/publish are separate explicit steps -- an Environment item with
    no libraries uploaded yet is still a valid, resolvable item)."""
    item = manager.resolve(item_id=item_id, display_name=display_name)
    if item is not None:
        return {**item, "action": "resolved"}
    created = manager.create(display_name)
    return {**created, "action": "created"}


__all__ = [
    "EnvironmentManager",
    "ensure_environment",
]
