from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, ClassVar
from urllib.parse import unquote

from opentelemetry import metrics

from .incident_analyzer import IncidentAnalyzer
from .incident_context_builder import IncidentContextBuilder
from .incident_correlator import IncidentCorrelator
from .incident_pattern_engine import IncidentPatternEngine
from .incident_summary_engine import IncidentSummaryEngine


class IncidentTelemetry:
    def __init__(self, meter=None) -> None:
        meter = meter or metrics.get_meter("aiops.incident_causality", "0.1.0")
        self.analysis_duration = meter.create_histogram("incident.analysis.duration", unit="s")
        self.correlation_latency = meter.create_histogram("incident.correlation.latency", unit="s")
        self.causality_latency = meter.create_histogram("incident.causality.latency", unit="s")
        self.business_impact_latency = meter.create_histogram("incident.business_impact.latency", unit="s")
        self.pattern_latency = meter.create_histogram("incident.pattern.latency", unit="s")
        self.report_duration = meter.create_histogram("incident.report.duration", unit="s")
        self.freshness = meter.create_histogram("incident.intelligence.freshness", unit="s")
        self.timeline_generation_duration = meter.create_histogram("incident.timeline.generation.duration", unit="s")
        self.blast_radius_generation_duration = meter.create_histogram("incident.blast_radius.generation.duration", unit="s")
        self.root_cause_analysis_duration = meter.create_histogram("incident.root_cause.analysis.duration", unit="s")
        self.knowledge_retrieval_latency = meter.create_histogram("incident.knowledge.retrieval.latency", unit="s")
        self.pattern_detection_duration = meter.create_histogram("incident.pattern.detection.duration", unit="s")


