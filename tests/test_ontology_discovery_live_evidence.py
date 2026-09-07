from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from scripts.validate_ontology_discovery_live import (
    DEPLOYED_LIFECYCLE_SEQUENCE,
    DEPLOYED_STAGES,
    EXPECTED_CURATOR_TOOLS,
    FIXED_JOB_NAMES,
    EvidenceError,
    _parser,
    assert_fixed_template,
    assert_stage_transition,
    build_job_start_command,
    evaluate_lifecycle_evidence,
    evaluate_publication_evidence,
    expand_role_actions,
    isolated_azure_environment,
    job_template_hash,
    load_plan19_deployment_contract,
    load_resume_checkpoint,
    main,
    sanitize_deployed_evidence,
    validate_azure_contexts,
    write_resume_checkpoint,
)


def _template() -> dict[str, object]:
    return {
        "properties": {
            "configuration": {
                "replicaTimeout": 900,
                "replicaRetryLimit": 2,
                "manualTriggerConfig": {"parallelism": 1, "replicaCompletionCount": 1},
            },
            "template": {
                "containers": [
                    {
                        "name": "ontology",
                        "image": "registry.invalid/api@sha256:" + ("a" * 64),
                        "command": ["python", "-m", "ontology_discovery.runtime"],
                        "args": ["fixture-prepare"],
                        "env": [
                            {"name": "AIOPS_ENVIRONMENT", "value": "validation"},
                            {
                                "name": "TOKEN",
                                "secretRef": "ontology-token",
                            },
                        ],
                    }
                ]
            },
            "identity": {"type": "UserAssigned", "userAssignedIdentities": {"x": {}}},
            "triggerType": "Manual",
        }
    }


