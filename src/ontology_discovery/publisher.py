"""Fenced, deterministic publication of immutable ontology generations."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from ontology.ontology_validator import (
    OntologyPublicationValidationReport,
    OntologyValidator,
)
from storage.datasets import (
    AuthoritativeDatasetPublisher,
    GenerationPointerConditions,
    GenerationPointerSnapshot,
)
from storage.onelake_documents import DocumentConflictError

APPROVED_PUBLICATION_CHECKPOINTS = frozenset(
    {"approve-pointer-cutover", "approve-publisher-rbac"}
)
CONSUMER_FAMILIES = ("api", "fabric", "agent", "export", "semantic")


class PublicationSafetyError(RuntimeError):
    """Fail-closed refusal to make a candidate reader-visible."""


class PostCheckRollbackError(PublicationSafetyError):
    """Post-CAS verification failed and rollback was attempted."""

    def __init__(self, *, rollback_succeeded: bool) -> None:
        self.rollback_succeeded = rollback_succeeded
        reason = (
            "post_check_failed_rolled_back"
            if rollback_succeeded
            else "critical_rollback_failed"
        )
        super().__init__(reason)


@dataclass(frozen=True)
class OntologyGenerationCandidate:
    """Complete deterministic candidate and its immutable lineage."""

    generation_id: str
    source_generation: str
    entities: tuple[dict[str, Any], ...]
    relationships: tuple[dict[str, Any], ...]
    proposal_lineage: tuple[str, ...]
    decision_lineage: tuple[str, ...]
    policy_version: str
    schema_version: str


class OntologyGenerationPublisher:
    """Stage, audit, promote, and roll back through one fenced pointer."""

    def __init__(
        self,
        storage: AuthoritativeDatasetPublisher,
        *,
        validator: OntologyValidator,
        approved_publisher_identity: str,
    ) -> None:
        self._storage = storage
        self._validator = validator
        self._approved_publisher_identity = str(
            approved_publisher_identity
        ).strip()
        if (
            not self._approved_publisher_identity
            or storage.publisher_identity != self._approved_publisher_identity
        ):
            raise PermissionError("publisher adapter identity is not approved")

    def publish(
        self,
        candidate: OntologyGenerationCandidate,
        *,
        publisher_identity: str,
        checkpoint_ids: Iterable[str],
        pointer_conditions: GenerationPointerConditions,
        owner_id: str,
        fence: int,
        consumer_compatibility: Mapping[str, bool],
        cancellation_check: Callable[[], bool],
        lease_guard: Callable[[], None],
        materialize_generation: Callable[
            [OntologyGenerationCandidate], Mapping[str, Any]
        ]
        | None = None,
        staged_consumer_check: Callable[
            [str], Mapping[str, bool]
        ]
        | None = None,
        post_consumer_check: Callable[
            [str], Mapping[str, bool]
        ]
        | None = None,
        step_recorder: Callable[[str, Mapping[str, Any]], None] | None = None,
        pre_cas_hook: Callable[[], None] | None = None,
        rollback_fence_allocator: Callable[[], int] | None = None,
    ) -> GenerationPointerSnapshot:
        self._authorize(publisher_identity, checkpoint_ids)
        self._guard_runtime(cancellation_check, lease_guard)
        self._assert_pointer(pointer_conditions)
        validation = self._validate(candidate, consumer_compatibility)
        if validation.model_derived_relationships:
            raise PublicationSafetyError(
                "model-derived relationships are forbidden in Phase 13 shadow publication"
            )
        if (
            not validation.consumers_complete
            or not validation.consumers_compatible
        ):
            raise PublicationSafetyError(
                "complete consumer compatibility evidence is required"
            )
        if not validation.passed:
            raise PublicationSafetyError("complete generation validation failed")

        staged = self._stage_payload(
            candidate,
            validation=validation,
            owner_id=owner_id,
            fence=fence,
            consumer_compatibility=consumer_compatibility,
        )
        try:
            self._storage.stage_generation(
                candidate.generation_id,
                manifest=staged["manifest"],
                entities=staged["entities"],
                relationships=staged["relationships"],
                lineage=staged["lineage"],
                validation=staged["validation"],
                compatibility=staged["compatibility"],
            )
        except DocumentConflictError:
            # Crash recovery may revisit an already-complete immutable stage,
            # but only byte-for-byte identical content is admissible.
            try:
                self._verify_staged(
                    candidate.generation_id, staged, require_audit=False
                )
            except PublicationSafetyError as mismatch:
                raise PublicationSafetyError(
                    f"generation {candidate.generation_id} is immutable"
                ) from mismatch
        _record(step_recorder, "immutable_stage", {
            "generation_id": candidate.generation_id,
            "content_hash": staged["manifest"]["content_hash"],
            "owner_id": owner_id,
            "fence": fence,
        })
        self._verify_staged(candidate.generation_id, staged, require_audit=False)
        persisted_validation = self._validate_staged(candidate.generation_id)
        if not persisted_validation.passed:
            raise PublicationSafetyError("persisted generation validation failed")
        _record(step_recorder, "persisted_validation", {
            "generation_id": candidate.generation_id,
            "passed": True,
        })
        staged_checks = _consumer_results(
            staged_consumer_check(candidate.generation_id)
            if staged_consumer_check is not None
            else consumer_compatibility
        )
        _record(step_recorder, "staged_compatibility", {
            "generation_id": candidate.generation_id,
            "families": staged_checks,
        })
        if not all(staged_checks.values()):
            raise PublicationSafetyError("staged consumer compatibility failed")
        materialization = (
            dict(materialize_generation(candidate))
            if materialize_generation is not None
            else {"status": "not_required"}
        )
        if materialization.get("status") not in {"completed", "not_required"}:
            raise PublicationSafetyError("Fabric materialization failed")
        _record(step_recorder, "fabric_materialization", {
            "generation_id": candidate.generation_id,
            "status": materialization["status"],
        })

        audit_intent = {
            "event": "ontology_generation_promotion",
            "outcome": "promotion_authorized",
            "generation_id": candidate.generation_id,
            "source_generation": candidate.source_generation,
            "publisher_identity": self._approved_publisher_identity,
            "owner_id": owner_id,
            "fence": fence,
            "checkpoint_ids": sorted(APPROVED_PUBLICATION_CHECKPOINTS),
            "content_hash": staged["manifest"]["content_hash"],
        }
        try:
            self._storage.persist_generation_audit(
                candidate.generation_id,
                audit_intent,
            )
        except Exception as exc:
            raise PublicationSafetyError(
                "publication audit could not be persisted"
            ) from exc

        # Recheck every mutable safety fact after staging/audit and immediately
        # before the one consequential storage CAS.
        self._guard_runtime(cancellation_check, lease_guard)
        self._assert_pointer(pointer_conditions)
        second_validation = self._validate(candidate, consumer_compatibility)
        if not second_validation.passed:
            raise PublicationSafetyError(
                "complete validation changed before promotion"
            )
        self._verify_staged(candidate.generation_id, staged)
        if pre_cas_hook is not None:
            pre_cas_hook()
        _record(step_recorder, "final_preconditions", {
            "generation_id": candidate.generation_id,
            "expected_etag": pointer_conditions.etag or "",
            "fence": fence,
        })
        try:
            promoted = self._storage.conditional_promote(
                generation_id=candidate.generation_id,
                source_generation=candidate.source_generation,
                owner_id=owner_id,
                fence=fence,
                conditions=pointer_conditions,
            )
        except DocumentConflictError as exc:
            raise PublicationSafetyError(
                "stale writer lost the active pointer CAS"
            ) from exc
        _record(step_recorder, "pointer_cas", {
            "generation_id": candidate.generation_id,
            "pointer_etag": promoted.etag or "",
            "fence": fence,
        })
        post_checks = _consumer_results(
            post_consumer_check(candidate.generation_id)
            if post_consumer_check is not None
            else consumer_compatibility
        )
        _record(step_recorder, "post_check", {
            "generation_id": candidate.generation_id,
            "families": post_checks,
        })
        if not all(post_checks.values()):
            self._automatic_rollback(
                promoted=promoted,
                predecessor=pointer_conditions.active_generation,
                publisher_identity=publisher_identity,
                owner_id=owner_id,
                rollback_fence_allocator=rollback_fence_allocator,
                post_consumer_check=post_consumer_check,
                step_recorder=step_recorder,
                failed_checks=post_checks,
                cancellation_check=cancellation_check,
                lease_guard=lease_guard,
            )
        self._storage.persist_generation_receipt(
            candidate.generation_id,
            {
                **audit_intent,
                "outcome": "promoted",
                "pointer_etag": promoted.etag,
            },
        )
        return promoted

    def _automatic_rollback(
        self,
        *,
        promoted: GenerationPointerSnapshot,
        predecessor: str | None,
        publisher_identity: str,
        owner_id: str,
        rollback_fence_allocator: Callable[[], int] | None,
        post_consumer_check: Callable[[str], Mapping[str, bool]] | None,
        step_recorder: Callable[[str, Mapping[str, Any]], None] | None,
        failed_checks: Mapping[str, bool],
        cancellation_check: Callable[[], bool],
        lease_guard: Callable[[], None],
    ) -> None:
        if predecessor is None or rollback_fence_allocator is None:
            _record(
                step_recorder,
                "automatic_rollback",
                {
                    "status": "critical_rollback_failed",
                    "failed_consumer_hash": _content_hash(failed_checks),
                },
            )
            raise PostCheckRollbackError(rollback_succeeded=False)
        try:
            target = self._storage.read_generation(predecessor)
            rollback_fence = int(rollback_fence_allocator())
            restored = self.rollback(
                target_generation_id=predecessor,
                source_generation=str(target["manifest"]["source_generation"]),
                publisher_identity=publisher_identity,
                checkpoint_ids=APPROVED_PUBLICATION_CHECKPOINTS,
                pointer_conditions=GenerationPointerConditions.from_snapshot(
                    promoted
                ),
                owner_id=owner_id,
                fence=rollback_fence,
                cancellation_check=cancellation_check,
                lease_guard=lease_guard,
            )
            restored_checks = _consumer_results(
                post_consumer_check(predecessor)
                if post_consumer_check is not None
                else {family: True for family in CONSUMER_FAMILIES}
            )
            if not all(restored_checks.values()):
                raise PublicationSafetyError(
                    "restored generation consumer verification failed"
                )
            _record(
                step_recorder,
                "automatic_rollback",
                {
                    "status": "post_check_failed_rolled_back",
                    "failed_generation": promoted.pointer.active_generation
                    if promoted.pointer
                    else "",
                    "restored_generation": predecessor,
                    "original_fence": promoted.pointer.fence
                    if promoted.pointer
                    else 0,
                    "rollback_fence": rollback_fence,
                    "pointer_etag": restored.etag or "",
                    "failed_consumer_hash": _content_hash(failed_checks),
                    "restored_consumer_hash": _content_hash(restored_checks),
                },
            )
        except PostCheckRollbackError:
            raise
        except (OSError, RuntimeError, TypeError, ValueError):
            _record(
                step_recorder,
                "automatic_rollback",
                {
                    "status": "critical_rollback_failed",
                    "failed_generation": promoted.pointer.active_generation
                    if promoted.pointer
                    else "",
                    "restored_generation": predecessor,
                    "failed_consumer_hash": _content_hash(failed_checks),
                },
            )
            raise PostCheckRollbackError(rollback_succeeded=False) from None
        raise PostCheckRollbackError(rollback_succeeded=True)

    def rollback(
        self,
        *,
        target_generation_id: str,
        source_generation: str,
        publisher_identity: str,
        checkpoint_ids: Iterable[str],
        pointer_conditions: GenerationPointerConditions,
        owner_id: str,
        fence: int,
        cancellation_check: Callable[[], bool],
        lease_guard: Callable[[], None],
    ) -> GenerationPointerSnapshot:
        self._authorize(publisher_identity, checkpoint_ids)
        self._guard_runtime(cancellation_check, lease_guard)
        self._assert_pointer(pointer_conditions)
        try:
            target = self._storage.read_generation(target_generation_id)
        except (FileNotFoundError, TypeError, ValueError) as exc:
            raise PublicationSafetyError(
                "rollback target is not a complete immutable generation"
            ) from exc
        manifest = target["manifest"]
        if (
            manifest.get("complete") is not True
            or manifest.get("source_generation") != source_generation
            or target["validation"].get("passed") is not True
            or target["compatibility"].get("all_consumers_compatible") is not True
            or not target.get("audit")
        ):
            raise PublicationSafetyError(
                "rollback target failed validation, audit, or compatibility checks"
            )
        audit = {
            "event": "ontology_generation_rollback",
            "outcome": "rollback_authorized",
            "target_generation_id": target_generation_id,
            "source_generation": source_generation,
            "publisher_identity": self._approved_publisher_identity,
            "owner_id": owner_id,
            "fence": fence,
            "checkpoint_ids": sorted(APPROVED_PUBLICATION_CHECKPOINTS),
        }
        try:
            self._storage.persist_rollback_audit(
                target_generation_id=target_generation_id,
                owner_id=owner_id,
                fence=fence,
                audit=audit,
            )
        except Exception as exc:
            raise PublicationSafetyError("rollback audit could not be persisted") from exc
        self._guard_runtime(cancellation_check, lease_guard)
        self._assert_pointer(pointer_conditions)
        try:
            return self._storage.conditional_promote(
                generation_id=target_generation_id,
                source_generation=source_generation,
                owner_id=owner_id,
                fence=fence,
                conditions=pointer_conditions,
            )
        except DocumentConflictError as exc:
            raise PublicationSafetyError(
                "stale writer lost the rollback pointer CAS"
            ) from exc

    def _authorize(
        self,
        publisher_identity: str,
        checkpoint_ids: Iterable[str],
    ) -> None:
        if str(publisher_identity).strip() != self._approved_publisher_identity:
            raise PublicationSafetyError("publisher identity is not approved")
        supplied = frozenset(str(value).strip() for value in checkpoint_ids)
        if not APPROVED_PUBLICATION_CHECKPOINTS.issubset(supplied):
            raise PublicationSafetyError(
                "approved pointer and publisher checkpoints are required"
            )

    @staticmethod
    def _guard_runtime(
        cancellation_check: Callable[[], bool],
        lease_guard: Callable[[], None],
    ) -> None:
        if cancellation_check():
            raise PublicationSafetyError("publication was cancelled")
        try:
            lease_guard()
        except Exception as exc:
            raise PublicationSafetyError("publisher lease was lost") from exc

    def _assert_pointer(
        self,
        conditions: GenerationPointerConditions,
    ) -> None:
        try:
            self._storage.assert_pointer_conditions(conditions)
        except DocumentConflictError as exc:
            raise PublicationSafetyError(
                "stale writer no longer matches the active pointer"
            ) from exc

    def _validate(
        self,
        candidate: OntologyGenerationCandidate,
        consumer_compatibility: Mapping[str, bool],
    ) -> OntologyPublicationValidationReport:
        return self._validator.validate_publication(
            entities=candidate.entities,
            relationships=candidate.relationships,
            source_generation=candidate.source_generation,
            proposal_lineage=candidate.proposal_lineage,
            decision_lineage=candidate.decision_lineage,
            consumer_compatibility=consumer_compatibility,
        )

    @staticmethod
    def _stage_payload(
        candidate: OntologyGenerationCandidate,
        *,
        validation: OntologyPublicationValidationReport,
        owner_id: str,
        fence: int,
        consumer_compatibility: Mapping[str, bool],
    ) -> dict[str, Any]:
        entities = [dict(row) for row in candidate.entities]
        relationships = [dict(row) for row in candidate.relationships]
        entity_hash = _content_hash(entities)
        relationship_hash = _content_hash(relationships)
        lineage = {
            "proposal_ids": list(candidate.proposal_lineage),
            "decision_ids": list(candidate.decision_lineage),
        }
        compatibility = {
            "families": dict(sorted(consumer_compatibility.items())),
            "all_consumers_compatible": all(consumer_compatibility.values()),
            "alias_version": "ontology-generation-alias/v1",
        }
        identity = {
            "generation_id": candidate.generation_id,
            "source_generation": candidate.source_generation,
            "entity_hash": entity_hash,
            "relationship_hash": relationship_hash,
            "lineage": lineage,
            "validation": validation.to_dict(),
            "compatibility": compatibility,
            "owner_id": owner_id,
            "fence": fence,
            "policy_version": candidate.policy_version,
            "schema_version": candidate.schema_version,
        }
        manifest = {
            **identity,
            "content_hash": _content_hash(identity),
            "complete": True,
        }
        return {
            "manifest": manifest,
            "entities": entities,
            "relationships": relationships,
            "lineage": lineage,
            "validation": validation.to_dict(),
            "compatibility": compatibility,
        }

    def _validate_staged(
        self,
        generation_id: str,
    ) -> OntologyPublicationValidationReport:
        staged = self._storage.read_generation(generation_id)
        return self._validator.validate_publication(
            entities=staged["entities"],
            relationships=staged["relationships"],
            source_generation=str(staged["manifest"]["source_generation"]),
            proposal_lineage=tuple(staged["lineage"]["proposal_ids"]),
            decision_lineage=tuple(staged["lineage"]["decision_ids"]),
            consumer_compatibility=staged["compatibility"]["families"],
        )

    def _verify_staged(
        self,
        generation_id: str,
        expected: Mapping[str, Any],
        *,
        require_audit: bool = True,
    ) -> None:
        try:
            staged = self._storage.read_generation(generation_id)
        except (FileNotFoundError, TypeError, ValueError) as exc:
            raise PublicationSafetyError("staged generation is partial") from exc
        for key in (
            "manifest",
            "entities",
            "relationships",
            "lineage",
            "validation",
            "compatibility",
        ):
            if staged.get(key) != expected[key]:
                raise PublicationSafetyError(
                    f"staged generation {key} changed before promotion"
                )
        if require_audit and not staged.get("audit"):
            raise PublicationSafetyError(
                "staged generation is unaudited and cannot be promoted"
            )


def _content_hash(value: object) -> str:
    body = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return hashlib.sha256(body).hexdigest()


def _consumer_results(values: Mapping[str, bool]) -> dict[str, bool]:
    if set(values) != set(CONSUMER_FAMILIES):
        raise PublicationSafetyError(
            "complete API/Fabric/agent/export/semantic compatibility is required"
        )
    return {family: values[family] is True for family in CONSUMER_FAMILIES}


def _record(
    recorder: Callable[[str, Mapping[str, Any]], None] | None,
    step: str,
    receipt: Mapping[str, Any],
) -> None:
    if recorder is not None:
        recorder(step, receipt)


__all__ = [
    "APPROVED_PUBLICATION_CHECKPOINTS",
    "CONSUMER_FAMILIES",
    "OntologyGenerationCandidate",
    "OntologyGenerationPublisher",
    "PostCheckRollbackError",
    "PublicationSafetyError",
]
