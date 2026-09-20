from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest

from operations.foundry_agent import specialist_catalog
from operations.foundry_candidate_catalog import (
    CANDIDATE_ARTIFACT_DIGEST_ENV,
    CANDIDATE_ARTIFACT_ENV,
    CANDIDATE_BINDING_ALGORITHM,
    CANDIDATE_EXPECTED_NAMES_ENV,
    CANDIDATE_PROJECT_RESOURCE_ID_ENV,
    CANDIDATE_PROMPT_DIGESTS_ENV,
    MODEL_DEPLOYMENT_ENV,
    SEARCH_CONNECTION_ID_ENV,
    SEARCH_INDEX_NAME_ENV,
    SOURCE_REVISION_ENV,
    candidate_artifact_binding,
    validated_candidate_catalog,
)
from operations.specialist_manifest import (
    load_specialist_manifest,
    specialist_manifest_digest,
)

SOURCE_REVISION = "0123456789abcdef0123456789abcdef01234567"
GENERATED_AT = "2026-09-20T00:00:00+00:00"
REPO_ROOT = Path(__file__).resolve().parents[1]
MODEL_DEPLOYMENT = "gpt-4.1-prod"
SEARCH_CONNECTION_ID = (
    "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.CognitiveServices/"
    "accounts/account/projects/project/connections/ai-search"
)
SEARCH_INDEX_NAME = "aiops-knowledge"
LIVE_PROVIDER_VERSION_IDS = {
    "network": "16",
    "vulnerability": "17",
    "patch": "17",
    "incident": "16",
    "change": "17",
    "governance": "17",
    "remediation": "17",
    "executive_summary": "16",
    "inventory_data_health": "1",
    "identity_access": "1",
    "finops": "1",
    "resource_health_observability": "1",
}


def _candidate_artifact() -> dict:
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
    agents = {}
    for index, specialist in enumerate(manifest.specialists, start=1):
        agents[specialist.id] = {
            "agent_name": specialist.foundry.name,
            "provider_version_id": f"provider-{index}",
            "candidate_version": f"2026.09.{specialist.foundry.version}",
            "model_deployment": MODEL_DEPLOYMENT,
            "contract_model": specialist.foundry.model,
            "contract_version": specialist.foundry.version,
            "prompt_digest": f"{index:064x}",
            "tools": {
                "operations_mcp": list(specialist.operations_mcp_tools),
                "ai_search": {
                    "enabled": True,
                    "project_connection_id": SEARCH_CONNECTION_ID,
                    "index_name": SEARCH_INDEX_NAME,
                    "query_type": "vector_semantic_hybrid",
                    "cardinality": 1,
                },
            },
            "scope_policy": "specialist-scope.v1",
            "read_only": True,
            "mutation_authorized": False,
            "citation_contract": "citation-closure.v1",
            "timeout_seconds": 30.0,
            "fallback_mode": "deterministic_local",
            "publication_status": "published",
            "validation": {
                "status": "pass",
                "validated_at": "2026-09-20T00:01:00+00:00",
                "checks": dict(checks),
            },
        }
    return {
        "contract_version": "foundry-specialist-candidates.v1",
        "status": "validated",
        "promotion": "held",
        "reason": "available_inactive",
        "release": "2026.09",
        "manifest_digest": specialist_manifest_digest(),
        "source_revision": SOURCE_REVISION,
        "generated_at": GENERATED_AT,
        "project": {
            "resource_id": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.CognitiveServices/accounts/account/projects/project",
            "endpoint_host": "project.services.ai.azure.com",
        },
        "agents": agents,
        "coordinator": {
            "agent_name": "operations-copilot",
            "provider_version_id": "provider-coordinator",
            "candidate_version": "2026.09.coordinator",
            "publication_status": "published",
            "validation": {
                "status": "pass",
                "validated_at": "2026-09-20T00:01:00+00:00",
            },
        },
        "rollback_target": {},
        "rollback_coordinator": {},
    }


