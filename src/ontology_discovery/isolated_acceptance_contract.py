"""Inert structural contracts, not authorization for an acceptance execution.

Nothing in this module imports live validators, reads cloud state or starts Jobs.
Reviewed/qualified are declared artifact states, not authenticated approvals.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    model_validator,
)

Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
Identifier = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")]
UUIDText = Annotated[str, Field(pattern=r"^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$")]
Image = Annotated[
    str,
    Field(
        pattern=r"^[a-z0-9][a-z0-9./:_-]*@sha256:[0-9a-f]{64}$",
    ),
]
ImageRole = Literal[
    "api",
    "web",
    "coordinator",
    "rbac_validator",
    "fixture_prepare",
    "fixture_cleanup",
    "evidence",
    "validation_publisher",
    "production_publisher",
]
JobRole = Literal[
    "coordinator",
    "rbac_validator",
    "fixture_prepare",
    "fixture_cleanup",
    "evidence",
    "validation_publisher",
]
RootRole = Literal[
    "connection",
    "state",
    "command",
    "dispatch",
    "publication",
    "fixture",
    "drill",
]
ConsumerRole = Literal["api", "fabric", "agent", "export", "semantic"]
_IMAGE_ROLES = {
    "api",
    "web",
    "coordinator",
    "rbac_validator",
    "fixture_prepare",
    "fixture_cleanup",
    "evidence",
    "validation_publisher",
    "production_publisher",
}
_JOB_ROLES = _IMAGE_ROLES - {"api", "web", "production_publisher"}
_ROOT_ROLES = {
    "connection",
    "state",
    "command",
    "dispatch",
    "publication",
    "fixture",
    "drill",
}
_CONSUMERS = {"api", "fabric", "agent", "export", "semantic"}
_ARM = re.compile(
    r"^/subscriptions/([0-9a-f-]+)/resourceGroups/([A-Za-z0-9_.-]+)"
    r"/providers/(Microsoft\.App/(jobs|containerApps)"
    r"|Microsoft\.ManagedIdentity/(userAssignedIdentities))/([A-Za-z0-9-]+)$"
)


class ContractError(ValueError):
    """A local contract is structurally invalid or its referenced bytes differ."""


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class ArtifactReference(_Closed):
    """Digest of exact retained bytes, never a pin derived from an observation."""

    key: Identifier
    sha256: Digest


class MaterializationTargets(_Closed):
    """Resolved Lakehouse Tables and native-item targets, separate from Files roots."""

    workspace_id: UUIDText
    lakehouse_id: UUIDText
    tables: list[TableTarget] = Field(min_length=1)
    native_enabled: bool
    native_item_ids: list[UUIDText]

    @model_validator(mode="after")
    def unique_targets(self) -> Self:
        names = [
            (t.schema_name.casefold(), t.table_name.casefold()) for t in self.tables
        ]
        if len(set(names)) != len(names) or len(set(self.native_item_ids)) != len(
            self.native_item_ids
        ):
            raise ValueError("duplicate materialization target")
        if self.native_enabled != bool(self.native_item_ids):
            raise ValueError("native enabled state must match explicit item targets")
        return self


class TableTarget(_Closed):
    """An explicit Lakehouse schema/table, not a purported Files namespace."""

    schema_name: Annotated[str, Field(pattern=r"^(|[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127})$")]
    table_name: Identifier


class MaintenanceTarget(_Closed):
    """Exact six-field target already required by the publisher runtime."""

    tenant_id: UUIDText
    subscription_id: UUIDText
    connection_id: UUIDText
    workspace_id: UUIDText
    item_id: UUIDText
    definition_fingerprint: Digest


class ConsumerBinding(_Closed):
    """A pinned observer surface; its label is not external-client proof."""

    resource_id: Identifier
    publication_root: str
    materialization_fingerprint: Digest


class ResolvedConfiguration(_Closed):
    """Effective targets after configuration resolution, regardless of YAML/JSON source."""

    roots: dict[RootRole, str]
    materialization: MaterializationTargets
    consumers: dict[ConsumerRole, ConsumerBinding]
    maintenance_target: MaintenanceTarget

    @model_validator(mode="after")
    def complete_bindings(self) -> Self:
        if set(self.roots) != _ROOT_ROLES or set(self.consumers) != _CONSUMERS:
            raise ValueError("exact root and five-consumer registries required")
        root_paths = [canonical_onelake_root(root) for root in self.roots.values()]
        _disjoint(root_paths)
        publication = canonical_onelake_root(self.roots["publication"])
        targets = self.materialization
        consumers = list(self.consumers.values())
        if len({c.resource_id.casefold() for c in consumers}) != len(consumers):
            raise ValueError("five distinct consumer bindings required")
        if any(
            canonical_onelake_root(c.publication_root) != publication for c in consumers
        ):
            raise ValueError("consumer publication root differs")
        if any(
            c.materialization_fingerprint != _digest(targets.model_dump())
            for c in consumers
        ):
            raise ValueError("consumer materialization fingerprint differs")
        if (
            self.maintenance_target.workspace_id != targets.workspace_id
            or self.maintenance_target.item_id != targets.lakehouse_id
        ):
            raise ValueError("maintenance target differs from resolved materialization")
        return self


class JobBinding(_Closed):
    """A freeze reference for a fixed Job; no read/start command is exposed."""

    resource_id: str
    identity_resource_id: str
    client_id: UUIDText
    image: Image
    template: ArtifactReference
    runtime_job_start: bool

    @model_validator(mode="after")
    def deny_job_start(self) -> Self:
        if self.runtime_job_start:
            raise ValueError("runtime Job-start authority forbidden")
        return self


class ProtectedProduction(_Closed):
    """Current freeze evidence does not explain historical publisher divergence."""

    publisher_resource_id: str
    api_resource_id: str
    publisher_client_id: UUIDText
    publisher_image: Image
    api_image: Image
    api_preimage: ArtifactReference
    publisher_preimage: ArtifactReference
    roots: list[str] = Field(min_length=1)
    materialization: MaterializationTargets
    historical_divergence: Literal["unresolved"]


class _Header(_Closed):
    schema_version: Literal["isolated-acceptance/v1"]
    purpose: Literal["offline-contract-validation"]
    authority: Literal["none"]
    source_sha: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    contract_digest: Digest


class DraftContract(_Header):
    """An explicitly incomplete design that cannot satisfy qualification loading."""

    status: Literal["draft"]
    unresolved_fields: list[Identifier] = Field(min_length=1)


class _BoundContract(_Header):
    """Complete bindings shared by disjoint reviewed and qualified document types."""

    tenant_id: UUIDText
    subscription_id: UUIDText
    production_plan: ArtifactReference
    validation_plan: ArtifactReference
    terraform_state: ArtifactReference
    review: ArtifactReference
    image_pins: dict[ImageRole, Image]
    jobs: dict[JobRole, JobBinding]
    protected: ProtectedProduction
    resolved: ResolvedConfiguration
    resolved_config: ArtifactReference
    maintenance_authorizer: ArtifactReference
    maintenance_observers: ArtifactReference
    drill_templates: dict[
        Literal["arm", "inspect", "resume", "cleanup"], ArtifactReference
    ]

    @model_validator(mode="after")
    def exact_isolated_bindings(self) -> Self:
        if set(self.image_pins) != _IMAGE_ROLES or set(self.jobs) != _JOB_ROLES:
            raise ValueError("complete role-keyed images and fixed Jobs required")
        if set(self.drill_templates) != {"arm", "inspect", "resume", "cleanup"}:
            raise ValueError("complete server-owned drill freeze registry required")
        protected = self.protected
        publisher = _arm_target(
            protected.publisher_resource_id, "jobs", self.subscription_id
        )
        _arm_target(protected.api_resource_id, "containerApps", self.subscription_id)
        if (
            protected.publisher_image != self.image_pins["production_publisher"]
            or protected.api_image != self.image_pins["api"]
        ):
            raise ValueError("protected image pin differs")
        job_ids = []
        for role, binding in self.jobs.items():
            target = _arm_target(binding.resource_id, "jobs", self.subscription_id)
            _arm_target(
                binding.identity_resource_id,
                "userAssignedIdentities",
                self.subscription_id,
            )
            if target == publisher or binding.image != self.image_pins[role]:
                raise ValueError(
                    "protected publisher substitution or mismatched role pin"
                )
            job_ids.append(target)
        if len(set(job_ids)) != len(job_ids):
            raise ValueError("fixed Job registry aliases a target")
        if self.jobs["validation_publisher"].client_id != protected.publisher_client_id:
            raise ValueError("isolated publisher must retain pinned publisher identity")
        actual = self.resolved.materialization
        production = protected.materialization
        if (
            actual.workspace_id == production.workspace_id
            or actual.lakehouse_id == production.lakehouse_id
            or set(actual.native_item_ids) & set(production.native_item_ids)
        ):
            raise ValueError("validation materialization aliases production")
        _disjoint(
            [
                *[
                    canonical_onelake_root(root)
                    for root in self.resolved.roots.values()
                ],
                *[canonical_onelake_root(root) for root in protected.roots],
            ]
        )
        target = self.resolved.maintenance_target
        if (
            target.tenant_id != self.tenant_id
            or target.subscription_id != self.subscription_id
        ):
            raise ValueError("maintenance scope differs from contract")
        return self


class ReviewedContract(_BoundContract):
    """Complete declared reviewed bindings; no signature or execution authority inferred."""

    status: Literal["reviewed"]


class QualificationReceipt(_Closed):
    """A declared direct observation reference, not a verified approval signature."""

    artifact: ArtifactReference
    outcome: Literal["passed"]
    observer_kind: Literal[
        "in_process_surface", "external_client", "effective_capability"
    ]
    binding_fingerprint: Digest


class DirectObservation(_Closed):
    """Closed receipt content; a generation-complete boolean is not this observation."""

    source_sha: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    role: (
        ConsumerRole
        | Literal[
            "publisher_write_cas_delete",
            "denied_principals",
            "lifecycle",
            "rollback",
        ]
    )
    mode: Literal["direct_observation"]
    observer_kind: Literal[
        "in_process_surface", "external_client", "effective_capability"
    ]
    outcome: Literal["passed"]
    binding_fingerprint: Digest
    observation: ArtifactReference


class QualifiedContract(_BoundContract):
    """Complete qualification claims, still inert and unauthenticated by this loader."""

    status: Literal["qualified"]
    consumer_receipts: dict[ConsumerRole, QualificationReceipt]
    capability_receipts: dict[
        Literal[
            "publisher_write_cas_delete", "denied_principals", "lifecycle", "rollback"
        ],
        QualificationReceipt,
    ]

    @model_validator(mode="after")
    def complete_receipts(self) -> Self:
        if set(self.consumer_receipts) != _CONSUMERS or set(
            self.capability_receipts
        ) != {
            "publisher_write_cas_delete",
            "denied_principals",
            "lifecycle",
            "rollback",
        }:
            raise ValueError("complete qualification receipts required")
        receipts = [
            *self.consumer_receipts.values(),
            *self.capability_receipts.values(),
        ]
        if len({r.artifact.sha256 for r in receipts}) != len(receipts):
            raise ValueError(
                "independent receipt artifacts required, not metadata echo"
            )
        for role, receipt in self.consumer_receipts.items():
            if (
                receipt.observer_kind == "effective_capability"
                or receipt.binding_fingerprint
                != _digest(self.resolved.consumers[role].model_dump())
            ):
                raise ValueError("consumer receipt binding differs")
        capability_binding = _digest(
            {
                "jobs": {key: value.model_dump() for key, value in self.jobs.items()},
                "resolved": self.resolved.model_dump(),
                "protected": self.protected.model_dump(),
            }
        )
        if any(
            r.binding_fingerprint != capability_binding
            for r in self.capability_receipts.values()
        ):
            raise ValueError("capability receipt binding differs")
        return self


Contract = Annotated[
    DraftContract | ReviewedContract | QualifiedContract, Field(discriminator="status")
]
_ADAPTER = TypeAdapter(Contract)


def canonical_onelake_root(value: str) -> tuple[str, str, tuple[str, ...]]:
    """Canonicalize explicit GUID-based ABFSS Files roots without ambiguous encodings."""
    if (
        not isinstance(value, str)
        or value != value.strip()
        or any(ord(char) < 33 or ord(char) > 126 for char in value)
    ):
        raise ValueError("OneLake root must be explicit")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "abfss"
        or parsed.query
        or parsed.fragment
        or "%" in value
        or "\\" in value
        or "?" in value
        or "#" in value
        or not re.fullmatch(
            r"[0-9a-fA-F-]{36}@onelake\.dfs\.fabric\.microsoft\.com",
            parsed.netloc,
            re.IGNORECASE,
        )
    ):
        raise ValueError("unsupported OneLake authority or ambiguous path")
    workspace = parsed.netloc.split("@")[0].lower()
    segments = parsed.path.removesuffix("/").split("/")
    if (
        len(segments) < 4
        or segments[0] != ""
        or segments[2] != "Files"
        or any(
            not re.fullmatch(r"[a-zA-Z0-9_.-]+", part) or part in {".", ".."}
            for part in segments[1:]
        )
    ):
        raise ValueError("OneLake root must be an unambiguous Files path")
    item = segments[1].lower()
    uuid_adapter = TypeAdapter(UUIDText)
    uuid_adapter.validate_python(workspace)
    uuid_adapter.validate_python(item)
    return workspace, item, tuple(part.casefold() for part in segments[2:])


def _disjoint(roots: list[tuple[str, str, tuple[str, ...]]]) -> None:
    for index, left in enumerate(roots):
        for right in roots[index + 1 :]:
            if left[:2] == right[:2] and (
                left[2] == right[2][: len(left[2])]
                or right[2] == left[2][: len(right[2])]
            ):
                raise ValueError("root capability alias or overlap")


def _arm_target(value: str, kind: str, subscription: str) -> str:
    match = _ARM.fullmatch(value)
    if not match or match[1] != subscription or kind not in {match[4], match[5]}:
        raise ValueError("resource target kind or subscription differs")
    return value.casefold()


def _digest(value: object) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode()
        ).hexdigest()
    )


def contract_digest(payload: Mapping[str, object]) -> str:
    """Hash canonical JSON excluding only the top-level self-digest field."""
    return _digest(
        {key: value for key, value in payload.items() if key != "contract_digest"}
    )


def contract_json_schema() -> dict[str, object]:
    """Return the versioned discriminated schema without creating any live binding."""
    return _ADAPTER.json_schema()


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise ContractError("nonfinite JSON value")


def _json(body: bytes) -> object:
    return json.loads(body, object_pairs_hook=_pairs, parse_constant=_reject_constant)


def _references(model: BaseModel):
    if isinstance(model, ArtifactReference):
        yield model
    else:
        for name in type(model).model_fields:
            value = getattr(model, name)
            if isinstance(value, BaseModel):
                yield from _references(value)
            elif isinstance(value, dict):
                for child in value.values():
                    if isinstance(child, BaseModel):
                        yield from _references(child)


def load_contract(path: Path, *, artifacts: Mapping[str, bytes]) -> Contract:
    """Load strict local JSON and verify all referenced bytes; never authenticate authority."""
    try:
        payload = _json(path.read_bytes())
        result = _ADAPTER.validate_python(payload)
        if result.contract_digest != contract_digest(payload):
            raise ContractError("contract digest mismatch")
        for reference in _references(result):
            body = artifacts.get(reference.key)
            if not isinstance(body, bytes) or (
                "sha256:" + hashlib.sha256(body).hexdigest() != reference.sha256
            ):
                raise ContractError("missing or mismatched artifact bytes")
        if isinstance(result, _BoundContract):
            effective = ResolvedConfiguration.model_validate(
                _json(artifacts[result.resolved_config.key])
            )
            if effective != result.resolved:
                raise ContractError("resolved configuration differs from contract")
        if isinstance(result, QualifiedContract):
            for role, receipt in {
                **result.consumer_receipts,
                **result.capability_receipts,
            }.items():
                observation = DirectObservation.model_validate(
                    _json(artifacts[receipt.artifact.key])
                )
                if (
                    observation.source_sha != result.source_sha
                    or observation.role != role
                    or observation.observer_kind != receipt.observer_kind
                    or observation.binding_fingerprint != receipt.binding_fingerprint
                    or observation.outcome != receipt.outcome
                ):
                    raise ContractError("qualification observation differs")
                reference = observation.observation
                body = artifacts.get(reference.key)
                if not isinstance(body, bytes) or (
                    "sha256:" + hashlib.sha256(body).hexdigest() != reference.sha256
                ):
                    raise ContractError("missing or mismatched observation artifact")
        return result
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        ValidationError,
        ValueError,
    ) as exc:
        if isinstance(exc, ContractError):
            raise
        raise ContractError("invalid isolated acceptance contract") from exc


def require_qualified_contract(
    path: Path, *, artifacts: Mapping[str, bytes]
) -> QualifiedContract:
    """Require complete declared qualification, not permission to execute or publish."""
    result = load_contract(path, artifacts=artifacts)
    if not isinstance(result, QualifiedContract):
        raise ContractError("qualified contract required")
    return result
