from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from incident_scenario import incident_engine

from fabric.config import FabricRuntimeConfig
from intelligence.incident.incident_context_builder import IncidentContextBuilder
from intelligence.incident.incident_intelligence import IncidentIntelligence
from intelligence.incidents.causality_graph import CausalityGraph
from intelligence.incidents.event_timeline import EventTimelineEngine
from intelligence.incidents.incident_engine import IncidentEngine
from intelligence.incidents.operational_patterns import OperationalPatterns


def _scenario():
    return json.loads(Path("tests/fixtures/sample_incident_causality.json").read_text())


@pytest.mark.parametrize(
    "bound",
    [
        "max_incidents",
        "max_evidence_rows",
        "max_resources",
        "correlation_lookback_hours",
        "max_evidence_per_incident",
        "max_collection_items",
        "max_output_items",
    ],
)
def test_direct_incident_bounds_reject_boolean_values(bound):
    with pytest.raises(ValueError):
        incident_engine(**{bound: True})


def test_event_timeline_and_graph_reject_invalid_bounds():
    with pytest.raises(ValueError):
        EventTimelineEngine(max_events=True)
    with pytest.raises(ValueError):
        CausalityGraph(freshness="2026-08-18T13:00:00Z", max_output_items=0)
    with pytest.raises(ValueError):
        OperationalPatterns(max_patterns=-1)


def test_malformed_changed_fields_and_risk_scores_fail_closed():
    scenario = _scenario()
    scenario["resource_changes"][0]["changed_fields"] = "owner"
    with pytest.raises(ValueError):
        IncidentIntelligence.from_snapshot(
            **scenario,
            now=lambda: datetime(2026, 8, 18, 13, tzinfo=UTC),
        )

    scenario = _scenario()
    scenario["lifecycle_findings"][0]["risk_score"] = True
    with pytest.raises(ValueError):
        IncidentIntelligence.from_snapshot(
            **scenario,
            now=lambda: datetime(2026, 8, 18, 13, tzinfo=UTC),
        )


def test_unknown_patch_and_lifecycle_scores_remain_unknown():
    engine = incident_engine()
    engine.evidence = [
        row
        for row in engine.evidence
        if row["evidence_type"] not in {"Patch Failure", "Lifecycle Risk"}
    ]
    finding = IncidentEngine.from_intelligence(engine).analyze()["findings"][0]

    assert finding["business_impact"]["patch_score"] is None
    assert finding["business_impact"]["lifecycle_score"] is None


def test_encoded_resource_identifiers_do_not_escape_new_incident_outputs():
    scenario = _scenario()
    internal = scenario["resources"][0]["resource_key"]
    encoded = base64.b64encode(internal.encode()).decode()
    scenario["alerts"][0]["title"] = f"signal {encoded}"
    engine = IncidentIntelligence.from_snapshot(
        **scenario,
        now=lambda: datetime(2026, 8, 18, 13, tzinfo=UTC),
    )

    output = json.dumps(IncidentEngine.from_intelligence(engine).analyze()).casefold()
    assert encoded.casefold() not in output
    assert "/subscriptions/" not in output


def test_mime_wrapped_encoded_resource_identifier_is_redacted():
    internal = _scenario()["resources"][0]["resource_key"]
    encoded = base64.b64encode(internal.encode()).decode()
    wrapped = " ".join(encoded[index : index + 8] for index in range(0, len(encoded), 8))

    assert encoded.casefold() not in IncidentIntelligence._safe_text(wrapped).replace(" ", "").casefold()


def test_whitespace_wrapped_hex_resource_identifier_is_redacted():
    internal = _scenario()["resources"][0]["resource_key"]
    encoded = internal.encode().hex()
    wrapped = " ".join(encoded[index : index + 16] for index in range(0, len(encoded), 16))

    assert encoded.casefold() not in IncidentIntelligence._safe_text(wrapped).replace(" ", "").casefold()


def test_history_cannot_expand_incidents_beyond_bound():
    scenario = _scenario()
    scenario["history"] = [
        {
            "incident_id": "INC-HISTORICAL",
            "observed_at": "2026-08-01T12:00:00Z",
            "resource_key": scenario["resources"][0]["resource_key"],
        }
    ]

    with pytest.raises(ValueError, match="bound"):
        IncidentIntelligence.from_snapshot(
            **scenario,
            max_incidents=2,
            now=lambda: datetime(2026, 8, 18, 13, tzinfo=UTC),
        )