def _configure(monkeypatch, artifact: dict) -> None:
    manifest = load_specialist_manifest()
    raw = json.dumps(artifact)
    monkeypatch.setenv(CANDIDATE_ARTIFACT_ENV, raw)
    monkeypatch.setenv(
        CANDIDATE_ARTIFACT_DIGEST_ENV,
        sha256(raw.encode("utf-8")).hexdigest(),
    )
    monkeypatch.setenv(SOURCE_REVISION_ENV, SOURCE_REVISION)
    monkeypatch.setenv(MODEL_DEPLOYMENT_ENV, MODEL_DEPLOYMENT)
    monkeypatch.setenv(SEARCH_CONNECTION_ID_ENV, SEARCH_CONNECTION_ID)
    monkeypatch.setenv(SEARCH_INDEX_NAME_ENV, SEARCH_INDEX_NAME)
    monkeypatch.setenv(
        CANDIDATE_PROJECT_RESOURCE_ID_ENV,
        artifact["project"]["resource_id"],
    )
    monkeypatch.setenv(
        "FOUNDRY_PROJECT_ENDPOINT",
        "https://project.services.ai.azure.com/api/projects/project",
    )
    monkeypatch.setenv("FOUNDRY_AGENT_NAME", "operations-copilot")
    monkeypatch.setenv(
        CANDIDATE_EXPECTED_NAMES_ENV,
        json.dumps(
            {
                specialist.id: specialist.foundry.name
                for specialist in manifest.specialists
            }
        ),
    )
    monkeypatch.setenv(
        CANDIDATE_PROMPT_DIGESTS_ENV,
        json.dumps(
            {
                specialist.id: f"{index:064x}"
                for index, specialist in enumerate(
                    manifest.specialists,
                    start=1,
                )
            }
        ),
    )


def _rows(monkeypatch, artifact: dict) -> dict[str, dict]:
    _configure(monkeypatch, artifact)
    return validated_candidate_catalog(
        load_specialist_manifest(),
        now=datetime(2026, 9, 20, 1, tzinfo=UTC),
    )


def _live_candidate_artifact() -> dict:
    artifact = _candidate_artifact()
    artifact["coordinator"]["provider_version_id"] = "6"
    for specialist_id, provider_version_id in LIVE_PROVIDER_VERSION_IDS.items():
        artifact["agents"][specialist_id]["provider_version_id"] = (
            provider_version_id
        )
    return artifact


def _binding(artifact: dict) -> str:
    return candidate_artifact_binding(
        json.dumps(artifact),
        load_specialist_manifest(),
    ).sha256


def test_semantic_binding_excludes_only_release_cycle_metadata():
    artifact = _candidate_artifact()
    baseline = candidate_artifact_binding(
        json.dumps(artifact),
        load_specialist_manifest(),
    )
    artifact["source_revision"] = "f" * 40
    artifact["generated_at"] = "2026-09-20T00:02:00+00:00"
    artifact["coordinator"]["validation"]["validated_at"] = (
        "2026-09-20T00:03:00+00:00"
    )
    for candidate in artifact["agents"].values():
        candidate["validation"]["validated_at"] = "2026-09-20T00:04:00+00:00"
        candidate["tools"]["operations_mcp"].reverse()

    rebound = candidate_artifact_binding(
        json.dumps(artifact, sort_keys=True),
        load_specialist_manifest(),
    )

    assert baseline.algorithm == CANDIDATE_BINDING_ALGORITHM
    assert rebound.sha256 == baseline.sha256
    assert rebound.source_revision == "f" * 40


