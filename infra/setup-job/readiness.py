"""Verify the reusable setup runtime without reading secrets or mutating Azure."""

import importlib.metadata
import json
import os
import socket


def _driver_names() -> list[str]:
    try:
        import pyodbc
    except ImportError:
        return []
    return pyodbc.drivers()


def main() -> None:
    """Emit bounded runtime and private-DNS readiness; fail explicitly on mismatch."""
    host = "aiops-dev-kv-7h0ih3.vault.azure.net"
    addresses = sorted({row[4][0] for row in socket.getaddrinfo(host, 443)})
    if addresses != ["10.50.8.4"]:
        raise RuntimeError("setup_readiness:unexpected_vault_private_dns")
    if os.getuid() != 10001:
        raise RuntimeError("setup_readiness:unexpected_uid")
    if "ODBC Driver 18 for SQL Server" not in _driver_names():
        raise RuntimeError("setup_readiness:odbc_driver_missing")
    if not os.environ.get("AZURE_CLIENT_ID"):
        raise RuntimeError("setup_readiness:identity_not_configured")
    print(
        "SETUP_JOB_READINESS="
        + json.dumps(
            {
                "status": "ready",
                "uid": os.getuid(),
                "vault_private_dns": addresses,
                "identity_client_id": os.environ["AZURE_CLIENT_ID"],
                "packages": {
                    name: importlib.metadata.version(name)
                    for name in ("azure-identity", "azure-storage-blob", "pyodbc")
                },
                "cloud_mutations": False,
                "secret_values_read": False,
            },
            sort_keys=True,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
