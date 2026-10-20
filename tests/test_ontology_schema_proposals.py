"""Schema proposal import/review: CLI -> strict envelope -> separate durable store."""

from __future__ import annotations

import base64
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from ontology.definition_compatibility import definition_fingerprint, stable_ids
from ontology_discovery import cli
from ontology_discovery.schema_proposal_store import (
    SchemaProposalStore,
    SchemaReviewDenied,
)
from ontology_discovery.schema_proposals import (
    SchemaProposalRejected,
    parse_envelope,
    proposal_id_for,
)

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "ontology_maintenance_definitions.json").read_text()
)
BASE = FIXTURE["legacy_json"]
ENTITY_ID = next(
    p["path"].split("/")[1]
    for p in BASE["parts"]
    if p["path"].startswith("EntityTypes/") and p["path"].endswith("/definition.json")
)
EVIDENCE = ["ev:1", "ev:2"]
TARGET = ["--scope", "tenant-1", "--workspace-id", "ws-1", "--item-id", "item-1",
          "--format", "legacy-json"]


def _envelope(**over) -> dict:
    doc = {
        "kind": "ontology-schema-proposal",
        "version": 1,
        "scope": "tenant-1",
        "workspace_id": "ws-1",
        "item_id": "item-1",
        "format": "legacy-json",
        "base_fingerprint": definition_fingerprint(BASE),
        "source_generation_id": "gen-1",
        "evidence_refs": ["ev:1"],
        "preserved_ids": sorted(stable_ids(BASE)),
        "operations": [
            {"op": "description_change", "target_kind": "entity", "stable_id": ENTITY_ID,
             "before": "", "after": "A server"}
        ],
        "binding_diff": [],
        "provenance": {"provider": "foundry", "model": "gpt-x"},
    }
    doc.update(over)
    return doc


@pytest.fixture
def files(tmp_path: Path) -> dict[str, Path]:
    out = {
        "base": tmp_path / "base.json",
        "evidence": tmp_path / "evidence.json",
        "envelope": tmp_path / "envelope.json",
    }
    out["base"].write_text(json.dumps(BASE))
    out["evidence"].write_text(json.dumps(EVIDENCE))
    out["envelope"].write_text(json.dumps(_envelope()))
    out["store"] = tmp_path / "store"
    return out


def _import(files, capsys, envelope: Path | None = None) -> dict:
    rc = cli.main([
        "schema-proposal-import", "--store-root", str(files["store"]),
        "--envelope", str(envelope or files["envelope"]),
        "--base-definition", str(files["base"]), "--evidence", str(files["evidence"]),
        *TARGET,
    ])
    assert rc == 0
    return json.loads(capsys.readouterr().out)


def _review(files, capsys, pid, reviewer, rev, decision="approve"):
    rc = cli.main([
        "schema-proposal-review", "--store-root", str(files["store"]),
        "--base-definition", str(files["base"]), "--proposal-id", pid,
        "--reviewer", reviewer, "--decision", decision, "--expected-revision", str(rev),
    ])
    assert rc == 0
    return json.loads(capsys.readouterr().out)


def test_schema_import_review_restart_and_base_conflict(files, capsys, monkeypatch) -> None:
    monkeypatch.setenv("AIOPS_SCHEMA_STEWARDS", "alice")
    imported = _import(files, capsys)
    pid = imported["proposal_id"]
    assert imported["advisory_only"] is True
    assert imported["proposal_id"] == _import(files, capsys)["proposal_id"]  # idempotent

    # unauthorized reviewer (payload cannot grant authority) and stale revision deny
    with pytest.raises(SchemaReviewDenied):
        cli.main(["schema-proposal-review", "--store-root", str(files["store"]),
                  "--base-definition", str(files["base"]), "--proposal-id", pid,
                  "--reviewer", "mallory", "--decision", "approve", "--expected-revision", "0"])
    with pytest.raises(SchemaReviewDenied):
        cli.main(["schema-proposal-review", "--store-root", str(files["store"]),
                  "--base-definition", str(files["base"]), "--proposal-id", pid,
                  "--reviewer", "alice", "--decision", "approve", "--expected-revision", "3"])
    assert _review(files, capsys, pid, "alice", 0)["sequence"] == 1
    with pytest.raises(SchemaReviewDenied):  # replayed revision
        cli.main(["schema-proposal-review", "--store-root", str(files["store"]),
                  "--base-definition", str(files["base"]), "--proposal-id", pid,
                  "--reviewer", "alice", "--decision", "approve", "--expected-revision", "0"])

    # independent process reconstruction from the on-disk store only
    code = (
        "import sys;from ontology_discovery.schema_proposal_store import SchemaProposalStore as S;"
        "s=S(sys.argv[1],is_steward=lambda a:False);pid=sys.argv[2];"
        "e=s.load(pid);print(e.item_id,s.revision(pid),s.approval_usable(pid,current_base_fingerprint=e.base_fingerprint))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code, str(files["store"]), pid],
        capture_output=True, text=True, check=True,
        env={"PYTHONPATH": str(Path(__file__).parent.parent / "src"), "PATH": ""},
    ).stdout.split()
    assert out == ["item-1", "1", "True"]

    store = SchemaProposalStore(files["store"], is_steward=lambda a: True)
    assert store.approval_usable(pid, current_base_fingerprint=definition_fingerprint(BASE))
    drifted = deepcopy(BASE)
    drifted["parts"].append(deepcopy(FIXTURE["unknown"]["parts"][0]))
    new_fp = definition_fingerprint(drifted)
    assert not store.approval_usable(pid, current_base_fingerprint=new_fp)
    with pytest.raises(SchemaReviewDenied):
        store.review(pid, reviewer="alice", decision="approve", expected_revision=1,
                     current_base_fingerprint=new_fp)


