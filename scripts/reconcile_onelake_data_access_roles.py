#!/usr/bin/env python3
"""Deterministic idempotent Fabric REST reconciliation for OneLake data-access roles.

Replaces the five ``fabric_onelake_data_access_security`` Terraform resources
that are blocked by the Fabric provider 1.13 ManagedIdentity round-tripping
bug.  This script uses the official Fabric REST API:

    PUT /v1/workspaces/{workspaceId}/items/{itemId}/dataAccessRoles

Each invocation:
 1. GETs the current roles and captures the ETag.
 2. Builds the exact desired ``Phase13EvidenceRead`` role.
 3. Merges the desired role into the existing list, preserving all unrelated
    roles.
 4. Compares existing vs desired; if already converged, exits with no write.
 5. In dry-run mode, reports the planned change without writing.
 6. PUTs the merged payload with ``If-Match: <etag>`` for optimistic
    concurrency.
 7. On 412 (ETag conflict) or 429 (throttle), refetches and recomputes up
    to ``MAX_RETRIES`` times.
 8. On non-retryable errors (4xx except 412/429), fails closed immediately.
 9. After a successful PUT, GETs the roles again and verifies the exact
    desired role is present — fails closed on any drift.

Credentials are acquired via ``DefaultAzureCredential`` (or an explicit token
provider callback); secrets never appear on the CLI.

This is an explicit operator-invoked script, not a Terraform ``local-exec``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import stat
import subprocess
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

EVIDENCE_ROLE_NAME = "Phase13EvidenceRead"
FABRIC_API_BASE = "https://api.fabric.microsoft.com/v1"
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0  # seconds, doubled per attempt
SERVER_ROLE_KEYS = frozenset({"eTag", "etag", "id"})

# The five Phase 13 evidence Lakehouse items.
EVIDENCE_ITEMS = (
    "ontology_discovery_state",
    "ontology_command",
    "ontology_dispatch",
    "ontology_publication",
    "ontology_rbac_validation",
)


class DataAccessRoleReconciliationError(RuntimeError):
    """Reconciliation cannot proceed safely."""


class VerificationDriftError(DataAccessRoleReconciliationError):
    """Post-write verification detected drift from the desired state."""


# ---------------------------------------------------------------------------
# Role construction
# ---------------------------------------------------------------------------


def build_desired_role(object_id: str, tenant_id: str) -> dict[str, Any]:
    """Build the exact least-privilege evidence role definition.

    Produces the canonical ``Phase13EvidenceRead`` role with:
    - ``Path = *`` (all paths in the Lakehouse item)
    - ``Action = Read`` (read-only)
    - One ``MicrosoftEntraMember`` with the given managed-identity objectId.
    """
    object_id = _validated_uuid(object_id, "objectId")
    tenant_id = _validated_uuid(tenant_id, "tenantId")

    return {
        "name": EVIDENCE_ROLE_NAME,
        "kind": "Policy",
        "decisionRules": [
            {
                "effect": "Permit",
                "permission": [
                    {
                        "attributeName": "Path",
                        "attributeValueIncludedIn": ["*"],
                    },
                    {
                        "attributeName": "Action",
                        "attributeValueIncludedIn": ["Read"],
                    },
                ],
            }
        ],
        "members": {
            "fabricItemMembers": [],
            "microsoftEntraMembers": [
                {
                    "objectId": object_id,
                    "objectType": "ManagedIdentity",
                    "tenantId": tenant_id,
                }
            ],
        },
    }


# ---------------------------------------------------------------------------
# Merge logic — preserve unrelated roles
# ---------------------------------------------------------------------------


def merge_roles(
    existing: list[dict[str, Any]],
    desired: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return a new list with unrelated roles preserved and the desired role
    added or replaced.

    Does not mutate the input list.
    """
    matches = [role for role in existing if role.get("name") == desired["name"]]
    if len(matches) > 1:
        raise DataAccessRoleReconciliationError(
            "duplicate evidence roles are forbidden"
        )
    merged = [
        _request_role(role)
        for role in existing
        if role.get("name") != desired["name"]
    ]
    merged.append(_request_role(desired))
    return merged


