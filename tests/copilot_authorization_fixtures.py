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
from operations.specialist_manifest import (
    load_specialist_manifest,
    specialist_manifest_digest,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGED_MANIFEST = (
    REPO_ROOT / "src" / "operations" / "copilot_canary_authorization.v1.json"
)
PACKAGED_DEFAULT_MANIFEST = (
    REPO_ROOT / "src" / "operations" / "copilot_default_authorization.v1.json"
)
SOURCE_REVISION = "a" * 40
CANARY_BASE_IMAGE_DIGEST = f"sha256:{'b' * 64}"
AUTHORIZED_NOW = datetime(2026, 9, 21, 2, tzinfo=UTC)
_PROVIDER_VERSIONS = {
    "change": "17",
    "executive_summary": "16",
    "finops": "1",
    "governance": "17",
    "identity_access": "1",
    "incident": "16",
    "inventory_data_health": "1",
    "network": "16",
    "patch": "17",
    "remediation": "17",
    "resource_health_observability": "1",
    "vulnerability": "17",
}
_PROMPT_DIGESTS = {
    "change": "f5bd4b600c7dd5db6a6e9eab83c7cae615d4c9cd0d731724812ba596860ae9f8",
    "executive_summary": "6a5b0ac929ddd7ef893b7113c38f6cb38fa41231e5b61656526416d1eaf8d8e7",
    "finops": "e49abaa747f2ec6dec245231f098b3d490e049027b36f40660a535b29a7684c4",
    "governance": "a786d8fab42fcff387a89a2da64be0f1032ff71ab28b566b6c801a1326318b37",
    "identity_access": "db8c85b2baf0a15ad1652d8d1a49dc593c4436f6a41862d8b155ea43ae891755",
    "incident": "da8636baf5c6ef5ee92cb6c3675b9970504c2bf20909cc74c494e39dd7d833a2",
    "inventory_data_health": "2741a98dabf398861d34e6750eb28e0ac80da79429f0ad0dd027ee83573f763f",
    "network": "2e5624865daa12c09a98ad579375952b176b1c4e032727911642052ede89184d",
    "patch": "293e1d951cbbdaa2948e7094d696288b50ce8b3968f3fa529d3632aa8dab3f48",
    "remediation": "f29b802c3bf3c7b304697700a0684b9be954d97e367bccfaf6471d827d9e50bf",
    "resource_health_observability": "bc9c0ec5e9aaab63b963c8f696d28e6b7e8cd0d87650ebbe4291e5167663b7ae",
    "vulnerability": "2be9e625b46ca7391bf6044f44e72b943c37f9bf95ee361fc7e99d0b70b23b2d",
}
_CANDIDATE_RELEASE = "p11-noazmcp-20260920T093238Z-c562f00e33d7"
_PROJECT_RESOURCE_ID = (
    "/subscriptions/a87a8e64-a52a-4aa8-a760-5e8919d23cd1/"
    "resourceGroups/aiops-dev-rg/providers/Microsoft.CognitiveServices/"
    "accounts/aiops-dev-foundry/projects/aiops-dev-ops"
)
_SEARCH_CONNECTION_ID = f"{_PROJECT_RESOURCE_ID}/connections/aiops-dev-ai-search"


def strict_candidate_artifact(
    *,
    source_revision: str = SOURCE_REVISION,
    generated_at: str = "2026-09-20T23:12:57.137515Z",
    validated_at: str = "2026-09-20T23:12:57.137515Z",
) -> dict[str, object]:
    """Build the exact reviewed strict candidate semantics for tests."""

    manifest = load_specialist_manifest()
    checks = {
        "identity": "pass",
        "project": "pass",
        "model": "pass",
        "manifest": "pass",
        "prompt": "pass",
        "tool_grants": "pass",
        "scope": "pass",
        "read_only": "pass",
        "citations": "pass",
        "latency": "pass",
        "errors": "pass",
        "fallback": "pass",
    }
    agents = {
        specialist.id: {
            "agent_name": f"aiops-{specialist.foundry.name}-agent",
            "provider_version_id": _PROVIDER_VERSIONS[specialist.id],
            "candidate_version": (f"{_CANDIDATE_RELEASE}.{specialist.foundry.version}"),
            "model_deployment": "gpt-5.4-mini",
            "contract_model": specialist.foundry.model,
            "contract_version": specialist.foundry.version,
            "prompt_digest": _PROMPT_DIGESTS[specialist.id],
            "tools": {
                "operations_mcp": list(specialist.operations_mcp_tools),
                "ai_search": {
                    "enabled": True,
                    "project_connection_id": _SEARCH_CONNECTION_ID,
                    "index_name": "aiops-knowledge",
                    "query_type": "vector_semantic_hybrid",
                    "cardinality": 1,
                },
            },
            "scope_policy": "specialist-manifest.v1",
            "read_only": True,
            "mutation_authorized": False,
            "citation_contract": "network-finding.v1/output-contract.1",
            "timeout_seconds": 30,
            "fallback_mode": "deterministic_local",
            "publication_status": "published",
            "validation": {
                "status": "pass",
                "validated_at": validated_at,
                "checks": dict(checks),
            },
        }
        for specialist in manifest.specialists
    }
    return {
        "contract_version": "foundry-specialist-candidates.v1",
        "status": "validated",
        "promotion": "held",
        "reason": "available_inactive",
        "release": _CANDIDATE_RELEASE,
        "manifest_digest": specialist_manifest_digest(),
        "source_revision": source_revision,
        "generated_at": generated_at,
        "project": {
            "resource_id": _PROJECT_RESOURCE_ID,
            "endpoint_host": "aiops-dev-ai-g6ludc.services.ai.azure.com",
        },
        "agents": agents,
        "coordinator": {
            "agent_name": "operations-copilot",
            "provider_version_id": "6",
            "candidate_version": f"{_CANDIDATE_RELEASE}.coordinator",
            "publication_status": "published",
            "validation": {
                "status": "pass",
                "validated_at": validated_at,
            },
        },
        "rollback_target": {},
        "rollback_coordinator": {},
    }


def install_valid_canary_evidence(monkeypatch) -> None:
    """Install valid lower-level authorization evidence without activating canary."""

    payload = json.loads(PACKAGED_MANIFEST.read_text(encoding="utf-8"))
    manifest_bytes = PACKAGED_MANIFEST.read_bytes()
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    default_manifest_payload = json.loads(
        PACKAGED_DEFAULT_MANIFEST.read_text(encoding="utf-8")
    )
    default_manifest_payload["status"] = "AUTHORIZED"
    reviewed_tree_sha256 = str(payload["reviewed_tree"]["sha256"])
    default_manifest_payload["reviewed_tree"]["sha256"] = reviewed_tree_sha256  # type: ignore[index]
    default_manifest_payload["canary_evidence"].update(  # type: ignore[union-attr]
        {
            "source_revision": SOURCE_REVISION,
            "image_digest": CANARY_BASE_IMAGE_DIGEST,
            "reviewed_tree_sha256": reviewed_tree_sha256,
        }
    )
    lineage = default_manifest_payload["promotion_lineage"]
    assert isinstance(lineage, dict)
    lineage.update(
        {
            "base_source_revision": SOURCE_REVISION,
            "base_image_digest": CANARY_BASE_IMAGE_DIGEST,
            "equivalent_reviewed_tree_sha256": reviewed_tree_sha256,
        }
    )
    proof_payload = {
        key: value for key, value in lineage.items() if key != "equivalence_proof"
    }
    lineage["equivalence_proof"]["sha256"] = hashlib.sha256(  # type: ignore[index]
        json.dumps(
            proof_payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    default_manifest_bytes = json.dumps(
        default_manifest_payload,
        sort_keys=True,
    ).encode()
    default_manifest_sha256 = hashlib.sha256(default_manifest_bytes).hexdigest()
    cache_root = REPO_ROOT / ".pytest_cache"
    cache_root.mkdir(exist_ok=True)
    evidence_directory = tempfile.TemporaryDirectory(
        prefix="canary-authorization-",
        dir=cache_root,
    )
    evidence_root = Path(evidence_directory.name)
    manifest_path = evidence_root / "authorization.json"
    default_manifest_path = evidence_root / "default-authorization.json"
    metadata_path = evidence_root / "build-metadata.json"
    manifest_path.write_bytes(manifest_bytes)
    default_manifest_path.write_bytes(default_manifest_bytes)
    metadata_path.write_text(
        json.dumps(
            {
                "schema_version": "copilot-build-metadata.v1",
                "source_revision": SOURCE_REVISION,
                "canary_authorization_manifest_sha256": manifest_sha256,
                "default_authorization_manifest_sha256": default_manifest_sha256,
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
        "DEFAULT_AUTHORIZATION_MANIFEST_PATH",
        default_manifest_path,
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
    candidate = strict_candidate_artifact()
    candidate_raw = json.dumps(candidate, sort_keys=True)
    candidate_transport_sha256 = hashlib.sha256(candidate_raw.encode()).hexdigest()
    environment = {
        "AIOPS_COPILOT_ROLLOUT_MODE": "compatibility",
        "AIOPS_COPILOT_CANARY_PERCENTAGE": "0",
        "AIOPS_COPILOT_ROLLBACK_MODE": str(scope["rollback_mode"]),
        "AIOPS_AGENT_ORCHESTRATION_MODE": str(scope["orchestration"]),
        "AIOPS_SPECIALIST_ACTIVATION_SOURCE": str(scope["activation_source"]),
        "AIOPS_SOURCE_REVISION": SOURCE_REVISION,
        "AIOPS_FOUNDRY_CANDIDATE_ARTIFACT": candidate_raw,
        "AIOPS_FOUNDRY_CANDIDATE_ARTIFACT_DIGEST": candidate_transport_sha256,
        "AIOPS_FOUNDRY_CANDIDATE_BINDING_DIGEST": str(binding["semantic_sha256"]),
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


def enable_authorized_default(monkeypatch) -> None:
    """Activate full canonical rollout through the separate default authority."""

    install_valid_canary_evidence(monkeypatch)
    default_payload = json.loads(
        copilot_canary_authorization.DEFAULT_AUTHORIZATION_MANIFEST_PATH.read_text(
            encoding="utf-8"
        )
    )
    default_reviewed_tree_sha256 = str(
        default_payload["canary_evidence"]["reviewed_tree_sha256"]
    )
    metadata = json.loads(
        copilot_canary_authorization.BUILD_METADATA_PATH.read_text(encoding="utf-8")
    )
    metadata["reviewed_tree_sha256"] = default_reviewed_tree_sha256
    metadata["source_revision"] = default_payload["promotion_lineage"][  # type: ignore[index]
        "base_source_revision"
    ]
    metadata["default_promotion"] = default_payload["promotion_lineage"]
    copilot_canary_authorization.BUILD_METADATA_PATH.write_text(
        json.dumps(metadata),
        encoding="utf-8",
    )

    monkeypatch.setenv(
        "AIOPS_DEFAULT_AUTHORIZATION_MANIFEST_SHA256",
        hashlib.sha256(
            copilot_canary_authorization.DEFAULT_AUTHORIZATION_MANIFEST_PATH.read_bytes()
        ).hexdigest(),
    )
    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "default")
    monkeypatch.setenv("AIOPS_COPILOT_CANARY_PERCENTAGE", "100")


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
