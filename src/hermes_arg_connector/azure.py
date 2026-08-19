from __future__ import annotations

import json
import subprocess  # nosec B404
from dataclasses import dataclass
from typing import Protocol

from .queries import QuerySpec


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class CommandRunner(Protocol):
    def run(self, command: list[str], timeout: int) -> CommandResult: ...


class SubprocessRunner:
    def run(self, command: list[str], timeout: int) -> CommandResult:
        # Safe: command is an internal argv list, never shell text.
        completed = subprocess.run(  # nosec B603
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return CommandResult(completed.returncode, completed.stdout, completed.stderr)


class AzureMcpClient:
    """Thin process adapter over the official Azure MCP CLI."""

    def __init__(
        self,
        runner: CommandRunner | None = None,
        command_prefix: tuple[str, ...] = ("azmcp",),
        timeout: int = 60,
    ) -> None:
        self.runner = runner or SubprocessRunner()
        if not command_prefix:
            raise ValueError("Azure MCP command_prefix cannot be empty")
        self.command_prefix = command_prefix
        self.timeout = timeout

    def list_subscriptions(self, tenant_id: str = "") -> list[dict]:
        command = [*self.command_prefix, "subscription", "list"]
        if tenant_id:
            command.extend(["--tenant", tenant_id])
        result = self.runner.run(command, self.timeout)
        if result.returncode:
            raise RuntimeError(f"Azure MCP subscription discovery failed: {result.stderr.strip()}")
        payload = _load_json(result.stdout, "Azure MCP")
        if int(payload.get("status", 500)) >= 400:
            raise RuntimeError(f"Azure MCP subscription discovery failed: {payload.get('message', payload)}")
        rows = payload.get("results") or []
        if isinstance(rows, dict):
            rows = rows.get("subscriptions") or []
        if not isinstance(rows, list):
            raise TypeError("Azure MCP returned an invalid subscription result")
        return rows


class AzureCliArgClient:
    """ARG query fallback because Azure MCP has no arbitrary ARG query tool."""

    def __init__(
        self,
        runner: CommandRunner | None = None,
        page_size: int = 1000,
        max_pages: int = 1000,
        timeout: int = 60,
    ) -> None:
        self.runner = runner or SubprocessRunner()
        self.page_size = page_size
        self.max_pages = max_pages
        self.timeout = timeout

    def query(self, spec: QuerySpec, scope_ids: list[str]) -> list[dict]:
        rows: list[dict] = []
        continuation_token: str | None = None
        for _ in range(self.max_pages):
            command = [
                "az",
                "graph",
                "query",
                "--graph-query",
                spec.query,
                "--first",
                str(self.page_size),
                "--only-show-errors",
                "--output",
                "json",
            ]
            if scope_ids:
                scope_option = (
                    "--management-groups"
                    if spec.scope == "management_groups"
                    else "--subscriptions"
                )
                command.extend([scope_option, *scope_ids])
            if continuation_token:
                command.extend(["--skip-token", continuation_token])
            result = self.runner.run(command, self.timeout)
            if result.returncode:
                detail = result.stderr.strip() or result.stdout.strip() or "unknown Azure CLI error"
                raise RuntimeError(f"ARG query '{spec.name}' failed: {detail}")
            payload = _load_json(result.stdout, f"ARG query {spec.name}")
            page = payload.get("data") if isinstance(payload, dict) else payload
            if not isinstance(page, list):
                raise TypeError(f"ARG query '{spec.name}' returned an invalid page")
            rows.extend(item for item in page if isinstance(item, dict))
            raw_token = (
                (payload or {}).get("skip_token")
                or (payload or {}).get("skipToken")
                or (payload or {}).get("$skipToken")
            )
            continuation_token = str(raw_token) if raw_token else None
            if not continuation_token:
                return rows
        raise RuntimeError(f"ARG query '{spec.name}' exceeded max_pages={self.max_pages}")


def _load_json(text: str, source: str) -> dict:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{source} returned invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise TypeError(f"{source} returned a non-object payload")
    return payload
