"""Plan 22 closes the acceptance chain, not merely the summary denominator."""

from __future__ import annotations

import copy
import hashlib

import pytest

from ontology_discovery import maintenance_release as releases
from scripts.validate_ontology_agent_maintenance import verify_saved_bundle
from tests.test_ontology_maintenance_release_evidence import qualified_live_authority


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ("accepted", "plan22_acceptance_absent"),
        ("digest", "plan22_not_bound_to_plan21"),
        ("early", "plan22_precedes_plan21_acceptance"),
        ("reverse", "plan22_precedes_plan21_acceptance"),
        ("missing-plan", "plan22_plan_missing"),
    ],
)
def test_live_reader_and_cli_deny_invalid_plan22_chain(tmp_path, change, reason):
    authority = qualified_live_authority(tmp_path)
    path = authority.root / "phases/13-ontology/13-22-SUMMARY.md"
    text = path.read_text()
    if change == "accepted":
        text = text.replace("accepted: true", "accepted: false")
    elif change == "digest":
        second = path.with_name("13-21-SUMMARY.md")
        text = text.replace(hashlib.sha256(second.read_bytes()).hexdigest(), "0" * 64)
    elif change == "early":
        text = text.replace("2026-10-18T13:00:00+00:00", "2026-10-18T11:00:00+00:00")
    elif change == "reverse":
        text = text.replace("2026-10-18T14:00:00+00:00", "2026-10-18T12:30:00+00:00")
    else:
        path.with_name("13-22-PLAN.md").unlink()
    path.write_text(text)
    # Isolated test issuer rebinds changed corpus, proving content checks are
    # mandatory even when the caller possesses valid synthetic test signatures.
    payload = copy.deepcopy(authority.envelope["payload"])
    payload["prerequisite"]["manifest_digest"] = releases.verify_prerequisite_corpus(
        authority.root, ["03.7", "03.8"],
    )[0]
    authority.envelope = authority.sign(payload)
    assert authority.reader().check() == reason
    report, code = verify_saved_bundle(
        {"attestation": authority.envelope}, mode="live-release", reader=authority.reader(),
    )
    assert code == 1
    assert report["authentication"]["reasons"] == [reason]


def test_plan22_change_after_signing_cannot_reuse_verified_manifest(tmp_path):
    authority = qualified_live_authority(tmp_path)
    reader = authority.reader()
    assert reader.check() == ""
    path = authority.root / "phases/13-ontology/13-22-SUMMARY.md"
    path.write_text(path.read_text().replace("accepted: true", "accepted: false"))
    assert reader.check() == "prerequisite_manifest_digest_mismatch"
