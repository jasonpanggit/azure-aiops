"""Synthetic raw artifact checks; no test establishes deployed acceptance."""

import copy
import hashlib

import pytest

from ontology_discovery.isolated_acceptance_contract import ContractError
from scripts.validate_ontology_deployment_plan import PlanValidationError
from scripts.validate_ontology_discovery_live import EvidenceError, job_template_hash
from scripts.verify_isolated_acceptance_artifacts import (
    SemanticExpectations,
    verify_artifact_semantics,
)
from tests.test_isolated_acceptance_contract import UUID, encoded, fixture, load
from tests.test_ontology_deployment_plan import API_DIGEST, WEB_DIGEST, _plan


def raw_fixture():
    payload, artifacts = fixture()
    payload["image_pins"]["api"] = "synthetic.invalid/api@" + API_DIGEST
    payload["image_pins"]["web"] = "synthetic.invalid/web@" + WEB_DIGEST
    payload["protected"]["api_image"] = payload["image_pins"]["api"]
    expectations = {}
    jobs = {}
    for role, binding in payload["jobs"].items():
        env = [{"name": "AZURE_CLIENT_ID", "value": UUID}]
        if role == "validation_publisher":
            env += [
                {"name": "AIOPS_IDENTITY_CLASS", "value": "publisher"},
                {"name": "AIOPS_ONTOLOGY_PUBLISHER_CLIENT_ID", "value": UUID},
            ]
        job = {
            "id": binding["resource_id"],
            "name": binding["resource_id"].rsplit("/", 1)[1],
            "identity": {
                "type": "UserAssigned",
                "userAssignedIdentities": {
                    binding["identity_resource_id"]: {"clientId": UUID},
                },
            },
            "properties": {
                "configuration": {
                    "triggerType": "Manual",
                    "replicaRetryLimit": 0,
                    "replicaTimeout": 300,
                    "manualTriggerConfig": {
                        "parallelism": 1,
                        "replicaCompletionCount": 1,
                    },
                },
                "template": {
                    "containers": [
                        {
                            "name": role,
                            "image": binding["image"],
                            "command": ["python", "-m", "synthetic.offline"],
                            "args": ["run-once"],
                            "env": env,
                            "resources": {"cpu": 1, "memory": "2Gi"},
                        }
                    ]
                },
            },
        }
        jobs[role] = job
        expectations[role] = {
            "template_projection_hash": job_template_hash(job),
            "command": ["python", "-m", "synthetic.offline"],
            "args": ["run-once"],
            "timeout_seconds": 300,
            "environment_names": [row["name"] for row in env],
            "trigger": "Manual",
            "retry_limit": 0,
            "parallelism": 1,
            "completion_count": 1,
        }
    return payload, artifacts, jobs, expectations


def replace(artifacts, ref, body):
    artifacts[ref["key"]] = encoded(body)
    ref["sha256"] = "sha256:" + hashlib.sha256(artifacts[ref["key"]]).hexdigest()


def run(tmp_path, payload, artifacts, jobs, expectations, plans=None):
    for role, job in jobs.items():
        replace(artifacts, payload["jobs"][role]["template"], job)
    for environment in ("production", "validation"):
        replace(
            artifacts,
            payload[f"{environment}_plan"],
            (plans[environment] if plans else _plan(environment)),
        )
    load(tmp_path, payload, artifacts)
    expected = SemanticExpectations.model_validate(
        {
            "schema_version": "isolated-artifact-semantics/v1",
            "contract_digest": payload["contract_digest"],
            "jobs": expectations,
        }
    )
    return verify_artifact_semantics(
        tmp_path / "synthetic.json", artifacts=artifacts, expectations=expected
    )


def test_verifies_raw_legacy_plans_and_fixed_job_semantics(tmp_path):
    assert run(tmp_path, *raw_fixture()) == {
        "status": "semantic_subset_verified",
        "authority": "none",
    }


