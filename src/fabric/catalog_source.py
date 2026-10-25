"""Bounded advisory discovery from the preview OneLake Catalog Search API."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from .fabric_client import FabricClient


@dataclass(frozen=True)
class CatalogCandidate:
    """Item metadata requiring direct source verification before maintenance."""

    item_id: str
    item_type: str
    display_name: str
    description: str
    workspace_id: str


@dataclass(frozen=True)
class CatalogObservation:
    """Fully paged search evidence, never authoritative source coverage."""

    workspace_id: str
    observed_at: datetime
    pages_fetched: int
    candidates: tuple[CatalogCandidate, ...]

    def to_dict(self) -> dict[str, Any]:
        """Serialize advisory evidence without claiming schema or permissions."""
        return {
            "source": "onelake_catalog",
            "workspace_id": self.workspace_id,
            "observed_at": self.observed_at.astimezone(UTC).isoformat(),
            "pages_fetched": self.pages_fetched,
            "search_complete": True,
            "coverage": "partial",
            "authoritative": False,
            "requires_direct_verification": True,
            "candidates": [
                {
                    "item_id": row.item_id,
                    "item_type": row.item_type,
                    "display_name": row.display_name,
                    "description": row.description,
                    "workspace_id": row.workspace_id,
                }
                for row in self.candidates
            ],
        }


@dataclass(frozen=True)
class VerifiedCatalogItem:
    """Direct item metadata with its endpoint and observation time."""

    current: CatalogCandidate
    endpoint: str
    verified_at: datetime
    catalog_metadata_changed: bool


@dataclass(frozen=True)
class VerifiedCatalogObservation:
    """Advisory catalog evidence paired with directly checked item metadata."""

    catalog: CatalogObservation
    verified_items: tuple[VerifiedCatalogItem, ...]

    def to_dict(self) -> dict[str, Any]:
        """Serialize metadata verification without claiming schema or lineage."""
        return {
            "source": "onelake_catalog_verified_items",
            "catalog": self.catalog.to_dict(),
            "coverage": "partial",
            "authoritative": False,
            "verification_scope": "item_metadata_only",
            "requires_direct_verification": False,
            "requires_schema_verification": True,
            "verified_items": [
                {
                    "current": asdict(row.current),
                    "endpoint": row.endpoint,
                    "verified_at": row.verified_at.astimezone(UTC).isoformat(),
                    "catalog_metadata_changed": row.catalog_metadata_changed,
                }
                for row in self.verified_items
            ],
        }


class FabricCatalogSource:
    """Fetch one explicitly allowed workspace with fail-closed resource bounds."""

    def __init__(
        self,
        client: FabricClient,
        *,
        workspace_id: str,
        page_size: int = 100,
        max_pages: int = 10,
        max_items: int = 1000,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.workspace_id = _guid(workspace_id)
        for name, value in (
            ("page_size", page_size), ("max_pages", max_pages), ("max_items", max_items),
        ):
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if page_size > 1000:
            raise ValueError("page_size must not exceed 1000")
        self.client = client
        self.page_size = page_size
        self.max_pages = max_pages
        self.max_items = max_items
        self.clock = clock

    def fetch(self) -> CatalogObservation:
        """Return complete bounded search results or raise without partial output.

        Search completion is not source completeness: the index can lag and is
        caller-scoped. This method never creates graph rows or retirements.
        """
        body: dict[str, object] = {
            "filter": f"WorkspaceId eq '{self.workspace_id}' and Type ne 'Workspace'",
            "pageSize": self.page_size,
        }
        rows: dict[str, CatalogCandidate] = {}
        seen_tokens: set[str] = set()
        for page_number in range(1, self.max_pages + 1):
            page = self.client.request(
                "POST", "/catalog/search", json_body=body,
                wait_for_completion=False,
                telemetry_skill="onelake-catalog-govern-cli",
            )
            values = page.get("value")
            if not isinstance(values, list) or len(values) > self.page_size:
                raise ValueError("Catalog returned an invalid or oversized page")
            if page.get("continuationUri"):
                raise ValueError("Catalog returned an unsupported continuation URI")
            for value in values:
                candidate = self._candidate(value)
                if candidate.item_id in rows:
                    raise ValueError("Catalog returned a duplicate item")
                if len(rows) >= self.max_items:
                    raise ValueError("Catalog item limit exceeded")
                rows[candidate.item_id] = candidate
            token = page.get("continuationToken")
            if token is None or token == "":
                observed_at = self.clock()
                if observed_at.tzinfo is None or observed_at.utcoffset() is None:
                    raise ValueError("Catalog observation time must be timezone-aware")
                return CatalogObservation(
                    workspace_id=self.workspace_id,
                    observed_at=observed_at,
                    pages_fetched=page_number,
                    candidates=tuple(rows[key] for key in sorted(rows)),
                )
            if not isinstance(token, str) or not token.strip() or token in seen_tokens:
                raise ValueError("Catalog returned an invalid or repeated continuation token")
            seen_tokens.add(token)
            body = {"continuationToken": token}
        raise ValueError("Catalog page limit exceeded")

    def fetch_verified(self) -> VerifiedCatalogObservation:
        """Check every discovered item's current metadata, or raise atomically.

        Search limits bound the number of direct GETs. Deletion, access errors,
        unsupported item APIs and identity/type drift are errors, not retirement
        evidence. Sequential reads do not provide a transactional snapshot.
        """
        catalog = self.fetch()
        verified: list[VerifiedCatalogItem] = []
        previous_verified_at = catalog.observed_at
        for candidate in catalog.candidates:
            endpoint = (
                f"/workspaces/{self.workspace_id}/items/{candidate.item_id}"
            )
            value = self.client.request(
                "GET", endpoint, wait_for_completion=False,
                telemetry_skill="onelake-catalog-govern-cli",
            )
            if (
                _guid(value.get("id")) != candidate.item_id
                or _guid(value.get("workspaceId")) != self.workspace_id
                or _text(value.get("type")) != candidate.item_type
            ):
                raise ValueError("Catalog direct item identity or type changed")
            current = CatalogCandidate(
                item_id=candidate.item_id,
                item_type=candidate.item_type,
                workspace_id=self.workspace_id,
                display_name=_text(value.get("displayName")),
                description=_description(value.get("description")),
            )
            verified_at = self.clock()
            if verified_at.tzinfo is None or verified_at.utcoffset() is None:
                raise ValueError("Catalog verification time must be timezone-aware")
            if verified_at < catalog.observed_at:
                raise ValueError("Catalog verification time precedes search observation")
            if verified_at < previous_verified_at:
                raise ValueError("Catalog verification time precedes previous item verification")
            previous_verified_at = verified_at
            verified.append(VerifiedCatalogItem(
                current=current, endpoint=endpoint, verified_at=verified_at,
                catalog_metadata_changed=current != candidate,
            ))
        return VerifiedCatalogObservation(catalog=catalog, verified_items=tuple(verified))

    def _candidate(self, value: object) -> CatalogCandidate:
        if not isinstance(value, dict) or value.get("catalogEntryType") != "FabricItem":
            raise ValueError("Catalog returned a non-item entry")
        hierarchy = value.get("hierarchy")
        workspace = hierarchy.get("workspace") if isinstance(hierarchy, dict) else None
        if not isinstance(workspace, dict) or _guid(workspace.get("id")) != self.workspace_id:
            raise ValueError("Catalog returned an item outside the allowed workspace")
        item_type = _text(value.get("type"))
        if item_type == "Workspace":
            raise ValueError("Catalog returned a workspace instead of an item")
        return CatalogCandidate(
            item_id=_guid(value.get("id")),
            item_type=item_type,
            display_name=_text(value.get("displayName")),
            description=_description(value.get("description")),
            workspace_id=self.workspace_id,
        )


def _guid(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("Catalog identity must be a GUID")
    return str(UUID(value))


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Catalog item metadata must be nonempty text")
    return value


def _description(value: object) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise TypeError("Catalog returned an invalid description")
    return value
