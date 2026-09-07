#!/usr/bin/env python3
"""Launch loopback Phoenix and inspect sanitized ontology lifecycle traces.

Interactive reproduction:

    UV_INDEX_URL=https://packagefeedproxy.microsoft.io/pypi/simple \
      uv sync --extra eval --locked
    uv run --extra eval phoenix serve
    uv run --extra eval python scripts/inspect_ontology_traces.py \
      --endpoint http://127.0.0.1:6006 \
      --dataset tests/fixtures/ontology_discovery/reference.jsonl \
      --fail-on-redaction

``--launch-local`` performs the server start, readiness wait, synthetic export,
query, inspection, and child termination as one finite command.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.evaluate_ontology_discovery import (
    LIFECYCLE_SPANS,
    TRACE_PROJECT,
    emit_sanitized_lifecycle_spans,
)

EXPECTED_SPAN_NAMES = frozenset(LIFECYCLE_SPANS)
CORRELATION_ATTRIBUTES = frozenset(
    {
        "ontology.run_hash",
        "ontology.batch_hash",
        "ontology.proposal_hash",
        "ontology.source_generation_hash",
    }
)
ALLOWED_ATTRIBUTES = frozenset(
    {
        *CORRELATION_ATTRIBUTES,
        "ontology.synthetic",
        "ontology.lifecycle_status",
        "ontology.policy_decision",
        "ontology.release_status",
        "ontology.publication_status",
        "ontology.rollback_status",
        "ontology.entity_count",
        "ontology.candidate_pair_count",
        "ontology.evidence_count",
        "ontology.model_input_tokens",
        "ontology.model_output_tokens",
        "ontology.attempt_ms",
    }
)
_HASH = re.compile(r"^[a-f0-9]{32}$")
_FORBIDDEN_FRAGMENTS = (
    "/subscriptions/",
    "/resourcegroups/",
    "prompt.body",
    "prompt_text",
    "evidence.body",
    "tool.body",
    "tool_input",
    "tool_output",
    "authorization",
    "bearer ",
    "client_secret",
    "password",
    "tenant_id",
    "subscription_id",
    "resource_id",
    "ignore previous",
    "system prompt",
)
_SAFE_STATUS_VALUES = frozenset(
    {
        "completed",
        "shadow_only",
        "BLOCKED/PENDING",
        "blocked",
        "retained",
    }
)
_FORWARDED_ENVIRONMENT = frozenset(
    {
        "HOME",
        "LANG",
        "LC_ALL",
        "LOGNAME",
        "PATH",
        "SHELL",
        "SSL_CERT_FILE",
        "TMPDIR",
        "USER",
    }
)


def assert_loopback_endpoint(endpoint: str) -> tuple[str, int]:
    """Return host/port only for credential-free loopback HTTP."""

    parsed = urlparse(endpoint)
    if parsed.username or parsed.password:
        raise ValueError("Phoenix endpoint credentials are forbidden")
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or not parsed.port
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Phoenix endpoint must be loopback HTTP with an explicit port")
    return parsed.hostname, parsed.port


def phoenix_environment(
    endpoint: str,
    *,
    working_dir: Path,
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Construct a minimal local-only child environment without credentials."""

    host, port = assert_loopback_endpoint(endpoint)
    source = environ if environ is not None else os.environ
    environment = {
        key: value for key, value in source.items() if key in _FORWARDED_ENVIRONMENT
    }
    environment.update(
        {
            "PHOENIX_HOST": host,
            "PHOENIX_PORT": str(port),
            "PHOENIX_GRPC_PORT": str(_available_loopback_port()),
            "PHOENIX_WORKING_DIR": str(working_dir),
            "PHOENIX_PROJECT_NAME": TRACE_PROJECT,
            "PHOENIX_TELEMETRY_ENABLED": "false",
            "PHOENIX_AGENTS_DISABLE_BASH": "true",
            "NO_PROXY": "127.0.0.1,localhost,::1",
        }
    )
    return environment


def inspect_span_records(records: Sequence[Mapping[str, object]]) -> list[str]:
    """Return explicit redaction/schema violations for Phoenix span records."""

    violations: list[str] = []
    for index, record in enumerate(records):
        name = record.get("name")
        if name not in EXPECTED_SPAN_NAMES:
            violations.append(f"span[{index}].name_not_allowlisted")
        attributes = record.get("attributes")
        if not isinstance(attributes, Mapping):
            violations.append(f"span[{index}].attributes_missing")
            continue
        unknown = sorted(set(attributes) - ALLOWED_ATTRIBUTES)
        if unknown:
            violations.append(f"span[{index}].unknown_attributes:{','.join(unknown)}")
        missing = sorted(CORRELATION_ATTRIBUTES - set(attributes))
        if missing:
            violations.append(f"span[{index}].missing_correlations:{','.join(missing)}")
        for key in CORRELATION_ATTRIBUTES & set(attributes):
            if not isinstance(attributes[key], str) or not _HASH.fullmatch(
                attributes[key]
            ):
                violations.append(f"span[{index}].invalid_opaque_hash:{key}")
        if attributes.get("ontology.synthetic") is not True:
            violations.append(f"span[{index}].not_synthetic")
        _check_bounded_counts(index, attributes, violations)
        for key in (
            "ontology.lifecycle_status",
            "ontology.policy_decision",
            "ontology.release_status",
            "ontology.publication_status",
            "ontology.rollback_status",
        ):
            if key in attributes and attributes[key] not in _SAFE_STATUS_VALUES:
                violations.append(f"span[{index}].invalid_status:{key}")
        serialized = json.dumps(record, sort_keys=True, default=str).casefold()
        for fragment in _FORBIDDEN_FRAGMENTS:
            if fragment in serialized:
                violations.append(f"span[{index}].forbidden_content:{fragment}")
    return sorted(set(violations))


