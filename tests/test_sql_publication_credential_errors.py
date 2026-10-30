"""Supported Azure credential diagnostics stay inside the SQL control boundary."""

import traceback
from types import SimpleNamespace

import pytest
from azure.core.exceptions import AzureError, ClientAuthenticationError
from azure.identity import CredentialUnavailableError

from ontology_discovery.sql_publication_control import (
    SqlPublicationControl,
    SqlPublicationError,
)
from tests.test_sql_publication_control import TARGET, UID

pyodbc = pytest.importorskip("pyodbc", reason="Existing .[fabric-sql] extra required")


@pytest.mark.parametrize(
    "error_type", [AzureError, ClientAuthenticationError, CredentialUnavailableError]
)
def test_credential_diagnostics_sanitized_without_driver_connection(
    monkeypatch, error_type
):
    monkeypatch.setattr(pyodbc, "pooling", False)
    monkeypatch.setattr(pyodbc, "drivers", lambda: ["ODBC Driver 18 for SQL Server"])
    monkeypatch.setattr(
        pyodbc,
        "connect",
        lambda *_args, **_kwargs: pytest.fail("Credential failure reached ODBC"),
    )

    def token(_scope):
        raise error_type(
            "provider diagnostic https://private-control.example/?secret=credential-context"
        )

    with pytest.raises(SqlPublicationError, match="procedure_failed") as failure:
        SqlPublicationControl(
            TARGET, SimpleNamespace(get_token=token), expected_client_id=UID
        ).read_control(
            "00000000-0000-0000-0000-000000000002",
        )
    trace = "".join(traceback.format_exception(failure.value))
    assert "private-control.example" not in trace and "credential-context" not in trace


def test_unsupported_programming_error_is_not_swallowed_as_provider_failure(
    monkeypatch,
):
    monkeypatch.setattr(pyodbc, "pooling", False)
    monkeypatch.setattr(pyodbc, "drivers", lambda: ["ODBC Driver 18 for SQL Server"])

    def invalid_credential(_scope):
        raise TypeError("test programming error")

    with pytest.raises(TypeError, match="programming error"):
        SqlPublicationControl(
            TARGET,
            SimpleNamespace(get_token=invalid_credential),
            expected_client_id=UID,
        ).read_control(
            "00000000-0000-0000-0000-000000000002",
        )
