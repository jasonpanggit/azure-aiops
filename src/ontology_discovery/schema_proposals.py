"""Closed, advisory schema-proposal envelope (separate from relationship proposals).

Operations are typed values with explicit before/after and stable IDs.  There is
no arbitrary patch, TMDL or serialized definition field.  Every operation is
review-only; nothing here executes or materializes a definition.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Collection, Mapping
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

SCHEMA_PROPOSAL_KIND = "ontology-schema-proposal"
SCHEMA_PROPOSAL_VERSION = 1
SchemaFormat = Literal["legacy-json", "ontology-tmdl"]
_FINGERPRINT = r"^sha256:[a-f0-9]{64}$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)


class DescriptionChange(_Strict):
    op: Literal["description_change"]
    target_kind: Literal["entity", "relationship"]
    stable_id: str = Field(min_length=1, max_length=128)
    before: str = Field(max_length=2_000)
    after: str = Field(max_length=2_000)


class DeclareEntity(_Strict):
    op: Literal["declare_entity"]
    stable_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(max_length=2_000)


class DeclareRelationship(_Strict):
    op: Literal["declare_relationship"]
    stable_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=128)
    source_stable_id: str = Field(min_length=1, max_length=128)
    target_stable_id: str = Field(min_length=1, max_length=128)


class BindingChange(_Strict):
    op: Literal["binding_change"]
    stable_id: str = Field(min_length=1, max_length=128)
    binding_path: str = Field(min_length=1, max_length=512)
    before: str = Field(min_length=1, max_length=256)
    after: str = Field(min_length=1, max_length=256)


SchemaOperation = Annotated[
    DescriptionChange | DeclareEntity | DeclareRelationship | BindingChange,
    Field(discriminator="op"),
]


class BindingDiffEntry(_Strict):
    stable_id: str = Field(min_length=1, max_length=128)
    before: str = Field(max_length=256)
    after: str = Field(max_length=256)


class ProviderProvenance(_Strict):
    provider: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    model: str = Field(default="", max_length=128, pattern=r"^[A-Za-z0-9._:/-]*$")


class SchemaProposalEnvelope(_Strict):
    kind: Literal["ontology-schema-proposal"]
    version: Literal[1]
    scope: str = Field(min_length=1, max_length=256)
    workspace_id: str = Field(min_length=1, max_length=128)
    item_id: str = Field(min_length=1, max_length=128)
    format: SchemaFormat
    base_fingerprint: str = Field(pattern=_FINGERPRINT)
    source_generation_id: str = Field(min_length=1, max_length=128)
    evidence_refs: list[str] = Field(min_length=1, max_length=40)
    preserved_ids: list[str] = Field(max_length=5_000)
    operations: list[SchemaOperation] = Field(min_length=1, max_length=20)
    binding_diff: list[BindingDiffEntry] = Field(max_length=100)
    provenance: ProviderProvenance

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        known = set(self.preserved_ids)
        for op in self.operations:
            if isinstance(op, (DescriptionChange, BindingChange)) and op.stable_id not in known:
                raise ValueError("operation stable_id is not in preserved_ids")
            if isinstance(op, DeclareRelationship):
                for ref in (op.source_stable_id, op.target_stable_id):
                    declared = {o.stable_id for o in self.operations if isinstance(o, DeclareEntity)}
                    if ref not in known and ref not in declared:
                        raise ValueError("relationship endpoint stable_id is unknown")
            if isinstance(op, (DeclareEntity, DeclareRelationship)) and op.stable_id in known:
                raise ValueError("declaration collides with a preserved stable id")
        binding_ids = {o.stable_id for o in self.operations if isinstance(o, BindingChange)}
        if {d.stable_id for d in self.binding_diff} != binding_ids:
            raise ValueError("binding_diff must match binding_change operations exactly")
        for d in self.binding_diff:
            match = [o for o in self.operations if isinstance(o, BindingChange) and o.stable_id == d.stable_id]
            if not any(o.before == d.before and o.after == d.after for o in match):
                raise ValueError("binding_diff before/after disagree with operation")
        return self


class SchemaProposalRejected(ValueError):
    """Untrusted envelope failed strict validation or trusted binding."""


_ENVELOPE_ADAPTER = TypeAdapter(SchemaProposalEnvelope)


def operation_digest(envelope: SchemaProposalEnvelope) -> str:
    payload = {
        "workspace_id": envelope.workspace_id,
        "item_id": envelope.item_id,
        "format": envelope.format,
        "base_fingerprint": envelope.base_fingerprint,
        "operations": [o.model_dump(mode="json") for o in envelope.operations],
        "binding_diff": [d.model_dump(mode="json") for d in envelope.binding_diff],
        "preserved_ids": sorted(envelope.preserved_ids),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def proposal_id_for(envelope: SchemaProposalEnvelope) -> str:
    return f"OSP-{operation_digest(envelope).upper()}"


def parse_envelope(raw: bytes | str | Mapping[str, Any]) -> SchemaProposalEnvelope:
    """Whole-document strict parse; relationship batches and extras reject."""

    try:
        document = json.loads(raw) if isinstance(raw, (bytes, str)) else dict(raw)
        if not isinstance(document, dict):
            raise SchemaProposalRejected("schema proposal must be a JSON object")
        if "proposals" in document or "batch_id" in document:
            raise SchemaProposalRejected("relationship output is not a schema proposal")
        return _ENVELOPE_ADAPTER.validate_python(document)
    except SchemaProposalRejected:
        raise
    except Exception as exc:
        raise SchemaProposalRejected(f"invalid schema proposal: {type(exc).__name__}") from exc


def validate_against_trusted(
    envelope: SchemaProposalEnvelope,
    *,
    scope: str,
    workspace_id: str,
    item_id: str,
    format: str,
    base_fingerprint: str,
    known_evidence_refs: Collection[str],
    base_stable_ids: Collection[str] | None,
) -> None:
    """Bind the untrusted envelope to trusted target/base/evidence (outside payload)."""

    if (envelope.scope, envelope.workspace_id, envelope.item_id, envelope.format) != (
        scope, workspace_id, item_id, format,
    ):
        raise SchemaProposalRejected("foreign or mismatched target")
    if envelope.base_fingerprint != base_fingerprint:
        raise SchemaProposalRejected("base fingerprint does not match captured base")
    unknown = set(envelope.evidence_refs) - set(known_evidence_refs)
    if unknown:
        raise SchemaProposalRejected("fabricated evidence citation")
    if base_stable_ids is not None:
        missing = set(envelope.preserved_ids) - set(base_stable_ids)
        if missing:
            raise SchemaProposalRejected("preserved id not present in captured base")
