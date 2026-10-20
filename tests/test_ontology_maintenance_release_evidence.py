"""Plan 05 saved evidence tests. All keys/corpus/receipts are isolated simulations."""

from __future__ import annotations

import copy
import hashlib
import json
import socket
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from ontology_discovery.maintenance_release import (
    LIVE_EVIDENCE_KINDS,
    PURPOSE_LIVE,
    TrustedKey,
    canonical_json,
    digest,
)
from scripts.validate_ontology_agent_maintenance import verify_saved_bundle
from tests.test_ontology_maintenance_admission import (
    NOW,
    Authority,
    _key,
    _pub,
    _sign,
)


def test_saved_release_bundle_validates_without_network(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("network forbidden")

    monkeypatch.setattr(socket, "socket", forbidden)
    authority = Authority(tmp_path)
    report, code = verify_saved_bundle(
        {"attestation": authority.envelope, "migration": "none"},
        mode="offline-qualification",
        reader=authority.reader(),
    )
    assert code == 0
    assert report["offline"]["status"] == "PASS"
    assert report["native"]["status"] == "UNSUPPORTED"
    assert report["live"]["status"] == "BLOCKED"
    assert report["admission"]["status"] == "BLOCKED"
    assert report["migration"]["status"] == "NONE"
    assert len(report["open_questions"]) == 5
    assert report["prerequisite"]["status"] == "SIMULATED_PASS"


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("issuer", "issuer_untrusted"),
        ("environment", "environment_mismatch"),
        ("implementation", "implementation_digest_mismatch"),
        ("deployment", "deployment_not_accepted"),
        ("approval", "approvals_incomplete"),
        ("expiry", "attestation_expired"),
        ("targets", "prerequisite_targets_incomplete"),
        ("native", "native_unsupported"),
        ("revocation", "revocation_revision_changed"),
        ("signature", "signature_invalid"),
    ],
)
def test_cli_and_runtime_share_authenticated_attestation_contract(
    tmp_path, mutation, reason
):
    authority = Authority(tmp_path)
    payload = authority.payload()
    if mutation == "issuer":
        payload["issuer"]["issuer_id"] = "unknown"
    elif mutation == "environment":
        payload["environment"] = "wrong"
    elif mutation == "implementation":
        payload["implementation_digest"] = "wrong"
    elif mutation == "deployment":
        payload["deployment_decision"]["status"] = "proposed"
    elif mutation == "expiry":
        payload["expires_at"] = (NOW - timedelta(seconds=1)).isoformat()
    elif mutation == "targets":
        payload["prerequisite"]["targets"] = ["03.8"]
    elif mutation == "native":
        payload["release"]["native_planner"] = True
        payload["adapter_receipt"] = {"qualified": True}
    authority.envelope = authority.sign(
        payload, drop_role="security_owner" if mutation == "approval" else None
    )
    if mutation == "signature":
        authority.envelope["payload"]["release"]["item_id"] = "forged"
    if mutation == "revocation":
        authority.control["revocation_revision"] += 1
    readers = [authority.reader(), authority.reader()]  # coordinator and publisher
    assert [reader.check() for reader in readers] == [reason, reason]
    report, code = verify_saved_bundle(
        {"attestation": authority.envelope, "migration": "none"},
        mode="live-release",
        reader=authority.reader(),
    )
    assert code != 0
    assert report["authentication"]["reasons"] == [reason]


@pytest.mark.parametrize(
    "missing",
    ["03.1-19", "03.1-20"]
    + [f"07-{n:02}" for n in range(1, 7)]
    + [f"09-{n:02}" for n in range(1, 12)]
    + [f"03.7-{n:02}" for n in range(1, 13)]
    + [f"11-{n:02}" for n in range(1, 17)]
    + [f"13-{n:02}" for n in range(1, 23)]
    + ["03.8-01", "03.8-02"],
)
def test_inherited_prerequisite_manifest_cannot_be_weakened(tmp_path, missing):
    authority = Authority(tmp_path)
    next(authority.root.glob(f"phases/*/{missing}-SUMMARY.md")).unlink()
    reason = f"prerequisite_summary_missing:{missing}"
    assert authority.reader().check() == reason
    report, code = verify_saved_bundle(
        {"attestation": authority.envelope}, mode="live-release",
        reader=authority.reader(),
    )
    assert code == 1
    assert report["authentication"]["reasons"] == [reason]


