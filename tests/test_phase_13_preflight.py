from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _load_preflight_module():
    script = Path(__file__).parents[1] / ".planning" / "scripts" / "preflight_phase_13.py"
    spec = importlib.util.spec_from_file_location("preflight_phase_13", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _frontmatter(**values: object) -> str:
    lines = ["---"]
    lines.extend(f"{key}: {str(value).lower() if isinstance(value, bool) else value}" for key, value in values.items())
    lines.extend(["---", ""])
    return "\n".join(lines)


def _write_complete_dependency_evidence(root: Path) -> None:
    planning = root / ".planning"
    phase_10 = planning / "phases" / "10-fabric-medallion-capability-expansion"
    phase_12 = planning / "phases" / "12-network-topology-integrity-and-scale"
    phase_10.mkdir(parents=True)
    phase_12.mkdir(parents=True)

    phase_10_plans = "\n".join(
        f"- [x] 10-{number:02d}-PLAN.md — complete" for number in range(1, 16)
    )
    phase_12_plans = "\n".join(
        f"- [x] 12-{number:02d}-PLAN.md — complete" for number in range(1, 12)
    )
    (planning / "ROADMAP.md").write_text(
        "\n".join(
            (
                "### Phase 10: Fabric",
                "**Plans:** 15/15 plans executed",
                "",
                "Plans:",
                phase_10_plans,
                "",
                "### Phase 11: Other",
                "",
                "### Phase 12: Network",
                "**Plans:** 11/11 plans complete",
                "",
                "Plans:",
                phase_12_plans,
                "",
                "### Phase 13: Ontology",
            )
        ),
        encoding="utf-8",
    )
    requirements = [
        *(f"- [x] **MED-{number:02d}**: complete" for number in range(1, 11)),
        *(f"- [x] **TOPO-{number:02d}**: complete" for number in range(1, 6)),
    ]
    (planning / "REQUIREMENTS.md").write_text(
        "\n".join(requirements) + "\n", encoding="utf-8"
    )
    (planning / "STATE.md").write_text(
        "status: complete\nstopped_at: Phase 12 complete\n", encoding="utf-8"
    )

    for phase_dir, phase, count in ((phase_10, 10, 15), (phase_12, 12, 11)):
        for number in range(1, count + 1):
            (phase_dir / f"{phase}-{number:02d}-SUMMARY.md").write_text(
                _frontmatter(
                    phase=f"{phase}-fixture",
                    plan=f"{number:02d}",
                    status="complete",
                ),
                encoding="utf-8",
            )
    (phase_10 / "10-VERIFICATION.md").write_text(
        _frontmatter(phase="10-fixture", status="passed"),
        encoding="utf-8",
    )
    (phase_12 / "12-VALIDATION.md").write_text(
        _frontmatter(
            phase="12-fixture",
            status="complete",
            nyquist_compliant=True,
        ),
        encoding="utf-8",
    )
    (phase_12 / "12-VERIFICATION.md").write_text(
        _frontmatter(phase="12-fixture", status="passed"),
        encoding="utf-8",
    )


def test_complete_independent_dependency_evidence_passes(tmp_path: Path) -> None:
    _write_complete_dependency_evidence(tmp_path)

    failures = _load_preflight_module().collect_preflight_failures(tmp_path)

    assert failures == []


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (
            lambda root: (root / ".planning" / "ROADMAP.md").write_text(
                (root / ".planning" / "ROADMAP.md")
                .read_text(encoding="utf-8")
                .replace("- [x] 10-15-PLAN.md", "- [ ] 10-15-PLAN.md"),
                encoding="utf-8",
            ),
            "phase 10 roadmap: missing checked plan 10-15",
        ),
        (
            lambda root: (
                root
                / ".planning"
                / "phases"
                / "12-network-topology-integrity-and-scale"
                / "12-11-SUMMARY.md"
            ).write_text(
                _frontmatter(phase="12-fixture", plan="11", status="planned"),
                encoding="utf-8",
            ),
            "phase 12 summaries: 12-11 status is 'planned', expected 'complete'",
        ),
        (
            lambda root: (root / ".planning" / "REQUIREMENTS.md").write_text(
                (root / ".planning" / "REQUIREMENTS.md")
                .read_text(encoding="utf-8")
                .replace("- [x] **MED-10**", "- [ ] **MED-10**"),
                encoding="utf-8",
            ),
            "phase 10 requirements: MED-10 is not checked complete",
        ),
        (
            lambda root: (
                root
                / ".planning"
                / "phases"
                / "10-fabric-medallion-capability-expansion"
                / "10-VERIFICATION.md"
            ).write_text(
                _frontmatter(phase="10-fixture", status="failed"),
                encoding="utf-8",
            ),
            "phase 10 verification: status is 'failed', expected 'passed'",
        ),
        (
            lambda root: (
                root
                / ".planning"
                / "phases"
                / "12-network-topology-integrity-and-scale"
                / "12-VALIDATION.md"
            ).write_text(
                _frontmatter(
                    phase="12-fixture",
                    status="complete",
                    nyquist_compliant=False,
                ),
                encoding="utf-8",
            ),
            "phase 12 validation: nyquist_compliant is not true",
        ),
        (
            lambda root: (
                root
                / ".planning"
                / "phases"
                / "12-network-topology-integrity-and-scale"
                / "12-VERIFICATION.md"
            ).unlink(),
            "phase 12 verification: 12-VERIFICATION.md is missing",
        ),
    ],
)
def test_dependency_gate_reports_exact_missing_or_contradictory_fact(
    tmp_path: Path,
    mutate,
    expected: str,
) -> None:
    _write_complete_dependency_evidence(tmp_path)
    mutate(tmp_path)

    failures = _load_preflight_module().collect_preflight_failures(tmp_path)

    assert expected in failures


def test_duplicate_roadmap_evidence_fails(tmp_path: Path) -> None:
    _write_complete_dependency_evidence(tmp_path)
    roadmap = tmp_path / ".planning" / "ROADMAP.md"
    roadmap.write_text(
        roadmap.read_text(encoding="utf-8").replace(
            "- [x] 12-11-PLAN.md — complete",
            "- [x] 12-11-PLAN.md — complete\n- [x] 12-11-PLAN.md — duplicate",
        ),
        encoding="utf-8",
    )

    failures = _load_preflight_module().collect_preflight_failures(tmp_path)

    assert "phase 12 roadmap: duplicate plan evidence for 12-11" in failures


def test_state_claim_alone_cannot_satisfy_dependency_gate(tmp_path: Path) -> None:
    planning = tmp_path / ".planning"
    planning.mkdir()
    (planning / "STATE.md").write_text(
        "status: complete\nstopped_at: Phase 10 and Phase 12 verified\n",
        encoding="utf-8",
    )

    failures = _load_preflight_module().collect_preflight_failures(tmp_path)

    assert "roadmap: ROADMAP.md is missing" in failures
    assert "requirements: REQUIREMENTS.md is missing" in failures
    assert "phase 10 verification: 10-VERIFICATION.md is missing" in failures
    assert "phase 12 verification: 12-VERIFICATION.md is missing" in failures