@pytest.mark.parametrize(
    "case",
    (
        "release",
        "project_resource",
        "project_endpoint",
        "model",
        "contract_model",
        "prompt",
        "grant",
        "connection",
        "scope",
        "citation",
        "timeout",
        "provider_version",
        "candidate_version",
        "agent_name",
        "coordinator_version",
    ),
)
def test_semantic_binding_changes_for_security_relevant_mutations(case):
    artifact = _candidate_artifact()
    baseline = _binding(artifact)
    network = artifact["agents"]["network"]
    if case == "release":
        artifact["release"] = "2026.10"
    elif case == "project_resource":
        artifact["project"]["resource_id"] += "-other"
    elif case == "project_endpoint":
        artifact["project"]["endpoint_host"] = "other.services.ai.azure.com"
    elif case == "model":
        network["model_deployment"] = "gpt-5.4-mini"
    elif case == "contract_model":
        network["contract_model"] = "gpt-5"
    elif case == "prompt":
        network["prompt_digest"] = "f" * 64
    elif case == "grant":
        network["tools"]["operations_mcp"][0] = "search"
    elif case == "connection":
        network["tools"]["ai_search"]["project_connection_id"] = (
            SEARCH_CONNECTION_ID.replace("/connections/", "/connections/other-")
        )
    elif case == "scope":
        network["scope_policy"] = "specialist-scope.v2"
    elif case == "citation":
        network["citation_contract"] = "citation-closure.v2"
    elif case == "timeout":
        network["timeout_seconds"] = 31.0
    elif case == "provider_version":
        network["provider_version_id"] = "provider-new"
    elif case == "candidate_version":
        network["candidate_version"] = "2026.09.2"
    elif case == "agent_name":
        network["agent_name"] = "network-other"
    elif case == "coordinator_version":
        artifact["coordinator"]["provider_version_id"] = "coordinator-new"

    assert _binding(artifact) != baseline


@pytest.mark.parametrize(
    "case",
    (
        "read_only",
        "mutation_authorized",
        "fallback",
        "publication",
        "validation_result",
        "coordinator_publication",
        "coordinator_validation",
        "duplicate_grant",
        "missing_agent",
        "extra_agent",
        "extra_field",
    ),
)
def test_semantic_binding_rejects_invalid_or_ambiguous_artifacts(case):
    artifact = _candidate_artifact()
    network = artifact["agents"]["network"]
    if case == "read_only":
        network["read_only"] = False
    elif case == "mutation_authorized":
        network["mutation_authorized"] = True
    elif case == "fallback":
        network["fallback_mode"] = "remote"
    elif case == "publication":
        network["publication_status"] = "draft"
    elif case == "validation_result":
        network["validation"]["checks"]["scope"] = "fail"
    elif case == "coordinator_publication":
        artifact["coordinator"]["publication_status"] = "draft"
    elif case == "coordinator_validation":
        artifact["coordinator"]["validation"]["status"] = "fail"
    elif case == "duplicate_grant":
        network["tools"]["operations_mcp"].append(
            network["tools"]["operations_mcp"][0]
        )
    elif case == "missing_agent":
        artifact["agents"].pop("network")
    elif case == "extra_agent":
        artifact["agents"]["unexpected"] = dict(network)
    elif case == "extra_field":
        network["unreviewed"] = True

    with pytest.raises(ValueError):
        _binding(artifact)


def test_semantic_binding_rejects_duplicate_json_keys():
    raw = json.dumps(_candidate_artifact())
    duplicated = raw.replace(
        '"status": "validated"',
        '"status": "validated", "status": "validated"',
        1,
    )

    with pytest.raises(ValueError, match="strict JSON"):
        candidate_artifact_binding(duplicated, load_specialist_manifest())


def test_validated_candidate_artifact_projects_exact_twelve_rows(monkeypatch):
    rows = _rows(monkeypatch, _candidate_artifact())

    assert tuple(rows) == load_specialist_manifest().specialist_ids
    assert all(row["source"] == "validated_candidate_artifact" for row in rows.values())


