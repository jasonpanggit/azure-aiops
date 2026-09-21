"""Code-bound authorization for the bounded Operations Copilot canary."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from operations.foundry_candidate_catalog import (
    CANDIDATE_ARTIFACT_DIGEST_ENV,
    CANDIDATE_ARTIFACT_ENV,
    CANDIDATE_BINDING_ALGORITHM,
    CANDIDATE_BINDING_DIGEST_ENV,
    candidate_artifact_binding,
)
from operations.reviewed_tree import (
    REVIEWED_TREE_ALGORITHM,
    REVIEWED_TREE_EXCLUDED_PATHS,
    REVIEWED_TREE_ROOTS,
    ReviewedTreeError,
    reviewed_tree_digest,
)
from operations.specialist_manifest import load_specialist_manifest

AUTHORIZATION_MANIFEST_PATH = Path(__file__).with_name(
    "copilot_canary_authorization.v1.json"
)
DEFAULT_AUTHORIZATION_MANIFEST_PATH = Path(__file__).with_name(
    "copilot_default_authorization.v1.json"
)
CANARY_VALIDATION_REPORT_PATH = Path(__file__).with_name(
    "copilot_canary_validation_report.v1.json"
)
DEFAULT_AUTHORIZATION_DESIGN_APPROVAL_PATH = Path(__file__).with_name(
    "copilot_default_authorization_design_approval.v1.json"
)
BUILD_METADATA_PATH = Path("/app/build-metadata.json")
PACKAGED_REVIEWED_TREE_ROOT = Path("/app")
ENV_ROLLOUT_MODE = "AIOPS_COPILOT_ROLLOUT_MODE"
ENV_CANARY_PERCENTAGE = "AIOPS_COPILOT_CANARY_PERCENTAGE"
ENV_SOURCE_REVISION = "AIOPS_SOURCE_REVISION"
ENV_AUTHORIZATION_MANIFEST_SHA256 = "AIOPS_CANARY_AUTHORIZATION_MANIFEST_SHA256"
ENV_DEFAULT_AUTHORIZATION_MANIFEST_SHA256 = (
    "AIOPS_DEFAULT_AUTHORIZATION_MANIFEST_SHA256"
)

_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_REVISION_PATTERN = r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$"
_DEFAULT_AUTHORIZATION_DESIGN_APPROVAL_SHA256 = (
    "183ed181a31e6943d81f172e18a8a8dbd5b1e3609208be31c51c2f356f0b24e2"
)
_CANONICAL_UTC_PATTERN = re.compile(
    r"^\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])"
    r"T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\dZ$"
)
_EXPECTED_AGENTS = {
    "change": ("aiops-change-agent", "17"),
    "executive_summary": ("aiops-executive-summary-agent", "16"),
    "finops": ("aiops-finops-agent", "1"),
    "governance": ("aiops-governance-agent", "17"),
    "identity_access": ("aiops-identity-access-agent", "1"),
    "incident": ("aiops-incident-agent", "16"),
    "inventory_data_health": ("aiops-inventory-data-health-agent", "1"),
    "network": ("aiops-network-agent", "16"),
    "patch": ("aiops-patch-agent", "17"),
    "remediation": ("aiops-remediation-agent", "17"),
    "resource_health_observability": (
        "aiops-resource-health-observability-agent",
        "1",
    ),
    "vulnerability": ("aiops-vulnerability-agent", "17"),
}
_EXPECTED_ENVIRONMENT = {
    "AIOPS_DEPLOYMENT_TENANT_ID": "ffc83107-fcc0-4d2e-8798-d582da36505e",
    "AIOPS_DEPLOYMENT_SUBSCRIPTION_ID": "a87a8e64-a52a-4aa8-a760-5e8919d23cd1",
    "AIOPS_DEPLOYMENT_RESOURCE_GROUP": "aiops-dev-rg",
    "AIOPS_DEPLOYMENT_APP": "aiops-dev-api",
    "AIOPS_DEPLOYMENT_ENVIRONMENT": "dev",
    "AIOPS_DEPLOYMENT_REGION": "australiaeast",
    "AIOPS_FOUNDRY_PROJECT_RESOURCE_ID": (
        "/subscriptions/a87a8e64-a52a-4aa8-a760-5e8919d23cd1/"
        "resourceGroups/aiops-dev-rg/providers/Microsoft.CognitiveServices/"
        "accounts/aiops-dev-foundry/projects/aiops-dev-ops"
    ),
    "AIOPS_FOUNDRY_PROJECT_NAME": "aiops-dev-ops",
    "AIOPS_FOUNDRY_ACCOUNT_ENDPOINT": (
        "https://aiops-dev-ai-g6ludc.services.ai.azure.com"
    ),
    "FOUNDRY_PROJECT_ENDPOINT": (
        "https://aiops-dev-ai-g6ludc.services.ai.azure.com/api/projects/aiops-dev-ops"
    ),
    "AIOPS_SPECIALIST_ACTIVATION_SOURCE": "validated_promotion",
    "AIOPS_AGENT_ORCHESTRATION_MODE": "maf",
    "AIOPS_COPILOT_ROLLBACK_MODE": "compatibility",
    "AIOPS_COPILOT_CANDIDATE_RELEASE": ("p11-noazmcp-20260920T093238Z-c562f00e33d7"),
    "AIOPS_COPILOT_CANDIDATE_CONTRACT_VERSION": ("foundry-specialist-candidates.v1"),
    "AIOPS_COPILOT_CANDIDATE_MANIFEST_SHA256": (
        "fbfc29fe93006c1a5d3bd035519bd04fd0bbd31e7086405b25b3db4f5dae3571"
    ),
    CANDIDATE_BINDING_DIGEST_ENV: (
        "c3b08c9dfdd6716476675c90457b6289f815fa8166baa29b7e92950fd217a4c4"
    ),
    "AIOPS_COPILOT_PARSER_PROOF_SHA256": (
        "929c0e067f3dd39c1a1edfe249d30c39cf9cff4102d777f8a9eab8383ec84132"
    ),
    "AIOPS_COPILOT_SERIALIZATION_PROOF_SHA256": (
        "cd92422b4d2d4c29913f32a103c6d3ae300d084de46fc00079c24063f801ea60"
    ),
    "AIOPS_COPILOT_SHADOW_REVISION": "aiops-dev-api--shadow-10af2ff5-r1",
    "AIOPS_COPILOT_SHADOW_IMAGE_DIGEST": (
        "sha256:b58399d0c41c7dbbf995dfb13fbc76380c2c90e91a21a9f37afe1c0ace406aa2"
    ),
    "AIOPS_COPILOT_SHADOW_REPORT_SHA256": (
        "8c9adc6377219adcf69401177eda11e7a718484d9137e27832502bd15f4810a2"
    ),
    "AIOPS_COPILOT_SHADOW_REPORT_INTEGRITY_SIGNATURE": (
        "9da29b506520c8724f12cdfeb04738ae255733dec395c1c3520ca4aa613886dc"
    ),
    "AIOPS_COPILOT_SHADOW_MATRIX_SHA256": (
        "1a8dbd72cdb30acd922c7ff01de45d7c2c2cca5b1c1a0f324fe53de429a2e896"
    ),
    "AIOPS_COPILOT_SHADOW_STATUS": "PASS",
}


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


class Issuer(_StrictModel):
    """Reviewed identity that issued the authorization."""

    name: Literal["azure-aiops-release-review"]
    role: Literal[
        "canary-authorization-reviewer",
        "default-authorization-reviewer",
    ]


class ReviewProvenance(_StrictModel):
    """Immutable repository evidence reviewed before authorization."""

    repository: Literal["https://github.com/jasonpanggit/azure-aiops"]
    evidence_commit: str = Field(pattern=_REVISION_PATTERN)


class ReviewedTree(_StrictModel):
    """Deterministic source/build file set approved by the reviewer."""

    algorithm: Literal["sha256-path-length-content-v1"]
    include_roots: tuple[str, ...]
    exclude_paths: tuple[str, ...]
    sha256: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_file_set(self) -> ReviewedTree:
        if (
            self.include_roots != REVIEWED_TREE_ROOTS
            or self.exclude_paths != REVIEWED_TREE_EXCLUDED_PATHS
        ):
            raise ValueError("reviewed tree definition differs from the fixed set")
        return self


class AuthorizationScope(_StrictModel):
    """Only rollout state that the reviewed record may authorize."""

    allowed_modes: tuple[str, ...]
    minimum_percentage: int = Field(strict=True)
    maximum_percentage: int = Field(strict=True)
    default_authorized: bool = Field(strict=True)
    activation_source: str
    orchestration: str
    rollback_mode: str

    @model_validator(mode="after")
    def validate_exact_scope(self) -> AuthorizationScope:
        if self.allowed_modes != ("canary",):
            raise ValueError("allowed_modes must be exactly ['canary']")
        if (
            self.minimum_percentage != 1
            or self.maximum_percentage != 10
            or self.default_authorized is not False
            or self.activation_source != "validated_promotion"
            or self.orchestration != "maf"
            or self.rollback_mode != "compatibility"
        ):
            raise ValueError("authorization scope differs from the reviewed boundary")
        return self


class DefaultAuthorizationScope(_StrictModel):
    """Only full canonical rollout state covered by default authority."""

    allowed_modes: tuple[str, ...]
    percentage: int = Field(strict=True)
    default_authorized: bool = Field(strict=True)
    activation_source: str
    orchestration: str
    rollback_mode: str

    @model_validator(mode="after")
    def validate_exact_scope(self) -> DefaultAuthorizationScope:
        if self.allowed_modes != ("default",):
            raise ValueError("allowed_modes must be exactly ['default']")
        if (
            self.percentage != 100
            or self.default_authorized is not True
            or self.activation_source != "validated_promotion"
            or self.orchestration != "maf"
            or self.rollback_mode != "compatibility"
        ):
            raise ValueError(
                "default authorization scope differs from the reviewed boundary"
            )
        return self


class DeploymentTarget(_StrictModel):
    """Exact Azure deployment boundary covered by the authorization."""

    tenant_id: str
    subscription_id: str
    resource_group: str
    app: str
    environment: str
    region: str


class FoundryProject(_StrictModel):
    """Exact Microsoft Foundry project boundary covered by the authorization."""

    resource_id: str
    name: str
    endpoint: str


class CandidateAgent(_StrictModel):
    """One immutable specialist provider identity."""

    id: str
    agent_name: str
    provider_version: str


class Coordinator(_StrictModel):
    """Immutable shared coordinator provider identity."""

    agent_name: str
    provider_version: str


class CandidateBinding(_StrictModel):
    """Exact candidate and proof digests reviewed for activation."""

    release: str
    contract_version: str
    manifest_sha256: str = Field(pattern=_SHA256_PATTERN)
    semantic_algorithm: Literal["sha256-canonical-json-candidate-v1"]
    semantic_sha256: str = Field(pattern=_SHA256_PATTERN)
    parser_proof_sha256: str = Field(pattern=_SHA256_PATTERN)
    serialization_proof_sha256: str = Field(pattern=_SHA256_PATTERN)
    agents: tuple[CandidateAgent, ...]
    coordinator: Coordinator

    @model_validator(mode="after")
    def validate_exact_identities(self) -> CandidateBinding:
        counts = Counter(agent.id for agent in self.agents)
        duplicates = sorted(key for key, count in counts.items() if count != 1)
        if duplicates:
            raise ValueError(f"candidate agent ids must be unique: {duplicates}")
        actual = {
            agent.id: (agent.agent_name, agent.provider_version)
            for agent in self.agents
        }
        if actual != _EXPECTED_AGENTS:
            raise ValueError("candidate agents must exactly match reviewed identities")
        if self.coordinator != Coordinator(
            agent_name="operations-copilot",
            provider_version="6",
        ):
            raise ValueError("coordinator must exactly match reviewed identity")
        return self


class ShadowEvidence(_StrictModel):
    """Immutable passing shadow-run evidence required by the canary."""

    revision: str
    image_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    report_sha256: str = Field(pattern=_SHA256_PATTERN)
    report_integrity_signature: str = Field(pattern=_SHA256_PATTERN)
    matrix_sha256: str = Field(pattern=_SHA256_PATTERN)
    shadow_status: str


class CleanCanaryEvidence(_StrictModel):
    """Passing, cleaned canary evidence required before default rollout."""

    report_sha256: str = Field(pattern=_SHA256_PATTERN)
    report_integrity_signature: str = Field(pattern=_SHA256_PATTERN)
    status: Literal["PASS_CLEAN"]
    tested_percentage: Literal[10]
    source_revision: str = Field(pattern=_REVISION_PATTERN)
    image_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    reviewed_tree_sha256: str = Field(pattern=_SHA256_PATTERN)
    cleanup_status: Literal["PASS_COMPLETE"]


class CanaryAuthorizationManifest(_StrictModel):
    """Strict packaged record authorizing one bounded canary window."""

    schema_version: Literal["copilot-canary-authorization.v1"]
    authorization_id: str = Field(min_length=1, max_length=128)
    status: str
    issued_at: datetime
    not_before: datetime
    expires_at: datetime
    issuer: Issuer
    review_provenance: ReviewProvenance
    reviewed_tree: ReviewedTree
    authorization_scope: AuthorizationScope
    deployment_target: DeploymentTarget
    foundry_project: FoundryProject
    candidate_binding: CandidateBinding
    shadow_evidence: ShadowEvidence

    @field_validator("issued_at", "not_before", "expires_at", mode="before")
    @classmethod
    def validate_canonical_utc_timestamp(cls, value: Any) -> str:
        if not isinstance(value, str) or _CANONICAL_UTC_PATTERN.fullmatch(value) is None:
            raise ValueError("timestamp must be canonical RFC3339 UTC")
        return value

    @model_validator(mode="after")
    def validate_reviewed_values(self) -> CanaryAuthorizationManifest:
        if self.status != "AUTHORIZED":
            raise ValueError("authorization status is inactive")
        if self.issuer.role != "canary-authorization-reviewer":
            raise ValueError("canary authorization issuer role is invalid")
        for name, value in (
            ("issued_at", self.issued_at),
            ("not_before", self.not_before),
            ("expires_at", self.expires_at),
        ):
            if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
                raise ValueError(f"{name} must be UTC")
        if not self.issued_at <= self.not_before < self.expires_at:
            raise ValueError("authorization window is invalid")
        expected_target = DeploymentTarget(
            tenant_id=_EXPECTED_ENVIRONMENT["AIOPS_DEPLOYMENT_TENANT_ID"],
            subscription_id=_EXPECTED_ENVIRONMENT["AIOPS_DEPLOYMENT_SUBSCRIPTION_ID"],
            resource_group=_EXPECTED_ENVIRONMENT["AIOPS_DEPLOYMENT_RESOURCE_GROUP"],
            app=_EXPECTED_ENVIRONMENT["AIOPS_DEPLOYMENT_APP"],
            environment=_EXPECTED_ENVIRONMENT["AIOPS_DEPLOYMENT_ENVIRONMENT"],
            region=_EXPECTED_ENVIRONMENT["AIOPS_DEPLOYMENT_REGION"],
        )
        expected_project = FoundryProject(
            resource_id=_EXPECTED_ENVIRONMENT["AIOPS_FOUNDRY_PROJECT_RESOURCE_ID"],
            name=_EXPECTED_ENVIRONMENT["AIOPS_FOUNDRY_PROJECT_NAME"],
            endpoint=_EXPECTED_ENVIRONMENT["AIOPS_FOUNDRY_ACCOUNT_ENDPOINT"],
        )
        if self.deployment_target != expected_target:
            raise ValueError("deployment target differs from reviewed target")
        if self.foundry_project != expected_project:
            raise ValueError("Foundry project differs from reviewed target")
        expected_binding = {
            "release": _EXPECTED_ENVIRONMENT["AIOPS_COPILOT_CANDIDATE_RELEASE"],
            "contract_version": _EXPECTED_ENVIRONMENT[
                "AIOPS_COPILOT_CANDIDATE_CONTRACT_VERSION"
            ],
            "manifest_sha256": _EXPECTED_ENVIRONMENT[
                "AIOPS_COPILOT_CANDIDATE_MANIFEST_SHA256"
            ],
            "semantic_algorithm": CANDIDATE_BINDING_ALGORITHM,
            "semantic_sha256": _EXPECTED_ENVIRONMENT[CANDIDATE_BINDING_DIGEST_ENV],
            "parser_proof_sha256": _EXPECTED_ENVIRONMENT[
                "AIOPS_COPILOT_PARSER_PROOF_SHA256"
            ],
            "serialization_proof_sha256": _EXPECTED_ENVIRONMENT[
                "AIOPS_COPILOT_SERIALIZATION_PROOF_SHA256"
            ],
        }
        if any(
            getattr(self.candidate_binding, key) != value
            for key, value in expected_binding.items()
        ):
            raise ValueError("candidate binding differs from reviewed evidence")
        expected_shadow = {
            "revision": _EXPECTED_ENVIRONMENT["AIOPS_COPILOT_SHADOW_REVISION"],
            "image_digest": _EXPECTED_ENVIRONMENT["AIOPS_COPILOT_SHADOW_IMAGE_DIGEST"],
            "report_sha256": _EXPECTED_ENVIRONMENT[
                "AIOPS_COPILOT_SHADOW_REPORT_SHA256"
            ],
            "report_integrity_signature": _EXPECTED_ENVIRONMENT[
                "AIOPS_COPILOT_SHADOW_REPORT_INTEGRITY_SIGNATURE"
            ],
            "matrix_sha256": _EXPECTED_ENVIRONMENT[
                "AIOPS_COPILOT_SHADOW_MATRIX_SHA256"
            ],
            "shadow_status": _EXPECTED_ENVIRONMENT["AIOPS_COPILOT_SHADOW_STATUS"],
        }
        actual_shadow = self.shadow_evidence.model_dump(mode="json")
        if any(
            actual_shadow.get(key) != value for key, value in expected_shadow.items()
        ):
            raise ValueError("shadow evidence differs from reviewed evidence")
        return self


class DefaultAuthorizationManifest(_StrictModel):
    """Strict packaged record authorizing one full canonical rollout."""

    schema_version: Literal["copilot-default-authorization.v1"]
    authorization_id: str = Field(min_length=1, max_length=128)
    status: Literal["AUTHORIZED", "HOLD_PENDING_CANARY_REVALIDATION"]
    design_approval_sha256: str = Field(pattern=_SHA256_PATTERN)
    issued_at: datetime
    not_before: datetime
    expires_at: datetime
    issuer: Issuer
    review_provenance: ReviewProvenance
    reviewed_tree: ReviewedTree
    authorization_scope: DefaultAuthorizationScope
    deployment_target: DeploymentTarget
    foundry_project: FoundryProject
    candidate_binding: CandidateBinding
    canary_evidence: CleanCanaryEvidence

    @field_validator("issued_at", "not_before", "expires_at", mode="before")
    @classmethod
    def validate_canonical_utc_timestamp(cls, value: Any) -> str:
        if not isinstance(value, str) or _CANONICAL_UTC_PATTERN.fullmatch(value) is None:
            raise ValueError("timestamp must be canonical RFC3339 UTC")
        return value

    @model_validator(mode="after")
    def validate_reviewed_values(self) -> DefaultAuthorizationManifest:
        if self.issuer.role != "default-authorization-reviewer":
            raise ValueError("default authorization issuer role is invalid")
        for name, value in (
            ("issued_at", self.issued_at),
            ("not_before", self.not_before),
            ("expires_at", self.expires_at),
        ):
            if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
                raise ValueError(f"{name} must be UTC")
        if not self.issued_at <= self.not_before < self.expires_at:
            raise ValueError("authorization window is invalid")
        expected_target = DeploymentTarget(
            tenant_id=_EXPECTED_ENVIRONMENT["AIOPS_DEPLOYMENT_TENANT_ID"],
            subscription_id=_EXPECTED_ENVIRONMENT[
                "AIOPS_DEPLOYMENT_SUBSCRIPTION_ID"
            ],
            resource_group=_EXPECTED_ENVIRONMENT[
                "AIOPS_DEPLOYMENT_RESOURCE_GROUP"
            ],
            app=_EXPECTED_ENVIRONMENT["AIOPS_DEPLOYMENT_APP"],
            environment=_EXPECTED_ENVIRONMENT["AIOPS_DEPLOYMENT_ENVIRONMENT"],
            region=_EXPECTED_ENVIRONMENT["AIOPS_DEPLOYMENT_REGION"],
        )
        expected_project = FoundryProject(
            resource_id=_EXPECTED_ENVIRONMENT["AIOPS_FOUNDRY_PROJECT_RESOURCE_ID"],
            name=_EXPECTED_ENVIRONMENT["AIOPS_FOUNDRY_PROJECT_NAME"],
            endpoint=_EXPECTED_ENVIRONMENT["AIOPS_FOUNDRY_ACCOUNT_ENDPOINT"],
        )
        if self.deployment_target != expected_target:
            raise ValueError("deployment target differs from reviewed target")
        if self.foundry_project != expected_project:
            raise ValueError("Foundry project differs from reviewed target")
        expected_binding = {
            "release": _EXPECTED_ENVIRONMENT["AIOPS_COPILOT_CANDIDATE_RELEASE"],
            "contract_version": _EXPECTED_ENVIRONMENT[
                "AIOPS_COPILOT_CANDIDATE_CONTRACT_VERSION"
            ],
            "manifest_sha256": _EXPECTED_ENVIRONMENT[
                "AIOPS_COPILOT_CANDIDATE_MANIFEST_SHA256"
            ],
            "semantic_algorithm": CANDIDATE_BINDING_ALGORITHM,
            "semantic_sha256": _EXPECTED_ENVIRONMENT[CANDIDATE_BINDING_DIGEST_ENV],
        }
        if any(
            getattr(self.candidate_binding, key) != value
            for key, value in expected_binding.items()
        ):
            raise ValueError("candidate binding differs from reviewed evidence")
        if (
            self.status == "AUTHORIZED"
            and self.canary_evidence.reviewed_tree_sha256
            != self.reviewed_tree.sha256
        ):
            raise ValueError(
                "authorized default requires clean canary evidence for this tree"
            )
        return self


class BuildMetadata(_StrictModel):
    """Immutable metadata generated inside the production image build."""

    schema_version: Literal["copilot-build-metadata.v1"]
    source_revision: str = Field(pattern=_REVISION_PATTERN)
    canary_authorization_manifest_sha256: str = Field(pattern=_SHA256_PATTERN)
    default_authorization_manifest_sha256: str = Field(pattern=_SHA256_PATTERN)
    canary_validation_report_sha256: str = Field(pattern=_SHA256_PATTERN)
    default_authorization_design_approval_sha256: str = Field(
        pattern=_SHA256_PATTERN
    )
    reviewed_tree_sha256: str = Field(pattern=_SHA256_PATTERN)


@dataclass(frozen=True)
class ValidatedCanaryAuthorization:
    """Immutable server-held authorization state returned after code checks."""

    authorization_id: str
    mode: Literal["canary", "default"]
    manifest_sha256: str
    source_revision: str
    reviewed_tree_sha256: str
    percentage: int
    expires_at: datetime


class CanaryAuthorizationError(ValueError):
    """Raised before provider or external execution when rollout authority fails."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"Copilot rollout authorization denied: {reason}")


