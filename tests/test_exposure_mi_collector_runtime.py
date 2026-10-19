"""Offline CLI exercise through real Azure SDK, SQL reader and query compiler."""

import json
import signal
import struct
import sys
import time
from datetime import date, datetime
from decimal import Decimal

import pytest
from azure.core.credentials import AccessToken, AccessTokenInfo
from azure.core.pipeline.transport import HttpResponse, HttpTransport
from azure.storage.filedatalake import FileSystemClient

from fabric.sql_endpoint import REQUIRED_EXPOSURE_SCHEMA
from scripts import exposure_mi_collector as collector


class FixtureResponse(HttpResponse):
    def __init__(self, request, body):
        super().__init__(request, None)
        self.status_code = 200 if request.method == "HEAD" else 206
        self.reason = "OK"
        self.headers = {
            "Content-Length": str(len(body)),
            "Content-Type": "application/octet-stream",
            "Content-Range": f"bytes 0-{len(body) - 1}/{len(body)}",
            "ETag": '"offline-fixed-document"',
            "Last-Modified": "Mon, 19 Oct 2026 15:00:00 GMT",
            "x-ms-resource-type": "file",
        }
        self._body = body

    def body(self):
        return self._body

    def stream_download(self, pipeline, **kwargs):
        body = self._body

        class Stream:
            content_length = len(body)

            def __iter__(self):
                return iter((body,))

        stream = Stream()
        stream.response = self
        return stream


class FixtureTransport(HttpTransport):
    def __init__(
        self, *, failure=None, changed_pointer=False, deadline=False, http_error=None
    ):
        self.requests = []
        self.failure = failure
        self.changed_pointer = changed_pointer
        self.pointer_reads = 0
        self.deadline = deadline
        self.http_error = http_error

    def open(self):
        pass

    def close(self):
        pass

    def __exit__(self, *_args):
        self.close()

    def send(self, request, **kwargs):
        self.requests.append(
            (request.method, request.url, dict(request.headers), kwargs)
        )
        if self.failure is not None:
            raise self.failure
        if self.deadline:
            signal.getsignal(signal.SIGALRM)(signal.SIGALRM, None)
        if self.http_error:
            status, code = self.http_error
            response = FixtureResponse(
                request,
                (
                    f"<Error><Code>{code}</Code>"
                    "<Message>offline-secret-provider-message</Message></Error>"
                ).encode(),
            )
            response.status_code = status
            response.reason = "offline-secret-provider-message"
            response.headers["x-ms-error-code"] = code
            response.headers["Content-Type"] = "application/xml"
            return response
        if "subscription_connections.json" in request.url:
            payload = {
                "connections": [
                    {
                        "connection_id": "offline-connection",
                        "tenant_id": collector.TENANT,
                        "subscription_id": collector.SUBSCRIPTION,
                        "is_active": True,
                    }
                ]
            }
        elif "gold-generation-pointer.json" in request.url:
            if request.method == "GET":
                self.pointer_reads += 1
            payload = {
                "readable_generation_id": (
                    "offline-changed-generation"
                    if self.changed_pointer and self.pointer_reads > 1
                    else "offline-generation"
                ),
                "previous_generation_id": None,
            }
        else:
            raise AssertionError("Unexpected storage request")
        return FixtureResponse(request, json.dumps(payload).encode())


class OfflineSqlError(Exception):
    pass


class FixtureOdbc:
    Error = OfflineSqlError

    def __init__(
        self,
        *,
        missing_table=False,
        benchmark_failure=False,
        no_driver=False,
        unsupported_value=False,
        nonfinite=False,
    ):
        self.calls = []
        self.connections = []
        self.missing_table = missing_table
        self.benchmark_failure = benchmark_failure
        self.no_driver = no_driver
        self.unsupported_value = unsupported_value
        self.nonfinite = nonfinite

    def drivers(self):
        return [] if self.no_driver else ["ODBC Driver 18 for SQL Server"]

    def connect(self, connection_string, **kwargs):
        self.connections.append((connection_string, kwargs))
        return FixtureConnection(self)


class FixtureConnection:
    def __init__(self, driver):
        self.driver = driver

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def cursor(self):
        return FixtureCursor(self.driver)


