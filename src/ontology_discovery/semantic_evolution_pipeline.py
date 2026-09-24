"""Durable advisory semantic evolution pipeline."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from fabric.semantic_model_manager import build_semantic_model_definition

from .semantic_evolution import (
    AdditiveStructuralProposal,
    SafeMetadataProposal,
    SemanticEvolutionBatch,
)

_LOGGER = logging.getLogger(__name__)
DEFAULT_GOLD_ALLOWLIST = (
    "gold_exposure_facts",
    "gold_container_exposure_current",
    "gold_container_exposure_coverage",
    "ontology_entities",
    "ontology_relationships",
    "ontology_health",
    "ontology_business_context",
    "ontology_compliance_context",
)


class SemanticMonitoringReport(BaseModel):
    """Bounded monitoring facts; this report is never a publication command."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    source_generation_id: str = Field(min_length=1)
    freshness: str
    unmapped_tables: tuple[str, ...] = ()
    dangling_relationships: tuple[str, ...] = ()
    reconciliation_drift: tuple[str, ...] = ()
    query_failures: tuple[str, ...] = ()


class GoldGroundingAdvisoryAdapter(Protocol):
    """Read-only adapter contract for bounded advisory proposals."""

    def propose(self, *, generation_id: str, evidence: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
        """Return strict proposal JSON without acquiring tokens or mutating Fabric."""


class NoOpGoldGroundingAdapter:
    """Default-off adapter that returns no proposals."""

    def propose(self, *, generation_id: str, evidence: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
        return {"proposals": []}


class StrictGoldGroundingAdvisoryAdapter:
    """Fail-closed adapter wrapper enforcing generation and table allowlists.

    The wrapper deliberately accepts an already-authorized delegate rather than
    acquiring credentials or calling Fabric itself.
    """

    def __init__(
        self,
        delegate: GoldGroundingAdvisoryAdapter,
        *,
        allowlist: Sequence[str] = DEFAULT_GOLD_ALLOWLIST,
        generation_allowlist: Sequence[str] = (),
    ) -> None:
        self.delegate = delegate
        self.allowlist = frozenset(allowlist)
        self.generation_allowlist = frozenset(generation_allowlist)

    def propose(self, *, generation_id: str, evidence: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
        if generation_id not in self.generation_allowlist:
            raise ValueError("generation is outside the Gold grounding allowlist")
        if any(str(item.get("table") or "") not in self.allowlist for item in evidence):
            raise ValueError("evidence table is outside the Gold grounding allowlist")
        result = self.delegate.propose(generation_id=generation_id, evidence=evidence)
        if not isinstance(result, Mapping):
            raise TypeError("Gold grounding adapter must return a JSON object")
        proposals = result.get("proposals")
        if not isinstance(proposals, list):
            raise TypeError("Gold grounding adapter must return {proposals: []}")
        for proposal in proposals:
            if not isinstance(proposal, Mapping):
                raise TypeError("Gold grounding proposals must be JSON objects")
            if proposal.get("source_generation_id") != generation_id:
                raise ValueError("proposal generation does not match requested generation")
            if str(proposal.get("table") or "") not in self.allowlist:
                raise ValueError("proposal table is outside the Gold grounding allowlist")
            try:
                TypeAdapter(SafeMetadataProposal | AdditiveStructuralProposal).validate_python(
                    dict(proposal), strict=True
                )
            except ValidationError as error:
                raise ValueError("Gold grounding proposal violates the strict contract") from error
        return {"proposals": [dict(proposal) for proposal in proposals]}


class ProfileArtifactStore:
    """Atomic local JSON artifact store for candidate/profile/monitoring outputs."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def write(self, name: str, payload: Mapping[str, Any]) -> Path:
        if not name or "/" in name or "\\" in name:
            raise ValueError("artifact name must be a simple filename")
        target = self.root / name
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self.root,
            prefix=f".{name}.",
            suffix=".pending",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(json.dumps(dict(payload), sort_keys=True, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(target)
        return target


class SemanticEvolutionPipeline:
    """Compile deterministic local candidates and persist advisory artifacts only."""

    def __init__(self, artifact_store: ProfileArtifactStore, adapter: GoldGroundingAdvisoryAdapter | None = None) -> None:
        self.artifacts = artifact_store
        self.adapter = adapter or NoOpGoldGroundingAdapter()

    def run(self, *, batch: SemanticEvolutionBatch, accepted: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
            gold_tables: Sequence[str] | None = None) -> dict[str, Any]:
        tables = tuple(sorted(set(gold_tables or batch.profile.tables), key=str.casefold))
        normalized = self._compile_metadata(accepted or {})
        definition = build_semantic_model_definition(
            batch.profile.semantic_model_name, list(tables), semantic_metadata=normalized
        )
        advisory = self.adapter.propose(
            generation_id=batch.profile.source_generation_id,
            evidence=[item.model_dump(mode="json") for item in batch.evidence],
        )
        report = SemanticMonitoringReport(
            source_generation_id=batch.profile.source_generation_id,
            freshness="current",
        )
        self.artifacts.write("semantic-candidate.json", definition)
        self.artifacts.write("semantic-profile.json", batch.profile.model_dump(mode="json"))
        self.artifacts.write("semantic-monitoring.json", report.model_dump(mode="json"))
        self.artifacts.write("semantic-advisory.json", advisory)
        return {"definition": definition, "report": report.model_dump(mode="json"), "advisory": advisory}

    @staticmethod
    def _compile_metadata(accepted: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, Any]:
        """Translate coordinator rows into manager metadata without changing meaning."""
        result: dict[str, Any] = {
            "descriptions": {}, "synonyms": {}, "classifications": {},
            "columns": {}, "relationships": [], "hierarchies": [], "measures": [],
            "proposal_ids": [],
        }
        for item in accepted.get("metadata", ()):
            table = str(item.get("table") or "")
            operation = str(item.get("operation") or "add_description")
            key = operation.removeprefix("add_") + "s" if operation != "add_description" else "descriptions"
            result.setdefault(key, {})
            result[key][table] = item.get("value")
            result["proposal_ids"].append(str(item.get("proposal_id") or ""))
        for item in accepted.get("structural", ()):
            kind = str(item.get("kind") or "")
            if kind in {"relationship", "measure", "hierarchy"}:
                result[f"{kind}s"].append(dict(item.get("definition") or {}))
            elif kind == "column":
                result["columns"].setdefault(str(item.get("table") or ""), []).append(
                    dict(item.get("definition") or {})
                )
            result["proposal_ids"].append(str(item.get("proposal_id") or ""))
        return result
