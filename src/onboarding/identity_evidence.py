"""Explicit read-only identity source acquisition; never an access decision."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from azure.core.credentials import TokenCredential
from azure.core.exceptions import AzureError

from .azure_clients import HttpRequester
from .config import ConnectorConfig

logger = logging.getLogger(__name__)

PrincipalType = Literal["user", "group", "service_principal"]
_GRAPH_TYPES = {
    "user": "users",
    "group": "groups",
    "service_principal": "servicePrincipals",
}


def _uuid(value: str, label: str) -> str:
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError(f"{label} must be a UUID") from exc
    if str(parsed) != value.lower():
        raise ValueError(f"{label} must be a hyphenated UUID")
    return str(parsed)


class IdentityEvidenceClient:
    """Collect bounded source pages using the registered connection credential.

    Results distinguish a fully read collection from failed or bounded reads.
    Even complete collections are not complete effective-access evidence:
    management-group inheritance, hidden memberships, condition evaluation,
    data-plane policy and service-specific authorization remain unverified.
    """

    def __init__(
        self,
        credential: TokenCredential,
        *,
        requester: HttpRequester | None = None,
        timeout: int = 30,
        max_pages: int = 10,
        max_rows: int = 5000,
        max_page_bytes: int = 1_048_576,
    ) -> None:
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 1
            for value in (timeout, max_pages, max_rows, max_page_bytes)
        ):
            raise ValueError("Identity evidence limits must be positive integers")
        self.credential = credential
        self.requester = requester or httpx.request
        self.timeout = timeout
        self.max_pages = max_pages
        self.max_rows = max_rows
        self.max_page_bytes = max_page_bytes

    def collect(
        self,
        subscription_id: str,
        principal_id: str,
        principal_type: PrincipalType,
    ) -> dict[str, Any]:
        """Read four independent evidence families without changing Azure or storage."""
        subscription = _uuid(subscription_id, "subscription_id")
        principal = _uuid(principal_id, "principal_id")
        if principal_type not in _GRAPH_TYPES:
            raise ValueError("principal_type must be user, group or service_principal")
        started_at = datetime.now(UTC).isoformat()
        graph = f"https://graph.microsoft.com/v1.0/{_GRAPH_TYPES[principal_type]}/{principal}/transitiveMemberOf"
        arm = f"https://management.azure.com/subscriptions/{subscription}/providers/Microsoft.Authorization"
        requests = {
            "transitive_membership": (
                graph + "?$select=id&$count=true",
                "https://graph.microsoft.com/.default",
                "@odata.nextLink",
            ),
            "deny_assignments": (
                arm + "/denyAssignments?api-version=2022-04-01",
                "https://management.azure.com/.default",
                "nextLink",
            ),
            "pim_eligibility_instances": (
                arm + "/roleEligibilityScheduleInstances?api-version=2020-10-01",
                "https://management.azure.com/.default",
                "nextLink",
            ),
            "pim_assignment_instances": (
                arm + "/roleAssignmentScheduleInstances?api-version=2020-10-01",
                "https://management.azure.com/.default",
                "nextLink",
            ),
        }
        sources = {
            name: self._read(name, *parameters) for name, parameters in requests.items()
        }
        return {
            "subscription_id": subscription,
            "principal_id": principal,
            "principal_type": principal_type,
            "read_only": True,
            "started_at": started_at,
            "completed_at": datetime.now(UTC).isoformat(),
            "source_reads_complete": all(row["complete"] for row in sources.values()),
            "effective_access": "not_evaluated",
            "sources": sources,
            "limitations": [
                "Membership is for the exact principal; hidden memberships may require separate authorized evidence.",
                "Graph advanced queries use an eventually consistent index, not real-time membership.",
                "ARM collections cover the requested subscription endpoint, not proven complete management-group inheritance.",
                "Deny and PIM rows are source observations, not evaluated permissions or active access.",
                "Role assignments/definitions, role conditions, data-plane policies and service-specific authorization require separate evaluation.",
                "Source reads are separate observations, not an atomic authorization snapshot.",
            ],
        }

    def _read(
        self, name: str, url: str, audience: str, next_key: str
    ) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        pages = 0

        def failed(reason: str, status: int | None = None) -> dict[str, Any]:
            logger.warning(
                "identity_evidence_read_incomplete source=%s reason=%s status=%s",
                name,
                reason,
                status,
            )
            return {
                "complete": False,
                "reason": reason,
                "http_status": status,
                "pages_read": pages,
                "rows": rows,
            }

        try:
            token = self.credential.get_token(audience)
        except AzureError:
            return failed("credential_unavailable")
        if not isinstance(getattr(token, "token", None), str) or not token.token:
            return failed("credential_unavailable")
        original = urlsplit(url)
        visited: set[str] = set()
        while pages < self.max_pages:
            try:
                location = urlsplit(url)
            except ValueError:
                return failed("invalid_continuation")
            if (
                location.scheme != "https"
                or location.netloc != original.netloc
                or location.path != original.path
                or location.fragment
                or url in visited
            ):
                return failed("invalid_continuation")
            visited.add(url)
            try:
                response = self.requester(
                    "GET",
                    url,
                    headers={
                        "Authorization": f"Bearer {token.token}",
                        **(
                            {"ConsistencyLevel": "eventual"}
                            if name == "transitive_membership"
                            else {}
                        ),
                    },
                    timeout=self.timeout,
                    follow_redirects=False,
                )
            except httpx.RequestError:
                return failed("transport_unavailable")
            if response.status_code != 200:
                return failed(
                    "permission_denied"
                    if response.status_code in {401, 403}
                    else "http_error",
                    response.status_code,
                )
            if len(response.content) > self.max_page_bytes:
                return failed("page_byte_limit")
            try:
                payload = response.json()
            except (json.JSONDecodeError, UnicodeDecodeError):
                return failed("invalid_payload")
            page = payload.get("value") if isinstance(payload, dict) else None
            if not isinstance(page, list) or any(
                not isinstance(row, dict) for row in page
            ):
                return failed("invalid_payload")
            for row in page:
                identifier = row.get("id")
                if not isinstance(identifier, str) or not identifier:
                    return failed("invalid_payload")
                if name == "transitive_membership":
                    try:
                        _uuid(identifier, "membership_id")
                    except ValueError:
                        return failed("invalid_payload")
                elif not identifier.startswith("/") or not isinstance(
                    row.get("properties"), dict
                ):
                    return failed("invalid_payload")
            if len(rows) + len(page) > self.max_rows:
                return failed("row_limit")
            continuation = payload.get(next_key)
            if continuation is not None and (
                not isinstance(continuation, str) or not continuation
            ):
                return failed("invalid_continuation")
            rows.extend(page)
            pages += 1
            if continuation is None:
                return {
                    "complete": True,
                    "reason": "",
                    "http_status": 200,
                    "pages_read": pages,
                    "rows": rows,
                }
            url = continuation
        return failed("page_limit")


def collect_connection_identity_evidence(
    config: ConnectorConfig,
    connection_id: str,
    principal_id: str,
    principal_type: PrincipalType,
) -> dict[str, Any]:
    """Read one active registered connection without starting sync or reconciliation."""
    from .registry import ConnectionRegistry
    from .runtime import build_connection_credential

    connection = ConnectionRegistry(config.output_dir).get(connection_id)
    if not connection.is_active:
        raise ValueError("Identity evidence requires an active subscription connection")
    client = IdentityEvidenceClient(build_connection_credential(connection))
    return {
        **client.collect(connection.subscription_id, principal_id, principal_type),
        "connection_id": connection.connection_id,
        "tenant_id": connection.tenant_id,
    }