@pytest.mark.parametrize(
    "marker",
    ["waiver", "waived", "deferral", "deferred", "conditional acceptance",
     "conditional_acceptance", "human_needed", "gaps_found"],
)
def test_qualified_verification_is_not_passed(tmp_path, marker):
    authority = Authority(tmp_path)
    verification = next(authority.root.glob("phases/03.8-*/*-VERIFICATION.md"))
    verification.write_text(f"---\nstatus: passed\nnote: {marker}\n---\n")
    assert authority.reader().check() == "prerequisite_verification_not_passed:03.8"


def live_authority(tmp_path: Path) -> Authority:
    """Synthetic live *schema* case, never production trust or retained acceptance."""
    authority = Authority(tmp_path)
    authority.trust = replace(authority.trust, purpose=PURPOSE_LIVE)
    # The live contract requires actual plan files, including the unresolved real 22.
    for summary in authority.root.glob("phases/*/*-SUMMARY.md"):
        summary.with_name(summary.name.replace("-SUMMARY", "-PLAN")).write_text("plan\n")
    first = next(authority.root.glob("phases/13-*/13-20-SUMMARY.md"))
    first.write_text(
        "---\nstatus: complete\ncompleted: 2026-10-18T10:00:00+00:00\n"
        "accepted: true\n---\nfinalization\n"
    )
    second = first.with_name("13-21-SUMMARY.md")
    second.write_text(
        "---\nstatus: complete\nstarted: 2026-10-18T11:00:00+00:00\n"
        "completed: 2026-10-18T12:00:00+00:00\naccepted: true\n"
        f"plan20_finalization_digest: {hashlib.sha256(first.read_bytes()).hexdigest()}"
        "\n---\nfinal acceptance\n"
    )
    payload = authority.payload()
    payload["purpose"] = PURPOSE_LIVE
    payload["release"]["tenant_id"] = "262a3a77-7d74-4684-8937-897d98d2a17a"
    payload["release"]["subscription_id"] = "890c9bfc-d09c-4143-9ce5-465e75e3eecc"
    plans = {
        str(p.relative_to(authority.root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in authority.root.glob("phases/*/*-PLAN.md")
    }
    payload["prerequisite"]["plan_manifest_digest"] = digest(sorted(plans.items()))
    payload["prerequisite"]["inherited_preconditions_digest"] = digest(sorted(plans.items()))
    payload["qualification"] = {"artifacts": []}
    authority.envelope = authority.sign(payload)
    return authority


def test_live_requires_owned_qualification_not_booleans(tmp_path):
    authority = live_authority(tmp_path)
    payload = copy.deepcopy(authority.envelope["payload"])
    payload["qualification"] = {"passed": True}
    authority.envelope = authority.sign(payload)
    assert authority.reader().check() == "live_evidence_missing:scope_security"


def test_live_corrected_target_is_pinned(tmp_path):
    authority = live_authority(tmp_path)
    payload = copy.deepcopy(authority.envelope["payload"])
    payload["release"]["tenant_id"] = "old-tenant"
    authority.envelope = authority.sign(payload)
    assert authority.reader().check() == "corrected_target_mismatch:tenant_id"


def test_live_plan21_must_start_after_accepted_plan20(tmp_path):
    authority = live_authority(tmp_path)
    second = next(authority.root.glob("phases/13-*/13-21-SUMMARY.md"))
    second.write_text(second.read_text().replace("11:00:00", "09:00:00"))
    payload = authority.payload()
    previous = authority.envelope["payload"]
    payload.update({k: previous[k] for k in ("purpose", "release", "qualification")})
    payload["prerequisite"]["plan_manifest_digest"] = previous["prerequisite"]["plan_manifest_digest"]
    authority.envelope = authority.sign(payload)
    assert authority.reader().check() == "plan21_precedes_plan20_finalization"


def test_unconfigured_cli_fails_closed_and_does_not_accept_input_trust(tmp_path, monkeypatch):
    from scripts.validate_ontology_agent_maintenance import main

    authority = Authority(tmp_path)
    source, output = tmp_path / "input.json", tmp_path / "output.json"
    source.write_text(json.dumps({
        "attestation": authority.envelope, "trust": {"purpose": PURPOSE_LIVE},
        "migration": "none",
    }))
    monkeypatch.delenv("ONTOLOGY_MAINTENANCE_TRUST_CONFIG", raising=False)
    assert main(["--mode", "live-release", "--input", str(source), "--output", str(output)]) == 1
    result = json.loads(output.read_text())
    assert result["live"]["status"] == "BLOCKED"
    assert "production_trust_unconfigured" in result["authentication"]["reasons"]


def test_input_attestation_cannot_substitute_for_server_pinned_release(tmp_path):
    authority = Authority(tmp_path)
    different = copy.deepcopy(authority.envelope)
    different["payload"]["release"]["release_id"] = "substituted"
    report, code = verify_saved_bundle(
        {"attestation": different}, mode="offline-qualification", reader=authority.reader(),
    )
    assert code == 1
    assert report["authentication"]["reasons"] == ["input_attestation_not_pinned"]


def test_saved_envelope_bytes_remain_unchanged(tmp_path):
    authority = Authority(tmp_path)
    before = canonical_json(authority.envelope)
    verify_saved_bundle(
        {"attestation": authority.envelope}, mode="offline-qualification", reader=authority.reader(),
    )
    assert canonical_json(authority.envelope) == before


def qualified_live_authority(tmp_path):
    from fabric.dataset_mapper import (
        ONTOLOGY_ENTITY_TYPES,
        ONTOLOGY_RELATIONSHIP_TYPES,
        ontology_entity_table,
        ontology_relationship_table,
    )

    authority = live_authority(tmp_path)
    payload = copy.deepcopy(authority.envelope["payload"])
    binding = digest({k: v for k, v in payload.items() if k not in {"approvals", "qualification"}})
    artifacts = []
    issuers = dict(authority.trust.issuers)
    tables = {"ontology_entities", "ontology_relationships", "ontology_health", "ontology_quality_report"}
    tables.update(ontology_entity_table(entity) for entity in ONTOLOGY_ENTITY_TYPES)
    tables.update(ontology_relationship_table(*triple) for triple in ONTOLOGY_RELATIONSHIP_TYPES)
    products = [
        {"table": table, "row_hash": digest(table), "delta_version": 2}
        for table in sorted(tables)
    ]
    measured = {
        "scope_security": dict.fromkeys(
            ("scope_denials_digest", "injection_results_digest", "identity_matrix_digest"), digest("security")),
        "source_discovery": dict.fromkeys(
            ("declaration_capture_digest", "appdependencies_capture_digest", "exact_pair_digest"), digest("sources")),
        "restart_replay": {"baseline_digest": digest("baseline"), "replayed_digest": digest("baseline"),
                           "process_id_before": "first", "process_id_after": "second"},
        "target_preservation": dict.fromkeys(
            ("full_capture_digest", "normalized_readback_digest", "predecessor_digest",
             "exclusive_writer_digest", "rules_history_disposition_digest"), digest("capture")),
        "quality": {"adjudications_digest": digest("adjudications"), "slice_results_digest": digest("slices"),
                    "citation_results_digest": digest("citations"), "evaluation_digest": digest(payload["evaluation"])},
        "budget_cost": dict.fromkeys(
            ("usage_digest", "price_digest", "latency_samples_digest", "limits_digest"), digest("budget")),
        "kill_revoke": dict.fromkeys(
            ("kill_receipt_digest", "revocation_receipt_digest", "no_later_write_digest"), digest("kill")),
        "stale_writer": {"loser_fence": 1, "winner_fence": 2, "winner_products_digest": digest("winner")},
        "products": {"candidate_digest": digest("new"), "catalog_digest": digest("catalog"), "products": products},
        "deployment": {
            **{k: payload[k] for k in ("implementation_digest", "identity_digest",
                                      "template_digest", "root_capability_digest")},
            "decision_digest": payload["deployment_decision"]["decision_digest"],
            "immutable_image_digest": digest("image"),
            "target_digest": digest({k: payload["release"][k] for k in (
                "tenant_id", "subscription_id", "connection_id", "workspace_id", "item_id")}),
        },
    }
    for index, kind in enumerate(LIVE_EVIDENCE_KINDS):
        key = _key(40 + index)
        collector = f"isolated-collector-{index}"
        issuers[collector] = TrustedKey(collector, _pub(key), frozenset({"evidence_collector"}))
        if kind.startswith("recovery_"):
            old = [{**p, "delta_version": 0} for p in products]
            new = [{**p, "delta_version": 1, "row_hash": digest("new-" + p["table"])} for p in products]
            measurements = {"old_digest": digest("old"), "new_digest": digest("new"),
                            "restored_digest": digest("old"), "restart_process_id": "new-process",
                            "products": products, "old_products": old, "new_products": new,
                            "catalog_digest": digest("catalog")}
        elif kind.startswith("consumer_"):
            measurements = dict.fromkeys(
                ("generation_digest", "product_fingerprint", "query_digest", "response_digest"), digest(kind))
            measurements["generation_digest"] = digest("new")
            measurements["product_fingerprint"] = digest({
                "catalog_digest": digest("catalog"), "products": products,
            })
        else:
            measurements = measured[kind]
        receipt = {
            "kind": kind, "origin": "live", "collector_id": collector,
            "source_id": f"isolated-source-{index}", "capture_id": f"isolated-capture-{index}",
            "result_digest": digest(measurements), "binding": binding,
            "observed_at": (NOW - timedelta(hours=1)).isoformat(),
            "expires_at": (NOW + timedelta(hours=1)).isoformat(), "measurements": measurements,
        }
        envelope = {"algorithm": "Ed25519", "key_id": collector, "payload": receipt,
                    "signature": _sign(key, canonical_json(receipt))}
        path = authority.root / f"{kind}.json"
        path.write_bytes(canonical_json(envelope))
        artifacts.append({"kind": kind, "path": path.name,
                          "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    authority.trust = replace(authority.trust, issuers=issuers)
    payload["qualification"] = {"artifacts": artifacts}
    authority.envelope = authority.sign(payload)
    return authority


def test_complete_synthetic_live_schema_not_always_denied(tmp_path, monkeypatch):
    monkeypatch.setattr(socket, "socket", lambda *a, **k: pytest.fail("network forbidden"))
    authority = qualified_live_authority(tmp_path)
    assert authority.reader().check() == ""
    report, code = verify_saved_bundle(
        {"attestation": authority.envelope, "migration": "none"},
        mode="live-release", reader=authority.reader(),
    )
    assert code == 0
    assert report["live"]["status"] == "PASS"
    assert report["native"]["status"] == "UNSUPPORTED"
    assert report["offline"]["status"] == "PENDING"
    # This in-memory trust is never a production config or retained acceptance.
    assert authority.trust.artifact_root.is_relative_to(tmp_path)


@pytest.mark.parametrize("kind", LIVE_EVIDENCE_KINDS)
def test_every_live_receipt_required_with_runtime_denial_equivalence(tmp_path, kind):
    authority = qualified_live_authority(tmp_path)
    reference = next(a for a in authority.envelope["payload"]["qualification"]["artifacts"] if a["kind"] == kind)
    (authority.root / reference["path"]).write_text("{}")
    reason = f"live_evidence_digest_mismatch:{kind}"
    assert authority.reader().check() == reason
    report, code = verify_saved_bundle(
        {"attestation": authority.envelope}, mode="live-release", reader=authority.reader(),
    )
    assert code == 1
    assert report["authentication"]["reasons"] == [reason]


def test_positive_offline_saved_file_and_negative_live_cli(tmp_path, monkeypatch):
    from scripts import validate_ontology_agent_maintenance as cli

    authority = Authority(tmp_path)
    source, output = tmp_path / "positive-offline.json", tmp_path / "disposition.json"
    source.write_text(json.dumps({"attestation": authority.envelope, "migration": "none"}))
    # Dependency injection exists only in this test, never an argument/env key.
    monkeypatch.setattr(cli, "build_production_reader", authority.reader)
    assert cli.main(["--mode", "offline-qualification", "--input", str(source), "--output", str(output)]) == 0
    assert json.loads(output.read_text())["offline"]["status"] == "PASS"
    assert cli.main(["--mode", "live-release", "--input", str(source), "--output", str(output)]) == 1
    assert json.loads(output.read_text())["live"]["reasons"] == ["offline_purpose_cannot_authorize_live"]


@pytest.mark.parametrize(
    "proof",
    ["delegated_ui", "mcp_query", "definition_rest_identity", "cookies",
     "private_endpoint", "narrative", "expired_delegation", "qualified_adapter_receipt"],
)
def test_native_receipts_cannot_implement_missing_adapter(tmp_path, proof):
    authority = Authority(tmp_path)
    payload = authority.payload()
    payload["release"]["native_planner"] = True
    payload["native_proof"] = {"kind": proof, "qualified": True}
    authority.envelope = authority.sign(payload)
    assert authority.reader().check() == "native_unsupported"


def test_fresh_readers_recheck_revocation_expiry_and_changed_artifacts(tmp_path):
    authority = qualified_live_authority(tmp_path)
    coordinator, publisher = authority.reader(), authority.reader()
    assert coordinator.check() == publisher.check() == ""
    authority.control["kill"] = True
    assert coordinator.check() == publisher.check() == "kill_switch_engaged"
    authority.control["kill"] = False
    authority.clock[0] = NOW + timedelta(days=31)
    assert coordinator.check() == publisher.check() == "attestation_expired"
    authority.clock[0] = NOW
    plan = next(authority.root.glob("phases/11-*/*-PLAN.md"))
    plan.write_text("changed implementation prerequisites")
    assert coordinator.check() == publisher.check() == "prerequisite_plan_manifest_digest_mismatch"


def test_migration_request_is_not_authorization(tmp_path):
    authority = qualified_live_authority(tmp_path)
    report, code = verify_saved_bundle(
        {"attestation": authority.envelope, "migration": {"approved": True}},
        mode="live-release", reader=authority.reader(),
    )
    assert code == 1
    assert report["migration"]["reasons"] == ["separate_migration_authority_required"]


def test_saved_signature_cannot_be_substituted_even_with_same_payload(tmp_path):
    authority = Authority(tmp_path)
    envelope = copy.deepcopy(authority.envelope)
    envelope["signature"] = "not-the-pinned-signature"
    report, code = verify_saved_bundle(
        {"attestation": envelope}, mode="offline-qualification", reader=authority.reader(),
    )
    assert code == 1
    assert report["authentication"]["reasons"] == ["input_attestation_not_pinned"]


@pytest.mark.parametrize(
    ("kind", "change", "reason"),
    [
        ("scope_security", "origin", "live_evidence_origin_invalid:scope_security"),
        ("scope_security", "binding", "live_evidence_binding_mismatch:scope_security"),
        ("scope_security", "expiry", "live_evidence_stale:scope_security"),
        ("scope_security", "signature", "signature_invalid"),
        ("scope_security", "booleans", "live_evidence_measurements_missing:scope_security"),
        ("products", "incomplete", "live_products_incomplete:products"),
        ("recovery_postcheck", "restore_hash", "live_physical_restore_mismatch:recovery_postcheck"),
        ("recovery_cas", "restore_version", "live_physical_restore_mismatch:recovery_cas"),
        ("consumer_fabric", "repeated_observer", "consumer_observation_not_independent"),
        ("deployment", "wrong_implementation", "live_deployment_binding_mismatch"),
        ("consumer_agent", "wrong_products", "live_consumer_product_binding_mismatch:consumer_agent"),
    ],
)
def test_signed_negative_live_receipts(tmp_path, kind, change, reason):
    authority = qualified_live_authority(tmp_path)
    payload = copy.deepcopy(authority.envelope["payload"])
    reference = next(a for a in payload["qualification"]["artifacts"] if a["kind"] == kind)
    path = authority.root / reference["path"]
    envelope = json.loads(path.read_text())
    receipt = envelope["payload"]
    measurements = receipt["measurements"]
    if change == "origin":
        receipt["origin"] = "offline"
    elif change == "binding":
        receipt["binding"] = digest("different-release")
    elif change == "expiry":
        receipt["expires_at"] = (NOW - timedelta(seconds=1)).isoformat()
    elif change == "booleans":
        receipt["measurements"] = {"passed": True}
    elif change == "incomplete":
        measurements["products"] = measurements["products"][:3]
    elif change == "restore_hash":
        measurements["products"][0]["row_hash"] = digest("not-restored")
    elif change == "restore_version":
        measurements["products"][0]["delta_version"] = 1
    elif change == "wrong_implementation":
        measurements["implementation_digest"] = "wrong"
    elif change == "wrong_products":
        measurements["product_fingerprint"] = digest("unrelated-products")
    elif change == "repeated_observer":
        receipt["collector_id"] = "isolated-collector-12"  # API observer
        envelope["key_id"] = "isolated-collector-12"
    index = 12 if change == "repeated_observer" else LIVE_EVIDENCE_KINDS.index(kind)
    receipt["result_digest"] = digest(receipt["measurements"])
    envelope["signature"] = _sign(_key(40 + index), canonical_json(receipt))
    if change == "signature":
        envelope["signature"] = _sign(_key(99), canonical_json(receipt))
    path.write_bytes(canonical_json(envelope))
    reference["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    authority.envelope = authority.sign(payload)
    assert authority.reader().check() == reason
    report, code = verify_saved_bundle(
        {"attestation": authority.envelope}, mode="live-release", reader=authority.reader(),
    )
    assert code == 1
    assert report["authentication"]["reasons"] == [reason]


@pytest.mark.parametrize("target", ["03.7", "03.8"])
def test_missing_verification_denies_even_with_existing_summaries(tmp_path, target):
    authority = Authority(tmp_path)
    next(authority.root.glob(f"phases/{target}-*/*-VERIFICATION.md")).unlink()
    assert authority.reader().check() == f"prerequisite_verification_missing:{target}"


def test_missing_plan22_stays_distinct_and_not_lowered(tmp_path):
    authority = Authority(tmp_path)
    next(authority.root.glob("phases/13-*/13-22-SUMMARY.md")).unlink()
    assert authority.reader().check() == "prerequisite_summary_missing:13-22"


def test_offline_config_cannot_be_selected_by_production_cli(tmp_path, monkeypatch):
    from scripts.validate_ontology_agent_maintenance import main

    config, source, output = (tmp_path / name for name in ("test-trust.json", "bundle.json", "report.json"))
    config.write_text(json.dumps({"purpose": "offline-qualification"}))
    source.write_text("{}")
    monkeypatch.setenv("ONTOLOGY_MAINTENANCE_TRUST_CONFIG", str(config))
    assert main(["--mode", "offline-qualification", "--input", str(source), "--output", str(output)]) == 1
    assert json.loads(output.read_text())["authentication"]["reasons"] == ["maintenance_purpose_not_live"]
