"""Offline cryptographic qualification; fixture keys are never runtime trust."""

import base64
import copy
import hashlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from ontology_discovery.maintenance_release import (
    ISSUER_ROLE,
    PURPOSE_LIVE,
    REQUIRED_APPROVAL_ROLES,
    MaintenanceDenied,
    MaintenanceRelease,
    TrustContext,
    TrustedKey,
    approval_message,
    canonical_json,
    digest,
)
from ontology_discovery.publication_authority import PublicationAuthorityIssuer

TARGET_ID = "191c9b47-2839-4983-97e8-2d8c6f1889eb"
OWNER = "38666bd3-5d4d-4d24-9fe3-fe279785ca93"
SESSION = "0c757db0-50c7-4e42-923c-1d674c9d4961"
ATTEMPT = "18655a3e-83af-46ce-a0c2-4659f1831ad5"


@pytest.fixture
def scenario(tmp_path):
    now = datetime(2026, 10, 30, 8, 0, tzinfo=UTC)
    target = {
        "tenant_id": "262a3a77-7d74-4684-8937-897d98d2a17a",
        "subscription_id": "890c9bfc-d09c-4143-9ce5-465e75e3eecc",
        "connection_id": "demo",
        "workspace_id": "2c1fea36-104d-4c26-86db-12e09e432b41",
        "item_id": TARGET_ID,
        "definition_fingerprint": "sha256:" + "1" * 64,
    }
    release = MaintenanceRelease(
        release_id="qualified-release",
        attestation_digest="a" * 64,
        purpose=PURPOSE_LIVE,
        revocation_revision=4,
        **target,
        sources=("inventory", "monitor"),
        pair=("app", "uses", "app"),
        lineage={"model": "pinned"},
        ontology_version="v2",
        operations=frozenset({"admit", "restore"}),
        max_model_edges=1,
        expires_at=now + timedelta(minutes=5),
    )
    private = {}

    def key(identity, role):
        private[identity] = Ed25519PrivateKey.generate()
        return TrustedKey(
            identity + "-key",
            private[identity].public_key().public_bytes(Encoding.Raw, PublicFormat.Raw),
            frozenset({role}),
        )

    issuer = key("issuer", ISSUER_ROLE)
    approvers = {role: key(role, role) for role in REQUIRED_APPROVAL_ROLES}
    trust = TrustContext(
        purpose=PURPOSE_LIVE,
        environment="dev",
        implementation_digest="i",
        identity_digest="id",
        template_digest="t",
        root_capability_digest="r",
        issuers={"issuer": issuer},
        approvers=approvers,
        artifact_root=tmp_path,
    )
    catalog = '{"candidate":{"generation_id":"actual-sealed-attempt"}}'
    payload = {
        "version": "publication-authority-review/v1",
        "environment": "dev",
        "implementation_digest": "i",
        "identity_digest": "id",
        "template_digest": "t",
        "root_capability_digest": "r",
        "issuer": {"issuer_id": "issuer", "key_id": issuer.key_id, "role": ISSUER_ROLE},
        "target_id": TARGET_ID,
        "target": target,
        "owner_id": OWNER,
        "session_id": SESSION,
        "epoch": 1,
        "attempt_id": ATTEMPT,
        "catalog_digest": hashlib.sha256(catalog.encode()).hexdigest(),
        "operation": "admit",
        "release_binding": release.authorization_binding(),
        "evidence_digest": "e" * 64,
        "issued_at": now.isoformat(),
        "valid_from": now.isoformat(),
        "valid_until": (now + timedelta(minutes=1)).isoformat(),
        "revocation_revision": 4,
        "approvals": [],
    }
    control_value = {
        "target_id": TARGET_ID,
        "owner_id": OWNER,
        "session_id": SESSION,
        "epoch": 1,
        "session_deadline": (now + timedelta(minutes=3)).isoformat(),
    }
    control = Mock()
    control.read_control.return_value = control_value
    control.read_attempt.return_value = {"catalog_json": catalog}
    authority = Mock()
    reader = Mock()
    reader.read.return_value = release
    state = {
        "kill": False,
        "revocation_revision": 4,
        "revoked_key_ids": [],
        "revoked_reviews": [],
    }
    envelope = {}

    def sign():
        payload["approvals"] = []
        binding = digest({k: v for k, v in payload.items() if k != "approvals"})
        for role, trusted in approvers.items():
            approval = {
                "role": role,
                "approver_id": role,
                "key_id": trusted.key_id,
                "reason": "Reviewed exact isolated DEV attempt",
                "expires_at": payload["valid_until"],
            }
            approval["signature"] = base64.b64encode(
                private[role].sign(approval_message(binding, approval))
            ).decode()
            payload["approvals"].append(approval)
        envelope.clear()
        envelope.update(
            algorithm="Ed25519",
            key_id=issuer.key_id,
            payload=copy.deepcopy(payload),
            signature=base64.b64encode(
                private["issuer"].sign(canonical_json(payload))
            ).decode(),
        )

    sign()
    clock = Mock(return_value=now)
    issuer_adapter = PublicationAuthorityIssuer(
        trust=trust,
        release_reader=reader,
        control=control,
        authority=authority,
        target_id=TARGET_ID,
        expected_target=target,
        review_source=lambda: envelope,
        revocation_source=lambda: state,
        clock=clock,
    )
    return SimpleNamespace(
        issuer=issuer_adapter,
        payload=payload,
        envelope=envelope,
        sign=sign,
        state=state,
        reader=reader,
        control=control,
        authority=authority,
        release=release,
        now=now,
        clock=clock,
        private=private,
        trust=trust,
    )