def _check_bounded_counts(
    index: int,
    attributes: Mapping[str, object],
    violations: list[str],
) -> None:
    maxima = {
        "ontology.entity_count": 50,
        "ontology.candidate_pair_count": 200,
        "ontology.evidence_count": 40,
        "ontology.model_input_tokens": 8_000,
        "ontology.model_output_tokens": 1_200,
        "ontology.attempt_ms": 60_000,
    }
    for key, maximum in maxima.items():
        value = attributes.get(key)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or value < 0
            or value > maximum
        ):
            violations.append(f"span[{index}].invalid_bound:{key}")


def inspect_local_phoenix(
    *,
    endpoint: str,
    dataset: Path,
    project_name: str = TRACE_PROJECT,
    timeout_seconds: float = 30.0,
) -> tuple[list[dict[str, object]], list[str]]:
    """Export synthetic spans, query Phoenix, and inspect returned records."""

    assert_loopback_endpoint(endpoint)
    emitted = emit_sanitized_lifecycle_spans(
        dataset,
        endpoint=endpoint,
        project_name=project_name,
    )
    from phoenix.client import Client

    client = Client(base_url=endpoint)
    deadline = time.monotonic() + timeout_seconds
    spans: list[dict[str, object]] = []
    while time.monotonic() < deadline:
        spans = [
            dict(span)
            for span in client.spans.get_spans(
                project_identifier=project_name,
                limit=100,
                timeout=5,
            )
        ]
        if len(spans) >= emitted:
            break
        time.sleep(0.25)
    if len(spans) < emitted:
        return spans, [f"expected_{emitted}_spans_found_{len(spans)}"]
    lifecycle_spans = [
        span for span in spans if span.get("name") in EXPECTED_SPAN_NAMES
    ]
    violations = inspect_span_records(lifecycle_spans)
    missing_names = EXPECTED_SPAN_NAMES - {
        str(span.get("name")) for span in lifecycle_spans
    }
    if missing_names:
        violations.append(f"missing_lifecycle_spans:{','.join(sorted(missing_names))}")
    return lifecycle_spans, sorted(set(violations))


def launch_and_inspect(
    *,
    endpoint: str,
    dataset: Path,
    timeout_seconds: float = 60.0,
) -> tuple[list[dict[str, object]], list[str]]:
    """Run a finite Phoenix child lifecycle and always terminate it."""

    assert_loopback_endpoint(endpoint)
    phoenix = shutil.which("phoenix")
    if not phoenix:
        raise RuntimeError(
            "phoenix executable is unavailable; run the trusted-proxy "
            "`uv sync --extra eval --locked` command first"
        )
    with tempfile.TemporaryDirectory(prefix="ontology-phoenix-") as temporary:
        environment = phoenix_environment(
            endpoint,
            working_dir=Path(temporary),
        )
        process = subprocess.Popen(
            [phoenix, "serve"],
            cwd=ROOT,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            _wait_for_ready(endpoint, process, timeout_seconds=timeout_seconds)
            return inspect_local_phoenix(
                endpoint=endpoint,
                dataset=dataset,
                timeout_seconds=timeout_seconds,
            )
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def _wait_for_ready(
    endpoint: str,
    process: subprocess.Popen[str],
    *,
    timeout_seconds: float,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    health_url = f"{endpoint.rstrip('/')}/healthz"
    last_error = "not started"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Phoenix exited before readiness ({process.returncode})")
        try:
            with urllib.request.urlopen(health_url, timeout=1) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError) as exc:
            last_error = str(exc)
        time.sleep(0.25)
    raise RuntimeError(f"Phoenix readiness timed out: {last_error}")


def _available_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect sanitized synthetic ontology lifecycle spans in self-hosted "
            "loopback Phoenix. First run "
            "`UV_INDEX_URL=https://packagefeedproxy.microsoft.io/pypi/simple "
            "uv sync --extra eval --locked`; for interactive inspection run "
            "`uv run --extra eval phoenix serve` and open "
            "http://localhost:6006."
        )
    )
    parser.add_argument("--launch-local", action="store_true")
    parser.add_argument("--endpoint", default="http://127.0.0.1:6006")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--fail-on-redaction", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.launch_local:
            spans, violations = launch_and_inspect(
                endpoint=args.endpoint,
                dataset=args.dataset,
            )
        else:
            spans, violations = inspect_local_phoenix(
                endpoint=args.endpoint,
                dataset=args.dataset,
            )
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        print(json.dumps({"passed": False, "error": str(exc)}, sort_keys=True))
        return 2
    result = {
        "passed": not violations,
        "endpoint": args.endpoint,
        "project": TRACE_PROJECT,
        "span_count": len(spans),
        "span_names": sorted({str(span.get("name")) for span in spans}),
        "violations": violations,
    }
    print(json.dumps(result, sort_keys=True))
    return 1 if args.fail_on_redaction and violations else 0


if __name__ == "__main__":
    sys.exit(main())