def _complete_lifecycle() -> dict[str, object]:
    records = ["sha256:" + char * 64 for char in ("1", "2", "3")]
    return {
        "sequence": list(DEPLOYED_LIFECYCLE_SEQUENCE),
        "environment": "validation",
        "credentials": {
            "contexts_distinct": True,
            "modes": {"deployer": "0700", "evidence": "0700"},
            "ambient_credentials_removed": True,
            "identity_hashes": {
                "deployer": "sha256:" + "8" * 64,
                "evidence": "sha256:" + "9" * 64,
            },
            "deployer_actions": ["job_read", "job_start", "job_execution_read"],
            "evidence_actions": ["arg_read", "fabric_read", "onelake_read"],
            "evidence_denied_actions": [
                "job_execution_read",
                "job_read",
                "job_start",
                "job_stop",
                "mutation",
            ],
            "runtime_job_start_grants": [],
        },
        "templates": {
            name: {
                "before": f"sha256:{index:064x}",
                "expected": f"sha256:{index:064x}",
                "after": f"sha256:{index:064x}",
                "override_fields": [],
            }
            for index, name in enumerate(FIXED_JOB_NAMES, start=1)
        },
        "prepare": {
            "status": "PASS",
            "server_generated": True,
            "drill_hash": "sha256:" + "a" * 64,
            "record_hashes": records,
            "epoch_hash": "sha256:" + "b" * 64,
            "ttl_bounded": True,
            "owner_hash": "sha256:" + "c" * 64,
            "fence_hash": "sha256:" + "d" * 64,
            "audit_create_only": True,
            "active_record_count_after_exit": 3,
        },
        "drain": {
            "status": "PASS",
            "connection_root_matches": True,
            "connection_root_hash": "sha256:" + "0" * 64,
            "registry_provider_class": "ConnectionRegistry",
            "registry_provider_module": "onboarding.registry",
            "registry_store_class": "OneLakeRegistryStore",
            "normal_selection": True,
            "normal_reauthorization": True,
            "processed_per_pass": [1, 1, 1, 1],
            "prepared_record_hashes": records,
            "terminal_record_hashes": records,
            "selection_receipts": [
                {
                    "record_hash": records[0],
                    "epoch_hash": "sha256:" + "b" * 64,
                    "snapshot_hash": "sha256:" + "4" * 64,
                    "cursor_before": 0,
                    "cursor_after": 1,
                    "attempt": 1,
                    "outcome": "duplicate",
                    "authorization_hash": "sha256:" + "5" * 64,
                    "process_hash": "sha256:" + "e" * 64,
                },
                {
                    "record_hash": records[1],
                    "epoch_hash": "sha256:" + "b" * 64,
                    "snapshot_hash": "sha256:" + "4" * 64,
                    "cursor_before": 1,
                    "cursor_after": 2,
                    "attempt": 1,
                    "outcome": "retrying",
                    "authorization_hash": "sha256:" + "6" * 64,
                    "process_hash": "sha256:" + "e" * 64,
                },
                {
                    "record_hash": records[2],
                    "epoch_hash": "sha256:" + "b" * 64,
                    "snapshot_hash": "sha256:" + "4" * 64,
                    "cursor_before": 2,
                    "cursor_after": 0,
                    "attempt": 1,
                    "outcome": "succeeded",
                    "authorization_hash": "sha256:" + "7" * 64,
                    "process_hash": "sha256:" + "f" * 64,
                },
                {
                    "record_hash": records[1],
                    "epoch_hash": "sha256:" + "b" * 64,
                    "snapshot_hash": "sha256:" + "4" * 64,
                    "cursor_before": 0,
                    "cursor_after": 2,
                    "attempt": 2,
                    "outcome": "exhausted_failure",
                    "authorization_hash": "sha256:" + "6" * 64,
                    "process_hash": "sha256:" + "f" * 64,
                },
            ],
            "retry_rotated": True,
            "later_member_progress": True,
            "process_hashes": ["sha256:" + "e" * 64, "sha256:" + "f" * 64],
            "restart_lineage_preserved": True,
            "post_selection_external_writes": 0,
            "validator_store_writes": 0,
        },
        "injection": {
            "status": "PASS",
            "terraform_tag_hash_matches": True,
            "lineage": ["terraform", "arg", "inventory", "evidence", "curator"],
            "resource_hash": "sha256:" + "a" * 64,
            "scope_hash": "sha256:" + "d" * 64,
            "tag_hashes": {
                source: "sha256:" + "7" * 64
                for source in ("terraform", "arg", "inventory", "evidence", "curator")
            },
            "curator_source_class": "OntologyCurator",
            "tools": list(EXPECTED_CURATOR_TOOLS),
            "scope_unchanged": True,
            "mutation_attempts": 0,
            "authoritative_model_edges": {
                "candidate": 0,
                "stage": 0,
                "active": 0,
                "consumer": 0,
            },
        },
        "cleanup": {
            "status": "PASS",
            "server_resolved_unique_drill": True,
            "fence_matches": True,
            "deleted_record_hashes": records,
            "deleted_epoch_count": 1,
            "active_fixture_connections": 0,
            "active_prepared_epochs": 0,
            "retained_receipts": ["prepare", "cleanup", "sweep"],
            "audit_immutable": True,
            "independent_observer": "evidence",
            "tag_hash_unchanged": True,
        },
        "maintenance": {
            "general_operator_denied": True,
            "maintenance_principal_accepted": True,
            "coordinator_reauthorized": True,
            "next_run": "full",
            "following_run": "incremental",
        },
        "release_status": "BLOCKED/PENDING",
    }


def test_sequence_rejects_reordered_or_incomplete_lifecycle() -> None:
    evidence = _complete_lifecycle()
    assert evaluate_lifecycle_evidence(evidence)["status"] == "PASS"

    for sequence in (
        list(reversed(DEPLOYED_LIFECYCLE_SEQUENCE)),
        list(DEPLOYED_LIFECYCLE_SEQUENCE[:-1]),
    ):
        changed = json.loads(json.dumps(evidence))
        changed["sequence"] = sequence
        report = evaluate_lifecycle_evidence(changed)
        assert report["status"] == "FAIL"
        assert "exact_lifecycle_sequence" in report["missing_evidence"]


def test_fixed_template_hash_covers_runtime_shape_and_rejects_drift() -> None:
    before = _template()
    digest = job_template_hash(before)
    assert digest.startswith("sha256:") and len(digest) == 71
    assert_fixed_template(digest, before, json.loads(json.dumps(before)))

    for path, changed in (
        ("command", ["sh"]),
        ("args", ["fixture-cleanup"]),
        ("image", "registry.invalid/api@sha256:" + ("b" * 64)),
    ):
        after = json.loads(json.dumps(before))
        after["properties"]["template"]["containers"][0][path] = changed
        with pytest.raises(EvidenceError, match="template"):
            assert_fixed_template(digest, before, after)