def test_invalid_candidate_row_fails_closed_without_hiding_valid_rows(monkeypatch):
    artifact = _candidate_artifact()
    artifact["agents"]["network"]["validation"]["checks"]["scope"] = "fail"

    rows = _rows(monkeypatch, artifact)

    assert "network" not in rows
    assert len(rows) == 11

    wrong_connection = _candidate_artifact()
    wrong_connection["agents"]["network"]["tools"]["ai_search"][
        "project_connection_id"
    ] = SEARCH_CONNECTION_ID.replace("/subscriptions/sub/", "/subscriptions/SUB/")
    rows = _rows(monkeypatch, wrong_connection)
    assert "network" not in rows
    assert len(rows) == 11


def test_injected_azure_mcp_metadata_fails_only_that_row(monkeypatch):
    artifact = _candidate_artifact()
    artifact["agents"]["network"]["tools"]["azure_mcp"] = ["subscription_list"]

    rows = _rows(monkeypatch, artifact)

    assert "network" not in rows
    assert len(rows) == 11


def test_ai_search_mismatch_and_malformed_booleans_fail_only_that_row(monkeypatch):
    mismatched = _candidate_artifact()
    mismatched["agents"]["network"]["tools"]["ai_search"]["index_name"] = (
        "other-index"
    )
    rows = _rows(monkeypatch, mismatched)
    assert "network" not in rows
    assert len(rows) == 11

    malformed = _candidate_artifact()
    malformed["agents"]["network"]["tools"]["ai_search"]["enabled"] = 1
    malformed["agents"]["network"]["read_only"] = 1
    malformed["agents"]["network"]["mutation_authorized"] = 0
    rows = _rows(monkeypatch, malformed)
    assert "network" not in rows
    assert len(rows) == 11


def test_current_model_prompt_and_artifact_digest_mismatches_fail_closed(
    monkeypatch,
):
    artifact = _candidate_artifact()
    _configure(monkeypatch, artifact)
    monkeypatch.setenv(MODEL_DEPLOYMENT_ENV, "wrong-model")
    assert validated_candidate_catalog(load_specialist_manifest()) == {}

    _configure(monkeypatch, artifact)
    prompt_digests = json.loads(os.environ[CANDIDATE_PROMPT_DIGESTS_ENV])
    prompt_digests["network"] = "f" * 64
    monkeypatch.setenv(CANDIDATE_PROMPT_DIGESTS_ENV, json.dumps(prompt_digests))
    rows = validated_candidate_catalog(load_specialist_manifest())
    assert "network" not in rows
    assert len(rows) == 11

    _configure(monkeypatch, artifact)
    monkeypatch.setenv(CANDIDATE_ARTIFACT_DIGEST_ENV, "0" * 64)
    assert validated_candidate_catalog(load_specialist_manifest()) == {}


def test_same_provider_version_is_valid_for_distinct_agents(monkeypatch):
    artifact = _candidate_artifact()
    duplicate = artifact["agents"]["network"]["provider_version_id"]
    artifact["agents"]["vulnerability"]["provider_version_id"] = duplicate.upper()

    rows = _rows(monkeypatch, artifact)

    assert len(rows) == 12
    assert rows["network"]["provider_version_id"].casefold() == duplicate.casefold()
    assert rows["vulnerability"]["provider_version_id"].casefold() == duplicate.casefold()


@pytest.mark.parametrize(
    "provider_version_id",
    [
        " provider-1",
        "provider-1 ",
        "provider/id",
        "client_secret=supersecret",
        "client_secret-supersecret",
        "token-abc",
        "apiKey-deadbeef",
        "privateKey-deadbeef",
        "connection_string-value",
        "api--key-deadbeef",
        "private..key-deadbeef",
        "connection:-string-value",
        "latest",
        "provider id",
        "",
    ],
)
def test_malformed_specialist_provider_id_fails_only_that_row(
    monkeypatch,
    provider_version_id,
):
    artifact = _candidate_artifact()
    artifact["agents"]["network"]["provider_version_id"] = provider_version_id

    rows = _rows(monkeypatch, artifact)

    assert "network" not in rows
    assert len(rows) == 11


