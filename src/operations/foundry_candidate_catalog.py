"""Fail-closed projection of validated, inactive Foundry candidates."""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from operations.specialist_manifest import (
    SpecialistDefinition,
    SpecialistManifest,
    load_specialist_manifest,
    specialist_manifest_digest,
)

CANDIDATE_ARTIFACT_ENV = "AIOPS_FOUNDRY_CANDIDATE_ARTIFACT"
CANDIDATE_ARTIFACT_DIGEST_ENV = "AIOPS_FOUNDRY_CANDIDATE_ARTIFACT_DIGEST"
CANDIDATE_BINDING_DIGEST_ENV = "AIOPS_FOUNDRY_CANDIDATE_BINDING_DIGEST"
CANDIDATE_EXPECTED_NAMES_ENV = "AIOPS_FOUNDRY_CANDIDATE_EXPECTED_NAMES"
CANDIDATE_PROMPT_DIGESTS_ENV = "AIOPS_FOUNDRY_CANDIDATE_PROMPT_DIGESTS"
CANDIDATE_PROJECT_RESOURCE_ID_ENV = "AIOPS_FOUNDRY_PROJECT_RESOURCE_ID"
MODEL_DEPLOYMENT_ENV = "AIOPS_FOUNDRY_MODEL_DEPLOYMENT"
SEARCH_CONNECTION_ID_ENV = "AIOPS_FOUNDRY_AI_SEARCH_CONNECTION_ID"
SEARCH_INDEX_NAME_ENV = "AIOPS_FOUNDRY_AI_SEARCH_INDEX_NAME"
SOURCE_REVISION_ENV = "AIOPS_SOURCE_REVISION"
CANDIDATE_CONTRACT_VERSION = "foundry-specialist-candidates.v1"
CANDIDATE_BINDING_ALGORITHM = "sha256-canonical-json-candidate-v1"
REQUIRED_CHECKS = (
    "identity",
    "project",
    "model",
    "manifest",
    "prompt",
    "tool_grants",
    "scope",
    "read_only",
    "citations",
    "latency",
    "errors",
    "fallback",
)
_MAX_CLOCK_SKEW = timedelta(minutes=5)
_PROVIDER_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_CREDENTIAL_MARKERS = (
    "accesstoken",
    "apikey",
    "clientsecret",
    "connectionstring",
    "credential",
    "password",
    "privatekey",
    "secret",
    "bearer",
    "token",
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class _Project(_StrictModel):
    resource_id: str = Field(min_length=1, max_length=1024)
    endpoint_host: str = Field(
        min_length=1,
        max_length=255,
        pattern=r"^[A-Za-z0-9.-]+$",
    )


class _AISearch(_StrictModel):
    enabled: bool = Field(strict=True)
    project_connection_id: str = Field(
        min_length=1,
        max_length=1024,
        pattern=(
            r"^/subscriptions/[^/]+/resourceGroups/[^/]+/providers/"
            r"Microsoft\.CognitiveServices/accounts/[^/]+/projects/[^/]+/"
            r"connections/[^/]+$"
        ),
    )
    index_name: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
    )
    query_type: Literal["vector_semantic_hybrid"]
    cardinality: int = Field(strict=True, ge=1, le=1)

    @model_validator(mode="after")
    def validate_enabled(self) -> _AISearch:
        if self.enabled is not True:
            raise ValueError("validated Azure AI Search is required")
        return self


class _CandidateTools(_StrictModel):
    operations_mcp: tuple[str, ...] = Field(max_length=32)
    ai_search: _AISearch


class _ValidationChecks(_StrictModel):
    identity: Literal["pass"]
    project: Literal["pass"]
    model: Literal["pass"]
    manifest: Literal["pass"]
    prompt: Literal["pass"]
    tool_grants: Literal["pass"]
    scope: Literal["pass"]
    read_only: Literal["pass"]
    citations: Literal["pass"]
    latency: Literal["pass"]
    errors: Literal["pass"]
    fallback: Literal["pass"]


class _CandidateValidation(_StrictModel):
    status: Literal["pass"]
    validated_at: datetime
    checks: _ValidationChecks


