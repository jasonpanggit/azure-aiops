"""Production benchmark evidence cannot be inferred from synthetic timings."""

from __future__ import annotations

import pytest

from api.exposure_query import ExposureAuthorization
from fabric.sql_endpoint import FabricSqlReader, SqlEndpoint
from scripts import benchmark_exposure_read_model as benchmark
from scripts.benchmark_exposure_read_model import (
    DeterministicFabricSqlReader,
    DeterministicMemoryAdapter,
    generate_exposure_rows,
    run_fabric_sql_benchmark,
)


def _authorization() -> ExposureAuthorization:
    return ExposureAuthorization(
        subject="contract-only",
        tenant_id="benchmark-tenant",
        connection_ids=("benchmark-connection-1", "benchmark-connection-2"),
        scope={
            "subscription": tuple(
                f"00000000-0000-0000-0000-{index:012d}" for index in range(1, 5)
            ),
        },
    )


@pytest.mark.parametrize("rows", [10, 100])
def test_synthetic_sql_contract_never_claims_production_certification(rows):
    reader = DeterministicFabricSqlReader(
        DeterministicMemoryAdapter(generate_exposure_rows(rows)),
    )
    report = run_fabric_sql_benchmark(
        reader,
        _authorization(),
        generation_id="benchmark-generation-0001",
        expected_rows=rows,
        page_size=25,
        warmups=1,
        measurements=2,
    )
    assert report["status"] == "pass"
    assert report["adapter"]["adapter_id"] == "deterministic_fabric_sql_contract"
    assert report["adapter"]["production"] is False
    assert report["adapter"]["production_slo_evidence"] is False
    assert report["slo"]["production_certified"] is False


@pytest.mark.parametrize(
    ("expected_rows", "warmups", "measurements", "qualified"),
    [
        (100_000, 5, 20, True),
        (99_999, 5, 20, False),
        (100_000, 4, 20, False),
        (100_000, 5, 19, False),
        (100_001, 6, 21, True),
    ],
)
@pytest.mark.parametrize("injected_connection", [False, True])
@pytest.mark.parametrize("fault", ["none", "duplicate", "empty_kind", "slow", "memory"])
def test_production_qualification_requires_real_reader_size_and_samples(
    monkeypatch, expected_rows, warmups, measurements, qualified, injected_connection,
    fault,
):
    # Exercise only the evidence decision here; no fake SQL result is retained
    # as a live benchmark receipt.
    reader = FabricSqlReader(
        SqlEndpoint(server="benchmark.invalid", database="benchmark"),
        credential=None,
        connect=(lambda: None) if injected_connection else None,
    )
    monkeypatch.setattr(benchmark.ExposureQueryService, "list_page", lambda *a, **k: None)
    monkeypatch.setattr(
        benchmark, "_measure",
        lambda *a, **k: {"p95_ms": 2_000.0 if fault == "slow" else 1.0},
    )
    rss = iter((1, benchmark.RSS_BUDGET_BYTES + 2 if fault == "memory" else 1))
    monkeypatch.setattr(benchmark, "_rss_bytes", lambda: next(rss))
    counts = iter(
        (expected_rows, 0) if fault == "empty_kind" else (expected_rows - 1, 1)
    )

    def walk(*args, **kwargs):
        count = next(counts)
        return {
            "expected_total": count,
            "returned_count": count,
            "unique_count": count - 1 if fault == "duplicate" else count,
            "duplicate_count": 1 if fault == "duplicate" else 0,
            "omission_count": 1 if fault == "duplicate" else 0,
            "status": "fail" if fault == "duplicate" else "pass",
        }

    monkeypatch.setattr(benchmark, "_exact_service_walk", walk)
    report = run_fabric_sql_benchmark(
        reader,
        _authorization(),
        generation_id="benchmark-generation-0001",
        expected_rows=expected_rows,
        page_size=25,
        warmups=warmups,
        measurements=measurements,
    )
    assert report["adapter"]["production"] is (not injected_connection)
    assert report["adapter"]["production_slo_evidence"] is (
        qualified and not injected_connection
    )
    assert report["slo"]["production_certified"] is (
        qualified and not injected_connection and fault == "none"
    )
    assert report["slo"]["qualification_scope_satisfied"] is qualified
    assert report["status"] == (
        "pass" if (qualified or injected_connection) and fault == "none" else "fail"
    )
