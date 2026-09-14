#!/usr/bin/env python3
"""Run one guarded fresh AUM Exposure publication and restore its Job."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import signal
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NamedTuple, Protocol

ACTIVE_EXECUTION_STATUSES = frozenset({"pending", "processing", "running", "starting"})
TERMINAL_EXECUTION_STATUSES = frozenset({"cancelled", "failed", "stopped", "succeeded"})
BASELINE_WORKLOAD_PROFILE = "Consumption"
BASELINE_CPU = 4.0
BASELINE_MEMORY = "8Gi"
BASELINE_TIMEOUT = 7_200
DEDICATED_WORKLOAD_PROFILE = "publication-e8"
DEDICATED_CPU = 8.0
DEDICATED_MEMORY = "64Gi"
DEDICATED_TIMEOUT = 14_400
SUPPORTED_TARGET_CONFIGURATIONS = frozenset(
    {
        (
            BASELINE_WORKLOAD_PROFILE,
            BASELINE_CPU,
            BASELINE_MEMORY,
            BASELINE_TIMEOUT,
        ),
        (
            DEDICATED_WORKLOAD_PROFILE,
            DEDICATED_CPU,
            DEDICATED_MEMORY,
            DEDICATED_TIMEOUT,
        ),
    }
)
MUTABLE_UPDATE_PATHS = {
    "workload_profile": "workloadProfileName",
    "cpu": "template.containers[0].resources.cpu",
    "memory": "template.containers[0].resources.memory",
    "timeout": "configuration.replicaTimeout",
    "image": "template.containers[0].image",
}
WORKLOAD_PROFILE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,31}$")
MEMORY_PATTERN = re.compile(r"^[1-9][0-9]*Gi$")
EXPECTED_COMMAND = (
    "python",
    "-m",
    "onboarding.cli",
    "activate",
    "--config",
    "/app/config.yaml",
    "--fabric-config",
    "/app/fabric.config.yaml",
    "--connection-id",
)


class RecoveryError(RuntimeError):
    """Report a fixed, non-sensitive recovery failure."""


class RecoveryOptions(NamedTuple):
    """Governed temporary values and expected persistent Job baseline."""

    image: str
    target_workload_profile: str = BASELINE_WORKLOAD_PROFILE
    target_cpu: float = BASELINE_CPU
    target_timeout: int = BASELINE_TIMEOUT
    target_memory: str = BASELINE_MEMORY
    expected_base_workload_profile: str = BASELINE_WORKLOAD_PROFILE
    expected_base_timeout: int = 3_600
    expected_base_memory: str = BASELINE_MEMORY
    expected_cpu: float = BASELINE_CPU
    expected_connection_id: str = "demo"
    poll_seconds: int = 30
    max_wait_seconds: int = 8_100
    status_retry_attempts: int = 5
    status_retry_initial_seconds: int = 1
    status_retry_max_seconds: int = 30
    stop_wait_seconds: int = 300


class AzureJobClient(Protocol):
    def show_job(self) -> dict[str, Any]: ...

    def list_executions(self) -> list[dict[str, Any]]: ...

    def update_job(
        self,
        *,
        workload_profile: str,
        cpu: float,
        image: str,
        timeout: int,
        memory: str,
    ) -> None: ...

    def start_job(self) -> str: ...

    def show_execution(self, execution_name: str) -> dict[str, Any]: ...

    def stop_execution(self, execution_name: str) -> None: ...


class FacetClient(Protocol):
    def read_overview(
        self,
        *,
        target_kind: str,
        source_family: str,
    ) -> dict[str, Any]: ...

    def read_provenance(
        self,
        *,
        generation: str,
        expected_connection_id: str,
    ) -> dict[str, Any]: ...


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _sanitize(value: object) -> object:
    if isinstance(value, Mapping):
        result = {str(key): _sanitize(child) for key, child in value.items()}
        for key in tuple(result):
            if key.casefold() in {
                "password",
                "secretvalue",
                "token",
                "value",
                "valuefrom",
            }:
                result[key] = _digest(value.get(key))
        return {key: result[key] for key in sorted(result)}
    if isinstance(value, list | tuple):
        return [_sanitize(child) for child in value]
    return value


def normalize_job_config(job: Mapping[str, Any]) -> dict[str, Any]:
    """Select stable semantic Job fields and hash any inline sensitive values."""
    properties = job.get("properties")
    if not isinstance(properties, Mapping):
        raise RecoveryError("Job response has no properties")
    configuration = properties.get("configuration")
    template = properties.get("template")
    if not isinstance(configuration, Mapping) or not isinstance(template, Mapping):
        raise RecoveryError("Job response has an invalid configuration or template")
    containers = template.get("containers")
    if not isinstance(containers, list):
        raise RecoveryError("Job response has invalid containers")
    normalized = {
        "configuration": {
            "triggerType": configuration.get("triggerType"),
            "replicaTimeout": configuration.get("replicaTimeout"),
            "replicaRetryLimit": configuration.get("replicaRetryLimit"),
            "manualTriggerConfig": deepcopy(
                configuration.get("manualTriggerConfig") or {}
            ),
            "registries": deepcopy(configuration.get("registries") or []),
        },
        "environmentId": properties.get("environmentId"),
        "identity": deepcopy(job.get("identity") or {}),
        "template": {
            "containers": [
                {
                    "name": container.get("name"),
                    "image": container.get("image"),
                    "command": deepcopy(container.get("command") or []),
                    "args": deepcopy(container.get("args") or []),
                    "resources": deepcopy(container.get("resources") or {}),
                    "env": deepcopy(container.get("env") or []),
                }
                if isinstance(container, Mapping)
                else container
                for container in containers
            ]
        },
        "workloadProfileName": properties.get("workloadProfileName"),
    }
    sanitized = _sanitize(normalized)
    if not isinstance(sanitized, dict):
        raise RecoveryError("Job configuration could not be normalized")
    return sanitized


def _container(config: Mapping[str, Any]) -> Mapping[str, Any]:
    template = config.get("template")
    containers = template.get("containers") if isinstance(template, Mapping) else None
    if not isinstance(containers, list) or len(containers) != 1:
        raise RecoveryError("publication Job must contain exactly one container")
    container = containers[0]
    if not isinstance(container, Mapping):
        raise RecoveryError("publication Job container is invalid")
    return container


def _configuration(config: Mapping[str, Any]) -> Mapping[str, Any]:
    configuration = config.get("configuration")
    if not isinstance(configuration, Mapping):
        raise RecoveryError("publication Job configuration is invalid")
    return configuration


def _changed_paths(before: object, after: object, path: str = "") -> set[str]:
    if isinstance(before, Mapping) and isinstance(after, Mapping):
        paths: set[str] = set()
        for key in set(before) | set(after):
            child = f"{path}.{key}" if path else str(key)
            paths.update(_changed_paths(before.get(key), after.get(key), child))
        return paths
    if isinstance(before, list) and isinstance(after, list):
        paths = set()
        for index in range(max(len(before), len(after))):
            child = f"{path}[{index}]"
            left = before[index] if index < len(before) else None
            right = after[index] if index < len(after) else None
            paths.update(_changed_paths(left, right, child))
        return paths
    return set() if before == after else {path}


def validate_preflight(config: Mapping[str, Any], options: RecoveryOptions) -> None:
    """Refuse any persistent Job that is not the expected fresh baseline."""
    configuration = _configuration(config)
    container = _container(config)
    resources = container.get("resources")
    manual = configuration.get("manualTriggerConfig")
    command = tuple(container.get("command") or ()) + tuple(container.get("args") or ())

    if str(configuration.get("triggerType") or "").casefold() != "manual":
        raise RecoveryError("publication Job trigger must be Manual")
    if configuration.get("replicaRetryLimit") != 0:
        raise RecoveryError("publication Job retry limit must be zero")
    if not isinstance(manual, Mapping) or (
        manual.get("parallelism") != 1
        or manual.get("replicaCompletionCount") != 1
    ):
        raise RecoveryError("publication Job must run one replica exactly once")
    if command != (*EXPECTED_COMMAND, options.expected_connection_id):
        raise RecoveryError("publication Job must use the exact fresh activation command")
    if "--replay-source-run-id" in command:
        raise RecoveryError("publication Job must use fresh activation, not replay")
    if not isinstance(resources, Mapping):
        raise RecoveryError("publication Job resources are invalid")
    if config.get("workloadProfileName") != options.expected_base_workload_profile:
        raise RecoveryError(
            "publication Job workload profile does not match the governed baseline"
        )
    if float(resources.get("cpu") or 0) != options.expected_cpu:
        raise RecoveryError("publication Job CPU does not match the governed baseline")
    if resources.get("memory") != options.expected_base_memory:
        raise RecoveryError("publication Job baseline memory does not match")
    if configuration.get("replicaTimeout") != options.expected_base_timeout:
        raise RecoveryError("publication Job baseline timeout does not match")
    if not options.image or options.image.casefold().endswith(":latest"):
        raise RecoveryError("recovery image must be an explicit immutable tag or digest")
    if container.get("image") == options.image:
        raise RecoveryError("recovery image must differ from the persistent baseline")
    if not WORKLOAD_PROFILE_PATTERN.fullmatch(options.target_workload_profile):
        raise RecoveryError("target workload profile format is invalid")
    if not MEMORY_PATTERN.fullmatch(options.target_memory):
        raise RecoveryError("target memory must use a whole-number Gi format")
    target_configuration = (
        options.target_workload_profile,
        float(options.target_cpu),
        options.target_memory,
        options.target_timeout,
    )
    if target_configuration not in SUPPORTED_TARGET_CONFIGURATIONS:
        raise RecoveryError(
            "target resources must exactly match the reviewed Consumption or "
            "publication-e8 configuration"
        )
    if (
        options.target_cpu > BASELINE_CPU
        or options.target_memory != BASELINE_MEMORY
        or options.target_timeout > BASELINE_TIMEOUT
    ) and options.target_workload_profile == BASELINE_WORKLOAD_PROFILE:
        raise RecoveryError(
            "resources above the Consumption baseline require an explicit "
            "dedicated workload profile"
        )
    if options.poll_seconds < 1 or options.max_wait_seconds <= options.target_timeout:
        raise RecoveryError("recovery polling bounds are invalid")
    if (
        options.status_retry_attempts < 1
        or options.status_retry_initial_seconds < 1
        or options.status_retry_max_seconds < options.status_retry_initial_seconds
        or options.stop_wait_seconds < options.poll_seconds
    ):
        raise RecoveryError("execution polling retry bounds are invalid")
    if "/aiops-api:" not in options.image and "/aiops-api@sha256:" not in options.image:
        raise RecoveryError("recovery image must target the aiops-api repository")


def _expected_update_paths(
    original: Mapping[str, Any],
    options: RecoveryOptions,
) -> set[str]:
    container = _container(original)
    resources = container.get("resources")
    configuration = _configuration(original)
    if not isinstance(resources, Mapping):
        raise RecoveryError("publication Job resources are invalid")
    requested = {
        "workload_profile": options.target_workload_profile,
        "cpu": options.target_cpu,
        "memory": options.target_memory,
        "timeout": options.target_timeout,
        "image": options.image,
    }
    current = {
        "workload_profile": original.get("workloadProfileName"),
        "cpu": float(resources.get("cpu") or 0),
        "memory": resources.get("memory"),
        "timeout": configuration.get("replicaTimeout"),
        "image": container.get("image"),
    }
    return {
        MUTABLE_UPDATE_PATHS[name]
        for name, value in requested.items()
        if current[name] != value
    }


def _execution_status(execution: Mapping[str, Any]) -> str:
    properties = execution.get("properties")
    status = properties.get("status") if isinstance(properties, Mapping) else None
    return str(status or execution.get("status") or "").strip()


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    temporary.replace(path)


def _data(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise RecoveryError("Exposure validation response has no data")
    return data


def _contains_unavailable(value: object) -> bool:
    if isinstance(value, Mapping):
        return any(_contains_unavailable(child) for child in value.values())
    if isinstance(value, list | tuple):
        return any(_contains_unavailable(child) for child in value)
    return str(value or "").strip().casefold() == "unavailable"


def validate_facet_payloads(
    server_payload: Mapping[str, Any],
    container_payload: Mapping[str, Any],
    provenance_payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Require one healthy generation and exact active AUM fact provenance."""
    server = _data(server_payload)
    container = _data(container_payload)
    provenance = _data(provenance_payload)
    server_count = int(server.get("total_count") or 0)
    container_count = int(container.get("total_count") or 0)
    if server_count < 1:
        raise RecoveryError("server/AUM facet is empty")
    if _contains_unavailable(server.get("completeness")):
        raise RecoveryError("server/AUM completeness is unavailable")
    if container_count < 1:
        raise RecoveryError("container/Defender facet is empty")
    server_generation = str(server.get("generation") or "")
    container_generation = str(container.get("generation") or "")
    if not server_generation.startswith("exposure-gold-"):
        raise RecoveryError("Exposure validation returned an invalid generation")
    if server_generation != container_generation:
        raise RecoveryError("Exposure facets resolved different generations")
    if str(provenance.get("generation") or "") != server_generation:
        raise RecoveryError("Exposure provenance resolved a different generation")
    active_fact_count = int(provenance.get("active_fact_count") or 0)
    expected_connection_fact_count = int(
        provenance.get("expected_connection_fact_count") or 0
    )
    legacy_connection_fact_count = int(
        provenance.get("legacy_connection_fact_count") or 0
    )
    unexpected_connection_fact_count = int(
        provenance.get("unexpected_connection_fact_count") or 0
    )
    if active_fact_count < 1:
        raise RecoveryError("active server/AUM provenance evidence is empty")
    if legacy_connection_fact_count:
        raise RecoveryError("active server/AUM facts include legacy connection provenance")
    if unexpected_connection_fact_count:
        raise RecoveryError(
            "active server/AUM facts include unexpected connection provenance"
        )
    if expected_connection_fact_count != active_fact_count:
        raise RecoveryError(
            "active server/AUM facts do not all belong to the expected connection"
        )
    return {
        "generation": server_generation,
        "facet_counts": {
            "server_aum": server_count,
            "container_defender": container_count,
        },
        "provenance": {
            "active_server_aum_facts": active_fact_count,
            "expected_connection_facts": expected_connection_fact_count,
            "legacy_connection_facts": legacy_connection_fact_count,
            "unexpected_connection_facts": unexpected_connection_fact_count,
        },
    }


