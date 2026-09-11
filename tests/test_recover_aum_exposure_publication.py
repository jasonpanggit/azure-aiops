from __future__ import annotations

import importlib.util
import json
import subprocess
from copy import deepcopy
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


def _load_module() -> ModuleType:
    path = (
        Path(__file__).parents[1]
        / "scripts"
        / "recover_aum_exposure_publication.py"
    )
    spec = importlib.util.spec_from_file_location(
        "recover_aum_exposure_publication",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _job() -> dict[str, Any]:
    return {
        "id": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.App/jobs/job",
        "name": "job",
        "properties": {
            "environmentId": "/environments/cae",
            "workloadProfileName": "Consumption",
            "configuration": {
                "triggerType": "Manual",
                "replicaTimeout": 3_600,
                "replicaRetryLimit": 0,
                "manualTriggerConfig": {
                    "parallelism": 1,
                    "replicaCompletionCount": 1,
                },
                "registries": [
                    {
                        "server": "registry.azurecr.io",
                        "identity": "/identities/apps",
                    }
                ],
            },
            "template": {
                "containers": [
                    {
                        "name": "activation",
                        "image": "registry.azurecr.io/aiops-api:old",
                        "command": ["python"],
                        "args": [
                            "-m",
                            "onboarding.cli",
                            "activate",
                            "--config",
                            "/app/config.yaml",
                            "--fabric-config",
                            "/app/fabric.config.yaml",
                            "--connection-id",
                            "demo",
                        ],
                        "resources": {"cpu": 4.0, "memory": "8Gi"},
                        "env": [
                            {"name": "AIOPS_HOME", "value": "abfss://root"},
                            {"name": "API_TOKEN", "secretRef": "api-token"},
                        ],
                    }
                ]
            },
        },
        "identity": {"type": "UserAssigned", "userAssignedIdentities": {}},
        "systemData": {"lastModifiedAt": "2026-09-11T00:00:00Z"},
    }


def _facet_payload(
    *,
    generation: str,
    total_count: int,
    completeness: str = "complete",
) -> dict[str, Any]:
    return {
        "data": {
            "generation": generation,
            "total_count": total_count,
            "completeness": {"state": completeness},
        }
    }


class FakeAzure:
    def __init__(
        self,
        *,
        execution_statuses: list[str] | None = None,
        existing_executions: list[dict[str, Any]] | None = None,
        drift_after_update: bool = False,
    ) -> None:
        self.job = _job()
        self.original = deepcopy(self.job)
        self.execution_statuses = iter(execution_statuses or ["Succeeded"])
        self.existing_executions = existing_executions or []
        self.drift_after_update = drift_after_update
        self.start_count = 0
        self.update_calls: list[tuple[str, int, str]] = []

    def show_job(self) -> dict[str, Any]:
        return deepcopy(self.job)

    def list_executions(self) -> list[dict[str, Any]]:
        return deepcopy(self.existing_executions)

    def update_job(self, *, image: str, timeout: int, memory: str) -> None:
        self.update_calls.append((image, timeout, memory))
        container = self.job["properties"]["template"]["containers"][0]
        container["image"] = image
        container["resources"]["memory"] = memory
        self.job["properties"]["configuration"]["replicaTimeout"] = timeout
        if self.drift_after_update and len(self.update_calls) == 1:
            self.job["properties"]["configuration"]["replicaRetryLimit"] = 1
        if len(self.update_calls) > 1:
            self.job = deepcopy(self.original)

    def start_job(self) -> str:
        self.start_count += 1
        return "job-execution-1"

    def show_execution(self, execution_name: str) -> dict[str, Any]:
        assert execution_name == "job-execution-1"
        return {"name": execution_name, "properties": {"status": next(self.execution_statuses)}}


class FakeFacets:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def read_overview(self, *, target_kind: str, source_family: str) -> dict[str, Any]:
        self.calls.append((target_kind, source_family))
        return _facet_payload(
            generation="exposure-gold-fresh",
            total_count=11 if target_kind == "server" else 77_857,
        )


def _options(module: ModuleType) -> Any:
    return module.RecoveryOptions(
        image="registry.azurecr.io/aiops-api:fresh-byte-bound",
        target_timeout=7_200,
        target_memory="8Gi",
        expected_base_timeout=3_600,
        expected_base_memory="8Gi",
        expected_cpu=4.0,
        expected_connection_id="demo",
        poll_seconds=1,
        max_wait_seconds=7_500,
    )


def test_recovery_updates_only_governed_fields_starts_once_restores_and_validates(
    tmp_path: Path,
) -> None:
    module = _load_module()
    azure = FakeAzure(execution_statuses=["Running", "Succeeded"])
    facets = FakeFacets()

    result = module.run_recovery(
        _options(module),
        azure=azure,
        facets=facets,
        evidence_dir=tmp_path,
        sleep=lambda _seconds: None,
    )

    assert azure.start_count == 1
    assert azure.update_calls == [
        ("registry.azurecr.io/aiops-api:fresh-byte-bound", 7_200, "8Gi"),
        ("registry.azurecr.io/aiops-api:old", 3_600, "8Gi"),
    ]
    assert module.normalize_job_config(azure.show_job()) == module.normalize_job_config(
        azure.original
    )
    assert facets.calls == [
        ("server", "aum"),
        ("container_image", "defender_image"),
    ]
    assert result["status"] == "succeeded"
    assert result["generation"] == "exposure-gold-fresh"
    assert result["facet_counts"] == {"server_aum": 11, "container_defender": 77_857}
    assert json.loads((tmp_path / "result.json").read_text()) == result


def test_terminal_failure_restores_without_validation(tmp_path: Path) -> None:
    module = _load_module()
    azure = FakeAzure(execution_statuses=["Running", "Failed"])
    facets = FakeFacets()

    with pytest.raises(module.RecoveryError, match="terminal status Failed"):
        module.run_recovery(
            _options(module),
            azure=azure,
            facets=facets,
            evidence_dir=tmp_path,
            sleep=lambda _seconds: None,
        )

    assert azure.start_count == 1
    assert len(azure.update_calls) == 2
    assert facets.calls == []
    assert module.normalize_job_config(azure.show_job()) == module.normalize_job_config(
        azure.original
    )


def test_unexpected_update_drift_blocks_start_and_restores(tmp_path: Path) -> None:
    module = _load_module()
    azure = FakeAzure(drift_after_update=True)

    with pytest.raises(module.RecoveryError, match="unexpected Job configuration drift"):
        module.run_recovery(
            _options(module),
            azure=azure,
            facets=FakeFacets(),
            evidence_dir=tmp_path,
            sleep=lambda _seconds: None,
        )

    assert azure.start_count == 0
    assert len(azure.update_calls) == 2
    assert module.normalize_job_config(azure.show_job()) == module.normalize_job_config(
        azure.original
    )


@pytest.mark.parametrize("status", ["Running", "", "FutureStatus"])
def test_active_or_unknown_execution_blocks_before_mutation(
    tmp_path: Path,
    status: str,
) -> None:
    module = _load_module()
    azure = FakeAzure(
        existing_executions=[{"properties": {"status": status}}]
    )

    with pytest.raises(module.RecoveryError, match="active or unknown execution"):
        module.run_recovery(
            _options(module),
            azure=azure,
            facets=FakeFacets(),
            evidence_dir=tmp_path,
        )

    assert azure.update_calls == []
    assert azure.start_count == 0


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda job: job["properties"]["template"]["containers"][0]["args"].extend(
                ["--replay-source-run-id", "activation-f002"]
            ),
            "fresh activation",
        ),
        (
            lambda job: job["properties"]["configuration"].update(
                {"replicaRetryLimit": 1}
            ),
            "retry limit",
        ),
        (
            lambda job: job["properties"]["template"]["containers"][0]["resources"].update(
                {"memory": "4Gi"}
            ),
            "baseline memory",
        ),
    ],
)
def test_preflight_refuses_unsafe_persistent_job_contract(mutation, message: str) -> None:
    module = _load_module()
    job = _job()
    mutation(job)

    with pytest.raises(module.RecoveryError, match=message):
        module.validate_preflight(module.normalize_job_config(job), _options(module))