def test_nested_v2_collections_obey_public_item_bound():
    scenario = _scenario()
    template = scenario["alerts"][0]
    scenario["alerts"] = [
        {
            **template,
            "alert_id": f"ALT-{index}",
            "fired_at": f"2026-08-18T11:{index:02d}:00Z",
        }
        for index in range(10)
    ]
    engine = IncidentIntelligence.from_snapshot(
        **scenario,
        max_output_items=2,
        now=lambda: datetime(2026, 8, 18, 13, tzinfo=UTC),
    )
    finding = IncidentEngine.from_intelligence(engine).analyze()["findings"][0]

    assert len(finding["related_events"]) <= 2
    assert len(finding["timeline"]) <= 2
    assert len(finding["probable_causes"]) <= 2
    assert len(finding["contributing_factors"]) <= 2
    assert len(finding["root_cause_analysis"]["evidence"]) <= 2
    assert len(finding["root_cause_analysis"]["reasoning_chain"]) <= 2
    assert len(
        IncidentEngine.from_intelligence(engine).analyze()["summaries"]["engineer"]["detail"]
    ) <= 2


def test_all_public_nested_collections_obey_item_bound():
    output = IncidentEngine.from_intelligence(
        incident_engine(max_output_items=1)
    ).analyze()

    def assert_bounded(value):
        if isinstance(value, dict):
            for child in value.values():
                assert_bounded(child)
        elif isinstance(value, list):
            assert len(value) <= 1
            for child in value:
                assert_bounded(child)

    assert_bounded(output)


def test_audience_summary_business_services_obey_item_bound():
    engine = incident_engine(max_output_items=2)
    key = engine.incidents[0]["resource_key"]
    context = engine.analyzer.context_builder.get(key)
    context["impacted_business_services"] = [f"Service {index}" for index in range(8)]
    engine.analyzer.context_builder._resources[key] = context

    summary = IncidentEngine.from_intelligence(engine).analyze()["summaries"]["cio"]
    assert len(summary["evidence"][0]["business_services"]) <= 2


def test_v2_summary_counts_all_findings_before_output_truncation():
    result = IncidentEngine.from_intelligence(
        incident_engine(max_output_items=1)
    ).analyze()

    assert len(result["findings"]) == 1
    assert result["summaries"]["cio"]["evidence"][0]["incident_count"] == 2


def test_incident_scope_lookup_occurs_before_public_truncation():
    engine = IncidentEngine.from_intelligence(incident_engine(max_output_items=1))
    engine.analyze()

    result = engine.incident("INC-090")
    assert result["finding"]["incident"]["incident_id"] == "INC-090"


def test_ontology_counts_are_independent_of_public_output_limit():
    full = IncidentEngine.from_intelligence(incident_engine()).knowledge_projection()
    limited = IncidentEngine.from_intelligence(
        incident_engine(max_output_items=1)
    ).knowledge_projection()

    assert limited["collection_metadata"]["entities"]["count"] == full[
        "collection_metadata"
    ]["entities"]["count"]
    assert limited["collection_metadata"]["entities"]["truncated"] is True


def test_event_classification_preserves_unknown_without_inventing_degradation_or_eol():
    events = EventTimelineEngine().normalize(
        alerts=[
            {
                "alert_id": "audit",
                "fired_at": "2026-08-18T10:00:00Z",
                "source": "Defender policy audit",
            }
        ],
        lifecycle=[
            {
                "finding_id": "supported",
                "observed_at": "2026-08-18T09:00:00Z",
                "status": "Supported",
            }
        ],
    )

    assert [event["event_type"] for event in events] == ["Lifecycle Status", "Alert"]


def test_explicit_service_degradation_type_survives_end_to_end_normalization():
    scenario = _scenario()
    scenario["alerts"][0].pop("signal", None)
    scenario["alerts"][0]["event_type"] = "Service Degradation"
    engine = IncidentIntelligence.from_snapshot(
        **scenario,
        now=lambda: datetime(2026, 8, 18, 13, tzinfo=UTC),
    )
    finding = IncidentEngine.from_intelligence(engine).analyze()["findings"][0]

    assert any(
        event["event_id"] == "ALT-100"
        and event["event_type"] == "Service Degradation"
        for event in finding["related_events"]
    )