def _role_semantics(
    role: Mapping[str, Any],
    *,
    verified_principal_type: str | None = None,
) -> dict[str, Any]:
    normalized = _request_role(role)
    members = normalized.get("members")
    members = dict(members) if isinstance(members, Mapping) else {}
    entra = members.get("microsoftEntraMembers")
    if (
        verified_principal_type == "ManagedIdentity"
        and isinstance(entra, list)
        and len(entra) == 1
        and isinstance(entra[0], Mapping)
        and not entra[0].get("objectType")
    ):
        member = dict(entra[0])
        member["objectType"] = verified_principal_type
        members["microsoftEntraMembers"] = [member]
        normalized["members"] = members
    return normalized


def _roles_equal(
    a: dict[str, Any],
    b: dict[str, Any],
    *,
    verified_principal_type: str | None = None,
) -> bool:
    """Deep-compare two role dicts by canonical JSON."""
    return json.dumps(
        _role_semantics(
            a,
            verified_principal_type=verified_principal_type,
        ),
        sort_keys=True,
    ) == json.dumps(
        _role_semantics(b),
        sort_keys=True,
    )


def _find_role(roles: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for role in roles:
        if role.get("name") == name:
            return role
    return None


def _request_role(role: Mapping[str, Any]) -> dict[str, Any]:
    return {
        str(key): value
        for key, value in role.items()
        if str(key) not in SERVER_ROLE_KEYS
    }


def _validated_uuid(value: str, label: str) -> str:
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"{label} must be a UUID") from exc


def parse_contract(
    value: object,
) -> tuple[list[tuple[str, str, str]], str, str, str]:
    """Parse the exact five-item Terraform output without CLI identifiers."""

    if not isinstance(value, Mapping):
        raise DataAccessRoleReconciliationError("role contract must be an object")
    if set(value) != {
        "principal_object_id",
        "principal_resource_id",
        "tenant_id",
        "targets",
    }:
        raise DataAccessRoleReconciliationError(
            "role contract has unexpected fields"
        )
    targets_value = value.get("targets")
    if not isinstance(targets_value, Mapping) or set(targets_value) != set(
        EVIDENCE_ITEMS
    ):
        raise DataAccessRoleReconciliationError(
            "role contract must contain five exact targets"
        )
    items: list[tuple[str, str, str]] = []
    for name in EVIDENCE_ITEMS:
        row = targets_value.get(name)
        if not isinstance(row, Mapping) or set(row) != {
            "workspace_id",
            "item_id",
        }:
            raise DataAccessRoleReconciliationError(
                f"{name} target is invalid"
            )
        items.append(
            (
                name,
                _validated_uuid(str(row.get("workspace_id")), "workspace_id"),
                _validated_uuid(str(row.get("item_id")), "item_id"),
            )
        )
    resource_id = str(value.get("principal_resource_id") or "").strip()
    if (
        "/providers/Microsoft.ManagedIdentity/userAssignedIdentities/"
        not in resource_id
    ):
        raise DataAccessRoleReconciliationError(
            "principal resource must be a user-assigned managed identity"
        )
    return (
        items,
        _validated_uuid(str(value.get("principal_object_id")), "objectId"),
        _validated_uuid(str(value.get("tenant_id")), "tenantId"),
        resource_id,
    )


def _opaque(value: object) -> str:
    rendered = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return "sha256:" + hashlib.sha256(rendered.encode()).hexdigest()


