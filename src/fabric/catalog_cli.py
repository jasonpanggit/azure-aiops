"""Read-only, finite Catalog metadata qualification with configured identity."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from uuid import UUID

import httpx
import yaml
from azure.core.exceptions import AzureError

from .auth import build_credential
from .catalog_source import FabricCatalogSource
from .config import FabricRuntimeConfig
from .fabric_client import FabricClient


def main(argv: Sequence[str] | None = None) -> int:
    """Print verified advisory evidence or a sanitized nonzero failure report.

    Workspace and identity come only from the existing runtime configuration.
    No command-line credential, workspace override or publication option exists.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", default=os.environ.get("AIOPS_FABRIC_CONFIG") or "fabric.config.yaml",
    )
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--max-pages", type=int, default=10)
    parser.add_argument("--max-items", type=int, default=1000)
    args = parser.parse_args(argv)
    stage = "configuration"
    try:
        config = FabricRuntimeConfig.load(args.config)
        workspace_id = str(UUID(config.workspace_id))
        for value in (args.page_size, args.max_pages, args.max_items):
            if value < 1:
                raise ValueError("Catalog bounds must be positive")
        if args.page_size > 1000:
            raise ValueError("Catalog page size exceeds the service limit")
        stage = "authentication"
        with build_credential(config.auth) as credential, httpx.Client(timeout=60) as http:
            source = FabricCatalogSource(
                FabricClient(credential, http_client=http),
                workspace_id=workspace_id,
                page_size=args.page_size,
                max_pages=args.max_pages,
                max_items=args.max_items,
            )
            stage = "catalog_verification"
            evidence = source.fetch_verified().to_dict()
        report = {
            "status": "advisory_metadata_verified",
            "authentication_mode": config.auth.mode,
            "evidence": evidence,
        }
        print(json.dumps(report, sort_keys=True))
        return 0
    except httpx.HTTPStatusError as exc:
        print(
            json.dumps({
                "status": "failed", "failure_stage": stage,
                "http_status": exc.response.status_code,
            }),
            file=sys.stderr,
        )
        return 1
    except (AzureError, httpx.HTTPError, OSError, ValueError, TypeError, yaml.YAMLError):
        print(
            json.dumps({"status": "failed", "failure_stage": stage}),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