@pytest.mark.parametrize(
    "change", ["arm", "uai", "client", "command", "retry", "timeout", "image"]
)
def test_resealed_wrong_identity_and_template_semantics_rejected(tmp_path, change):
    payload, artifacts, jobs, expectations = raw_fixture()
    job = jobs["coordinator"]
    container = job["properties"]["template"]["containers"][0]
    if change == "arm":
        job["id"] += "-substituted"
    elif change == "uai":
        assigned = job["identity"]["userAssignedIdentities"]
        original = next(iter(assigned))
        assigned[original + "-substituted"] = assigned.pop(original)
    elif change == "client":
        next(iter(job["identity"]["userAssignedIdentities"].values()))["clientId"] = (
            "wrong"
        )
    elif change == "command":
        container["command"] = ["sh", "-c"]
    elif change == "retry":
        job["properties"]["configuration"]["replicaRetryLimit"] = 1
    elif change == "timeout":
        job["properties"]["configuration"]["replicaTimeout"] = 0
    else:
        container["image"] = payload["image_pins"]["api"]
    # Rehashing the observed projection cannot evade independent semantic pins.
    expectations["coordinator"]["template_projection_hash"] = job_template_hash(job)
    with pytest.raises(ContractError):
        run(tmp_path, payload, artifacts, jobs, expectations)


def test_stale_reviewed_template_projection_rejected(tmp_path):
    payload, artifacts, jobs, expectations = raw_fixture()
    jobs["coordinator"]["properties"]["template"]["containers"][0]["resources"][
        "cpu"
    ] = 2
    with pytest.raises(EvidenceError, match="hash mismatch"):
        run(tmp_path, payload, artifacts, jobs, expectations)


@pytest.mark.parametrize("change", ["delete", "unexpected-address", "distinct-worker"])
def test_reviewed_plan_substitution_keeps_existing_guardrails(tmp_path, change):
    payload, artifacts, jobs, expectations = raw_fixture()
    plans = {env: _plan(env) for env in ("production", "validation")}
    plan = plans["validation"]
    if change == "distinct-worker":
        worker = next(
            row
            for row in plan["planned_values"]["root_module"]["resources"]
            if row["address"] == "azurerm_container_app_job.ontology_discovery"
        )
        worker["values"]["template"][0]["container"][0]["image"] = (
            "synthetic.invalid/worker@sha256:" + "f" * 64
        )
    else:
        plan["resource_changes"].append(
            {
                "address": "azurerm_container_app.api"
                if change == "delete"
                else "unexpected.resource",
                "change": {"actions": ["delete"] if change == "delete" else ["create"]},
            }
        )
    with pytest.raises(PlanValidationError):
        run(tmp_path, payload, artifacts, jobs, expectations, plans)


def test_projection_only_artifact_cannot_prove_uai_association(tmp_path):
    payload, artifacts, jobs, expectations = raw_fixture()
    del jobs["coordinator"]["identity"]
    expectations["coordinator"]["template_projection_hash"] = job_template_hash(
        jobs["coordinator"]
    )
    with pytest.raises(ContractError):
        run(tmp_path, payload, artifacts, jobs, expectations)


def test_expectations_are_closed_and_must_bind_contract(tmp_path):
    from pydantic import ValidationError

    payload, artifacts, jobs, expectations = raw_fixture()
    invalid = copy.deepcopy(expectations)
    invalid["coordinator"]["extra"] = True
    with pytest.raises(ValidationError):
        run(tmp_path, payload, artifacts, jobs, invalid)