class FixtureCursor:
    timeout = 0

    def __init__(self, driver):
        self.driver = driver
        self.rows = []
        self.description = []

    def execute(self, sql, *parameters):
        self.driver.calls.append((sql, parameters, self.timeout))
        assert sql.count("?") == len(parameters)
        if self.driver.benchmark_failure and sql.startswith("WITH [scoped]"):
            raise OfflineSqlError("08001", "offline SQL provider failure")
        if self.driver.missing_table and "dbo.silver_workload_deployments" in sql:
            raise OfflineSqlError("42S02", "offline missing table")
        if sql == "SELECT 1 AS probe":
            rows = [{"probe": 1}]
        elif "INFORMATION_SCHEMA.TABLES" in sql:
            rows = [{"present": 1}]
        elif "INFORMATION_SCHEMA.COLUMNS" in sql:
            rows = [
                {"COLUMN_NAME": name}
                for name in sorted(REQUIRED_EXPOSURE_SCHEMA[parameters[1]])
            ]
        elif "GROUP BY target_kind" in sql:
            rows = [
                {
                    "row_count": Decimal(185),
                    "represented_per_fact_sum": (
                        Decimal("NaN")
                        if self.driver.nonfinite
                        else Decimal("12345678901234567890.12345678901234567890")
                    ),
                    "unknown_per_fact_sum": None,
                    "source_generation_id": "offline-private-source",
                }
            ]
        elif "FROM dbo.metadata_exposure_gold_generations" in sql:
            rows = [
                {
                    "read_model_generation_id": "offline-generation",
                    "previous_generation_id": None,
                    "ingestion_run_id": "offline-private-source",
                    "reconciliation_status": "reconciled",
                    "reconciliation_hash": (
                        b"offline-unsupported"
                        if self.driver.unsupported_value
                        else "offline-hash"
                    ),
                    "published_at": datetime(2026, 10, 19, 15, 0, 0, 123456),  # noqa: DTZ001 - ODBC datetime2 is naive
                    "retain_until": date(2026, 10, 20),
                }
            ]
        elif "COUNT_BIG" in sql and "GROUP BY" not in sql:
            rows = [{"total_count": 0, "freshest_at": "", "all_complete": 1}]
        else:
            rows = []
        self.description = [(name,) for name in rows[0]] if rows else []
        self.rows = [tuple(row.values()) for row in rows]

    def fetchall(self):
        return self.rows

    def fetchmany(self, maximum):
        return self.rows[:maximum]


def cli_environment():
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