def test_job_start_command_has_no_override_surface() -> None:
    command = build_job_start_command(
        resource_group="opaque-group",
        job_name="ontology-fixture-prepare",
    )
    assert command == [
        "az",
        "containerapp",
        "job",
        "start",
        "--resource-group",
        "opaque-group",
        "--name",
        "ontology-fixture-prepare",
        "-o",
        "json",
    ]
    assert not set(command).intersection(
        {
            "--command",
            "--args",
            "--env-vars",
            "--image",
            "--mi-user-assigned",
            "--parallelism",
            "--replica-completion-count",
        }
    )
    with pytest.raises(EvidenceError, match="fixed deployed Job"):
        build_job_start_command(
            resource_group="opaque-group",
            job_name="caller-selected-job",
        )


def test_fixed_job_registry_matches_deployed_plan19_templates() -> None:
    assert FIXED_JOB_NAMES == {
        "coordinator": "aiops-dev-ontology-discovery",
        "publisher": "aiops-dev-ontology-publisher",
        "rbac_validator": "aiops-dev-ontology-rbac-check",
        "ontology_fixture_prepare": "ontology-fixture-prepare",
        "ontology_fixture_cleanup": "ontology-fixture-cleanup",
    }


def test_plan19_contract_requires_applied_stable_hashes_and_exact_roots(
    tmp_path: Path,
) -> None:
    hashes = {
        logical: f"sha256:{index:064x}"
        for index, logical in enumerate(FIXED_JOB_NAMES, start=1)
    }
    deployment = {
        "schema_version": "ontology-gap-deployment.v1",
        "status": "applied",
        "live": {
            "applied": True,
            "no_runtime_job_start_grants": True,
            "deployment_principal_fixture_access": True,
            "template_hashes_before": hashes,
            "template_hashes_after": hashes,
            "root_hashes": {
                "AIOPS_CONNECTION_HOME": "sha256:" + "a" * 64,
                "AIOPS_ONTOLOGY_COMMAND_HOME": "sha256:" + "b" * 64,
                "AIOPS_ONTOLOGY_STATE_HOME": "sha256:" + "c" * 64,
                "AIOPS_ONTOLOGY_PUBLICATION_HOME": "sha256:" + "d" * 64,
            },
            "coordinator_tag_hash": "sha256:" + "e" * 64,
        },
    }
    path = tmp_path / "deployment.json"
    path.write_text(json.dumps(deployment), encoding="utf-8")

    contract = load_plan19_deployment_contract(path)
    assert contract.status == "applied"
    assert contract.template_hashes == hashes
    assert contract.validation_connection_root_hash == "sha256:" + "a" * 64
    assert contract.coordinator_tag_hash == "sha256:" + "e" * 64

    drifted = json.loads(json.dumps(deployment))
    drifted["live"]["template_hashes_after"]["publisher"] = (
        "sha256:" + "f" * 64
    )
    path.write_text(json.dumps(drifted), encoding="utf-8")
    with pytest.raises(EvidenceError, match="Plan 19"):
        load_plan19_deployment_contract(path)


def test_credential_contexts_are_distinct_private_and_non_bleeding(
    tmp_path: Path,
) -> None:
    deployer = tmp_path / "deployer"
    evidence = tmp_path / "evidence"
    deployer.mkdir(mode=0o700)
    evidence.mkdir(mode=0o700)
    os.chmod(deployer, 0o700)
    os.chmod(evidence, 0o700)
    env = {
        "AIOPS_DEPLOYER_AZURE_CONFIG_DIR": str(deployer),
        "AIOPS_EVIDENCE_AZURE_CONFIG_DIR": str(evidence),
        "PATH": "/usr/bin",
    }

    contexts = validate_azure_contexts(env)
    assert contexts.deployer == deployer.resolve()
    assert contexts.evidence == evidence.resolve()

    isolated = isolated_azure_environment(
        contexts.deployer,
        {
            **env,
            "AZURE_CLIENT_ID": "must-not-bleed",
            "AZURE_TENANT_ID": "must-not-bleed",
            "AZURE_CLIENT_SECRET": "must-not-bleed",
            "ARM_CLIENT_SECRET": "must-not-bleed",
        },
    )
    assert isolated["AZURE_CONFIG_DIR"] == str(deployer.resolve())
    assert isolated["PATH"] == "/usr/bin"
    assert "AZURE_CLIENT_ID" not in isolated
    assert "AZURE_TENANT_ID" not in isolated
    assert "AZURE_CLIENT_SECRET" not in isolated
    assert "ARM_CLIENT_SECRET" not in isolated

    os.chmod(evidence, 0o755)
    with pytest.raises(EvidenceError, match="0700"):
        validate_azure_contexts(env)