def _utc_now() -> datetime:
    return datetime.now(UTC)


def canary_authorization_required(
    environment: Mapping[str, str] | None = None,
) -> bool:
    """Return whether requested rollout settings require reviewed authority."""

    values = environment if environment is not None else os.environ
    mode = values.get(ENV_ROLLOUT_MODE, "").strip().casefold()
    percentage_text = values.get(ENV_CANARY_PERCENTAGE, "").strip()
    percentage = int(percentage_text) if percentage_text.isdecimal() else 0
    return mode in {"canary", "default"} or percentage > 0


def _canonical_artifact_integrity(payload: dict[str, Any]) -> str:
    signature = payload.get("integrity_signature")
    if not isinstance(signature, dict) or signature.get("algorithm") != "sha256":
        raise ValueError("artifact integrity signature is invalid")
    unsigned = dict(payload)
    unsigned.pop("integrity_signature")
    actual = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if signature.get("value") != actual:
        raise ValueError("artifact integrity signature does not match")
    return actual


def _validate_default_evidence_artifacts(
    *,
    manifest: DefaultAuthorizationManifest,
    build_metadata: BuildMetadata,
    report_path: Path,
    design_approval_path: Path,
) -> None:
    try:
        report_bytes = report_path.read_bytes()
        report = json.loads(report_bytes)
        approval_bytes = design_approval_path.read_bytes()
        approval = json.loads(approval_bytes)
        if not isinstance(report, dict) or not isinstance(approval, dict):
            raise TypeError("authorization evidence artifacts must be objects")
        _canonical_artifact_integrity(report)
        _canonical_artifact_integrity(approval)

        report_sha256 = hashlib.sha256(report_bytes).hexdigest()
        approval_sha256 = hashlib.sha256(approval_bytes).hexdigest()
        evidence = manifest.canary_evidence
        report_authorization = report["authorization"]
        report_bindings = report["bindings"]
        serving_revision = report["serving_revision"]
        cleanup = report["operational_cleanup"]
        execution_equivalence = report["execution_evidence_equivalence"]
        approval_contract = approval["manifest_contract"]
        approval_evidence = approval_contract["canary_evidence"]
        approval_tree = approval["reviewed_tree_contract"]

        if (
            report_sha256 != evidence.report_sha256
            or build_metadata.canary_validation_report_sha256 != report_sha256
            or report["integrity_signature"]["value"]
            != evidence.report_integrity_signature
            or report.get("schema_version")
            != "foundry-canary-validation-report.v1"
            or report.get("status") != "PASS_CLEAN"
            or report.get("canary_status") != "PASS"
            or report.get("canary_authorized") is not True
            or report_authorization.get("rollout_mode") != "canary"
            or report_authorization.get("percentage") != evidence.tested_percentage
            or report.get("source_revision") != evidence.source_revision
            or serving_revision.get("image_digest") != evidence.image_digest
            or serving_revision.get("active") is not True
            or serving_revision.get("health_state") != "Healthy"
            or serving_revision.get("latest") is not True
            or serving_revision.get("latest_ready") is not True
            or serving_revision.get("replica_ready") is not True
            or cleanup.get("status") != evidence.cleanup_status
            or not execution_equivalence
            or not all(value is True for value in execution_equivalence.values())
            or report_bindings.get("candidate_semantic_sha256")
            != manifest.candidate_binding.semantic_sha256
        ):
            raise ValueError(
                "clean canary evidence differs from the platform-observed report"
            )

        if (
            approval_sha256 != _DEFAULT_AUTHORIZATION_DESIGN_APPROVAL_SHA256
            or manifest.design_approval_sha256
            != _DEFAULT_AUTHORIZATION_DESIGN_APPROVAL_SHA256
            or build_metadata.default_authorization_design_approval_sha256
            != approval_sha256
            or approval.get("schema_version")
            != "foundry-default-authorization-design-approval.v1"
            or approval.get("decision") != "APPROVE_FOR_IMPLEMENTATION"
            or approval.get("default_authorized") is not False
            or approval_contract.get("schema_version")
            != manifest.schema_version
            or approval_contract.get("path")
            != "src/operations/copilot_default_authorization.v1.json"
            or approval_evidence.get("clean_report_sha256")
            != evidence.report_sha256
            or approval_evidence.get("clean_report_signature")
            != evidence.report_integrity_signature
            or approval_evidence.get("status") != evidence.status
            or approval_evidence.get("tested_percentage")
            != evidence.tested_percentage
            or approval_evidence.get("source_revision")
            != evidence.source_revision
            or approval_evidence.get("image_digest") != evidence.image_digest
            or approval_evidence.get("reviewed_tree_sha256")
            != evidence.reviewed_tree_sha256
            or approval_evidence.get("cleanup_status") != evidence.cleanup_status
            or approval_tree.get("protected_tree_must_equal_clean_canary_tree")
            is not True
        ):
            raise ValueError(
                "default authorization differs from the signed design approval"
            )
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise CanaryAuthorizationError(
            "independent default authorization evidence is missing or invalid"
        ) from exc


