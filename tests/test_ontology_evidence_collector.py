from __future__ import annotations

import json

import pytest

from scripts.collect_ontology_evidence import (
    EvidenceCollectionError,
    _collect_api,
    _list_fixed_paths,
    build_closed_record,
    decode_identity_claims,
    sanitize_closed_record,
    summarize_lifecycle_documents,
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


def test_api_observation_uses_managed_identity_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def request(
        method: str,
        url: str,
        *,
        token: str | None = None,
        json_body: object = None,
    ) -> object:
        observed.update(
            method=method,
            url=url,
            token=token,
            json_body=json_body,
        )
        return {"data": []}

    monkeypatch.setattr(
        "scripts.collect_ontology_evidence._request_json",
        request,
    )

    result = _collect_api(
        {"AIOPS_EVIDENCE_API_URL": "https://api.example"},
        "managed-identity-token",
    )

    assert observed == {
        "method": "GET",
        "url": "https://api.example/api/v1/connections?limit=1",
        "token": "managed-identity-token",
        "json_body": None,
    }
    assert result["count"] == 1


def test_missing_optional_onelake_prefix_is_an_empty_observation() -> None:
    class MissingPath(Exception):
        status_code = 404

    class Client:
        def get_paths(self, **_: object) -> object:
            raise MissingPath

    assert _list_fixed_paths(Client(), path="missing", root="state") == []


def test_onelake_authorization_failure_remains_blocking() -> None:
    class Forbidden(Exception):
        status_code = 403

    class Client:
        def get_paths(self, **_: object) -> object:
            raise Forbidden

    with pytest.raises(EvidenceCollectionError, match="state root"):
        _list_fixed_paths(Client(), path="forbidden", root="state")


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


def test_lifecycle_documents_reduce_to_closed_hashes_counts_and_states() -> None:
    fixture = {
        "revision": 4,
        "drills": [
            {
                "drill_id": "raw-drill-id",
                "drill_hash": "raw-server-hash",
                "owner_hash": "raw-owner-hash",
                "fence": 7,
                "status": "prepared",
                "connection_ids": [
                    "ontology-fixture-a-head-change",
                    "ontology-fixture-a-retry-rotation",
                    "ontology-fixture-a-later-restart",
                ],
                "epoch_id": "ODE-RAW",
                "prepared_at": "2026-09-07T00:00:00+00:00",
                "expires_at": "2026-09-07T02:00:00+00:00",
                "receipts": [{"event": "prepared", "at": "raw-time"}],
            }
        ],
    }
    registry = {
        "revision": 9,
        "connections": [
            {
                "connection_id": f"ontology-fixture-a-{role}",
                "metadata": {"fixture_role": role},
            }
            for role in ("head-change", "retry-rotation", "later-restart")
        ],
    }
    state = {
        "revision": 12,
        "eligible_epochs": [
            {
                "epoch_id": "ODE-RAW",
                "status": "active",
                "cursor": 2,
                "member_order": [
                    "ontology-fixture-a-head-change",
                    "ontology-fixture-a-retry-rotation",
                    "ontology-fixture-a-later-restart",
                ],
                "members": {
                    "ontology-fixture-a-head-change": {
                        "outcome": "duplicate",
                        "attempt_count": 1,
                        "reason_code": "logical_run_already_completed",
                        "updated_at": "raw-time",
                    },
                    "ontology-fixture-a-retry-rotation": {
                        "outcome": "pending",
                        "attempt_count": 1,
                        "reason_code": "run_claim_contended",
                        "updated_at": "raw-time",
                    },
                    "ontology-fixture-a-later-restart": {
                        "outcome": "succeeded",
                        "attempt_count": 1,
                        "reason_code": "publisher_dispatch_created",
                        "updated_at": "raw-time",
                    },
                },
            }
        ],
    }

    facts = summarize_lifecycle_documents(
        fixture=fixture,
        registry=registry,
        state=state,
    )

    assert facts["fixture"]["active_drill_count"] == 1
    assert facts["fixture"]["record_count"] == 3
    assert facts["fixture"]["ttl_bounded"] is True
    assert facts["registry"]["active_fixture_count"] == 3
    assert facts["epoch"]["active_epoch_count"] == 1
    assert facts["epoch"]["cursor"] == 2
    assert [row["outcome"] for row in facts["epoch"]["members"]] == [
        "duplicate",
        "pending",
        "succeeded",
    ]
    rendered = json.dumps(facts, sort_keys=True)
    for raw in (
        "raw-drill-id",
        "raw-server-hash",
        "raw-owner-hash",
        "ODE-RAW",
        "ontology-fixture-a-head-change",
        "raw-time",
    ):
        assert raw not in rendered


def test_closed_record_accepts_only_sanitized_lifecycle_facts() -> None:
    identity = {
        "client_id_hash": "sha256:" + "1" * 64,
        "object_id_hash": "sha256:" + "2" * 64,
        "managed_identity_resource_hash": "sha256:" + "3" * 64,
        "entra_signature_hash": "sha256:" + "4" * 64,
    }
    observations = {
        name: {"count": 1, "hashes": ["sha256:" + char * 64]}
        for name, char in zip(
            ("arg", "fabric", "onelake", "api"),
            ("5", "6", "7", "8"),
            strict=True,
        )
    }
    facts = {
        "fixture": {
            "active_drill_count": 0,
            "record_hashes": [],
            "status": "cleaned",
        }
    }
    record = build_closed_record(
        identity=identity,
        observations=observations,
        capabilities={
            "azure": ["read"],
            "fabric": ["Viewer"],
            "onelake": ["Read"],
            "denied": ["job_start", "mutation"],
        },
        facts=facts,
    )
    assert record["facts"] == facts

    with pytest.raises(EvidenceCollectionError, match="sensitive"):
        build_closed_record(
            identity=identity,
            observations=observations,
            capabilities={
                "azure": ["read"],
                "fabric": ["Viewer"],
                "onelake": ["Read"],
                "denied": ["job_start", "mutation"],
            },
            facts={"fixture": {"path": "Files/raw"}},
        )