@pytest.mark.parametrize(
    "extra",
    [
        "identity",
        "container",
        "env",
        "secret",
        "init",
        "volume",
        "configuration",
    ],
)
def test_extras_are_not_stripped_and_errors_redact_values(tmp_path, extra):
    payload, artifacts, jobs, expectations = raw_fixture()
    job = jobs["coordinator"]
    container = job["properties"]["template"]["containers"][0]
    secret = "PRIVATE-VALUE-DO-NOT-LOG"
    if extra == "identity":
        job["identity"]["userAssignedIdentities"]["other-identity"] = {
            "clientId": secret
        }
    elif extra == "container":
        job["properties"]["template"]["containers"].append(copy.deepcopy(container))
    elif extra == "env":
        container["env"].append({"name": "UNREVIEWED", "value": secret})
    elif extra == "secret":
        container["env"][0]["secretRef"] = secret
    elif extra == "init":
        job["properties"]["template"]["initContainers"] = [{"command": [secret]}]
    elif extra == "volume":
        container["volumeMounts"] = [{"name": secret}]
    else:
        job["properties"]["configuration"]["secrets"] = [{"value": secret}]
    expectations["coordinator"]["template_projection_hash"] = job_template_hash(job)
    with pytest.raises(ContractError) as error:
        run(tmp_path, payload, artifacts, jobs, expectations)
    assert secret not in str(error.value)


def test_arm_identity_matching_is_exact_case_insensitive(tmp_path):
    payload, artifacts, jobs, expectations = raw_fixture()
    job = jobs["coordinator"]
    job["id"] = job["id"].upper()
    job["name"] = job["name"].upper()
    assigned = job["identity"]["userAssignedIdentities"]
    original = next(iter(assigned))
    assigned[original.upper()] = assigned.pop(original)
    expectations["coordinator"]["template_projection_hash"] = job_template_hash(job)
    assert run(tmp_path, payload, artifacts, jobs, expectations)["authority"] == "none"


def test_missing_raw_bytes_never_falls_back_to_cli(tmp_path, monkeypatch):
    import subprocess

    def forbidden(*args, **kwargs):
        raise AssertionError("no CLI allowed")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "check_output", forbidden)
    payload, artifacts, _jobs, expectations = raw_fixture()
    load(tmp_path, payload, artifacts)
    del artifacts[payload["jobs"]["coordinator"]["template"]["key"]]
    expected = SemanticExpectations.model_validate(
        {
            "schema_version": "isolated-artifact-semantics/v1",
            "contract_digest": payload["contract_digest"],
            "jobs": expectations,
        }
    )
    with pytest.raises(ContractError, match="artifact"):
        verify_artifact_semantics(
            tmp_path / "synthetic.json", artifacts=artifacts, expectations=expected
        )


@pytest.mark.parametrize(
    "change", ["args", "parallelism", "completion", "trigger", "duplicate-env"]
)
def test_resealed_template_cannot_override_explicit_settings(tmp_path, change):
    payload, artifacts, jobs, expectations = raw_fixture()
    job = jobs["coordinator"]
    container = job["properties"]["template"]["containers"][0]
    configuration = job["properties"]["configuration"]
    if change == "args":
        container["args"] = ["different"]
    elif change == "trigger":
        configuration["triggerType"] = "Schedule"
    elif change == "duplicate-env":
        container["env"].append(copy.deepcopy(container["env"][0]))
    else:
        key = "parallelism" if change == "parallelism" else "replicaCompletionCount"
        configuration["manualTriggerConfig"][key] = 2
    expectations["coordinator"]["template_projection_hash"] = job_template_hash(job)
    with pytest.raises(ContractError):
        run(tmp_path, payload, artifacts, jobs, expectations)


def test_expectations_for_different_contract_are_rejected(tmp_path):
    payload, artifacts, jobs, expectations = raw_fixture()
    run(tmp_path, payload, artifacts, jobs, expectations)
    expected = SemanticExpectations.model_validate(
        {
            "schema_version": "isolated-artifact-semantics/v1",
            "contract_digest": "sha256:" + "f" * 64,
            "jobs": expectations,
        }
    )
    with pytest.raises(ContractError, match="different contract"):
        verify_artifact_semantics(
            tmp_path / "synthetic.json", artifacts=artifacts, expectations=expected
        )
