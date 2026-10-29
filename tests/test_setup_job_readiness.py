"""Readiness checks must fail closed without contacting the vault data plane."""

import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import pytest


def _module():
    path = Path(__file__).parents[1] / "infra/setup-job/readiness.py"
    spec = importlib.util.spec_from_file_location("setup_readiness", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("addresses", "uid", "drivers", "client_id", "error"),
    [
        (["20.1.1.1"], 10001, ["ODBC Driver 18 for SQL Server"], "client", "private_dns"),
        (["10.50.8.4"], 0, ["ODBC Driver 18 for SQL Server"], "client", "uid"),
        (["10.50.8.4"], 10001, [], "client", "odbc_driver_missing"),
        (["10.50.8.4"], 10001, ["ODBC Driver 18 for SQL Server"], "", "identity"),
        (["10.50.8.4"], 10001, ["ODBC Driver 18 for SQL Server"], "client", None),
    ],
)
def test_readiness(addresses, uid, drivers, client_id, error, capsys):
    module = _module()
    dns = [(None, None, None, None, (address, 443)) for address in addresses]
    with (
        patch.object(module.socket, "getaddrinfo", return_value=dns),
        patch.object(module.os, "getuid", return_value=uid),
        patch.object(module, "_driver_names", return_value=drivers),
        patch.object(module.importlib.metadata, "version", return_value="verified"),
        patch.dict(module.os.environ, {"AZURE_CLIENT_ID": client_id}, clear=True),
    ):
        if error:
            with pytest.raises(RuntimeError, match=error):
                module.main()
            assert not capsys.readouterr().out
        else:
            module.main()
            receipt = json.loads(capsys.readouterr().out.split("=", 1)[1])
            assert receipt["status"] == "ready"
            assert receipt["cloud_mutations"] is False
            assert receipt["secret_values_read"] is False
