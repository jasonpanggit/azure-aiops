"""Read-only logical projection; the broker alone owns physical destinations."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from fabric.dataset_mapper import (
    ONTOLOGY_ENTITY_TYPES,
    ONTOLOGY_RELATIONSHIP_TYPES,
    ontology_entity_table,
    ontology_relationship_table,
)
from fabric.maintenance_output import (
    GenerationOutputContext,
    canonical_json,
    output_digest,
    validate_logical_candidate,
)
from fabric.schema_registry import schema_for
from ontology_discovery.immutable_attempt import AttemptPublicationProtocol
from ontology_discovery.maintenance_materialization import (
    ATTEMPT_PROTOCOL,
    _AttemptProjectionChecks,
)
from ontology_discovery.publisher import PublicationSafetyError


class StagedAttemptInput(Protocol):
    """Read-only immutable generation and exact stage-authority capability."""

    def read_generation(self, generation_id: str) -> dict[str, Any]:
        """Read one complete retained staged generation."""
        ...

    def read_stage_authorization(
        self, *, target_generation_id: str, owner_id: str, fence: int
    ) -> dict[str, Any]:
        """Read the exact immutable authority recorded for a stage."""
        ...


def _tables() -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                *(ontology_entity_table(name) for name in ONTOLOGY_ENTITY_TYPES),
                *(
                    ontology_relationship_table(*triple)
                    for triple in ONTOLOGY_RELATIONSHIP_TYPES
                ),
                "ontology_entities",
                "ontology_relationships",
                "ontology_health",
                "ontology_quality_report",
            }
        )
    )


@dataclass(frozen=True)
class LogicalProduct:
    """One independently expected logical table, without a destination URI."""

    name: str
    schema_digest: str
    row_count: int
    content_digest: str

    def __post_init__(self) -> None:
        if (
            type(self.name) is not str
            or type(self.row_count) is not int
            or self.row_count < 0
            or any(
                type(value) is not str or re.fullmatch(r"[a-f0-9]{64}", value) is None
                for value in (self.schema_digest, self.content_digest)
            )
        ):
            raise PublicationSafetyError("attempt_projection:product_shape")


def describe_logical_products(
    products: Mapping[str, Sequence[Mapping[str, Any]]],
) -> tuple[LogicalProduct, ...]:
    """Describe complete logical rows for independent planning or comparison."""
    if tuple(sorted(products)) != _tables():
        raise PublicationSafetyError("attempt_projection:table_membership")
    return tuple(
        LogicalProduct(
            name,
            hashlib.sha256(schema_for(name).serialize()).hexdigest(),
            len(products[name]),
            output_digest(sorted(canonical_json(dict(row)) for row in products[name])),
        )
        for name in sorted(products)
    )


@dataclass(frozen=True)
class ImmutableLogicalProjectionPolicy:
    """Trusted, independently pinned context and complete logical product batch."""

    context: GenerationOutputContext
    products: tuple[LogicalProduct, ...]

    def __post_init__(self) -> None:
        if (
            type(self.context) is not GenerationOutputContext
            or type(self.products) is not tuple
            or any(type(product) is not LogicalProduct for product in self.products)
            or tuple(product.name for product in self.products) != _tables()
        ):
            raise PublicationSafetyError("attempt_projection:policy_shape")

    def validate(
        self,
        context: GenerationOutputContext,
        entities: Sequence[Mapping[str, Any]],
        relationships: Sequence[Mapping[str, Any]],
        products: Mapping[str, Sequence[Mapping[str, Any]]],
    ) -> None:
        """Refuse context, vocabulary, schema/count/content or membership drift."""
        validate_logical_candidate(
            self.context,
            context,
            entities,
            relationships,
            self.entity_types,
            self.relationship_triples,
        )
        if describe_logical_products(products) != self.products:
            raise PublicationSafetyError("attempt_projection:logical_batch_changed")

    @property
    def entity_types(self) -> tuple[str, ...]:
        """Return the existing closed canonical entity vocabulary."""
        return tuple(sorted(ONTOLOGY_ENTITY_TYPES))

    @property
    def relationship_triples(self) -> tuple[tuple[str, str, str], ...]:
        """Return the existing closed canonical relationship vocabulary."""
        return tuple(sorted(ONTOLOGY_RELATIONSHIP_TYPES))


class ReadOnlyAttemptProjector(_AttemptProjectionChecks):
    """Execute logical projection and exact broker lifecycle without a sink writer.

    Application composition supplies staged reads, current authorizer, target,
    independently expected policies and the already configured protocol.
    No service, Delta writer, local root, pointer or reader is constructed.
    """

    publication_protocol = ATTEMPT_PROTOCOL

    def __init__(
        self,
        *,
        storage: StagedAttemptInput,
        authorizer: Any,
        expected_target: Mapping[str, str],
        definition_fingerprint: Callable[[], str],
        attempt_protocol: AttemptPublicationProtocol,
        policies: tuple[ImmutableLogicalProjectionPolicy, ...],
    ) -> None:
        if (
            not isinstance(attempt_protocol, AttemptPublicationProtocol)
            or not callable(getattr(storage, "read_generation", None))
            or not callable(getattr(storage, "read_stage_authorization", None))
            or not callable(definition_fingerprint)
            or authorizer is None
            or type(policies) is not tuple
            or not policies
            or any(type(p) is not ImmutableLogicalProjectionPolicy for p in policies)
            or any(
                dict(p.context.expected_target) != dict(expected_target)
                for p in policies
            )
            or len({p.context for p in policies}) != len(policies)
        ):
            raise PublicationSafetyError("attempt_projection:trusted_binding_required")
        self._storage = storage
        self._authorizer = authorizer
        self._expected_target = dict(expected_target)
        self._definition_fingerprint = definition_fingerprint
        self._attempt_protocol = attempt_protocol
        self._policies = policies
        self._attempt_session = None
        self._attempt_id = None
        self._attempt_reference = None
        self._attempt_before_send = None
        self._attempt_request_digests = {}

    def _target_for(
        self, staged: Mapping[str, Any], generation_id: str
    ) -> dict[str, str]:
        target = self._expected_target
        if (
            self._definition_fingerprint() != target["definition_fingerprint"]
            or staged["manifest"].get("generation_id") != generation_id
        ):
            raise PublicationSafetyError("attempt_projection:target_changed")
        return dict(target)

    def __call__(self, candidate: Any) -> Mapping[str, Any]:
        """Project one exact staged candidate and stage only its approved batch."""
        if self._attempt_session is None or self._attempt_id is None:
            raise PublicationSafetyError("immutable_attempt:session_missing")
        staged, context, products = self._project_attempt(candidate)
        target = dict(context.expected_target)
        policy = next((p for p in self._policies if p.context == context), None)
        if policy is None:
            raise PublicationSafetyError("attempt_projection:operation_policy_missing")
        policy.validate(context, staged["entities"], staged["relationships"], products)
        args = {
            "attempt_id": self._attempt_id,
            "candidate": {
                "generation_id": context.generation_id,
                "source_generation": context.source_generation,
                "content_hash": context.content_hash,
                "authorization_digest": context.authorization_digest,
                "attestation_digest": context.attestation_digest,
                "staged_manifest_digest": context.staged_manifest_digest,
                "validation_digest": context.validation_digest,
                "expected_target": target,
            },
            "products": products,
        }
        reference = self._attempt_protocol.stage(
            self._attempt_session,
            **args,
            before_send=self._attempt_before_send,
        )
        self._attempt_reference = reference
        return {
            "status": "completed",
            "protocol": ATTEMPT_PROTOCOL,
            "attempt_reference": reference.as_dict(),
            "receipt_digest": reference.catalog_digest,
        }
