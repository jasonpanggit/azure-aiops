"""Shared test setup for routes that intentionally exercise authorized canary."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from operations import (
    copilot_canary_authorization,
    maf_orchestrator,
)
from operations.maf_orchestrator import CopilotRolloutDecision

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGED_MANIFEST = (
    REPO_ROOT / "src" / "operations" / "copilot_canary_authorization.v1.json"
)
SOURCE_REVISION = "a" * 40
AUTHORIZED_NOW = datetime(2026, 9, 21, tzinfo=UTC)


def install_valid_canary_evidence(monkeypatch) -> None:
    """Install valid lower-level authorization evidence without activating canary."""

    payload = json.loads(PACKAGED_MANIFEST.read_text(encoding="utf-8"))
    manifest_bytes = PACKAGED_MANIFEST.read_bytes()
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    reviewed_tree_sha256 = str(payload["reviewed_tree"]["sha256"])
    cache_root = REPO_ROOT / ".pytest_cache"
    cache_root.mkdir(exist_ok=True)
    evidence_directory = tempfile.TemporaryDirectory(
        prefix="canary-authorization-",
        dir=cache_root,
    )
    evidence_root = Path(evidence_directory.name)
    manifest_path = evidence_root / "authorization.json"
    metadata_path = evidence_root / "build-metadata.json"
    manifest_path.write_bytes(manifest_bytes)
    metadata_path.write_text(
        json.dumps(
            {
                "schema_version": "copilot-build-metadata.v1",
                "source_revision": SOURCE_REVISION,
                "canary_authorization_manifest_sha256": manifest_sha256,
                "reviewed_tree_sha256": reviewed_tree_sha256,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        copilot_canary_authorization,
        "_test_evidence_directory",
        evidence_directory,
        raising=False,
    )
    monkeypatch.setattr(
        copilot_canary_authorization,
        "AUTHORIZATION_MANIFEST_PATH",
        manifest_path,
    )
    monkeypatch.setattr(
        copilot_canary_authorization,
        "BUILD_METADATA_PATH",
        metadata_path,
    )
    monkeypatch.setattr(
        copilot_canary_authorization,
        "PACKAGED_REVIEWED_TREE_ROOT",
        REPO_ROOT,
    )

    def read_reviewed_tree_digest(root, include_roots, exclude_paths):
        assert root == REPO_ROOT
        assert tuple(include_roots) == tuple(payload["reviewed_tree"]["include_roots"])
        assert tuple(exclude_paths) == tuple(payload["reviewed_tree"]["exclude_paths"])
        return reviewed_tree_sha256

    monkeypatch.setattr(
        copilot_canary_authorization,
        "reviewed_tree_digest",
        read_reviewed_tree_digest,
    )
    monkeypatch.setattr(
        copilot_canary_authorization,
        "_utc_now",
        lambda: AUTHORIZED_NOW,
    )
    monkeypatch.setattr(maf_orchestrator, "_utc_now", lambda: AUTHORIZED_NOW)
    monkeypatch.setattr(maf_orchestrator, "_canary_bucket", lambda _stable_key: 0)

    target = payload["deployment_target"]
    project = payload["foundry_project"]
    scope = payload["authorization_scope"]
    binding = payload["candidate_binding"]
    shadow = payload["shadow_evidence"]
    environment = {
        "AIOPS_COPILOT_ROLLOUT_MODE": "compatibility",
        "AIOPS_COPILOT_CANARY_PERCENTAGE": "0",
        "AIOPS_COPILOT_ROLLBACK_MODE": str(scope["rollback_mode"]),
        "AIOPS_AGENT_ORCHESTRATION_MODE": str(scope["orchestration"]),
        "AIOPS_SPECIALIST_ACTIVATION_SOURCE": str(scope["activation_source"]),
        "AIOPS_SOURCE_REVISION": SOURCE_REVISION,
        "AIOPS_CANARY_AUTHORIZATION_MANIFEST_SHA256": manifest_sha256,
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
        "AIOPS_COPILOT_CANDIDATE_CONTRACT_VERSION": str(
            binding["contract_version"]
        ),
        "AIOPS_COPILOT_CANDIDATE_MANIFEST_SHA256": str(
            binding["manifest_sha256"]
        ),
        "AIOPS_COPILOT_STRICT_CANDIDATE_SHA256": str(
            binding["strict_candidate_sha256"]
        ),
        "AIOPS_COPILOT_CANDIDATE_RUNTIME_SHA256": str(binding["runtime_sha256"]),
        "AIOPS_COPILOT_PARSER_PROOF_SHA256": str(binding["parser_proof_sha256"]),
        "AIOPS_COPILOT_SERIALIZATION_PROOF_SHA256": str(
            binding["serialization_proof_sha256"]
        ),
        "AIOPS_SPECIALIST_MANIFEST_DIGEST": str(binding["manifest_sha256"]),
        "AIOPS_FOUNDRY_CANDIDATE_ARTIFACT_DIGEST": str(
            binding["strict_candidate_sha256"]
        ),
        "AIOPS_COPILOT_SHADOW_REVISION": str(shadow["revision"]),
        "AIOPS_COPILOT_SHADOW_IMAGE_DIGEST": str(shadow["image_digest"]),
        "AIOPS_COPILOT_SHADOW_REPORT_SHA256": str(shadow["report_sha256"]),
        "AIOPS_COPILOT_SHADOW_REPORT_INTEGRITY_SIGNATURE": str(
            shadow["report_integrity_signature"]
        ),
        "AIOPS_COPILOT_SHADOW_MATRIX_SHA256": str(shadow["matrix_sha256"]),
        "AIOPS_COPILOT_SHADOW_STATUS": str(shadow["shadow_status"]),
    }
    for agent in binding["agents"]:
        prefix = f"FOUNDRY_{str(agent['id']).upper()}_AGENT"
        environment[f"{prefix}_NAME"] = str(agent["agent_name"])
        environment[f"{prefix}_VERSION"] = str(agent["provider_version"])
    coordinator = binding["coordinator"]
    environment["FOUNDRY_AGENT_NAME"] = str(coordinator["agent_name"])
    environment["FOUNDRY_AGENT_VERSION"] = str(coordinator["provider_version"])
    for name, value in environment.items():
        monkeypatch.setenv(name, value)


def enable_authorized_canary(
    monkeypatch,
    *,
    canonical: bool = True,
    percentage: int = 10,
) -> None:
    """Activate real validation over controlled immutable test evidence."""

    install_valid_canary_evidence(monkeypatch)
    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "canary")
    monkeypatch.setenv("AIOPS_COPILOT_CANARY_PERCENTAGE", str(percentage))
    monkeypatch.setattr(
        maf_orchestrator,
        "_canary_bucket",
        lambda _stable_key: 0 if canonical else 99,
    )


def rollout_decision_for_test(
    *, principal_subject: str = "operator-a"
) -> CopilotRolloutDecision:
    """Resolve a canonical decision through the production validator."""

    os.environ["AIOPS_COPILOT_ROLLOUT_MODE"] = "canary"
    os.environ["AIOPS_COPILOT_CANARY_PERCENTAGE"] = "10"
    return maf_orchestrator.copilot_rollout_decision(
        stable_key=principal_subject,
    )


def route_authority_for_test(
    request,
    *,
    principal_subject: str = "operator-a",
    selection_snapshot=None,
    canonical_selection_snapshot=None,
):
    """Activate canary inputs; the service invokes the fixed authorizer."""

    del request, selection_snapshot, canonical_selection_snapshot
    os.environ["AIOPS_COPILOT_ROLLOUT_MODE"] = "canary"
    os.environ["AIOPS_COPILOT_CANARY_PERCENTAGE"] = "10"
    assert principal_subject