def _unrelated_roles(
    roles: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    return [
        _request_role(role)
        for role in roles
        if role.get("name") != EVIDENCE_ROLE_NAME
    ]


def _list_roles(client: Any, url: str) -> tuple[list[dict[str, Any]], str]:
    roles: list[dict[str, Any]] = []
    continuation: str | None = None
    etag = ""
    while True:
        response = client.get(
            url,
            params={"continuationToken": continuation} if continuation else None,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, Mapping):
            raise DataAccessRoleReconciliationError(
                "Fabric role response is invalid"
            )
        page = payload.get("value")
        if not isinstance(page, list) or any(
            not isinstance(row, Mapping) for row in page
        ):
            raise DataAccessRoleReconciliationError(
                "Fabric role list is invalid"
            )
        roles.extend(dict(row) for row in page)
        if not etag:
            etag = str(response.headers.get("ETag", "")).strip()
        continuation_value = payload.get("continuationToken")
        continuation = str(continuation_value) if continuation_value else None
        if not continuation:
            break
    if not etag:
        raise DataAccessRoleReconciliationError(
            "OneLake role collection ETag is missing"
        )
    return roles, etag


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def verify_roles_match(
    actual_roles: list[dict[str, Any]],
    desired: dict[str, Any],
    *,
    verified_principal_type: str | None = None,
) -> None:
    """Fail closed if the desired role is missing or drifted."""
    found = _find_role(actual_roles, desired["name"])
    if found is None:
        raise VerificationDriftError(
            f"role {desired['name']!r} not found in response after PUT"
        )
    if not _roles_equal(
        found,
        desired,
        verified_principal_type=verified_principal_type,
    ):
        raise VerificationDriftError(
            "evidence role drifted from exact ManagedIdentity Read"
        )


# ---------------------------------------------------------------------------
# Core reconciliation
# ---------------------------------------------------------------------------

_RETRYABLE_STATUS = {412, 429}
_TRANSIENT_STATUS = {500, 502, 503, 504}


def reconcile_item_roles(
    *,
    client: Any,
    workspace_id: str,
    item_id: str,
    object_id: str,
    tenant_id: str,
    dry_run: bool = True,
    verified_principal_type: str | None = None,
) -> dict[str, Any]:
    """Reconcile data-access roles for one Lakehouse item.

    Parameters
    ----------
    client:
        An HTTP client with ``.get()`` and ``.put()`` methods (e.g.
        ``httpx.Client`` with an ``Authorization`` header pre-configured).
    workspace_id, item_id:
        Fabric workspace and Lakehouse item identifiers.
    object_id, tenant_id:
        The managed-identity objectId and Entra tenantId for the evidence
        member.
    dry_run:
        If True, compute and report the change without writing.

    Returns
    -------
    dict with keys: ``already_converged``, ``would_change``, ``dry_run``,
    ``verified``, ``retries``, ``etag_before_hash``, ``etag_after_hash``.
    """
    url = f"{FABRIC_API_BASE}/workspaces/{workspace_id}/items/{item_id}/dataAccessRoles"
    desired = build_desired_role(object_id, tenant_id)
    retries = 0

    for attempt in range(MAX_RETRIES + 1):
        # ---- GET current state ----
        current_roles, etag = _list_roles(client, url)

        # ---- Check convergence ----
        existing_evidence = _find_role(current_roles, EVIDENCE_ROLE_NAME)
        if existing_evidence is not None and _roles_equal(
            existing_evidence,
            desired,
            verified_principal_type=verified_principal_type,
        ):
            return {
                "already_converged": True,
                "would_change": False,
                "dry_run": dry_run,
                "verified": True,
                "retries": retries,
                "etag_before_hash": _opaque(etag),
                "etag_after_hash": _opaque(etag),
            }

        # ---- Merge ----
        merged = merge_roles(current_roles, desired)
        unrelated_before = _unrelated_roles(current_roles)

        # ---- Dry-run exit ----
        if dry_run:
            return {
                "already_converged": False,
                "would_change": True,
                "dry_run": True,
                "verified": False,
                "retries": 0,
                "etag_before_hash": _opaque(etag),
                "etag_after_hash": None,
                "planned_role_count": len(merged),
            }

        # ---- Server dry run, then PUT with the same If-Match ----
        put_resp = client.put(
            url,
            params={"dryRun": "true"},
            json={"value": merged},
            headers={"If-Match": etag},
        )
        if put_resp.status_code < 400:
            put_resp = client.put(
                url,
                json={"value": merged},
                headers={"If-Match": etag},
            )

        if put_resp.status_code in _RETRYABLE_STATUS:
            retries += 1
            if attempt < MAX_RETRIES:
                delay = RETRY_BASE_DELAY * (2**attempt)
                if put_resp.status_code == 429:
                    retry_after = put_resp.headers.get("Retry-After")
                    if retry_after:
                        try:
                            delay = max(delay, float(retry_after))
                        except ValueError:
                            pass
                logger.warning(
                    "Retryable %d on attempt %d/%d; waiting %.1fs",
                    put_resp.status_code,
                    attempt + 1,
                    MAX_RETRIES + 1,
                    delay,
                )
                time.sleep(delay)
                continue  # refetch and recompute
            raise DataAccessRoleReconciliationError(
                f"retries exhausted ({MAX_RETRIES}); "
                f"last status {put_resp.status_code}"
            )

        if put_resp.status_code in _TRANSIENT_STATUS:
            retries += 1
            if attempt < MAX_RETRIES:
                delay = RETRY_BASE_DELAY * (2**attempt)
                logger.warning(
                    "Transient %d on attempt %d; waiting %.1fs",
                    put_resp.status_code,
                    attempt + 1,
                    delay,
                )
                time.sleep(delay)
                continue
            raise DataAccessRoleReconciliationError(
                f"retries exhausted ({MAX_RETRIES}); "
                f"last status {put_resp.status_code}"
            )

        if 400 <= put_resp.status_code < 600:
            raise DataAccessRoleReconciliationError(
                f"non-retryable HTTP {put_resp.status_code}"
            )

        put_resp.raise_for_status()
        etag_after = put_resp.headers.get("ETag", etag)

        # ---- POST-WRITE VERIFICATION ----
        actual_roles, verified_etag = _list_roles(client, url)
        verify_roles_match(
            actual_roles,
            desired,
            verified_principal_type=verified_principal_type,
        )
        if _unrelated_roles(actual_roles) != unrelated_before:
            raise VerificationDriftError("unrelated OneLake roles changed")

        return {
            "already_converged": False,
            "would_change": True,
            "dry_run": False,
            "verified": True,
            "retries": retries,
            "etag_before_hash": _opaque(etag),
            "etag_after_hash": _opaque(verified_etag or etag_after),
        }

    # Unreachable under normal flow, but fail closed.
    raise DataAccessRoleReconciliationError(  # pragma: no cover
        "reconciliation loop exited without result"
    )


# ---------------------------------------------------------------------------
# Multi-item orchestrator
# ---------------------------------------------------------------------------


def reconcile_all_evidence_items(
    *,
    items: Sequence[tuple[str, str, str]],
    object_id: str,
    tenant_id: str,
    token_provider: Callable[[], str],
    principal_type_provider: Callable[[str], str] | None = None,
    dry_run: bool = True,
) -> list[dict[str, Any]]:
    """Reconcile the evidence read role across all five Phase 13 items.

    Parameters
    ----------
    items:
        Sequence of ``(logical_name, workspace_id, item_id)`` tuples.
    object_id, tenant_id:
        Evidence managed-identity principal.
    token_provider:
        Callable returning a bearer token (e.g. from DefaultAzureCredential).
    dry_run:
        If True, compute planned changes without writing.

    Returns
    -------
    List of per-item result dicts.
    """
    import httpx

    results: list[dict[str, Any]] = []
    names = {name for name, _, _ in items}
    workspaces = {
        _validated_uuid(workspace_id, "workspace_id")
        for _, workspace_id, _ in items
    }
    item_ids = {
        _validated_uuid(item_id, "item_id") for _, _, item_id in items
    }
    if (
        names != set(EVIDENCE_ITEMS)
        or len(items) != 5
        or len(workspaces) != 5
        or len(item_ids) != 5
    ):
        raise DataAccessRoleReconciliationError(
            "exactly five isolated Phase 13 evidence items are required"
        )

    # Acquire token once for the batch.
    token = token_provider()
    verified_principal_type = (
        principal_type_provider(object_id)
        if principal_type_provider is not None
        else None
    )
    if (
        principal_type_provider is not None
        and verified_principal_type != "ManagedIdentity"
    ):
        raise DataAccessRoleReconciliationError(
            "evidence principal is not an Entra managed identity"
        )

    with httpx.Client(
        headers={"Authorization": f"Bearer {token}"},
        timeout=30.0,
    ) as client:
        for logical_name, workspace_id, item_id in items:
            logger.info(
                "%s: reconciling target (dry_run=%s)",
                logical_name,
                dry_run,
            )
            result = reconcile_item_roles(
                client=client,
                workspace_id=workspace_id,
                item_id=item_id,
                object_id=object_id,
                tenant_id=tenant_id,
                dry_run=dry_run,
                verified_principal_type=verified_principal_type,
            )
            result["logical_name"] = logical_name
            results.append(result)
            logger.info(
                "%s: %s",
                logical_name,
                "already converged"
                if result.get("already_converged")
                else ("would change" if dry_run else "applied"),
            )

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _get_token_from_azure_cli(config_dir: Path) -> str:
    try:
        resolved = config_dir.expanduser().resolve(strict=True)
        mode = stat.S_IMODE(resolved.stat().st_mode)
    except OSError as exc:
        raise DataAccessRoleReconciliationError(
            "Azure CLI config is unavailable"
        ) from exc
    if not resolved.is_dir() or mode != 0o700:
        raise DataAccessRoleReconciliationError(
            "Azure CLI config must be a mode-0700 directory"
        )
    blocked = {
        "AZURE_CLIENT_ID",
        "AZURE_CLIENT_SECRET",
        "AZURE_FEDERATED_TOKEN_FILE",
        "AZURE_TENANT_ID",
        "ARM_CLIENT_ID",
        "ARM_CLIENT_SECRET",
        "ARM_TENANT_ID",
    }
    environment = {
        key: value for key, value in os.environ.items() if key not in blocked
    }
    environment["AZURE_CONFIG_DIR"] = str(resolved)
    completed = subprocess.run(
        [
            "az",
            "account",
            "get-access-token",
            "--resource",
            FABRIC_API_BASE.removesuffix("/v1"),
            "--query",
            "accessToken",
            "--output",
            "tsv",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
        env=environment,
    )
    token = completed.stdout.strip()
    if completed.returncode != 0 or not token:
        raise DataAccessRoleReconciliationError(
            "delegated Fabric token acquisition failed"
        )
    return token


def _get_principal_type_from_azure_cli(
    config_dir: Path,
    object_id: str,
    resource_id: str,
) -> str:
    resolved = config_dir.expanduser().resolve(strict=True)
    environment = {
        key: value
        for key, value in os.environ.items()
        if key
        not in {
            "AZURE_CLIENT_ID",
            "AZURE_CLIENT_SECRET",
            "AZURE_FEDERATED_TOKEN_FILE",
            "AZURE_TENANT_ID",
            "ARM_CLIENT_ID",
            "ARM_CLIENT_SECRET",
            "ARM_TENANT_ID",
        }
    }
    environment["AZURE_CONFIG_DIR"] = str(resolved)
    completed = subprocess.run(
        [
            "az",
            "identity",
            "show",
            "--ids",
            resource_id,
            "--query",
            "principalId",
            "--output",
            "tsv",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
        env=environment,
    )
    principal_id = completed.stdout.strip()
    if completed.returncode != 0 or principal_id.casefold() != object_id.casefold():
        raise DataAccessRoleReconciliationError(
            "evidence principal managed-identity proof failed"
        )
    return "ManagedIdentity"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Reconcile OneLake data-access roles for the five Phase 13 "
            "evidence Lakehouse items using the Fabric REST API."
        ),
    )
    parser.add_argument(
        "--contract-file",
        type=argparse.FileType("r"),
        required=True,
        help="JSON emitted by Terraform output ontology_evidence_role_contract",
    )
    parser.add_argument("--azure-config-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Actually write changes (default is dry-run)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    args = _parser().parse_args(argv)
    items, object_id, tenant_id, resource_id = parse_contract(
        json.load(args.contract_file)
    )
    dry_run = not args.apply

    if dry_run:
        logger.info("DRY RUN — no changes will be written")
    else:
        logger.info("APPLY MODE — changes will be written with ETag preconditions")

    results = reconcile_all_evidence_items(
        items=items,
        object_id=object_id,
        tenant_id=tenant_id,
        token_provider=lambda: _get_token_from_azure_cli(args.azure_config_dir),
        principal_type_provider=lambda object_id: (
            _get_principal_type_from_azure_cli(
                args.azure_config_dir,
                object_id,
                resource_id,
            )
        ),
        dry_run=dry_run,
    )

    evidence = {
        "schema_version": "ontology-onelake-role-reconciliation.v1",
        "status": "PASS",
        "sanitized": True,
        "target_count": len(results),
        "principal_type_proof_hash": _opaque("ManagedIdentity"),
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(evidence, sort_keys=True, separators=(",", ":")))

    if any(
        not r.get("verified") and not r.get("dry_run") and not r.get("already_converged")
        for r in results
    ):
        logger.error("One or more items failed verification")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