class _ProviderIdentity(_StrictModel):
    agent_name: str = Field(min_length=1, max_length=160)
    provider_version_id: str = Field(min_length=1, max_length=256)
    candidate_version: str = Field(min_length=1, max_length=128)

    @field_validator("provider_version_id", mode="before")
    @classmethod
    def reject_provider_id_whitespace(cls, value: Any) -> Any:
        if isinstance(value, str) and value != value.strip():
            raise ValueError("provider_version_id must not contain outer whitespace")
        return value

    @model_validator(mode="after")
    def validate_immutable_identity(self) -> _ProviderIdentity:
        _validate_provider_identity(
            self.provider_version_id,
            agent_name=self.agent_name,
            candidate_version=self.candidate_version,
        )
        return self


class _CandidateAgent(_ProviderIdentity):
    model_deployment: str = Field(min_length=1, max_length=160)
    contract_model: str = Field(min_length=1, max_length=160)
    contract_version: str = Field(min_length=1, max_length=64)
    prompt_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    tools: _CandidateTools
    scope_policy: str = Field(min_length=1, max_length=160)
    read_only: bool = Field(strict=True)
    mutation_authorized: bool = Field(strict=True)
    citation_contract: str = Field(min_length=1, max_length=160)
    timeout_seconds: float = Field(gt=0, le=120, strict=True)
    fallback_mode: Literal["deterministic_local"]
    publication_status: Literal["published"]
    validation: _CandidateValidation

    @model_validator(mode="after")
    def validate_candidate_contract(self) -> _CandidateAgent:
        if len(self.tools.operations_mcp) != len(set(self.tools.operations_mcp)):
            raise ValueError("Operations MCP grants must be unique")
        if self.read_only is not True or self.mutation_authorized is not False:
            raise ValueError("candidate must be read-only without mutation authority")
        return self


class _CoordinatorValidation(_StrictModel):
    status: Literal["pass"]
    validated_at: datetime


class _Coordinator(_ProviderIdentity):
    publication_status: Literal["published"]
    validation: _CoordinatorValidation


class _CandidateArtifact(_StrictModel):
    contract_version: Literal["foundry-specialist-candidates.v1"]
    status: Literal["validated"]
    promotion: Literal["held"]
    reason: Literal["available_inactive"]
    release: str = Field(min_length=1, max_length=128)
    manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_revision: str = Field(pattern=r"^[0-9a-f]{7,64}$")
    generated_at: datetime
    project: _Project
    agents: dict[str, Any]
    coordinator: _Coordinator
    rollback_target: dict[str, Any]
    rollback_coordinator: dict[str, Any]

    @model_validator(mode="after")
    def validate_held_rollback_state(self) -> _CandidateArtifact:
        if self.rollback_target or self.rollback_coordinator:
            raise ValueError("held candidate catalog artifact must not select rollback")
        return self


@dataclass(frozen=True)
class CandidateArtifactBinding:
    """Stable semantic identity derived from one strict candidate artifact."""

    algorithm: str
    sha256: str
    source_revision: str


