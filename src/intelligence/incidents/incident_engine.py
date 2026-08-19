from __future__ import annotations

from .blast_radius_engine import BlastRadiusEngine
from .causality_graph import CausalityGraph
from .event_timeline import EventTimelineEngine
from .incident_summary import IncidentSummary
from .operational_patterns import OperationalPatterns
from .root_cause_engine import RootCauseEngine


class IncidentEngine:
    """Requested operational reasoning facade over verified incident intelligence."""

    def __init__(self, intelligence) -> None:
        self.intelligence = intelligence
        self.timeline = EventTimelineEngine()
        self.root_causes = RootCauseEngine(max_items=intelligence.max_output_items)
        self.projection_root_causes = RootCauseEngine(
            max_items=intelligence.analyzer.correlator.max_evidence
        )
        self.blast_radius = BlastRadiusEngine(max_items=intelligence.max_output_items)
        self.patterns = OperationalPatterns(max_patterns=50)
        self.summaries = IncidentSummary(max_items=intelligence.max_output_items)
        self._last_analysis = None

    @classmethod
    def from_intelligence(cls, intelligence):
        return cls(intelligence)

    @classmethod
    def from_snapshot(cls, **snapshot):
        from intelligence.incident.incident_intelligence import IncidentIntelligence

        return cls(IncidentIntelligence.from_snapshot(**snapshot))

    def analyze(self):
        all_findings = self.intelligence._analyze_findings()
        findings = []
        projection_findings = []
        all_events = self._all_events()
        limit = self.intelligence.max_output_items
        for finding in all_findings:
            raw_incident = next(
                row
                for row in self.intelligence.incidents
                if row["incident_id"] == finding["incident"]["incident_id"]
            )
            correlated = self.intelligence.analyzer.correlator.correlate(
                raw_incident, self.intelligence.evidence
            )
            timeline_started=self.intelligence.clock()
            related_internal = self._events_from_evidence(correlated)
            related = [
                self._public_event(event)
                for event in related_internal[-limit:]
            ]
            incident_event = [
                self._public_event(event)
                for event in self.timeline.normalize(incidents=[raw_incident])
            ]
            timeline = sorted(
                [*related[-max(limit - 1, 0):], *incident_event],
                key=lambda event: (event["timestamp"], event["event_id"]),
            )[-limit:]
            self._record(
                "timeline_generation_duration",
                self.intelligence.clock() - timeline_started,
            )
            root_started = self.intelligence.clock()
            root = self.root_causes.analyze(finding, timeline)
            projection_related = [
                self._public_event(event) for event in related_internal
            ]
            projection_timeline = sorted(
                [*projection_related, *incident_event],
                key=lambda event: (event["timestamp"], event["event_id"]),
            )
            projection_root = self.projection_root_causes.analyze(
                finding, projection_timeline
            )
            self._record(
                "root_cause_analysis_duration",
                self.intelligence.clock() - root_started,
            )
            blast_started = self.intelligence.clock()
            blast = self.blast_radius.analyze(finding)
            self._record(
                "blast_radius_generation_duration",
                self.intelligence.clock() - blast_started,
            )
            patch_rows = [row for row in correlated if row["evidence_type"] == "Patch Failure"]
            lifecycle_rows = [row for row in correlated if row["evidence_type"] == "Lifecycle Risk"]
            patch_score = max(
                [100 if str(row.get("status") or "").casefold() in {"failed", "failure", "noncompliant", "error"} else 0 for row in patch_rows],
                default=None,
            )
            lifecycle_score = max(
                [
                    row["risk_score"]
                    for row in lifecycle_rows
                    if row.get("risk_score") is not None
                ],
                default=None,
            )
            enriched = {
                **finding,
                "_resource_key": raw_incident["resource_key"],
                "probable_causes": root["probable_causes"],
                "contributing_factors": root["contributing_factors"],
                "related_events": related,
                "timeline": timeline,
                "event_chains": self.timeline.chain(
                    timeline, incident_at=finding["incident"]["started_at"]
                ),
                "root_cause_analysis": root,
                "reasoning_chain": root["reasoning_chain"],
                "blast_radius": blast,
                "dependency_chain": blast["dependency_tree"],
                "business_impact": {
                    "applications": blast["applications"],
                    "services": blast["services"],
                    "business_services": blast["business_services"],
                    "owners": blast["owners"],
                    "support_teams": blast["support_teams"],
                    "risk_score": finding.get("risk_score"),
                    "patch_score": patch_score,
                    "lifecycle_score": lifecycle_score,
                },
            }
            findings.append(enriched)
            projection_findings.append(
                {
                    "incident": finding["incident"],
                    "related_events": projection_related,
                    "root_cause_analysis": projection_root,
                }
            )
        pattern_started = self.intelligence.clock()
        patterns = self.patterns.detect(all_events, findings)
        self._record(
            "pattern_detection_duration",
            self.intelligence.clock() - pattern_started,
        )
        public_findings = [
            {key: value for key, value in finding.items() if not key.startswith("_")}
            for finding in findings
        ]
        summary = {
            "incident_count": len(findings),
            "incidents_with_probable_causes": sum(
                bool(item["probable_causes"]) for item in findings
            ),
            "business_services_exposed": len(
                {
                    service
                    for item in findings
                    for service in item["impacted_business_services"]
                }
            ),
            "recurring_pattern_count": len(patterns),
        }
        result = {
            "findings": public_findings[:limit],
            "operational_patterns": patterns[:limit],
            "summaries": self.summaries.audiences(public_findings, patterns),
            "summary": summary,
            "freshness": self.intelligence.freshness,
            "read_only": True,
        }
        self._projection_analysis = {
            "findings": projection_findings,
            "operational_patterns": patterns,
        }
        self._all_public_findings = public_findings
        self._last_analysis = self.intelligence._bounded_public(result)
        return self._last_analysis

    def incident(self, incident_id):
        if self._last_analysis is None:
            self.analyze()
        matches = [
            finding
            for finding in self._all_public_findings
            if finding["incident"]["incident_id"].casefold()
            == str(incident_id).casefold()
        ]
        if not matches:
            raise ValueError("Incident is not present in governed context")
        return self.intelligence._bounded_public(
            {"finding": matches[0], "read_only": True, "freshness": self.intelligence.freshness}
        )

    def knowledge_projection(self):
        if self._last_analysis is None:
            self.analyze()
        analysis = self._projection_analysis
        projection = CausalityGraph(
            freshness=self.intelligence.freshness,
            max_output_items=self.intelligence.max_output_items,
        ).build(analysis)
        return self.intelligence._bounded_public(projection)

    def report(self):
        analysis = self._last_analysis or self.analyze()
        return self.intelligence._bounded_public(
            {
                "report_type": "incident_operational_reasoning_report",
                "audience_summaries": analysis["summaries"],
                "incidents": [
                    {
                        "incident": finding["incident"],
                        "root_cause_analysis": finding["root_cause_analysis"],
                        "blast_radius": finding["blast_radius"],
                        "timeline": finding["timeline"],
                        "business_impact": finding["business_impact"],
                    }
                    for finding in analysis["findings"]
                ],
                "operational_patterns": analysis["operational_patterns"],
                "freshness": self.intelligence.freshness,
                "read_only": True,
            }
        )

    def _all_events(self):
        return self.timeline.normalize(
            incidents=self.intelligence.incidents,
            alerts=[row for row in self.intelligence.evidence if row["evidence_type"] == "Alert"],
            changes=[row for row in self.intelligence.evidence if row["evidence_type"] == "Resource Change"],
            patch=[row for row in self.intelligence.evidence if row["evidence_type"] == "Patch Failure"],
            lifecycle=[row for row in self.intelligence.evidence if row["evidence_type"] == "Lifecycle Risk"],
        )

    def _events_from_evidence(self, evidence):
        return self.timeline.normalize(
            alerts=[row for row in evidence if row["evidence_type"] == "Alert"],
            changes=[row for row in evidence if row["evidence_type"] == "Resource Change"],
            patch=[row for row in evidence if row["evidence_type"] == "Patch Failure"],
            lifecycle=[row for row in evidence if row["evidence_type"] == "Lifecycle Risk"],
        )

    def _record(self,name,value):
        instrument=getattr(self.intelligence.telemetry,name,None)
        if instrument is not None: instrument.record(value)

    @staticmethod
    def _public_event(event):
        return {key: value for key, value in event.items() if not key.startswith("_")}
