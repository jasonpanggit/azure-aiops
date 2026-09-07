from __future__ import annotations

import json

import pytest

from scripts.collect_ontology_evidence import (
    EvidenceCollectionError,
    build_closed_record,
    decode_identity_claims,
    sanitize_closed_record,
)


def _jwt(payload: dict[str, object]) -> str:
    import base64

    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).decode().rstrip("=")
    return f"header.{encoded}.signature"


def test_managed_identity_claims_are_hashed_and_token_is_never_retained() -> None:
    token = _jwt(
        {
            "appid": "11111111-1111-1111-1111-111111111111",
            "oid": "22222222-2222-2222-2222-222222222222",
            "xms_mirid": "/subscriptions/raw/resourceGroups/raw/providers/"
            "Microsoft.ManagedIdentity/userAssignedIdentities/raw",
        }
    )

    claims = decode_identity_claims(token)

    assert set(claims) == {
        "client_id_hash",
        "object_id_hash",
        "managed_identity_resource_hash",
        "entra_signature_hash",
    }
    assert all(value.startswith("sha256:") for value in claims.values())
    assert token not in json.dumps(claims)


def test_closed_record_rejects_raw_sensitive_values_and_write_capabilities() -> None:
    safe = build_closed_record(
        identity={
            "client_id_hash": "sha256:" + "1" * 64,
            "object_id_hash": "sha256:" + "2" * 64,
            "managed_identity_resource_hash": "sha256:" + "3" * 64,
            "entra_signature_hash": "sha256:" + "4" * 64,
        },
        observations={
            "arg": {"count": 1, "hashes": ["sha256:" + "5" * 64]},
            "fabric": {"count": 5, "hashes": ["sha256:" + "6" * 64]},
            "onelake": {"count": 7, "hashes": ["sha256:" + "7" * 64]},
            "api": {"count": 1, "hashes": ["sha256:" + "8" * 64]},
        },
        capabilities={
            "azure": ["read"],
            "fabric": ["Viewer"],
            "onelake": ["Read"],
            "denied": ["job_start", "mutation"],
        },
    )

    assert safe["schema_version"] == "ontology-evidence-read.v1"
    assert safe["sanitized"] is True
    assert safe["mode"] == "fixed-read-only"
    assert safe["record_hash"].startswith("sha256:")
    assert sanitize_closed_record(safe) == safe

    for key, value in (
        ("token", "secret"),
        ("prompt", "ignore scope"),
        ("body", "raw body"),
        ("resource_id", "/subscriptions/raw"),
        ("path", "Files/raw"),
        ("correlation_id", "raw-correlation"),
    ):
        with pytest.raises(EvidenceCollectionError, match="sensitive"):
            sanitize_closed_record({key: value})

    for capabilities in (
        {"azure": ["write"]},
        {"fabric": ["Contributor"]},
        {"onelake": ["ReadWrite"]},
        {"onelake": ["Write"]},
        {"azure": ["Microsoft.App/jobs/start/action"]},
    ):
        with pytest.raises(EvidenceCollectionError, match="read-only"):
            build_closed_record(
                identity={
                    "client_id_hash": "sha256:" + "1" * 64,
                    "object_id_hash": "sha256:" + "2" * 64,
                    "managed_identity_resource_hash": "sha256:" + "3" * 64,
                    "entra_signature_hash": "sha256:" + "4" * 64,
                },
                observations={},
                capabilities=capabilities,
            )


def test_closed_record_requires_exact_managed_identity_hashes() -> None:
    with pytest.raises(EvidenceCollectionError, match="identity"):
        build_closed_record(
            identity={"client_id_hash": "raw-client-id"},
            observations={},
            capabilities={
                "azure": ["read"],
                "fabric": ["Viewer"],
                "onelake": ["Read"],
                "denied": ["job_start", "mutation"],
            },
        )