@pytest.mark.parametrize("operation", ["admit", "restore"])
def test_exact_signed_review_records_only_separate_authority_grant(scenario, operation):
    s = scenario
    s.payload["operation"] = operation
    s.sign()
    result = s.issuer.issue(operation)
    assert result == digest(s.envelope)
    s.authority.record_grant.assert_called_once_with(
        TARGET_ID,
        SESSION,
        1,
        catalog_digest=s.payload["catalog_digest"],
        operation=operation,
        authority_digest=result,
        evidence_digest=s.payload["evidence_digest"],
        valid_from=s.now,
        valid_until=s.now + timedelta(minutes=1),
    )
    assert s.control.read_control.call_count == 2
    assert s.reader.read.call_count == 2


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("version", "maintenance-attestation/v1"),
        ("environment", "prod"),
        ("implementation_digest", "changed"),
        ("target_id", SESSION),
        ("target", {}),
        ("session_id", "not-a-uuid"),
        ("epoch", True),
        ("epoch", 0),
        ("catalog_digest", "F" * 64),
        ("evidence_digest", ""),
        ("operation", "restore"),
        ("release_binding", {}),
        ("valid_from", "2026-10-31T00:00:00+00:00"),
        ("valid_until", "2026-10-30T07:59:59+00:00"),
        ("issued_at", "2026-10-30T08:01:00+00:00"),
        ("valid_until", "2026-10-30T08:01:00"),
        ("revocation_revision", True),
    ],
)
def test_signed_wrong_binding_never_reaches_authority(scenario, field, value):
    s = scenario
    s.payload[field] = value
    s.sign()
    with pytest.raises(MaintenanceDenied):
        s.issuer.issue("admit")
    s.authority.record_grant.assert_not_called()


def test_tampered_signature_fails(scenario):
    scenario.envelope["payload"]["evidence_digest"] = "f" * 64
    with pytest.raises(MaintenanceDenied, match="signature_invalid"):
        scenario.issuer.issue("admit")
    scenario.authority.record_grant.assert_not_called()


@pytest.mark.parametrize("change", ["kill", "key", "review", "revision"])
def test_revoked_review_never_reaches_authority(scenario, change):
    s = scenario
    if change == "kill":
        s.state["kill"] = True
    elif change == "key":
        s.state["revoked_key_ids"] = [s.trust.approvers["security_owner"].key_id]
    elif change == "review":
        s.state["revoked_reviews"] = [digest(s.envelope)]
    else:
        s.state["revocation_revision"] += 1
    with pytest.raises(MaintenanceDenied):
        s.issuer.issue("admit")
    s.authority.record_grant.assert_not_called()


@pytest.mark.parametrize("change", ["owner", "session", "epoch", "deadline", "catalog"])
def test_actual_sql_state_mismatch_never_reaches_authority(scenario, change):
    s = scenario
    if change == "catalog":
        s.control.read_attempt.return_value["catalog_json"] = "{}"
    else:
        field, value = {
            "owner": ("owner_id", SESSION),
            "session": ("session_id", OWNER),
            "epoch": ("epoch", 2),
            "deadline": ("session_deadline", s.now.isoformat()),
        }[change]
        s.control.read_control.return_value[field] = value
    with pytest.raises(MaintenanceDenied):
        s.issuer.issue("admit")
    s.authority.record_grant.assert_not_called()