def test_validation_registry_eligible_set_restart_and_no_injection_contracts() -> None:
    evidence = _complete_lifecycle()
    for field, value, code in (
        ("processed_per_pass", [1, 2], "one_member_per_pass"),
        ("later_member_progress", False, "later_member_progress"),
        ("restart_lineage_preserved", False, "restart_lineage"),
        ("post_selection_external_writes", 1, "no_post_selection_injection"),
        ("validator_store_writes", 1, "no_validator_store_writes"),
    ):
        changed = json.loads(json.dumps(evidence))
        changed["drain"][field] = value
        report = evaluate_lifecycle_evidence(changed)
        assert report["status"] == "FAIL"
        assert code in report["missing_evidence"]

    wrong_provider = json.loads(json.dumps(evidence))
    wrong_provider["drain"]["registry_store_class"] = "FixtureRegistryStore"
    report = evaluate_lifecycle_evidence(wrong_provider)
    assert "production_registry_path" in report["missing_evidence"]


def test_three_record_drain_proves_starvation_free_retry_rotation() -> None:
    evidence = _complete_lifecycle()
    assert evaluate_lifecycle_evidence(evidence)["status"] == "PASS"

    no_later_progress = json.loads(json.dumps(evidence))
    retry = no_later_progress["drain"]["selection_receipts"].pop()
    no_later_progress["drain"]["selection_receipts"].insert(2, retry)
    report = evaluate_lifecycle_evidence(no_later_progress)
    assert "starvation_free_selection_order" in report["missing_evidence"]

    mixed_epoch = json.loads(json.dumps(evidence))
    mixed_epoch["drain"]["selection_receipts"][2]["epoch_hash"] = (
        "sha256:" + "9" * 64
    )
    report = evaluate_lifecycle_evidence(mixed_epoch)
    assert "restart_lineage" in report["missing_evidence"]


def test_injection_tag_requires_real_provenance_exact_tools_and_zero_edges() -> None:
    evidence = _complete_lifecycle()
    for field, value, code in (
        ("lineage", ["terraform", "local", "curator"], "real_tag_lineage"),
        ("tools", list(EXPECTED_CURATOR_TOOLS[:-1]), "exact_four_curator_tools"),
        ("scope_unchanged", False, "curator_scope_unchanged"),
        ("mutation_attempts", 1, "zero_curator_mutations"),
    ):
        changed = json.loads(json.dumps(evidence))
        changed["injection"][field] = value
        report = evaluate_lifecycle_evidence(changed)
        assert report["status"] == "FAIL"
        assert code in report["missing_evidence"]

    changed = json.loads(json.dumps(evidence))
    changed["injection"]["authoritative_model_edges"]["candidate"] = 1
    report = evaluate_lifecycle_evidence(changed)
    assert "zero_authoritative_model_edges" in report["missing_evidence"]

    changed = json.loads(json.dumps(evidence))
    changed["injection"]["tag_hashes"]["inventory"] = "sha256:" + "8" * 64
    report = evaluate_lifecycle_evidence(changed)
    assert "exact_tag_lineage" in report["missing_evidence"]


def test_cleanup_requires_fence_exact_set_empty_registry_and_retained_audit() -> None:
    evidence = _complete_lifecycle()
    for field, value, code in (
        ("server_resolved_unique_drill", False, "server_resolved_cleanup"),
        ("fence_matches", False, "cleanup_fence"),
        ("active_fixture_connections", 1, "fixture_registry_empty"),
        ("active_prepared_epochs", 1, "prepared_epoch_registry_empty"),
        ("retained_receipts", ["prepare"], "retained_fixture_audit"),
        ("audit_immutable", False, "immutable_fixture_audit"),
    ):
        changed = json.loads(json.dumps(evidence))
        changed["cleanup"][field] = value
        report = evaluate_lifecycle_evidence(changed)
        assert report["status"] == "FAIL"
        assert code in report["missing_evidence"]

    changed = json.loads(json.dumps(evidence))
    changed["cleanup"]["independent_observer"] = "deployer"
    report = evaluate_lifecycle_evidence(changed)
    assert "independent_empty_registry_observation" in report["missing_evidence"]


