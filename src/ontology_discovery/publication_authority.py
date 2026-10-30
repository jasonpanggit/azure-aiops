"""Explicit publication review-to-SQL authority composition, never worker wiring."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from ontology_discovery.maintenance_release import (
    ISSUER_ROLE,
    PURPOSE_LIVE,
    REQUIRED_APPROVAL_ROLES,
    MaintenanceDenied,
    MaintenanceReleaseReader,
    TrustContext,
    _verify_signature,
    approval_message,
    canonical_json,
    digest,
)
from ontology_discovery.sql_publication_control import (
    SqlPublicationAuthority,
    SqlPublicationControl,
)

_VERSION = "publication-authority-review/v1"
_TARGET_FIELDS = frozenset(
    {
        "tenant_id",
        "subscription_id",
        "connection_id",
        "workspace_id",
        "item_id",
        "definition_fingerprint",
    }
)
_PAYLOAD_FIELDS = frozenset(
    {
        "version",
        "environment",
        "implementation_digest",
        "identity_digest",
        "template_digest",
        "root_capability_digest",
        "issuer",
        "target_id",
        "target",
        "owner_id",
        "session_id",
        "epoch",
        "attempt_id",
        "catalog_digest",
        "operation",
        "release_binding",
        "evidence_digest",
        "issued_at",
        "valid_from",
        "valid_until",
        "revocation_revision",
        "approvals",
    }
)


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise MaintenanceDenied("publication_authority:" + reason)


def _time(value: Any) -> datetime:
    try:
        result = datetime.fromisoformat(value)
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError
        return result.astimezone(UTC)
    except (ValueError, TypeError):
        raise MaintenanceDenied("publication_authority:time_invalid") from None


def _uuid(value: Any) -> str:
    try:
        _require(type(value) is str and str(UUID(value)) == value, "uuid_invalid")
    except (ValueError, AttributeError):
        raise MaintenanceDenied("publication_authority:uuid_invalid") from None
    return value


def _sql_deadline(value: Any) -> datetime:
    # SessionDeadline is UTC datetime2; SQL FOR JSON omits its timezone suffix.
    try:
        result = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        raise MaintenanceDenied("publication_authority:sql_deadline_invalid") from None
    return (
        result.replace(tzinfo=UTC) if result.tzinfo is None else result.astimezone(UTC)
    )


class PublicationAuthorityIssuer:
    """Verify fresh independently signed review before a separate SQL grant.

    All dependencies are server/operator-owned. No default credentials, listener,
    signing keys or bootstrap are installed. The authority credential must never
    be the worker, broker, verifier or artifact credential. SQL permissions remain
    the deployment-enforced boundary; constructor injection cannot establish them.
    """

    def __init__(
        self,
        *,
        trust: TrustContext,
        release_reader: MaintenanceReleaseReader,
        control: SqlPublicationControl,
        authority: SqlPublicationAuthority,
        target_id: str,
        expected_target: Mapping[str, str],
        review_source: Callable[[], Mapping[str, Any] | None],
        revocation_source: Callable[[], Mapping[str, Any]],
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        _require(trust.purpose == PURPOSE_LIVE, "live_trust_required")
        _require(
            set(expected_target) == _TARGET_FIELDS
            and all(type(v) is str and bool(v) for v in expected_target.values()),
            "target_invalid",
        )
        self._target_id = _uuid(target_id)
        self._target = dict(expected_target)
        self._trust, self._release = trust, release_reader
        self._control, self._authority = control, authority
        self._review_source, self._revocation_source = review_source, revocation_source
        self._clock = clock or (lambda: datetime.now(UTC))

    def _revocations(self, payload: Mapping[str, Any], envelope_digest: str) -> None:
        state = self._revocation_source()
        _require(isinstance(state, Mapping), "revocation_unavailable")
        _require(
            set(state)
            == {
                "kill",
                "revocation_revision",
                "revoked_key_ids",
                "revoked_reviews",
            }
            and state["kill"] is False
            and type(state["revocation_revision"]) is int
            and state["revocation_revision"] >= 0
            and type(payload["revocation_revision"]) is int
            and state["revocation_revision"] == payload["revocation_revision"]
            and type(state["revoked_key_ids"]) is list
            and all(type(v) is str for v in state["revoked_key_ids"])
            and type(state["revoked_reviews"]) is list
            and all(type(v) is str for v in state["revoked_reviews"]),
            "revocation_invalid",
        )
        key_ids = [payload["issuer"]["key_id"]] + [
            approval["key_id"] for approval in payload["approvals"]
        ]
        _require(
            not set(key_ids).intersection(state["revoked_key_ids"])
            and envelope_digest not in state["revoked_reviews"],
            "review_revoked",
        )

    def _session(self, payload: Mapping[str, Any], now: datetime) -> None:
        control = self._control.read_control(self._target_id)
        _require(
            control.get("target_id") == self._target_id
            and control.get("owner_id") == payload["owner_id"]
            and control.get("session_id") == payload["session_id"]
            and type(control.get("epoch")) is int
            and control["epoch"] == payload["epoch"]
            and _sql_deadline(control.get("session_deadline"))
            >= _time(payload["valid_until"])
            and _sql_deadline(control.get("session_deadline")) > now,
            "session_changed",
        )

    def issue(self, operation: str) -> str:
        """Record one verified grant; return its signed-envelope digest.

        Does not acquire a session, seal artifacts, commit publication or retry
        an uncertain SQL write. Revoke uses the existing separate SQL authority
        client and must be dispatched by the operator's fresh revocation policy.
        """
        _require(
            type(operation) is str and operation in {"admit", "restore"},
            "operation_invalid",
        )
        envelope = self._review_source()
        _require(isinstance(envelope, Mapping), "review_absent")
        _require(
            set(envelope) == {"algorithm", "key_id", "payload", "signature"}
            and envelope["algorithm"] == "Ed25519"
            and isinstance(envelope["payload"], Mapping),
            "envelope_invalid",
        )
        # Snapshot operator-owned inputs before callbacks can change nested data.
        try:
            envelope = json.loads(canonical_json(envelope))
        except (ValueError, TypeError):
            raise MaintenanceDenied("publication_authority:review_invalid") from None
        payload = envelope["payload"]
        _require(set(payload) == _PAYLOAD_FIELDS, "payload_invalid")
        _require(payload["version"] == _VERSION, "version_invalid")
        for field in (
            "environment",
            "implementation_digest",
            "identity_digest",
            "template_digest",
            "root_capability_digest",
        ):
            _require(
                bool(getattr(self._trust, field))
                and payload[field] == getattr(self._trust, field),
                "deployment_mismatch",
            )
        _require(
            payload["target_id"] == self._target_id
            and payload["target"] == self._target
            and payload["operation"] == operation,
            "binding_mismatch",
        )
        for field in ("owner_id", "session_id", "attempt_id"):
            _uuid(payload[field])
        _require(
            type(payload["epoch"]) is int and 1 <= payload["epoch"] < 2**63, "epoch"
        )
        for field in ("catalog_digest", "evidence_digest"):
            _require(
                type(payload[field]) is str
                and re.fullmatch(r"[a-f0-9]{64}", payload[field]) is not None,
                "digest",
            )
        issuer = payload["issuer"]
        _require(
            type(issuer) is dict
            and set(issuer) == {"issuer_id", "key_id", "role"}
            and all(type(value) is str for value in issuer.values()),
            "issuer_invalid",
        )
        trusted = self._trust.issuers.get(issuer["issuer_id"])
        _require(
            trusted is not None
            and trusted.key_id == issuer["key_id"]
            and envelope["key_id"] == trusted.key_id
            and issuer["role"] == ISSUER_ROLE
            and ISSUER_ROLE in trusted.roles,
            "issuer_untrusted",
        )
        _verify_signature(trusted, canonical_json(payload), envelope["signature"])
        now = self._clock()
        _require(
            now.tzinfo is not None and now.utcoffset() is not None, "clock_invalid"
        )
        start, end = _time(payload["valid_from"]), _time(payload["valid_until"])
        _require(
            _time(payload["issued_at"]) <= now and start <= now < end, "review_expired"
        )
        approvals = payload["approvals"]
        _require(type(approvals) is list, "approvals_invalid")
        base = digest({k: v for k, v in payload.items() if k != "approvals"})
        identities, keys, roles = {issuer["issuer_id"]}, {trusted.public_key}, set()
        for approval in approvals:
            _require(
                type(approval) is dict
                and set(approval)
                == {
                    "role",
                    "approver_id",
                    "key_id",
                    "reason",
                    "expires_at",
                    "signature",
                }
                and all(type(value) is str for value in approval.values()),
                "approval_invalid",
            )
            key = self._trust.approvers.get(approval["approver_id"])
            role = approval["role"]
            _require(
                key is not None
                and key.key_id == approval["key_id"]
                and role in REQUIRED_APPROVAL_ROLES
                and role in key.roles
                and role not in roles
                and approval["approver_id"] not in identities
                and key.public_key not in keys
                and type(approval["reason"]) is str
                and bool(approval["reason"].strip())
                and _time(approval["expires_at"]) >= end,
                "approval_untrusted",
            )
            _verify_signature(
                key, approval_message(base, approval), approval["signature"]
            )
            identities.add(approval["approver_id"])
            keys.add(key.public_key)
            roles.add(role)
        _require(roles == REQUIRED_APPROVAL_ROLES, "approvals_incomplete")
        envelope_digest = digest(envelope)
        self._revocations(payload, envelope_digest)
        release = self._release.read(operation)
        _require(
            release.purpose == PURPOSE_LIVE
            and release.authorization_binding() == payload["release_binding"]
            and all(getattr(release, k) == v for k, v in self._target.items())
            and end <= release.expires_at,
            "release_mismatch",
        )
        self._session(payload, now)
        attempt = self._control.read_attempt(
            self._target_id,
            payload["attempt_id"],
            payload["catalog_digest"],
        )
        catalog = attempt.get("catalog_json")
        _require(
            type(catalog) is str
            and hashlib.sha256(catalog.encode()).hexdigest()
            == payload["catalog_digest"],
            "sealed_catalog_mismatch",
        )
        # Provider callbacks can outlive a review or observe newer control state.
        final_now = self._clock()
        _require(start <= final_now < end, "review_expired")
        _require(
            self._release.read(operation).authorization_binding()
            == release.authorization_binding(),
            "release_changed",
        )
        self._session(payload, final_now)
        self._revocations(payload, envelope_digest)
        _require(start <= self._clock() < end, "review_expired")
        self._authority.record_grant(
            self._target_id,
            payload["session_id"],
            payload["epoch"],
            catalog_digest=payload["catalog_digest"],
            operation=operation,
            authority_digest=envelope_digest,
            evidence_digest=payload["evidence_digest"],
            valid_from=start,
            valid_until=end,
        )
        return envelope_digest