@pytest.mark.parametrize(
    "mode",
    [
        "aggregate",
        "benchmark",
        "sql_failure",
        "storage_failure",
        "invalid_config",
        "config_root_shape",
        "config_fabric_shape",
        "config_auth_shape",
        "mi_failure",
        "benchmark_sql_failure",
        "metadata_changed",
        "readiness_failure",
        "deadline",
        "unsupported_output",
        "storage_denied",
        "storage_unknown_error",
        "nonfinite_output",
    ],
)
def test_exact_cli_with_real_sdk_and_sql_boundaries(monkeypatch, capsys, mode):
    from azure.core.exceptions import ServiceRequestError

    transport = FixtureTransport(
        failure=ServiceRequestError("offline transport failure")
        if mode == "storage_failure"
        else None,
        changed_pointer=mode == "metadata_changed",
        deadline=mode == "deadline",
        http_error=(
            (403, "AuthorizationPermissionMismatch")
            if mode == "storage_denied"
            else (404, "offline-sensitive-code")
            if mode == "storage_unknown_error"
            else None
        ),
    )
    driver = FixtureOdbc(
        missing_table=mode == "sql_failure",
        benchmark_failure=mode == "benchmark_sql_failure",
        no_driver=mode == "readiness_failure",
        unsupported_value=mode == "unsupported_output",
        nonfinite=mode == "nonfinite_output",
    )
    monkeypatch.setitem(sys.modules, "pyodbc", driver)
    scopes = []

    def token(self, *requested, **kwargs):
        scopes.extend(requested)
        if mode == "mi_failure":
            from azure.identity import CredentialUnavailableError

            raise CredentialUnavailableError("offline MI unavailable")
        return AccessToken("offline-not-an-entra-token", int(time.time()) + 3600)

    monkeypatch.setattr(collector.ManagedIdentityCredential, "get_token", token)
    monkeypatch.setattr(
        collector.ManagedIdentityCredential,
        "get_token_info",
        lambda self, *requested, **kwargs: AccessTokenInfo(
            token(self, *requested, **kwargs).token, int(time.time()) + 3600
        ),
    )

    def storage(**kwargs):
        assert kwargs["credential"].__class__ is collector.ManagedIdentityCredential
        assert kwargs["connection_timeout"] == 10
        assert kwargs["read_timeout"] == 20
        assert kwargs["retry_total"] == 0
        return FileSystemClient(**kwargs, transport=transport)

    monkeypatch.setattr(collector, "FileSystemClient", storage)
    for key, value in cli_environment().items():
        monkeypatch.setenv(key, value)
    if mode == "invalid_config":
        monkeypatch.setenv("AIOPS_HOME", "historical-invalid-root")
    for case, payload in (
        ("config_root_shape", []),
        ("config_fabric_shape", {"fabric": []}),
        (
            "config_auth_shape",
            {
                "fabric": {
                    **json.loads(cli_environment()["AIOPS_FABRIC_CONFIG_JSON"])[
                        "fabric"
                    ],
                    "auth": [],
                }
            },
        ),
    ):
        if mode == case:
            monkeypatch.setenv("AIOPS_FABRIC_CONFIG_JSON", json.dumps(payload))
    monkeypatch.setattr(
        sys,
        "argv",
        ["exposure_mi_collector.py"]
        + (["--benchmark"] if mode in {"benchmark", "benchmark_sql_failure"} else []),
    )
    previous_handler = signal.getsignal(signal.SIGALRM)
    alarm_calls = []
    monkeypatch.setattr(collector.signal, "alarm", alarm_calls.append)
    try:
        status = collector.main()
    finally:
        signal.signal(signal.SIGALRM, previous_handler)
    assert alarm_calls == [900, 0]
    output = capsys.readouterr().out
    report = json.loads(output)
    assert report["production_certified"] is False
    assert report["phase4_ready"] is False
    assert "offline-private-source" not in output
    assert "offline-not-an-entra-token" not in output
    assert "offline-secret-provider-message" not in output
    assert "offline-sensitive-code" not in output
    assert status == (0 if mode == "aggregate" else 2)
    if mode == "aggregate":
        assert report["status"] == "observations_collected"
        publication = report["queries"]["publication"]["rows"][0]
        assert publication["published_at"] == "2026-10-19T15:00:00.123456"
        assert publication["retain_until"] == "2026-10-20"
        assert publication["previous_generation_id"] is None
        counts = report["queries"]["gold_counts"]["rows"][0]
        assert counts["row_count"] == "185"
        assert counts["represented_per_fact_sum"] == (
            "12345678901234567890.12345678901234567890"
        )
        assert counts["unknown_per_fact_sum"] is None
    elif mode == "benchmark":
        assert report["status"] == "blocked_benchmark_not_qualified"
        assert any(
            sql.startswith("WITH [scoped] AS (SELECT") for sql, _, _ in driver.calls
        )
    elif mode == "sql_failure":
        assert report["queries"]["silver_deployment_sources"]["sqlstate"] == "42S02"
    elif mode == "benchmark_sql_failure":
        assert report["benchmark"]["status"] == "provider_query_failed"
        assert report["benchmark"]["sqlstate"] == "08001"
    elif mode == "metadata_changed":
        assert report["status"] == "blocked_incomplete_or_changed_evidence"
        assert report["metadata_unchanged_during_collection"] is False
    elif mode == "readiness_failure":
        assert report["status"] == "blocked_sql_readiness"
        assert not driver.connections
        assert len(transport.requests) == 4
    elif mode in {"storage_denied", "storage_unknown_error"}:
        assert report["status"] == "blocked_collection_error"
        assert report["http_status"] == (403 if mode == "storage_denied" else 404)
        if mode == "storage_denied":
            assert report["provider_error_code"] == "AuthorizationPermissionMismatch"
        else:
            assert "provider_error_code" not in report
        assert not driver.calls
    else:
        assert report["status"] == "blocked_collection_error"
    if mode == "invalid_config" or mode.startswith("config_"):
        assert not transport.requests and not driver.calls and not scopes
    elif mode not in {
        "storage_failure",
        "mi_failure",
        "deadline",
        "readiness_failure",
        "storage_denied",
        "storage_unknown_error",
        "nonfinite_output",
    }:
        assert len(transport.requests) == 8
        assert all(
            headers["x-ms-range"] == f"bytes=0-{collector.MAX_DOCUMENT_BYTES}"
            for method, _, headers, _ in transport.requests
            if method == "GET"
        )
        assert all(
            "Encrypt=Yes;TrustServerCertificate=No;" in connection
            for connection, _ in driver.connections
        )
        assert all(
            collector.ENDPOINT["database"] in connection
            for connection, _ in driver.connections
        )
        assert any(timeout == 20 for _, _, timeout in driver.calls)
        assert {timeout for _, _, timeout in driver.calls} == {20, 30}
        for _, options in driver.connections:
            assert options["timeout"] in {20, 30}
            packed = options["attrs_before"][1256]
            assert struct.unpack("<I", packed[:4])[0] == len(packed[4:])
            assert packed[4:].decode("utf-16-le") == "offline-not-an-entra-token"
