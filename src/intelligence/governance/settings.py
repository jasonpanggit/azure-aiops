"""Enterprise administration settings.

A single versioned settings document covering roles, taxonomies, onboarding
and architecture policies, vulnerability thresholds, agent policy, retention,
and report templates.

Two deliberate choices:

* **One document, not one per section.** Settings are read together on nearly
  every admin request and written rarely, so a single revision-checked
  document gives cross-section consistency for free and avoids a partial
  configuration being observed mid-update.
* **Defaults only for absence.** Valid older documents are merged over current
  defaults; corrupt or unavailable documents never become fresh defaults.
"""

from __future__ import annotations

import copy
import json
import threading
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from storage.onelake_documents import DocumentConflictError, DocumentSnapshot

SETTINGS_DOCUMENT = "state/enterprise_settings.json"
MAX_SETTINGS_BYTES = 512 * 1024
MAX_SETTINGS_REVISION = 9_007_199_254_740_991

#: Retention is bounded rather than free-form: an unbounded value silently
#: turns into "keep forever", which is a data-governance liability.
_MIN_RETENTION_DAYS = 1
_MAX_RETENTION_DAYS = 3650

_VALID_SECTIONS = (
    "roles",
    "taxonomies",
    "onboarding_policy",
    "architecture_policy",
    "vulnerability_policy",
    "agent_policy",
    "retention_policy",
    "report_templates",
)


def default_settings() -> dict[str, Any]:
    """The settings a fresh tenant starts with.

    Defaults are intentionally conservative: read-only roles, no auto
    approval, and retention at one year.
    """
    return {
        "roles": [
            {
                "role_id": "viewer",
                "name": "Viewer",
                "description": "Read-only access to observed estate data",
                "permissions": ["read"],
            },
            {
                "role_id": "operator",
                "name": "Operator",
                "description": "Can run discovery, sync, and remediation plans",
                "permissions": ["read", "operate"],
            },
            {
                "role_id": "administrator",
                "name": "Administrator",
                "description": "Can manage connections, policy, and settings",
                "permissions": ["read", "operate", "write", "admin"],
            },
        ],
        "taxonomies": {
            "environments": ["production", "staging", "development", "test"],
            "criticalities": ["critical", "high", "medium", "low"],
            "business_services": [],
        },
        "onboarding_policy": {
            "require_business_service": True,
            "require_environment_mapping": True,
            "require_owner": True,
            "allow_self_service": False,
            "credential_expiry_warning_days": 30,
        },
        "architecture_policy": {
            "require_private_endpoints": True,
            "require_nsg_on_subnets": True,
            "deny_public_ip_on_vms": True,
            "require_diagnostic_settings": True,
        },
        "vulnerability_policy": {
            "critical_sla_days": 7,
            "high_sla_days": 30,
            "medium_sla_days": 90,
            "low_sla_days": 180,
            "auto_create_remediation_plan": False,
        },
        "agent_policy": {
            "allow_autonomous_remediation": False,
            "require_human_approval": True,
            "allow_self_approval": False,
            "max_concurrent_investigations": 3,
            "investigation_timeout_seconds": 900,
        },
        "retention_policy": {
            "estate_snapshot_days": 365,
            "audit_log_days": 365,
            "investigation_history_days": 180,
            "export_artifact_days": 90,
        },
        "report_templates": [],
    }


def _merge(defaults: Mapping[str, Any], stored: Mapping[str, Any]) -> dict[str, Any]:
    """Overlay stored values on defaults, one level into each section."""
    merged = copy.deepcopy(dict(defaults))
    for key, value in stored.items():
        if key not in merged:
            continue
        current = merged[key]
        if isinstance(current, dict) and isinstance(value, Mapping):
            current.update(value)
        else:
            merged[key] = value
    return merged


class SettingsValidationError(ValueError):
    """Raised when a settings update would produce an unusable configuration."""


class SettingsChange(BaseModel):
    """A reviewed, attributed enterprise-wide partial settings change."""

    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: int = Field(ge=0, lt=MAX_SETTINGS_REVISION)
    changes: dict[str, Any] = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=1200)

    @field_validator("reason")
    @classmethod
    def meaningful_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A change reason is required")
        return value.strip()