class IncidentIntelligence:
    """Read-only correlation and probabilistic causality over governed evidence."""

    QUERY_NAMES: ClassVar[set[str]] = {
        "show probable root causes",
        "show incident blast radius",
        "show correlated incidents",
        "show recurring incident patterns",
        "show business impact",
    }
    MAX_PUBLIC_STRING: ClassVar[int] = 512

    def __init__(
        self,
        *,
        resources: list[dict[str, Any]],
        incidents: list[dict[str, Any]],
        alerts: list[dict[str, Any]],
        resource_changes: list[dict[str, Any]],
        patch_findings: list[dict[str, Any]],
        lifecycle_findings: list[dict[str, Any]],
        history: list[dict[str, Any]],
        freshness: str,
        max_resources: int = 5000,
        max_incidents: int = 10000,
        max_evidence_rows: int = 50000,
        correlation_lookback_hours: int = 168,
        max_evidence_per_incident: int = 100,
        max_collection_items: int = 50,
        max_output_items: int = 50,
        max_serialized_bytes: int = 1_000_000,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        clock: Callable[[], float] = time.monotonic,
        telemetry: IncidentTelemetry | None = None,
    ) -> None:
        positive_bounds = {
            "max_resources": max_resources,
            "max_incidents": max_incidents,
            "max_evidence_rows": max_evidence_rows,
            "correlation_lookback_hours": correlation_lookback_hours,
            "max_evidence_per_incident": max_evidence_per_incident,
            "max_collection_items": max_collection_items,
            "max_output_items": max_output_items,
        }
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 1
            for value in positive_bounds.values()
        ) or (
            isinstance(max_serialized_bytes, bool)
            or not isinstance(max_serialized_bytes, int)
            or max_serialized_bytes < 1024
        ):
            raise ValueError("Incident bounds must be positive")
        if len(incidents) > max_incidents:
            raise ValueError("Incident snapshot exceeds configured bound")
        if sum(map(len, (alerts, resource_changes, patch_findings, lifecycle_findings, history))) > max_evidence_rows:
            raise ValueError("Incident evidence exceeds configured bound")
        self.now = now
        self.clock = clock
        self.max_output_items = max_output_items
        self.max_serialized_bytes = max_serialized_bytes
        self.telemetry = telemetry or IncidentTelemetry()
        self.freshness = self._timestamp(freshness, "freshness")
        if datetime.fromisoformat(self.freshness) > self._current_time():
            raise ValueError("Incident freshness cannot be in the future")
        current_incidents = self._incidents(incidents)
        self.history = self._history(history)
        current_ids = {
            str(row["incident_id"]).casefold() for row in current_incidents
        }
        historical_incidents: dict[str, dict[str, Any]] = {}
        for row in self.history:
            identity = str(row["incident_id"]).casefold()
            if identity in current_ids:
                continue
            candidate = {
                "incident_id": row["incident_id"],
                "title": str(row.get("title") or "Historical incident"),
                "status": str(row.get("status") or "Unknown"),
                "severity": str(row.get("severity") or "Unknown"),
                "started_at": row["observed_at"],
                "resource_key": row["resource_key"],
            }
            previous = historical_incidents.get(identity)
            if previous is None or candidate["started_at"] < previous["started_at"]:
                historical_incidents[identity] = candidate
        self.incidents = [
            *current_incidents,
            *self._incidents(list(historical_incidents.values())),
        ]
        if len(self.incidents) > max_incidents:
            raise ValueError("Incident snapshot exceeds configured bound after history")
        self.evidence = self._evidence(alerts, resource_changes, patch_findings, lifecycle_findings)
        self._reject_future_evidence()
        self.analyzer = IncidentAnalyzer(
            IncidentContextBuilder(
                resources,
                max_resources=max_resources,
                max_collection_items=max_collection_items,
                max_string_length=self.MAX_PUBLIC_STRING,
            ),
            correlator=IncidentCorrelator(
                lookback_hours=correlation_lookback_hours,
                max_evidence_per_incident=max_evidence_per_incident,
            ),
        )
        self.pattern_engine = IncidentPatternEngine()
        self.summary_engine = IncidentSummaryEngine()

    @classmethod
    def from_snapshot(cls, **snapshot: Any) -> IncidentIntelligence:
        return cls(**snapshot)

    @classmethod
    def from_semantic_engine(
        cls,
        semantic_engine,
        *,
        inventory: list[dict[str, Any]],
        incidents: list[dict[str, Any]],
        alerts: list[dict[str, Any]],
        resource_changes: list[dict[str, Any]],
        patch_findings: list[dict[str, Any]],
        lifecycle_findings: list[dict[str, Any]],
        history: list[dict[str, Any]],
        **kwargs: Any,
    ) -> IncidentIntelligence:
        max_resources = kwargs.get("max_resources", 5000)
        if (
            isinstance(max_resources, bool)
            or not isinstance(max_resources, int)
            or max_resources < 1
        ):
            raise ValueError("Incident max_resources must be a positive integer")
        if not isinstance(inventory, list):
            raise TypeError("Incident inventory must be a list")
        if len(inventory) > max_resources:
            raise ValueError("Incident resource snapshot exceeds configured bound")
        if any(not isinstance(row, dict) for row in inventory):
            raise TypeError("Incident inventory rows must be mappings")
        semantic_clock = kwargs.get("clock", time.monotonic)
        semantic_telemetry = kwargs.get("telemetry")
        if semantic_telemetry is None:
            semantic_telemetry = IncidentTelemetry()
            kwargs["telemetry"] = semantic_telemetry
        retrieval_started = semantic_clock()
        resources = []
        advisor_alerts = []
        for row in inventory:
            resource_key = str(row.get("resource_id") or "").casefold()
            name = str(row.get("name") or "")
            entity_type = str(row.get("entity_type") or "Resource")
            if not resource_key or not name:
                continue
            try:
                context = semantic_engine.get_resource_context(resource_key, subject_type=entity_type)
                impact = semantic_engine.get_impact_context(resource_key, subject_type=entity_type)
                public = semantic_engine.indexes.public(resource_key)
            except LookupError:
                continue
            sections = context.get("sections") or {}
            classification = sections.get("operational_classification") or {}
            resources.append(
                {
                    "resource_key": resource_key,
                    "name": name,
                    "entity_type": entity_type,
                    "application": cls._first_name(sections.get("applications")),
                    "business_service": cls._first_name(sections.get("business_services")),
                    "owner": cls._first_name(sections.get("ownership")),
                    "support_team": cls._first_name(sections.get("support_teams")),
                    "environment": str(classification.get("environment") or "Unknown"),
                    "business_criticality": str(classification.get("criticality") or "Unknown"),
                    "subscription_alias": str(
                        classification.get("subscription_alias") or "Unknown"
                    ),
                    "subscription_id": str(
                        public.get("subscription_id")
                        or row.get("subscription_id")
                        or ""
                    ),
                    "subscription_connection": str(
                        public.get("subscription_connection")
                        or row.get("subscription_connection")
                        or row.get("connection_id")
                        or ""
                    ),
                    "impacted_applications": cls._names(impact.get("impacted_applications")),
                    "impacted_services": cls._names(impact.get("impacted_services")),
                    "impacted_business_services": cls._names(impact.get("impacted_business_services")),
                    "upstream_dependencies": cls._names(
                        sections.get("upstream_dependencies")
                    ),
                    "downstream_dependents": cls._names(
                        sections.get("downstream_dependents")
                    ),
                    "business_functions": cls._names(
                        sections.get("business_functions")
                    ),
                }
            )
            for index, advisor in enumerate(sections.get("advisor_findings") or [], 1):
                summary = str(
                    advisor.get("name")
                    or advisor.get("summary")
                    or "Advisor recommendation"
                )
                advisor_alerts.append(
                    {
                        "alert_id": "advisor-"
                        + hashlib.sha256(
                            f"{resource_key}|{index}|{summary}".encode()
                        ).hexdigest()[:16],
                        "title": summary,
                        "severity": str(advisor.get("severity") or "Moderate"),
                        "fired_at": str(
                            advisor.get("observed_at") or semantic_engine.freshness
                        ),
                        "resource_key": resource_key,
                        "source": "Azure Advisor",
                    }
                )
        instrument = getattr(semantic_telemetry, "knowledge_retrieval_latency", None)
        if instrument is not None:
            instrument.record(semantic_clock() - retrieval_started)
        return cls(
            resources=resources,
            incidents=incidents,
            alerts=[*alerts, *advisor_alerts],
            resource_changes=resource_changes,
            patch_findings=patch_findings,
            lifecycle_findings=lifecycle_findings,
            history=history,
            freshness=str(semantic_engine.freshness),
            **kwargs,
        )

    def analyze(self) -> dict[str, Any]:
        started = self.clock()
        correlation_started = self.clock()
        findings = self.analyzer.analyze(
            self.incidents, self.evidence, now=self._current_time()
        )
        for finding in findings:
            finding["freshness"] = self.freshness
        correlation_elapsed = self.clock() - correlation_started
        self.telemetry.correlation_latency.record(correlation_elapsed)
        self.telemetry.causality_latency.record(correlation_elapsed)
        impact_started = self.clock()
        _ = sum(item["blast_radius"]["application_count"] for item in findings)
        self.telemetry.business_impact_latency.record(self.clock() - impact_started)
        pattern_started = self.clock()
        patterns = self.pattern_engine.detect(findings)
        self.telemetry.pattern_latency.record(self.clock() - pattern_started)
        self._record_telemetry("pattern_detection_duration",self.clock()-pattern_started)
        result = {
            "findings": findings[: self.max_output_items],
            "patterns": patterns,
            "summary": {
                "incident_count": len(findings),
                "incidents_with_probable_causes": sum(bool(item["probable_causes"]) for item in findings),
                "business_services_exposed": len({service for item in findings for service in item["impacted_business_services"]}),
                "recurring_pattern_count": len(patterns),
            },
            "freshness": self.freshness,
            "read_only": True,
        }
        self.telemetry.analysis_duration.record(self.clock() - started)
        self.telemetry.freshness.record(
            max((self._current_time() - datetime.fromisoformat(self.freshness)).total_seconds(), 0)
        )
        return self._bounded_public(result)

    def _analyze_findings(self) -> list[dict[str, Any]]:
        findings = self.analyzer.analyze(
            self.incidents, self.evidence, now=self._current_time()
        )
        for finding in findings:
            finding["freshness"] = self.freshness
        return findings

    def internal_resource_posture(self) -> dict[str, dict[str, Any]]:
        """Canonical incident recurrence counts for governed peer intelligence."""
        now = self._current_time()
        posture: dict[str, dict[str, Any]] = {}
        for incident in self.incidents:
            key = str(incident.get("resource_key") or "").casefold()
            started = datetime.fromisoformat(str(incident.get("started_at") or ""))
            row = posture.setdefault(
                key, {"incident_count_30d": 0, "incident_count_90d": 0}
            )
            age_days = (now - started).total_seconds() / 86400
            if 0 <= age_days <= 90:
                row["incident_count_90d"] += 1
            if 0 <= age_days <= 30:
                row["incident_count_30d"] += 1
        return posture

    def query(self, question: str) -> dict[str, Any]:
        normalized = " ".join(question.strip().rstrip(".?!").casefold().split())
        if normalized not in self.QUERY_NAMES:
            raise ValueError("Unsupported incident intelligence query")
        analysis = self.analyze()
        if normalized == "show probable root causes":
            payload: Any = [
                {"incident": item["incident"], "probable_causes": item["probable_causes"]}
                for item in analysis["findings"]
            ]
        elif normalized == "show incident blast radius":
            payload = [
                {
                    "incident": item["incident"],
                    "blast_radius": item["blast_radius"],
                    "applications": item["impacted_applications"],
                    "business_services": item["impacted_business_services"],
                }
                for item in analysis["findings"]
            ]
        elif normalized == "show recurring incident patterns":
            payload = analysis["patterns"]
        elif normalized == "show business impact":
            payload = [
                {
                    "incident": item["incident"],
                    "application": item["application"],
                    "business_service": item["business_service"],
                    "owner": item["owner"],
                    "support_team": item["support_team"],
                }
                for item in analysis["findings"]
            ]
        else:
            payload = analysis["findings"]
        return self._bounded_public({
            "query": normalized,
            "result": payload,
            "freshness": self.freshness,
            "read_only": True,
        })

    def report(self, report_type: str) -> dict[str, Any]:
        started = self.clock()
        analysis = self.analyze()
        report = self.summary_engine.generate(
            report_type,
            findings=analysis["findings"],
            patterns=analysis["patterns"],
            freshness=self.freshness,
        )
        self.telemetry.report_duration.record(self.clock() - started)
        return self._bounded_public(report)

    def _incidents(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result = []
        identities = set()
        for source in rows:
            row = dict(source)
            incident_id = str(row.get("incident_id") or "").strip()
            resource_key = IncidentContextBuilder.canonical_key(row.get("resource_key"))
            if not incident_id or not resource_key:
                raise ValueError("Incidents require incident_id and canonical resource_key")
            if incident_id.casefold() in identities:
                raise ValueError("Duplicate incident identity")
            identities.add(incident_id.casefold())
            row["incident_id"] = self._safe_identifier(incident_id, "incident")
            row["resource_key"] = resource_key
            row["title"] = self._safe_text(row.get("title") or "Unknown")
            row["status"] = self._safe_text(row.get("status") or "Unknown")
            row["severity"] = self._safe_text(row.get("severity") or "Unknown")
            row["started_at"] = self._timestamp(row.get("started_at"), "incident.started_at")
            result.append(row)
        return result

    def _evidence(self, alerts, changes, patch, lifecycle) -> list[dict[str, Any]]:
        result = []
        identities: set[tuple[str, str]] = set()
        specs = (
            (alerts, "alert_id", "fired_at", "Alert", "title"),
            (changes, "change_id", "changed_at", "Resource Change", "summary"),
            (patch, "finding_id", "observed_at", "Patch Failure", "summary"),
            (lifecycle, "finding_id", "observed_at", "Lifecycle Risk", "summary"),
        )
        for rows, id_field, time_field, evidence_type, summary_field in specs:
            for source in rows:
                if not isinstance(source, dict):
                    raise TypeError("Incident evidence rows must be mappings")
                row = dict(source)
                key = IncidentContextBuilder.canonical_key(row.get("resource_key"))
                evidence_id = str(row.get(id_field) or "").strip()
                if not key or not evidence_id:
                    raise ValueError("Incident evidence requires identity and resource_key")
                identity = (evidence_type, evidence_id.casefold())
                if identity in identities:
                    raise ValueError("Duplicate incident evidence identity")
                identities.add(identity)
                status = str(row.get("status") or "").casefold()
                causal_eligible = evidence_type in {"Alert", "Resource Change"} or (
                    evidence_type == "Patch Failure"
                    and status in {"failed", "failure", "noncompliant", "error"}
                )
                changed_fields = row.get("changed_fields") or []
                if not isinstance(changed_fields, list) or any(
                    isinstance(field, (dict, list, tuple, set))
                    for field in changed_fields
                ):
                    raise ValueError("Incident changed_fields must be a list of scalar values")
                risk_score = row.get("risk_score")
                if risk_score is not None and (
                    isinstance(risk_score, bool)
                    or not isinstance(risk_score, int)
                    or not 0 <= risk_score <= 100
                ):
                    raise ValueError("Incident risk_score must be an integer from 0 to 100")
                result.append(
                    {
                        "evidence_id": self._safe_identifier(evidence_id, "evidence"),
                        "evidence_type": evidence_type,
                        "observed_at": self._timestamp(row.get(time_field), f"{evidence_type}.observed_at"),
                        "resource_key": key,
                        "severity": str(row.get("severity") or ("High" if evidence_type == "Resource Change" else "Moderate")),
                        "summary": self._safe_text(
                            row.get(summary_field) or row.get("status") or "Unknown"
                        ),
                        "status": self._safe_text(row.get("status") or "Unknown"),
                        "risk_score": risk_score,
                        "source": self._safe_text(row.get("source") or evidence_type),
                        "signal": self._safe_text(row.get("signal") or ""),
                        "event_type": self._safe_text(row.get("event_type") or ""),
                        "change_type": self._safe_text(row.get("change_type") or ""),
                        "changed_fields": [
                            self._safe_text(field)
                            for field in changed_fields[:50]
                        ],
                        "causal_eligible": causal_eligible,
                    }
                )
        return result

    def _history(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized = []
        identities: set[tuple[str, str]] = set()
        freshness = datetime.fromisoformat(self.freshness)
        for source in rows:
            row = dict(source)
            incident_id = str(row.get("incident_id") or "").strip()
            resource_key = IncidentContextBuilder.canonical_key(
                row.get("resource_key") or row.get("target_resource_id")
            )
            if not incident_id or not resource_key:
                raise ValueError(
                    "Incident history requires incident_id and canonical resource_key"
                )
            observed_at = self._timestamp(
                row.get("observed_at"), "history.observed_at"
            )
            if datetime.fromisoformat(observed_at) > freshness:
                raise ValueError("Incident history exceeds snapshot freshness")
            identity = (incident_id.casefold(), observed_at)
            if identity in identities:
                raise ValueError("Duplicate incident history identity")
            identities.add(identity)
            row.update(
                {
                    "incident_id": self._safe_identifier(incident_id, "incident"),
                    "resource_key": resource_key,
                    "observed_at": observed_at,
                    "title": self._safe_text(
                        row.get("title") or "Historical incident"
                    ),
                    "status": self._safe_text(row.get("status") or "Unknown"),
                    "severity": self._safe_text(row.get("severity") or "Unknown"),
                }
            )
            normalized.append(row)
        return normalized

    def _reject_future_evidence(self) -> None:
        freshness = datetime.fromisoformat(self.freshness)
        for row in [*self.incidents, *self.evidence]:
            field = "started_at" if "started_at" in row else "observed_at"
            if datetime.fromisoformat(str(row[field])) > freshness:
                raise ValueError("Incident evidence exceeds snapshot freshness")

    def _current_time(self) -> datetime:
        value = self.now()
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    @staticmethod
    def _timestamp(value: Any, field: str) -> str:
        try:
            parsed = datetime.fromisoformat(str(value))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Incident {field} must be an ISO timestamp") from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _first_name(value: Any) -> str:
        names = IncidentIntelligence._names(value)
        return names[0] if names else "Unknown"

    @staticmethod
    def _names(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return sorted(
            {
                str(item.get("name") or "")
                for item in value
                if isinstance(item, dict) and item.get("name")
            }
        )

    @staticmethod
    def _safe_identifier(value: Any, kind: str) -> str:
        text = str(value or "").strip()
        if IncidentIntelligence._contains_internal_identifier(text):
            digest = hashlib.sha256(text.casefold().encode()).hexdigest()[:12]
            return f"{kind}-{digest}"
        return IncidentIntelligence._safe_text(text)

    @staticmethod
    def _safe_text(value: Any) -> str:
        text = str(value or "")[:8192]
        while True:
            decoded_escapes = re.sub(
                r"\\u([0-9a-fA-F]{4})",
                lambda match: chr(int(match.group(1), 16)),
                text,
            )
            decoded_escapes = re.sub(
                r"\\x([0-9a-fA-F]{2})",
                lambda match: chr(int(match.group(1), 16)),
                decoded_escapes,
            )
            if decoded_escapes == text:
                break
            text = decoded_escapes
        while True:
            decoded = unquote(text)
            if decoded == text:
                break
            text = decoded
        text = re.sub(
            r"/subscriptions/[^\s,;]+",
            "[REDACTED RESOURCE]",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"\b(?:tenant|subscription|run)\s*(?:id)?\s*[:=]\s*[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b",
            "[REDACTED IDENTIFIER]",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"\b(?:tenant|subscription|run)[-_][A-Za-z0-9][A-Za-z0-9-]*\b",
            "[REDACTED IDENTIFIER]",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b",
            "[REDACTED IDENTIFIER]",
            text,
            flags=re.IGNORECASE,
        )
        text = IncidentIntelligence._redact_wrapped_sensitive(text)
        text = re.sub(
            r"(?i)(?<![A-Z2-7])(?:[A-Z2-7]{24,}={0,6})(?![A-Z2-7=])",
            lambda match: "[REDACTED RESOURCE]"
            if IncidentIntelligence._decoded_contains_internal_identifier(
                match.group(0)
            )
            else match.group(0),
            text,
        )
        text = re.sub(
            r"(?i)0x([0-9a-f]{32,})",
            lambda match: "[REDACTED ENCODED VALUE]"
            if IncidentIntelligence._decoded_contains_internal_identifier(
                match.group(1)
            )
            else match.group(0),
            text,
        )
        text = re.sub(
            r"(?<![A-Za-z0-9+/])(?:[0-9a-fA-F]{32,}|[A-Za-z0-9+/]{24,}={0,2})(?![A-Za-z0-9+/=])",
            lambda match: "[REDACTED RESOURCE]"
            if IncidentIntelligence._decoded_contains_internal_identifier(
                match.group(0)
            )
            else match.group(0),
            text,
        )
        if len(text) > IncidentIntelligence.MAX_PUBLIC_STRING:
            return (
                text[: IncidentIntelligence.MAX_PUBLIC_STRING - 12]
                + "…[truncated]"
            )
        return text

    @staticmethod
    def _contains_internal_identifier(value: str) -> bool:
        decoded = str(value)
        while True:
            next_value = unquote(decoded)
            if next_value == decoded:
                break
            decoded = next_value
        return IncidentIntelligence._decoded_contains_internal_identifier(decoded) or bool(
            re.search(r"/subscriptions/", decoded, flags=re.IGNORECASE)
            or re.search(
                r"\b(?:tenant|subscription|run)(?:[-_]|\s+(?:id)?\s*[:=])",
                decoded,
                flags=re.IGNORECASE,
            )
        )

    @staticmethod
    def _decoded_contains_internal_identifier(value: str) -> bool:
        pending = [value]
        seen: set[str] = set()
        while pending:
            candidate = pending.pop()
            if candidate in seen:
                continue
            seen.add(candidate)
            decoded_url = unquote(candidate)
            if (
                "/subscriptions/" in decoded_url.casefold()
                or re.search(
                    r"\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b",
                    decoded_url,
                    flags=re.IGNORECASE,
                )
                or re.search(
                    r"\b(?:tenant|subscription|run)(?:[-_]|\s+(?:id)?\s*[:=])",
                    decoded_url,
                    flags=re.IGNORECASE,
                )
            ):
                return True
            if decoded_url != candidate and decoded_url not in seen:
                pending.append(decoded_url)
            compact_hex = re.sub(r"\s+", "", candidate)
            if (
                re.fullmatch(r"[0-9a-fA-F]{32,}", compact_hex)
                and len(compact_hex) % 2 == 0
            ):
                try:
                    decoded_hex = bytes.fromhex(compact_hex).decode()
                    if decoded_hex not in seen:
                        pending.append(decoded_hex)
                except (ValueError, UnicodeDecodeError):
                    pass
            compact = re.sub(r"\s+", "", candidate)
            if re.fullmatch(r"[A-Za-z2-7]+={0,6}", compact):
                try:
                    padded_b32 = compact + "=" * (-len(compact) % 8)
                    decoded_b32 = base64.b32decode(
                        padded_b32, casefold=True
                    ).decode()
                    if decoded_b32 not in seen:
                        pending.append(decoded_b32)
                except (binascii.Error, UnicodeDecodeError, ValueError):
                    pass
            if re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", compact):
                try:
                    padded = compact + "=" * (-len(compact) % 4)
                    decoded_b64 = base64.b64decode(padded, validate=True).decode()
                    if decoded_b64 not in seen:
                        pending.append(decoded_b64)
                except (binascii.Error, UnicodeDecodeError, ValueError):
                    pass
        return False

    @staticmethod
    def _redact_wrapped_sensitive(value: str) -> str:
        pattern = re.compile(
            r"(?<![A-Za-z0-9+/=])(?:[A-Za-z0-9+/=]+\s+)+[A-Za-z0-9+/=]+(?![A-Za-z0-9+/=])"
        )

        def redact(match):
            tokens = re.findall(r"[A-Za-z0-9+/=]+", match.group(0))
            if len(tokens) > 256:
                return (
                    "[REDACTED ENCODED VALUE]"
                    if IncidentIntelligence._decoded_contains_internal_identifier(
                        "".join(tokens)
                    )
                    else match.group(0)
                )
            for start in range(len(tokens)):
                candidate = ""
                for token in tokens[start:]:
                    candidate += token
                    if len(candidate) > 4096:
                        break
                    if len(candidate) >= 24 and (
                        IncidentIntelligence._decoded_contains_internal_identifier(
                            candidate
                        )
                    ):
                        return "[REDACTED ENCODED VALUE]"
            return match.group(0)

        return pattern.sub(redact, value)

    @classmethod
    def _sanitize_public(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {key: cls._sanitize_public(item) for key, item in value.items()}
        if isinstance(value, list):
            return [cls._sanitize_public(item) for item in value]
        if isinstance(value, tuple):
            return [cls._sanitize_public(item) for item in value]
        if isinstance(value, str):
            return cls._safe_text(value)
        return value

    def _bounded_public(self, value: Any) -> Any:
        sanitized = self._bound_public_collections(self._sanitize_public(value))
        encoded = json.dumps(
            sanitized, sort_keys=True, separators=(",", ":")
        ).encode()
        if len(encoded) > self.max_serialized_bytes:
            raise ValueError("Incident intelligence output exceeds configured bound")
        return sanitized

    def _bound_public_collections(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: self._bound_public_collections(item)
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [
                self._bound_public_collections(item)
                for item in value[: self.max_output_items]
            ]
        return value

    def _record_telemetry(self,name,value):
        instrument=getattr(self.telemetry,name,None)
        if instrument is not None: instrument.record(value)
