"""Fenced, deterministic publication of immutable ontology generations."""

from __future__ import annotations

import contextlib
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
        maintenance_authorizer: Any | None = None,
    ) -> GenerationPointerSnapshot:
        self._authorize(publisher_identity, checkpoint_ids)
        self._guard_runtime(cancellation_check, lease_guard)
        self._assert_pointer(pointer_conditions)
        authorization: dict[str, Any] = {}

        def reauthorize(stage: str) -> None:
            # Fresh release/attestation/kill/base read for every consequential
            # step; nothing is trusted from the coordinator or an earlier read.
            nonlocal authorization
            if maintenance_authorizer is None:
                return
            try:
                authorization = dict(maintenance_authorizer.authorize(candidate))
            except PublicationSafetyError:
                raise
            except Exception as exc:
                reason = getattr(exc, "reason", "maintenance_authorization_failed")
                raise PublicationSafetyError(
                    f"maintenance authorization denied at {stage}: {reason}"
                ) from exc

        has_model_rows = any(
            str(row.get("source") or "").strip().casefold() in {"model", "ai", "llm"}
            or row.get("model_derived") is True
            for row in candidate.relationships
        )
        if has_model_rows and maintenance_authorizer is None:
            raise PublicationSafetyError(
                "model-derived relationships are forbidden in Phase 13 shadow publication"
            )
        reauthorize("pre_stage")
        validation = self._validate(
            candidate, consumer_compatibility, maintenance_authorizer
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
            authorization_digest=str(authorization.get("authorization_digest") or ""),
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
        persisted_validation = self._validate_staged(
            candidate.generation_id, maintenance_authorizer
        )
        if not persisted_validation.passed:
            raise PublicationSafetyError("persisted generation validation failed")
        _record(step_recorder, "persisted_validation", {
            "generation_id": candidate.generation_id,
            "passed": True,
        })
        if maintenance_authorizer is not None and has_model_rows:
            reauthorize("post_stage")
            # Separate create-only immutable stage-authorization audit, written
            # through the publisher-authority storage API after validation and
            # before any materializer or later step.  A duplicate/conflicting
            # record denies; nothing is overwritten.
            stage_audit = {
                "event": "maintenance_stage_authorization",
                "generation_id": candidate.generation_id,
                "source_generation": candidate.source_generation,
                "content_hash": staged["manifest"]["content_hash"],
                "authorization_digest": authorization["authorization_digest"],
                "attestation_digest": str(authorization.get("attestation_digest") or ""),
                "release_id": str(authorization.get("release_id") or ""),
                "model_rows": int(authorization.get("model_rows") or 0),
                "publisher_identity": self._approved_publisher_identity,
                "owner_id": owner_id,
                "fence": fence,
            }
            try:
                try:
                    self._storage.persist_stage_authorization(
                        target_generation_id=candidate.generation_id,
                        owner_id=owner_id,
                        fence=fence,
                        audit=stage_audit,
                    )
                except DocumentConflictError:
                    # Crash recovery reuses the recorded fence; the existing
                    # immutable record must be byte-for-byte the same decision.
                    existing = self._storage.read_stage_authorization(
                        target_generation_id=candidate.generation_id,
                        owner_id=owner_id,
                        fence=fence,
                    )
                    if existing != stage_audit:
                        raise
            except Exception as exc:
                raise PublicationSafetyError(
                    "maintenance stage authorization audit could not be persisted"
                ) from exc
            _record(step_recorder, "maintenance_stage_authorization", {
                "generation_id": candidate.generation_id,
                "authorization_digest": authorization["authorization_digest"],
                "attestation_digest": str(authorization.get("attestation_digest") or ""),
                "model_rows": int(authorization.get("model_rows") or 0),
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
        if has_model_rows and not getattr(
            materialize_generation, "maintenance_candidate_bound", False
        ):
            # Plan 06 supplies the candidate-bound product materializer; the
            # existing service.sync callback and pointer-only rollback never
            # qualify maintenance publication.
            raise PublicationSafetyError("materializer_unqualified")
        materializer = (
            materialize_generation
            if getattr(materialize_generation, "maintenance_candidate_bound", False)
            and callable(getattr(materialize_generation, "bind", None))
            else None
        )
        if materializer is not None:
            materializer.bind(
                owner_id=owner_id,
                fence=fence,
                predecessor=pointer_conditions.active_generation,
                pointer_etag=pointer_conditions.etag,
                runtime_guard=lambda: self._guard_runtime(cancellation_check, lease_guard),
            )
        try:
            reauthorize("pre_materialization")
            materialization = (
                dict(materialize_generation(candidate))
                if materialize_generation is not None
                else {"status": "not_required"}
            )
            if materialization.get("status") not in {"completed", "not_required"}:
                raise PublicationSafetyError("Fabric materialization failed")
            reauthorize("post_materialization")
            _record(step_recorder, "fabric_materialization", {
                "generation_id": candidate.generation_id,
                "status": materialization["status"],
                **(
                    {
                        "receipt_digest": str(materialization.get("receipt_digest") or ""),
                        "content_hash": str(materialization.get("content_hash") or ""),
                        "attestation_digest": str(
                            materialization.get("attestation_digest") or ""
                        ),
                    }
                    if materializer is not None
                    else {}
                ),
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
            except DocumentConflictError as exc:
                if self._storage.read_generation(candidate.generation_id)["audit"] != audit_intent:
                    raise PublicationSafetyError(
                        "publication audit conflicts with persisted authorization"
                    ) from exc
            except Exception as exc:
                raise PublicationSafetyError(
                    "publication audit could not be persisted"
                ) from exc

            # Recheck every mutable safety fact after staging/audit and immediately
            # before the one consequential storage CAS.
            self._guard_runtime(cancellation_check, lease_guard)
            self._assert_pointer(pointer_conditions)
            reauthorize("pre_cas")
            second_validation = self._validate(
                candidate, consumer_compatibility, maintenance_authorizer
            )
            if not second_validation.passed:
                raise PublicationSafetyError(
                    "complete validation changed before promotion"
                )
            self._verify_staged(candidate.generation_id, staged)
            if materializer is not None:
                # Candidate, stage, authorization and observed product hashes and
                # versions must agree, under live target ownership, before the CAS.
                materializer.verify_before_cas(candidate)
                materializer.assert_owned()
            if pre_cas_hook is not None:
                pre_cas_hook()
            _record(step_recorder, "final_preconditions", {
                "generation_id": candidate.generation_id,
                "expected_etag": pointer_conditions.etag or "",
                "fence": fence,
            })
            self._guard_runtime(cancellation_check, lease_guard)
            self._assert_pointer(pointer_conditions)
            if materializer is not None:
                materializer.verify_before_cas(candidate)
                materializer.assert_owned()
            reauthorize("final_cas")
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
            if materializer is not None:
                materializer.record_pointer_committed(promoted.etag or "")
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
                    materializer=materializer,
                    candidate_generation=candidate.generation_id,
                )
            self._storage.persist_generation_receipt(
                candidate.generation_id,
                {
                    **audit_intent,
                    "outcome": "promoted",
                    "pointer_etag": promoted.etag,
                },
            )
            if materializer is not None:
                materializer.complete()
        except PostCheckRollbackError:
            raise
        except Exception as failure:
            if materializer is not None:
                self._recover_maintenance(
                    materializer,
                    candidate.generation_id,
                    failure,
                    post_consumer_check,
                )
            raise
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
        materializer: Any | None = None,
        candidate_generation: str = "",
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
            if materializer is not None:
                # Physical products first (new fence-protected ownership); the
                # pointer is restored only afterwards and never implies it.
                materializer.recover_physical(
                    reason="post_check_failed",
                    target=predecessor,
                    expected_active=candidate_generation,
                )
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
                # Only a fresh authenticated restore guard can replace the
                # admission runtime guard; no successful boolean is authority.
                restore_guard=(
                    materializer.assert_restore_authorized if materializer is not None else None
                ),
            )
            if materializer is not None:
                materializer.record_restore_pointer()
            restored_checks = _consumer_results(
                post_consumer_check(predecessor)
                if post_consumer_check is not None
                else {family: True for family in CONSUMER_FAMILIES}
            )
            if materializer is not None:
                materializer.mark_recovery(
                    pointer=True, consumer=all(restored_checks.values())
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
            if materializer is not None:
                # Never leave products at a rejected/stale generation:
                # converge to whatever the pointer now authorizes.  A failure
                # is already a durable critical journal entry.
                with contextlib.suppress(Exception):
                    materializer.recover_physical(reason="rollback_failed")
                materializer.quarantine("rollback_pointer_or_consumer_uncertain")
                materializer.release()
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
        if materializer is not None:
            materializer.release()
        raise PostCheckRollbackError(rollback_succeeded=True)

    def resume_recovery(
        self, *, materializer: Any, publisher_identity: str, owner_id: str,
        rollback_fence_allocator: Callable[[], int],
        post_consumer_check: Callable[[str], Mapping[str, bool]],
    ) -> None:
        """Resume the durable restore decision, never re-admit its rejected candidate."""
        journal = materializer.journal.read() or {}
        intent = journal["recovery_intent"]
        target = str(intent["target_generation"])
        candidate = str((journal.get("operation") or {})["generation_id"])
        current = self._storage.read_pointer()
        active = current.pointer.active_generation if current.pointer else None
        if active == candidate:
            self._automatic_rollback(
                promoted=current, predecessor=target,
                publisher_identity=publisher_identity, owner_id=owner_id,
                rollback_fence_allocator=rollback_fence_allocator,
                post_consumer_check=post_consumer_check, step_recorder=None,
                failed_checks=dict.fromkeys(CONSUMER_FAMILIES, False),
                cancellation_check=lambda: False, lease_guard=materializer.assert_owned,
                materializer=materializer, candidate_generation=candidate,
            )
        try:
            materializer.recover_physical(reason="resume_restore", target=target, expected_active=target)
            if active != target:
                materializer.quarantine("restore_superseded_by_newer_winner")
                raise PostCheckRollbackError(rollback_succeeded=False)
            checks = _consumer_results(post_consumer_check(target))
            materializer.mark_recovery(pointer=True, consumer=all(checks.values()))
            raise PostCheckRollbackError(rollback_succeeded=all(checks.values()))
        finally:
            materializer.release()

    def _recover_maintenance(
        self,
        materializer: Any,
        generation_id: str,
        failure: BaseException,
        post_consumer_check: Callable[[str], Mapping[str, bool]] | None,
    ) -> None:
        """Rematerialize authoritative products after any pre/post-CAS failure."""
        try:
            outcome = materializer.recover_after_failure(
                f"publish_failed:{type(failure).__name__}",
                candidate_generation=generation_id,
            )
            target = outcome.get("target_generation")
            if target is not None and post_consumer_check is not None:
                checks = _consumer_results(post_consumer_check(target))
                materializer.mark_recovery(
                    pointer=True, consumer=all(checks.values())
                )
                if not all(checks.values()):
                    raise PublicationSafetyError(
                        "restored products failed consumer verification"
                    )
        finally:
            materializer.release()

    def resume_committed(
        self,
        *,
        generation_id: str,
        source_generation: str,
        content_hash: str,
        materializer: Any,
        post_consumer_check: Callable[[str], Mapping[str, bool]],
        publisher_identity: str,
        owner_id: str,
        rollback_fence_allocator: Callable[[], int] | None,
        cancellation_check: Callable[[], bool],
        lease_guard: Callable[[], None],
        step_recorder: Callable[[str, Mapping[str, Any]], None] | None = None,
    ) -> GenerationPointerSnapshot:
        """Finish a publication whose pointer CAS survived a process death."""
        promoted = self._storage.read_pointer()
        if (
            promoted.pointer is None
            or promoted.pointer.active_generation != generation_id
        ):
            raise PublicationSafetyError("generation is not the committed active generation")
        checks = _consumer_results(post_consumer_check(generation_id))
        _record(step_recorder, "post_check", {
            "generation_id": generation_id,
            "families": checks,
        })
        if not all(checks.values()):
            self._automatic_rollback(
                promoted=promoted,
                predecessor=promoted.pointer.prior_generation,
                publisher_identity=publisher_identity,
                owner_id=owner_id,
                rollback_fence_allocator=rollback_fence_allocator,
                post_consumer_check=post_consumer_check,
                step_recorder=step_recorder,
                failed_checks=checks,
                cancellation_check=cancellation_check,
                lease_guard=lease_guard,
                materializer=materializer,
                candidate_generation=generation_id,
            )
        try:
            self._storage.persist_generation_receipt(
                generation_id,
                {
                    "event": "ontology_generation_promotion",
                    "outcome": "promoted",
                    "generation_id": generation_id,
                    "source_generation": source_generation,
                    "publisher_identity": self._approved_publisher_identity,
                    "owner_id": owner_id,
                    "content_hash": content_hash,
                    "pointer_etag": promoted.etag,
                    "resumed": True,
                },
            )
        except DocumentConflictError:
            pass  # receipt already durable before the interruption
        materializer.complete()
        return promoted

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
        restore_guard: Callable[[], None] | None = None,
    ) -> GenerationPointerSnapshot:
        self._authorize(publisher_identity, checkpoint_ids)
        if restore_guard is not None:
            restore_guard()
        else:
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
        if restore_guard is not None:
            restore_guard()
        else:
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
        maintenance_authorizer: Any | None = None,
    ) -> OntologyPublicationValidationReport:
        return self._validator.validate_publication(
            entities=candidate.entities,
            relationships=candidate.relationships,
            source_generation=candidate.source_generation,
            proposal_lineage=candidate.proposal_lineage,
            decision_lineage=candidate.decision_lineage,
            consumer_compatibility=consumer_compatibility,
            model_authorizer=(
                None
                if maintenance_authorizer is None
                else lambda _rows: bool(maintenance_authorizer.authorize(candidate))
            ),
        )

    @staticmethod
    def _stage_payload(
        candidate: OntologyGenerationCandidate,
        *,
        validation: OntologyPublicationValidationReport,
        owner_id: str,
        fence: int,
        consumer_compatibility: Mapping[str, bool],
        authorization_digest: str = "",
    ) -> dict[str, Any]:
        entities = [dict(row) for row in candidate.entities]
        relationships = [dict(row) for row in candidate.relationships]
        entity_hash = _content_hash(entities)
        relationship_hash = _content_hash(relationships)
        lineage = {
            "proposal_ids": list(candidate.proposal_lineage),
            "decision_ids": list(candidate.decision_lineage),
            **(
                {"maintenance_authorization_digest": authorization_digest}
                if authorization_digest
                else {}
            ),
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
        maintenance_authorizer: Any | None = None,
    ) -> OntologyPublicationValidationReport:
        staged = self._storage.read_generation(generation_id)

        def authorize_staged(_rows: list[dict[str, Any]]) -> bool:
            persisted = type(
                "_StagedCandidate",
                (),
                {
                    "relationships": tuple(staged["relationships"]),
                    "entities": tuple(staged["entities"]),
                    "proposal_lineage": tuple(staged["lineage"]["proposal_ids"]),
                    "source_generation": str(staged["manifest"]["source_generation"]),
                },
            )()
            return bool(maintenance_authorizer.authorize(persisted))

        return self._validator.validate_publication(
            entities=staged["entities"],
            relationships=staged["relationships"],
            source_generation=str(staged["manifest"]["source_generation"]),
            proposal_lineage=tuple(staged["lineage"]["proposal_ids"]),
            decision_lineage=tuple(staged["lineage"]["decision_ids"]),
            consumer_compatibility=staged["compatibility"]["families"],
            model_authorizer=(
                None if maintenance_authorizer is None else authorize_staged
            ),
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
