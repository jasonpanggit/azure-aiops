"""Local corpus inventory never grants release or invents missing evidence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import validate_ontology_agent_maintenance as cli


def _corpus(tmp_path: Path) -> Path:
    phase = tmp_path / "phases/13-autonomous-ontology-discovery-and-fabric-synchronization"
    phase.mkdir(parents=True)
    for number in range(1, 23):
        (phase / f"13-{number:02d}-PLAN.md").write_text("---\nstatus: planned\n---\n")
        (phase / f"13-{number:02d}-SUMMARY.md").write_text("---\nstatus: complete\n---\n")
    (phase / "13-VERIFICATION.md").write_text("---\nstatus: passed\n---\n")
    return phase


def test_diagnostic_separates_missing_plan_from_unfinished_execution(tmp_path):
    phase = _corpus(tmp_path)
    (phase / "13-22-PLAN.md").unlink()
    for number in (21, 22):
        (phase / f"13-{number:02d}-SUMMARY.md").unlink()
    (phase / "13-20-SUMMARY.md").write_text("---\nstatus: partial\n---\n")
    (phase / "13-VERIFICATION.md").write_text("---\nstatus: gaps_found\n---\n")

    report = cli.phase13_corpus_diagnostic(tmp_path)

    assert report["present"] == 20
    assert report["required"] == 22
    assert report["missing"] == ["13-21-SUMMARY.md", "13-22-SUMMARY.md"]
    assert report["missing_plans"] == ["13-22-PLAN.md"]
    assert report["unfinished_summaries"] == [
        {"path": "13-20-SUMMARY.md", "status": "partial"}
    ]
    assert report["verification_status"] == "gaps_found"
    assert report["status"] == "BLOCKED"
    assert report["authority"] == "diagnostic_only"
    assert not (phase / "13-22-PLAN.md").exists()
    assert not (phase / "13-21-SUMMARY.md").exists()


def test_complete_local_corpus_is_not_live_authority(tmp_path):
    _corpus(tmp_path)
    report = cli.phase13_corpus_diagnostic(tmp_path)
    assert report["status"] == "LOCAL_ONLY"
    assert report["authority"] == "diagnostic_only"
    assert report["missing_plans"] == report["unfinished_summaries"] == []


@pytest.mark.parametrize("contents", ["no frontmatter", "---\nstatus: [\n---\n", "---\n[]\n---\n"])
def test_malformed_summary_is_explicitly_unqualified(tmp_path, contents):
    phase = _corpus(tmp_path)
    (phase / "13-20-SUMMARY.md").write_text(contents)
    report = cli.phase13_corpus_diagnostic(tmp_path)
    assert report["status"] == "BLOCKED"
    assert report["unfinished_summaries"] == [
        {"path": "13-20-SUMMARY.md", "status": "unreadable_or_invalid"}
    ]


def test_diagnostic_does_not_change_failed_authentication_exit(tmp_path, monkeypatch):
    _corpus(tmp_path)
    source = tmp_path / "src"
    source.mkdir()
    planning = tmp_path / ".planning"
    (tmp_path / "phases").rename(planning)
    # The diagnostic expects .planning/phases, as the actual command does.
    (planning / "phases").mkdir()
    (planning / "13-autonomous-ontology-discovery-and-fabric-synchronization").rename(
        planning / "phases/13-autonomous-ontology-discovery-and-fabric-synchronization"
    )
    monkeypatch.setattr(cli, "SOURCE", source)
    monkeypatch.setattr(cli, "build_production_reader", lambda: None)
    request = tmp_path / "request.json"
    request.write_text("{}")
    output = tmp_path / "report.json"
    assert cli.main([
        "--input", str(request), "--output", str(output), "--mode", "live-release",
    ]) == 1
    report = json.loads(output.read_text())
    assert report["phase13_count_diagnostic"]["status"] == "LOCAL_ONLY"
    assert report["authentication"]["status"] == "BLOCKED"
    assert report["live"]["status"] == "BLOCKED"
