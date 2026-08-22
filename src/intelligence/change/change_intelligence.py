from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import ClassVar
from urllib.parse import unquote

from opentelemetry import metrics

from ontology.entity_builder import stable_version

from .change_analyzer import ChangeAnalyzer
from .change_classifier import ChangeClassifier
from .change_context_builder import ChangeContextBuilder
from .change_correlator import ChangeCorrelator
from .change_summary_engine import ChangeSummaryEngine
from .change_trend_engine import ChangeTrendEngine
from .configuration_drift import DriftDetectionEngine
from .configuration_drift_engine import ConfigurationDriftEngine


class ChangeTelemetry:
    def __init__(self, meter=None):
        meter = meter or metrics.get_meter("hermes.change_intelligence", "0.1.0")
        self.analysis_duration = meter.create_histogram("change.analysis.duration", unit="s")
        self.drift_duration = meter.create_histogram("change.drift.duration", unit="s")
        self.risk_duration = meter.create_histogram("change.risk.duration", unit="s")
        self.incident_correlation_duration = meter.create_histogram("change.incident.correlation.duration", unit="s")
        self.report_duration = meter.create_histogram("change.report.duration", unit="s")
        self.freshness = meter.create_histogram("change.intelligence.freshness", unit="s")
        self.change_processing_duration = meter.create_histogram("change.processing.duration", unit="s")
        self.drift_detection_duration = meter.create_histogram("change.drift.detection.duration", unit="s")
        self.risk_calculation_duration = meter.create_histogram("change.risk.calculation.duration", unit="s")
        self.baseline_comparison_duration = meter.create_histogram("change.baseline.comparison.duration", unit="s")
        self.timeline_generation_duration = meter.create_histogram("change.timeline.generation.duration", unit="s")