@pytest.mark.parametrize("identity_source", ["agent_name", "candidate_version"])
def test_specialist_provider_id_rejects_non_provider_identity(
    monkeypatch,
    identity_source,
):
    artifact = _candidate_artifact()
    artifact["agents"]["network"]["provider_version_id"] = artifact["agents"][
        "network"
    ][identity_source]

    rows = _rows(monkeypatch, artifact)

    assert "network" not in rows
    assert len(rows) == 11


@pytest.mark.parametrize(
    "provider_version_id",
    [
        " coordinator-1",
        "coordinator-1 ",
        "coordinator/id",
        "client_secret=supersecret",
        "client_secret-supersecret",
        "token-abc",
        "apiKey-deadbeef",
        "privateKey-deadbeef",
        "connection_string-value",
        "api--key-deadbeef",
        "private..key-deadbeef",
        "connection:-string-value",
        "",
        "latest",
    ],
)
def test_malformed_coordinator_provider_id_fails_whole_artifact(
    monkeypatch,
    provider_version_id,
):
    artifact = _candidate_artifact()
    artifact["coordinator"]["provider_version_id"] = provider_version_id

    assert _rows(monkeypatch, artifact) == {}


@pytest.mark.parametrize("identity_source", ["agent_name", "candidate_version"])
def test_coordinator_provider_id_rejects_non_provider_identity(
    monkeypatch,
    identity_source,
):
    artifact = _candidate_artifact()
    artifact["coordinator"]["provider_version_id"] = artifact["coordinator"][
        identity_source
    ]

    assert _rows(monkeypatch, artifact) == {}


def test_coordinator_may_share_version_number_with_specialist(monkeypatch):
    artifact = _candidate_artifact()
    artifact["coordinator"]["provider_version_id"] = artifact["agents"]["network"][
        "provider_version_id"
    ].upper()

    assert len(_rows(monkeypatch, artifact)) == 12


def test_malformed_coordinator_name_invalidates_whole_artifact(
    monkeypatch,
):
    artifact = _candidate_artifact()
    artifact["coordinator"]["agent_name"] = "wrong-coordinator"

    assert _rows(monkeypatch, artifact) == {}


def test_duplicate_expected_agent_names_fail_closed(
    monkeypatch,
):
    artifact = _candidate_artifact()
    duplicate_name = artifact["agents"]["network"]["agent_name"]
    artifact["agents"]["vulnerability"]["agent_name"] = duplicate_name
    _configure(monkeypatch, artifact)
    expected_names = json.loads(os.environ[CANDIDATE_EXPECTED_NAMES_ENV])
    expected_names["vulnerability"] = duplicate_name
    monkeypatch.setenv(CANDIDATE_EXPECTED_NAMES_ENV, json.dumps(expected_names))

    assert validated_candidate_catalog(load_specialist_manifest()) == {}


def test_duplicate_qualified_identity_invalidates_whole_artifact(
    monkeypatch,
):
    artifact = _candidate_artifact()
    vulnerability = artifact["agents"]["vulnerability"]
    artifact["agents"]["network"]["agent_name"] = (
        f" {vulnerability['agent_name'].upper()} "
    )
    artifact["agents"]["network"]["provider_version_id"] = vulnerability[
        "provider_version_id"
    ].upper()

    assert _rows(monkeypatch, artifact) == {}


def test_coordinator_qualified_identity_collision_invalidates_whole_artifact(
    monkeypatch,
):
    artifact = _candidate_artifact()
    artifact["agents"]["network"]["agent_name"] = artifact["coordinator"][
        "agent_name"
    ]
    artifact["agents"]["network"]["provider_version_id"] = artifact["coordinator"][
        "provider_version_id"
    ]

    assert _rows(monkeypatch, artifact) == {}


def test_tampered_coordinator_stamp_cannot_hide_synthetic_provider_id(monkeypatch):
    artifact = _candidate_artifact()
    artifact["coordinator"]["provider_version_id"] = "2026.09.coordinator"
    artifact["coordinator"]["candidate_version"] = "not-the-synthetic-stamp"

    assert _rows(monkeypatch, artifact) == {}


