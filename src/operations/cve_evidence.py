"""Private, bounded CVE evidence receipts acquired by the authorized server."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from operations.patch_review import PatchReviewFilters, PatchReviewFinding
from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore

MAX_BYTES = 512 * 1024
CVE_PATTERN = r"^CVE-\d{4}-\d{4,}$"


class CaptureCveEvidence(BaseModel):
    """Only query bindings and a reviewed revision are browser-controlled."""

    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: int = Field(ge=0, le=20)
    generation: str = Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9._:-]+$")
    cursor: str | None = Field(default=None, max_length=8192)
    page_size: int = Field(ge=1, le=100)
    sort_by: Literal["priority_score", "severity", "target_id", "weakness_id"] = "priority_score"
    sort_direction: Literal["asc", "desc"] = "desc"
    filters: PatchReviewFilters


class CveSourceReceipt(BaseModel):
    """Small public catalog projection, not an arbitrary provider payload."""

    model_config = ConfigDict(extra="forbid", strict=True)
    source: Literal["nvd", "epss", "kev", "msrc"]
    identifier: str = Field(min_length=1, max_length=256)
    status: str = Field(min_length=1, max_length=80)
    stale: bool
    has_last_known_good: bool
    source_at: str = Field(max_length=80)
    safe_error_code: str = Field(max_length=128)
    severity: str = Field(default="", max_length=80)
    cvss_score: float | None = Field(default=None, ge=0, le=10, allow_inf_nan=False)
    cvss_vector: str = Field(default="", max_length=256)
    epss_score: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    kev_listed: bool | None = None
    kb_ids: list[str] = Field(default_factory=list, max_length=100)
    product_ids: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def bounded(self) -> CveSourceReceipt:
        """Reject ambiguous or unbounded recorded identifiers."""
        for values in (self.kb_ids, self.product_ids):
            if len(values) != len(set(values)) or any(not value.strip() or len(value) > 256 for value in values):
                raise ValueError("Catalog identifiers are duplicate or unbounded")
        return self


class CveEvidenceReceipt(BaseModel):
    """Immutable server attribution plus scoped finding and external evidence."""

    model_config = ConfigDict(extra="forbid", strict=True)
    receipt_id: str = Field(pattern=r"^cve-[a-f0-9]{32}$")
    captured_at: str
    actor: str = Field(min_length=1)
    scope: dict[str, list[str]]
    cve_id: str = Field(pattern=CVE_PATTERN)
    generation: str = Field(min_length=1, max_length=256)
    query_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    filters: PatchReviewFilters
    sort_by: str
    sort_direction: str
    page_size: int = Field(ge=1, le=100)
    cursor_page: bool
    total_count: int = Field(ge=0, le=9_007_199_254_740_991)
    source_completeness: str = Field(min_length=1, max_length=80)
    source_observed_at: str = Field(max_length=80)
    findings: list[PatchReviewFinding] = Field(max_length=100)
    sources: list[CveSourceReceipt] = Field(max_length=40)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def coherent(self) -> CveEvidenceReceipt:
        """Verify immutable payload integrity and CVE/page identity."""
        if datetime.fromisoformat(self.captured_at).tzinfo is None:
            raise ValueError("Capture clock requires a timezone")
        if self.filters.weakness_id != self.cve_id or len(self.findings) > min(self.page_size, self.total_count):
            raise ValueError("Receipt query/count mismatch")
        if len({row.exposure_id for row in self.findings}) != len(self.findings) or any(row.weakness_id.upper() != self.cve_id for row in self.findings):
            raise ValueError("Receipt finding identity mismatch")
        if len({(row.source, row.identifier) for row in self.sources}) != len(self.sources):
            raise ValueError("Receipt source identities are duplicate")
        if any(row.source != "msrc" and row.identifier.upper() != self.cve_id for row in self.sources):
            raise ValueError("Receipt public source CVE mismatch")
        if self.sha256 != receipt_digest(self.model_dump(exclude={"sha256"})):
            raise ValueError("CVE receipt digest does not agree")
        return self


def canonical_json(payload: dict) -> str:
    """Serialize portable exact JSON bytes, preserving numeric representation."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def receipt_digest(payload: dict) -> str:
    """Hash canonical UTF-8 JSON; integrity is not a signature or attestation."""
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()


class CveEvidenceHistory(BaseModel):
    """Exact actor/scope/CVE append-only receipts, without silent eviction."""

    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[1] = 1
    actor: str = Field(min_length=1)
    scope: dict[str, list[str]]
    cve_id: str = Field(pattern=CVE_PATTERN)
    revision: int = Field(ge=0, le=20)
    receipts: list[CveEvidenceReceipt] = Field(max_length=20)

    @model_validator(mode="after")
    def coherent(self) -> CveEvidenceHistory:
        """Reject corrupt history identity, attribution or revision."""
        if self.revision != len(self.receipts) or len({row.receipt_id for row in self.receipts}) != self.revision:
            raise ValueError("CVE evidence revision mismatch")
        if any(row.actor != self.actor or row.scope != self.scope or row.cve_id != self.cve_id for row in self.receipts):
            raise ValueError("CVE evidence receipt attribution mismatch")
        return self


