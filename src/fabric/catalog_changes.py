"""Advisory item-metadata deltas, never Catalog-based retirement authority."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    @field_validator(
        "search_complete", "authoritative", "requires_direct_verification",
        "requires_schema_verification", mode="before", check_fields=False,
    )
    @classmethod
    def boolean_flags(cls, value: object) -> object:
        if type(value) is not bool:
            raise ValueError("Catalog evidence flags must be JSON booleans")
        return value


class _Item(_Closed):
    item_id: UUID
    item_type: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    description: str
    workspace_id: UUID


class _Search(_Closed):
    source: Literal["onelake_catalog"]
    workspace_id: UUID
    observed_at: AwareDatetime
    pages_fetched: int = Field(strict=True, ge=1)
    search_complete: Literal[True]
    coverage: Literal["partial"]
    authoritative: Literal[False]
    requires_direct_verification: Literal[True]
    candidates: list[_Item] = Field(max_length=1000)


class _VerifiedItem(_Closed):
    current: _Item
    endpoint: str
    verified_at: AwareDatetime
    catalog_metadata_changed: bool = Field(strict=True)


class _Evidence(_Closed):
    source: Literal["onelake_catalog_verified_items"]
    catalog: _Search
    coverage: Literal["partial"]
    authoritative: Literal[False]
    verification_scope: Literal["item_metadata_only"]
    requires_direct_verification: Literal[False]
    requires_schema_verification: Literal[True]
    verified_items: list[_VerifiedItem] = Field(max_length=1000)

    @model_validator(mode="after")
    def consistent(self) -> _Evidence:
        indexed = {row.item_id: row for row in self.catalog.candidates}
        verified = {row.current.item_id: row for row in self.verified_items}
        if (
            len(indexed) != len(self.catalog.candidates)
            or len(verified) != len(self.verified_items)
            or indexed.keys() != verified.keys()
        ):
            raise ValueError("Catalog evidence item identities must match uniquely")
        for item_id, row in verified.items():
            candidate = indexed[item_id]
            expected_endpoint = f"/workspaces/{self.catalog.workspace_id}/items/{item_id}"
            if (
                row.current.workspace_id != self.catalog.workspace_id
                or candidate.workspace_id != self.catalog.workspace_id
                or row.current.item_type != candidate.item_type
                or row.current.item_type == "Workspace"
                or row.endpoint != expected_endpoint
                or row.verified_at < self.catalog.observed_at
                or row.catalog_metadata_changed != (row.current != candidate)
                or not row.current.item_type.strip()
                or not row.current.display_name.strip()
                or not candidate.display_name.strip()
            ):
                raise ValueError("Catalog evidence scope, identity or provenance mismatch")
        return self


class _Report(_Closed):
    status: Literal["advisory_metadata_verified"]
    authentication_mode: Literal["managed_identity", "service_principal"]
    evidence: _Evidence


def validate_catalog_report(raw: str) -> dict[str, Any]:
    """Parse saved advisory evidence, not an authenticated maintenance approval.

    Structural/provenance checks prevent accidental cross-scope or partial
    comparison. Local JSON cannot prove that an identity performed the reads.
    """
    if len(raw.encode("utf-8")) > 2_000_000:
        raise ValueError("Catalog baseline exceeds the serialized size limit")
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object)
    except RecursionError as exc:
        raise ValueError("Catalog baseline JSON nesting exceeds the decoder limit") from exc
    if not isinstance(value, dict):
        raise TypeError("Catalog baseline must be an object")
    # A previous comparison is derived output, never baseline input evidence.
    value.pop("metadata_delta", None)
    return _Report.model_validate_json(json.dumps(value)).model_dump(mode="json")


def compare_catalog_reports(
    previous: dict[str, Any], current: dict[str, Any],
) -> dict[str, Any]:
    """Compare validated direct item metadata; unseen items stay unresolved.

    No item ID is an ontology stable ID. Changed types require review rather
    than an automatic schema change. Both reports must share workspace/auth
    mode, and the current search must not predate baseline verification.
    """
    before = _Report.model_validate_json(json.dumps(previous))
    after = _Report.model_validate_json(json.dumps(current))
    if (
        before.evidence.catalog.workspace_id != after.evidence.catalog.workspace_id
        or before.authentication_mode != after.authentication_mode
    ):
        raise ValueError("Catalog comparison scope or authentication mode changed")
    previous_end = max(
        (row.verified_at for row in before.evidence.verified_items),
        default=before.evidence.catalog.observed_at,
    )
    if after.evidence.catalog.observed_at < previous_end:
        raise ValueError("Catalog observation precedes baseline verification")
    old = {str(row.current.item_id): row.current for row in before.evidence.verified_items}
    new = {str(row.current.item_id): row.current for row in after.evidence.verified_items}
    changed = []
    unchanged = []
    for item_id in sorted(old.keys() & new.keys()):
        fields = [
            name for name in ("item_type", "display_name", "description")
            if getattr(old[item_id], name) != getattr(new[item_id], name)
        ]
        if fields:
            changed.append({
                "item_id": item_id, "changed_fields": fields,
                "before": old[item_id].model_dump(mode="json"),
                "after": new[item_id].model_dump(mode="json"),
            })
        else:
            unchanged.append(item_id)
    return {
        "source": "onelake_catalog_metadata_delta",
        "workspace_id": str(after.evidence.catalog.workspace_id),
        "coverage": "partial",
        "authoritative": False,
        "requires_steward_review": True,
        "requires_schema_verification": True,
        "baseline_sha256": _digest(before),
        "current_sha256": _digest(after),
        "added": [new[key].model_dump(mode="json") for key in sorted(new.keys() - old.keys())],
        "changed": changed,
        "unresolved": [
            {"before": old[key].model_dump(mode="json"), "reason": "not_observed"}
            for key in sorted(old.keys() - new.keys())
        ],
        "unchanged": unchanged,
        "retired": [],
    }


def _digest(report: _Report) -> str:
    value = report.model_dump(mode="json")
    evidence = value["evidence"]
    evidence["catalog"]["candidates"].sort(key=lambda row: row["item_id"])
    evidence["verified_items"].sort(key=lambda row: row["current"]["item_id"])
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Catalog report contains duplicate JSON keys")
        result[key] = value
    return result