def _require_no_non_terminal_executions(azure: AzureJobClient) -> None:
    non_terminal = [
        execution
        for execution in azure.list_executions()
        if _execution_status(execution).casefold()
        not in TERMINAL_EXECUTION_STATUSES
    ]
    if non_terminal:
        raise RecoveryError("publication Job has an active or unknown execution")


def _restore(
    azure: AzureJobClient,
    original: Mapping[str, Any],
    evidence_dir: Path,
) -> None:
    _require_no_non_terminal_executions(azure)
    container = _container(original)
    resources = container.get("resources")
    configuration = _configuration(original)
    if not isinstance(resources, Mapping):
        raise RecoveryError("snapshot resources are invalid")
    azure.update_job(
        workload_profile=str(original.get("workloadProfileName") or ""),
        cpu=float(resources.get("cpu") or 0),
        image=str(container.get("image") or ""),
        timeout=int(configuration.get("replicaTimeout") or 0),
        memory=str(resources.get("memory") or ""),
    )
    restored = normalize_job_config(azure.show_job())
    _write_json(evidence_dir / "restored.json", restored)
    if restored != original:
        raise RecoveryError("persistent Job restoration did not match the snapshot")


def _show_execution_with_retry(
    azure: AzureJobClient,
    execution_name: str,
    options: RecoveryOptions,
    *,
    sleep: Callable[[float], None],
) -> dict[str, Any]:
    delay = options.status_retry_initial_seconds
    for attempt in range(options.status_retry_attempts):
        try:
            return azure.show_execution(execution_name)
        except RecoveryError as exc:
            if attempt + 1 >= options.status_retry_attempts:
                raise RecoveryError(
                    "Azure CLI execution status remained unavailable after "
                    "bounded retries"
                ) from exc
            sleep(delay)
            delay = min(delay * 2, options.status_retry_max_seconds)
    raise AssertionError("unreachable")


