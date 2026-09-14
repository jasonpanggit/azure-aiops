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


def _provenance_payload(
    *,
    generation: str = "silver-patch:source-generation-17",
    active: int = 11,
    expected: int = 11,
    legacy: int = 0,
    unexpected: int = 0,
) -> dict[str, Any]:
    return {
        "data": {
            "generation": generation,
            "active_fact_count": active,
            "expected_connection_fact_count": expected,
            "legacy_connection_fact_count": legacy,
            "unexpected_connection_fact_count": unexpected,
        }
    }


class FakeAzure:
    def __init__(
        self,
        *,
        execution_statuses: list[str | Exception] | None = None,
        existing_executions: list[dict[str, Any]] | None = None,
        drift_after_update: bool = False,
        stop_statuses: list[str | Exception] | None = None,
    ) -> None:
        self.job = _job()
        self.original = deepcopy(self.job)
        self.execution_statuses = iter(execution_statuses or ["Succeeded"])
        self.existing_executions = existing_executions or []
        self.drift_after_update = drift_after_update
        self.stop_statuses = iter(stop_statuses or ["Stopped"])
        self.start_count = 0
        self.stop_count = 0
        self.update_calls: list[tuple[str, float, str, int, str]] = []

    def show_job(self) -> dict[str, Any]:
        return deepcopy(self.job)

    def list_executions(self) -> list[dict[str, Any]]:
        return deepcopy(self.existing_executions)

    def update_job(
        self,
        *,
        workload_profile: str,
        cpu: float,
        image: str,
        timeout: int,
        memory: str,
    ) -> None:
        self.update_calls.append(
            (workload_profile, cpu, image, timeout, memory)
        )
        self.job["properties"]["workloadProfileName"] = workload_profile
        container = self.job["properties"]["template"]["containers"][0]
        container["image"] = image
        container["resources"]["cpu"] = cpu
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
        value = (
            next(self.stop_statuses)
            if self.stop_count
            else next(self.execution_statuses)
        )
        if isinstance(value, BaseException):
            raise value
        return {"name": execution_name, "properties": {"status": value}}

    def stop_execution(self, execution_name: str) -> None:
        assert execution_name == "job-execution-1"
        self.stop_count += 1


class FakeFacets:
    def __init__(
        self,
        *,
        provenance: dict[str, Any] | None = None,
    ) -> None:
        self.calls: list[tuple[str, str]] = []
        self.provenance = provenance or _provenance_payload()
        self.provenance_calls: list[tuple[str, str]] = []

    def read_overview(self, *, target_kind: str, source_family: str) -> dict[str, Any]:
        self.calls.append((target_kind, source_family))
        return _facet_payload(
            generation=(
                "silver-patch:source-generation-17"
                if target_kind == "server"
                else "exposure-gold-fresh"
            ),
            total_count=11 if target_kind == "server" else 77_857,
        )

    def read_provenance(
        self,
        *,
        generation: str,
        expected_connection_id: str,
    ) -> dict[str, Any]:
        self.provenance_calls.append((generation, expected_connection_id))
        return deepcopy(self.provenance)


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
        stop_wait_seconds=30,
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
        (
            "Consumption",
            4.0,
            "registry.azurecr.io/aiops-api:fresh-byte-bound",
            7_200,
            "8Gi",
        ),
        (
            "Consumption",
            4.0,
            "registry.azurecr.io/aiops-api:old",
            3_600,
            "8Gi",
        ),
    ]
    assert module.normalize_job_config(azure.show_job()) == module.normalize_job_config(
        azure.original
    )
    assert facets.calls == [
        ("server", "aum"),
        ("container_image", "defender_image"),
    ]
    assert facets.provenance_calls == [
        ("silver-patch:source-generation-17", "demo")
    ]
    assert result["status"] == "succeeded"
    assert result["generation"] == "silver-patch:source-generation-17"
    assert result["container_generation"] == "exposure-gold-fresh"
    assert result["facet_counts"] == {"server_aum": 11, "container_defender": 77_857}
    assert result["provenance"]["legacy_connection_facts"] == 0
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


