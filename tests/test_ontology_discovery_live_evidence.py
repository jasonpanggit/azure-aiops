from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from scripts.validate_ontology_discovery_live import (
    DEPLOYED_LIFECYCLE_SEQUENCE,
    DEPLOYED_STAGES,
    EXPECTED_CURATOR_TOOLS,
    FIXED_JOB_NAMES,
    EvidenceError,
    Plan19DeploymentContract,
    _configured_curator_tools,
    _deployed_failure_report,
    _full_opaque,
    _parser,
    _run_isolated_az_json,
    assert_fixed_template,
    assert_stage_transition,
    build_job_start_command,
    derive_cleanup_evidence,
    derive_coordinator_selection_receipt,
    derive_injection_evidence,
    derive_maintenance_evidence,
    derive_prepare_evidence,
    evaluate_lifecycle_evidence,
    evaluate_publication_evidence,
    expand_role_actions,
    extract_evidence_job_record,
    fetch_live_job,
    isolated_azure_environment,
    job_template_hash,
    load_plan19_deployment_contract,
    load_resume_checkpoint,
    main,
    merge_resume_checkpoint,
    run_fixed_job,
    sanitize_deployed_evidence,
    validate_azure_contexts,
    validate_evidence_job_boundary,
    validate_evidence_job_record,
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
            "local_context_count": 1,
            "modes": {"deployer": "0700"},
            "ambient_credentials_removed": True,
            "identity_hashes": {
                "deployer": "sha256:" + "8" * 64,
                "evidence": "sha256:" + "9" * 64,
            },
            "evidence_source": "fixed_job",
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
        "evidence_job": {
            "identity_hash": "sha256:" + "9" * 64,
            "expected_identity_hash": "sha256:" + "9" * 64,
            "template_hash": "sha256:" + "a" * 64,
            "expected_template_hash": "sha256:" + "a" * 64,
            "template_unchanged": True,
            "attached_identity_count": 1,
            "trigger": "Manual",
            "overrides": [],
            "workspace_roles": ["Viewer"] * 5,
            "onelake_actions": ["Read"] * 5,
            "onelake_paths": ["*"] * 5,
            "job_control_actions": [],
            "mutation_actions": [],
            "production_workspace_access": False,
            "record_hash": "sha256:" + "b" * 64,
            "entra_bound_record_hash": "sha256:" + "c" * 64,
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
            "retained_receipts": ["prepare", "cleanup"],
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


def _snapshot(
    *,
    cursor: int,
    outcomes: tuple[str, str, str],
    attempts: tuple[int, int, int],
    fixture_status: str = "prepared",
    active_records: int = 3,
    active_epochs: int = 1,
) -> dict[str, object]:
    records = ["sha256:" + char * 64 for char in ("1", "2", "3")]
    return {
        "facts": {
            "fixture": {
                "drill_count": 1,
                "active_drill_count": int(fixture_status == "prepared"),
                "status": fixture_status,
                "drill_hash": "sha256:" + "a" * 64,
                "owner_hash": "sha256:" + "b" * 64,
                "fence_hash": "sha256:" + "c" * 64,
                "epoch_hash": "sha256:" + "d" * 64,
                "record_count": 3,
                "record_hashes": records,
                "ttl_bounded": True,
                "receipt_events": (
                    ["prepared"]
                    if fixture_status == "prepared"
                    else ["prepared", "cleaned"]
                ),
                "receipt_count": 1 if fixture_status == "prepared" else 2,
                "audit_hash": "sha256:" + "e" * 64,
                "prepare_receipt_hash": "sha256:" + "4" * 64,
                "cleanup_receipt_hash": (
                    ""
                    if fixture_status == "prepared"
                    else "sha256:" + "5" * 64
                ),
            },
            "registry": {
                "revision": 7,
                "active_fixture_count": active_records,
                "fixture_record_hashes": records if active_records else [],
            },
            "epoch": {
                "active_epoch_count": active_epochs,
                "epoch_count": 1 if active_epochs else 0,
                "epoch_hash": "sha256:" + "d" * 64 if active_epochs else "",
                "snapshot_hash": (
                    "sha256:" + "f" * 64 if active_epochs else ""
                ),
                "status": "active" if active_epochs else "absent",
                "cursor": cursor,
                "revision": sum(attempts),
                "member_count": 3 if active_epochs else 0,
                "members": (
                    [
                        {
                            "record_hash": record_hash,
                            "outcome": outcome,
                            "attempt_count": attempt,
                            "reason_hash": "sha256:" + str(index + 4) * 64,
                            "updated_at_hash": (
                                "sha256:" + str(index + 7) * 64
                            ),
                            "authorization_hash": (
                                "sha256:" + str(index) * 64
                            ),
                        }
                        for index, (record_hash, outcome, attempt) in enumerate(
                            zip(records, outcomes, attempts, strict=True),
                            start=1,
                        )
                    ]
                    if active_epochs
                    else []
                ),
            },
            "runs": {"count": 3, "records": []},
            "evidence_batches": {
                "count": 1,
                "injection_match_count": 1,
                "injection_resource_hash": "sha256:" + "9" * 64,
                "injection_tag_hash": "sha256:" + "8" * 64,
                "injection_scope_hash": "sha256:" + "7" * 64,
                "records": [],
            },
            "dispatch": {
                "count": 1,
                "model_edge_counts": {
                    "candidate": 0,
                    "stage": 0,
                    "active": 0,
                    "consumer": 0,
                },
                "records": [],
            },
            "arg": {
                "matching_tag_count": 1,
                "resource_hash": "sha256:" + "9" * 64,
                "tag_hash": "sha256:" + "8" * 64,
                "scope_hash": "sha256:" + "7" * 64,
                "observation_hash": "sha256:" + "6" * 64,
            },
        }
    }


def test_prepare_and_cleanup_are_derived_from_successive_closed_snapshots() -> None:
    prepared = _snapshot(
        cursor=0,
        outcomes=("pending", "pending", "pending"),
        attempts=(0, 0, 0),
    )
    prepare = derive_prepare_evidence(prepared)
    assert prepare["status"] == "PASS"
    assert prepare["active_record_count_after_exit"] == 3
    assert prepare["audit_create_only"] is True

    cleaned = _snapshot(
        cursor=0,
        outcomes=("pending", "pending", "pending"),
        attempts=(0, 0, 0),
        fixture_status="cleaned",
        active_records=0,
        active_epochs=0,
    )
    cleanup = derive_cleanup_evidence(prepared, cleaned)
    assert cleanup["status"] == "PASS"
    assert cleanup["deleted_record_hashes"] == prepare["record_hashes"]
    assert cleanup["retained_receipts"] == ["prepare", "cleanup"]

    malformed = json.loads(json.dumps(prepared))
    malformed["facts"]["registry"]["active_fixture_count"] = 2
    with pytest.raises(EvidenceError, match="prepare_exact_three_records"):
        derive_prepare_evidence(malformed)


def test_selection_receipts_are_snapshot_diffs_not_synthesized_flags() -> None:
    before = _snapshot(
        cursor=0,
        outcomes=("pending", "pending", "pending"),
        attempts=(0, 0, 0),
    )
    after = _snapshot(
        cursor=1,
        outcomes=("duplicate", "pending", "pending"),
        attempts=(1, 0, 0),
    )
    receipt = derive_coordinator_selection_receipt(
        before,
        after,
        {"execution_hash": "sha256:" + "a" * 64},
    )
    assert receipt["record_hash"] == "sha256:" + "1" * 64
    assert receipt["outcome"] == "duplicate"
    assert receipt["cursor_before"] == 0
    assert receipt["cursor_after"] == 1

    two_changes = json.loads(json.dumps(after))
    two_changes["facts"]["epoch"]["members"][1]["attempt_count"] = 1
    two_changes["facts"]["epoch"]["members"][1]["outcome"] = "succeeded"
    with pytest.raises(EvidenceError, match="coordinator_exactly_one_member"):
        derive_coordinator_selection_receipt(
            before,
            two_changes,
            {"execution_hash": "sha256:" + "b" * 64},
        )

    drifted = json.loads(json.dumps(after))
    drifted["facts"]["epoch"]["snapshot_hash"] = "sha256:" + "0" * 64
    with pytest.raises(EvidenceError, match="coordinator_snapshot_lineage"):
        derive_coordinator_selection_receipt(
            before,
            drifted,
            {"execution_hash": "sha256:" + "b" * 64},
        )


def test_injection_derivation_requires_direct_arg_batch_dispatch_and_tool_facts() -> None:
    observed = _snapshot(
        cursor=0,
        outcomes=("duplicate", "exhausted_failure", "succeeded"),
        attempts=(1, 2, 1),
    )
    preflight = {
        "injection_contract": {
            "resource_hash": "sha256:" + "9" * 64,
            "tag_hash": "sha256:" + "8" * 64,
            "scope_hash": "sha256:" + "7" * 64,
            "configured_tools": list(EXPECTED_CURATOR_TOOLS),
            "curator_source_class": "OntologyCurator",
        }
    }

    injection = derive_injection_evidence(preflight, observed)

    assert injection["status"] == "PASS"
    assert injection["lineage"] == [
        "terraform",
        "arg",
        "inventory",
        "evidence",
        "curator",
    ]
    assert injection["authoritative_model_edges"] == {
        "candidate": 0,
        "stage": 0,
        "active": 0,
        "consumer": 0,
    }

    no_arg = json.loads(json.dumps(observed))
    no_arg["facts"]["arg"]["matching_tag_count"] = 0
    with pytest.raises(EvidenceError, match="injection_arg_exact_match"):
        derive_injection_evidence(preflight, no_arg)

    no_tools = json.loads(json.dumps(preflight))
    del no_tools["injection_contract"]["configured_tools"]
    with pytest.raises(
        EvidenceError,
        match="injection_configured_tools_unavailable",
    ):
        derive_injection_evidence(no_tools, observed)


def test_maintenance_evidence_boundary_fails_closed_without_direct_api_receipts() -> None:
    with pytest.raises(
        EvidenceError,
        match="maintenance_authenticated_api_evidence_required",
    ):
        derive_maintenance_evidence(None)

    direct = {
        "source": "authenticated_api",
        "general_operator_status": 403,
        "maintenance_status": 200,
        "command_authorization": "authorized",
        "next_run": "full",
        "following_run": "incremental",
    }
    assert derive_maintenance_evidence(direct) == {
        "general_operator_denied": True,
        "maintenance_principal_accepted": True,
        "coordinator_reauthorized": True,
        "next_run": "full",
        "following_run": "incremental",
    }

    fabricated = {**direct, "source": "local_contract"}
    with pytest.raises(
        EvidenceError,
        match="maintenance_authenticated_api_evidence_required",
    ):
        derive_maintenance_evidence(fabricated)

    failure = _deployed_failure_report(
        stage="lifecycle",
        exc=EvidenceError("maintenance_authenticated_api_evidence_required"),
    )
    assert failure["closed_reason"] == (
        "maintenance_authenticated_api_evidence_required"
    )


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
        "evidence": "ontology-evidence-read",
    }


def test_plan19_contract_requires_applied_stable_hashes_and_exact_roots(
    tmp_path: Path,
) -> None:
    hashes = {
        logical: f"sha256:{index:064x}"
        for index, logical in enumerate(FIXED_JOB_NAMES, start=1)
        if logical != "evidence"
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
        "plans": {
            "validation": {
                "root_hashes": {
                    "coordinator_connection": "sha256:" + "f" * 64,
                }
            }
        },
    }
    path = tmp_path / "deployment.json"
    path.write_text(json.dumps(deployment), encoding="utf-8")

    contract = load_plan19_deployment_contract(path)
    assert contract.status == "applied"
    assert contract.template_hashes == hashes
    assert contract.validation_connection_root_hash == "sha256:" + "f" * 64
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
    deployer.mkdir(mode=0o700)
    os.chmod(deployer, 0o700)
    env = {
        "AIOPS_DEPLOYER_AZURE_CONFIG_DIR": str(deployer),
        "PATH": "/usr/bin",
    }

    contexts = validate_azure_contexts(env)
    assert contexts.deployer == deployer.resolve()

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

    os.chmod(deployer, 0o755)
    with pytest.raises(EvidenceError, match="0700"):
        validate_azure_contexts(env)

    os.chmod(deployer, 0o700)
    duplicate_context = dict(env)
    duplicate_context["AIOPS_EVIDENCE_AZURE_CONFIG_DIR"] = str(deployer)
    with pytest.raises(EvidenceError, match="must not be configured"):
        validate_azure_contexts(duplicate_context)


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

    widened = _complete_lifecycle()
    widened["evidence_job"]["onelake_actions"][0] = "ReadWrite"
    widened["evidence_job"]["workspace_roles"][0] = "Contributor"
    widened["evidence_job"]["production_workspace_access"] = True
    report = evaluate_lifecycle_evidence(widened)
    assert "evidence_job_read_only_roles" in report["missing_evidence"]
    assert "evidence_job_no_production_workspace" in report["missing_evidence"]


def test_evidence_job_record_is_entra_bound_closed_and_exact_identity() -> None:
    identity_hash = "sha256:" + "1" * 64
    record = {
        "schema_version": "ontology-evidence-read.v1",
        "mode": "fixed-read-only",
        "sanitized": True,
        "identity": {
            "client_id_hash": "sha256:" + "2" * 64,
            "object_id_hash": identity_hash,
            "managed_identity_resource_hash": "sha256:" + "3" * 64,
            "entra_signature_hash": "sha256:" + "4" * 64,
        },
        "capabilities": {
            "azure": ["read"],
            "fabric": ["Viewer"],
            "onelake": ["Read"],
            "denied": ["job_start", "mutation"],
        },
        "observations": {
            name: {"count": 1, "hashes": ["sha256:" + char * 64]}
            for name, char in zip(
                ("arg", "fabric", "onelake"),
                ("5", "6", "7"),
                strict=True,
            )
        },
    }
    from scripts.collect_ontology_evidence import build_closed_record

    record = build_closed_record(
        identity=record["identity"],
        observations=record["observations"],
        capabilities=record["capabilities"],
        facts={
            "fixture": {"active_drill_count": 0},
            "registry": {"active_fixture_count": 0},
            "epoch": {"active_epoch_count": 0},
        },
    )
    result = validate_evidence_job_record(
        record,
        expected_object_id_hash=identity_hash,
    )
    assert result["record_hash"] == record["record_hash"]

    wrong = json.loads(json.dumps(record))
    wrong["identity"]["object_id_hash"] = "sha256:" + "9" * 64
    with pytest.raises(EvidenceError, match="identity"):
        validate_evidence_job_record(
            wrong,
            expected_object_id_hash=identity_hash,
        )


def test_evidence_job_log_parser_accepts_exactly_one_closed_console_record() -> None:
    from scripts.collect_ontology_evidence import build_closed_record

    record = build_closed_record(
        identity={
            "client_id_hash": "sha256:" + "1" * 64,
            "object_id_hash": "sha256:" + "2" * 64,
            "managed_identity_resource_hash": "sha256:" + "3" * 64,
            "entra_signature_hash": "sha256:" + "4" * 64,
        },
        observations={
            name: {"count": 1, "hashes": ["sha256:" + char * 64]}
            for name, char in zip(
                ("arg", "fabric", "onelake"),
                ("5", "6", "7"),
                strict=True,
            )
        },
        capabilities={
            "azure": ["read"],
            "fabric": ["Viewer"],
            "onelake": ["Read"],
            "denied": ["job_start", "mutation"],
        },
        facts={
            "fixture": {"active_drill_count": 0},
            "registry": {"active_fixture_count": 0},
            "epoch": {"active_epoch_count": 0},
        },
    )
    logs = [
        {"Log_s": "system startup"},
        {"Log_s": json.dumps(record, separators=(",", ":"))},
    ]

    assert extract_evidence_job_record(logs) == record
    aca_line = (
        '{"TimeStamp":"2026-09-08T00:00:00Z","Log":"F '
        + json.dumps(record, separators=(",", ":"))
        + '"}'
    )
    assert extract_evidence_job_record(aca_line) == record
    with pytest.raises(EvidenceError, match="exactly one"):
        extract_evidence_job_record(
            [*logs, {"Log_s": json.dumps(record, separators=(",", ":"))}]
        )


def test_evidence_job_boundary_requires_fixed_identity_template_and_roles() -> None:
    before = _template()
    before["properties"]["triggerType"] = "Manual"
    before["properties"]["configuration"]["replicaRetryLimit"] = 0
    before["properties"]["identity"]["userAssignedIdentities"] = {
        "/subscriptions/sub/resourceGroups/rg/providers/"
        "Microsoft.ManagedIdentity/userAssignedIdentities/azure-mcp": {}
    }
    after = json.loads(json.dumps(before))
    identity_resource = next(
        iter(
            before["properties"]["identity"]["userAssignedIdentities"]
        )
    )
    expected_identity_hash = "sha256:" + "1" * 64
    roles = {
        "workspace_roles": [
            {
                "role": "Viewer",
                "principal_hash": expected_identity_hash,
                "production_workspace": False,
            }
            for _ in range(5)
        ],
        "onelake_roles": [
            {
                "actions": ["Read"],
                "paths": ["*"],
                "object_type": "ManagedIdentity",
                "principal_hash": expected_identity_hash,
                "production_workspace": False,
            }
            for _ in range(5)
        ],
        "job_control_actions": [],
        "mutation_actions": [],
    }
    result = validate_evidence_job_boundary(
        before=before,
        after=after,
        expected_template_hash=job_template_hash(before),
        expected_identity_resource_hash=_full_opaque(identity_resource),
        expected_principal_hash=expected_identity_hash,
        role_snapshot=roles,
    )
    assert result["workspace_roles"] == ["Viewer"] * 5
    assert result["onelake_actions"] == ["Read"] * 5

    widened = json.loads(json.dumps(roles))
    widened["onelake_roles"][0]["actions"] = ["ReadWrite"]
    with pytest.raises(EvidenceError, match="OneLake"):
        validate_evidence_job_boundary(
            before=before,
            after=after,
            expected_template_hash=job_template_hash(before),
            expected_identity_resource_hash=_full_opaque(identity_resource),
            expected_principal_hash=expected_identity_hash,
            role_snapshot=widened,
        )


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
    assert report["missing_evidence"] == ["evidence_precondition"]
    assert report["closed_reason"] == "evidence_precondition"
    assert report["blocker_code"] == "evidence_precondition"
    assert "AIOPS_DEPLOYER_AZURE_CONFIG_DIR" not in json.dumps(report)


def test_isolated_az_json_never_uses_ambient_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    azure_home = tmp_path / "azure"
    azure_home.mkdir(mode=0o700)
    os.chmod(azure_home, 0o700)
    observed: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        observed["command"] = command
        observed["env"] = kwargs["env"]
        return subprocess.CompletedProcess(command, 0, '{"name":"fixed"}', "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = _run_isolated_az_json(
        ["az", "account", "show", "-o", "json"],
        azure_config_dir=azure_home,
        env={
            "PATH": "/usr/bin",
            "AZURE_CONFIG_DIR": "/ambient",
            "AZURE_CLIENT_SECRET": "must-not-bleed",
            "ARM_CLIENT_SECRET": "must-not-bleed",
        },
    )

    assert result == {"name": "fixed"}
    isolated = observed["env"]
    assert isinstance(isolated, dict)
    assert isolated["AZURE_CONFIG_DIR"] == str(azure_home.resolve())
    assert isolated["PATH"] == "/usr/bin"
    assert "AZURE_CLIENT_SECRET" not in isolated
    assert "ARM_CLIENT_SECRET" not in isolated


def test_fixed_job_execution_fetches_starts_waits_and_reads_logs_without_overrides(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[list[str]] = []
    job = _template()
    expected_hash = job_template_hash(job)
    container = job["properties"]["template"]["containers"][0]
    container["name"] = "ontology"

    def fake_az(
        command: list[str],
        **_: object,
    ) -> object:
        calls.append(command)
        joined = " ".join(command)
        if " job show " in f" {joined} ":
            return job
        if " job start " in f" {joined} ":
            return {"name": "execution-raw-id"}
        if " job execution list " in f" {joined} ":
            return [
                {
                    "name": "execution-raw-id",
                    "properties": {"status": "Succeeded"},
                }
            ]
        if " job logs show " in f" {joined} ":
            return [{"Log_s": '{"status":"PASS","count":3}'}]
        raise AssertionError(command)

    monkeypatch.setattr(
        "scripts.validate_ontology_discovery_live._run_isolated_az_json",
        fake_az,
    )
    monkeypatch.setattr(
        "scripts.validate_ontology_discovery_live._run_isolated_az_text",
        fake_az,
    )
    result = run_fixed_job(
        resource_group="opaque-group",
        job_name="ontology-fixture-prepare",
        expected_template_hash=expected_hash,
        azure_config_dir=tmp_path,
        max_wait_seconds=10,
    )

    starts = [command for command in calls if command[2:4] == ["job", "start"]]
    assert starts == [
        [
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
    ]
    assert result["template"]["before"] == expected_hash
    assert result["template"]["after"] == expected_hash
    assert result["template"]["override_fields"] == []
    assert result["execution_hash"] == _full_opaque("execution-raw-id")
    assert result["logs"] == [{"Log_s": '{"status":"PASS","count":3}'}]


def test_fetch_live_job_uses_only_isolated_deployer_context(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    seen: list[tuple[list[str], Path]] = []

    def fake_az(
        command: list[str],
        *,
        azure_config_dir: Path,
        **_: object,
    ) -> object:
        seen.append((command, azure_config_dir))
        return _template()

    monkeypatch.setattr(
        "scripts.validate_ontology_discovery_live._run_isolated_az_json",
        fake_az,
    )
    assert fetch_live_job(
        resource_group="opaque-group",
        job_name="ontology-fixture-prepare",
        azure_config_dir=tmp_path,
    ) == _template()
    assert seen == [
        (
            [
                "az",
                "containerapp",
                "job",
                "show",
                "--resource-group",
                "opaque-group",
                "--name",
                "ontology-fixture-prepare",
                "-o",
                "json",
            ],
            tmp_path,
        )
    ]


def test_configured_curator_tools_are_read_from_live_agent_definition(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    coordinator = _template()
    environment = coordinator["properties"]["template"]["containers"][0]["env"]
    environment.extend(
        [
            {
                "name": "FOUNDRY_PROJECT_ENDPOINT",
                "value": "https://foundry.invalid/project",
            },
            {"name": "FOUNDRY_ONTOLOGY_AGENT_NAME", "value": "curator"},
            {"name": "FOUNDRY_ONTOLOGY_AGENT_VERSION", "value": "7"},
        ]
    )
    monkeypatch.setattr(
        "scripts.validate_ontology_discovery_live._run_isolated_az_json",
        lambda *_args, **_kwargs: {
            "name": "curator",
            "state": "enabled",
            "versions": {
                "latest": {
                    "id": "curator:1",
                    "status": "active",
                    "definition": {
                        "kind": "prompt",
                        "model": "gpt-5.4-mini",
                        "tools": [
                            {
                                "allowed_tools": {
                                    "tool_names": list(
                                        EXPECTED_CURATOR_TOOLS
                                    )
                                }
                            }
                        ]
                    },
                }
            },
        },
    )

    result = _configured_curator_tools(
        coordinator_job=coordinator,
        azure_config_dir=tmp_path,
    )
    assert result["configured_tools"] == list(EXPECTED_CURATOR_TOOLS)
    assert result["configured_version_hash"] != result["deployed_version_hash"]


def test_deployed_stage_dispatch_is_ordered_resumable_and_idempotent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output = tmp_path / "artifact.json"
    checkpoint = tmp_path / "checkpoint.json"
    deployer = tmp_path / "deployer"
    deployer.mkdir(mode=0o700)
    os.chmod(deployer, 0o700)
    monkeypatch.setenv("AIOPS_DEPLOYER_AZURE_CONFIG_DIR", str(deployer))
    monkeypatch.delenv("AIOPS_EVIDENCE_AZURE_CONFIG_DIR", raising=False)
    hashes = {
        name: f"sha256:{index:064x}"
        for index, name in enumerate(FIXED_JOB_NAMES, start=1)
        if name != "evidence"
    }
    contract = Plan19DeploymentContract(
        status="applied",
        template_hashes=hashes,
        validation_connection_root_hash="sha256:" + "a" * 64,
        coordinator_tag_hash="sha256:" + "b" * 64,
    )
    calls: list[str] = []

    monkeypatch.setattr(
        "scripts.validate_ontology_discovery_live.load_plan19_deployment_contract",
        lambda: contract,
    )

    def stage_result(name: str) -> dict[str, object]:
        calls.append(name)
        if name == "lifecycle":
            return {
                "status": "PASS",
                "evidence": _complete_lifecycle(),
                "evaluation": {"status": "PASS"},
            }
        if name == "publication":
            return {
                "status": "PASS",
                "evidence": {"release_status": "BLOCKED/PENDING"},
                "evaluation": {"status": "PASS"},
            }
        return {"status": "PASS", "release_status": "BLOCKED/PENDING"}

    for stage in DEPLOYED_STAGES:
        monkeypatch.setattr(
            f"scripts.validate_ontology_discovery_live._run_{stage}_stage",
            lambda *_, _stage=stage, **__: stage_result(_stage),
        )

    def argv(stage: str) -> list[str]:
        return [
            "--stage",
            stage,
            "--environment",
            "validation",
            "--shadow",
            "--resume-file",
            str(checkpoint),
            "--output",
            str(output),
            "--fail-on-missing-evidence",
        ]

    assert main(argv("preflight")) == 0
    assert main(argv("preflight")) == 0
    assert calls == ["preflight"]
    with pytest.raises(EvidenceError, match="stage transition"):
        merge_resume_checkpoint(
            checkpoint,
            requested_stage="publication",
            evidence_ref="sha256:" + "c" * 64,
        )
    assert main(argv("lifecycle")) == 0
    assert main(argv("publication")) == 0
    assert main(argv("finalize")) == 0
    assert calls == list(DEPLOYED_STAGES)
    artifact = json.loads(output.read_text(encoding="utf-8"))
    assert artifact["completed_stages"] == list(DEPLOYED_STAGES)
    assert artifact["status"] == "PASS"
    assert load_resume_checkpoint(checkpoint)["completed_step_count"] == 4


def test_deployed_stage_failure_artifact_never_retains_exception_text(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output = tmp_path / "artifact.json"
    checkpoint = tmp_path / "checkpoint.json"
    deployer = tmp_path / "deployer"
    deployer.mkdir(mode=0o700)
    os.chmod(deployer, 0o700)
    monkeypatch.setenv("AIOPS_DEPLOYER_AZURE_CONFIG_DIR", str(deployer))
    monkeypatch.delenv("AIOPS_EVIDENCE_AZURE_CONFIG_DIR", raising=False)
    monkeypatch.setattr(
        "scripts.validate_ontology_discovery_live.load_plan19_deployment_contract",
        lambda: Plan19DeploymentContract(
            status="applied",
            template_hashes={},
            validation_connection_root_hash="sha256:" + "a" * 64,
            coordinator_tag_hash="sha256:" + "b" * 64,
        ),
    )
    monkeypatch.setattr(
        "scripts.validate_ontology_discovery_live._run_preflight_stage",
        lambda *_, **__: (_ for _ in ()).throw(
            EvidenceError(
                "Bearer super-secret /subscriptions/raw command=az containerapp"
            )
        ),
    )

    assert (
        main(
            [
                "--stage",
                "preflight",
                "--environment",
                "validation",
                "--shadow",
                "--resume-file",
                str(checkpoint),
                "--output",
                str(output),
                "--fail-on-missing-evidence",
            ]
        )
        == 1
    )
    rendered = output.read_text(encoding="utf-8")
    assert "super-secret" not in rendered
    assert "/subscriptions/raw" not in rendered
    report = json.loads(rendered)
    assert report["blocker_code"] == "evidence_precondition"
    assert report["closed_reason"] == "evidence_precondition"
    assert report["status"] == "FAIL"