def test_numeric_provider_ids_are_valid(monkeypatch):
    artifact = _candidate_artifact()
    artifact["agents"]["network"]["provider_version_id"] = "123"
    artifact["coordinator"]["provider_version_id"] = "456"

    rows = _rows(monkeypatch, artifact)

    assert len(rows) == 12
    assert rows["network"]["provider_version_id"] == "123"


def test_live_provider_version_distribution_projects_all_twelve_rows(monkeypatch):
    rows = _rows(monkeypatch, _live_candidate_artifact())

    assert tuple(rows) == load_specialist_manifest().specialist_ids
    assert {
        specialist_id: row["provider_version_id"]
        for specialist_id, row in rows.items()
    } == LIVE_PROVIDER_VERSION_IDS


def test_stale_or_partial_artifact_fails_as_a_whole(monkeypatch):
    stale = _candidate_artifact()
    stale["source_revision"] = "abcdef0123456789"
    assert _rows(monkeypatch, stale) == {}

    partial = _candidate_artifact()
    partial["agents"].pop("network")
    assert _rows(monkeypatch, partial) == {}


def test_manifest_mismatch_and_unknown_top_level_fields_fail_closed(monkeypatch):
    mismatched = _candidate_artifact()
    mismatched["manifest_digest"] = "0" * 64
    assert _rows(monkeypatch, mismatched) == {}

    widened = _candidate_artifact()
    widened["azure_mcp_connection_id"] = "/connections/azure-mcp"
    assert _rows(monkeypatch, widened) == {}

    project_mismatch = _candidate_artifact()
    _configure(monkeypatch, project_mismatch)
    monkeypatch.setenv(
        CANDIDATE_PROJECT_RESOURCE_ID_ENV,
        "/subscriptions/other/resourceGroups/rg/providers/Microsoft.CognitiveServices/accounts/account/projects/project",
    )
    assert validated_candidate_catalog(load_specialist_manifest()) == {}


def test_candidate_catalog_never_sets_runtime_configured(monkeypatch):
    artifact = _live_candidate_artifact()
    _configure(monkeypatch, artifact)
    for specialist in load_specialist_manifest().specialists:
        monkeypatch.setenv(
            f"FOUNDRY_{specialist.id.upper()}_AGENT_NAME",
            specialist.foundry.name,
        )
        monkeypatch.delenv(
            f"FOUNDRY_{specialist.id.upper()}_AGENT_VERSION",
            raising=False,
        )
    monkeypatch.setenv("AIOPS_SPECIALIST_ACTIVATION_SOURCE", "legacy_unversioned")
    monkeypatch.setenv("AIOPS_FOUNDRY_VERSION_PINNING_REQUIRED", "true")

    catalog = specialist_catalog()

    assert len(catalog) == 12
    assert all(row["status"] == "available_inactive" for row in catalog)
    assert all(row["configured"] is False for row in catalog)


def test_exact_validated_runtime_mapping_is_active(monkeypatch):
    artifact = _candidate_artifact()
    _configure(monkeypatch, artifact)
    network = artifact["agents"]["network"]
    monkeypatch.setenv("FOUNDRY_NETWORK_AGENT_NAME", network["agent_name"])
    monkeypatch.setenv(
        "FOUNDRY_NETWORK_AGENT_VERSION",
        network["provider_version_id"],
    )
    monkeypatch.setenv("AIOPS_SPECIALIST_ACTIVATION_SOURCE", "validated_promotion")
    monkeypatch.setenv("AIOPS_FOUNDRY_VERSION_PINNING_REQUIRED", "true")

    by_id = {row["id"]: row for row in specialist_catalog()}

    assert by_id["network"]["status"] == "active"
    assert by_id["network"]["configured"] is True
    assert by_id["vulnerability"]["status"] == "available_inactive"
    assert by_id["vulnerability"]["configured"] is False