def test_explicit_e8_configuration_is_accepted_and_fully_restored(
    tmp_path: Path,
) -> None:
    module = _load_module()
    azure = FakeAzure()
    options = _options(module)._replace(
        target_workload_profile="publication-e8",
        target_cpu=8.0,
        target_memory="64Gi",
        target_timeout=14_400,
        max_wait_seconds=15_300,
    )

    module.run_recovery(
        options,
        azure=azure,
        facets=FakeFacets(),
        evidence_dir=tmp_path,
        sleep=lambda _seconds: None,
    )

    assert azure.update_calls[0][:2] == ("publication-e8", 8.0)
    assert azure.update_calls[0][3:] == (14_400, "64Gi")
    assert azure.update_calls[-1][:2] == ("Consumption", 4.0)
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


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        (
            {"target_cpu": 8.0},
            "reviewed Consumption or publication-e8",
        ),
        (
            {"target_memory": "64Gi"},
            "reviewed Consumption or publication-e8",
        ),
        (
            {"target_timeout": 14_400},
            "reviewed Consumption or publication-e8",
        ),
        (
            {
                "target_workload_profile": "publication-e8",
                "target_cpu": 8.0,
                "target_memory": "64GB",
                "target_timeout": 14_400,
                "max_wait_seconds": 15_300,
            },
            "whole-number Gi",
        ),
        (
            {
                "target_workload_profile": "unreviewed-e8",
                "target_cpu": 8.0,
                "target_memory": "64Gi",
                "target_timeout": 14_400,
                "max_wait_seconds": 15_300,
            },
            "reviewed Consumption or publication-e8",
        ),
    ],
)
def test_unsafe_resource_combinations_are_rejected(
    changes: dict[str, Any],
    message: str,
) -> None:
    module = _load_module()
    options = _options(module)._replace(**changes)

    with pytest.raises(module.RecoveryError, match=message):
        module.validate_preflight(
            module.normalize_job_config(_job()),
            options,
        )


def test_exact_allowed_diff_includes_requested_e8_fields_only() -> None:
    module = _load_module()
    original = module.normalize_job_config(_job())
    updated = deepcopy(original)
    updated["workloadProfileName"] = "publication-e8"
    container = updated["template"]["containers"][0]
    container["image"] = "registry.azurecr.io/aiops-api:fresh-byte-bound"
    container["resources"] = {"cpu": 8.0, "memory": "64Gi"}
    updated["configuration"]["replicaTimeout"] = 14_400
    options = _options(module)._replace(
        target_workload_profile="publication-e8",
        target_cpu=8.0,
        target_memory="64Gi",
        target_timeout=14_400,
        max_wait_seconds=15_300,
    )

    assert module._changed_paths(original, updated) == module._expected_update_paths(
        original,
        options,
    )

    updated["configuration"]["replicaRetryLimit"] = 1
    assert module._changed_paths(original, updated) != module._expected_update_paths(
        original,
        options,
    )


def test_transient_execution_show_failures_retry_with_exponential_backoff(
    tmp_path: Path,
) -> None:
    module = _load_module()
    azure = FakeAzure(
        execution_statuses=[
            module.RecoveryError("transient"),
            module.RecoveryError("transient"),
            "Succeeded",
        ]
    )
    sleeps: list[float] = []

    module.run_recovery(
        _options(module),
        azure=azure,
        facets=FakeFacets(),
        evidence_dir=tmp_path,
        sleep=sleeps.append,
    )

    assert sleeps == [1, 2]
    assert len(azure.update_calls) == 2


def test_timeout_stops_confirms_terminal_then_restores(tmp_path: Path) -> None:
    module = _load_module()
    azure = FakeAzure(
        execution_statuses=["Running"],
        stop_statuses=["Running", "Stopped"],
    )
    times = iter([0.0, 8_000.0, 8_000.0, 8_010.0])

    with pytest.raises(module.RecoveryError, match="terminal status in time"):
        module.run_recovery(
            _options(module),
            azure=azure,
            facets=FakeFacets(),
            evidence_dir=tmp_path,
            sleep=lambda _seconds: None,
            clock=lambda: next(times),
        )

    assert azure.stop_count == 1
    assert len(azure.update_calls) == 2


def test_interrupt_stops_confirms_terminal_then_restores(tmp_path: Path) -> None:
    module = _load_module()
    azure = FakeAzure(
        execution_statuses=[KeyboardInterrupt()],
        stop_statuses=["Stopped"],
    )

    with pytest.raises(KeyboardInterrupt):
        module.run_recovery(
            _options(module),
            azure=azure,
            facets=FakeFacets(),
            evidence_dir=tmp_path,
            sleep=lambda _seconds: None,
        )

    assert azure.stop_count == 1
    assert len(azure.update_calls) == 2


