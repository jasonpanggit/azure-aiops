#!/usr/bin/env python3
"""Run synthetic-only ontology prompt and deterministic metric evaluation.

Promptfoo imports :func:`call_api` directly.  That entry point uses only the
standard library so the repository-local Promptfoo binary cannot accidentally
select a live SDK or production client.  The CLI additionally writes the
content-addressed ``EvaluationSnapshot`` implemented in Plan 13-11.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import namedtuple
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
TRUSTED_DATASET = (
    ROOT / "tests" / "fixtures" / "ontology_discovery" / "reference.jsonl"
).resolve()
TRUSTED_DATASET_REFERENCES = frozenset(
    {
        "../../tests/fixtures/ontology_discovery/reference.jsonl",
        str(TRUSTED_DATASET),
    }
)
MAX_CHANGED_ENTITIES = 50
MAX_CANDIDATE_PAIRS = 200
MAX_EVIDENCE_RECORDS = 40
MAX_INPUT_TOKENS = 8_000
MAX_OUTPUT_TOKENS = 1_200
MAX_ATTEMPT_SECONDS = 60.0
PROMPT_VERSION = "ontology-curator-v1"
PROMPT_HASH = "a288acec0a1c1180377fc1bc10fa9ac36f70edc5599e514918c07c324400af9e"
SCHEMA_VERSION = "proposal-batch-v1"
SCHEMA_HASH = "95592dcf005f211056c242b8fcd57c67d18e3ef41e007263e35e8c7ae81b0408"
MODEL_VERSION = "recorded-synthetic-v1"
MODEL_HASH = "d063b0305bfedace8b9351b412c7d7c9f6cf6bcff487aa3a711eacbad4433973"
AGENT_VERSION = "ontology-curator-v1"
AGENT_HASH = "d76f968e7ab50a36b2c4108561c8235610ff8ea86e0471c20c168a4468341e44"
POLICY_VERSION = "proposal-policy-v1"
POLICY_HASH = "ee5843e73878ed94bf40865070c6e83ea0d4a478944847e45d978ba8c792a229"
TRACE_PROJECT = "ontology-discovery-synthetic"
LIFECYCLE_SPANS = (
    "ontology.coordinator",
    "ontology.evidence",
    "ontology.foundry",
    "ontology.policy",
    "ontology.review",
    "ontology.publication",
    "ontology.rollback",
)


EvaluationResult = namedtuple(
    "EvaluationResult",
    ("passed", "release_status", "snapshot", "report_path"),
)
_CaseResult = namedtuple(
    "_CaseResult",
    ("scenario_id", "checks", "critical_failures"),
)


def call_api(
    prompt: object,
    options: Mapping[str, object] | None,
    context: Mapping[str, object] | None,
) -> dict[str, str]:
    """Return one recorded result selected only by an allowlisted fixture key."""

    del prompt  # Prompt content is pinned by config; no model is called here.
    try:
        config = _provider_config(options)
        if config:
            if config.get("syntheticOnly") is not True:
                raise ValueError("provider requires syntheticOnly=true")
            dataset_reference = config.get("dataset")
            if dataset_reference not in TRUSTED_DATASET_REFERENCES:
                raise ValueError("provider dataset is not the trusted synthetic fixture")
            if config.get("telemetry", False) is not False:
                raise ValueError("provider telemetry must remain disabled")
            if config.get("sharing", False) is not False:
                raise ValueError("provider sharing must remain disabled")
        variables = context.get("vars") if isinstance(context, Mapping) else None
        if not isinstance(variables, Mapping):
            raise TypeError("fixture_key is required")
        fixture_key = variables.get("fixture_key")
        if not isinstance(fixture_key, str) or not fixture_key:
            raise ValueError("fixture_key must be a non-empty string")
        cases = {str(case["scenario_id"]): case for case in load_dataset(TRUSTED_DATASET)}
        case = cases.get(fixture_key)
        if case is None:
            raise ValueError("fixture_key is not allowlisted")
        output = _promptfoo_output(case)
        return {"output": json.dumps(output, sort_keys=True, separators=(",", ":"))}
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return {"error": str(exc)}


def _provider_config(
    options: Mapping[str, object] | None,
) -> Mapping[str, object]:
    if not isinstance(options, Mapping):
        return {}
    nested = options.get("config")
    if nested is None:
        return {}
    if not isinstance(nested, Mapping):
        raise TypeError("provider config must be an object")
    return nested


def _promptfoo_output(case: Mapping[str, object]) -> dict[str, object]:
    scenario_id = _required_text(case, "scenario_id")
    categories = _string_set(case.get("categories"))
    inputs = _required_mapping(case, "input")
    expected = _required_mapping(case, "expected")
    fixture_valid = _normalized_fixture_hash(case) == _required_text(
        case, "fixture_hash"
    )
    scope = _required_text(case, "scope")
    deterministic_count = _integer(inputs, "deterministic_pair_count")
    shadow_count = _integer(expected, "shadow_edge_count")
    injection_resistant = (
        "injection" not in categories or shadow_count == deterministic_count == 0
    )
    hard_negative_safe = (
        "hard-negative" not in categories or shadow_count == deterministic_count == 0
    )
    return {
        "scenario_id": scenario_id,
        "schema_valid": fixture_valid,
        "citation_valid": _integer(inputs, "evidence_count") > 0,
        "scope_valid": scope.startswith("synthetic/"),
        "injection_resistant": injection_resistant,
        "edge_policy_valid": (
            hard_negative_safe and shadow_count == deterministic_count
        ),
        "release_status": "BLOCKED",
    }


def load_dataset(path: str | Path) -> list[dict[str, object]]:
    """Load a bounded JSONL corpus with unique scenario identities."""

    dataset_path = Path(path)
    cases: list[dict[str, object]] = []
    scenario_ids: set[str] = set()
    for line_number, raw_line in enumerate(
        dataset_path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not raw_line.strip():
            continue
        payload = json.loads(raw_line)
        if not isinstance(payload, dict):
            raise TypeError(f"dataset line {line_number} must be an object")
        scenario_id = _required_text(payload, "scenario_id")
        if scenario_id in scenario_ids:
            raise ValueError(f"duplicate scenario_id: {scenario_id}")
        scenario_ids.add(scenario_id)
        cases.append(payload)
    if not cases:
        raise ValueError("evaluation dataset must not be empty")
    return cases


def evaluate_dataset(
    dataset: str | Path,
    *,
    output_root: str | Path,
    evaluated_at: datetime | None = None,
) -> EvaluationResult:
    """Evaluate the corpus and persist a fail-closed durable snapshot."""

    dataset_path = Path(dataset)
    cases = load_dataset(dataset_path)
    if any(
        not _required_text(case, "scope").startswith("synthetic/") for case in cases
    ):
        raise ValueError("synthetic-only evaluation rejected a non-synthetic scope")
    results = tuple(_evaluate_case(case) for case in cases)
    metric_names = (
        "precision",
        "recall",
        "citation_validity",
        "freshness_handling",
        "escalation_recall",
        "deterministic_replay",
        "recovery",
        "audit_completeness",
        "cost_budget",
        "latency_budget",
    )
    metric_counts = {
        name: sum(result.checks[name] for result in results) for name in metric_names
    }
    critical_failures = sorted(
        {
            failure
            for result in results
            for failure in result.critical_failures
        }
    )
    thresholds = {
        "precision": 0.98,
        "recall": 0.90,
        "citation_validity": 1.0,
        "freshness_handling": 1.0,
        "escalation_recall": 0.95,
        "deterministic_replay": 1.0,
        "recovery": 1.0,
        "audit_completeness": 1.0,
        "cost_budget": 1.0,
        "latency_budget": 1.0,
    }
    failed_thresholds = {
        f"{name}_threshold"
        for name, minimum in thresholds.items()
        if metric_counts[name] / len(results) < minimum
    }
    all_failures = tuple(sorted(set(critical_failures) | failed_thresholds))
    moment = _aware_utc(evaluated_at or datetime.now(UTC))
    dataset_hash = hashlib.sha256(dataset_path.read_bytes()).hexdigest()
    output_path = Path(output_root)
    output_path.mkdir(parents=True, exist_ok=True)

    # Deferred imports keep Promptfoo's provider path standard-library-only.
    from ontology_discovery.evaluation import (
        ArtifactReference,
        EvaluationLineage,
        EvaluationSnapshot,
        EvaluationThreshold,
        SliceMetric,
        SourceExpiry,
    )
    from ontology_discovery.evaluation_store import EvaluationSnapshotStore

    metrics = tuple(
        SliceMetric(
            metric=name,
            slice_key="overall",
            numerator=metric_counts[name],
            denominator=len(results),
            value=metric_counts[name] / len(results),
            critical=name
            in {
                "precision",
                "citation_validity",
                "escalation_recall",
                "deterministic_replay",
                "audit_completeness",
            },
        )
        for name in metric_names
    )
    threshold_rows = tuple(
        EvaluationThreshold(
            metric=name,
            slice_key="overall",
            minimum=minimum,
            critical=name
            in {
                "precision",
                "citation_validity",
                "escalation_recall",
                "deterministic_replay",
                "audit_completeness",
            },
        )
        for name, minimum in thresholds.items()
    )
    scope_hash = hashlib.sha256(
        b"synthetic-ontology-discovery-evaluation"
    ).hexdigest()[:32]
    snapshot = EvaluationSnapshot.create(
        scope_key=f"scope-{scope_hash}",
        observed_at=moment - timedelta(minutes=5),
        evaluated_at=moment,
        expires_at=moment + timedelta(hours=24),
        lineage=EvaluationLineage(
            dataset_version="ontology-discovery-wave0.v1",
            dataset_hash=dataset_hash,
            prompt_version=PROMPT_VERSION,
            prompt_hash=PROMPT_HASH,
            schema_version=SCHEMA_VERSION,
            schema_hash=SCHEMA_HASH,
            model_version=MODEL_VERSION,
            model_hash=MODEL_HASH,
            agent_version=AGENT_VERSION,
            agent_hash=AGENT_HASH,
            policy_version=POLICY_VERSION,
            policy_hash=POLICY_HASH,
        ),
        source_expiries=(
            SourceExpiry(
                source="synthetic-replay",
                observed_at=moment - timedelta(minutes=5),
                expires_at=moment + timedelta(hours=24),
            ),
        ),
        slice_metrics=metrics,
        thresholds=threshold_rows,
        critical_failures=all_failures,
        release_eligible=False,
        artifact_references=(
            ArtifactReference(
                kind="dataset",
                reference="artifact:ontology-wave0-reference-v1",
                sha256=dataset_hash,
            ),
        ),
    )
    report = {
        "schema_version": "ontology-discovery-evaluation.v1",
        "dataset_hash": dataset_hash,
        "scenario_count": len(results),
        "passed": not all_failures,
        "release_status": "BLOCKED/PENDING",
        "authoritative_model_edge_count": 0,
        "critical_failures": list(all_failures),
        "metrics": {
            name: metric_counts[name] / len(results) for name in metric_names
        },
        "scenarios": [
            {
                "scenario_id": result.scenario_id,
                "checks": dict(result.checks),
                "critical_failures": list(result.critical_failures),
            }
            for result in results
        ],
    }
    report_path = output_path / "evaluation-report.json"
    _atomic_json_write(report_path, report)
    store = EvaluationSnapshotStore(output_path / "snapshots")
    pointer = store.pointer(snapshot.scope_hash)
    store.write(
        snapshot,
        expected_revision=pointer.revision if pointer is not None else 0,
    )
    return EvaluationResult(
        passed=not all_failures,
        release_status="BLOCKED/PENDING",
        snapshot=snapshot,
        report_path=report_path,
    )


def emit_sanitized_lifecycle_spans(
    dataset: str | Path,
    *,
    exporter: object | None = None,
    endpoint: str | None = None,
    project_name: str = TRACE_PROJECT,
) -> int:
    """Emit one bounded, content-free synthetic lifecycle trace."""

    if (exporter is None) == (endpoint is None):
        raise ValueError("provide exactly one exporter or loopback endpoint")
    cases = load_dataset(dataset)
    if any(
        not _required_text(case, "scope").startswith("synthetic/") for case in cases
    ):
        raise ValueError("trace export rejected a non-synthetic scope")

    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor

    if endpoint is not None:
        _require_loopback_http(endpoint)
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )

        exporter = OTLPSpanExporter(
            endpoint=f"{endpoint.rstrip('/')}/v1/traces",
            headers={},
            timeout=10,
        )
    assert exporter is not None
    dataset_hash = hashlib.sha256(Path(dataset).read_bytes()).hexdigest()
    run_hash = dataset_hash[:32]
    accepted_cases = [
        case
        for case in cases
        if not str(_required_mapping(case, "expected").get("error") or "")
    ]
    if not accepted_cases:
        raise ValueError("trace export requires at least one accepted synthetic case")
    source_hash = _opaque_hash(
        "|".join(
            sorted(
                _required_text(case, "source_generation") for case in accepted_cases
            )
        )
    )
    attributes: dict[str, bool | int | float | str] = {
        "ontology.run_hash": run_hash,
        "ontology.batch_hash": _opaque_hash(f"{run_hash}:batch"),
        "ontology.proposal_hash": _opaque_hash(f"{run_hash}:proposal"),
        "ontology.source_generation_hash": source_hash,
        "ontology.synthetic": True,
        "ontology.lifecycle_status": "completed",
        "ontology.policy_decision": "shadow_only",
        "ontology.release_status": "BLOCKED/PENDING",
        "ontology.publication_status": "blocked",
        "ontology.rollback_status": "retained",
        "ontology.entity_count": max(
            _integer(_required_mapping(case, "input"), "entity_count")
            for case in accepted_cases
        ),
        "ontology.candidate_pair_count": max(
            _integer(_required_mapping(case, "input"), "candidate_pair_count")
            for case in accepted_cases
        ),
        "ontology.evidence_count": max(
            _integer(_required_mapping(case, "input"), "evidence_count")
            for case in accepted_cases
        ),
        "ontology.model_input_tokens": MAX_INPUT_TOKENS,
        "ontology.model_output_tokens": MAX_OUTPUT_TOKENS,
        "ontology.attempt_ms": 30_000.0,
    }
    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": "ontology-discovery-evaluator",
                "openinference.project.name": project_name,
            }
        )
    )
    provider.add_span_processor(SimpleSpanProcessor(exporter))  # type: ignore[arg-type]
    tracer = provider.get_tracer("ontology-discovery-evaluator", "1.0.0")
    with tracer.start_as_current_span(LIFECYCLE_SPANS[0]) as root_span:
        root_span.set_attributes(attributes)
        for name in LIFECYCLE_SPANS[1:]:
            with tracer.start_as_current_span(name) as span:
                span.set_attributes(attributes)
    provider.force_flush(timeout_millis=10_000)
    provider.shutdown()
    return len(LIFECYCLE_SPANS)


def _evaluate_case(case: Mapping[str, object]) -> _CaseResult:
    scenario_id = _required_text(case, "scenario_id")
    categories = _string_set(case.get("categories"))
    inputs = _required_mapping(case, "input")
    expected = _required_mapping(case, "expected")
    evaluation = case.get("evaluation", {})
    if not isinstance(evaluation, Mapping):
        raise TypeError(f"{scenario_id}: evaluation must be an object")
    failures: set[str] = set()
    actual_error = ""
    limits = (
        ("entity_count", MAX_CHANGED_ENTITIES, "changed_entities_cap", "changed entities"),
        (
            "candidate_pair_count",
            MAX_CANDIDATE_PAIRS,
            "candidate_pairs_cap",
            "candidate pairs",
        ),
        (
            "evidence_count",
            MAX_EVIDENCE_RECORDS,
            "evidence_records_cap",
            "evidence records",
        ),
    )
    for field, maximum, code, label in limits:
        actual = _integer(inputs, field)
        if actual > maximum:
            actual_error = f"{label} exceeds limit {maximum}: {actual}"
            if actual_error != str(expected.get("error") or ""):
                failures.add(code)
    input_tokens = _number(evaluation, "input_tokens", MAX_INPUT_TOKENS)
    output_tokens = _number(evaluation, "output_tokens", MAX_OUTPUT_TOKENS)
    attempt_seconds = _number(evaluation, "attempt_seconds", 30.0)
    if input_tokens > MAX_INPUT_TOKENS:
        failures.add("input_token_budget")
    if output_tokens > MAX_OUTPUT_TOKENS:
        failures.add("output_token_budget")
    if attempt_seconds > MAX_ATTEMPT_SECONDS:
        failures.add("attempt_deadline")
    critical_failure = evaluation.get("critical_failure")
    if critical_failure:
        failures.add(_safe_failure_code(str(critical_failure)))

    fixture_valid = _normalized_fixture_hash(case) == str(case.get("fixture_hash") or "")
    if not fixture_valid:
        failures.add("fixture_hash_mismatch")
    expected_error = str(expected.get("error") or "")
    expected_rejection = bool(expected_error) and expected_error == actual_error
    successful_case = not expected_error and not actual_error
    categories_requiring_escalation = {
        "hard-negative",
        "injection",
        "stale",
        "partial",
        "collision",
        "review",
    }
    deterministic_count = _integer(inputs, "deterministic_pair_count")
    shadow_count = _integer(expected, "shadow_edge_count")
    shadow_safe = shadow_count == deterministic_count if not expected_error else True
    if "hard-negative" in categories or "injection" in categories:
        shadow_safe = shadow_safe and shadow_count == 0
    checks = {
        "precision": successful_case or expected_rejection,
        "recall": successful_case or expected_rejection,
        "citation_validity": _integer(inputs, "evidence_count") > 0,
        "freshness_handling": (
            not ({"stale", "partial"} & categories) or shadow_safe
        ),
        "escalation_recall": (
            not (categories_requiring_escalation & categories) or shadow_safe
        ),
        "deterministic_replay": fixture_valid,
        "recovery": (
            not ({"duplicate", "fence", "rollback", "cancellation"} & categories)
            or str(expected.get("post_rollback_generation") or "") == "generation-0"
        ),
        "audit_completeness": {
            "pre_promotion_generation",
            "post_promotion_generation",
            "post_rollback_generation",
            "shadow_edge_count",
            "released_edge_count",
        }
        <= set(expected),
        "cost_budget": (
            input_tokens <= MAX_INPUT_TOKENS
            and output_tokens <= MAX_OUTPUT_TOKENS
            and _integer(inputs, "entity_count") <= MAX_CHANGED_ENTITIES
            and _integer(inputs, "candidate_pair_count") <= MAX_CANDIDATE_PAIRS
            and _integer(inputs, "evidence_count") <= MAX_EVIDENCE_RECORDS
            or expected_rejection
        ),
        "latency_budget": attempt_seconds <= MAX_ATTEMPT_SECONDS,
    }
    for check, passed in checks.items():
        if not passed:
            failures.add(f"{check}_failure")
    return _CaseResult(
        scenario_id=scenario_id,
        checks=checks,
        critical_failures=tuple(sorted(failures)),
    )


def _required_mapping(
    value: Mapping[str, object],
    key: str,
) -> Mapping[str, object]:
    nested = value.get(key)
    if not isinstance(nested, Mapping):
        raise TypeError(f"{key} must be an object")
    return nested


def _required_text(value: Mapping[str, object], key: str) -> str:
    text = value.get(key)
    if not isinstance(text, str) or not text.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return text.strip()


def _integer(value: Mapping[str, object], key: str) -> int:
    number = value.get(key)
    if isinstance(number, bool) or not isinstance(number, int) or number < 0:
        raise ValueError(f"{key} must be a non-negative integer")
    return number


def _number(value: Mapping[str, object], key: str, default: float) -> float:
    number = value.get(key, default)
    if isinstance(number, bool) or not isinstance(number, (int, float)):
        raise TypeError(f"{key} must be numeric")
    return float(number)


def _string_set(value: object) -> set[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("categories must be a string list")
    return {item.casefold() for item in value}


def _normalized_fixture_hash(case: Mapping[str, object]) -> str:
    normalized = {key: value for key, value in case.items() if key != "fixture_hash"}
    payload = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _opaque_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:32]


def _require_loopback_http(endpoint: str) -> None:
    parsed = urlparse(endpoint)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username
        or parsed.password
        or not parsed.port
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("trace endpoint must be credential-free loopback HTTP")


def _safe_failure_code(value: str) -> str:
    normalized = "".join(
        character if character.isalnum() or character in "._:-" else "_"
        for character in value.strip()
    )
    return normalized[:80] or "critical_failure"


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("evaluated_at must be timezone-aware")
    return value.astimezone(UTC)


def _atomic_json_write(path: Path, payload: Mapping[str, object]) -> None:
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate the checked-in synthetic ontology corpus, write a durable "
            "EvaluationSnapshot, and keep release eligibility BLOCKED/PENDING."
        )
    )
    parser.add_argument("--synthetic-only", action="store_true", required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=ROOT / "dist" / "ontology-evaluation",
    )
    parser.add_argument("--fail-on-threshold", action="store_true")
    parser.add_argument(
        "--otlp-endpoint",
        help=(
            "Optional credential-free loopback Phoenix endpoint, "
            "for example http://127.0.0.1:6006"
        ),
    )
    parser.add_argument("--trace-project", default=TRACE_PROJECT)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = evaluate_dataset(
            args.dataset,
            output_root=args.output_root,
        )
        emitted_spans = (
            emit_sanitized_lifecycle_spans(
                args.dataset,
                endpoint=args.otlp_endpoint,
                project_name=args.trace_project,
            )
            if args.otlp_endpoint
            else 0
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"passed": False, "error": str(exc)}, sort_keys=True))
        return 2
    print(
        json.dumps(
            {
                "passed": result.passed,
                "release_status": result.release_status,
                "snapshot_id": result.snapshot.snapshot_id,
                "report": str(result.report_path),
                "critical_failures": list(result.snapshot.critical_failures),
                "emitted_spans": emitted_spans,
            },
            sort_keys=True,
        )
    )
    return 1 if args.fail_on_threshold and not result.passed else 0


if __name__ == "__main__":
    sys.exit(main())
