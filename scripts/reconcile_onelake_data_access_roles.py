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
import json
import logging
import time
from collections.abc import Callable, Sequence
from typing import Any

logger = logging.getLogger(__name__)

EVIDENCE_ROLE_NAME = "Phase13EvidenceRead"
FABRIC_API_BASE = "https://api.fabric.microsoft.com/v1"
FABRIC_SCOPE = "https://api.fabric.microsoft.com/.default"
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0  # seconds, doubled per attempt

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
    if not object_id or not object_id.strip():
        raise ValueError("objectId must not be empty")
    if not tenant_id or not tenant_id.strip():
        raise ValueError("tenantId must not be empty")

    return {
        "name": EVIDENCE_ROLE_NAME,
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
    merged = [role for role in existing if role.get("name") != desired["name"]]
    merged.append(desired)
    return merged


def _roles_equal(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Deep-compare two role dicts by canonical JSON."""
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def _find_role(roles: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for role in roles:
        if role.get("name") == name:
            return role
    return None


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def verify_roles_match(
    actual_roles: list[dict[str, Any]],
    desired: dict[str, Any],
) -> None:
    """Fail closed if the desired role is missing or drifted."""
    found = _find_role(actual_roles, desired["name"])
    if found is None:
        raise VerificationDriftError(
            f"role {desired['name']!r} not found in response after PUT"
        )
    if not _roles_equal(found, desired):
        raise VerificationDriftError(
            f"role {desired['name']!r} drift detected: "
            f"expected={json.dumps(desired, sort_keys=True)}, "
            f"actual={json.dumps(found, sort_keys=True)}"
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
    ``verified``, ``retries``, ``etag_before``, ``etag_after``.
    """
    url = f"{FABRIC_API_BASE}/workspaces/{workspace_id}/items/{item_id}/dataAccessRoles"
    desired = build_desired_role(object_id, tenant_id)
    retries = 0

    for attempt in range(MAX_RETRIES + 1):
        # ---- GET current state ----
        get_resp = client.get(url)
        get_resp.raise_for_status()
        current_roles: list[dict[str, Any]] = get_resp.json().get("value", [])
        etag = get_resp.headers.get("ETag", "")

        # ---- Check convergence ----
        existing_evidence = _find_role(current_roles, EVIDENCE_ROLE_NAME)
        if existing_evidence is not None and _roles_equal(existing_evidence, desired):
            return {
                "already_converged": True,
                "would_change": False,
                "dry_run": dry_run,
                "verified": True,
                "retries": retries,
                "etag_before": etag,
                "etag_after": etag,
            }

        # ---- Merge ----
        merged = merge_roles(current_roles, desired)

        # ---- Dry-run exit ----
        if dry_run:
            return {
                "already_converged": False,
                "would_change": True,
                "dry_run": True,
                "verified": False,
                "retries": 0,
                "etag_before": etag,
                "etag_after": None,
                "planned_roles": [r["name"] for r in merged],
            }

        # ---- PUT with If-Match ----
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
                    "Retryable %d on attempt %d/%d for %s/%s; waiting %.1fs",
                    put_resp.status_code,
                    attempt + 1,
                    MAX_RETRIES + 1,
                    workspace_id,
                    item_id,
                    delay,
                )
                time.sleep(delay)
                continue  # refetch and recompute
            raise DataAccessRoleReconciliationError(
                f"retries exhausted ({MAX_RETRIES}) for {workspace_id}/{item_id} "
                f"— last status {put_resp.status_code}"
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
                f"retries exhausted ({MAX_RETRIES}) for {workspace_id}/{item_id} "
                f"— last status {put_resp.status_code}"
            )

        if 400 <= put_resp.status_code < 600:
            raise DataAccessRoleReconciliationError(
                f"non-retryable HTTP {put_resp.status_code} for "
                f"{workspace_id}/{item_id}"
            )

        put_resp.raise_for_status()
        etag_after = put_resp.headers.get("ETag", etag)

        # ---- POST-WRITE VERIFICATION ----
        verify_resp = client.get(url)
        verify_resp.raise_for_status()
        actual_roles = verify_resp.json().get("value", [])
        verify_roles_match(actual_roles, desired)

        return {
            "already_converged": False,
            "would_change": True,
            "dry_run": False,
            "verified": True,
            "retries": retries,
            "etag_before": etag,
            "etag_after": etag_after,
        }

    # Unreachable under normal flow, but fail closed.
    raise DataAccessRoleReconciliationError(  # pragma: no cover
        f"reconciliation loop exited without result for {workspace_id}/{item_id}"
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

    # Acquire token once for the batch.
    token = token_provider()

    with httpx.Client(
        headers={"Authorization": f"Bearer {token}"},
        timeout=30.0,
    ) as client:
        for logical_name, workspace_id, item_id in items:
            logger.info(
                "%s: reconciling %s/%s (dry_run=%s)",
                logical_name,
                workspace_id,
                item_id,
                dry_run,
            )
            result = reconcile_item_roles(
                client=client,
                workspace_id=workspace_id,
                item_id=item_id,
                object_id=object_id,
                tenant_id=tenant_id,
                dry_run=dry_run,
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


def _get_token_from_default_credential() -> str:
    from azure.identity import DefaultAzureCredential

    credential = DefaultAzureCredential()
    token = credential.get_token(FABRIC_SCOPE)
    return token.token


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Reconcile OneLake data-access roles for the five Phase 13 "
            "evidence Lakehouse items using the Fabric REST API."
        ),
    )
    parser.add_argument(
        "--items-json",
        type=argparse.FileType("r"),
        required=True,
        help=(
            'JSON file: [{"name":"...", "workspace_id":"...", "item_id":"..."}]'
        ),
    )
    parser.add_argument("--object-id", required=True, help="Evidence UAI objectId (principal_id)")
    parser.add_argument("--tenant-id", required=True, help="Entra tenant ID")
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
    args = _parser().parse_args(argv)
    items_raw = json.load(args.items_json)
    if not isinstance(items_raw, list):
        logger.error("--items-json must be a JSON array")
        return 1

    items = [
        (item["name"], item["workspace_id"], item["item_id"])
        for item in items_raw
    ]
    dry_run = not args.apply

    if dry_run:
        logger.info("DRY RUN — no changes will be written")
    else:
        logger.info("APPLY MODE — changes will be written with ETag preconditions")

    results = reconcile_all_evidence_items(
        items=items,
        object_id=args.object_id,
        tenant_id=args.tenant_id,
        token_provider=_get_token_from_default_credential,
        dry_run=dry_run,
    )

    print(json.dumps(results, indent=2, sort_keys=True))

    if any(
        not r.get("verified") and not r.get("dry_run") and not r.get("already_converged")
        for r in results
    ):
        logger.error("One or more items failed verification")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