def test_facet_validation_requires_nonempty_same_generation_and_available_aum() -> None:
    module = _load_module()
    server = _facet_payload(
        generation="exposure-gold-new",
        total_count=0,
        completeness="unavailable",
    )
    container = _facet_payload(
        generation="exposure-gold-old",
        total_count=77_857,
    )

    with pytest.raises(module.RecoveryError, match="server/AUM facet is empty"):
        module.validate_facet_payloads(server, container)

    server["data"]["total_count"] = 1
    with pytest.raises(module.RecoveryError, match="server/AUM completeness is unavailable"):
        module.validate_facet_payloads(server, container)

    server["data"]["completeness"]["state"] = "complete"
    with pytest.raises(module.RecoveryError, match="different generations"):
        module.validate_facet_payloads(server, container)


def test_az_cli_start_uses_persistent_template_without_execution_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    commands: list[list[str]] = []

    def capture(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout='{"name":"job-execution-1"}',
            stderr="",
        )

    monkeypatch.setattr(module.subprocess, "run", capture)
    client = module.AzCliJobClient(
        subscription="sub-1",
        resource_group="rg-1",
        job_name="job-1",
    )

    assert client.start_job() == "job-execution-1"
    assert commands == [
        [
            "az",
            "containerapp",
            "job",
            "start",
            "--name",
            "job-1",
            "--subscription",
            "sub-1",
            "--resource-group",
            "rg-1",
            "--only-show-errors",
            "--output",
            "json",
        ]
    ]


def test_az_cli_update_changes_only_image_timeout_and_memory_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    commands: list[list[str]] = []

    def capture(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="{}", stderr="")

    monkeypatch.setattr(module.subprocess, "run", capture)
    client = module.AzCliJobClient(
        subscription="sub-1",
        resource_group="rg-1",
        job_name="job-1",
    )

    client.update_job(
        image="registry.azurecr.io/aiops-api:fresh",
        timeout=7_200,
        memory="8Gi",
    )

    command = commands[0]
    assert command[1:3] == ["resource", "update"]
    assert command[command.index("--ids") :] == [
        "--ids",
        "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.App/jobs/job-1",
        "--api-version",
        "2024-03-01",
        "--set",
        "properties.template.containers[0].image=registry.azurecr.io/aiops-api:fresh",
        "properties.configuration.replicaTimeout=7200",
        "properties.template.containers[0].resources.memory=8Gi",
        "--only-show-errors",
        "--output",
        "json",
    ]
    assert not {"--cpu", "--command", "--args", "--env-vars"} & set(command)


def test_normalized_snapshot_hashes_inline_environment_values() -> None:
    module = _load_module()

    normalized = module.normalize_job_config(_job())
    serialized = json.dumps(normalized)

    assert "abfss://root" not in serialized
    assert '"value": "sha256:' in serialized
    assert "api-token" in serialized