class ChangeIntelligence:
    QUERY_NAMES: ClassVar[set[str]] = {
        "show recent changes", "show high risk changes", "show configuration drift",
        "show policy deviations", "show security baseline deviations",
        "show incident contributing changes", "show change trends", "show configuration compliance",
        "analyze changes", "show resource changes", "show policy violations",
        "show unapproved changes", "show change timeline", "explain incident changes"
    }

    def __init__(self, *, resources, resource_changes, policy_deviations, security_deviations,
                 network_changes, identity_changes, iac_changes, incidents, history, freshness,
                 max_resources=5000, max_changes=50000, max_output_items=100,
                 max_serialized_bytes=1_000_000,
                 now: Callable[[], datetime] = lambda: datetime.now(UTC),
                 clock: Callable[[], float] = time.monotonic, telemetry=None):
        for name,value in (("max_resources",max_resources),("max_changes",max_changes),("max_output_items",max_output_items),("max_serialized_bytes",max_serialized_bytes)):
            if isinstance(value,bool) or not isinstance(value,int): raise TypeError(f"{name} must be an integer")
        if max_resources < 1 or max_changes < 1 or max_output_items < 1 or max_serialized_bytes < 1024:
            raise ValueError("Change intelligence bounds must be positive")
        if sum(map(len, (resource_changes, policy_deviations, security_deviations, network_changes, identity_changes, iac_changes, incidents, history))) > max_changes:
            raise ValueError("Change intelligence evidence exceeds configured bound")
        self.now, self.clock = now, clock
        self.telemetry = telemetry or ChangeTelemetry()
        self.max_output_items = max_output_items
        self.max_serialized_bytes = max_serialized_bytes
        self.freshness = self._timestamp(freshness, "freshness")
        if datetime.fromisoformat(self.freshness) > self._now():
            raise ValueError("Change intelligence freshness cannot be in the future")
        self.context_builder = ChangeContextBuilder(resources, max_resources=max_resources)
        self.classifier = ChangeClassifier()
        self.changes = self._changes(resource_changes, "Configuration", "change_id", "changed_at")
        self.changes += self._changes(network_changes, "Network", "change_id", "changed_at")
        self.changes += self._changes(identity_changes, "Identity", "change_id", "changed_at")
        self.changes += self._changes(iac_changes, "Infrastructure as Code", "change_id", "changed_at")
        change_identities = [str(row["change_id"]).casefold() for row in self.changes]
        if len(change_identities) != len(set(change_identities)):
            raise ValueError("Duplicate change identity")
        self.policy = self._deviations(policy_deviations, "Policy")
        self.security = self._deviations(security_deviations, "Security Baseline")
        deviation_ids = [
            str(row["deviation_id"]).casefold()
            for row in [*self.policy, *self.security]
        ]
        if len(deviation_ids) != len(set(deviation_ids)):
            raise ValueError("Duplicate deviation identity")
        self.incidents = self._incidents(incidents)
        self.history = self._history(history)
        self._reject_future()
        self.analyzer = ChangeAnalyzer(
            self.context_builder, drift=DriftDetectionEngine(), correlator=ChangeCorrelator(), max_nested_items=max_output_items
        )
        self.drift_engine = ConfigurationDriftEngine()
        self.trend_engine = ChangeTrendEngine()
        self.summary_engine = ChangeSummaryEngine()

    @classmethod
    def from_snapshot(cls, **snapshot):
        return cls(**snapshot)

    @classmethod
    def from_semantic_engine(cls, semantic_engine, *, inventory, expected_configurations,
                             observed_configurations, **snapshot):
        resources = []
        for row in inventory:
            key = ChangeContextBuilder.canonical_key(row.get("resource_id"))
            name, entity_type = str(row.get("name") or ""), str(row.get("entity_type") or "Resource")
            if not key or not name:
                continue
            try:
                context = semantic_engine.get_resource_context(key, subject_type=entity_type)
            except LookupError:
                continue
            sections = context.get("sections") or {}
            classification = sections.get("operational_classification") or {}
            resources.append({
                "resource_key": key, "name": name, "entity_type": entity_type,
                "application": cls._first(sections.get("applications")),
                "business_service": cls._first(sections.get("business_services")),
                "owner": cls._first(sections.get("ownership")),
                "support_team": cls._first(sections.get("support_teams")),
                "environment": str(classification.get("environment") or "Unknown"),
                "business_criticality": str(classification.get("criticality") or "Unknown"),
                "dependency_count": len(sections.get("upstream_dependencies") or [])
                + len(sections.get("downstream_dependents") or []),
                "expected_configuration": dict(expected_configurations.get(key) or {}),
                "observed_configuration": dict(observed_configurations.get(key) or {}),
            })
        return cls(resources=resources, freshness=str(semantic_engine.freshness), **snapshot)

    def _analysis(self):
        started = self.clock()
        processing_started=self.clock(); findings = self.analyzer.analyze(self.changes, self.policy, self.security, self.incidents); processing_elapsed=self.clock()-processing_started
        self._record_telemetry("change_processing_duration",processing_elapsed); self._record_telemetry("risk_calculation_duration",processing_elapsed)
        compliance = []
        for context in self.context_builder.all():
            key = context["_resource_key"]
            drift_started=self.clock(); drift = self.drift_engine.compare(context["expected_configuration"], context["observed_configuration"]); drift_elapsed=self.clock()-drift_started
            self._record_telemetry("drift_detection_duration",drift_elapsed); self._record_telemetry("baseline_comparison_duration",drift_elapsed)
            active = {"noncompliant", "deviated", "active", "open", "failed", "error"}
            policy_count = sum(row["resource_key"] == key and str(row.get("status") or "").casefold() in active for row in self.policy)
            security_count = sum(row["resource_key"] == key and str(row.get("status") or "").casefold() in active for row in self.security)
            score = self.drift_engine.compliance_score(drift, policy_count=policy_count, security_count=security_count)
            violations=[*drift["fields"],*[row["control"] for row in self.policy+self.security if row["resource_key"]==key and str(row.get("status") or "").casefold() in active]]
            compliance.append({
                "resource": context["resource"], "application": context["application"],
                "business_service": context["business_service"],
                "subscription_alias": context["subscription_alias"],
                "configuration_compliant": None if drift["drifted"] is None else not drift["drifted"],
                "evidence_status": drift["evidence_status"], "drift_fields": drift["fields"][:self.max_output_items],
                "policy_deviation_count": policy_count, "security_deviation_count": security_count,
                "violations": violations[:self.max_output_items],
                "critical_deviation_count": sum(row["resource_key"]==key and str(row.get("severity") or "").casefold()=="critical" and str(row.get("status") or "").casefold() in active for row in self.policy+self.security),
                "compliance_score": score,
            })
        trends = self.trend_engine.calculate(self.history, now=self._now())
        application_compliance=self._aggregate_compliance(compliance,"application")
        service_compliance=self._aggregate_compliance(compliance,"business_service")
        subscription_compliance=self._aggregate_compliance(compliance,"subscription_alias")
        result = {"findings": findings, "compliance": compliance,
                  "application_compliance":application_compliance,"business_service_compliance":service_compliance,"subscription_compliance":subscription_compliance,
                  "trends": trends, "summary": {"change_count": len(findings),
                  "high_risk_change_count": sum(row["risk_score"] >= 50 for row in findings),
                  "drifted_resource_count": sum(row["configuration_compliant"] is False for row in compliance),
                  "incident_contributing_change_count": sum(row["incident_correlation"]["contribution_score"] >= 60 for row in findings)},
                  "freshness": self.freshness, "read_only": True}
        self.telemetry.analysis_duration.record(self.clock() - started)
        self.telemetry.freshness.record(max((self._now() - datetime.fromisoformat(self.freshness)).total_seconds(), 0))
        return result

    def analyze(self):
        result = self._analysis()
        collections=("findings","compliance","application_compliance","business_service_compliance","subscription_compliance")
        return self._bounded_public(
            {
                **result,
                **{name:result[name][:self.max_output_items] for name in collections},
                "collection_metadata":{name:self._metadata(result[name]) for name in collections},
            }
        )

    def internal_resource_posture(self):
        """Canonical change risk and drift posture for governed peer intelligence."""
        changes_by_id = {
            str(row["change_id"]): str(row["resource_key"]) for row in self.changes
        }
        posture = {}
        for finding in self._analysis()["findings"]:
            key = changes_by_id.get(str(finding["change"]["change_id"]), "")
            if not key:
                continue
            row = posture.setdefault(
                key, {"change_risk_score": 0, "configuration_drift_count": 0}
            )
            row["change_risk_score"] = max(
                row["change_risk_score"], int(finding["risk_score"])
            )
            row["configuration_drift_count"] = max(
                row["configuration_drift_count"],
                len(finding["configuration_drift"]["fields"]),
            )
        return posture

    def timelines(self):
        started=self.clock(); now=self._now(); result={}
        for name,hours in (("24_hour",24),("7_day",168),("30_day",720),("90_day",2160)):
            rows=[row for row in self.changes if 0<=(now-datetime.fromisoformat(row["changed_at"])).total_seconds()<=hours*3600]
            rows=sorted(rows,key=lambda row:(row["changed_at"],row["change_id"]),reverse=True)
            public=[{key:value for key,value in row.items() if key!="resource_key"} for row in rows]
            result[name]={"change_count":len(public),"changes":public[:self.max_output_items],"collection_metadata":self._metadata(public)}
        self._record_telemetry("timeline_generation_duration",self.clock()-started)
        return self._bounded_public(result)

    def explain_incident_changes(self):
        findings=self._analysis()["findings"]
        correlated=[row for row in findings if row["incident_correlation"]["incident_id"]]
        patterns=ChangeCorrelator.patterns(correlated)
        recurring=[{"pattern":"Multiple material changes preceded incidents","change_count":len(correlated)}] if len(correlated)>=2 else []
        return self._bounded_public({"changes_before_incidents":correlated[:self.max_output_items],"common_change_patterns":patterns[:self.max_output_items],"recurring_failure_causing_changes":recurring,"confirmed_cause":False,"reasoning":"Temporal and resource alignment indicate possible contribution only; causality is not confirmed.","read_only":True})

    def knowledge_projection(self):
        analysis=self._analysis(); entities=[]; relationships=[]; baseline_by_resource={}
        for context in self.context_builder.all():
            if context["expected_configuration"]:
                baseline_id="change-baseline:"+hashlib.sha256(context["_resource_key"].encode()).hexdigest()[:20]
                baseline_by_resource[context["_resource_key"]]=baseline_id
                entities.append(self._ontology_entity(baseline_id,"ConfigurationBaseline",f"Baseline for {context['resource']['name']}"))
        for finding in analysis["findings"]:
            change=finding["change"]; raw=next(row for row in self.changes if row["change_id"]==change["change_id"])
            change_id="change-event:"+hashlib.sha256(f"{raw['resource_key']}|{change['change_id']}".encode()).hexdigest()[:20]
            entities.append(self._ontology_entity(change_id,"ChangeEvent",change["change_id"]))
            if change["authorized"] is not None:
                authorization_type="AuthorizedChange" if change["authorized"] else "UnapprovedChange"
                auth_id=f"{change_id}:{authorization_type.casefold()}"
                entities.append(self._ontology_entity(auth_id,authorization_type,change["approval_reference"]))
                relationships.append(self._ontology_relationship(change_id,"classifiedAs",auth_id,"ChangeEvent",authorization_type))
            baseline_id=baseline_by_resource.get(raw["resource_key"])
            if baseline_id:
                relationships.append(self._ontology_relationship(change_id,"evaluatedAgainst",baseline_id,"ChangeEvent","ConfigurationBaseline"))
            if finding["configuration_drift"]["drifted"]:
                drift_id=f"{change_id}:drift"
                entities.append(self._ontology_entity(drift_id,"ConfigurationDrift",", ".join(finding["configuration_drift"]["fields"])))
                relationships.append(self._ontology_relationship(change_id,"resultedIn",drift_id,"ChangeEvent","ConfigurationDrift"))
        for row,entity_type in [*((item,"PolicyDeviation") for item in self.policy),*((item,"SecurityDeviation") for item in self.security)]:
            identity=f"change-deviation:{entity_type.casefold()}:"+hashlib.sha256(str(row["deviation_id"]).encode()).hexdigest()[:20]
            entities.append(self._ontology_entity(identity,entity_type,row["control"]))
        entity_count=len(entities); relationship_count=len(relationships); entities=entities[:self.max_output_items]; known={row["resource_id"] for row in entities}; relationships=[row for row in relationships if row["subject_id"] in known and row["object_id"] in known][:self.max_output_items]
        return self._bounded_public({"entities":entities,"relationships":relationships,"collection_metadata":{"entities":{"count":entity_count,"returned":len(entities),"truncated":len(entities)<entity_count},"relationships":{"count":relationship_count,"returned":len(relationships),"truncated":len(relationships)<relationship_count}},"read_only":True})

    def query(self, question: str):
        normalized = " ".join(question.strip().rstrip(".?!").casefold().split())
        if normalized not in self.QUERY_NAMES:
            raise ValueError("Unsupported change intelligence query")
        analysis = self._analysis()
        findings = analysis["findings"]
        if normalized == "show high risk changes": candidates = [x for x in findings if x["risk_score"] >= 50]
        elif normalized == "show configuration drift": candidates = [x for x in analysis["compliance"] if x["configuration_compliant"] is False]
        elif normalized in {"show policy deviations","show policy violations"}: candidates = [{key: value for key, value in row.items() if key != "resource_key"} for row in sorted(self.policy, key=lambda row: str(row.get("deviation_id") or ""))]
        elif normalized == "show security baseline deviations": candidates = [{key: value for key, value in row.items() if key != "resource_key"} for row in sorted(self.security, key=lambda row: str(row.get("deviation_id") or ""))]
        elif normalized == "show incident contributing changes": candidates=[row for row in findings if row["incident_correlation"]["contribution_score"]>=60]
        elif normalized == "explain incident changes": return self.explain_incident_changes()
        elif normalized == "show change trends": return self._bounded_public({"query":normalized,"result":analysis["trends"],"freshness":self.freshness,"read_only":True})
        elif normalized == "show configuration compliance": candidates = analysis["compliance"]
        elif normalized == "show unapproved changes": candidates=[row for row in findings if row["change"]["authorized"] is False]
        elif normalized == "show change timeline": return self._bounded_public({"query":normalized,"result":self.timelines(),"freshness":self.freshness,"read_only":True})
        else: candidates = sorted(findings, key=lambda row: (row["change"]["changed_at"], row["change"]["change_id"]), reverse=True)
        payload=candidates[:self.max_output_items]
        return self._bounded_public({"query": normalized, "result": payload,"collection_metadata":{"result":self._metadata(candidates)}, "freshness": self.freshness, "read_only": True})

    def report(self, report_type: str):
        started = self.clock(); analysis = self._analysis()
        result = self.summary_engine.generate(report_type, findings=analysis["findings"][:self.max_output_items], compliance=analysis["compliance"][:self.max_output_items], trends=analysis["trends"], freshness=self.freshness, portfolio_summary=analysis["summary"])
        self.telemetry.report_duration.record(self.clock() - started); return self._bounded_public(result)

    def _aggregate_compliance(self,rows,field):
        grouped={}
        for row in rows: grouped.setdefault(str(row.get(field) or "Unknown"),[]).append(row)
        result=[]
        for name,items in grouped.items():
            known=[item["compliance_score"] for item in items if item["compliance_score"] is not None]
            result.append({"name":name,"resource_count":len(items),"compliance_score":sum(known)//len(known) if known else None,"drift_count":sum(len(item["drift_fields"]) for item in items),"violations":sorted({violation for item in items for violation in item["violations"]})[:self.max_output_items],"critical_deviation_count":sum(item["critical_deviation_count"] for item in items)})
        return sorted(result,key=lambda row:(row["compliance_score"] is None,row["compliance_score"] if row["compliance_score"] is not None else 101,row["name"]))

    def _metadata(self,values):
        returned=min(len(values),self.max_output_items)
        return {"count":len(values),"returned":returned,"truncated":returned<len(values)}

    def _record_telemetry(self,name,value):
        instrument=getattr(self.telemetry,name,None)
        if instrument is not None: instrument.record(value)

    def _ontology_entity(self,identity,entity_type,name):
        timestamp=self.freshness; row={"tenant_id":"not-applicable","subscription_id":"not-applicable","resource_id":identity,"timestamp":timestamp,"change_version":"","ingestion_run_id":"change-projection","entity_type":entity_type,"name":self._safe_text(name),"resource_type":f"change/{entity_type.casefold()}","location":"","payload_json":"{}","lineage_json":"{}","semantic_metadata_json":json.dumps({"source":"Change Intelligence"},sort_keys=True),"lifecycle_status":"active","valid_from":timestamp,"retired_at":"","ontology_version":"1"}; row["change_version"]=stable_version({key:value for key,value in row.items() if key not in {"timestamp","ingestion_run_id","change_version","valid_from"}}); return row

    def _ontology_relationship(self,subject,predicate,obj,subject_type,object_type):
        timestamp=self.freshness; identity="change-rel:"+hashlib.sha256(f"{subject}|{predicate}|{obj}".encode()).hexdigest()[:20]; row={"tenant_id":"not-applicable","subscription_id":"not-applicable","resource_id":identity,"timestamp":timestamp,"change_version":"","ingestion_run_id":"change-projection","subject_id":subject,"subject_type":subject_type,"predicate":predicate,"object_id":obj,"object_type":object_type,"confidence":1.0,"source":"Change Intelligence","payload_json":"{}","lineage_json":"{}","lifecycle_status":"active","valid_from":timestamp,"retired_at":"","ontology_version":"1"}; row["change_version"]=stable_version({key:value for key,value in row.items() if key not in {"timestamp","ingestion_run_id","change_version","valid_from"}}); return row

    def _changes(self, rows, default_category, id_field, time_field):
        result=[]; identities=set()
        for source in rows:
            row=dict(source); identity=str(row.get(id_field) or "").strip(); key=ChangeContextBuilder.canonical_key(row.get("resource_key"))
            if not identity or not key: raise ValueError("Changes require identity and canonical resource_key")
            if identity.casefold() in identities: raise ValueError("Duplicate change identity")
            identities.add(identity.casefold())
            for field in ("previous_state","current_state"):
                if field in row and not isinstance(row[field],dict): raise TypeError(f"{field} must be a mapping")
            authorized=row.get("authorized")
            if authorized is not None and not isinstance(authorized,bool): raise TypeError("authorized must be boolean or null")
            category=self.classifier.classify({**row,"category":row.get("category") if default_category=="Configuration" else default_category})
            result.append({"change_id": self._safe_text(identity)[:256], "resource_key": key, "changed_at": self._timestamp(row.get(time_field), "change.changed_at"),
                           "change_type": str(row.get("change_type") or "Update")[:128], "category": category,
                           "severity": str(row.get("severity") or ("High" if default_category in {"Network", "Identity", "Infrastructure as Code"} else "Medium"))[:128],
                           "changed_by": self._safe_text(row.get("changed_by") or "Unknown")[:512], "source": self._safe_text(row.get("source") or default_category)[:256],
                           "changed_fields": sorted({self._safe_text(x)[:256] for x in row.get("changed_fields", [])})[:50], "summary": self._safe_text(row.get("summary") or "Change observed")[:512],
                           "previous_state":dict(row.get("previous_state") or {}),"current_state":dict(row.get("current_state") or {}),"authorized":authorized,"approval_reference":self._safe_text(row.get("approval_reference") or "Unknown")[:256]})
        return result

    def _deviations(self, rows, kind):
        result=[]
        for row in rows:
            key=ChangeContextBuilder.canonical_key(row.get("resource_key")); identity=str(row.get("deviation_id") or "")
            if not key or not identity: raise ValueError("Deviation requires identity and resource_key")
            result.append({"deviation_id": identity[:256], "resource_key": key, "kind": kind, "observed_at": self._timestamp(row.get("observed_at"), "deviation.observed_at"), "severity": str(row.get("severity") or "Unknown")[:128], "control": str(row.get("control") or "Unknown")[:512], "status": str(row.get("status") or "Unknown")[:128]})
        return result

    def _incidents(self, rows):
        result = []
        identities = set()
        for row in rows:
            incident_id = str(row.get("incident_id") or "").strip()
            resource_key = ChangeContextBuilder.canonical_key(row.get("resource_key"))
            if not incident_id or not resource_key:
                raise ValueError("Incidents require incident_id and resource_key")
            if incident_id.casefold() in identities:
                raise ValueError("Duplicate incident identity")
            identities.add(incident_id.casefold())
            result.append({"incident_id": self._safe_text(incident_id)[:256], "resource_key": resource_key, "started_at": self._timestamp(row.get("started_at"), "incident.started_at"), "severity": str(row.get("severity") or "Unknown")[:128], "title": self._safe_text(row.get("title") or "Unknown")[:512]})
        return result

    def _history(self, rows):
        return [{**dict(row), "resource_key": ChangeContextBuilder.canonical_key(row.get("resource_key")), "observed_at": self._timestamp(row.get("observed_at"), "history.observed_at")} for row in rows]

    def _reject_future(self):
        freshness=datetime.fromisoformat(self.freshness)
        for row, field in [*((x,"changed_at") for x in self.changes), *((x,"observed_at") for x in self.policy+self.security+self.history), *((x,"started_at") for x in self.incidents)]:
            if datetime.fromisoformat(row[field]) > freshness: raise ValueError("Change evidence exceeds snapshot freshness")

    def _now(self):
        value=self.now(); return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    @staticmethod
    def _timestamp(value, field):
        try: parsed=datetime.fromisoformat(str(value))
        except (TypeError, ValueError) as exc: raise ValueError(f"Change {field} must be ISO timestamp") from exc
        if parsed.tzinfo is None: parsed=parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC).isoformat().replace("+00:00","Z")

    @staticmethod
    def _first(value):
        return str(value[0].get("name") or "Unknown") if isinstance(value,list) and value and isinstance(value[0],dict) else "Unknown"

    @staticmethod
    def _safe_text(value):
        text = str(value or "")
        while True:
            decoded = unquote(text)
            if decoded == text:
                break
            text = decoded
        text = re.sub(r"/subscriptions/[^\s,;]+", "[REDACTED RESOURCE]", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(?:tenant|subscription|run)\s*(?:id)?\s*[:=]\s*[0-9a-f-]{16,}\b", "[REDACTED IDENTIFIER]", text, flags=re.IGNORECASE)
        text = re.sub(r"\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b", "[REDACTED IDENTIFIER]", text, flags=re.IGNORECASE)
        def redact_encoded(match):
            token = match.group(0)
            try:
                decoded = bytes.fromhex(token).decode()
                if "/subscriptions/" in decoded.casefold():
                    return "[REDACTED RESOURCE]"
            except (ValueError, UnicodeDecodeError):
                pass
            try:
                decoded = base64.b64decode(token, validate=True).decode()
                if "/subscriptions/" in decoded.casefold():
                    return "[REDACTED RESOURCE]"
            except (binascii.Error, UnicodeDecodeError, ValueError):
                pass
            return token
        text = re.sub(
            r"(?<![A-Za-z0-9+/=])(?:[0-9a-fA-F]{32,}|[A-Za-z0-9+/]{32,}={0,2})(?![A-Za-z0-9+/=])",
            redact_encoded,
            text,
        )
        return text[:512]

    @classmethod
    def _sanitize_public(cls, value):
        if isinstance(value, dict):
            return {key: cls._sanitize_public(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [cls._sanitize_public(item) for item in value]
        if isinstance(value, str):
            return cls._safe_text(value)
        return value

    def _bounded_public(self, value):
        sanitized = self._sanitize_public(value)
        if len(json.dumps(sanitized, sort_keys=True, separators=(",", ":")).encode()) > self.max_serialized_bytes:
            raise ValueError("Change intelligence output exceeds configured bound")
        return sanitized