def _wait_for_terminal(
    azure: AzureJobClient,
    execution_name: str,
    options: RecoveryOptions,
    *,
    deadline: float,
    sleep: Callable[[float], None],
    clock: Callable[[], float],
    timeout_message: str,
) -> str:
    while True:
        execution = _show_execution_with_retry(
            azure,
            execution_name,
            options,
            sleep=sleep,
        )
        status = _execution_status(execution)
        if status.casefold() in TERMINAL_EXECUTION_STATUSES:
            return status
        if clock() >= deadline:
            raise RecoveryError(timeout_message)
        sleep(options.poll_seconds)


def _stop_and_confirm_terminal(
    azure: AzureJobClient,
    execution_name: str,
    options: RecoveryOptions,
    *,
    sleep: Callable[[float], None],
    clock: Callable[[], float],
) -> str:
    try:
        azure.stop_execution(execution_name)
        return _wait_for_terminal(
            azure,
            execution_name,
            options,
            deadline=clock() + options.stop_wait_seconds,
            sleep=sleep,
            clock=clock,
            timeout_message=(
                "stopped publication could not be confirmed terminal; "
                "the Job snapshot was not restored"
            ),
        )
    except RecoveryError as exc:
        if "not restored" in str(exc):
            raise
        raise RecoveryError(
            "publication could not be stopped and confirmed terminal; "
            "the Job snapshot was not restored"
        ) from exc


