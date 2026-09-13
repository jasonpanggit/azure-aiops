#!/usr/bin/env python3
"""Render sourceable non-secret Copilot provider env from Terraform output JSON."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import urllib.parse
from pathlib import Path
from typing import Any

EXIT_INVALID = 2
EXIT_BLOCKED = 3
OUTPUT_NAME = "copilot_provider_environment"
ENV_KEYS = (
    "FOUNDRY_PROJECT_ENDPOINT",
    "OPERATIONS_MCP_SERVER_URL",
    "AZURE_MCP_SERVER_URL",
    "MCP_APIM_AUDIENCE",
    "FOUNDRY_CANDIDATE_MAPPING",
    "FOUNDRY_OPERATIONS_MCP_CONNECTION_ID",
    "FOUNDRY_AZURE_MCP_CONNECTION_ID",
    "AIOPS_COPILOT_ROLLOUT_MODE",
    "AIOPS_COPILOT_CANARY_PERCENTAGE",
    "AIOPS_COPILOT_ROLLBACK_MODE",
)
ROLLOUT_MODES = frozenset({"compatibility", "shadow", "canary", "default"})
CONNECTION_LABELS = ("operations-mcp", "azure-mcp")
CONNECTION_ID_PATTERN = re.compile(
    r"^/subscriptions/[^/]+/resourcegroups/[^/]+/providers/"
    r"microsoft\.cognitiveservices/accounts/[^/]+/projects/[^/]+/"
    r"connections/[^/]+$",
    re.IGNORECASE,
)


class BlockedConfiguration(ValueError):
    """Required externally produced evidence is absent."""


def _terraform_value(payload: dict[str, Any]) -> dict[str, str]:
    output = payload.get(OUTPUT_NAME)
    if not isinstance(output, dict) or not isinstance(output.get("value"), dict):
        raise BlockedConfiguration(OUTPUT_NAME)
    values = output["value"]
    missing = [
        key
        for key in ENV_KEYS
        if key not in values or not isinstance(values[key], str) or not values[key].strip()
    ]
    if missing:
        raise BlockedConfiguration(",".join(missing))
    return {key: values[key].strip() for key in ENV_KEYS}


def _validate_https_url(name: str, value: str, *, expected_path: str) -> None:
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError(name) from exc
    if (
        parsed.scheme.casefold() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/") != expected_path
    ):
        raise ValueError(name)


def _normalize_connection_id(name: str, value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError(name)
    normalized = value.strip().rstrip("/")
    if not CONNECTION_ID_PATTERN.fullmatch(normalized):
        raise ValueError(name)
    return normalized


def _validate_candidate_mapping(values: dict[str, str]) -> None:
    path = Path(values["FOUNDRY_CANDIDATE_MAPPING"])
    if not path.is_absolute() or not path.is_file():
        raise BlockedConfiguration("FOUNDRY_CANDIDATE_MAPPING")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("FOUNDRY_CANDIDATE_MAPPING") from exc
    if not isinstance(payload, dict):
        raise TypeError("FOUNDRY_CANDIDATE_MAPPING")
    agents = payload.get("agents")
    coordinator = payload.get("coordinator")
    connections = payload.get("connections")
    if not isinstance(agents, dict) or not agents or not isinstance(coordinator, dict):
        raise ValueError("FOUNDRY_CANDIDATE_MAPPING")
    if not all(
        isinstance(entry, dict)
        and isinstance(entry.get("agent_name"), str)
        and bool(entry["agent_name"].strip())
        and isinstance(entry.get("provider_version_id"), str)
        and bool(entry["provider_version_id"].strip())
        for entry in [*agents.values(), coordinator]
    ):
        raise ValueError("FOUNDRY_CANDIDATE_MAPPING")
    if not isinstance(connections, dict) or set(connections) != set(CONNECTION_LABELS):
        raise ValueError("FOUNDRY_CANDIDATE_MAPPING")

    expected = {
        "operations-mcp": values["FOUNDRY_OPERATIONS_MCP_CONNECTION_ID"],
        "azure-mcp": values["FOUNDRY_AZURE_MCP_CONNECTION_ID"],
    }
    normalized: dict[str, str] = {}
    for label in CONNECTION_LABELS:
        entry = connections[label]
        if not isinstance(entry, dict):
            raise TypeError("FOUNDRY_CANDIDATE_MAPPING")
        normalized[label] = _normalize_connection_id(
            "FOUNDRY_CANDIDATE_MAPPING",
            entry.get("project_connection_id"),
        )
        if normalized[label].casefold() != expected[label].rstrip("/").casefold():
            raise ValueError("FOUNDRY_CANDIDATE_MAPPING")
    if len({value.casefold() for value in normalized.values()}) != len(normalized):
        raise ValueError("FOUNDRY_CANDIDATE_MAPPING")


def _load_payload(path: Path | None, terraform_dir: Path | None) -> dict[str, Any]:
    if path is not None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise BlockedConfiguration("terraform_output") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("terraform_output") from exc
    else:
        assert terraform_dir is not None
        try:
            completed = subprocess.run(
                ["terraform", f"-chdir={terraform_dir}", "output", "-json"],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError as exc:
            raise BlockedConfiguration("terraform_output") from exc
        if completed.returncode != 0:
            raise BlockedConfiguration("terraform_output")
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise ValueError("terraform_output") from exc
    if not isinstance(payload, dict):
        raise TypeError("terraform_output")
    return payload


def load_environment(
    *,
    path: Path | None = None,
    terraform_dir: Path | None = None,
) -> dict[str, str]:
    """Load and validate the exact allowlisted Terraform output."""

    payload = _load_payload(path, terraform_dir)
    try:
        values = _terraform_value(payload)
    finally:
        payload.clear()

    _validate_https_url(
        "FOUNDRY_PROJECT_ENDPOINT",
        values["FOUNDRY_PROJECT_ENDPOINT"],
        expected_path=urllib.parse.urlsplit(
            values["FOUNDRY_PROJECT_ENDPOINT"]
        ).path.rstrip("/"),
    )
    foundry_path = urllib.parse.urlsplit(values["FOUNDRY_PROJECT_ENDPOINT"]).path
    if not re.fullmatch(r"/api/projects/[^/]+/?", foundry_path):
        raise ValueError("FOUNDRY_PROJECT_ENDPOINT")
    _validate_https_url(
        "OPERATIONS_MCP_SERVER_URL",
        values["OPERATIONS_MCP_SERVER_URL"],
        expected_path="/operations-mcp",
    )
    _validate_https_url(
        "AZURE_MCP_SERVER_URL",
        values["AZURE_MCP_SERVER_URL"],
        expected_path="/azure-mcp",
    )
    operations_host = (
        urllib.parse.urlsplit(values["OPERATIONS_MCP_SERVER_URL"]).hostname or ""
    ).casefold()
    azure_host = (
        urllib.parse.urlsplit(values["AZURE_MCP_SERVER_URL"]).hostname or ""
    ).casefold()
    if operations_host != azure_host:
        raise ValueError("AZURE_MCP_SERVER_URL")

    audience = urllib.parse.urlsplit(values["MCP_APIM_AUDIENCE"])
    if (
        audience.scheme.casefold() not in {"api", "https"}
        or not audience.netloc
        or audience.username is not None
        or audience.password is not None
        or audience.query
        or audience.fragment
    ):
        raise ValueError("MCP_APIM_AUDIENCE")

    mode = values["AIOPS_COPILOT_ROLLOUT_MODE"].casefold()
    if mode not in ROLLOUT_MODES:
        raise ValueError("AIOPS_COPILOT_ROLLOUT_MODE")
    percentage = values["AIOPS_COPILOT_CANARY_PERCENTAGE"]
    if not percentage.isdecimal() or not 0 <= int(percentage) <= 100:
        raise ValueError("AIOPS_COPILOT_CANARY_PERCENTAGE")
    if values["AIOPS_COPILOT_ROLLBACK_MODE"].casefold() != "compatibility":
        raise ValueError("AIOPS_COPILOT_ROLLBACK_MODE")

    operation_connection = _normalize_connection_id(
        "FOUNDRY_OPERATIONS_MCP_CONNECTION_ID",
        values["FOUNDRY_OPERATIONS_MCP_CONNECTION_ID"],
    )
    azure_connection = _normalize_connection_id(
        "FOUNDRY_AZURE_MCP_CONNECTION_ID",
        values["FOUNDRY_AZURE_MCP_CONNECTION_ID"],
    )
    if operation_connection.casefold() == azure_connection.casefold():
        raise ValueError("FOUNDRY_AZURE_MCP_CONNECTION_ID")

    _validate_candidate_mapping(values)
    return values


def write_environment(path: Path, values: dict[str, str]) -> None:
    """Atomically write an owner-readable shell fragment."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            os.chmod(temporary_path, 0o600)
            for key in ENV_KEYS:
                handle.write(f"export {key}={shlex.quote(values[key])}\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        os.chmod(path, 0o600)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--terraform-output", type=Path)
    source.add_argument("--terraform-dir", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        values = load_environment(
            path=args.terraform_output,
            terraform_dir=args.terraform_dir,
        )
        write_environment(args.output, values)
    except BlockedConfiguration as exc:
        print(f"BLOCKED: missing authoritative {exc}", file=sys.stderr)
        return EXIT_BLOCKED
    except (OSError, TypeError, ValueError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return EXIT_INVALID
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