def test_job_start_authority_and_maintenance_are_fail_closed() -> None:
    evidence = _complete_lifecycle()
    changed = json.loads(json.dumps(evidence))
    changed["credentials"]["runtime_job_start_grants"] = ["coordinator"]
    changed["maintenance"]["general_operator_denied"] = False
    report = evaluate_lifecycle_evidence(changed)
    assert report["status"] == "FAIL"
    assert "no_runtime_job_start_grants" in report["missing_evidence"]
    assert "general_maintenance_denied" in report["missing_evidence"]

    same_identity = _complete_lifecycle()
    same_identity["credentials"]["identity_hashes"]["evidence"] = (
        same_identity["credentials"]["identity_hashes"]["deployer"]
    )
    report = evaluate_lifecycle_evidence(same_identity)
    assert "distinct_azure_identities" in report["missing_evidence"]

    evidence_can_start = _complete_lifecycle()
    evidence_can_start["credentials"]["evidence_denied_actions"].remove(
        "job_start"
    )
    report = evaluate_lifecycle_evidence(evidence_can_start)
    assert "evidence_has_no_job_authority" in report["missing_evidence"]


def test_resume_checkpoint_has_finite_stages_and_opaque_step_keys(
    tmp_path: Path,
) -> None:
    resume_file = tmp_path / "checkpoint.json"
    write_resume_checkpoint(
        resume_file,
        stage="lifecycle",
        completed_steps=("preflight", "prepare"),
        evidence_refs=("sha256:" + "a" * 64,),
    )
    checkpoint = load_resume_checkpoint(resume_file)
    assert checkpoint["stage"] == "lifecycle"
    assert checkpoint["completed_step_count"] == 2
    assert all(
        value.startswith("sha256:") and len(value) == 71
        for value in checkpoint["completed_step_keys"]
    )
    rendered = resume_file.read_text(encoding="utf-8")
    assert "preflight" not in rendered
    assert "prepare" not in rendered

    with pytest.raises(EvidenceError, match="stage"):
        write_resume_checkpoint(
            resume_file,
            stage="unbounded",
            completed_steps=(),
            evidence_refs=(),
        )


def test_stage_state_machine_is_finite_ordered_and_idempotent() -> None:
    assert DEPLOYED_STAGES == (
        "preflight",
        "lifecycle",
        "publication",
        "finalize",
    )
    assert_stage_transition((), "preflight")
    assert_stage_transition(("preflight",), "preflight")
    assert_stage_transition(("preflight",), "lifecycle")
    assert_stage_transition(
        ("preflight", "lifecycle", "publication"),
        "finalize",
    )
    with pytest.raises(EvidenceError, match="stage transition"):
        assert_stage_transition((), "lifecycle")
    with pytest.raises(EvidenceError, match="stage transition"):
        assert_stage_transition(("preflight",), "publication")


def test_deployed_evidence_sanitizer_rejects_raw_operational_values() -> None:
    safe = {
        "identity_hash": "sha256:" + "a" * 64,
        "tag_hash": "sha256:" + "b" * 64,
        "record_count": 3,
        "status": "PASS",
    }
    assert sanitize_deployed_evidence(safe) == safe
    for key, value in (
        ("access_token", "secret"),
        ("raw_error", "boom"),
        ("resource_id", "/subscriptions/raw"),
        ("tag_value", "instruction=raw"),
        ("command", "az containerapp job start"),
        ("fixture_path", "abfss://raw"),
    ):
        with pytest.raises(EvidenceError, match="unsafe deployed evidence"):
            sanitize_deployed_evidence({key: value})


def test_parser_exposes_only_finite_deployed_stages_and_assertions() -> None:
    parser = _parser()
    args = parser.parse_args(
        [
            "--stage",
            "lifecycle",
            "--environment",
            "validation",
            "--shadow",
            "--resume-file",
            "checkpoint.json",
            "--output",
            "evidence.json",
            "--max-wait-seconds",
            "1800",
            "--assert-isolated-azure-contexts",
            "--assert-fixed-job-template-hashes",
            "--assert-no-job-overrides",
            "--assert-fixture-registry-empty",
            "--fail-on-local-substitution",
            "--fail-on-missing-evidence",
        ]
    )
    assert args.stage == "lifecycle"
    assert args.environment == "validation"
    assert args.max_wait_seconds == 1800
    assert args.assert_isolated_azure_contexts is True
    assert args.assert_fixed_job_template_hashes is True
    assert args.assert_no_job_overrides is True
    assert args.assert_fixture_registry_empty is True
    assert args.fail_on_local_substitution is True


