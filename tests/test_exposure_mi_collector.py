"""Offline contracts for the fixed, read-only collector candidate."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import exposure_mi_collector as collector


def test_fixed_job_entrypoint_is_packaged_in_runtime_image():
    dockerfile = (Path(__file__).parents[1] / "Dockerfile").read_text()
    runtime = dockerfile.split("FROM python:3.12-slim AS runtime", 1)[1]
    assert (
        "COPY scripts/exposure_mi_collector.py /app/scripts/exposure_mi_collector.py"
        in runtime
    )
    assert "COPY scripts/benchmark_exposure_read_model.py " in runtime
    assert "COPY src/ /app/src/" in runtime


@pytest.fixture(autouse=True)
def offline_odbc(monkeypatch):
    """Keep fake-reader contracts independent of the optional native SQL driver."""
    monkeypatch.setitem(sys.modules, "pyodbc", SimpleNamespace(Error=RuntimeError))


def environment():
    return {
        "AIOPS_HOME": collector.ROOT,
        "AIOPS_CONNECTION_HOME": collector.ROOT + "/connections",
        "AZURE_CLIENT_ID": collector.CLIENT,
        "AIOPS_SOURCE_REVISION": "a" * 40,
        "AIOPS_FABRIC_CONFIG_JSON": json.dumps(
            {
                "fabric": {
                    "workspace_id": collector.WORKSPACE,
                    "lakehouse_id": collector.LAKEHOUSE,
                    "sql_endpoint": collector.ENDPOINT,
                    "auth": {
                        "tenant_id": collector.TENANT,
                        "mode": "managed_identity",
                        "managed_identity_client_id": collector.CLIENT,
                    },
                }
            }
        ),
    }


def test_exact_corrected_binding():
    collector.validate_runtime(environment())


@pytest.mark.parametrize(
    "key",
    [
        "AIOPS_HOME",
        "AIOPS_CONNECTION_HOME",
        "AZURE_CLIENT_ID",
        "AIOPS_SOURCE_REVISION",
        "AIOPS_FABRIC_CONFIG_JSON",
    ],
)
def test_binding_fails_closed(key):
    values = environment()
    values[key] = "{}" if key.endswith("_JSON") else "stale"
    with pytest.raises(ValueError):
        collector.validate_runtime(values)


@pytest.mark.parametrize(
    ("sql", "limit"),
    [
        ("DELETE FROM dbo.gold_exposure_facts", 1),
        ("SELECT 1", None),
        ("SELECT 1", 0),
        ("SELECT 1", 102),
        ("SELECT 1", True),
    ],
)
def test_benchmark_bounds(sql, limit):
    reader = collector.BoundedBenchmarkReader(SimpleNamespace())
    with pytest.raises(ValueError, match="bound"):
        reader.query(sql, max_rows=limit)


def test_walk_query_budget():
    reader = collector.BoundedBenchmarkReader(
        SimpleNamespace(query=lambda *args, **kwargs: [{"count": 1}])
    )
    assert reader.query("SELECT COUNT_BIG(*) FROM fixed", max_rows=1) == [{"count": 1}]
    reader.calls = 6000
    with pytest.raises(ValueError, match="bound"):
        reader.query("SELECT 1", max_rows=1)


def test_actual_benchmark_instrumentation_accepts_bounded_reader():
    from api.exposure_query import ExposureAuthorization

    queries = []

    def query(sql, parameters=(), *, max_rows):
        queries.append((sql, parameters, max_rows))
        if "COUNT_BIG" in sql and "GROUP BY" not in sql:
            return [{"total_count": 0, "freshest_at": "", "all_complete": 1}]
        return []

    endpoint = collector.SqlEndpoint(**collector.ENDPOINT)
    reader = collector.BoundedBenchmarkReader(
        SimpleNamespace(endpoint=endpoint, query=query)
    )
    authorization = ExposureAuthorization(
        subject="collector-instrumentation-regression",
        tenant_id=collector.TENANT,
        connection_ids=("connection-live",),
        scope={"subscription": (collector.SUBSCRIPTION,)},
    )
    result = collector.run_fabric_sql_benchmark(
        reader,
        authorization,
        generation_id="generation-live",
        expected_rows=100_000,
        page_size=100,
        warmups=0,
        measurements=1,
    )
    assert reader.endpoint is endpoint
    assert result["status"] == "fail"
    assert queries
    assert reader.calls == len(queries)
    assert all(sql.startswith("WITH [scoped] AS (SELECT") for sql, _, _ in queries)
    assert all(max_rows <= 101 for _, _, max_rows in queries)


def test_actual_production_compiler_ctes_are_supported():
    from api.exposure_query import (
        ExposureAuthorization,
        ExposureQuery,
        _compile_queries,
    )

    authorization = ExposureAuthorization(
        subject="collector-regression",
        tenant_id=collector.TENANT,
        connection_ids=("connection-live",),
        scope={"subscription": (collector.SUBSCRIPTION,)},
    )
    compiled = _compile_queries(
        authorization,
        generation_id="generation-live",
        query=ExposureQuery(page_size=100),
        after=None,
        schema="dbo",
    )
    calls = []
    reader = collector.BoundedBenchmarkReader(
        SimpleNamespace(query=lambda sql, parameters, **kwargs: calls.append(sql) or [])
    )
    reader.query(compiled.count_sql, compiled.parameters, max_rows=1)
    reader.query(
        compiled.page_sql,
        compiled.page_parameters,
        max_rows=compiled.page_limit,
    )
    assert len(calls) == 2


def test_document_read_uses_real_sdk_range_contract_without_network():
    from azure.core.credentials import AzureSasCredential
    from azure.core.pipeline.transport import HttpTransport
    from azure.storage.filedatalake import DataLakeFileClient

    class RequestCaptured(RuntimeError):
        pass

    class CaptureTransport(HttpTransport):
        def __init__(self):
            self.requests = []

        def open(self):
            pass

        def close(self):
            pass

        def __exit__(self, *_args):
            self.close()

        def send(self, request, **kwargs):
            self.requests.append(request)
            raise RequestCaptured("offline transport reached")

    transport = CaptureTransport()
    with DataLakeFileClient(
        account_url="https://onelake.dfs.fabric.microsoft.com",
        file_system_name=collector.WORKSPACE,
        file_path=f"{collector.LAKEHOUSE}/Files/aiops/exposure/gold-generation-pointer.json",
        credential=AzureSasCredential("sig=offline-test-no-network"),
        transport=transport,
        retry_total=0,
    ) as sdk_client:
        client = SimpleNamespace(
            get_file_properties=lambda: SimpleNamespace(size=100),
            download_file=sdk_client.download_file,
        )
        fs = SimpleNamespace(get_file_client=lambda _path: client)
        with pytest.raises(RequestCaptured, match="offline transport"):
            collector.read_document(fs, "exposure/gold-generation-pointer.json")
    assert len(transport.requests) == 1
    assert transport.requests[0].headers["x-ms-range"] == (
        f"bytes=0-{collector.MAX_DOCUMENT_BYTES}"
    )


def test_oversized_document_never_downloaded():
    client = SimpleNamespace(
        get_file_properties=lambda: SimpleNamespace(
            size=collector.MAX_DOCUMENT_BYTES + 1
        )
    )
    fs = SimpleNamespace(get_file_client=lambda path: client)
    with pytest.raises(ValueError, match="size_bound"):
        collector.read_document(fs, "exposure/gold-generation-pointer.json")


@pytest.mark.parametrize(
    "body", [b'{"revision":1}', b"[]", b"x" * (4 * 1024 * 1024 + 1)]
)
def test_document_body_validation_preserves_download_bound(body):
    requests = []

    def download(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(readall=lambda: body)

    client = SimpleNamespace(
        get_file_properties=lambda: SimpleNamespace(size=1),
        download_file=download,
    )
    fs = SimpleNamespace(get_file_client=lambda _path: client)
    if body.startswith(b"{"):
        payload, digest = collector.read_document(fs, "fixed.json")
        assert payload == {"revision": 1}
        assert digest == collector.digest(body)
    else:
        with pytest.raises((TypeError, ValueError)):
            collector.read_document(fs, "fixed.json")
    assert requests == [
        {
            "offset": 0,
            "length": collector.MAX_DOCUMENT_BYTES + 1,
            "max_concurrency": 1,
        }
    ]


def test_delegated_credential_cannot_be_labelled_application_mi():
    with pytest.raises(TypeError, match="application_managed_identity_required"):
        collector.collect(object(), benchmark=False)


@pytest.mark.parametrize("benchmark", [False, True])
@pytest.mark.parametrize("changed", [False, True])
def test_observations_never_invent_acceptance(monkeypatch, benchmark, changed):
    monkeypatch.setenv("AIOPS_SOURCE_REVISION", "a" * 40)
    connection = SimpleNamespace(
        tenant_id=collector.TENANT,
        subscription_id=collector.SUBSCRIPTION,
        connection_id="registered-connection",
        is_active=True,
    )
    monkeypatch.setattr(
        collector.SubscriptionConnection, "from_mapping", lambda row: connection
    )
    monkeypatch.setattr(collector, "FileSystemClient", lambda **kwargs: object())
    reads = {}

    def read_document(fs, name):
        reads[name] = reads.get(name, 0) + 1
        if name.startswith("connections"):
            return {"connections": [{}]}, "registry-hash"
        return (
            {
                "readable_generation_id": "generation-observed",
                "previous_generation_id": None,
            },
            "changed" if changed and reads[name] > 1 else "pointer-hash",
        )

    monkeypatch.setattr(collector, "read_document", read_document)
    monkeypatch.setattr(
        collector,
        "probe_exposure_readiness",
        lambda *args, **kwargs: SimpleNamespace(to_dict=lambda: {"ready": True}),
    )

    class Reader:
        def __init__(self, *args, **kwargs):
            assert kwargs["timeout_seconds"] == 20

        def query(self, sql, parameters=(), *, max_rows):
            assert sql.startswith("SELECT ")
            assert sql.count("?") == len(parameters)
            assert max_rows <= 64
            if "GROUP BY target_kind" in sql:
                return [{"row_count": 185, "source_generation_id": "real-source-run"}]
            return []

    monkeypatch.setattr(collector, "FabricSqlReader", Reader)
    monkeypatch.setattr(
        collector,
        "run_fabric_sql_benchmark",
        lambda *args, **kwargs: {"status": "fail", "row_count": 185},
    )
    with collector.ManagedIdentityCredential(client_id=collector.CLIENT) as credential:
        report = collector.collect(credential, benchmark=benchmark)

    assert report["production_certified"] is False
    assert report["phase4_ready"] is False
    assert report["source_binding_complete"] is False
    assert "real-source-run" not in json.dumps(report)
    assert report["metadata_unchanged_during_collection"] is not changed
    if benchmark:
        assert report["status"] == "blocked_benchmark_not_qualified"
    elif changed:
        assert report["status"] == "blocked_incomplete_or_changed_evidence"
    else:
        assert report["status"] == "observations_collected"