def test_recurring_risk_requires_same_resource_and_distinct_incidents():
    findings = [
        {
            "incident": {"incident_id": "I-1"},
            "_resource_key": "resource-1",
            "owner": "Team",
        },
        {
            "incident": {"incident_id": "I-2"},
            "_resource_key": "resource-2",
            "owner": "Team",
        },
    ]
    patterns = OperationalPatterns().detect([], findings)
    assert all(row["pattern_type"] != "Recurring Risk" for row in patterns)

    findings[1]["_resource_key"] = "resource-1"
    patterns = OperationalPatterns().detect([], findings)
    assert any(row["pattern_type"] == "Recurring Risk" for row in patterns)


def test_missing_lifecycle_risk_score_remains_unknown_and_context_risk_is_preserved():
    engine = incident_engine()
    engine.evidence = [
        {**row, "risk_score": None}
        if row["evidence_type"] == "Lifecycle Risk"
        else row
        for row in engine.evidence
    ]
    context = engine.analyzer.context_builder.get(engine.incidents[0]["resource_key"])
    context["risk_score"] = 7
    engine.analyzer.context_builder._resources[engine.incidents[0]["resource_key"]] = context
    finding = IncidentEngine.from_intelligence(engine).analyze()["findings"][0]

    assert finding["business_impact"]["lifecycle_score"] is None
    assert finding["business_impact"]["risk_score"] == 7


def test_timeline_rejects_malformed_timestamp_and_canonicalizes_encoded_aliases():
    with pytest.raises(ValueError, match="timestamp"):
        EventTimelineEngine().normalize(
            alerts=[{"alert_id": "bad", "fired_at": "not-a-time"}]
        )

    literal = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm"
    encoded = literal.replace("/", "%2F")
    assert (
        IncidentContextBuilder.canonical_key(literal)
        == IncidentContextBuilder.canonical_key(encoded)
    )


class _Recorder:
    def __init__(self):
        self.values = []

    def record(self, value):
        self.values.append(value)


def test_v2_pattern_duration_measures_v2_pattern_detection():
    recorder = _Recorder()
    telemetry = SimpleNamespace(
        **{
            name: _Recorder()
            for name in (
                "analysis_duration",
                "correlation_latency",
                "causality_latency",
                "business_impact_latency",
                "pattern_latency",
                "report_duration",
                "freshness",
                "timeline_generation_duration",
                "blast_radius_generation_duration",
                "root_cause_analysis_duration",
                "knowledge_retrieval_latency",
            )
        },
        pattern_detection_duration=recorder,
    )
    IncidentEngine.from_intelligence(incident_engine(telemetry=telemetry)).analyze()

    assert len(recorder.values) == 1
    assert telemetry.pattern_latency.values == []


def test_post_incident_events_never_become_probable_causes():
    scenario = _scenario()
    scenario["alerts"][0]["fired_at"] = "2026-08-18T12:30:00Z"
    engine = IncidentIntelligence.from_snapshot(
        **scenario,
        now=lambda: datetime(2026, 8, 18, 13, tzinfo=UTC),
    )
    finding = IncidentEngine.from_intelligence(engine).analyze()["findings"][0]

    assert all(
        cause["evidence_id"] != "ALT-100"
        for cause in finding["root_cause_analysis"]["probable_causes"]
    )
    assert finding["root_cause_analysis"]["confirmed_cause"] is False


@pytest.mark.parametrize(
    "incident_config",
    [
        "true",
        "{enabled: 'yes'}",
        "{lookback_hours: true}",
        "{max_incidents: 1.5}",
        "{max_evidence_rows: 0}",
    ],
)
def test_incident_runtime_configuration_fails_closed(tmp_path, incident_config):
    path = tmp_path / "fabric.yaml"
    path.write_text(
        "fabric:\n"
        "  auth: {mode: managed_identity}\n"
        "  workspace_name: Operations\n"
        "  lakehouse_name: Inventory\n"
        "  source_data_root: ./source\n"
        f"  incident_causality: {incident_config}\n"
    )

    with pytest.raises((TypeError, ValueError)):
        FabricRuntimeConfig.load(path)


@pytest.mark.parametrize("encoding", ["base64", "mime_base64", "hex", "wrapped_hex"])
def test_encoded_guid_is_redacted(encoding):
    guid = "12345678-1234-1234-1234-123456789abc"
    if encoding in {"base64", "mime_base64"}:
        encoded = base64.b64encode(guid.encode()).decode()
        value = encoded if encoding == "base64" else " ".join(
            encoded[index : index + 8] for index in range(0, len(encoded), 8)
        )
    else:
        encoded = guid.encode().hex()
        value = encoded if encoding == "hex" else " ".join(
            encoded[index : index + 16] for index in range(0, len(encoded), 16)
        )
    assert encoded.casefold() not in IncidentIntelligence._safe_text(value).replace(
        " ", ""
    ).casefold()


