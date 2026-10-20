"""Separately selected Phase 14 admission and independent publisher authorizer.

Phase 13 stays shadow: this path never uses ``allow_pair_release_testing`` and
never changes ``ProposalPolicy`` defaults.  Eligibility reuses the strict
deterministic evidence policy; admission additionally needs a fresh, verified
maintenance release, an accepted review and an exact lineage/scope match.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from fabric.dataset_mapper import allowed_relationship_triples
from ontology_discovery.maintenance_relationships import (
    materialize_relationship,
    stable_relationship_id,
)
from ontology_discovery.maintenance_release import (
    MaintenanceDenied,
    MaintenanceRelease,
    MaintenanceReleaseReader,
    canonical_json,
    digest,
)
from ontology_discovery.policy import ProposalDecision, ProposalPolicy


def _proposal_membership_key(proposal: Mapping[str, Any]) -> bytes:
    # Preserve the prior parsed-dict equality for JSON integer/float confidence
    # (1 == 1.0), without scanning every proposal on every row authorization.
    value = dict(proposal)
    confidence = value.get("confidence")
    if type(confidence) in (int, float):
        value["confidence"] = 0.0 if confidence == 0 else float(confidence)
    return canonical_json(value)


@lru_cache(maxsize=32)
def _validated_receipt_body(
    batch_bytes: bytes, body_bytes: bytes
) -> frozenset[bytes] | None:
    """Pure bounded decoding cache, keyed by the complete current bytes.

    This is NOT a receipt approval: membership, response hash, lineage, source
    support and clock checks still run at every authorization. Bytes come from
    the fresh durable-store read, so same-mtime mutations cannot hit this cache.
    The returned proposal index cannot be changed by a caller.
    """
    from ontology_discovery.contracts import EvidenceBatch
    from ontology_discovery.curator import CuratorInvalidOutput, parse_proposal_batch

    try:
        parsed = parse_proposal_batch(
            body_bytes.decode(), batch=EvidenceBatch.from_dict(json.loads(batch_bytes))
        ).model_dump(mode="json")
        return (
            frozenset(_proposal_membership_key(p) for p in parsed.get("proposals", ()))
            if parsed == json.loads(body_bytes) else None
        )
    except (CuratorInvalidOutput, KeyError, TypeError, ValueError):
        return None


def vocabulary_fingerprint() -> str:
    """Server-derived fingerprint of the authoritative relationship vocabulary."""

    return digest(sorted(list(t) for t in allowed_relationship_triples()))


@dataclass(frozen=True)
class MaintenanceDecision:
    proposal_id: str
    admitted: bool
    reasons: tuple[str, ...]
    decision: ProposalDecision
    release: MaintenanceRelease | None


class MaintenanceAdmission:
    def __init__(
        self,
        *,
        reader: MaintenanceReleaseReader,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.reader = reader
        self._now = now or (lambda: datetime.now(UTC))
        # Eligibility only; the shadow flag here is never an authority switch.
        self._policy = ProposalPolicy(shadow_mode=True, now=self._now)

    def check_open(self, operation: str = "admit") -> str:
        return self.reader.check(operation)

    def evaluate(
        self,
        record: Mapping[str, Any],
        *,
        entities: Mapping[str, Mapping[str, Any]],
        evidence_records: Mapping[str, Mapping[str, Any]],
        scope: str,
        source_generation_id: str,
        review_status: str,
        observed_lineage: Mapping[str, str],
        connection: Any,
    ) -> MaintenanceDecision:
        proposal = record["proposal"]
        decision = self._policy.evaluate(
            proposal,
            entities=entities,
            evidence_records=evidence_records,
            scope=scope,
            source_generation_id=source_generation_id,
            review_status=review_status,
            schema_version=str(record.get("schema_version") or "proposal-schema-v1"),
            policy_version=str(record.get("policy_version") or "proposal-policy-v1"),
        )
        reasons: list[str] = []
        release: MaintenanceRelease | None = None
        if not decision.policy_eligible:
            reasons.extend(r for r in decision.reasons if r != "shadow_review_only")
        elif str(review_status).casefold() != "accepted":
            reasons.append("awaiting_review")
        else:
            try:
                release = self.reader.read("admit")
            except MaintenanceDenied as denied:
                reasons.append(denied.reason)
        if release is not None:
            reasons.extend(
                self._release_mismatches(
                    release, decision, evidence_records, scope, observed_lineage, connection
                )
            )
        admitted = release is not None and not reasons
        return MaintenanceDecision(
            proposal_id=str(record["proposal_id"]),
            admitted=admitted,
            reasons=tuple(reasons),
            decision=decision,
            release=release if admitted else None,
        )

    @staticmethod
    def _release_mismatches(
        release: MaintenanceRelease,
        decision: ProposalDecision,
        evidence_records: Mapping[str, Mapping[str, Any]],
        scope: str,
        observed: Mapping[str, str],
        connection: Any,
    ) -> list[str]:
        out: list[str] = []
        rel = decision.relationship
        if (rel["subject_type"], rel["predicate"], rel["object_type"]) != release.pair:
            out.append("pair_not_released")
        if (
            str(connection.tenant_id).casefold() != release.tenant_id.casefold()
            or str(connection.subscription_id).casefold()
            != release.subscription_id.casefold()
            or str(connection.connection_id).casefold()
            != release.connection_id.casefold()
            or scope.casefold() != release.scope
        ):
            out.append("scope_not_released")
        sources = {
            str(evidence_records[ref].get("source"))
            for ref in rel["evidence_refs"]
            if ref in evidence_records
        }
        if not sources or not sources <= set(release.sources):
            out.append("source_not_allowlisted")
        for key, expected in release.lineage.items():
            actual = observed.get(key)
            if actual != expected:
                out.append(f"lineage_mismatch:{key}")
        # Exact provider model is mandatory evidence; absence is denial.
        if (
            "model" not in release.lineage or not observed.get("model")
        ) and "lineage_mismatch:model" not in out:
            out.append("lineage_mismatch:model")
        if observed.get("definition_fingerprint") != release.definition_fingerprint:
            out.append("lineage_mismatch:definition_fingerprint")
        return out

    def canonical_rows(
        self,
        decisions: Iterable[MaintenanceDecision],
        *,
        deterministic_edges: Iterable[Mapping[str, Any]],
        records_by_id: Mapping[str, Mapping[str, Any]],
        entities: Mapping[str, Mapping[str, Any]],
        evidence_records: Mapping[str, Mapping[str, Any]],
        source_observed_at: datetime,
        ingestion_run_id: str,
        first_admission: Callable[[str, datetime], str],
        source_generation_id: str,
    ) -> list[dict[str, Any]]:
        existing = {
            (
                str(e.get("subject_id") or "").casefold(),
                str(e.get("predicate") or ""),
                str(e.get("object_id") or "").casefold(),
            )
            for e in deterministic_edges
        }
        rows: dict[str, dict[str, Any]] = {}
        for item in sorted(decisions, key=lambda d: d.proposal_id):
            if not item.admitted or item.release is None:
                continue
            rel = item.decision.relationship
            key = (rel["subject_id"], rel["predicate"], rel["object_id"])
            if key in existing:
                continue
            stable = stable_relationship_id(
                tenant_id=item.release.tenant_id,
                subscription_id=item.release.subscription_id,
                subject_id=str(entities[rel["subject_id"]]["resource_id"]),
                predicate=rel["predicate"],
                object_id=str(entities[rel["object_id"]]["resource_id"]),
            )
            if stable in rows:
                continue
            rows[stable] = materialize_relationship(
                proposal_id=item.proposal_id,
                relationship=rel,
                release=item.release,
                entities=entities,
                evidence_records=evidence_records,
                source_observed_at=source_observed_at,
                ingestion_run_id=ingestion_run_id,
                first_admitted_at=first_admission(stable, source_observed_at),
                source_generation_id=source_generation_id,
                ontology_version=item.release.ontology_version,
            )
        cap = min((d.release.max_model_edges for d in decisions if d.release), default=0)
        if len(rows) > cap:
            raise MaintenanceDenied("model_edge_budget_exceeded")
        return [rows[k] for k in sorted(rows)]


class MaintenanceAuthorizer:
    """Publisher-side independent recomputation from durable records."""

    def __init__(
        self,
        *,
        reader: MaintenanceReleaseReader,
        store: Any,
        trusted_records: Any | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.reader = reader
        self._store = store
        # Same clock as the release reader unless injected: freshness and the
        # control/expiry checks must agree at every authorize call.
        self._now = now or getattr(reader, "_clock", None) or (lambda: datetime.now(UTC))
        # Durable read-only port over coordinator-written trusted records
        # (source observation, run, first admission).  Absent port => deny.
        self._trusted = trusted_records

    @staticmethod
    def model_rows(relationships: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
        return [
            r
            for r in relationships
            if str(r.get("source") or "").casefold() in {"model", "ai", "llm"}
            or r.get("model_derived") is True
        ]

    def authorize_restore(
        self, *, expected_target: Mapping[str, str] | None = None
    ) -> MaintenanceRelease:
        """Read current restore authority and bind it to one exact recovery.

        The no-argument form is inspection-only.  A physical restore must pass
        the target tuple and retained generation digests; those values must be
        present as a closed object inside the signed release itself.
        """
        release = self.reader.read("restore")
        if expected_target is None:
            return release

        required = {
            "tenant_id",
            "subscription_id",
            "connection_id",
            "workspace_id",
            "item_id",
            "generation_id",
            "content_hash",
            "definition_fingerprint",
            "authorization_digest",
        }
        if set(expected_target) != required or any(
            not str(expected_target.get(key) or "").strip() for key in required
        ):
            raise MaintenanceDenied("restore_target_binding_incomplete")

        # The typed release is produced by the verifier, but target-generation
        # metadata is intentionally an exact signed extension.  Re-read the
        # envelope only to inspect that extension and bind it to the verified
        # release digest, preventing a changed envelope between the two reads.
        try:
            envelope = self.reader._envelope_source()
            payload = envelope["payload"]
            signed_release = payload["release"]
        except (KeyError, TypeError):
            raise MaintenanceDenied("restore_target_binding_missing") from None
        if digest(payload) != release.attestation_digest:
            raise MaintenanceDenied("restore_authority_changed")
        signed_target = (
            signed_release.get("restore_target")
            if isinstance(signed_release, Mapping)
            else None
        )
        if not isinstance(signed_target, Mapping) or set(signed_target) != required:
            raise MaintenanceDenied("restore_target_binding_missing")
        normalized = {key: str(value) for key, value in signed_target.items()}
        expected = {key: str(value) for key, value in expected_target.items()}
        if normalized != expected:
            raise MaintenanceDenied("restore_target_mismatch")
        declared = {
            "tenant_id": release.tenant_id,
            "subscription_id": release.subscription_id,
            "connection_id": release.connection_id,
            "workspace_id": release.workspace_id,
            "item_id": release.item_id,
            "definition_fingerprint": release.definition_fingerprint,
        }
        if any(expected[key] != value for key, value in declared.items()):
            raise MaintenanceDenied("restore_target_mismatch")
        return release

    def authorize(self, candidate: Any) -> dict[str, Any]:
        release = self.reader.read("admit")  # fresh clock/control every call
        return self._authorize_with_release(candidate, release)

    def authorize_bound(
        self, candidate: Any, expected_target: Mapping[str, str]
    ) -> tuple[MaintenanceRelease, dict[str, Any]]:
        """One fresh verification shared by row and exact-target checks.

        No caller-provided verified release or approval flag is accepted.
        """
        release = self.reader.read("admit")
        declared = {
            key: str(getattr(release, key))
            for key in (
                "tenant_id", "subscription_id", "connection_id", "workspace_id",
                "item_id", "definition_fingerprint",
            )
        }
        if dict(expected_target) != declared:
            raise MaintenanceDenied("maintenance_release_target_mismatch")
        return release, self._authorize_with_release(candidate, release)

    def _authorize_with_release(
        self, candidate: Any, release: MaintenanceRelease
    ) -> dict[str, Any]:
        rows = self.model_rows(candidate.relationships)
        if not rows:
            return {"authorization_digest": "", "model_rows": 0}
        if len(rows) > release.max_model_edges:
            raise MaintenanceDenied("model_edge_budget_exceeded")
        entities = {
            str(e.get("resource_id") or "").casefold(): e for e in candidate.entities
        }
        # One current durable snapshot per authorize call, not one whole-store
        # read/deepcopy per model row plus another for its evidence index.
        batches = self._store.list_evidence_batches()
        evidence = self._evidence_index(batches)
        seen: set[str] = set()
        for row in rows:
            self._authorize_row(row, release, candidate, entities, evidence, batches)
            if row["resource_id"] in seen:
                raise MaintenanceDenied("duplicate_model_edge")
            seen.add(row["resource_id"])
        return {
            "authorization_digest": digest(
                {
                    "binding": release.authorization_binding(),
                    "rows": sorted(
                        (r["resource_id"], r["change_version"]) for r in rows
                    ),
                }
            ),
            "model_rows": len(rows),
            "attestation_digest": release.attestation_digest,
            "release_id": release.release_id,
        }

    def _evidence_index(self, batches=None) -> dict[str, Mapping[str, Any]]:
        out: dict[str, Mapping[str, Any]] = {}
        if batches is None:
            batches = self._store.list_evidence_batches()
        for batch in batches:
            for rec in (batch.get("batch") or {}).get("evidence_records", ()):
                out[str(rec.get("evidence_id"))] = rec
        return out

    def _require_actual_receipt(self, record, proposal_id, release, candidate, batches) -> None:
        """Independently bind the proposal to its real validated provider receipt."""

        from ontology_discovery.contracts import proposal_content_id

        schema_version = str(record.get("schema_version") or "")
        policy_version = str(record.get("policy_version") or "")
        matched = 0
        bindings: set[tuple[tuple[str, str], ...]] = set()
        for stored in batches:
            if (
                stored.get("status") != "dispatched"
                or stored.get("source_generation_id") != candidate.source_generation
            ):
                continue
            result = stored.get("result")
            if not isinstance(result, Mapping):
                continue
            body = {k: v for k, v in result.items() if k != "provider_receipt"}
            try:
                validated = _validated_receipt_body(
                    canonical_json(stored["batch"]),
                    json.dumps(
                        body, sort_keys=True, separators=(",", ":"),
                        ensure_ascii=False, allow_nan=False,
                    ).encode(),
                )
            except (KeyError, TypeError, ValueError):
                continue
            if validated is None:
                continue
            item = record.get("proposal")
            if not isinstance(item, Mapping) or _proposal_membership_key(item) not in validated:
                continue
            try:
                pid = proposal_content_id(
                    proposal=item, scope=str(record.get("scope") or ""),
                    source_generation_id=str(candidate.source_generation),
                    schema_version=schema_version, policy_version=policy_version,
                )
            except (TypeError, ValueError):
                continue
            if pid != proposal_id:
                continue
            matched += 1
            receipt = result.get("provider_receipt")
            if not isinstance(receipt, Mapping):
                raise MaintenanceDenied("model_edge_receipt_missing")
            expected_hash = hashlib.sha256(
                json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            if (
                receipt.get("receipt_version") != "planner-receipt/v1"
                or receipt.get("metadata_status") != "available"
                or receipt.get("response_hash") != expected_hash
            ):
                raise MaintenanceDenied("model_edge_receipt_mismatch")
            observed = {
                "provider": str(receipt.get("selected_provider") or ""),
                "model": str(receipt.get("model") or ""),
                "agent_version": str(receipt.get("agent_version") or ""),
                "prompt_hash": str(receipt.get("prompt_hash") or ""),
                "schema_hash": str(receipt.get("schema_hash") or ""),
                "policy_version": policy_version,
                "schema_version": schema_version,
                "definition_fingerprint": vocabulary_fingerprint(),
            }
            if (
                not observed["model"]
                or observed["provider"] != release.lineage.get("provider")
                or observed["definition_fingerprint"] != release.definition_fingerprint
                or any(observed.get(k) != v for k, v in release.lineage.items())
            ):
                raise MaintenanceDenied("model_edge_receipt_lineage_mismatch")
            bindings.add(tuple(sorted(observed.items())))
        # Duplicate delivery of the same proposal must carry one exact trusted
        # receipt binding; any conflicting provider/model/version denies.
        if len(bindings) > 1:
            raise MaintenanceDenied("model_edge_receipt_conflict")
        if not matched:
            raise MaintenanceDenied("model_edge_receipt_missing")

    def _authorize_row(self, row, release, candidate, entities, evidence, batches) -> None:
        try:
            lineage = json.loads(row["lineage_json"])
            proposal_id = str(lineage["proposal_id"])
        except (KeyError, TypeError, ValueError):
            raise MaintenanceDenied("model_edge_lineage_incomplete") from None
        triple = (row.get("subject_type"), row.get("predicate"), row.get("object_type"))
        if (
            row.get("source") != "model"
            or row.get("model_derived") is not True
            or triple != release.pair
            or row.get("tenant_id") != release.tenant_id
            or row.get("subscription_id") != release.subscription_id
            or str(row.get("scope")).casefold() != release.scope
            or lineage.get("attestation_digest") != release.attestation_digest
            or lineage.get("release_id") != release.release_id
        ):
            raise MaintenanceDenied("model_edge_not_released")
        if row["resource_id"] != stable_relationship_id(
            tenant_id=release.tenant_id,
            subscription_id=release.subscription_id,
            subject_id=str(row["subject_id"]),
            predicate=str(row["predicate"]),
            object_id=str(row["object_id"]),
        ):
            raise MaintenanceDenied("model_edge_identity_mismatch")
        record = self._store.get_proposal(proposal_id)
        if record is None or proposal_id not in candidate.proposal_lineage:
            raise MaintenanceDenied("model_edge_proposal_unknown")
        proposal = record["proposal"]
        if (
            str(proposal.get("subject_id")).casefold() != str(row["subject_id"]).casefold()
            or str(proposal.get("object_id")).casefold() != str(row["object_id"]).casefold()
            or (proposal.get("subject_type"), proposal.get("predicate"), proposal.get("object_type")) != triple
            or record.get("source_generation_id") != candidate.source_generation
        ):
            raise MaintenanceDenied("model_edge_proposal_mismatch")
        if self._store.get_review(proposal_id).get("status") != "accepted":
            raise MaintenanceDenied("model_edge_review_not_accepted")
        self._require_actual_receipt(record, proposal_id, release, candidate, batches)
        refs = sorted(str(r) for r in proposal.get("evidence_refs", ()))
        if not refs or sorted(lineage.get("evidence_ids", ())) != refs:
            raise MaintenanceDenied("model_edge_evidence_mismatch")
        # Same deterministic policy as admission, fresh clock, current durable
        # evidence/scope/lineage: evidence that expired since dispatch denies.
        policy = ProposalPolicy(shadow_mode=True, now=self._now).evaluate(
            proposal,
            entities=entities,
            evidence_records=evidence,
            scope=str(record.get("scope") or ""),
            source_generation_id=str(candidate.source_generation),
            review_status="accepted",
            schema_version=str(record.get("schema_version") or "proposal-schema-v1"),
            policy_version=str(record.get("policy_version") or "proposal-policy-v1"),
        )
        if not policy.policy_eligible:
            stale = "stale_evidence" in policy.reasons
            raise MaintenanceDenied(
                "model_edge_evidence_stale" if stale else "model_edge_policy_ineligible"
            )
        sources: set[str] = set()
        for ref in refs:
            item = evidence.get(ref)
            if (
                item is None
                or item.get("supports") is not True
                or item.get("contradicts")
                or (item.get("subject_type"), item.get("predicate"), item.get("object_type")) != triple
                or str(item.get("subject_id")).casefold() != str(row["subject_id"]).casefold()
                or str(item.get("object_id")).casefold() != str(row["object_id"]).casefold()
                or item.get("source_generation_id") != candidate.source_generation
            ):
                raise MaintenanceDenied("model_edge_evidence_mismatch")
            sources.add(str(item.get("source")))
        if len(sources) < 2 or not sources <= set(release.sources):
            raise MaintenanceDenied("model_edge_sources_not_allowlisted")
        if lineage.get("evidence_digest") != digest([evidence[r] for r in refs]):
            raise MaintenanceDenied("model_edge_evidence_mismatch")
        for end in (row["subject_id"], row["object_id"]):
            entity = entities.get(str(end).casefold())
            if (
                entity is None
                or entity.get("lifecycle_status") != "active"
                or str(entity.get("scope") or "").casefold() != release.scope
            ):
                raise MaintenanceDenied("model_edge_endpoint_unauthorized")
        # Exact independent recomputation: every derived field of the canonical
        # row must equal what trusted durable facts produce.  Observation time,
        # ingestion run and first-admission instant come only from the durable
        # trusted records written by the coordinator, never from the row.
        if self._trusted is None:
            raise MaintenanceDenied("trusted_records_unavailable")
        observation = self._trusted.source_observation(str(candidate.source_generation))
        first = self._trusted.first_admission(str(row["resource_id"]))
        if observation is None or first is None:
            raise MaintenanceDenied("trusted_records_missing")
        if (
            observation.get("source_generation_id") != str(candidate.source_generation)
            or first.get("source_generation_id") is None
            or not first.get("first_admitted_at")
        ):
            raise MaintenanceDenied("trusted_records_inconsistent")
        try:
            expected = materialize_relationship(
                proposal_id=proposal_id,
                relationship={
                    "subject_id": row["subject_id"],
                    "subject_type": row["subject_type"],
                    "predicate": row["predicate"],
                    "object_id": row["object_id"],
                    "object_type": row["object_type"],
                    "evidence_refs": refs,
                },
                release=release,
                entities=entities,
                evidence_records=evidence,
                source_observed_at=datetime.fromisoformat(
                    str(observation["source_observed_at"])
                ),
                ingestion_run_id=str(observation["ingestion_run_id"]),
                first_admitted_at=str(first["first_admitted_at"]),
                source_generation_id=str(candidate.source_generation),
                ontology_version=str(row["ontology_version"]),
            )
        except (KeyError, TypeError, ValueError):
            raise MaintenanceDenied("model_edge_recomputation_failed") from None
        if dict(row) != expected:
            raise MaintenanceDenied("model_edge_not_canonical")


__all__ = [
    "MaintenanceAdmission",
    "MaintenanceAuthorizer",
    "MaintenanceDecision",
    "vocabulary_fingerprint",
]
