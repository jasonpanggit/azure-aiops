#!/usr/bin/env python3
"""Score the contextual agents against a fixed question set.

Agent quality has so far been asserted from one-off curl probes, which is how
a prompt bug survived long enough to make every specialist look broken. This
runs a fixed set of questions against a deployed environment and reports
aggregate scores, so a change can be shown to help or hurt rather than argued
about.

It is deliberately a script, not a test: it costs real model calls and needs a
deployed environment, so it must never run in CI by accident.

    az login
    python3 scripts/evaluate_agents.py
    python3 scripts/evaluate_agents.py --baseline .planning/eval/baseline.json

What is scored, per question:

* ``routing``      -- did the expected specialists run? This is objective:
                      the expected set is derived from the same catalog the
                      router uses.
* ``groundedness`` -- fraction of findings backed by evidence, as reported by
                      the investigation's own evaluation block.
* ``narration``    -- did Foundry narration succeed? A degraded run still
                      returns deterministic findings, so this is a quality
                      signal, not a failure.
* ``latency_ms``   -- wall clock for the whole investigation.

There is deliberately no LLM-as-judge scoring of answer text. That would make
the harness's own reliability the thing under test. Routing and groundedness
are checkable facts; answer quality is reported for a human to read.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_API = (
    "https://aiops-dev-api.greenpond-732382e3.australiaeast.azurecontainerapps.io"
)
DEFAULT_RESOURCE = "api://306c1437-0e7d-43bd-940b-79b878166331"
REQUEST_TIMEOUT_SECONDS = 300
# Each investigation occupies a worker for 15-100s and the dev API runs a
# single replica, so firing cases back to back saturates it and the gateway
# answers 503 "no healthy upstream". That is a harness artefact, not an agent
# result, so pace the run and retry transient gateway errors.
PAUSE_BETWEEN_CASES_SECONDS = 12
TRANSIENT_STATUSES = frozenset({429, 502, 503, 504})
MAX_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 20


@dataclass(frozen=True)
class Case:
    """One scored question.

    ``expect_specialists`` is the set that must appear. It is a subset check,
    not equality: the router may legitimately add a specialist as the catalog
    grows, and that should not fail an unrelated case.
    """

    case_id: str
    page_kind: str
    question: str
    expect_specialists: frozenset[str]
    note: str = ""


CASES: tuple[Case, ...] = (
    # Page-anchored: the page specialist must lead and answer.
    Case("net-topology", "network", "What depends on demo-vnet?", frozenset({"network"}),
         "Topic-free network question must stay on the network specialist"),
    Case("vuln-exposure", "vulnerability", "Which CVEs are exploitable on internet-facing hosts?",
         frozenset({"vulnerability"}), "Core vulnerability question"),
    Case("patch-priority", "patch", "Which patches should we prioritise this week?",
         frozenset({"patch"}), "Core patch question"),
    Case("incident-cause", "incident", "What is the root cause candidate for the latest incident?",
         frozenset({"incident"}), "Core incident question"),
    Case("gov-owner", "governance", "Who owns the payments business service?",
         frozenset({"governance"}), "Core governance question"),
    # Cross-cutting: the question must pull in a specialist the page alone
    # would never have selected. These are the cases that were broken.
    Case("net-change", "network", "What changed recently that could explain this?",
         frozenset({"network", "change"}), "Change question asked on the network page"),
    Case("net-governance", "network", "Who owns this and is there an approval?",
         frozenset({"network", "governance"}), "Governance question on the network page"),
    Case("net-cve", "network", "Are there CVEs on the hosts behind this hub?",
         frozenset({"network", "vulnerability"}), "Vulnerability question on the network page"),
    Case("vuln-remediate", "vulnerability", "How do I remediate this safely with a rollback?",
         frozenset({"vulnerability", "remediation"}), "Remediation question on the vulnerability page"),
    # Honesty: the estate has no such thing. The agent must say so rather
    # than invent one. Scored by reading the answer, not asserting on it.
    Case("unknown-subject", "network", "What depends on totally-nonexistent-vnet-xyz?",
         frozenset({"network"}), "Must not invent a resource that does not exist"),
)


@dataclass
class Result:
    case_id: str
    ok: bool
    specialists: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    groundedness: float | None = None
    tool_correctness: float | None = None
    narrated: bool = False
    narration_warning: str = ""
    latency_ms: float = 0.0
    stop_reason: str = ""
    timed_out: bool = False
    summary: str = ""
    narration: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "ok": self.ok,
            "specialists": self.specialists,
            "missing": self.missing,
            "groundedness": self.groundedness,
            "tool_correctness": self.tool_correctness,
            "narrated": self.narrated,
            "narration_warning": self.narration_warning,
            "latency_ms": round(self.latency_ms, 1),
            "stop_reason": self.stop_reason,
            "timed_out": self.timed_out,
            "summary": self.summary[:400],
            "narration": self.narration[:400],
            "error": self.error,
        }


def _token(resource: str) -> str:
    proc = subprocess.run(
        ["az", "account", "get-access-token", "--resource", resource,
         "--query", "accessToken", "-o", "tsv"],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(f"could not acquire a token; run `az login` first\n{proc.stderr.strip()}")
    return proc.stdout.strip()


def _investigate(api: str, token: str, case: Case) -> tuple[dict[str, Any], float]:
    payload = json.dumps({
        "snapshot": {
            "version": "1",
            "page_kind": case.page_kind,
            "page_id": f"eval-{case.case_id}",
            "question": case.question,
        }
    }).encode()
    request = urllib.request.Request(
        f"{api}/api/v1/copilot/investigate-context",
        data=payload,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        body = json.load(response)
    return body.get("data", {}), (time.monotonic() - started) * 1000


def _run_case(api: str, resource: str, case: Case) -> Result:
    """Run one case, retrying transient gateway failures.

    The token is acquired per attempt: a full run takes long enough that a
    token acquired at the start can expire before the last case, which
    previously surfaced as a spurious 401.
    """
    last_error = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            data, latency = _investigate(api, _token(resource), case)
            break
        except urllib.error.HTTPError as exc:
            body = exc.read()[:200]
            last_error = f"HTTP {exc.code}: {body!r}"
            if exc.code in TRANSIENT_STATUSES and attempt < MAX_ATTEMPTS:
                print(f"    transient {exc.code}, retrying in {RETRY_BACKOFF_SECONDS}s "
                      f"(attempt {attempt}/{MAX_ATTEMPTS})")
                time.sleep(RETRY_BACKOFF_SECONDS)
                continue
            return Result(case.case_id, ok=False, error=last_error)
        except Exception as exc:  # noqa: BLE001 - one bad case must not end the run
            last_error = str(exc)
            if attempt < MAX_ATTEMPTS:
                print(f"    {last_error[:80]}, retrying in {RETRY_BACKOFF_SECONDS}s")
                time.sleep(RETRY_BACKOFF_SECONDS)
                continue
            return Result(case.case_id, ok=False, error=last_error)
    else:
        return Result(case.case_id, ok=False, error=last_error)

    seen: list[str] = []
    for call in data.get("tool_calls", []):
        specialist = call.get("specialist")
        if specialist and specialist not in seen:
            seen.append(specialist)

    missing = sorted(case.expect_specialists - set(seen))
    evaluation = data.get("evaluation") or {}
    synthesis = data.get("synthesis") or {}
    narration = str(synthesis.get("narration") or "")
    stop_reason = str(data.get("stop_reason") or "")
    # A wall-clock timeout drops specialists that would otherwise have run, so
    # reporting it as a routing miss blames the router for a budget problem.
    # Scored separately: routing is only judged on runs that completed.
    timed_out = stop_reason == "wall_clock_timeout"

    return Result(
        case_id=case.case_id,
        ok=not missing,
        specialists=seen,
        missing=missing,
        groundedness=evaluation.get("groundedness"),
        tool_correctness=evaluation.get("tool_correctness"),
        narrated=bool(narration),
        narration_warning=str(synthesis.get("warning") or synthesis.get("narration_warning") or ""),
        latency_ms=latency,
        stop_reason=stop_reason,
        timed_out=timed_out,
        summary=str(synthesis.get("summary") or narration),
        narration=narration,
    )


def _aggregate(results: list[Result]) -> dict[str, Any]:
    scored = [r for r in results if not r.error]
    # Routing is judged only on runs that finished. A timed-out run drops
    # specialists for budget reasons, and counting that as a routing failure
    # would make the score a latency proxy.
    routable = [r for r in scored if not r.timed_out]
    grounded = [r.groundedness for r in scored if r.groundedness is not None]
    correct = [r.tool_correctness for r in scored if r.tool_correctness is not None]
    return {
        "cases": len(results),
        "errors": sum(1 for r in results if r.error),
        "timeouts": sum(1 for r in scored if r.timed_out),
        "routing_pass": sum(1 for r in routable if r.ok),
        "routing_scored": len(routable),
        "routing_rate": round(sum(1 for r in routable if r.ok) / max(1, len(routable)), 3),
        "narrated": sum(1 for r in scored if r.narrated),
        "narration_rate": round(sum(1 for r in scored if r.narrated) / max(1, len(scored)), 3),
        "groundedness_mean": round(statistics.fmean(grounded), 3) if grounded else None,
        "tool_correctness_mean": round(statistics.fmean(correct), 3) if correct else None,
        "latency_ms_median": round(statistics.median([r.latency_ms for r in scored]), 1) if scored else None,
    }


def _compare(current: dict[str, Any], baseline: dict[str, Any]) -> list[str]:
    """Report movement against a baseline. Higher is better except latency."""
    lines: list[str] = []
    for key, better_is_higher in (
        ("routing_rate", True),
        ("narration_rate", True),
        ("groundedness_mean", True),
        ("tool_correctness_mean", True),
        ("latency_ms_median", False),
    ):
        now, was = current.get(key), baseline.get(key)
        if now is None or was is None:
            continue
        delta = now - was
        if abs(delta) < 1e-9:
            marker = "="
        elif (delta > 0) == better_is_higher:
            marker = "better"
        else:
            marker = "WORSE"
        lines.append(f"  {key:24} {was:>8} -> {now:>8}  {marker}")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default=DEFAULT_API)
    parser.add_argument("--resource", default=DEFAULT_RESOURCE)
    parser.add_argument("--out", type=Path, help="write the full run to this JSON file")
    parser.add_argument("--baseline", type=Path, help="compare against a previous run")
    parser.add_argument("--case", action="append", help="run only these case ids")
    args = parser.parse_args()

    cases = CASES
    if args.case:
        wanted = set(args.case)
        cases = tuple(c for c in CASES if c.case_id in wanted)
        if not cases:
            raise SystemExit(f"no cases matched {sorted(wanted)}")

    # Verify credentials once up front so a misconfigured run fails fast
    # rather than after ten slow cases.
    _token(args.resource)
    print(f"Evaluating {len(cases)} cases against {args.api}\n")

    results: list[Result] = []
    for index, case in enumerate(cases, start=1):
        if index > 1:
            time.sleep(PAUSE_BETWEEN_CASES_SECONDS)
        print(f"[{index}/{len(cases)}] {case.case_id:18} {case.question[:58]}")
        result = _run_case(args.api, args.resource, case)
        results.append(result)
        if result.error:
            print(f"    ERROR {result.error}")
        else:
            status = "TIME" if result.timed_out else ("ok " if result.ok else "MISS")
            print(f"    {status} specialists={result.specialists} "
                  f"grounded={result.groundedness} narrated={result.narrated} "
                  f"{result.latency_ms:.0f}ms")
            if result.missing and not result.timed_out:
                print(f"    expected but absent: {result.missing}")
            if result.timed_out:
                print("    wall-clock timeout; routing not scored for this case")
            if result.narration_warning:
                print(f"    narration warning: {result.narration_warning}")

    summary = _aggregate(results)
    print("\n" + "=" * 62)
    for key, value in summary.items():
        print(f"  {key:24} {value}")

    run = {
        "at": datetime.now(UTC).isoformat(),
        "api": args.api,
        "summary": summary,
        "results": [r.to_dict() for r in results],
    }

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(run, indent=2) + "\n")
        print(f"\nwrote {args.out}")

    if args.baseline and args.baseline.exists():
        baseline = json.loads(args.baseline.read_text()).get("summary", {})
        print(f"\nagainst baseline {args.baseline}:")
        for line in _compare(summary, baseline):
            print(line)

    # A routing miss on a completed run is a real regression. A timeout is a
    # budget problem and a narration outage still leaves deterministic
    # findings standing, so neither fails the run.
    return 1 if summary["errors"] or summary["routing_pass"] < summary["routing_scored"] else 0


if __name__ == "__main__":
    sys.exit(main())