@pytest.mark.parametrize(
    "encoding,split_at", [("base64", 24), ("hex", 36), ("base64", 1), ("hex", 1)]
)
def test_two_chunk_encoded_guid_is_redacted(encoding, split_at):
    guid = "12345678-1234-1234-1234-123456789abc"
    encoded = (
        base64.b64encode(guid.encode()).decode()
        if encoding == "base64"
        else guid.encode().hex()
    )
    wrapped = f"{encoded[:split_at]} {encoded[split_at:]}"

    for value in (wrapped, f"signal {wrapped} observed"):
        assert encoded.casefold() not in IncidentIntelligence._safe_text(value).replace(
            " ", ""
        ).casefold()


@pytest.mark.parametrize("separator", ["\u00a0", "\f", "\v"])
def test_unicode_and_less_common_whitespace_wrapped_guid_is_redacted(separator):
    guid = "12345678-1234-1234-1234-123456789abc"
    encoded = base64.b64encode(guid.encode()).decode()
    wrapped = f"{encoded[:24]}{separator}{encoded[24:]}"

    assert encoded.casefold() not in IncidentIntelligence._safe_text(wrapped).replace(
        separator, ""
    ).casefold()


def test_semantic_inventory_bound_is_checked_before_enrichment():
    class CountingSemantic:
        freshness = "2026-08-18T13:00:00Z"

        def __init__(self):
            self.calls = 0

        def get_resource_context(self, *_args, **_kwargs):
            self.calls += 1
            return {"sections": {}}

        def get_impact_context(self, *_args, **_kwargs):
            self.calls += 1
            return {}

    semantic = CountingSemantic()
    inventory = [
        {"resource_id": f"resource-{index}", "name": f"Resource {index}"}
        for index in range(2)
    ]
    with pytest.raises(ValueError, match="bound"):
        IncidentIntelligence.from_semantic_engine(
            semantic,
            inventory=inventory,
            incidents=[],
            alerts=[],
            resource_changes=[],
            patch_findings=[],
            lifecycle_findings=[],
            history=[],
            max_resources=1,
        )
    assert semantic.calls == 0


@pytest.mark.parametrize(
    "malformed",
    [
        "Payments",
        {"Payments": True},
        {"Payments"},
        [frozenset({"Payments"})],
        [range(2)],
    ],
)
def test_malformed_context_collections_fail_closed(malformed):
    with pytest.raises(TypeError, match="collection"):
        IncidentContextBuilder(
            [
                {
                    "resource_key": "resource-1",
                    "name": "Resource",
                    "impacted_applications": malformed,
                }
            ]
        )


def test_ontology_entity_ids_are_stable_when_earlier_evidence_is_inserted():
    base_finding = {
        "incident": {"incident_id": "INC-1", "title": "Outage"},
        "related_events": [
            {"event_id": "PATCH-1", "event_type": "Patch Failure"}
        ],
        "root_cause_analysis": {
            "probable_causes": [
                {
                    "evidence_id": "PATCH-1",
                    "evidence_type": "Patch Failure",
                    "summary": "Patch failed",
                }
            ]
        },
    }
    expanded_finding = json.loads(json.dumps(base_finding))
    expanded_finding["related_events"].insert(
        0, {"event_id": "ALERT-0", "event_type": "Alert"}
    )
    base = {
        "findings": [base_finding],
        "operational_patterns": [
            {"pattern_type": "Repeated Patch Failure", "evidence": ["two events"]}
        ],
    }
    expanded = {
        "findings": [expanded_finding],
        "operational_patterns": [
            {"pattern_type": "Ownership Gap", "evidence": ["two gaps"]},
            *base["operational_patterns"],
        ],
    }
    graph = CausalityGraph(
        freshness="2026-08-18T13:00:00Z", max_output_items=50
    )
    before = {
        (row["entity_type"], row["name"]): row["resource_id"]
        for row in graph.build(base)["entities"]
    }
    after = {
        (row["entity_type"], row["name"]): row["resource_id"]
        for row in graph.build(expanded)["entities"]
    }
    for identity in (
        ("OperationalEvent", "Patch Failure"),
        ("RootCause", "Patch failed"),
        ("RiskPattern", "Repeated Patch Failure"),
    ):
        assert before[identity] == after[identity]