def test_relationship_state_never_grants_schema_approval(files, capsys, tmp_path) -> None:
    store = SchemaProposalStore(files["store"], is_steward=lambda a: True)
    pid = store.import_proposal(parse_envelope(_envelope()))
    # a relationship-style accepted record elsewhere in the same root is irrelevant
    rel = Path(files["store"]) / "proposals" / pid
    rel.parent.mkdir(parents=True, exist_ok=True)
    rel.write_text(json.dumps({"status": "accepted", "proposal_id": pid}))
    assert not store.approval_usable(pid, current_base_fingerprint=definition_fingerprint(BASE))
    assert store.revision(pid) == 0


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(proposals=[], batch_id="b", status="proposals"),
        lambda d: d.update(patch=[{"op": "replace", "path": "/x", "value": 1}]),
        lambda d: d.update(operations=[{"op": "raw_tmdl", "text": "entityType X"}]),
        lambda d: d.pop("base_fingerprint"),
        lambda d: d.update(base_fingerprint="sha256:" + "0" * 63),
        lambda d: d.update(operations=[{"op": "description_change", "target_kind": "entity",
                                        "stable_id": "not-preserved", "before": "", "after": "x"}]),
        lambda d: d.update(binding_diff=[{"stable_id": ENTITY_ID, "before": "a", "after": "b"}]),
        lambda d: d.update(format="tmdl"),
    ],
)
def test_malformed_envelopes_reject(mutate) -> None:
    doc = _envelope()
    mutate(doc)
    with pytest.raises(SchemaProposalRejected):
        parse_envelope(json.dumps(doc))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(item_id="foreign"),
        lambda d: d.update(evidence_refs=["ev:fabricated"]),
        lambda d: d.update(base_fingerprint="sha256:" + "1" * 64),
        lambda d: d.update(preserved_ids=["ghost-id"], operations=[
            {"op": "description_change", "target_kind": "entity", "stable_id": "ghost-id",
             "before": "", "after": "x"}]),
    ],
)
def test_untrusted_binding_rejected_by_cli(files, capsys, mutate) -> None:
    doc = _envelope()
    mutate(doc)
    files["envelope"].write_text(json.dumps(doc))
    with pytest.raises(SchemaProposalRejected):
        _import(files, capsys)
    assert not Path(files["store"]).exists()


def test_all_operation_classes_validate_without_execution() -> None:
    sid = sorted(stable_ids(BASE))
    doc = _envelope(
        operations=[
            {"op": "declare_entity", "stable_id": "new-e", "name": "Cluster", "description": "d"},
            {"op": "declare_relationship", "stable_id": "new-r", "name": "inCluster",
             "source_stable_id": ENTITY_ID, "target_stable_id": "new-e"},
            {"op": "binding_change", "stable_id": ENTITY_ID, "binding_path": "EntityTypes/x/DataBindings/y.json",
             "before": "a", "after": "b"},
        ],
        binding_diff=[{"stable_id": ENTITY_ID, "before": "a", "after": "b"}],
    )
    envelope = parse_envelope(doc)
    assert proposal_id_for(envelope).startswith("OSP-") and sid


def test_cli_rejects_remote_store_and_keeps_run_once_default() -> None:
    with pytest.raises(SystemExit):
        cli.main(["schema-proposal-import", "--store-root", "abfss://x@onelake/x/Files/y"])
    assert cli._parser().parse_args([]).command == "run-once"


def test_base64_fixture_decodes() -> None:
    assert base64.b64decode(BASE["parts"][0]["payload"]) == b"{}"
