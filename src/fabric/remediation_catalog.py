"""Versioned publication of governed remediation configuration to OneLake."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fabric.schema_registry import schema_for
from intelligence.remediation.approval_engine import ApprovalEngine
from intelligence.remediation.remediation_opportunity_engine import (
    RemediationOpportunityEngine,
)
from storage.delta_writer import DeltaWriteMode, DeltaWriter, DeltaWriteResult
from storage.onelake_writer import OneLakeWriter

DEFAULT_CATALOG_PATH = (
    Path(__file__).resolve().parent
    / "catalogs"
    / "governed_remediation_catalog.v1.json"
)

_ACTION_JSON_FIELDS = (
    "trigger",
    "execution_steps",
    "preconditions",
    "rollback_actions",
    "success_criteria",
    "failure_criteria",
    "deployment_stages",
    "effectiveness",
)


@dataclass(frozen=True)
class RemediationCatalogPublication:
    """Result of publishing one immutable catalog generation."""

    catalog_version: str
    content_digest: str
    action_count: int
    policy_count: int
    action_table: DeltaWriteResult
    policy_table: DeltaWriteResult

    @property
    def changed(self) -> bool:
        """Whether either governed table advanced to a new generation."""
        return not (self.action_table.skipped and self.policy_table.skipped)

    def to_dict(self) -> dict[str, Any]:
        """Return a secret-free deployment result."""
        return {
            "catalog_version": self.catalog_version,
            "content_digest": self.content_digest,
            "action_count": self.action_count,
            "policy_count": self.policy_count,
            "changed": self.changed,
            "action_table_version": self.action_table.version,
            "policy_table_version": self.policy_table.version,
        }


def load_governed_catalog(path: str | Path = DEFAULT_CATALOG_PATH) -> dict[str, Any]:
    """Load and validate the versioned governed catalog."""
    source = Path(path).expanduser().resolve()
    payload = json.loads(source.read_text())
    if not isinstance(payload, dict):
        raise TypeError("Governed remediation catalog must be a JSON object")
    version = str(payload.get("catalog_version") or "").strip()
    if not version:
        raise ValueError("Governed remediation catalog requires catalog_version")
    actions = payload.get("action_catalog")
    policies = payload.get("approval_policies")
    if not isinstance(actions, list) or not actions:
        raise ValueError("Governed remediation action_catalog must not be empty")
    if not isinstance(policies, list) or not policies:
        raise ValueError("Governed remediation approval_policies must not be empty")
    RemediationOpportunityEngine(actions)
    ApprovalEngine(policies)
    return payload


def catalog_content_digest(catalog: Mapping[str, Any]) -> str:
    """Return the stable digest that fences both Silver tables."""
    canonical = json.dumps(
        dict(catalog),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def publish_governed_catalog(
    *,
    onelake: OneLakeWriter,
    delta: DeltaWriter,
    catalog_path: str | Path = DEFAULT_CATALOG_PATH,
    now: datetime | None = None,
) -> RemediationCatalogPublication:
    """Validate and atomically fence a governed catalog publication.

    Delta Lake cannot commit two independent tables in one transaction. Both
    tables therefore receive the same content digest as ``change_version``.
    The read path rejects mixed generations, so a reader either observes the
    previous complete generation or fails closed while publication is between
    table commits. ProviderRuntime retains its last known-good planner during
    that bounded interval.
    """
    catalog = load_governed_catalog(catalog_path)
    digest = catalog_content_digest(catalog)
    published_at = (now or datetime.now(UTC)).astimezone(UTC).isoformat()
    base = {
        "tenant_id": "governed-catalog",
        "subscription_id": "governed-catalog",
        "resource_id": "governed-catalog",
        "timestamp": published_at,
        "change_version": digest,
        "ingestion_run_id": f"remediation-catalog:{digest}",
    }
    actions = _action_rows(catalog["action_catalog"], base)
    policies = _policy_rows(catalog["approval_policies"], base)

    with onelake.sync_lock():
        action_result = delta.write(
            onelake.table_uri("silver", "remediation_action_catalog"),
            actions,
            mode=DeltaWriteMode.OVERWRITE,
            key_columns=("action_id",),
            schema=schema_for("silver_remediation_action_catalog"),
        )
        policy_result = delta.write(
            onelake.table_uri("silver", "remediation_approval_policies"),
            policies,
            mode=DeltaWriteMode.OVERWRITE,
            key_columns=("policy_id",),
            schema=schema_for("silver_remediation_approval_policies"),
        )

    return RemediationCatalogPublication(
        catalog_version=str(catalog["catalog_version"]),
        content_digest=digest,
        action_count=len(actions),
        policy_count=len(policies),
        action_table=action_result,
        policy_table=policy_result,
    )


def _action_rows(
    actions: list[dict[str, Any]], base: Mapping[str, str]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for action in actions:
        row = {
            **base,
            "resource_id": str(action["action_id"]),
            "action_id": str(action["action_id"]),
            "title": str(action["title"]),
            "opportunity_type": str(action["opportunity_type"]),
        }
        for field in _ACTION_JSON_FIELDS:
            row[f"{field}_json"] = json.dumps(
                action[field], sort_keys=True, separators=(",", ":")
            )
        rows.append(row)
    return rows


def _policy_rows(
    policies: list[dict[str, Any]], base: Mapping[str, str]
) -> list[dict[str, Any]]:
    return [
        {
            **base,
            "resource_id": str(policy["policy_id"]),
            "policy_id": str(policy["policy_id"]),
            "conditions_json": json.dumps(
                policy["conditions"], sort_keys=True, separators=(",", ":")
            ),
            "roles_json": json.dumps(
                policy["roles"], sort_keys=True, separators=(",", ":")
            ),
            "role_ids_json": json.dumps(
                policy.get("role_ids") or {},
                sort_keys=True,
                separators=(",", ":"),
            ),
        }
        for policy in policies
    ]


__all__ = [
    "DEFAULT_CATALOG_PATH",
    "RemediationCatalogPublication",
    "catalog_content_digest",
    "load_governed_catalog",
    "publish_governed_catalog",
]
