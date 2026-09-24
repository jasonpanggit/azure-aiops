"""Bounded, proposal-only semantic evolution contracts and coordination."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .store import OntologyRunStore


class GenerationPinnedProfile(BaseModel):
    """A semantic profile that is immutable and bound to one source generation."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    profile_id: str = Field(min_length=1, max_length=256)
    source_generation_id: str = Field(min_length=1, max_length=256)
    semantic_model_name: str = Field(min_length=1, max_length=256)
    tables: tuple[str, ...] = Field(min_length=1, max_length=500)
    profile_version: str = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_tables(self) -> GenerationPinnedProfile:
        if len(set(self.tables)) != len(self.tables):
            raise ValueError("profile tables must be unique")
        return self


class SemanticEvidence(BaseModel):
    """Bounded evidence supporting a semantic proposal."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    evidence_id: str = Field(min_length=1, max_length=256)
    source_generation_id: str = Field(min_length=1, max_length=256)
    table: str = Field(min_length=1, max_length=256)
    kind: Literal["column", "relationship", "hierarchy", "measure", "description"]
    details: str = Field(min_length=1, max_length=2000)


class SafeMetadataProposal(BaseModel):
    """Additive metadata proposal; identity and scope changes are forbidden."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    proposal_id: str = Field(min_length=1, max_length=256)
    source_generation_id: str = Field(min_length=1, max_length=256)
    table: str = Field(min_length=1, max_length=256)
    field: str = Field(min_length=1, max_length=256)
    value: str = Field(min_length=1, max_length=4000)
    evidence_ids: tuple[str, ...] = Field(min_length=1, max_length=40)
    operation: Literal["add_description", "add_synonym", "add_classification"] = "add_description"

    @model_validator(mode="after")
    def reject_unsafe_fields(self) -> SafeMetadataProposal:
        if self.field.casefold() in {"identity", "cardinality", "scope", "delete", "drop", "replace"}:
            raise ValueError("destructive, identity, cardinality, or scope changes are forbidden")
        return self


class AdditiveStructuralProposal(BaseModel):
    """A reviewed additive semantic structure proposal."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    proposal_id: str = Field(min_length=1, max_length=256)
    source_generation_id: str = Field(min_length=1, max_length=256)
    kind: Literal["column", "relationship", "hierarchy", "measure"]
    table: str = Field(min_length=1, max_length=256)
    definition: dict[str, str] = Field(min_length=1, max_length=30)
    evidence_ids: tuple[str, ...] = Field(min_length=1, max_length=40)

    @model_validator(mode="after")
    def reject_unsafe_keys(self) -> AdditiveStructuralProposal:
        forbidden = {"identity", "cardinality", "scope", "delete", "drop", "replace"}
        if forbidden.intersection(self.definition):
            raise ValueError("destructive, identity, cardinality, or scope changes are forbidden")
        return self


class SemanticEvolutionBatch(BaseModel):
    """Validated profile, evidence, and additive proposals for one generation."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    profile: GenerationPinnedProfile
    evidence: tuple[SemanticEvidence, ...] = ()
    metadata: tuple[SafeMetadataProposal, ...] = ()
    structural: tuple[AdditiveStructuralProposal, ...] = ()

    @model_validator(mode="after")
    def pin_generation(self) -> SemanticEvolutionBatch:
        generation = self.profile.source_generation_id
        for item in (*self.evidence, *self.metadata, *self.structural):
            if item.source_generation_id != generation:
                raise ValueError("all semantic evolution inputs must share the profile generation")
        return self


def _proposal_digest(item: BaseModel) -> str:
    payload = item.model_dump(mode="json")
    return "SEM-" + hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest().upper()


class SemanticEvolutionCoordinator:
    """Persist proposals and compile only durably accepted proposals."""

    def __init__(self, store: OntologyRunStore) -> None:
        self.store = store

    def submit(self, batch: SemanticEvolutionBatch, *, scope: str, policy_version: str) -> tuple[dict, ...]:
        """Persist validated proposals without publishing or mutating Fabric."""
        rows: list[dict] = []
        for item in (*batch.metadata, *batch.structural):
            payload = item.model_dump(mode="json")
            payload["proposal_id"] = _proposal_digest(item)
            row, _ = self.store.save_proposal(
                proposal=payload,
                scope=scope,
                source_generation_id=batch.profile.source_generation_id,
                schema_version="semantic-evolution.v1",
                policy_version=policy_version,
            )
            rows.append(row)
        return tuple(rows)

    def compile_accepted(self, *, scope: str, source_generation_id: str) -> dict[str, list[dict]]:
        """Return deterministic additive metadata and structure accepted by stewards."""
        result: dict[str, list[dict]] = {"metadata": [], "structural": []}
        for row in self.store.list_proposals(scope=scope):
            if row.get("source_generation_id") != source_generation_id:
                continue
            if (row.get("review") or {}).get("status") != "accepted":
                continue
            proposal = dict(row.get("proposal") or row)
            target = "metadata" if "value" in proposal and "field" in proposal else "structural"
            result[target].append(proposal)
        for values in result.values():
            values.sort(key=lambda value: str(value.get("proposal_id") or ""))
        return result
