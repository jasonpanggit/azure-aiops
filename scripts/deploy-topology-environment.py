#!/usr/bin/env python3
"""Build this project's wheel and deploy it as a Fabric Environment custom
library, so the ``topology_pipeline_notebook`` Fabric-hosted notebook item
(see ``scripts/deploy-topology-notebook.py``) has a Spark session with this
repo's own packages (``fabric_pipelines``, ``hermes_arg_connector``,
``storage``, ...) installed, instead of failing with an import error.

This is a one-off operator script (not part of the automated test suite),
mirroring ``scripts/deploy-topology-notebook.py``'s CLI/credential-loading
style: it (1) builds a wheel via ``hatchling``, (2) creates/resolves the
Fabric Environment item, (3) uploads the wheel as a custom library, and
(4) publishes the environment, polling until publish completes (this is
genuinely slow -- minutes, not seconds).

Usage:
    .venv/bin/python scripts/deploy-topology-environment.py [--fabric-config path] [--skip-build]

Credentials are sourced from the environment (AZURE_CLIENT_SECRET, or
whatever fabric.yaml's auth.client_secret_env names) exactly as the rest of
this repo's Fabric tooling expects -- source web/.env.local first if needed.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fabric.auth import FabricAuthConfig, build_credential  # noqa: E402
from fabric.environment_manager import EnvironmentManager, ensure_environment  # noqa: E402
from fabric.fabric_client import FabricClient  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent


def _build_wheel() -> Path:
    """Builds the project wheel via hatchling and returns its path."""
    dist_dir = REPO_ROOT / "dist"
    for stale in dist_dir.glob("*.whl") if dist_dir.exists() else []:
        stale.unlink()
    subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", "-w", str(dist_dir), str(REPO_ROOT)],
        check=True,
        cwd=REPO_ROOT,
    )
    wheels = sorted(dist_dir.glob("*.whl"))
    if not wheels:
        raise RuntimeError(f"No wheel produced in {dist_dir}")
    return wheels[-1]


#: PyPI dependencies this repo's wheel needs at runtime (mirrors
#: ``pyproject.toml``'s ``[project].dependencies`` -- kept in sync manually
#: since Fabric's external-libraries API wants an ``environment.yml``, not a
#: ``pyproject.toml``/``requirements.txt`` passthrough). These are the
#: transitive imports ``fabric_pipelines``/``storage``/``hermes_arg_connector``
#: need (``deltalake``, ``pyarrow``, ``azure-storage-file-datalake``, ...)
#: that installing only this repo's own wheel does not pull in.
_PYPI_DEPENDENCIES: tuple[str, ...] = (
    "azure-identity>=1.19,<2",
    "azure-keyvault-secrets>=4.9,<5",
    "azure-storage-file-datalake>=12.18,<13",
    "deltalake>=1.0,<2",
    "httpx>=0.27,<1",
    "opentelemetry-api>=1.29,<2",
    "PyJWT[crypto]>=2.10,<3",
    "pyarrow>=23.0.1,<24",
    "PyYAML>=6,<7",
    "fsspec>=2024.6,<2025",
    "adlfs>=2024.7,<2025",
)


def _build_environment_yml() -> str:
    """Renders a conda-style ``environment.yml`` for Fabric's "import
    external libraries" staging endpoint, listing this repo's own PyPI
    dependencies as pip packages so the Spark session actually has them
    installed alongside the custom-library wheel."""
    pip_lines = "\n".join(f"    - {dep}" for dep in _PYPI_DEPENDENCIES)
    return f"dependencies:\n  - pip:\n{pip_lines}\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fabric-config", default="fabric.config.yaml")
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Reuse the most recently built wheel in dist/ instead of rebuilding.",
    )
    args = parser.parse_args()

    config_path = Path(args.fabric_config)
    if not config_path.exists():
        print(f"error: {config_path} not found", file=sys.stderr)
        return 1

    raw = yaml.safe_load(config_path.read_text())
    fabric_cfg = raw.get("fabric") or {}
    workspace_id = str(fabric_cfg.get("workspace_id") or "")
    if not workspace_id or workspace_id == "00000000-0000-0000-0000-000000000000":
        print("error: fabric.workspace_id is not set to a real workspace", file=sys.stderr)
        return 1

    topology_cfg = fabric_cfg.get("topology_pipeline") or {}
    display_name = str(topology_cfg.get("environment_display_name") or "topology_pipeline_env")
    item_id = str(topology_cfg.get("environment_item_id") or "")

    if args.skip_build:
        dist_dir = REPO_ROOT / "dist"
        wheels = sorted(dist_dir.glob("*.whl")) if dist_dir.exists() else []
        if not wheels:
            print("error: --skip-build given but no wheel found in dist/", file=sys.stderr)
            return 1
        wheel_path = wheels[-1]
        print(f"Reusing existing wheel: {wheel_path}")
    else:
        print("Building wheel ...")
        wheel_path = _build_wheel()
        print(f"Built wheel: {wheel_path}")

    auth_cfg = FabricAuthConfig.from_mapping(fabric_cfg.get("auth") or {})
    credential = build_credential(auth_cfg)
    client = FabricClient(credential)

    manager = EnvironmentManager(client, workspace_id)
    print(f"Resolving/creating environment '{display_name}' in workspace {workspace_id} ...")
    result = ensure_environment(manager, display_name=display_name, item_id=item_id)
    environment_id = str(result["id"])
    print(f"Environment {result['action']}: id={environment_id} displayName={result.get('displayName')}")

    print(f"Uploading {wheel_path.name} as a custom library ...")
    manager.upload_library(environment_id, wheel_path)
    print("Upload complete.")

    print("Importing PyPI dependencies as external libraries ...")
    manager.import_public_libraries(environment_id, _build_environment_yml())
    print("External libraries import complete.")

    print("Publishing environment (this can take several minutes) ...")
    published = manager.publish(environment_id)
    print(f"Publish complete. environment_id={environment_id}")
    print(f"Set fabric.topology_pipeline.environment_item_id: \"{environment_id}\" in {config_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
