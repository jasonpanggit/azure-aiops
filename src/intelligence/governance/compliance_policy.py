"""Scope-exact architecture assessment policy and exception decisions.

These decisions affect the architecture assessment only. They never authorize
remediation or modify provider-side policy. Stored browser preferences are not
imported as approvals.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore


class DesignPolicy(BaseModel):
    """Validated architecture assessment parameters."""

    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    name: str = Field(default="Approved hub-spoke landing-zone baseline", min_length=1, max_length=200)
    requiredHubRouting: bool = True
    firewallInspectionRequired: bool = True
    environmentIsolationRequired: bool = True
    allowedPorts: str = Field(default="443, 1433, 5671", max_length=1000)
    privateEndpointRequiredFor: str = Field(
        default="microsoft.sql, microsoft.storage, microsoft.keyvault, microsoft.web",
        max_length=2000,
    )
    requiredDnsZones: str = Field(
        default="privatelink.database.windows.net, privatelink.blob.core.windows.net, privatelink.vaultcore.azure.net",
        max_length=2000,
    )
    loggingRequired: bool = True
    ownerTag: str = Field(default="owner", min_length=1, max_length=128)
    allowCrossSubscriptionPeering: bool = False

    @field_validator("allowedPorts")
    @classmethod
    def ports(cls, value: str) -> str:
        """Accept only concrete TCP/UDP port numbers, not arbitrary expressions."""
        for port in value.split(","):
            if port.strip() and (not port.strip().isdigit() or not 1 <= int(port) <= 65535):
                raise ValueError("Allowed ports must be comma-separated integers from 1 to 65535")
        return value


class PolicyChange(BaseModel):
    """A revision-bound policy replacement with operator rationale."""

    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    expected_revision: int = Field(ge=0)
    policy: DesignPolicy
    reason: str = Field(min_length=1, max_length=1000)


class ExceptionDecision(BaseModel):
    """A revision-bound acceptance or revocation for one assessed finding."""

    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    expected_revision: int = Field(ge=0)
    action: Literal["accept", "revoke"]
    violationId: str = Field(min_length=1, max_length=2048)
    owner: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=1000)
    expiresAt: str = Field(default="", max_length=40)


class CompliancePolicyStore:
    """Persist policy, decisions, and audit atomically using storage ETags."""

    def __init__(self, documents: OneLakeDocumentStore) -> None:
        self.documents = documents

    @staticmethod
    def _name(scope: dict[str, Any]) -> str:
        encoded = json.dumps(scope, sort_keys=True, separators=(",", ":")).encode()
        return f"state/compliance/{hashlib.sha256(encoded).hexdigest()}.json"

    @staticmethod
    def _default(scope: dict[str, Any]) -> dict[str, Any]:
        return {
            "revision": 0, "policy_revision": 0, "scope": scope,
            "policy": DesignPolicy().model_dump(), "exceptions": [], "audit": [],
        }

    def read(self, scope: dict[str, Any]) -> dict[str, Any]:
        """Read exactly this scope; missing documents show unapplied defaults."""
        snapshot = self.documents.read_snapshot(self._name(scope))
        state = snapshot.payload if snapshot.exists else self._default(scope)
        return self._view(state)

    @staticmethod
    def _view(state: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(UTC)
        return {
            **state,
            "exceptions": [
                {
                    **item,
                    "active": not item.get("revoked_at")
                    and item["policy_revision"] == state["policy_revision"]
                    and datetime.fromisoformat(item["expiresAt"]) > now,
                }
                for item in state["exceptions"]
            ],
        }

    def update(
        self,
        scope: dict[str, Any],
        change: PolicyChange | ExceptionDecision,
        actor: str,
    ) -> dict[str, Any]:
        """Apply one checked decision; conflicts never overwrite another writer."""
        name = self._name(scope)
        snapshot = self.documents.read_snapshot(name)
        state = snapshot.payload if snapshot.exists else self._default(scope)
        if state["revision"] != change.expected_revision:
            raise DocumentConflictError("Compliance policy changed; reload before deciding")
        now = datetime.now(UTC)
        at = now.isoformat()
        if len(state["audit"]) >= 10000:
            raise ValueError("Compliance audit requires archival before more decisions")
        if isinstance(change, PolicyChange):
            state["policy"] = change.policy.model_dump()
            state["policy_revision"] += 1
            action = "replace_policy"
        else:
            action = change.action
            if action == "accept":
                try:
                    expires = datetime.fromisoformat(change.expiresAt)
                except ValueError as exc:
                    raise ValueError("Expiry must be an ISO timestamp with timezone") from exc
                if expires.tzinfo is None or expires <= now:
                    raise ValueError("Expiry must be a future timestamp with timezone")
                existing = [item for item in state["exceptions"] if item["violationId"] == change.violationId and not item.get("revoked_at")]
                for item in existing:
                    item["revoked_at"] = at
                state["exceptions"].append({
                    "exception_id": str(uuid4()), "violationId": change.violationId,
                    "owner": change.owner, "reason": change.reason,
                    "expiresAt": expires.astimezone(UTC).isoformat(),
                    "approved_by": actor, "approved_at": at,
                    "policy_revision": state["policy_revision"], "revoked_at": "",
                })
            else:
                matching = [item for item in state["exceptions"] if item["violationId"] == change.violationId and not item.get("revoked_at")]
                if not matching:
                    raise ValueError("No current exception matches this finding")
                for item in matching:
                    item["revoked_at"] = at
        state["revision"] += 1
        state["audit"].append({
            "revision": state["revision"], "actor": actor, "at": at,
            "action": action, "reason": change.reason,
            "change": change.model_dump(exclude={"expected_revision"}),
        })
        if snapshot.exists:
            self.documents.replace_if_match(name, state, expected_etag=snapshot.etag)
        else:
            self.documents.create_only(name, state)
        return self._view(state)