def run_recovery(
    options: RecoveryOptions,
    *,
    azure: AzureJobClient,
    facets: FacetClient,
    evidence_dir: Path,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Execute the guarded mutation, one start, restoration, and facet checks."""
    original = normalize_job_config(azure.show_job())
    validate_preflight(original, options)
    _require_no_non_terminal_executions(azure)
    _write_json(evidence_dir / "pre-update.json", original)

    mutation_attempted = False
    start_attempted = False
    terminal_confirmed = False
    execution_name = ""
    try:
        mutation_attempted = True
        azure.update_job(
            workload_profile=options.target_workload_profile,
            cpu=options.target_cpu,
            image=options.image,
            timeout=options.target_timeout,
            memory=options.target_memory,
        )
        updated = normalize_job_config(azure.show_job())
        _write_json(evidence_dir / "post-update.json", updated)
        changed = _changed_paths(original, updated)
        if changed != _expected_update_paths(original, options):
            raise RecoveryError("unexpected Job configuration drift after update")
        container = _container(updated)
        resources = container.get("resources")
        configuration = _configuration(updated)
        if not isinstance(resources, Mapping) or (
            updated.get("workloadProfileName") != options.target_workload_profile
            or float(resources.get("cpu") or 0) != options.target_cpu
            or container.get("image") != options.image
            or resources.get("memory") != options.target_memory
            or configuration.get("replicaTimeout") != options.target_timeout
        ):
            raise RecoveryError("Job update did not apply the governed target values")

        start_attempted = True
        execution_name = azure.start_job()
        if not execution_name:
            raise RecoveryError(
                "Job start returned no execution identity; the Job snapshot was "
                "not restored because execution state is unknown"
            )
        try:
            status = _wait_for_terminal(
                azure,
                execution_name,
                options,
                deadline=clock() + options.max_wait_seconds,
                sleep=sleep,
                clock=clock,
                timeout_message=(
                    "publication did not reach a terminal status in time"
                ),
            )
            terminal_confirmed = True
        except BaseException:
            status = _stop_and_confirm_terminal(
                azure,
                execution_name,
                options,
                sleep=sleep,
                clock=clock,
            )
            terminal_confirmed = True
            raise
        if status.casefold() != "succeeded":
            raise RecoveryError(f"publication reached terminal status {status}")
    finally:
        if mutation_attempted and (not start_attempted or terminal_confirmed):
            _restore(azure, original, evidence_dir)

    server = facets.read_overview(target_kind="server", source_family="aum")
    container = facets.read_overview(
        target_kind="container_image",
        source_family="defender_image",
    )
    server_generation = str(_data(server).get("generation") or "")
    provenance = facets.read_provenance(
        generation=server_generation,
        expected_connection_id=options.expected_connection_id,
    )
    validation = validate_facet_payloads(server, container, provenance)
    result = {
        "status": "succeeded",
        "execution_name": execution_name,
        **validation,
        "job_restored": True,
    }
    _write_json(evidence_dir / "result.json", result)
    return result


class AzCliJobClient:
    """Invoke only the guarded Azure CLI operations permitted by this workflow."""

    def __init__(self, *, subscription: str, resource_group: str, job_name: str) -> None:
        self._scope = [
            "--subscription",
            subscription,
            "--resource-group",
            resource_group,
        ]
        self._job_name = job_name

    def _json(self, arguments: Sequence[str]) -> Any:
        try:
            completed = subprocess.run(
                ["az", *arguments, "--only-show-errors", "--output", "json"],
                check=True,
                capture_output=True,
                text=True,
            )
            return json.loads(completed.stdout)
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            raise RecoveryError("Azure CLI operation failed") from exc

    def show_job(self) -> dict[str, Any]:
        value = self._json(
            ["containerapp", "job", "show", "--name", self._job_name, *self._scope]
        )
        if not isinstance(value, dict):
            raise RecoveryError("Azure CLI returned an invalid Job")
        return value

    def list_executions(self) -> list[dict[str, Any]]:
        value = self._json(
            [
                "containerapp",
                "job",
                "execution",
                "list",
                "--name",
                self._job_name,
                *self._scope,
            ]
        )
        if not isinstance(value, list):
            raise RecoveryError("Azure CLI returned an invalid execution list")
        return [item for item in value if isinstance(item, dict)]

    def update_job(
        self,
        *,
        workload_profile: str,
        cpu: float,
        image: str,
        timeout: int,
        memory: str,
    ) -> None:
        subscription = self._scope[1]
        resource_group = self._scope[3]
        resource_id = (
            f"/subscriptions/{subscription}/resourceGroups/{resource_group}"
            "/providers/Microsoft.App/jobs/"
            f"{self._job_name}"
        )
        self._json(
            [
                "resource",
                "update",
                "--ids",
                resource_id,
                "--api-version",
                "2024-03-01",
                "--set",
                f"properties.workloadProfileName={workload_profile}",
                f"properties.template.containers[0].image={image}",
                f"properties.configuration.replicaTimeout={timeout}",
                f"properties.template.containers[0].resources.cpu={cpu:g}",
                f"properties.template.containers[0].resources.memory={memory}",
            ]
        )

    def start_job(self) -> str:
        value = self._json(
            ["containerapp", "job", "start", "--name", self._job_name, *self._scope]
        )
        if not isinstance(value, Mapping):
            return ""
        return str(value.get("name") or "")

    def show_execution(self, execution_name: str) -> dict[str, Any]:
        value = self._json(
            [
                "containerapp",
                "job",
                "execution",
                "show",
                "--name",
                self._job_name,
                *self._scope,
                "--job-execution-name",
                execution_name,
            ]
        )
        if not isinstance(value, dict):
            raise RecoveryError("Azure CLI returned an invalid execution")
        return value

    def stop_execution(self, execution_name: str) -> None:
        self._json(
            [
                "containerapp",
                "job",
                "stop",
                "--name",
                self._job_name,
                *self._scope,
                "--job-execution-name",
                execution_name,
            ]
        )


class ExposureApiFacetClient:
    def __init__(
        self,
        *,
        base_url: str,
        subscription_scope: str,
        token_env: str,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._subscription_scope = subscription_scope
        self._token_env = token_env

    def read_overview(self, *, target_kind: str, source_family: str) -> dict[str, Any]:
        token = os.environ.get(self._token_env, "").strip()
        if not token:
            raise RecoveryError("Exposure API token environment variable is empty")
        query = urllib.parse.urlencode(
            {
                "subscription": self._subscription_scope,
                "target_kind": target_kind,
                "source_family": source_family,
            }
        )
        request = urllib.request.Request(
            f"{self._base_url}/api/v1/vulnerabilities/exposure/overview?{query}",
            headers={"Authorization": f"Bearer {token}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                value = json.loads(response.read())
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise RecoveryError("Exposure API validation failed") from exc
        if not isinstance(value, dict):
            raise RecoveryError("Exposure API returned an invalid response")
        return value

    def read_provenance(
        self,
        *,
        generation: str,
        expected_connection_id: str,
    ) -> dict[str, Any]:
        token = os.environ.get(self._token_env, "").strip()
        if not token:
            raise RecoveryError("Exposure API token environment variable is empty")
        query = urllib.parse.urlencode(
            {
                "subscription": self._subscription_scope,
                "generation": generation,
                "connection_id": expected_connection_id,
            }
        )
        request = urllib.request.Request(
            (
                f"{self._base_url}/api/v1/vulnerabilities/exposure/"
                f"provenance-evidence?{query}"
            ),
            headers={"Authorization": "Bearer " + token},
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                value = json.loads(response.read())
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise RecoveryError("Exposure API validation failed") from exc
        if not isinstance(value, dict):
            raise RecoveryError("Exposure API returned an invalid response")
        return value


def restore_snapshot(azure: AzureJobClient, snapshot: Path, evidence_dir: Path) -> None:
    value = json.loads(snapshot.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RecoveryError("restore snapshot is invalid")
    _restore(azure, value, evidence_dir)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subscription", default=os.environ.get("AZURE_SUBSCRIPTION_ID", ""))
    parser.add_argument("--resource-group", default="aiops-dev-rg")
    parser.add_argument("--job-name", default="aiops-dev-exposure-publication")
    parser.add_argument("--image", default="")
    parser.add_argument(
        "--target-workload-profile",
        default=BASELINE_WORKLOAD_PROFILE,
    )
    parser.add_argument("--target-cpu", type=float, default=BASELINE_CPU)
    parser.add_argument("--target-memory", default=BASELINE_MEMORY)
    parser.add_argument("--target-timeout", type=int, default=BASELINE_TIMEOUT)
    parser.add_argument("--api-base-url", default="")
    parser.add_argument("--subscription-scope", default="")
    parser.add_argument("--token-env", default="AIOPS_API_TOKEN")
    parser.add_argument("--evidence-dir", default="")
    parser.add_argument("--restore-snapshot", default="")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.subscription:
        raise RecoveryError("subscription is required")
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    evidence_dir = Path(
        args.evidence_dir
        or f".planning/evidence/aum-publication-recovery/{timestamp}"
    )
    azure = AzCliJobClient(
        subscription=args.subscription,
        resource_group=args.resource_group,
        job_name=args.job_name,
    )
    if args.restore_snapshot:
        restore_snapshot(azure, Path(args.restore_snapshot), evidence_dir)
        print(json.dumps({"status": "restored", "job_restored": True}, sort_keys=True))
        return 0
    if not args.image or not args.api_base_url or not args.subscription_scope:
        raise RecoveryError(
            "image, api-base-url, and subscription-scope are required for recovery"
        )
    options = RecoveryOptions(
        image=args.image,
        target_workload_profile=args.target_workload_profile,
        target_cpu=args.target_cpu,
        target_memory=args.target_memory,
        target_timeout=args.target_timeout,
        max_wait_seconds=args.target_timeout + 900,
    )
    facets = ExposureApiFacetClient(
        base_url=args.api_base_url,
        subscription_scope=args.subscription_scope,
        token_env=args.token_env,
    )
    previous_sigterm = signal.getsignal(signal.SIGTERM)
    signal.signal(
        signal.SIGTERM,
        lambda _signum, _frame: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    try:
        result = run_recovery(
            options,
            azure=azure,
            facets=facets,
            evidence_dir=evidence_dir,
        )
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyboardInterrupt, RecoveryError) as exc:
        message = str(exc) if isinstance(exc, RecoveryError) else "recovery interrupted"
        print(json.dumps({"status": "failed", "safe_error": message}), flush=True)
        raise SystemExit(1) from exc