"""Tests for explicitly selected, non-certifying Fabric SQL diagnostics."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import benchmark_exposure_read_model as benchmark


def _forbidden(*_args, **_kwargs):
    pytest.fail("diagnostic mode must not enter production auth or benchmark paths")


def test_diagnostic_probe_uses_explicit_azure_cli_tenant_and_never_production_auth(
    monkeypatch,
):
    tenant_id = "explicit-diagnostic-tenant"
    credential = SimpleNamespace(closed=False, close=lambda: None)
    constructed_tenants = []
    probes = []
    readiness = {
        "schema_version": "1.0.0",
        "probe": "production_exposure_adapter",
        "ready": True,
        "selected_production_adapter": "fabric_sql",
        "checks": [],
        "reason_codes": [],
        "sanitized": True,
    }

    def build_cli_credential(*, tenant_id):
        constructed_tenants.append(tenant_id)
        return credential

    def probe(endpoint, supplied_credential, *, endpoint_source):
        probes.append((endpoint, supplied_credential, endpoint_source))
        return SimpleNamespace(to_dict=lambda: readiness)

    monkeypatch.setattr(benchmark, "AzureCliCredential", build_cli_credential)
    monkeypatch.setattr(benchmark, "_load_yaml", lambda _path: {
        "fabric": {
            "sql_endpoint": {
                "server": "verified-target.datawarehouse.fabric.microsoft.com",
                "database": "exposure-lakehouse",
            }
        }
    })
    monkeypatch.setattr(benchmark, "probe_exposure_readiness", probe)
    monkeypatch.setattr(benchmark, "build_credential", _forbidden)

    report = benchmark.probe_azure_cli_diagnostic(
        Path("fabric.config.yaml"),
        tenant_id,
    )

    assert constructed_tenants == [tenant_id]
    assert probes[0][1] is credential
    assert probes[0][2] == "config"
    assert probes[0][0] == {
        "server": "verified-target.datawarehouse.fabric.microsoft.com",
        "database": "exposure-lakehouse",
        "schema": "dbo",
    }
    assert report["diagnostic_ready"] is True
    assert report["diagnostic_status"] == "ready"
    assert report["diagnostic_only"] is True
    assert report["diagnostic_adapter"] == "fabric_sql"
    assert report["credential_source"] == "azure_cli"
    assert report["tenant_id_supplied"] is True
    assert report["production_certified"] is False
    assert report["production_scale_certified"] is False
    assert report["release_evidence_eligible"] is False
    assert "ready" not in report
    assert "selected_production_adapter" not in report
    assert tenant_id not in json.dumps(report)


@pytest.mark.parametrize(
    "arguments",
    [
        ["--diagnose-azure-cli"],
        [
            "--diagnose-azure-cli",
            "--diagnostic-tenant-id",
            " ",
        ],
        [
            "--diagnose-azure-cli",
            "--diagnostic-tenant-id",
            "target-tenant",
            "--require-ready",
        ],
        [
            "--diagnose-azure-cli",
            "--diagnostic-tenant-id",
            "target-tenant",
            "--probe-production-adapter",
        ],
        [
            "--diagnose-azure-cli",
            "--diagnostic-tenant-id",
            "target-tenant",
            "--rows",
            "100000",
        ],
        ["--diagnostic-tenant-id", "target-tenant"],
    ],
)
def test_diagnostic_requires_explicit_tenant_and_rejects_conflicting_modes(
    monkeypatch, arguments
):
    monkeypatch.setattr(benchmark, "probe_azure_cli_diagnostic", _forbidden)

    with pytest.raises(SystemExit) as captured:
        benchmark.main(arguments)

    assert captured.value.code == 2


def test_diagnostic_does_not_fall_back_to_benchmark_tenant_environment(
    monkeypatch,
):
    monkeypatch.setenv(
        "EXPOSURE_BENCHMARK_TENANT_ID",
        "benchmark-tenant-must-not-be-reused",
    )
    monkeypatch.setattr(benchmark, "probe_azure_cli_diagnostic", _forbidden)

    with pytest.raises(SystemExit) as captured:
        benchmark.main(["--diagnose-azure-cli"])

    assert captured.value.code == 2


def test_diagnostic_dispatch_never_runs_any_benchmark_or_production_probe(
    monkeypatch, capsys
):
    monkeypatch.setattr(benchmark, "probe_azure_cli_diagnostic", lambda *_args: {
        "diagnostic_ready": False,
        "diagnostic_only": True,
        "production_scale_certified": False,
        "reason_codes": ["fabric_sql_login_denied"],
    })
    monkeypatch.setattr(benchmark, "build_credential", _forbidden)
    monkeypatch.setattr(benchmark, "probe_production_adapter", _forbidden)
    monkeypatch.setattr(benchmark, "_require_production_reader", _forbidden)
    monkeypatch.setattr(benchmark, "run_fabric_sql_benchmark", _forbidden)
    monkeypatch.setattr(benchmark, "run_local_benchmark", _forbidden)
    monkeypatch.setattr(benchmark, "derive_live_benchmark_inputs", _forbidden)

    result = benchmark.main(
        [
            "--diagnose-azure-cli",
            "--diagnostic-tenant-id",
            "explicit-diagnostic-tenant",
            "--json",
        ]
    )

    report = json.loads(capsys.readouterr().out)
    assert result == 2
    assert report["diagnostic_only"] is True
    assert report["production_scale_certified"] is False
    assert report["reason_codes"] == ["fabric_sql_login_denied"]


def test_default_cli_still_runs_only_the_local_correctness_benchmark(
    monkeypatch, capsys
):
    local_report = {
        "status": "pass",
        "adapter": {"adapter_id": "deterministic_memory"},
    }
    monkeypatch.setattr(
        benchmark,
        "run_local_benchmark",
        lambda **_kwargs: local_report,
    )
    monkeypatch.setattr(benchmark, "build_credential", _forbidden)
    monkeypatch.setattr(benchmark, "probe_production_adapter", _forbidden)
    monkeypatch.setattr(benchmark, "probe_azure_cli_diagnostic", _forbidden)

    result = benchmark.main(["--rows", "1", "--warmups", "1", "--measurements", "1"])

    assert result == 0
    assert json.loads(capsys.readouterr().out) == local_report