def test_no_restore_occurs_when_stopped_execution_remains_live(tmp_path: Path) -> None:
    module = _load_module()
    azure = FakeAzure(
        execution_statuses=[KeyboardInterrupt()],
        stop_statuses=["Running"],
    )
    times = iter([0.0, 0.0, 31.0])

    with pytest.raises(module.RecoveryError, match="not restored"):
        module.run_recovery(
            _options(module),
            azure=azure,
            facets=FakeFacets(),
            evidence_dir=tmp_path,
            sleep=lambda _seconds: None,
            clock=lambda: next(times),
        )

    assert azure.stop_count == 1
    assert len(azure.update_calls) == 1
    assert azure.job["properties"]["configuration"]["replicaTimeout"] == 7_200


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


def test_restore_snapshot_refuses_active_execution(tmp_path: Path) -> None:
    module = _load_module()
    azure = FakeAzure(
        existing_executions=[{"properties": {"status": "Running"}}]
    )
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(
        json.dumps(module.normalize_job_config(_job())),
        encoding="utf-8",
    )

    with pytest.raises(module.RecoveryError, match="active or unknown execution"):
        module.restore_snapshot(azure, snapshot, tmp_path)

    assert azure.update_calls == []


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


def test_facet_validation_requires_nonempty_complete_split_generations() -> None:
    module = _load_module()
    server = _facet_payload(
        generation="silver-patch:source-generation-17",
        total_count=0,
        completeness="unavailable",
    )
    container = _facet_payload(
        generation="exposure-gold-old",
        total_count=77_857,
    )

    with pytest.raises(module.RecoveryError, match="server/AUM facet is empty"):
        module.validate_facet_payloads(server, container, _provenance_payload())

    server["data"]["total_count"] = 1
    with pytest.raises(
        module.RecoveryError,
        match="server/AUM completeness is not complete",
    ):
        module.validate_facet_payloads(server, container, _provenance_payload())

    server["data"]["completeness"]["state"] = "complete"
    result = module.validate_facet_payloads(
        server,
        container,
        _provenance_payload(),
    )
    assert result["generation"] == "silver-patch:source-generation-17"
    assert result["container_generation"] == "exposure-gold-old"

    server["data"]["generation"] = "exposure-gold-new"
    with pytest.raises(module.RecoveryError, match="Silver patch generation"):
        module.validate_facet_payloads(server, container, _provenance_payload())

    server["data"]["generation"] = "silver-patch:source-generation-17"
    container["data"]["generation"] = "silver-patch:source-generation-17"
    with pytest.raises(module.RecoveryError, match="Gold generation"):
        module.validate_facet_payloads(server, container, _provenance_payload())


def test_demo_provenance_succeeds_and_legacy_provenance_is_rejected() -> None:
    module = _load_module()
    server = _facet_payload(
        generation="silver-patch:source-generation-17",
        total_count=11,
    )
    container = _facet_payload(
        generation="exposure-gold-fresh",
        total_count=77_857,
    )

    result = module.validate_facet_payloads(
        server,
        container,
        _provenance_payload(),
    )
    assert result["provenance"] == {
        "active_server_aum_facts": 11,
        "expected_connection_facts": 11,
        "legacy_connection_facts": 0,
        "unexpected_connection_facts": 0,
    }

    with pytest.raises(module.RecoveryError, match="legacy connection"):
        module.validate_facet_payloads(
            server,
            container,
            _provenance_payload(
                active=12,
                expected=11,
                legacy=1,
                unexpected=1,
            ),
        )

    with pytest.raises(module.RecoveryError, match="different generation"):
        module.validate_facet_payloads(
            server,
            container,
            _provenance_payload(generation="silver-patch:other-generation"),
        )


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


def test_az_cli_update_changes_only_reviewed_temporary_fields(
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
        workload_profile="publication-e8",
        cpu=8.0,
        image="registry.azurecr.io/aiops-api:fresh",
        timeout=14_400,
        memory="64Gi",
    )

    command = commands[0]
    assert command[1:3] == ["resource", "update"]
    assert command[command.index("--ids") :] == [
        "--ids",
        "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.App/jobs/job-1",
        "--api-version",
        "2024-03-01",
        "--set",
        "properties.workloadProfileName=publication-e8",
        "properties.template.containers[0].image=registry.azurecr.io/aiops-api:fresh",
        "properties.configuration.replicaTimeout=14400",
        "properties.template.containers[0].resources.cpu=8",
        "properties.template.containers[0].resources.memory=64Gi",
        "--only-show-errors",
        "--output",
        "json",
    ]
    assert not {"--command", "--args", "--env-vars"} & set(command)


def test_normalized_snapshot_hashes_inline_environment_values() -> None:
    module = _load_module()

    normalized = module.normalize_job_config(_job())
    serialized = json.dumps(normalized)

    assert "abfss://root" not in serialized
    assert '"value": "sha256:' in serialized
    assert "api-token" in serialized