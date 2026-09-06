"""Deterministic proposal policy and the hard shadow admission boundary."""

from __future__ import annotations

import copy
import math
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from fabric.dataset_mapper import is_allowed_relationship_triple
from ontology_discovery.contracts import (
    AdmissionEvaluationSnapshot,
    proposal_content_id,
)

_ACCEPTED_REVIEW = "accepted"
_FRESH_STATES = frozenset({"fresh", "current"})
_REQUIRED_RELEASE_APPROVALS = frozenset(
    {
        "ontology_steward",
        "security_owner",
        "fabric_governance_steward",
    }
)


@dataclass(frozen=True)
class ProposalDecision:
    """Reproducible policy result for one untrusted model proposal."""

    proposal_id: str
    review_status: str
    policy_eligible: bool
    admitted: bool
    reasons: tuple[str, ...]
    relationship: Mapping[str, Any]


@dataclass(frozen=True)
class ReleaseEligibility:
    """Exact result of evaluating one immutable pair-release snapshot."""

    status: str
    reasons: tuple[str, ...]
    wilson_precision_lower_bound: float


def evaluate_release_eligibility(
    snapshot: AdmissionEvaluationSnapshot,
) -> ReleaseEligibility:
    """Apply every AI-SPEC release gate to one explicit pair."""

    reasons: list[str] = []
    if not is_allowed_relationship_triple(*snapshot.pair):
        reasons.append("unsupported_triple")
    if snapshot.evaluated_at - snapshot.shadow_started_at < timedelta(days=30):
        reasons.append("shadow_days")
    if snapshot.expert_adjudicated_eligible_count < 200:
        reasons.append("expert_adjudications")
    if snapshot.critical_failures:
        reasons.append("critical_failures")
    if snapshot.escalation_recall != 1.0:
        reasons.append("escalation_recall")
    if snapshot.recall < 0.90:
        reasons.append("recall")
    lower_bound = _wilson_lower_bound(
        snapshot.precision_true_positives,
        snapshot.precision_total,
    )
    if lower_bound < 0.98:
        reasons.append("precision_wilson_lower_bound")
    if not _REQUIRED_RELEASE_APPROVALS.issubset(snapshot.approvals):
        reasons.append("required_approvals")
    if not snapshot.ai_spec_gates_passed:
        reasons.append("ai_spec_gates")
    return ReleaseEligibility(
        status="BLOCKED/PENDING" if reasons else "ELIGIBLE",
        reasons=tuple(reasons),
        wilson_precision_lower_bound=lower_bound,
    )


