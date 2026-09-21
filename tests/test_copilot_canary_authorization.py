"""Fail-closed tests for the packaged Operations Copilot canary authority."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from copilot_authorization_fixtures import (
    enable_authorized_default,
    strict_candidate_artifact,
)
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_api_copilot_investigation import _context

from api.app import create_app
from api.scope import Scope
from operations import copilot_canary_authorization as authorization
from operations.copilot_canary_authorization import CanaryAuthorizationError
from operations.maf_orchestrator import (
    authorize_canonical_execution,
    copilot_rollout_decision,
)
from operations.orchestration_contract import (
    EvidenceSnapshotV2,
    InvestigationRequest,
    SnapshotCoverage,
)
from operations.orchestration_service import OrchestrationService
from operations.reviewed_tree import (
    REVIEWED_TREE_EXCLUDED_PATHS,
    REVIEWED_TREE_ROOTS,
    reviewed_tree_paths,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGED_MANIFEST = (
    REPO_ROOT / "src" / "operations" / "copilot_canary_authorization.v1.json"
)
PACKAGED_DEFAULT_MANIFEST = (
    REPO_ROOT / "src" / "operations" / "copilot_default_authorization.v1.json"
)
SOURCE_REVISION = "a" * 40
API_IMAGE_DIGEST = f"sha256:{'b' * 64}"


def _manifest_payload() -> dict[str, object]:
    return json.loads(PACKAGED_MANIFEST.read_text(encoding="utf-8"))


def _authorized_environment(
    payload: dict[str, object],
    manifest_sha256: str,
    *,
    percentage: str = "10",
) -> dict[str, str]:
    target = payload["deployment_target"]
    project = payload["foundry_project"]
    scope = payload["authorization_scope"]
    binding = payload["candidate_binding"]
    shadow = payload["shadow_evidence"]
    candidate_raw = json.dumps(strict_candidate_artifact(), sort_keys=True)
    assert isinstance(target, dict)
    assert isinstance(project, dict)
    assert isinstance(scope, dict)
    assert isinstance(binding, dict)
    assert isinstance(shadow, dict)
    values = {
        "AIOPS_COPILOT_ROLLOUT_MODE": "canary",
        "AIOPS_COPILOT_CANARY_PERCENTAGE": percentage,
        "AIOPS_COPILOT_ROLLBACK_MODE": str(scope["rollback_mode"]),
        "AIOPS_AGENT_ORCHESTRATION_MODE": str(scope["orchestration"]),
        "AIOPS_SPECIALIST_ACTIVATION_SOURCE": str(scope["activation_source"]),
        "AIOPS_SOURCE_REVISION": SOURCE_REVISION,
        "AIOPS_FOUNDRY_CANDIDATE_ARTIFACT": candidate_raw,
        "AIOPS_FOUNDRY_CANDIDATE_ARTIFACT_DIGEST": hashlib.sha256(
            candidate_raw.encode()
        ).hexdigest(),
        "AIOPS_FOUNDRY_CANDIDATE_BINDING_DIGEST": str(binding["semantic_sha256"]),
        "AIOPS_CANARY_AUTHORIZATION_MANIFEST_SHA256": manifest_sha256,
        "AIOPS_API_IMAGE_DIGEST": API_IMAGE_DIGEST,
        "AIOPS_DEPLOYMENT_TENANT_ID": str(target["tenant_id"]),
        "AIOPS_DEPLOYMENT_SUBSCRIPTION_ID": str(target["subscription_id"]),
        "AIOPS_DEPLOYMENT_RESOURCE_GROUP": str(target["resource_group"]),
        "AIOPS_DEPLOYMENT_APP": str(target["app"]),
        "AIOPS_DEPLOYMENT_ENVIRONMENT": str(target["environment"]),
        "AIOPS_DEPLOYMENT_REGION": str(target["region"]),
        "AIOPS_FOUNDRY_PROJECT_RESOURCE_ID": str(project["resource_id"]),
        "AIOPS_FOUNDRY_PROJECT_NAME": str(project["name"]),
        "AIOPS_FOUNDRY_ACCOUNT_ENDPOINT": str(project["endpoint"]),
        "FOUNDRY_PROJECT_ENDPOINT": (
            f"{project['endpoint']}/api/projects/{project['name']}"
        ),
        "AIOPS_COPILOT_CANDIDATE_RELEASE": str(binding["release"]),
        "AIOPS_COPILOT_CANDIDATE_CONTRACT_VERSION": str(binding["contract_version"]),
        "AIOPS_COPILOT_CANDIDATE_MANIFEST_SHA256": str(binding["manifest_sha256"]),
        "AIOPS_COPILOT_PARSER_PROOF_SHA256": str(binding["parser_proof_sha256"]),
        "AIOPS_COPILOT_SERIALIZATION_PROOF_SHA256": str(
            binding["serialization_proof_sha256"]
        ),
        "AIOPS_SPECIALIST_MANIFEST_DIGEST": str(binding["manifest_sha256"]),
        "AIOPS_COPILOT_SHADOW_REVISION": str(shadow["revision"]),
        "AIOPS_COPILOT_SHADOW_IMAGE_DIGEST": str(shadow["image_digest"]),
        "AIOPS_COPILOT_SHADOW_REPORT_SHA256": str(shadow["report_sha256"]),
        "AIOPS_COPILOT_SHADOW_REPORT_INTEGRITY_SIGNATURE": str(
            shadow["report_integrity_signature"]
        ),
        "AIOPS_COPILOT_SHADOW_MATRIX_SHA256": str(shadow["matrix_sha256"]),
        "AIOPS_COPILOT_SHADOW_STATUS": str(shadow["shadow_status"]),
    }
    agents = binding["agents"]
    assert isinstance(agents, list)
    for agent in agents:
        assert isinstance(agent, dict)
        prefix = f"FOUNDRY_{str(agent['id']).upper()}_AGENT"
        values[f"{prefix}_NAME"] = str(agent["agent_name"])
        values[f"{prefix}_VERSION"] = str(agent["provider_version"])
    coordinator = binding["coordinator"]
    assert isinstance(coordinator, dict)
    values["FOUNDRY_AGENT_NAME"] = str(coordinator["agent_name"])
    values["FOUNDRY_AGENT_VERSION"] = str(coordinator["provider_version"])
    return values


def _write_authorization(
    tmp_path: Path,
    payload: dict[str, object] | None = None,
    *,
    raw: bytes | None = None,
) -> tuple[Path, Path, dict[str, str]]:
    manifest_path = tmp_path / "authorization.json"
    manifest_bytes = (
        raw
        if raw is not None
        else json.dumps(
            payload or _manifest_payload(),
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
    )
    manifest_path.write_bytes(manifest_bytes)
    digest = hashlib.sha256(manifest_bytes).hexdigest()
    metadata_path = tmp_path / "build-metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "schema_version": "copilot-build-metadata.v1",
                "source_revision": SOURCE_REVISION,
                "canary_authorization_manifest_sha256": digest,
                "default_authorization_manifest_sha256": "d" * 64,
                "reviewed_tree_sha256": str(
                    (payload or _manifest_payload())["reviewed_tree"]["sha256"]  # type: ignore[index]
                ),
            }
        ),
        encoding="utf-8",
    )
    environment = _authorized_environment(
        payload or _manifest_payload(),
        digest,
    )
    return manifest_path, metadata_path, environment


def _install_runtime_case(
    monkeypatch: pytest.MonkeyPatch,
    manifest_path: Path,
    metadata_path: Path,
    environment: dict[str, str],
) -> None:
    monkeypatch.setattr(
        authorization,
        "AUTHORIZATION_MANIFEST_PATH",
        manifest_path,
    )
    monkeypatch.setattr(authorization, "BUILD_METADATA_PATH", metadata_path)
    monkeypatch.setattr(authorization, "PACKAGED_REVIEWED_TREE_ROOT", REPO_ROOT)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)


@pytest.mark.parametrize("percentage", ("1", "10"))
def test_reviewed_authorization_accepts_only_bounded_canary(
    tmp_path: Path,
    percentage: str,
) -> None:
    payload = _manifest_payload()
    manifest_path, metadata_path, environment = _write_authorization(
        tmp_path,
        payload,
    )
    environment["AIOPS_COPILOT_CANARY_PERCENTAGE"] = percentage

    authority = authorization.validate_canary_authorization(
        environment=environment,
        manifest_path=manifest_path,
        build_metadata_path=metadata_path,
        reviewed_tree_root=REPO_ROOT,
        now=datetime(2026, 9, 21, tzinfo=UTC),
    )

    assert authority.authorization_id == payload["authorization_id"]
    assert authority.percentage == int(percentage)
    assert authority.reviewed_tree_sha256 == payload["reviewed_tree"]["sha256"]  # type: ignore[index]
    assert (
        authority.manifest_sha256
        == hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    )


def test_packaged_default_authorization_binds_clean_canary() -> None:
    payload = json.loads(PACKAGED_DEFAULT_MANIFEST.read_text(encoding="utf-8"))

    manifest = authorization.DefaultAuthorizationManifest.model_validate(payload)

    assert manifest.status == "AUTHORIZED"
    assert manifest.authorization_scope.percentage == 100
    assert manifest.authorization_scope.default_authorized is True
    assert manifest.canary_evidence.status == "PASS_CLEAN"
    assert manifest.canary_evidence.cleanup_status == "PASS_COMPLETE"


def test_packaged_default_binds_exact_promotion_lineage() -> None:
    manifest = authorization.DefaultAuthorizationManifest.model_validate_json(
        PACKAGED_DEFAULT_MANIFEST.read_text(encoding="utf-8")
    )

    assert manifest.promotion_lineage.base_source_revision == (
        manifest.canary_evidence.source_revision
    )
    assert manifest.promotion_lineage.base_image_digest == (
        manifest.canary_evidence.image_digest
    )
    assert manifest.promotion_lineage.allowed_mutations == (
        authorization.DEFAULT_PROMOTION_ALLOWED_MUTATIONS
    )
    assert (
        authorization.default_promotion_equivalence_sha256(manifest.promotion_lineage)
        == manifest.promotion_lineage.equivalence_proof.sha256
    )


def test_pending_default_manifest_cannot_authorize(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enable_authorized_default(monkeypatch)
    payload = json.loads(PACKAGED_DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    payload["status"] = "HOLD_PENDING_CANARY_REVALIDATION"
    pending_manifest = tmp_path / "pending-default.json"
    pending_manifest.write_text(json.dumps(payload), encoding="utf-8")
    manifest_sha256 = hashlib.sha256(pending_manifest.read_bytes()).hexdigest()
    metadata = json.loads(authorization.BUILD_METADATA_PATH.read_text())
    metadata["default_authorization_manifest_sha256"] = manifest_sha256
    authorization.BUILD_METADATA_PATH.write_text(json.dumps(metadata))
    monkeypatch.setattr(
        authorization,
        "DEFAULT_AUTHORIZATION_MANIFEST_PATH",
        pending_manifest,
    )
    monkeypatch.setenv(
        "AIOPS_DEFAULT_AUTHORIZATION_MANIFEST_SHA256",
        manifest_sha256,
    )

    with pytest.raises(CanaryAuthorizationError, match="status is inactive"):
        copilot_rollout_decision(stable_key="operator-a")


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("status", "REVOKED"),
        ("tested_percentage", 9),
        ("cleanup_status", "PENDING"),
        ("canary_tree", "c" * 64),
        ("semantic_sha256", "c" * 64),
    ),
)
def test_default_authorization_rejects_unreviewed_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    enable_authorized_default(monkeypatch)
    payload = json.loads(PACKAGED_DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    payload["status"] = "AUTHORIZED"
    payload["canary_evidence"]["reviewed_tree_sha256"] = payload["reviewed_tree"][  # type: ignore[index]
        "sha256"
    ]
    if field == "semantic_sha256":
        payload["candidate_binding"][field] = value
    elif field == "canary_tree":
        payload["canary_evidence"]["reviewed_tree_sha256"] = value
    elif field == "status":
        payload[field] = value
    else:
        payload["canary_evidence"][field] = value
    manifest_path = tmp_path / "default-authorization.json"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    metadata = json.loads(authorization.BUILD_METADATA_PATH.read_text())
    metadata["default_authorization_manifest_sha256"] = manifest_sha256
    authorization.BUILD_METADATA_PATH.write_text(json.dumps(metadata))
    monkeypatch.setattr(
        authorization,
        "DEFAULT_AUTHORIZATION_MANIFEST_PATH",
        manifest_path,
    )
    monkeypatch.setenv(
        "AIOPS_DEFAULT_AUTHORIZATION_MANIFEST_SHA256",
        manifest_sha256,
    )

    with pytest.raises(CanaryAuthorizationError):
        copilot_rollout_decision(stable_key="operator-a")


def test_general_rebuilt_image_cannot_authorize_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enable_authorized_default(monkeypatch)
    metadata = json.loads(authorization.BUILD_METADATA_PATH.read_text(encoding="utf-8"))
    metadata.pop("default_promotion")
    authorization.BUILD_METADATA_PATH.write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(
        CanaryAuthorizationError,
        match="authorized promotion path",
    ):
        copilot_rollout_decision(stable_key="operator-a")


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("source_revision", "c" * 40),
        ("image_digest", f"sha256:{'c' * 64}"),
    ),
)
def test_default_rejects_stale_canary_source_or_base_image(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: str,
) -> None:
    enable_authorized_default(monkeypatch)
    metadata = json.loads(authorization.BUILD_METADATA_PATH.read_text(encoding="utf-8"))
    lineage_field = (
        "base_source_revision" if field == "source_revision" else "base_image_digest"
    )
    metadata["default_promotion"][lineage_field] = value
    authorization.BUILD_METADATA_PATH.write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(
        CanaryAuthorizationError,
        match="authorized promotion path",
    ):
        copilot_rollout_decision(stable_key="operator-a")


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("transformation_policy", "general-rebuild-v1"),
        (
            "equivalence_proof",
            {
                "algorithm": authorization.DEFAULT_PROMOTION_EQUIVALENCE_ALGORITHM,
                "sha256": "c" * 64,
            },
        ),
    ),
)
def test_default_rejects_wrong_transformation_policy_or_equivalence_proof(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    enable_authorized_default(monkeypatch)
    metadata = json.loads(authorization.BUILD_METADATA_PATH.read_text(encoding="utf-8"))
    metadata["default_promotion"][field] = value
    authorization.BUILD_METADATA_PATH.write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(CanaryAuthorizationError):
        copilot_rollout_decision(stable_key="operator-a")


def test_default_manifest_cannot_authorize_canary(
    tmp_path: Path,
) -> None:
    _, metadata_path, environment = _write_authorization(tmp_path)
    environment["AIOPS_COPILOT_ROLLOUT_MODE"] = "canary"
    environment["AIOPS_COPILOT_CANARY_PERCENTAGE"] = "10"

    with pytest.raises(CanaryAuthorizationError, match="missing or invalid"):
        authorization.validate_canary_authorization(
            environment=environment,
            manifest_path=PACKAGED_DEFAULT_MANIFEST,
            build_metadata_path=metadata_path,
            reviewed_tree_root=REPO_ROOT,
            now=datetime(2026, 9, 21, 2, tzinfo=UTC),
        )


def test_canary_manifest_cannot_authorize_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enable_authorized_default(monkeypatch)
    manifest_sha256 = hashlib.sha256(PACKAGED_MANIFEST.read_bytes()).hexdigest()
    metadata = json.loads(authorization.BUILD_METADATA_PATH.read_text())
    metadata["default_authorization_manifest_sha256"] = manifest_sha256
    authorization.BUILD_METADATA_PATH.write_text(json.dumps(metadata))
    monkeypatch.setattr(
        authorization,
        "DEFAULT_AUTHORIZATION_MANIFEST_PATH",
        PACKAGED_MANIFEST,
    )
    monkeypatch.setenv(
        "AIOPS_DEFAULT_AUTHORIZATION_MANIFEST_SHA256",
        manifest_sha256,
    )

    with pytest.raises(CanaryAuthorizationError, match="missing or invalid"):
        copilot_rollout_decision(stable_key="operator-a")


def test_packaged_semantic_digest_matches_reviewed_candidate() -> None:
    payload = _manifest_payload()
    binding = authorization.candidate_artifact_binding(
        json.dumps(strict_candidate_artifact()),
        authorization.load_specialist_manifest(),
    )

    assert binding.algorithm == payload["candidate_binding"]["semantic_algorithm"]  # type: ignore[index]
    assert binding.sha256 == payload["candidate_binding"]["semantic_sha256"]  # type: ignore[index]


@pytest.mark.parametrize(
    "case",
    (
        "project",
        "model",
        "prompt",
        "grant",
        "connection",
        "identity",
        "coordinator",
        "provider",
        "scope",
        "runtime_policy",
    ),
)
def test_security_relevant_candidate_mutation_fails_authorization(
    tmp_path: Path,
    case: str,
) -> None:
    manifest_path, metadata_path, environment = _write_authorization(tmp_path)
    candidate = json.loads(environment["AIOPS_FOUNDRY_CANDIDATE_ARTIFACT"])
    network = candidate["agents"]["network"]
    if case == "project":
        candidate["project"]["resource_id"] += "-other"
    elif case == "model":
        network["model_deployment"] = "other-model"
    elif case == "prompt":
        network["prompt_digest"] = "c" * 64
    elif case == "grant":
        network["tools"]["operations_mcp"][0] = "search"
    elif case == "connection":
        network["tools"]["ai_search"]["project_connection_id"] += "-other"
    elif case == "identity":
        network["agent_name"] = "aiops-network-other"
    elif case == "coordinator":
        candidate["coordinator"]["provider_version_id"] = "7"
    elif case == "provider":
        network["provider_version_id"] = "99"
    elif case == "scope":
        network["scope_policy"] = "specialist-manifest.v2"
    elif case == "runtime_policy":
        network["read_only"] = False
    candidate_raw = json.dumps(candidate, sort_keys=True)
    environment["AIOPS_FOUNDRY_CANDIDATE_ARTIFACT"] = candidate_raw
    environment["AIOPS_FOUNDRY_CANDIDATE_ARTIFACT_DIGEST"] = hashlib.sha256(
        candidate_raw.encode()
    ).hexdigest()

    with pytest.raises(
        CanaryAuthorizationError,
        match="candidate (artifact is invalid|semantic binding mismatch)",
    ):
        authorization.validate_canary_authorization(
            environment=environment,
            manifest_path=manifest_path,
            build_metadata_path=metadata_path,
            reviewed_tree_root=REPO_ROOT,
            now=datetime(2026, 9, 21, tzinfo=UTC),
        )


def test_candidate_source_revision_mismatch_is_independent_of_transport_digest(
    tmp_path: Path,
) -> None:
    manifest_path, metadata_path, environment = _write_authorization(tmp_path)
    candidate = strict_candidate_artifact(source_revision="c" * 40)
    candidate_raw = json.dumps(candidate, sort_keys=True)
    environment["AIOPS_FOUNDRY_CANDIDATE_ARTIFACT"] = candidate_raw
    environment["AIOPS_FOUNDRY_CANDIDATE_ARTIFACT_DIGEST"] = hashlib.sha256(
        candidate_raw.encode()
    ).hexdigest()

    with pytest.raises(CanaryAuthorizationError, match="candidate source revision"):
        authorization.validate_canary_authorization(
            environment=environment,
            manifest_path=manifest_path,
            build_metadata_path=metadata_path,
            reviewed_tree_root=REPO_ROOT,
            now=datetime(2026, 9, 21, tzinfo=UTC),
        )


@pytest.mark.parametrize(
    "case",
    (
        "percentage_zero",
        "percentage_eleven",
        "percentage_out_of_range",
        "missing_agent",
        "extra_agent",
        "duplicate_agent",
        "wrong_coordinator",
        "wrong_candidate_digest",
        "wrong_semantic_digest",
        "wrong_manifest_digest",
        "wrong_report_digest",
        "wrong_matrix_digest",
        "wrong_source",
        "wrong_authorization_digest",
        "wrong_baked_manifest_digest",
        "wrong_target",
        "wrong_project",
        "wrong_rollback",
        "expired",
        "not_yet_valid",
        "inactive",
        "malformed",
        "shadow_misuse",
        "default_misuse",
        "env_only_substitution",
        "wrong_release",
        "extra_manifest_key",
    ),
)
def test_every_authorization_failure_blocks_readiness_and_external_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    payload = copy.deepcopy(_manifest_payload())
    binding = payload["candidate_binding"]
    assert isinstance(binding, dict)
    agents = binding["agents"]
    assert isinstance(agents, list)
    now = datetime.now(UTC)
    raw = None
    if case == "missing_agent":
        agents.pop()
    elif case == "extra_agent":
        agents.append(
            {
                "id": "unexpected",
                "agent_name": "aiops-unexpected-agent",
                "provider_version": "1",
            }
        )
    elif case == "duplicate_agent":
        agents.append(copy.deepcopy(agents[0]))
    elif case == "wrong_coordinator":
        binding["coordinator"]["provider_version"] = "7"  # type: ignore[index]
    elif case == "inactive":
        payload["status"] = "REVOKED"
    elif case == "expired":
        payload["issued_at"] = (now - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
        payload["not_before"] = (now - timedelta(hours=2)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        payload["expires_at"] = (now - timedelta(hours=1)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    elif case == "not_yet_valid":
        payload["issued_at"] = (now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        payload["not_before"] = (now + timedelta(hours=2)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        payload["expires_at"] = (now + timedelta(hours=3)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    elif case == "malformed":
        raw = b"{not-json"
    elif case == "extra_manifest_key":
        payload["unreviewed"] = True

    manifest_path, metadata_path, environment = _write_authorization(
        tmp_path,
        payload,
        raw=raw,
    )
    wrong_environment = {
        "percentage_zero": ("AIOPS_COPILOT_CANARY_PERCENTAGE", "0"),
        "percentage_eleven": ("AIOPS_COPILOT_CANARY_PERCENTAGE", "11"),
        "percentage_out_of_range": ("AIOPS_COPILOT_CANARY_PERCENTAGE", "101"),
        "wrong_candidate_digest": (
            "AIOPS_FOUNDRY_CANDIDATE_ARTIFACT_DIGEST",
            "c" * 64,
        ),
        "wrong_semantic_digest": (
            "AIOPS_FOUNDRY_CANDIDATE_BINDING_DIGEST",
            "c" * 64,
        ),
        "wrong_manifest_digest": (
            "AIOPS_SPECIALIST_MANIFEST_DIGEST",
            "c" * 64,
        ),
        "wrong_report_digest": (
            "AIOPS_COPILOT_SHADOW_REPORT_SHA256",
            "c" * 64,
        ),
        "wrong_matrix_digest": (
            "AIOPS_COPILOT_SHADOW_MATRIX_SHA256",
            "c" * 64,
        ),
        "wrong_source": ("AIOPS_SOURCE_REVISION", "c" * 40),
        "wrong_target": ("AIOPS_DEPLOYMENT_APP", "other-api"),
        "wrong_project": ("AIOPS_FOUNDRY_PROJECT_NAME", "other-project"),
        "wrong_rollback": ("AIOPS_COPILOT_ROLLBACK_MODE", "canonical"),
        "shadow_misuse": ("AIOPS_COPILOT_ROLLOUT_MODE", "shadow"),
        "default_misuse": ("AIOPS_COPILOT_ROLLOUT_MODE", "default"),
        "wrong_release": ("AIOPS_COPILOT_CANDIDATE_RELEASE", "mutable"),
    }
    if case in wrong_environment:
        name, value = wrong_environment[case]
        environment[name] = value
    if case == "wrong_authorization_digest":
        environment["AIOPS_CANARY_AUTHORIZATION_MANIFEST_SHA256"] = "c" * 64
    if case == "wrong_baked_manifest_digest":
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["canary_authorization_manifest_sha256"] = "c" * 64
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    if case == "env_only_substitution":
        manifest_path = tmp_path / "missing-authorization.json"
    _install_runtime_case(
        monkeypatch,
        manifest_path,
        metadata_path,
        environment,
    )

    health = authorization.canary_authorization_health()
    assert health["status"] == "denied"
    if case == "expired":
        assert health["reason"] == "authorization has expired"
    elif case == "not_yet_valid":
        assert health["reason"] == "authorization is not yet valid"
    assert (
        TestClient(create_app(_context(tmp_path, None))).get("/ready").status_code
        == 503
    )

    external_calls = 0

    def external_executor(*_args, **_kwargs):
        nonlocal external_calls
        external_calls += 1
        raise AssertionError("authorization failure reached external I/O")

    service = OrchestrationService(executor=external_executor)
    with pytest.raises(CanaryAuthorizationError):
        service.execute_turn(  # type: ignore[arg-type]
            object(),
            context=object(),
            principal_subject="operator",
            effective_scope=object(),  # type: ignore[arg-type]
        )
    assert external_calls == 0


def test_validated_authority_is_attached_to_canary_route_decision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path, metadata_path, environment = _write_authorization(tmp_path)
    _install_runtime_case(
        monkeypatch,
        manifest_path,
        metadata_path,
        environment,
    )
    stable_key = next(
        f"operator-{index}"
        for index in range(10_000)
        if int.from_bytes(
            hashlib.sha256(f"copilot-rollout-v1\0operator-{index}".encode()).digest()[
                :8
            ],
            "big",
        )
        % 100
        < 10
    )

    decision = copilot_rollout_decision(stable_key=stable_key)

    assert decision.mode == "canary"
    assert decision.canonical_enabled is True
    assert decision.authorization_id == "p11-canary-authorization-20260920"
    assert (
        decision.authorization_manifest_sha256
        == hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    )
    assert (
        decision.reviewed_tree_sha256 == _manifest_payload()["reviewed_tree"]["sha256"]
    )  # type: ignore[index]


@pytest.mark.parametrize(
    "value",
    (
        1789930800,
        "2026-09-20T12:00:00-07:00",
        " 2026-09-20T19:00:00Z",
        "2026-09-20T19:00:00Z ",
        "2026-09-20T19:00:00.000Z",
        "2026-09-20t19:00:00z",
    ),
)
def test_manifest_rejects_noncanonical_security_timestamps(value: object) -> None:
    payload = _manifest_payload()
    payload["issued_at"] = value

    with pytest.raises(ValidationError):
        authorization.CanaryAuthorizationManifest.model_validate(payload)


def test_modified_reviewed_source_and_arbitrary_revision_cannot_authorize(
    tmp_path: Path,
) -> None:
    payload = _manifest_payload()
    manifest_path, metadata_path, environment = _write_authorization(
        tmp_path,
        payload,
    )
    packaged_root = tmp_path / "packaged"
    for relative in reviewed_tree_paths(
        REPO_ROOT,
        REVIEWED_TREE_ROOTS,
        REVIEWED_TREE_EXCLUDED_PATHS,
    ):
        destination = packaged_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / relative, destination)
    modified = packaged_root / "src" / "operations" / "orchestration_service.py"
    modified.write_bytes(modified.read_bytes() + b"\n# unauthorized change\n")
    arbitrary_revision = "d" * 40
    environment["AIOPS_SOURCE_REVISION"] = arbitrary_revision
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["source_revision"] = arbitrary_revision
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(CanaryAuthorizationError, match="reviewed tree"):
        authorization.validate_canary_authorization(
            environment=environment,
            manifest_path=manifest_path,
            build_metadata_path=metadata_path,
            reviewed_tree_root=packaged_root,
            now=datetime(2026, 9, 21, tzinfo=UTC),
        )


def test_direct_canonical_service_revalidates_server_authority_and_rejects_forgery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path, metadata_path, environment = _write_authorization(tmp_path)
    _install_runtime_case(monkeypatch, manifest_path, metadata_path, environment)
    monkeypatch.setattr("operations.maf_orchestrator._canary_bucket", lambda _key: 0)
    request = InvestigationRequest(
        question="Show inventory health",
        requested_scope={"subscription": ["sub-a"]},
        snapshot=EvidenceSnapshotV2(
            page_kind="inventory",
            page_id="inventory",
            coverage=SnapshotCoverage(
                visible_count=0,
                total_count=0,
                complete=False,
            ),
        ),
    )
    external_calls = 0

    def external_executor(*_args, **_kwargs):
        nonlocal external_calls
        external_calls += 1
        raise AssertionError("route authority failure reached external I/O")

    service = OrchestrationService(executor=external_executor)
    monkeypatch.setenv(
        "AIOPS_CANARY_AUTHORIZATION_MANIFEST_SHA256",
        "c" * 64,
    )
    with pytest.raises(CanaryAuthorizationError, match="authorization digest"):
        service.execute(
            request,
            context=object(),
            principal_subject="operator-a",
            effective_scope=Scope({"subscription": ["sub-a"]}),
        )
    monkeypatch.setenv(
        "AIOPS_CANARY_AUTHORIZATION_MANIFEST_SHA256",
        hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
    )
    with pytest.raises(CanaryAuthorizationError, match="caller-supplied"):
        service.execute(
            request,
            context=object(),
            principal_subject="operator-a",
            effective_scope=Scope({"subscription": ["sub-a"]}),
            route_authority=object(),
        )
    assert external_calls == 0


@pytest.mark.parametrize("mode", ("compatibility", "shadow", "default"))
def test_noncanonical_runtime_cannot_authorize_direct_service(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    request = {"question": "Show inventory health"}
    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", mode)
    monkeypatch.setenv("AIOPS_COPILOT_CANARY_PERCENTAGE", "0")

    with pytest.raises(CanaryAuthorizationError):
        authorize_canonical_execution(
            request=request,
            principal_subject="operator-a",
            stable_key="operator-a",
        )


def test_route_authority_rejects_mismatched_principal_stable_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path, metadata_path, environment = _write_authorization(tmp_path)
    _install_runtime_case(monkeypatch, manifest_path, metadata_path, environment)
    monkeypatch.setattr("operations.maf_orchestrator._canary_bucket", lambda _key: 0)

    with pytest.raises(CanaryAuthorizationError, match="not selected"):
        authorize_canonical_execution(
            request={"question": "Show inventory health"},
            principal_subject="operator-b",
            stable_key="operator-a",
        )


def test_default_authority_revalidates_request_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enable_authorized_default(monkeypatch)
    request = {"question": "Show inventory health"}

    decision = copilot_rollout_decision(stable_key="operator-a")
    authorize_canonical_execution(
        request=request,
        principal_subject="operator-a",
        stable_key="operator-a",
    )

    assert decision.mode == "default"
    assert decision.canonical_enabled is True
    assert decision.canary_bucket is None
    assert decision.authorization_id == (
        "p11-default-authorization-source05065b82-20260921"
    )


def test_exact_canary_derived_default_fixture_authorizes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enable_authorized_default(monkeypatch)
    manifest = authorization.DefaultAuthorizationManifest.model_validate_json(
        authorization.DEFAULT_AUTHORIZATION_MANIFEST_PATH.read_text(encoding="utf-8")
    )

    authority = authorization.validate_canary_authorization()

    assert authority.mode == "default"
    assert authority.reviewed_tree_sha256 == (
        manifest.canary_evidence.reviewed_tree_sha256
    )
    assert authority.source_revision == manifest.promotion_lineage.base_source_revision
    assert "AIOPS_API_IMAGE_DIGEST" not in os.environ


def test_default_authority_requires_exact_effective_percentage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enable_authorized_default(monkeypatch)
    monkeypatch.setenv("AIOPS_COPILOT_CANARY_PERCENTAGE", "99")

    with pytest.raises(CanaryAuthorizationError, match="exactly 100"):
        copilot_rollout_decision(stable_key="operator-a")


def test_forged_object_cannot_authorize_external_execution() -> None:
    request = InvestigationRequest(
        question="Show inventory health",
        requested_scope={"subscription": ["sub-a"]},
        snapshot=EvidenceSnapshotV2(
            page_kind="inventory",
            page_id="inventory",
            coverage=SnapshotCoverage(
                visible_count=0,
                total_count=0,
                complete=False,
            ),
        ),
    )
    external_calls = 0

    def external_executor(*_args, **_kwargs):
        nonlocal external_calls
        external_calls += 1
        raise AssertionError("forged rollout decision reached external I/O")

    with pytest.raises(CanaryAuthorizationError, match="caller-supplied"):
        OrchestrationService(executor=external_executor).execute(
            request,
            context=object(),
            principal_subject="operator-a",
            effective_scope=Scope({"subscription": ["sub-a"]}),
            route_authority=object(),
        )
    assert external_calls == 0


def test_constructor_authorizer_injection_is_rejected_and_cannot_bypass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = InvestigationRequest(
        question="Show inventory health",
        requested_scope={"subscription": ["sub-a"]},
        snapshot=EvidenceSnapshotV2(
            page_kind="inventory",
            page_id="inventory",
            coverage=SnapshotCoverage(
                visible_count=0,
                total_count=0,
                complete=False,
            ),
        ),
    )
    external_calls = 0

    def external_executor(*_args, **_kwargs):
        nonlocal external_calls
        external_calls += 1
        raise AssertionError("denied request reached external I/O")

    with pytest.raises(TypeError, match="canonical_authorizer"):
        OrchestrationService(
            executor=external_executor,
            canonical_authorizer=lambda **_kwargs: None,  # type: ignore[call-arg]
        )

    manifest_path, metadata_path, environment = _write_authorization(tmp_path)
    _install_runtime_case(
        monkeypatch,
        manifest_path,
        metadata_path,
        environment,
    )
    monkeypatch.setattr("operations.maf_orchestrator._canary_bucket", lambda _key: 0)
    monkeypatch.setenv(
        "AIOPS_CANARY_AUTHORIZATION_MANIFEST_SHA256",
        "c" * 64,
    )
    with pytest.raises(CanaryAuthorizationError, match="authorization digest"):
        OrchestrationService(executor=external_executor).execute(
            request,
            context=object(),
            principal_subject="operator-a",
            stable_key="operator-a",
            effective_scope=Scope({"subscription": ["sub-a"]}),
        )

    assert external_calls == 0


def test_build_and_terraform_wiring_is_fail_closed() -> None:
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    promotion_dockerfile = (REPO_ROOT / "Dockerfile.default-promotion").read_text(
        encoding="utf-8"
    )
    dockerignore = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8")
    build_script = (REPO_ROOT / "infra" / "scripts" / "build-and-push.sh").read_text(
        encoding="utf-8"
    )
    deploy_script = (REPO_ROOT / "infra" / "scripts" / "deploy.sh").read_text(
        encoding="utf-8"
    )
    terraform = (REPO_ROOT / "infra" / "terraform" / "container_apps.tf").read_text(
        encoding="utf-8"
    )
    packaging = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert "ARG AIOPS_SOURCE_REVISION" in dockerfile
    assert "ARG AIOPS_CANARY_AUTHORIZATION_MANIFEST_SHA256" not in dockerfile
    assert 'pathlib.Path("/app/build-metadata.json")' in dockerfile
    assert "operations.reviewed_tree" in dockerfile
    assert "COPY arg.config.deploy.yaml fabric.config.deploy.yaml /app/" in dockerfile
    assert "COPY arg.config.deploy.yaml /app/config.yaml" in dockerfile
    assert "COPY fabric.config.deploy.yaml /app/fabric.config.yaml" in dockerfile
    assert "AIOPS_ARG_CONFIG=/app/config.yaml" in dockerfile
    assert "AIOPS_FABRIC_CONFIG=/app/fabric.config.yaml" in dockerfile
    assert dockerfile.index("COPY arg.config.deploy.yaml") < dockerfile.index(
        "python -m operations.reviewed_tree"
    )
    assert 'git -C "${repo_root}" rev-parse HEAD' in build_script
    assert "python3 -m operations.reviewed_tree" in build_script
    assert (
        build_script.count("refusing to reuse existing API tag aiops-api:${tag}") == 2
    )
    assert build_script.index('image "aiops-api:${tag}"') < build_script.index(
        "prepare_acr_context"
    )
    assert "resolve_api_digest()" in build_script
    assert "--api-authorization-release" in build_script
    assert "--default-promotion" in build_script
    assert 'api_dockerfile="${repo_root}/Dockerfile.default-promotion"' in build_script
    assert "FROM ${AIOPS_CANARY_BASE_IMAGE}" in promotion_dockerfile
    assert promotion_dockerfile.count("COPY ") == 1
    assert (
        "COPY src/operations/copilot_default_authorization.v1.json "
        "/app/src/operations/copilot_default_authorization.v1.json"
        in promotion_dockerfile
    )
    assert "uv sync" not in promotion_dockerfile
    assert "COPY src/ /app/src/" not in promotion_dockerfile
    assert 'metadata["default_promotion"]=lineage.model_dump' in promotion_dockerfile
    authorization_release = build_script.split(
        "# This release gate authorizes API code only.",
        maxsplit=1,
    )[1].split("\nelse\n  build_image", maxsplit=1)[0]
    assert "build_image aiops-api" in authorization_release
    assert "verify_pushed aiops-api" in authorization_release
    assert "mcp-server" not in authorization_release
    assert "azure-mcp" not in authorization_release
    assert "aiops-web" not in authorization_release
    assert "-target=azurerm_container_app.api" in build_script
    assert "terraform console -no-color" in deploy_script
    assert "var.copilot_rollout_mode" in deploy_script
    assert "rollout_mode_from_file" not in deploy_script
    assert "validate_api_authorization_target" in deploy_script
    assert (
        '"${target_count}" -ne 1 || "${target}" != "azurerm_container_app.api"'
    ) in deploy_script
    assert "-target|--target)" in deploy_script
    assert "-target=*|--target=*)" in deploy_script
    assert deploy_script.count('validate_api_authorization_target "$@"') == 1
    assert "apply_api_authorization_release" in deploy_script
    assert "apply_api_compatibility_hold" in deploy_script
    assert "restore_and_verify_api_compatibility" in deploy_script
    assert "api_digest_args" in deploy_script
    assert 'API_DIGEST_ARGS+=("-var=api_image_digest=${digest}")' in deploy_script
    assert 'captured_api_image="$(terraform output -raw api_image' in deploy_script
    assert 'captured_api_digest="${captured_api_image##*@}"' in deploy_script
    assert (
        'validate_running_api_revision compatibility 0 "${captured_api_image}"'
        in deploy_script
    )
    assert deploy_script.index(
        'validate_running_api_revision compatibility 0 "${captured_api_image}"'
    ) < deploy_script.index(
        'terraform apply -input=false "${bound_args[@]}"',
        deploy_script.index("apply_api_authorization_release()"),
    )
    assert '[[ "${applied_api_image}" != "${captured_api_image}" ]]' in deploy_script
    assert '[[ "${applied_api_digest}" != "${captured_api_digest}" ]]' in deploy_script
    assert (
        '"${requested_mode}" "${requested_percentage}" "${captured_api_image}"'
        in deploy_script
    )
    assert (
        deploy_script.count(
            "restore_and_verify_api_compatibility \\\n"
            '      "${captured_api_image}" "${bound_args[@]}"'
        )
        == 3
    )
    assert 'environment.get("AIOPS_COPILOT_ROLLOUT_MODE", "")' in deploy_script
    assert 'environment.get("AIOPS_COPILOT_CANARY_PERCENTAGE", "")' in deploy_script
    assert (
        'az containerapp show --subscription "${ARM_SUBSCRIPTION_ID}"' in deploy_script
    )
    assert (
        'az containerapp revision list --subscription "${ARM_SUBSCRIPTION_ID}"'
        in deploy_script
    )
    assert (
        deploy_script.count(
            'az containerapp revision list --subscription "${ARM_SUBSCRIPTION_ID}"'
        )
        == 1
    )
    assert (
        "resolved API resource ID does not match the authorized subscription, "
        "resource group, and app"
    ) in deploy_script
    assert (
        'expected_resource_id="/subscriptions/${authorized_subscription}/'
        "resourceGroups/${authorized_rg}/providers/Microsoft.App/containerApps/"
        '${authorized_app}"'
    ) in deploy_script
    assert 'api_authorization_release}" != "1"' in deploy_script
    assert 'api_image_digest = \\"" digest "\\""' in build_script
    assert 'deployment_source_revision = \\"" revision "\\""' in build_script
    assert "record_application_release" in build_script
    assert 'api_digest="$(resolve_api_digest)"' in build_script
    assert "az acr repository show \\" in build_script
    assert '--image "aiops-api:${tag}"' in build_script
    assert '--query "{name:name,digest:digest}"' in build_script
    assert "az acr repository show-tags" not in build_script
    assert (
        "AIOPS_API_AUTHORIZATION_RELEASE=1 "
        "./infra/scripts/deploy.sh apply "
        "-target=azurerm_container_app.api"
    ) in build_script
    assert (
        'exec "${repo_root}/infra/scripts/deploy.sh" apply \\\n'
        "      -target=azurerm_container_app.api"
    ) in build_script
    assert 'local.copilot_default_authorization.status == "AUTHORIZED"' in terraform
    assert (
        "var.copilot_default_base_image_digest == "
        "local.copilot_default_authorization.promotion_lineage.base_image_digest"
    ) in terraform
    assert (
        "local.copilot_default_authorization.promotion_lineage."
        "equivalence_proof.sha256 == sha256("
        "jsonencode(local.copilot_default_equivalence_payload))"
    ) in terraform
    assert (
        "local.copilot_default_authorization.reviewed_tree.sha256 == "
        "local.copilot_default_authorization.promotion_lineage."
        "equivalent_reviewed_tree_sha256"
    ) in terraform
    assert (
        "local.copilot_default_authorization.authorization_scope.percentage == 100"
        in terraform
    )
    api_resource = terraform.split(
        'resource "azurerm_container_app" "api" {',
        maxsplit=1,
    )[1].split(
        'resource "azurerm_container_app" "web" {',
        maxsplit=1,
    )[0]
    assert 'revision_mode                = "Multiple"' in api_resource
    assert 'revision_mode                = "Single"' not in api_resource
    assert 'var.api_image_digest != ""' in terraform
    assert "local.copilot_canary_percentage <= 10" in terraform
    assert (
        'local.foundry_specialist_activation_source == "validated_promotion"'
        in terraform
    )
    assert "AIOPS_CANARY_AUTHORIZATION_MANIFEST_SHA256" in terraform
    assert "AIOPS_DEFAULT_AUTHORIZATION_MANIFEST_SHA256" in terraform
    assert "AIOPS_API_IMAGE_DIGEST" in terraform
    assert "AIOPS_SOURCE_REVISION" in terraform
    assert "AIOPS_FOUNDRY_CANDIDATE_ARTIFACT_DIGEST" in terraform
    assert "AIOPS_FOUNDRY_CANDIDATE_BINDING_DIGEST" in terraform
    assert "AIOPS_COPILOT_STRICT_CANDIDATE_SHA256" not in terraform
    assert "AIOPS_COPILOT_CANDIDATE_RUNTIME_SHA256" not in terraform
    assert (
        "foundry_specialist_candidate_binding_sha256 == "
        "local.copilot_canary_authorization.candidate_binding.semantic_sha256"
        in terraform
    )
    assert (
        "foundry_specialist_candidate_binding_sha256 == "
        "local.copilot_default_authorization.candidate_binding.semantic_sha256"
        in terraform
    )
    assert 'value = "/app/config.yaml"' in terraform
    assert 'value = "/app/fabric.config.yaml"' in terraform
    assert "arg.config.deploy.yaml" in REVIEWED_TREE_ROOTS
    assert "fabric.config.deploy.yaml" in REVIEWED_TREE_ROOTS
    assert (
        "src/operations/copilot_default_authorization.v1.json"
        in REVIEWED_TREE_EXCLUDED_PATHS
    )
    assert "Dockerfile.default-promotion" in REVIEWED_TREE_ROOTS
    required_skill = "skills/operational-context-graph/SKILL.md"
    assert "!skills/**/SKILL.md" in dockerignore.splitlines()
    assert required_skill in reviewed_tree_paths(
        REPO_ROOT,
        REVIEWED_TREE_ROOTS,
        REVIEWED_TREE_EXCLUDED_PATHS,
    )
    assert '"src/operations/copilot_canary_authorization.v1.json"' in packaging
    assert '"src/operations/copilot_default_authorization.v1.json"' in packaging
    assert '"default_authorization_manifest_sha256"' in dockerfile
    assert "copilot_canary_validation_report" not in dockerfile
    assert "default_authorization_design_approval" not in dockerfile
    assert "copilot_default_authorization.v1.json" in build_script


def test_observable_api_image_digest_is_not_runtime_authority(
    tmp_path: Path,
) -> None:
    manifest_path, metadata_path, environment = _write_authorization(tmp_path)
    environment.pop("AIOPS_API_IMAGE_DIGEST")

    authority = authorization.validate_canary_authorization(
        environment=environment,
        manifest_path=manifest_path,
        build_metadata_path=metadata_path,
        reviewed_tree_root=REPO_ROOT,
        now=datetime(2026, 9, 21, tzinfo=UTC),
    )

    assert authority.authorization_id == "p11-canary-authorization-20260920"
