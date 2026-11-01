"""Opt-in local semantic checks; no execution caller or cloud adapter uses this module."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ontology_discovery.isolated_acceptance_contract import (
    ArtifactReference,
    ContractError,
    Digest,
    JobRole,
    QualifiedContract,
    ReviewedContract,
    _json,
    load_contract,
)
from scripts.validate_ontology_deployment_plan import (
    PlanValidationError,
    validate_saved_plan,
)
from scripts.validate_ontology_discovery_live import (
    EvidenceError,
    assert_fixed_template,
)

_ROLES = {
    "coordinator",
    "rbac_validator",
    "fixture_prepare",
    "fixture_cleanup",
    "evidence",
    "validation_publisher",
}


class JobSemantics(BaseModel):
    """Explicit expected semantics; the verifier never learns pins from snapshots."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    template_projection_hash: Digest
    command: list[str] = Field(min_length=1)
    args: list[str]
    timeout_seconds: Annotated[int, Field(ge=1, le=900)]
    environment_names: list[str]
    trigger: Literal["Manual"]
    retry_limit: Annotated[int, Field(ge=0, le=0)]
    parallelism: Annotated[int, Field(ge=1, le=1)]
    completion_count: Annotated[int, Field(ge=1, le=1)]


class SemanticExpectations(BaseModel):
    """Separate locally supplied expectations, not authenticated review or authority."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    schema_version: Literal["isolated-artifact-semantics/v1"]
    contract_digest: Digest
    jobs: dict[JobRole, JobSemantics]

    @model_validator(mode="after")
    def exact_roles(self) -> Self:
        if set(self.jobs) != _ROLES:
            raise ValueError("complete Job semantics registry required")
        return self


def verify_artifact_semantics(
    path: Path,
    *,
    artifacts: Mapping[str, bytes],
    expectations: SemanticExpectations,
) -> dict[str, str]:
    """Verify local raw plans/Job snapshots without granting approval or execution.

    The unchanged saved-plan helper deliberately rejects isolated plans outside
    its legacy address/image contract. This function does not rewrite those plans.
    """
    contract = load_contract(path, artifacts=artifacts)
    if not isinstance(contract, ReviewedContract | QualifiedContract):
        raise ContractError("complete declared bindings required for semantic checks")
    if expectations.contract_digest != contract.contract_digest:
        raise ContractError("semantic expectations refer to a different contract")
    for environment, reference in (
        ("production", contract.production_plan),
        ("validation", contract.validation_plan),
    ):
        try:
            validate_saved_plan(
                _object(artifacts, reference),
                environment=environment,
                expected_image_digests={
                    role: contract.image_pins[role].rsplit("@", 1)[1]
                    for role in ("api", "web")
                },
            )
        except (PlanValidationError, TypeError, KeyError, AttributeError) as exc:
            raise PlanValidationError("semantic_subset.plan rejected") from exc
    for role, binding in contract.jobs.items():
        job = _object(artifacts, binding.template)
        expected = expectations.jobs[role]
        # This historical projection omits exact UAI keys; check them separately.
        try:
            assert_fixed_template(expected.template_projection_hash, job, job)
        except (EvidenceError, TypeError, AttributeError) as exc:
            raise EvidenceError("semantic_subset.template hash mismatch") from exc
        _closed(job, {"id", "name", "identity", "properties"}, "job")
        identity = job.get("identity")
        properties = job.get("properties")
        if not isinstance(identity, dict) or not isinstance(properties, dict):
            raise ContractError("raw ARM identity/properties required")
        _closed(identity, {"type", "userAssignedIdentities"}, "identity")
        _closed(properties, {"configuration", "template"}, "properties")
        assigned = identity.get("userAssignedIdentities")
        if (
            str(job.get("id")).casefold() != binding.resource_id.casefold()
            or str(job.get("name")).casefold()
            != binding.resource_id.rsplit("/", 1)[1].casefold()
            or identity.get("type") != "UserAssigned"
            or not isinstance(assigned, dict)
            or len(assigned) != 1
            or {key.casefold() for key in assigned}
            != {binding.identity_resource_id.casefold()}
        ):
            raise ContractError("Job ARM target or exact UAI association differs")
        assigned_identity = next(iter(assigned.values()))
        if (
            not isinstance(assigned_identity, dict)
            or str(assigned_identity.get("clientId")).casefold()
            != binding.client_id.casefold()
        ):
            raise ContractError("Job assigned identity client ID differs")
        _closed(assigned_identity, {"clientId", "principalId"}, "assigned_identity")
        configuration = properties.get("configuration")
        template = properties.get("template")
        if not isinstance(configuration, dict) or not isinstance(template, dict):
            raise ContractError("raw ARM configuration/template required")
        _closed(
            configuration,
            {
                "triggerType",
                "replicaRetryLimit",
                "replicaTimeout",
                "manualTriggerConfig",
                "scheduleTriggerConfig",
                "eventTriggerConfig",
            },
            "configuration",
        )
        _closed(template, {"containers"}, "template")
        containers = template.get("containers")
        if not isinstance(containers, list) or len(containers) != 1:
            raise ContractError("exactly one Job container required")
        container = containers[0]
        if not isinstance(container, dict):
            raise ContractError("Job container object required")
        _closed(
            container,
            {"name", "image", "command", "args", "env", "resources"},
            "container",
        )
        resources = container.get("resources")
        if not isinstance(resources, dict):
            raise ContractError("semantic_subset.resources required")
        _closed(resources, {"cpu", "memory"}, "resources")
        manual = configuration.get("manualTriggerConfig")
        if not isinstance(manual, dict) or any(
            type(manual.get(key)) is not int
            for key in ("parallelism", "replicaCompletionCount")
        ):
            raise ContractError("semantic_subset.manual trigger differs")
        if (
            configuration.get("triggerType") != expected.trigger
            or configuration.get("replicaRetryLimit") != expected.retry_limit
            or type(configuration.get("replicaRetryLimit")) is not int
            or configuration.get("replicaTimeout") != expected.timeout_seconds
            or type(configuration.get("replicaTimeout")) is not int
            or configuration.get("manualTriggerConfig")
            != {
                "parallelism": expected.parallelism,
                "replicaCompletionCount": expected.completion_count,
            }
            or configuration.get("scheduleTriggerConfig") not in (None, {})
            or configuration.get("eventTriggerConfig") not in (None, {})
            or container.get("command") != expected.command
            or container.get("args") != expected.args
            or container.get("image") != binding.image
        ):
            raise ContractError("Job command/image or finite manual template differs")
        rows = container.get("env")
        if not isinstance(rows, list) or any(
            not isinstance(row, dict)
            or not isinstance(row.get("name"), str)
            or not isinstance(row.get("value"), str)
            or row.get("secretRef")
            for row in rows
        ):
            raise ContractError("Job environment must contain explicit raw values")
        environment = {row["name"]: row["value"] for row in rows}
        for row in rows:
            _closed(row, {"name", "value"}, "environment_row")
        if (
            len(environment) != len(rows)
            or set(environment) != set(expected.environment_names)
            or len(set(expected.environment_names)) != len(expected.environment_names)
            or environment.get("AZURE_CLIENT_ID", "").casefold()
            != binding.client_id.casefold()
        ):
            raise ContractError("duplicate environment or client identity mismatch")
        if role == "validation_publisher" and (
            environment.get("AIOPS_IDENTITY_CLASS") != "publisher"
            or environment.get("AIOPS_ONTOLOGY_PUBLISHER_CLIENT_ID", "").casefold()
            != binding.client_id.casefold()
        ):
            raise ContractError("publisher identity class or client binding differs")
    return {"status": "semantic_subset_verified", "authority": "none"}


def _closed(value: dict, allowed: set[str], field: str) -> None:
    if set(value) - allowed:
        raise ContractError(f"semantic_subset.{field} contains unsupported fields")


def _object(artifacts: Mapping[str, bytes], reference: ArtifactReference) -> dict:
    value = _json(artifacts[reference.key])
    if not isinstance(value, dict):
        raise ContractError("raw artifact must contain an object")
    return value