def _source_receipts(catalog: dict) -> list[CveSourceReceipt]:
    rows = []
    for source in catalog["item"]["sources"].values():
        name = source["source"]
        if name not in {"nvd", "epss", "kev", "msrc"}:
            raise ValueError("Unexpected CVE catalog source")
        payload = source.get("payload") or {}
        if payload.get("cve_id") and payload["cve_id"].upper() != catalog["item"]["cve_id"].upper():
            raise ValueError("CVE provider payload identity mismatch")
        if name == "msrc" and payload.get("cve_ids") and catalog["item"]["cve_id"].upper() not in {value.upper() for value in payload["cve_ids"]}:
            raise ValueError("MSRC association belongs to another CVE")
        cvss = payload.get("cvss") or {}
        values = {}
        if name == "nvd":
            values = {"severity": payload.get("severity") or "", "cvss_score": cvss.get("base_score"), "cvss_vector": cvss.get("vector") or "", "kb_ids": payload.get("associated_kbs") or []}
        elif name == "epss":
            values = {"epss_score": payload.get("epss_score")}
        elif name == "kev":
            values = {"kev_listed": bool(payload) if source["status"] in {"success", "succeeded", "complete"} and not source["stale"] else None}
        else:
            values = {"kb_ids": [payload["kb_id"]] if payload.get("kb_id") else [], "product_ids": payload.get("product_ids") or []}
        rows.append(CveSourceReceipt(
            source=name, identifier=source["identifier"], status=source["status"], stale=source["stale"],
            has_last_known_good=source["has_last_known_good"], source_at=source.get("source_at") or "",
            safe_error_code=source.get("safe_error_code") or "", **values,
        ))
    return sorted(rows, key=lambda row: (row.source, row.identifier))


class CveEvidenceStore:
    """Retain server-reacquired receipts with existing document CAS storage."""

    def __init__(self, documents: OneLakeDocumentStore):
        self.documents = documents

    @staticmethod
    def _name(actor: str, scope: dict, cve_id: str) -> str:
        return f"state/cve-evidence/{receipt_digest({'actor': actor, 'scope': scope, 'cve_id': cve_id})}.json"

    @staticmethod
    def _bounded(payload: dict) -> None:
        if len((json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()) > MAX_BYTES:
            raise ValueError("CVE evidence history exceeds 512 KiB")

    def _read(self, actor: str, scope: dict, cve_id: str):
        name = self._name(actor, scope, cve_id)
        snapshot = self.documents.read_snapshot(name)
        if snapshot.exists:
            self._bounded(snapshot.payload)
            state = CveEvidenceHistory.model_validate(snapshot.payload)
        else:
            state = CveEvidenceHistory(actor=actor, scope=scope, cve_id=cve_id, revision=0, receipts=[])
        if state.actor != actor or state.scope != scope or state.cve_id != cve_id:
            raise ValueError("CVE evidence history identity mismatch")
        return name, snapshot, state

    def read(self, actor: str, scope: dict, cve_id: str) -> dict:
        """Read retained receipts only; no provider acquisition or refresh."""
        return self._read(actor, scope, cve_id)[2].model_dump()

    def append(self, actor: str, scope: dict, cve_id: str, request: CaptureCveEvidence, page: dict, catalog: dict) -> dict:
        """Capture strict server projections, rejecting mixed source identities."""
        name, snapshot, state = self._read(actor, scope, cve_id)
        if state.revision != request.expected_revision or state.revision >= 20:
            raise DocumentConflictError("CVE evidence changed or reached 20 receipts; reload. No receipts were evicted")
        if request.filters.weakness_id != cve_id or page["scope"] != scope or catalog["scope"] != scope:
            raise ValueError("CVE evidence source scope/CVE mismatch")
        data = catalog["data"]
        if page["generation"] != request.generation or data["generation"] != request.generation or data["item"]["cve_id"].upper() != cve_id:
            raise ValueError("CVE evidence source generation/CVE mismatch")
        if data["catalog_scope"] != "external_public_metadata" or data["environment_membership_included"] is not False or page["completeness"]["state"] == "unavailable":
            raise ValueError("CVE source evidence is unavailable or invalid")
        findings = []
        for row in page["items"]:
            if row.get("read_model_generation_id") not in {None, request.generation}:
                raise ValueError("CVE finding generation mismatch")
            findings.append(PatchReviewFinding(
                exposure_id=row["exposure_id"], target_id=row["target_id"], weakness_id=row["weakness_id"],
                target_kind=row["target_kind"], severity=row.get("severity") or "unknown",
                completeness=row.get("completeness") or "unknown", sla_state=row.get("sla_state") or "unknown",
            ))
        selectors = request.model_dump(exclude={"expected_revision", "generation", "cursor"})
        payload = {
            "receipt_id": f"cve-{uuid4().hex}", "captured_at": datetime.now(UTC).isoformat(),
            "actor": actor, "scope": scope, "cve_id": cve_id, "generation": request.generation,
            "query_fingerprint": receipt_digest(selectors), "filters": request.filters.model_dump(),
            "sort_by": request.sort_by, "sort_direction": request.sort_direction, "page_size": request.page_size,
            "cursor_page": bool(request.cursor), "total_count": page["total_count"],
            "source_completeness": page["completeness"]["state"], "source_observed_at": page["freshness"].get("as_of") or "",
            "findings": [row.model_dump() for row in findings],
            "sources": [row.model_dump() for row in _source_receipts(data)],
        }
        receipt = CveEvidenceReceipt(**payload, sha256=receipt_digest(payload))
        stored = CveEvidenceHistory(actor=actor, scope=scope, cve_id=cve_id, revision=state.revision + 1, receipts=[*state.receipts, receipt]).model_dump()
        self._bounded(stored)
        if snapshot.exists:
            self.documents.replace_if_match(name, stored, expected_etag=snapshot.etag)
        else:
            self.documents.create_only(name, stored)
        return stored
