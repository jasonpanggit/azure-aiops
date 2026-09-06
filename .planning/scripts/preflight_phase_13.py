#!/usr/bin/env python3
"""Fail closed unless Phase 10 and Phase 12 have independent completion evidence."""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

_PHASES = {
    10: {
        "slug": "10-fabric-medallion-capability-expansion",
        "plan_count": 15,
        "requirements": tuple(f"MED-{number:02d}" for number in range(1, 11)),
    },
    12: {
        "slug": "12-network-topology-integrity-and-scale",
        "plan_count": 11,
        "requirements": tuple(f"TOPO-{number:02d}" for number in range(1, 6)),
    },
}


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _frontmatter(path: Path) -> dict[str, Any] | None:
    text = _read_text(path)
    if text is None or not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end < 0:
        return None
    try:
        payload = yaml.safe_load(text[4:end])
    except yaml.YAMLError:
        return None
    return payload if isinstance(payload, dict) else None


def _roadmap_section(roadmap: str, phase: int) -> str | None:
    match = re.search(
        rf"(?ms)^### Phase {phase}:[^\n]*\n(?P<body>.*?)(?=^### Phase \d+(?:\.\d+)?:|\Z)",
        roadmap,
    )
    return match.group("body") if match else None


def _check_roadmap(root: Path, failures: list[str]) -> None:
    path = root / ".planning" / "ROADMAP.md"
    roadmap = _read_text(path)
    if roadmap is None:
        failures.append("roadmap: ROADMAP.md is missing")
        return
    for phase, config in _PHASES.items():
        section = _roadmap_section(roadmap, phase)
        if section is None:
            failures.append(f"phase {phase} roadmap: phase section is missing")
            continue
        plan_pattern = re.compile(rf"^- \[(?P<checked>[ xX])\] {phase}-(?P<number>\d{{2}})-PLAN\.md\b", re.MULTILINE)
        entries = [
            (int(match.group("number")), match.group("checked").casefold() == "x")
            for match in plan_pattern.finditer(section)
        ]
        counts = Counter(number for number, _checked in entries)
        for number in sorted(number for number, count in counts.items() if count > 1):
            failures.append(
                f"phase {phase} roadmap: duplicate plan evidence for {phase}-{number:02d}"
            )
        expected = range(1, int(config["plan_count"]) + 1)
        checked = {number for number, is_checked in entries if is_checked}
        for number in expected:
            if number not in checked:
                failures.append(
                    f"phase {phase} roadmap: missing checked plan {phase}-{number:02d}"
                )


def _check_requirements(root: Path, failures: list[str]) -> None:
    path = root / ".planning" / "REQUIREMENTS.md"
    requirements = _read_text(path)
    if requirements is None:
        failures.append("requirements: REQUIREMENTS.md is missing")
        return
    entries: dict[str, list[bool]] = {}
    for match in re.finditer(
        r"^- \[(?P<checked>[ xX])\] \*\*(?P<requirement>(?:MED|TOPO)-\d{2})\*\*:",
        requirements,
        re.MULTILINE,
    ):
        entries.setdefault(match.group("requirement"), []).append(
            match.group("checked").casefold() == "x"
        )
    for phase, config in _PHASES.items():
        for requirement in config["requirements"]:
            statuses = entries.get(str(requirement), [])
            if len(statuses) > 1:
                failures.append(
                    f"phase {phase} requirements: duplicate evidence for {requirement}"
                )
            if statuses != [True]:
                failures.append(
                    f"phase {phase} requirements: {requirement} is not checked complete"
                )


def _check_summaries(root: Path, failures: list[str]) -> None:
    phases_root = root / ".planning" / "phases"
    for phase, config in _PHASES.items():
        phase_dir = phases_root / str(config["slug"])
        for number in range(1, int(config["plan_count"]) + 1):
            plan_id = f"{phase}-{number:02d}"
            summary = phase_dir / f"{plan_id}-SUMMARY.md"
            metadata = _frontmatter(summary)
            if metadata is None:
                if summary.exists():
                    failures.append(
                        f"phase {phase} summaries: {plan_id} has invalid frontmatter"
                    )
                else:
                    failures.append(
                        f"phase {phase} summaries: {plan_id}-SUMMARY.md is missing"
                    )
                continue
            status = str(metadata.get("status") or "")
            if status != "complete":
                failures.append(
                    f"phase {phase} summaries: {plan_id} status is {status!r}, expected 'complete'"
                )


def _check_artifact_status(
    root: Path,
    failures: list[str],
    *,
    phase: int,
    filename: str,
    expected_status: str,
    extra_truth: tuple[str, Any] | None = None,
) -> None:
    config = _PHASES[phase]
    path = root / ".planning" / "phases" / str(config["slug"]) / filename
    label = filename.removesuffix(".md").split("-", 1)[1].casefold()
    metadata = _frontmatter(path)
    if metadata is None:
        if path.exists():
            failures.append(f"phase {phase} {label}: frontmatter is invalid")
        else:
            failures.append(f"phase {phase} {label}: {filename} is missing")
        return
    status = str(metadata.get("status") or "")
    if status != expected_status:
        failures.append(
            f"phase {phase} {label}: status is {status!r}, expected {expected_status!r}"
        )
    if extra_truth is not None:
        field, expected = extra_truth
        if metadata.get(field) is not expected:
            failures.append(f"phase {phase} {label}: {field} is not true")


def collect_preflight_failures(root: Path) -> list[str]:
    """Return every independently observed dependency fact that is not complete."""
    resolved = Path(root).resolve()
    failures: list[str] = []
    _check_roadmap(resolved, failures)
    _check_requirements(resolved, failures)
    _check_summaries(resolved, failures)
    _check_artifact_status(
        resolved,
        failures,
        phase=10,
        filename="10-VERIFICATION.md",
        expected_status="passed",
    )
    _check_artifact_status(
        resolved,
        failures,
        phase=12,
        filename="12-VALIDATION.md",
        expected_status="complete",
        extra_truth=("nyquist_compliant", True),
    )
    _check_artifact_status(
        resolved,
        failures,
        phase=12,
        filename="12-VERIFICATION.md",
        expected_status="passed",
    )
    return failures


def main(argv: list[str] | None = None) -> int:
    """Run the Phase 13 dependency gate and return a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Repository root containing .planning (default: inferred from script path)",
    )
    args = parser.parse_args(argv)
    failures = collect_preflight_failures(args.root)
    if failures:
        print("Phase 13 dependency preflight failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print(
        "Phase 13 dependency preflight passed: "
        "Phase 10 (15 plans, MED-01..10, verification) and "
        "Phase 12 (11 plans, TOPO-01..05, Nyquist validation, verification)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