def test_role_expansion_rejects_wildcards_and_job_actions_outside_deployer() -> None:
    roles = [
        {
            "role": "Reader",
            "actions": ["Microsoft.Resources/subscriptions/resourceGroups/read"],
            "not_actions": [],
        },
        {
            "role": "Fabric reader",
            "actions": ["Microsoft.Fabric/workspaces/read"],
            "not_actions": [],
        },
    ]
    expanded = expand_role_actions(roles)
    assert expanded["wildcard"] is False
    assert expanded["job_start"] is False
    assert expanded["mutation"] is False

    expanded = expand_role_actions(
        [{"role": "Owner", "actions": ["*"], "not_actions": []}]
    )
    assert expanded["wildcard"] is True
    assert expanded["job_start"] is True
    assert expanded["mutation"] is True


def test_publication_requires_real_topology_drills_rollback_and_consumers() -> None:
    evidence = _complete_lifecycle()
    publication = {
        "release_status": "BLOCKED/PENDING",
        "templates": evidence["templates"],
        "credentials": evidence["credentials"],
        "command_topology": [
            "api_intake",
            "coordinator_claim",
            "coordinator_reauthorization",
            "publish_dispatch",
            "publisher_claim",
            "publisher_status",
            "api_reload",
        ],
        "process_hashes": {
            "api": "sha256:" + "1" * 64,
            "coordinator": "sha256:" + "2" * 64,
            "publisher": "sha256:" + "3" * 64,
            "api_reload": "sha256:" + "4" * 64,
        },
        "receipts": {
            name: True
            for name in (
                "immutable_stage",
                "validation",
                "five_consumer_compatibility",
                "fabric_materialization",
                "final_precondition",
                "pointer_cas",
                "post_check",
            )
        },
        "stale_writer": {
            "pre_cas_pause": True,
            "stale_fence_rejected": True,
            "stale_etag_rejected": True,
            "one_shot_consumed": True,
            "cleaned": True,
        },
        "rollback": {
            "allowlisted_post_check_failure": True,
            "automatic": True,
            "order": ["old", "new", "old"],
            "one_shot_consumed": True,
            "cleaned": True,
        },
        "consumers": {
            name: "PASS"
            for name in ("api", "fabric", "agent", "export", "semantic")
        },
        "final": {
            "fixture_registry_empty": True,
            "fixture_audit_retained": True,
            "terraform_tag_unchanged": True,
            "runtime_job_start_grants": [],
            "authoritative_model_edges": 0,
            "local_substitution": False,
        },
    }
    assert evaluate_publication_evidence(publication)["status"] == "PASS"

    changed = json.loads(json.dumps(publication))
    changed["rollback"]["order"] = ["old", "new"]
    report = evaluate_publication_evidence(changed)
    assert report["status"] == "FAIL"
    assert "old_new_old" in report["missing_evidence"]


def test_deployed_stage_fails_before_legacy_shadow_or_cloud_action(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output = tmp_path / "deployed.json"

    def forbidden_shadow(_: object) -> object:
        raise AssertionError("legacy shadow collector must not run for a deployed stage")

    monkeypatch.setattr(
        "scripts.validate_ontology_discovery_live._shadow",
        forbidden_shadow,
    )
    monkeypatch.delenv("AIOPS_DEPLOYER_AZURE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("AIOPS_EVIDENCE_AZURE_CONFIG_DIR", raising=False)
    result = main(
        [
            "--stage",
            "lifecycle",
            "--environment",
            "validation",
            "--shadow",
            "--resume-file",
            str(tmp_path / "resume.json"),
            "--output",
            str(output),
            "--fail-on-missing-evidence",
        ]
    )
    assert result == 1
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["mode"] == "deployed-fixed-template"
    assert report["status"] == "FAIL"
    assert report["missing_evidence"] == ["EvidenceError"]
    assert "AIOPS_DEPLOYER_AZURE_CONFIG_DIR" in report["blocker"]