def validate_canary_authorization(
    *,
    environment: Mapping[str, str] | None = None,
    manifest_path: Path | None = None,
    default_manifest_path: Path | None = None,
    canary_report_path: Path | None = None,
    design_approval_path: Path | None = None,
    build_metadata_path: Path | None = None,
    reviewed_tree_root: Path | None = None,
    now: datetime | None = None,
) -> ValidatedCanaryAuthorization:
    """Validate packaged authorization, build identity, target, and provider pins."""

    values = environment if environment is not None else os.environ
    build_metadata_path = build_metadata_path or BUILD_METADATA_PATH
    reviewed_tree_root = reviewed_tree_root or PACKAGED_REVIEWED_TREE_ROOT
    canary_report_path = canary_report_path or CANARY_VALIDATION_REPORT_PATH
    design_approval_path = (
        design_approval_path or DEFAULT_AUTHORIZATION_DESIGN_APPROVAL_PATH
    )
    mode = values.get(ENV_ROLLOUT_MODE, "").strip().casefold()
    percentage_text = values.get(ENV_CANARY_PERCENTAGE, "").strip()
    if not percentage_text.isdecimal():
        raise CanaryAuthorizationError("rollout percentage is malformed")
    percentage = int(percentage_text)
    if mode == "canary" and not 1 <= percentage <= 10:
        raise CanaryAuthorizationError("canary percentage must be between 1 and 10")
    if mode == "default" and percentage != 100:
        raise CanaryAuthorizationError("default percentage must be exactly 100")
    if mode not in {"canary", "default"}:
        raise CanaryAuthorizationError(
            "only canary or separately authorized default rollout is permitted"
        )

    try:
        selected_manifest_path = (
            manifest_path or AUTHORIZATION_MANIFEST_PATH
            if mode == "canary"
            else default_manifest_path or DEFAULT_AUTHORIZATION_MANIFEST_PATH
        )
        manifest_bytes = selected_manifest_path.read_bytes()
        manifest_payload = json.loads(manifest_bytes)
        manifest: CanaryAuthorizationManifest | DefaultAuthorizationManifest
        if mode == "canary":
            manifest = CanaryAuthorizationManifest.model_validate(manifest_payload)
        else:
            manifest = DefaultAuthorizationManifest.model_validate(manifest_payload)
            if manifest.status != "AUTHORIZED":
                raise CanaryAuthorizationError("default authorization status is inactive")
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        ValidationError,
        TypeError,
    ) as exc:
        raise CanaryAuthorizationError(
            "authorization manifest is missing or invalid"
        ) from exc
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    try:
        build_metadata = BuildMetadata.model_validate_json(
            build_metadata_path.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, ValidationError) as exc:
        raise CanaryAuthorizationError("build metadata is missing or invalid") from exc
    if mode == "default":
        _validate_default_evidence_artifacts(
            manifest=manifest,
            build_metadata=build_metadata,
            report_path=canary_report_path,
            design_approval_path=design_approval_path,
        )
    expected_packaged_digest = (
        build_metadata.canary_authorization_manifest_sha256
        if mode == "canary"
        else build_metadata.default_authorization_manifest_sha256
    )
    if expected_packaged_digest != manifest_sha256:
        raise CanaryAuthorizationError("packaged authorization digest mismatch")
    deployment_digest_env = (
        ENV_AUTHORIZATION_MANIFEST_SHA256
        if mode == "canary"
        else ENV_DEFAULT_AUTHORIZATION_MANIFEST_SHA256
    )
    if values.get(deployment_digest_env, "").strip() != manifest_sha256:
        raise CanaryAuthorizationError("deployment authorization digest mismatch")
    source_revision = values.get(ENV_SOURCE_REVISION, "").strip()
    if not source_revision or source_revision != build_metadata.source_revision:
        raise CanaryAuthorizationError("build source revision mismatch")
    try:
        packaged_reviewed_tree_sha256 = reviewed_tree_digest(
            reviewed_tree_root,
            manifest.reviewed_tree.include_roots,
            manifest.reviewed_tree.exclude_paths,
        )
    except (OSError, ReviewedTreeError) as exc:
        raise CanaryAuthorizationError("packaged reviewed tree is invalid") from exc
    if (
        manifest.reviewed_tree.algorithm != REVIEWED_TREE_ALGORITHM
        or manifest.reviewed_tree.include_roots != REVIEWED_TREE_ROOTS
        or manifest.reviewed_tree.exclude_paths != REVIEWED_TREE_EXCLUDED_PATHS
        or packaged_reviewed_tree_sha256 != manifest.reviewed_tree.sha256
        or packaged_reviewed_tree_sha256 != build_metadata.reviewed_tree_sha256
    ):
        raise CanaryAuthorizationError("packaged reviewed tree digest mismatch")
    if (
        mode == "default"
        and packaged_reviewed_tree_sha256
        != manifest.canary_evidence.reviewed_tree_sha256
    ):
        raise CanaryAuthorizationError(
            "default build differs from the clean canary reviewed tree"
        )

    current = (now or _utc_now()).astimezone(UTC)
    if current < manifest.not_before:
        raise CanaryAuthorizationError("authorization is not yet valid")
    if current >= manifest.expires_at:
        raise CanaryAuthorizationError("authorization has expired")

    for name, expected in _EXPECTED_ENVIRONMENT.items():
        if mode == "default" and (
            name.startswith("AIOPS_COPILOT_SHADOW_")
            or name
            in {
                "AIOPS_COPILOT_PARSER_PROOF_SHA256",
                "AIOPS_COPILOT_SERIALIZATION_PROOF_SHA256",
            }
        ):
            continue
        if values.get(name, "").strip() != expected:
            raise CanaryAuthorizationError(f"runtime binding mismatch: {name}")
    if (
        values.get("AIOPS_SPECIALIST_MANIFEST_DIGEST", "").strip()
        != manifest.candidate_binding.manifest_sha256
    ):
        raise CanaryAuthorizationError("runtime specialist manifest mismatch")
    raw_candidate = values.get(CANDIDATE_ARTIFACT_ENV, "")
    raw_candidate_sha256 = values.get(CANDIDATE_ARTIFACT_DIGEST_ENV, "").strip()
    if (
        not raw_candidate
        or not re.fullmatch(_SHA256_PATTERN, raw_candidate_sha256)
        or hashlib.sha256(raw_candidate.encode("utf-8")).hexdigest()
        != raw_candidate_sha256
    ):
        raise CanaryAuthorizationError("candidate artifact transport digest mismatch")
    try:
        candidate_binding = candidate_artifact_binding(
            raw_candidate,
            load_specialist_manifest(),
        )
    except (OSError, TypeError, ValueError) as exc:
        raise CanaryAuthorizationError("candidate artifact is invalid") from exc
    if candidate_binding.source_revision != source_revision:
        raise CanaryAuthorizationError("candidate source revision mismatch")
    if (
        candidate_binding.algorithm
        != manifest.candidate_binding.semantic_algorithm
        or candidate_binding.sha256 != manifest.candidate_binding.semantic_sha256
        or values.get(CANDIDATE_BINDING_DIGEST_ENV, "").strip()
        != candidate_binding.sha256
    ):
        raise CanaryAuthorizationError("candidate semantic binding mismatch")
    for specialist_id, (agent_name, provider_version) in _EXPECTED_AGENTS.items():
        prefix = f"FOUNDRY_{specialist_id.upper()}_AGENT"
        if (
            values.get(f"{prefix}_NAME", "").strip() != agent_name
            or values.get(f"{prefix}_VERSION", "").strip() != provider_version
        ):
            raise CanaryAuthorizationError(
                f"runtime specialist mismatch: {specialist_id}"
            )
    if (
        values.get("FOUNDRY_AGENT_NAME", "").strip() != "operations-copilot"
        or values.get("FOUNDRY_AGENT_VERSION", "").strip() != "6"
    ):
        raise CanaryAuthorizationError("runtime coordinator mismatch")

    return ValidatedCanaryAuthorization(
        authorization_id=manifest.authorization_id,
        mode=mode,
        manifest_sha256=manifest_sha256,
        source_revision=source_revision,
        reviewed_tree_sha256=packaged_reviewed_tree_sha256,
        percentage=percentage,
        expires_at=manifest.expires_at,
    )


