"""Non-authoritative Phase 13 protocol harness.

The harness names the contracts later plans implement while keeping all state
in memory. It cannot access Fabric, OneLake, Azure, or any production writer.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

MAX_CHANGED_ENTITIES = 50
MAX_CANDIDATE_PAIRS = 200
MAX_EVIDENCE_RECORDS = 40


class StaleFenceError(RuntimeError):
    """A pointer transition used a stale fence or stale active generation."""


class RollbackError(RuntimeError):
    """A rollback failed before its atomic pointer transition."""


@dataclass(frozen=True)
class RelationshipEdge:
    edge_id: str
    subject_id: str
    subject_type: str
    predicate: str
    object_id: str
    object_type: str
    source: str
    evidence_refs: tuple[str, ...]

    @property
    def triple(self) -> tuple[str, str, str]:
        return (self.subject_type, self.predicate, self.object_type)


@dataclass(frozen=True)
class EvidenceBatch:
    batch_id: str
    scope: str
    source_generation: str
    entity_ids: tuple[str, ...]
    candidate_pairs: tuple[RelationshipEdge, ...]
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _bounded("changed entities", len(self.entity_ids), MAX_CHANGED_ENTITIES)
        _bounded("candidate pairs", len(self.candidate_pairs), MAX_CANDIDATE_PAIRS)
        _bounded("evidence records", len(self.evidence_ids), MAX_EVIDENCE_RECORDS)
        if len(set(self.entity_ids)) != len(self.entity_ids):
            raise ValueError("entity ids must be unique")
        if len({edge.edge_id for edge in self.candidate_pairs}) != len(
            self.candidate_pairs
        ):
            raise ValueError("candidate edge ids must be unique")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("evidence ids must be unique")


@dataclass(frozen=True)
class CandidateGeneration:
    generation_id: str
    source_generation: str
    edges: tuple[RelationshipEdge, ...]

    @property
    def edge_ids(self) -> tuple[str, ...]:
        return tuple(edge.edge_id for edge in self.edges)


@dataclass(frozen=True)
class ContractTrace:
    reviewed_proposal_ids: tuple[str, ...]
    candidate: CandidateGeneration
    validation_passed: bool
    promoted_generation: str
    consumer_generation: str
    rolled_back_generation: str


class FencedPointerStore:
    """Retained in-memory generations with fenced compare-and-swap visibility."""

    def __init__(self, *, initial_generation: str, initial_fence: int) -> None:
        self._active_generation = initial_generation
        self._fence = initial_fence
        self._retained = {initial_generation}

    def resolve(self) -> str:
        """Resolve the one reader-visible generation."""
        return self._active_generation

    def promote(
        self,
        candidate: CandidateGeneration,
        *,
        expected_generation: str,
        fencing_token: int,
    ) -> str:
        """Conditionally promote a complete immutable candidate."""
        self._assert_current(expected_generation, fencing_token)
        self._retained.add(candidate.generation_id)
        self._active_generation = candidate.generation_id
        self._fence = fencing_token
        return self._active_generation

    def rollback(
        self,
        *,
        target_generation: str,
        expected_generation: str,
        fencing_token: int,
        fail_before_swap: bool = False,
    ) -> str:
        """Conditionally move the pointer to a retained valid generation."""
        self._assert_current(expected_generation, fencing_token)
        if target_generation not in self._retained:
            raise RollbackError("rollback target is not retained")
        if fail_before_swap:
            raise RollbackError("injected rollback failure before pointer swap")
        self._active_generation = target_generation
        self._fence = fencing_token
        return self._active_generation

    def _assert_current(self, expected_generation: str, fencing_token: int) -> None:
        if expected_generation != self._active_generation:
            raise StaleFenceError("active generation precondition failed")
        if fencing_token <= self._fence:
            raise StaleFenceError("fencing token is stale")


class ContractHarness:
    """Exercise proposal, review, admission, validation, pointer, and rollback."""

    def __init__(self, pointer: FencedPointerStore) -> None:
        self.pointer = pointer

    def build_candidate(
        self,
        batch: EvidenceBatch,
        *,
        reviewed_proposal_ids: set[str],
        shadow_mode: bool,
        released_triples: set[tuple[str, str, str]] | None = None,
    ) -> CandidateGeneration:
        """Build a deterministic candidate without granting model authority."""
        released = released_triples or set()
        admitted: list[RelationshipEdge] = []
        for edge in batch.candidate_pairs:
            if edge.source == "deterministic":
                admitted.append(edge)
                continue
            if edge.source != "model":
                raise ValueError(f"unknown edge source {edge.source!r}")
            if (
                not shadow_mode
                and edge.edge_id in reviewed_proposal_ids
                and edge.triple in released
            ):
                admitted.append(edge)
        admitted.sort(key=lambda edge: edge.edge_id)
        normalized = {
            "source_generation": batch.source_generation,
            "edge_ids": [edge.edge_id for edge in admitted],
        }
        digest = hashlib.sha256(
            json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return CandidateGeneration(
            generation_id=f"generation-{digest[:16]}",
            source_generation=batch.source_generation,
            edges=tuple(admitted),
        )

    def validate(
        self, candidate: CandidateGeneration, batch: EvidenceBatch
    ) -> None:
        """Fail closed on unknown endpoints, citations, or model authority."""
        known_entities = set(batch.entity_ids)
        known_evidence = set(batch.evidence_ids)
        for edge in candidate.edges:
            if edge.subject_id not in known_entities or edge.object_id not in known_entities:
                raise ValueError(f"candidate edge {edge.edge_id} has an unknown endpoint")
            if not edge.evidence_refs or not set(edge.evidence_refs) <= known_evidence:
                raise ValueError(f"candidate edge {edge.edge_id} has invalid evidence")

    def run(
        self,
        batch: EvidenceBatch,
        *,
        reviewed_proposal_ids: set[str],
        shadow_mode: bool,
        fencing_token: int,
        released_triples: set[tuple[str, str, str]] | None = None,
    ) -> ContractTrace:
        """Run one safe promotion and rollback leg through the protocol."""
        previous = self.pointer.resolve()
        candidate = self.build_candidate(
            batch,
            reviewed_proposal_ids=reviewed_proposal_ids,
            shadow_mode=shadow_mode,
            released_triples=released_triples,
        )
        self.validate(candidate, batch)
        promoted = self.pointer.promote(
            candidate,
            expected_generation=previous,
            fencing_token=fencing_token,
        )
        consumer = self.pointer.resolve()
        rolled_back = self.pointer.rollback(
            target_generation=previous,
            expected_generation=promoted,
            fencing_token=fencing_token + 1,
        )
        return ContractTrace(
            reviewed_proposal_ids=tuple(sorted(reviewed_proposal_ids)),
            candidate=candidate,
            validation_passed=True,
            promoted_generation=promoted,
            consumer_generation=consumer,
            rolled_back_generation=rolled_back,
        )


def _bounded(name: str, actual: int, maximum: int) -> None:
    if actual > maximum:
        raise ValueError(f"{name} exceeds limit {maximum}: {actual}")


def edge_ids(edges: Iterable[RelationshipEdge]) -> tuple[str, ...]:
    """Return deterministic edge IDs for fixture assertions."""
    return tuple(sorted(edge.edge_id for edge in edges))


def candidate_membership_hash(candidate: CandidateGeneration) -> str:
    """Hash exact ordered candidate membership for immutable fixture assertions."""
    payload = json.dumps(
        list(candidate.edge_ids),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def normalized_fixture_hash(case: Mapping[str, Any]) -> str:
    """Hash a fixture bundle without its self-referential hash field."""
    normalized = {key: value for key, value in case.items() if key != "fixture_hash"}
    payload = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def materialize_fixture_batch(case: Mapping[str, Any]) -> EvidenceBatch:
    """Expand one compact synthetic fixture descriptor into exact protocol input."""
    scenario_id = str(case["scenario_id"])
    inputs = case["input"]
    if not isinstance(inputs, Mapping):
        raise TypeError("fixture input must be an object")
    entity_count = _fixture_count(inputs, "entity_count")
    pair_count = _fixture_count(inputs, "candidate_pair_count")
    evidence_count = _fixture_count(inputs, "evidence_count")
    deterministic_count = _fixture_count(inputs, "deterministic_pair_count")
    if entity_count < 2:
        raise ValueError("fixture requires at least two entities")
    if deterministic_count > pair_count:
        raise ValueError("deterministic pair count exceeds candidate pair count")

    entities = tuple(
        f"/subscriptions/synthetic-sub/resourceGroups/wave0/providers/"
        f"Microsoft.Test/resources/{scenario_id}-entity-{index:03d}"
        for index in range(entity_count)
    )
    evidence = tuple(
        f"{scenario_id}-evidence-{index:03d}" for index in range(evidence_count)
    )
    pairs = tuple(
        RelationshipEdge(
            edge_id=f"{scenario_id}-edge-{index:03d}",
            subject_id=entities[index % entity_count],
            subject_type="SyntheticResource",
            predicate="depends_on",
            object_id=entities[(index + 1) % entity_count],
            object_type="SyntheticResource",
            source="deterministic" if index < deterministic_count else "model",
            evidence_refs=(evidence[index % evidence_count],) if evidence else (),
        )
        for index in range(pair_count)
    )
    return EvidenceBatch(
        batch_id=f"batch-{scenario_id}",
        scope=str(case["scope"]),
        source_generation=str(case["source_generation"]),
        entity_ids=entities,
        candidate_pairs=pairs,
        evidence_ids=evidence,
    )


def _fixture_count(inputs: Mapping[str, Any], field: str) -> int:
    value = inputs[field]
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value
