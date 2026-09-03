"""Enterprise administration settings.

A single versioned settings document covering roles, taxonomies, onboarding
and architecture policies, vulnerability thresholds, agent policy, retention,
and report templates.

Two deliberate choices:

* **One document, not one per section.** Settings are read together on nearly
  every admin request and written rarely, so a single revision-checked
  document gives cross-section consistency for free and avoids a partial
  configuration being observed mid-update.
* **Validated on write, defaulted on read.** A settings document written by an
  older build is merged over current defaults rather than rejected, so a
  rollback or a forward deploy never leaves the admin surface unusable.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

SETTINGS_DOCUMENT = "state/enterprise_settings.json"

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


def validate_settings(settings: Mapping[str, Any]) -> None:
    """Reject updates that would break invariants callers depend on."""
    unknown = set(settings) - set(_VALID_SECTIONS)
    if unknown:
        raise SettingsValidationError(
            f"Unknown settings sections: {', '.join(sorted(unknown))}"
        )

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
    or None. A None store keeps settings in process memory, which is correct
    for a single-process local run and never reached in a deployed replica.
    """

    def __init__(self, documents: Any = None) -> None:
        self._documents = documents
        self._memory: dict[str, Any] = {}

    def read(self) -> dict[str, Any]:
        if self._documents is None:
            return _merge(default_settings(), self._memory)
        payload = self._documents.read(SETTINGS_DOCUMENT)
        stored = payload.get("settings")
        return _merge(default_settings(), stored if isinstance(stored, Mapping) else {})

    def update(self, changes: Mapping[str, Any]) -> dict[str, Any]:
        """Apply a partial update, returning the full effective settings."""
        validate_settings(changes)
        if self._documents is None:
            self._memory = _merge(_merge(default_settings(), self._memory), changes)
            return copy.deepcopy(self._memory)

        payload = self._documents.read(SETTINGS_DOCUMENT)
        stored = payload.get("settings")
        stored = dict(stored) if isinstance(stored, Mapping) else {}
        revision = int(payload.get("revision") or 0)
        merged = _merge(_merge(default_settings(), stored), changes)
        self._documents.write(
            SETTINGS_DOCUMENT,
            {"settings": merged, "revision": revision + 1},
            expected_revision=revision,
        )
        return merged


__all__ = [
    "SETTINGS_DOCUMENT",
    "EnterpriseSettingsStore",
    "SettingsValidationError",
    "default_settings",
    "validate_settings",
]