class _LastChange(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    actor: str = Field(min_length=1, max_length=320)
    reason: str = Field(min_length=1, max_length=1200)
    recorded_at: str

    @field_validator("actor", "reason")
    @classmethod
    def meaningful_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Change attribution cannot be blank")
        return value.strip()

    @field_validator("recorded_at")
    @classmethod
    def aware_time(cls, value: str) -> str:
        if datetime.fromisoformat(value).utcoffset() is None:
            raise ValueError("Change time must have a timezone")
        return value


def validate_settings(settings: Mapping[str, Any]) -> None:
    """Reject updates that would break invariants callers depend on."""
    unknown = set(settings) - set(_VALID_SECTIONS)
    if unknown:
        raise SettingsValidationError(
            f"Unknown settings sections: {', '.join(sorted(unknown))}"
        )

    defaults = default_settings()
    for section in _VALID_SECTIONS:
        if section not in settings:
            continue
        value = settings[section]
        if isinstance(defaults[section], dict):
            if not isinstance(value, Mapping):
                raise SettingsValidationError(f"{section} must be a mapping")
            for key, expected in defaults[section].items():
                if key not in value:
                    continue
                actual = value[key]
                if isinstance(expected, bool) and type(actual) is not bool:
                    raise SettingsValidationError(f"{section}.{key} must be a boolean")
                if type(expected) is int and (
                    type(actual) is not int or not 1 <= actual <= MAX_SETTINGS_REVISION
                ):
                    raise SettingsValidationError(f"{section}.{key} must be a positive integer")
                if isinstance(expected, list) and (
                    not isinstance(actual, list)
                    or not all(isinstance(item, str) for item in actual)
                ):
                    raise SettingsValidationError(f"{section}.{key} must be a string list")
        elif not isinstance(value, list):
            raise SettingsValidationError(f"{section} must be a list")

    roles = settings.get("roles")
    if roles is not None:
        if not isinstance(roles, list) or not roles:
            raise SettingsValidationError("roles must be a non-empty list")
        identifiers: set[str] = set()
        for role in roles:
            if not isinstance(role, Mapping):
                raise SettingsValidationError("Each role must be a mapping")
            role_id = str(role.get("role_id") or "").strip()
            if not role_id:
                raise SettingsValidationError("Each role requires a role_id")
            if role_id in identifiers:
                raise SettingsValidationError(f"Duplicate role_id: {role_id}")
            identifiers.add(role_id)
            permissions = role.get("permissions")
            if not isinstance(permissions, list) or not permissions:
                raise SettingsValidationError(
                    f"Role {role_id} requires a non-empty permissions list"
                )
        # Losing the last admin role would lock every operator out of the
        # settings surface with no in-product way back.
        if not any(
            "admin" in (role.get("permissions") or ())
            for role in roles
            if isinstance(role, Mapping)
        ):
            raise SettingsValidationError(
                "At least one role must retain the admin permission"
            )

    retention = settings.get("retention_policy")
    if retention is not None:
        if not isinstance(retention, Mapping):
            raise SettingsValidationError("retention_policy must be a mapping")
        for key, value in retention.items():
            if isinstance(value, bool) or not isinstance(value, int):
                raise SettingsValidationError(f"retention_policy.{key} must be an integer")
            if not _MIN_RETENTION_DAYS <= value <= _MAX_RETENTION_DAYS:
                raise SettingsValidationError(
                    f"retention_policy.{key} must be between "
                    f"{_MIN_RETENTION_DAYS} and {_MAX_RETENTION_DAYS} days"
                )

    vulnerability = settings.get("vulnerability_policy")
    if vulnerability is not None:
        if not isinstance(vulnerability, Mapping):
            raise SettingsValidationError("vulnerability_policy must be a mapping")
        for key in ("critical_sla_days", "high_sla_days", "medium_sla_days", "low_sla_days"):
            if key not in vulnerability:
                continue
            value = vulnerability[key]
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise SettingsValidationError(f"vulnerability_policy.{key} must be a positive integer")

    agent = settings.get("agent_policy")
    if agent is not None:
        if not isinstance(agent, Mapping):
            raise SettingsValidationError("agent_policy must be a mapping")
        if agent.get("allow_autonomous_remediation") and not agent.get(
            "require_human_approval", True
        ):
            # Both switches off at once is the one combination that lets an
            # agent change production with nobody in the loop.
            raise SettingsValidationError(
                "Autonomous remediation cannot be enabled while human approval is disabled"
            )
        concurrency = agent.get("max_concurrent_investigations")
        if concurrency is not None and (
            isinstance(concurrency, bool) or not isinstance(concurrency, int) or concurrency < 1
        ):
            raise SettingsValidationError(
                "agent_policy.max_concurrent_investigations must be a positive integer"
            )


class EnterpriseSettingsStore:
    """Reads and writes the enterprise settings document.

    ``documents`` is an :class:`~storage.onelake_documents.OneLakeDocumentStore`
    or None. None is explicitly non-durable test/embedded memory. Runtime
    deployments and local runs both supply a document store.
    """

    def __init__(self, documents: Any = None) -> None:
        self._documents = documents
        self._memory: dict[str, Any] = {}
        self._lock = threading.RLock()

    def read(self) -> dict[str, Any]:
        """Return effective settings, failing closed on invalid stored state."""
        result = self.read_versioned()
        return {key: result[key] for key in _VALID_SECTIONS}

    def _snapshot(self) -> DocumentSnapshot:
        if self._documents is None:
            return DocumentSnapshot(copy.deepcopy(self._memory), "memory" if self._memory else None)
        return self._documents.read_snapshot(SETTINGS_DOCUMENT)

    def _effective(self, snapshot: DocumentSnapshot) -> dict[str, Any]:
        payload = snapshot.payload
        if not snapshot.exists:
            return {**default_settings(), "revision": 0, "last_change": None,
                    "persistent": self._documents is not None}
        try:
            revision = payload["revision"]
            if (
                type(revision) is not int or not 0 <= revision <= MAX_SETTINGS_REVISION
                or not isinstance(payload["settings"], dict)
                or len((json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()) > MAX_SETTINGS_BYTES
            ):
                raise ValueError("Invalid enterprise settings document")
            settings = _merge(default_settings(), payload["settings"])
            validate_settings(payload["settings"])
            validate_settings(settings)
            last = payload.get("last_change")
            attribution = _LastChange.model_validate(last).model_dump() if last is not None else None
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("Persisted enterprise settings are invalid") from exc
        return {**settings, "revision": revision, "last_change": attribution,
                "persistent": self._documents is not None}

    def read_versioned(self) -> dict[str, Any]:
        """Read settings and revision together; metadata is not policy."""
        with self._lock:
            return self._effective(self._snapshot())

    def update(
        self, changes: Mapping[str, Any], *, expected_revision: int,
        reason: str, actor: str,
    ) -> dict[str, Any]:
        """Commit a reviewed partial update once, using storage ETag CAS."""
        request = SettingsChange(
            expected_revision=expected_revision, changes=dict(changes), reason=reason,
        )
        attribution = _LastChange(
            actor=actor, reason=request.reason, recorded_at=datetime.now(UTC).isoformat(),
        ).model_dump()
        with self._lock:
            snapshot = self._snapshot()
            current = self._effective(snapshot)
            if current["revision"] != request.expected_revision:
                raise DocumentConflictError("Settings changed; reload and review again")
            validate_settings(request.changes)
            merged = _merge({key: current[key] for key in _VALID_SECTIONS}, request.changes)
            validate_settings(merged)
            payload = {"settings": merged, "revision": current["revision"] + 1,
                       "last_change": attribution}
            try:
                size = len((json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n").encode())
            except (TypeError, ValueError) as exc:
                raise SettingsValidationError("Settings must contain finite JSON values") from exc
            if size > MAX_SETTINGS_BYTES:
                raise SettingsValidationError("Settings exceed the 512 KiB document limit")
            if self._documents is None:
                self._memory = copy.deepcopy(payload)
            elif snapshot.exists:
                self._documents.replace_if_match(SETTINGS_DOCUMENT, payload, expected_etag=snapshot.etag)
            else:
                self._documents.create_only(SETTINGS_DOCUMENT, payload)
            return {**merged, "revision": payload["revision"], "last_change": attribution,
                    "persistent": self._documents is not None}


__all__ = [
    "SETTINGS_DOCUMENT",
    "EnterpriseSettingsStore",
    "SettingsValidationError",
    "default_settings",
    "validate_settings",
]