def require_canary_authorization_if_requested() -> ValidatedCanaryAuthorization | None:
    """Return immutable canary authority, or raise before any external I/O."""

    if not canary_authorization_required():
        return None
    return validate_canary_authorization()


def canary_authorization_health() -> dict[str, Any]:
    """Return a secret-free readiness projection for the canary gate."""

    if not canary_authorization_required():
        return {"required": False, "status": "not_required", "reason": ""}
    try:
        authority = validate_canary_authorization()
    except CanaryAuthorizationError as exc:
        return {"required": True, "status": "denied", "reason": exc.reason}
    return {
        "required": True,
        "status": "authorized",
        "reason": "",
        "authorization_id": authority.authorization_id,
        "mode": authority.mode,
        "manifest_sha256": authority.manifest_sha256,
        "expires_at": authority.expires_at.isoformat().replace("+00:00", "Z"),
    }


__all__ = [
    "AUTHORIZATION_MANIFEST_PATH",
    "BUILD_METADATA_PATH",
    "CANARY_VALIDATION_REPORT_PATH",
    "DEFAULT_AUTHORIZATION_DESIGN_APPROVAL_PATH",
    "DEFAULT_AUTHORIZATION_MANIFEST_PATH",
    "PACKAGED_REVIEWED_TREE_ROOT",
    "BuildMetadata",
    "CanaryAuthorizationError",
    "CanaryAuthorizationManifest",
    "DefaultAuthorizationManifest",
    "ValidatedCanaryAuthorization",
    "canary_authorization_health",
    "canary_authorization_required",
    "require_canary_authorization_if_requested",
    "validate_canary_authorization",
]