class ProposalPolicy:
    """Fail closed before model-derived edges can enter a candidate.

    Phase 13 production construction uses the defaults: global shadow mode is
    on and pair release is unavailable.  ``allow_pair_release_testing`` exists
    solely so unit tests can exercise the later reversible transition without
    exposing a production activation configuration.
    """

    def __init__(
        self,
        *,
        shadow_mode: bool = True,
        minimum_corroborating_sources: int = 2,
        allow_pair_release_testing: bool = False,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if (
            isinstance(minimum_corroborating_sources, bool)
            or minimum_corroborating_sources < 2
        ):
            raise ValueError("minimum_corroborating_sources must be at least 2")
        self.shadow_mode = bool(shadow_mode)
        self.minimum_corroborating_sources = minimum_corroborating_sources
        self._allow_pair_release_testing = bool(allow_pair_release_testing)
        self._now = now or (lambda: datetime.now(UTC))

    def evaluate(
        self,
        proposal: Mapping[str, Any],
        *,
        entities: Mapping[str, Mapping[str, Any]],
        evidence_records: Mapping[str, Mapping[str, Any]],
        scope: str,
        source_generation_id: str,
        review_status: str = "pending",
        admission_release: Mapping[str, Any] | None = None,
        schema_version: str = "proposal-schema-v1",
        policy_version: str = "proposal-policy-v1",
    ) -> ProposalDecision:
        """Evaluate an untrusted proposal against server-owned facts."""

        candidate = copy.deepcopy(dict(proposal))
        trusted_scope = _required(scope, "scope").casefold()
        source_generation = _required(
            source_generation_id, "source_generation_id"
        )
        normalized_review = str(review_status or "pending").strip().casefold()
        reasons: list[str] = []
        triple = _triple(candidate)

        if not is_allowed_relationship_triple(*triple):
            _add_reason(reasons, "unsupported_triple")

        entity_index = {
            str(key).strip().casefold(): value for key, value in entities.items()
        }
        subject_id = str(candidate.get("subject_id") or "").strip().casefold()
        object_id = str(candidate.get("object_id") or "").strip().casefold()
        subject = entity_index.get(subject_id)
        object_row = entity_index.get(object_id)
        if subject is None or object_row is None:
            _add_reason(reasons, "unknown_endpoint")
        else:
            if (
                str(subject.get("entity_type") or "") != triple[0]
                or str(object_row.get("entity_type") or "") != triple[2]
            ):
                _add_reason(reasons, "endpoint_type_mismatch")
            if (
                _record_scope(subject) != trusted_scope
                or _record_scope(object_row) != trusted_scope
            ):
                _add_reason(reasons, "cross_scope")
            if (
                str(subject.get("lifecycle_status") or "").casefold() != "active"
                or str(object_row.get("lifecycle_status") or "").casefold()
                != "active"
            ):
                _add_reason(reasons, "inactive_endpoint")

        evidence_refs = candidate.get("evidence_refs")
        if not isinstance(evidence_refs, (list, tuple)) or not evidence_refs:
            evidence_refs = ()
            _add_reason(reasons, "unsupported_evidence")
        sources: set[str] = set()
        for reference in evidence_refs:
            evidence = evidence_records.get(str(reference))
            if evidence is None:
                _add_reason(reasons, "unsupported_evidence")
                continue
            if _record_scope(evidence) != trusted_scope:
                _add_reason(reasons, "cross_scope")
            if (
                str(evidence.get("source_generation_id") or "")
                != source_generation
            ):
                _add_reason(reasons, "stale_evidence")
            if not _evidence_is_fresh(evidence, self._now()):
                _add_reason(reasons, "stale_evidence")
            if bool(evidence.get("contradicts")):
                _add_reason(reasons, "contradictory_evidence")
            if (
                evidence.get("supports") is not True
                or _triple(evidence) != triple
                or str(evidence.get("subject_id") or "").strip().casefold()
                != subject_id
                or str(evidence.get("object_id") or "").strip().casefold()
                != object_id
            ):
                _add_reason(reasons, "unsupported_evidence")
                continue
            source = str(evidence.get("source") or "").strip().casefold()
            if source:
                sources.add(source)
        if len(sources) < self.minimum_corroborating_sources:
            _add_reason(reasons, "insufficient_corroboration")

        policy_eligible = not reasons
        admitted = False
        if policy_eligible:
            if self.shadow_mode:
                reasons.append("shadow_review_only")
            elif normalized_review != _ACCEPTED_REVIEW:
                reasons.append("awaiting_review")
            elif not self._allow_pair_release_testing:
                reasons.append("pair_release_disabled")
            elif not _release_matches(admission_release, triple):
                reasons.append("pair_not_released")
            else:
                admitted = True

        relationship = {
            "resource_id": _proposal_id(
                proposal=candidate,
                scope=trusted_scope,
                source_generation_id=source_generation,
                schema_version=schema_version,
                policy_version=policy_version,
            ),
            "subject_id": subject_id,
            "subject_type": triple[0],
            "predicate": triple[1],
            "object_id": object_id,
            "object_type": triple[2],
            "source": "model",
            "scope": trusted_scope,
            "source_generation_id": source_generation,
            "evidence_refs": sorted(str(value) for value in evidence_refs),
        }
        return ProposalDecision(
            proposal_id=relationship["resource_id"],
            review_status=normalized_review,
            policy_eligible=policy_eligible,
            admitted=admitted,
            reasons=tuple(reasons),
            relationship=relationship,
        )

    def assemble_candidate(
        self,
        *,
        deterministic_edges: Iterable[Mapping[str, Any]],
        proposal_decisions: Iterable[ProposalDecision],
    ) -> list[dict[str, Any]]:
        """Merge edges with the mandatory server-side shadow check last.

        The check deliberately sits immediately before model candidate
        assembly.  Review state, confidence, and caller flags cannot bypass it.
        """

        candidate: list[dict[str, Any]] = [
            copy.deepcopy(dict(edge)) for edge in deterministic_edges
        ]
        deterministic_keys = {_edge_key(edge) for edge in candidate}

        # Hard authority boundary: reviewed model proposals remain evidence,
        # never candidate edges, whenever global/per-scope shadow applies.
        if self.shadow_mode:
            return candidate

        for decision in proposal_decisions:
            if not decision.admitted:
                continue
            relationship = copy.deepcopy(dict(decision.relationship))
            key = _edge_key(relationship)
            if key in deterministic_keys:
                continue
            candidate.append(relationship)
            deterministic_keys.add(key)
        return candidate


def _proposal_id(**values: Any) -> str:
    return proposal_content_id(**values)


def _triple(value: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(value.get("subject_type") or ""),
        str(value.get("predicate") or ""),
        str(value.get("object_type") or ""),
    )


def _record_scope(value: Mapping[str, Any]) -> str:
    explicit = str(value.get("scope") or "").strip().casefold()
    if explicit:
        return explicit
    tenant = str(value.get("tenant_id") or "").strip().casefold()
    subscription = str(value.get("subscription_id") or "").strip().casefold()
    return f"{tenant}/{subscription}" if tenant and subscription else ""


def _evidence_is_fresh(value: Mapping[str, Any], now: datetime) -> bool:
    if str(value.get("freshness") or "").strip().casefold() not in _FRESH_STATES:
        return False
    expires_at = str(value.get("expires_at") or "").strip()
    if not expires_at:
        return True
    try:
        expiry = datetime.fromisoformat(expires_at)
    except ValueError:
        return False
    if expiry.tzinfo is None or expiry.utcoffset() is None:
        return False
    return now < expiry


def _release_matches(
    release: Mapping[str, Any] | None,
    triple: tuple[str, str, str],
) -> bool:
    if (
        release is None
        or str(release.get("status") or "").strip().casefold() != "enabled"
    ):
        return False
    return (
        str(release.get("subject_type") or ""),
        str(release.get("predicate") or ""),
        str(release.get("object_type") or ""),
    ) == triple


def _edge_key(edge: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(edge.get("subject_id") or "").strip().casefold(),
        str(edge.get("predicate") or ""),
        str(edge.get("object_id") or "").strip().casefold(),
    )


def _add_reason(reasons: list[str], reason: str) -> None:
    if reason not in reasons:
        reasons.append(reason)


def _required(value: object, name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    return normalized


def _wilson_lower_bound(successes: int, total: int) -> float:
    if total <= 0:
        return 0.0
    proportion = successes / total
    z = 1.959963984540054
    denominator = 1 + (z * z / total)
    centre = proportion + (z * z / (2 * total))
    margin = z * math.sqrt(
        (proportion * (1 - proportion) / total)
        + (z * z / (4 * total * total))
    )
    return (centre - margin) / denominator


__all__ = [
    "ProposalDecision",
    "ProposalPolicy",
    "ReleaseEligibility",
    "evaluate_release_eligibility",
]