@pytest.mark.parametrize("change", ["release", "session", "revoke", "expiry"])
def test_callback_changes_checked_again_before_write(scenario, change):
    s = scenario
    original = copy.deepcopy(s.control.read_control.return_value)
    if change == "release":
        changed = copy.copy(s.release)
        object.__setattr__(changed, "attestation_digest", "f" * 64)
        s.reader.read.side_effect = [s.release, changed]
    elif change == "session":
        s.control.read_control.side_effect = [
            original,
            {**original, "epoch": 2},
        ]
    elif change == "expiry":
        s.clock.side_effect = [s.now, s.now + timedelta(minutes=2)]
    else:

        def mutate(*args):
            s.state["kill"] = True
            return {
                "catalog_json": '{"candidate":{"generation_id":"actual-sealed-attempt"}}'
            }

        s.control.read_attempt.side_effect = mutate
    with pytest.raises(MaintenanceDenied):
        s.issuer.issue("admit")
    s.authority.record_grant.assert_not_called()


def test_uncertain_sql_write_is_not_retried(scenario):
    scenario.authority.record_grant.side_effect = TimeoutError("uncertain write")
    with pytest.raises(TimeoutError):
        scenario.issuer.issue("admit")
    assert scenario.authority.record_grant.call_count == 1


@pytest.mark.parametrize(
    "change", ["absent", "missing", "duplicate", "bad_signature", "extra"]
)
def test_invalid_approvals_fail_before_sql(scenario, change):
    s = scenario
    payload = s.envelope["payload"]
    if change == "absent":
        payload["approvals"] = None
    elif change == "missing":
        payload["approvals"].pop()
    elif change == "duplicate":
        payload["approvals"].append(copy.deepcopy(payload["approvals"][0]))
    elif change == "extra":
        payload["approvals"][0]["private_key"] = "not accepted"
    else:
        payload["approvals"][0]["signature"] = "invalid"
    s.envelope["signature"] = base64.b64encode(
        s.private["issuer"].sign(canonical_json(payload))
    ).decode()
    with pytest.raises(MaintenanceDenied):
        s.issuer.issue("admit")
    s.authority.record_grant.assert_not_called()
    s.control.read_control.assert_not_called()


def test_same_signing_key_cannot_supply_distinct_approval_roles(scenario):
    s = scenario
    original = s.trust.approvers["security_owner"]
    issuer = s.trust.issuers["issuer"]
    s.trust.approvers["security_owner"] = TrustedKey(
        original.key_id,
        issuer.public_key,
        original.roles,
    )
    with pytest.raises(MaintenanceDenied, match="approval_untrusted"):
        s.issuer.issue("admit")
    s.authority.record_grant.assert_not_called()


def test_expiration_during_final_revocation_callback_denies_write(scenario):
    s = scenario
    s.clock.side_effect = [s.now, s.now, s.now + timedelta(minutes=2)]
    with pytest.raises(MaintenanceDenied, match="review_expired"):
        s.issuer.issue("admit")
    s.authority.record_grant.assert_not_called()


def test_failed_inherited_maintenance_gate_cannot_be_bypassed(scenario):
    s = scenario
    s.reader.read.side_effect = MaintenanceDenied("prerequisite_incomplete")
    with pytest.raises(MaintenanceDenied, match="prerequisite_incomplete"):
        s.issuer.issue("admit")
    s.authority.record_grant.assert_not_called()


def test_unsealed_or_expired_attempt_refusal_propagates_without_grant(scenario):
    s = scenario
    s.control.read_attempt.side_effect = RuntimeError("sealed attempt unavailable")
    with pytest.raises(RuntimeError, match="sealed attempt unavailable"):
        s.issuer.issue("admit")
    s.authority.record_grant.assert_not_called()


def test_actual_sql_datetime2_json_deadline_is_known_utc(scenario):
    s = scenario
    s.control.read_control.return_value["session_deadline"] = (
        (s.now + timedelta(minutes=3)).replace(tzinfo=None).isoformat()
    )
    s.issuer.issue("admit")
    s.authority.record_grant.assert_called_once()