def test_validated_active_mapping_does_not_depend_on_held_candidate_metadata(
    monkeypatch,
):
    monkeypatch.delenv(CANDIDATE_ARTIFACT_ENV, raising=False)
    monkeypatch.setenv(
        "FOUNDRY_PROJECT_ENDPOINT",
        "https://project.services.ai.azure.com/api/projects/project",
    )
    monkeypatch.setenv("FOUNDRY_NETWORK_AGENT_NAME", "network")
    monkeypatch.setenv("FOUNDRY_NETWORK_AGENT_VERSION", "provider-active")
    monkeypatch.setenv("AIOPS_SPECIALIST_ACTIVATION_SOURCE", "validated_promotion")
    monkeypatch.setenv("AIOPS_FOUNDRY_VERSION_PINNING_REQUIRED", "true")

    by_id = {row["id"]: row for row in specialist_catalog()}

    assert by_id["network"]["status"] == "active"
    assert by_id["network"]["configured"] is True
    assert by_id["vulnerability"]["status"] == "unavailable"
    assert by_id["vulnerability"]["configured"] is False


def test_terraform_wires_catalog_metadata_without_active_version_values():
    variables = (REPO_ROOT / "infra/terraform/variables.tf").read_text(
        encoding="utf-8"
    )
    foundry = (REPO_ROOT / "infra/terraform/foundry.tf").read_text(
        encoding="utf-8"
    )
    container = (REPO_ROOT / "infra/terraform/container_apps.tf").read_text(
        encoding="utf-8"
    )

    assert 'variable "foundry_specialist_candidate_catalog_artifact"' in variables
    assert (
        'variable "foundry_specialist_candidate_catalog_artifact_sha256"'
        in variables
    )
    assert 'variable "foundry_specialist_candidate_binding_sha256"' in variables
    assert 'variable "foundry_specialist_candidate_prompt_digests"' in variables
    assert 'variable "deployment_source_revision"' in variables
    assert 'variable "foundry_specialist_activation_target"' in variables
    activation_block = variables[
        variables.index('variable "foundry_specialist_activation_target"') :
    ]
    assert 'default     = "legacy"' in activation_block.split("\n}\n", 1)[0]

    assert 'name  = "AIOPS_FOUNDRY_CANDIDATE_ARTIFACT"' in container
    assert 'name  = "AIOPS_FOUNDRY_CANDIDATE_ARTIFACT_DIGEST"' in container
    assert 'name  = "AIOPS_FOUNDRY_CANDIDATE_BINDING_DIGEST"' in container
    assert 'name  = "AIOPS_FOUNDRY_CANDIDATE_EXPECTED_NAMES"' in container
    assert 'name  = "AIOPS_FOUNDRY_CANDIDATE_PROMPT_DIGESTS"' in container
    assert 'name  = "AIOPS_SOURCE_REVISION"' in container
    assert 'name  = "AIOPS_FOUNDRY_PROJECT_RESOURCE_ID"' in container
    assert 'name  = "AIOPS_FOUNDRY_MODEL_DEPLOYMENT"' in container
    assert 'name  = "AIOPS_FOUNDRY_AI_SEARCH_CONNECTION_ID"' in container
    assert 'name  = "AIOPS_FOUNDRY_AI_SEARCH_INDEX_NAME"' in container
    assert "if agent.version != \"\"" in container
    assert 'version = ""' in foundry
    assert 'source  = "legacy_unversioned"' in foundry


def test_catalog_metadata_does_not_modify_candidate_publication_triggers():
    foundry = (REPO_ROOT / "infra/terraform/foundry.tf").read_text(
        encoding="utf-8"
    )
    publication = foundry[
        foundry.index('resource "terraform_data" "foundry_agent"') :
        foundry.index('resource "terraform_data" "foundry_coordinator_candidate"')
    ]

    assert "foundry_candidate_catalog" not in publication
    assert "AIOPS_FOUNDRY_CANDIDATE_ARTIFACT" not in publication