def _reject_duplicate_object_pairs(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for key, value in pairs:
        if key in values:
            raise ValueError(f"candidate artifact contains duplicate key: {key}")
        values[key] = value
    return values


def _strict_candidate_artifact(
    raw: str,
    manifest: SpecialistManifest,
) -> tuple[_CandidateArtifact, dict[str, _CandidateAgent]]:
    try:
        payload = json.loads(raw, object_pairs_hook=_reject_duplicate_object_pairs)
        artifact = _CandidateArtifact.model_validate(payload)
    except (json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise ValueError("candidate artifact is not valid strict JSON") from exc
    if set(artifact.agents) != set(manifest.specialist_ids):
        raise ValueError("candidate artifact must contain exactly the manifest agents")

    parsed_agents: dict[str, _CandidateAgent] = {}
    identities: list[tuple[str, str]] = []
    for specialist in manifest.specialists:
        try:
            candidate = _CandidateAgent.model_validate(artifact.agents[specialist.id])
        except ValidationError as exc:
            raise ValueError(
                f"candidate artifact agent is invalid: {specialist.id}"
            ) from exc
        parsed_agents[specialist.id] = candidate
        identities.append(
            _provider_identity_key(
                agent_name=candidate.agent_name,
                provider_version_id=candidate.provider_version_id,
            )
        )
    coordinator_identity = _provider_identity_key(
        agent_name=artifact.coordinator.agent_name,
        provider_version_id=artifact.coordinator.provider_version_id,
    )
    if len(identities) != len(set(identities)):
        raise ValueError("candidate artifact provider identities must be unique")
    if coordinator_identity in identities:
        raise ValueError("candidate coordinator identity must be unique")
    return artifact, parsed_agents


def candidate_artifact_binding(
    raw: str,
    manifest: SpecialistManifest,
) -> CandidateArtifactBinding:
    """Return the versioned semantic digest of a strict candidate artifact.

    The projection excludes only release-cycle metadata: the top-level source
    revision and generation time plus specialist/coordinator validation times.
    Operations MCP grants are sorted because the existing validator defines
    them as an unordered set; every other list retains its declared order.
    """

    artifact, parsed_agents = _strict_candidate_artifact(raw, manifest)
    projection = artifact.model_dump(
        mode="json",
        exclude={
            "source_revision": True,
            "generated_at": True,
            "agents": True,
            "coordinator": True,
        },
    )
    semantic_agents: dict[str, Any] = {}
    for specialist in manifest.specialists:
        candidate = parsed_agents[specialist.id]
        semantic_agents[specialist.id] = {
            **candidate.model_dump(
                mode="json",
                exclude={"validation": {"validated_at"}},
            ),
            "tools": {
                **candidate.tools.model_dump(mode="json"),
                "operations_mcp": sorted(candidate.tools.operations_mcp),
            },
        }
    projection["agents"] = semantic_agents
    projection["coordinator"] = artifact.coordinator.model_dump(
        mode="json",
        exclude={"validation": {"validated_at"}},
    )
    canonical = json.dumps(
        {
            "algorithm": CANDIDATE_BINDING_ALGORITHM,
            "candidate": projection,
        },
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return CandidateArtifactBinding(
        algorithm=CANDIDATE_BINDING_ALGORITHM,
        sha256=sha256(canonical).hexdigest(),
        source_revision=artifact.source_revision,
    )


def main(argv: list[str] | None = None) -> int:
    """Print transport and semantic digests for one strict candidate artifact."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", required=True, type=Path)
    args = parser.parse_args(argv)
    raw_bytes = args.artifact.read_bytes()
    raw = raw_bytes.decode("utf-8")
    binding = candidate_artifact_binding(raw, load_specialist_manifest())
    print(
        json.dumps(
            {
                "transport_sha256": sha256(raw_bytes).hexdigest(),
                "semantic_algorithm": binding.algorithm,
                "semantic_sha256": binding.sha256,
                "source_revision": binding.source_revision,
            },
            sort_keys=True,
        )
    )
    return 0


def _validate_provider_identity(
    provider_version_id: str,
    *,
    agent_name: str,
    candidate_version: str,
) -> None:
    normalized = _validated_provider_id(provider_version_id).casefold()
    if normalized in {
        "latest",
        agent_name.casefold(),
        candidate_version.casefold(),
    }:
        raise ValueError("provider_version_id must be immutable provider identity")


def _validated_provider_id(value: Any) -> str:
    if not isinstance(value, str) or value != value.strip():
        raise ValueError("provider_version_id must not contain outer whitespace")
    if _PROVIDER_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("provider_version_id syntax is invalid")
    compact = re.sub(r"[._:-]+", "", value.casefold())
    if any(marker in compact for marker in _CREDENTIAL_MARKERS):
        raise ValueError("provider_version_id must not contain credential markers")
    return value


def _provider_identity_key(
    *,
    agent_name: Any,
    provider_version_id: Any,
) -> tuple[str, str]:
    if not isinstance(agent_name, str) or not agent_name.strip():
        raise ValueError("agent_name must identify the provider identity owner")
    return (
        agent_name.strip().casefold(),
        _validated_provider_id(provider_version_id).casefold(),
    )


def _expected_names() -> dict[str, str] | None:
    return _string_mapping(CANDIDATE_EXPECTED_NAMES_ENV)


def _string_mapping(environment_name: str) -> dict[str, str] | None:
    raw = os.environ.get(environment_name, "").strip()
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or not all(
        isinstance(key, str) and isinstance(value, str) and value.strip()
        for key, value in payload.items()
    ):
        return None
    return {key: value.strip() for key, value in payload.items()}


def _agent_matches_manifest(
    candidate: _CandidateAgent,
    specialist: SpecialistDefinition,
    *,
    release: str,
    expected_name: str,
    expected_model_deployment: str,
    expected_prompt_digest: str,
    expected_search_connection_id: str,
    expected_search_index_name: str,
    generated_at: datetime,
    now: datetime,
) -> bool:
    validated_at = candidate.validation.validated_at
    if validated_at.tzinfo is None:
        return False
    if validated_at < generated_at or validated_at > now + _MAX_CLOCK_SKEW:
        return False
    return (
        candidate.agent_name == expected_name
        and candidate.model_deployment == expected_model_deployment
        and candidate.candidate_version == f"{release}.{specialist.foundry.version}"
        and candidate.contract_model == specialist.foundry.model
        and candidate.contract_version == specialist.foundry.version
        and candidate.prompt_digest == expected_prompt_digest
        and set(candidate.tools.operations_mcp)
        == set(specialist.operations_mcp_tools)
        and candidate.tools.ai_search.project_connection_id
        == expected_search_connection_id
        and candidate.tools.ai_search.index_name == expected_search_index_name
    )


def validated_candidate_catalog(
    manifest: SpecialistManifest,
    *,
    now: datetime | None = None,
) -> dict[str, dict[str, Any]]:
    """Return only candidate rows that pass the complete inactive contract."""

    raw = os.environ.get(CANDIDATE_ARTIFACT_ENV, "")
    expected_artifact_digest = os.environ.get(
        CANDIDATE_ARTIFACT_DIGEST_ENV,
        "",
    ).strip()
    expected_revision = os.environ.get(SOURCE_REVISION_ENV, "").strip().casefold()
    expected_project_id = os.environ.get(
        CANDIDATE_PROJECT_RESOURCE_ID_ENV,
        "",
    ).strip()
    expected_endpoint = os.environ.get("FOUNDRY_PROJECT_ENDPOINT", "").strip()
    expected_model_deployment = os.environ.get(
        MODEL_DEPLOYMENT_ENV,
        "",
    ).strip()
    expected_coordinator_name = os.environ.get(
        "FOUNDRY_AGENT_NAME",
        "",
    ).strip()
    expected_search_connection_id = os.environ.get(
        SEARCH_CONNECTION_ID_ENV,
        "",
    ).strip()
    expected_search_index_name = os.environ.get(
        SEARCH_INDEX_NAME_ENV,
        "",
    ).strip()
    expected_names = _expected_names()
    expected_prompt_digests = _string_mapping(CANDIDATE_PROMPT_DIGESTS_ENV)
    if (
        not raw.strip()
        or not expected_artifact_digest
        or not expected_revision
        or not expected_project_id
        or not expected_endpoint
        or not expected_model_deployment
        or not expected_coordinator_name
        or not expected_search_connection_id
        or not expected_search_index_name
        or expected_names is None
        or expected_prompt_digests is None
    ):
        return {}
    if sha256(raw.encode("utf-8")).hexdigest() != expected_artifact_digest:
        return {}
    try:
        payload = json.loads(raw)
        artifact = _CandidateArtifact.model_validate(payload)
    except (json.JSONDecodeError, ValidationError):
        return {}

    moment = now or datetime.now(UTC)
    generated_at = artifact.generated_at
    if generated_at.tzinfo is None or generated_at > moment + _MAX_CLOCK_SKEW:
        return {}
    coordinator_validated_at = artifact.coordinator.validation.validated_at
    if (
        coordinator_validated_at.tzinfo is None
        or coordinator_validated_at < generated_at
        or coordinator_validated_at > moment + _MAX_CLOCK_SKEW
        or artifact.coordinator.agent_name != expected_coordinator_name
        or artifact.coordinator.candidate_version
        != f"{artifact.release}.coordinator"
    ):
        return {}
    if artifact.manifest_digest != specialist_manifest_digest():
        return {}
    if artifact.source_revision.casefold() != expected_revision:
        return {}
    if artifact.project.resource_id != expected_project_id:
        return {}
    if artifact.project.endpoint_host != (urlsplit(expected_endpoint).hostname or ""):
        return {}
    if set(artifact.agents) != set(manifest.specialist_ids):
        return {}
    if set(expected_names) != set(manifest.specialist_ids):
        return {}
    if set(expected_prompt_digests) != set(manifest.specialist_ids):
        return {}

    declared_provider_identities: dict[str, tuple[str, str]] = {}
    for specialist in manifest.specialists:
        raw_candidate = artifact.agents[specialist.id]
        if not isinstance(raw_candidate, dict):
            continue
        try:
            declared_provider_identities[specialist.id] = _provider_identity_key(
                agent_name=raw_candidate.get("agent_name"),
                provider_version_id=raw_candidate.get("provider_version_id"),
            )
        except ValueError:
            continue

    provider_identity_counts = Counter(declared_provider_identities.values())
    duplicate_provider_identities = {
        identity
        for identity, count in provider_identity_counts.items()
        if count > 1
    }
    if duplicate_provider_identities:
        return {}
    coordinator_identity = _provider_identity_key(
        agent_name=artifact.coordinator.agent_name,
        provider_version_id=artifact.coordinator.provider_version_id,
    )
    if coordinator_identity in provider_identity_counts:
        return {}
    expected_identity_names = [
        *(name.casefold() for name in expected_names.values()),
        expected_coordinator_name.casefold(),
    ]
    if len(expected_identity_names) != len(set(expected_identity_names)):
        return {}

    parsed_agents: dict[str, _CandidateAgent] = {}
    for specialist in manifest.specialists:
        try:
            candidate = _CandidateAgent.model_validate(
                artifact.agents[specialist.id]
            )
        except ValidationError:
            continue
        parsed_agents[specialist.id] = candidate

    validated_agents: dict[str, _CandidateAgent] = {}
    for specialist in manifest.specialists:
        candidate = parsed_agents.get(specialist.id)
        if candidate is None:
            continue
        if _agent_matches_manifest(
            candidate,
            specialist,
            release=artifact.release,
            expected_name=expected_names[specialist.id],
            expected_model_deployment=expected_model_deployment,
            expected_prompt_digest=expected_prompt_digests[specialist.id],
            expected_search_connection_id=expected_search_connection_id,
            expected_search_index_name=expected_search_index_name,
            generated_at=generated_at,
            now=moment,
        ):
            validated_agents[specialist.id] = candidate

    rows: dict[str, dict[str, Any]] = {}
    for specialist in manifest.specialists:
        candidate = validated_agents.get(specialist.id)
        if candidate is None:
            continue
        rows[specialist.id] = {
            "name": candidate.agent_name,
            "provider_version_id": candidate.provider_version_id,
            "candidate_version": candidate.candidate_version,
            "validated_at": candidate.validation.validated_at.isoformat(),
            "source": "validated_candidate_artifact",
            "source_revision": artifact.source_revision,
            "release": artifact.release,
        }
    return rows


__all__ = [
    "CANDIDATE_ARTIFACT_DIGEST_ENV",
    "CANDIDATE_ARTIFACT_ENV",
    "CANDIDATE_BINDING_ALGORITHM",
    "CANDIDATE_BINDING_DIGEST_ENV",
    "CANDIDATE_CONTRACT_VERSION",
    "CANDIDATE_EXPECTED_NAMES_ENV",
    "CANDIDATE_PROJECT_RESOURCE_ID_ENV",
    "CANDIDATE_PROMPT_DIGESTS_ENV",
    "MODEL_DEPLOYMENT_ENV",
    "REQUIRED_CHECKS",
    "SEARCH_CONNECTION_ID_ENV",
    "SEARCH_INDEX_NAME_ENV",
    "SOURCE_REVISION_ENV",
    "CandidateArtifactBinding",
    "candidate_artifact_binding",
    "main",
    "validated_candidate_catalog",
]


if __name__ == "__main__":
    raise SystemExit(main())
