from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import ClassVar

from opentelemetry import metrics

from intelligence.incident.incident_intelligence import IncidentIntelligence

from .failure_prediction import FailurePredictionEngine
from .forecast_engine import ForecastEngine
from .operational_debt_engine import OperationalDebtEngine
from .predictive_context_builder import PredictiveContextBuilder
from .predictive_feature_engine import PredictiveFeatureEngine
from .predictive_summary_engine import PredictiveSummaryEngine
from .predictive_trend_engine import PredictiveTrendEngine
from .service_health_forecaster import ServiceHealthForecaster
from .trend_detector import TrendDetector


class PredictiveTelemetry:
    def __init__(self,meter=None):
        meter=meter or metrics.get_meter("hermes.predictive_operations","0.1.0")
        self.analysis_duration=meter.create_histogram("predictive.analysis.duration",unit="s")
        self.feature_duration=meter.create_histogram("predictive.feature.duration",unit="s")
        self.forecast_duration=meter.create_histogram("predictive.forecast.duration",unit="s")
        self.trend_duration=meter.create_histogram("predictive.trend.duration",unit="s")
        self.aggregation_duration=meter.create_histogram("predictive.aggregation.duration",unit="s")
        self.report_duration=meter.create_histogram("predictive.report.duration",unit="s")
        self.freshness=meter.create_histogram("predictive.intelligence.freshness",unit="s")
        self.prediction_latency=meter.create_histogram("predictive.prediction.latency",unit="s")
        self.risk_scoring_duration=meter.create_histogram("predictive.risk.scoring.duration",unit="s")
        self.forecast_accuracy=meter.create_histogram("predictive.forecast.accuracy",unit="1")
        self.trend_generation_duration=meter.create_histogram("predictive.trend.generation.duration",unit="s")
        self.context_assembly_duration=meter.create_histogram("predictive.context.assembly.duration",unit="s")
        self.recommendation_generation_duration=meter.create_histogram("predictive.recommendation.generation.duration",unit="s")

    def record_forecast_accuracy(self, *, predicted, observed):
        if isinstance(predicted,bool) or not isinstance(predicted,(int,float)) or not 0<=predicted<=100:
            raise ValueError("Predicted risk must be numeric from 0 to 100")
        if not (
            isinstance(observed, bool)
            or (type(observed) is int and observed in (0, 1))
        ):
            raise ValueError("Observed outcome must be binary")
        accuracy=round(1-abs(float(predicted)/100-int(bool(observed))),4)
        self.forecast_accuracy.record(accuracy)
        return accuracy


class PredictiveIntelligence:
    QUERY_NAMES: ClassVar[set[str]]={"what is likely to fail next","show unstable applications","show services accumulating debt","forecast incidents","show workloads requiring intervention","show predictive trends","predict operational risk","show high risk applications","service stability forecast","show compliance trends","show operational debt","show high risk resources","show risk drivers"}
    def __init__(self,*,resources,history,freshness,max_resources=5000,max_history_rows=50000,max_output_items=100,max_serialized_bytes=1_000_000,now:Callable[[],datetime]=lambda:datetime.now(UTC),clock:Callable[[],float]=time.monotonic,telemetry=None):
        for name,value in (("max_resources",max_resources),("max_history_rows",max_history_rows),("max_output_items",max_output_items),("max_serialized_bytes",max_serialized_bytes)):
            if isinstance(value,bool) or not isinstance(value,int): raise TypeError(f"{name} must be an integer")
        if max_history_rows<1 or max_output_items<1 or max_serialized_bytes<1024: raise ValueError("Predictive bounds must be positive")
        if len(history)>max_history_rows: raise ValueError("Predictive history exceeds configured bound")
        self.now,self.clock=now,clock; self.telemetry=telemetry or PredictiveTelemetry(); self.max_output_items=max_output_items; self.max_serialized_bytes=max_serialized_bytes
        self.freshness=self._timestamp(freshness,"freshness")
        if datetime.fromisoformat(self.freshness)>self._now(): raise ValueError("Predictive freshness cannot be in the future")
        context_started=self.clock(); self.context_builder=PredictiveContextBuilder(resources,max_resources=max_resources); self._record_telemetry("context_assembly_duration",self.clock()-context_started)
        self.history=self._history(history)
        self.feature_engine=PredictiveFeatureEngine(); self.trend_engine=PredictiveTrendEngine(); self.trend_detector=TrendDetector(); self.forecast_engine=ForecastEngine(); self.failure_engine=FailurePredictionEngine(); self.debt_engine=OperationalDebtEngine(); self.service_forecaster=ServiceHealthForecaster(); self.summary_engine=PredictiveSummaryEngine()

    @classmethod
    def from_snapshot(cls,**snapshot): return cls(**snapshot)

    @classmethod
    def from_semantic_engine(cls,semantic_engine,*,inventory,resource_signals,history,**kwargs):
        resources=[]
        for row in inventory:
            key=PredictiveContextBuilder.canonical_key(row.get("resource_id")); name=str(row.get("name") or ""); entity_type=str(row.get("entity_type") or "Resource")
            if not key or not name: continue
            context=semantic_engine.get_resource_context(key,subject_type=entity_type); sections=context.get("sections") or {}; classification=sections.get("operational_classification") or {}; signals=dict(resource_signals.get(key) or {})
            if "security_findings" in sections:
                signals.setdefault(
                    "security_finding_count", len(sections["security_findings"] or [])
                )
            if "advisor_findings" in sections:
                signals.setdefault(
                    "advisor_recommendation_count",
                    len(sections["advisor_findings"] or []),
                )
            resource={"resource_key":key,"name":name,"entity_type":entity_type,"application":cls._first(sections.get("applications")),"business_service":cls._first(sections.get("business_services")),"owner":cls._first(sections.get("ownership")),"support_team":cls._first(sections.get("support_teams")),"environment":str(classification.get("environment") or "Unknown"),"business_criticality":str(classification.get("criticality") or "Unknown"),**signals}
            if "ownership" in sections: resource["ownership_coverage"]=bool(sections["ownership"])
            resources.append(resource)
        return cls(resources=resources,history=history,freshness=str(semantic_engine.freshness),**kwargs)

    def _analysis(self):
        started=self.clock(); predictions=[]
        for context in self.context_builder.all():
            trend_started=self.clock(); trend=self.trend_detector.calculate(context["_resource_key"],self.history); trend_elapsed=self.clock()-trend_started; self.telemetry.trend_duration.record(trend_elapsed); self._record_telemetry("trend_generation_duration",trend_elapsed)
            feature_started=self.clock(); features=self.feature_engine.build(context,trend); feature_elapsed=self.clock()-feature_started; self.telemetry.feature_duration.record(feature_elapsed); self._record_telemetry("risk_scoring_duration",feature_elapsed)
            forecast_started=self.clock(); forecasts={days:self.forecast_engine.forecast(features,days) for days in (30,60,90)}; self.telemetry.forecast_duration.record(self.clock()-forecast_started)
            factors=features["factors"]; modes=[]
            mapping=(("incident_recurrence","Recurring operational incidents"),("patch_debt","Patch-related degradation"),("lifecycle_exposure","Lifecycle support exposure"),("configuration_drift","Configuration instability"),("change_volatility","Change-related instability"),("security_exposure","Security-related disruption"),("ownership_gap","Ownership and response delay"),("advisor_exposure","Advisor-reported operational exposure"))
            for factor,label in mapping:
                if factors.get(factor,0)>0: modes.append({"mode":label,"contribution":factors[factor]})
            modes=sorted(modes,key=lambda row:(-row["contribution"],row["mode"]))[:5]
            observation_count=trend["observation_count"]; span_score=min(float(trend.get("history_span_days") or 0)/90,1); has_evidence=features["coverage"]>0 or observation_count>0; coverage=min(features["coverage"]*0.5+min(observation_count,3)/3*0.2+span_score*0.2+0.05,0.95) if has_evidence else 0
            confidence=round(coverage,2); recommendation_started=self.clock(); failure=self.failure_engine.predict(context,trend,forecasts[30],confidence); debt_profile=self.debt_engine.profile(context,trend); self._record_telemetry("recommendation_generation_duration",self.clock()-recommendation_started)
            public={key:value for key,value in context.items() if not key.startswith("_") and key not in {"patch_risk_score","patch_debt","lifecycle_risk_score","incident_count_30d","incident_count_90d","change_risk_score","configuration_drift_count","security_finding_count","advisor_recommendation_count","ownership_coverage","signal_coverage"}}
            drivers=[name for name,value in factors.items() if value]
            entity_type=public["resource"]["entity_type"].casefold(); risk_models={"infrastructure_risk":forecasts[30]["score"],"vm_failure_risk":forecasts[30]["score"] if entity_type=="virtualmachine" else None,"arc_server_degradation_risk":forecasts[30]["score"] if entity_type=="arcserver" else None,"patch_compliance_degradation":forecasts[90]["compliance_degradation_score"],"service_instability":forecasts[90]["score"],"ownership_failure_risk":forecasts[90]["ownership_risk_score"],"business_service_disruption_risk":forecasts[90]["score"]}
            prediction_id="PRD-"+hashlib.sha256(context["_resource_key"].encode()).hexdigest()[:16].upper(); predictions.append({**public,"prediction_id":prediction_id,"forecast_30_day":forecasts[30],"forecast_60_day":forecasts[60],"forecast_90_day":forecasts[90],"failure_prediction":failure,"risk_models":risk_models,"predicted_failure_modes":modes,"operational_debt_score":debt_profile["score"],"operational_debt":debt_profile,"trend":trend,"observed_patterns":self.trend_detector.observed_patterns(trend),"contributors":factors,"feature_contributions":factors,"risk_drivers":drivers,"confidence":confidence,"confidence_kind":"Evidence sufficiency, not calibrated probability","evidence":[f"{name.replace('_',' ')} +{value}" for name,value in factors.items() if value] or failure["evidence"],"potential_consequences":failure["potential_consequences"],"explanation":"The workload has an elevated evidence-backed scenario forecast based on current posture and observed trend; outcomes remain uncertain." if confidence else "Insufficient governed evidence for an evidence-backed operational forecast.","prediction_status":"Evidence-backed forecast" if confidence else "Insufficient evidence","recommended_action":failure["preventive_action"],"read_only":True})
        predictions=sorted(predictions,key=lambda row:(-row["forecast_30_day"]["score"],row["resource"]["name"]))
        aggregation_started=self.clock(); applications=self.feature_engine.aggregate(predictions,"application"); services=self.feature_engine.aggregate(predictions,"business_service"); self.telemetry.aggregation_duration.record(self.clock()-aggregation_started)
        for row in applications: row.update(critical_application_exposure=row["instability_score"]>=75,potential_consequences=["Application incidents may disrupt dependent business services"] if row["instability_score"]>=50 else [])
        service_health=self.service_forecaster.forecast(predictions,"business_service"); subscriptions=self.feature_engine.aggregate(predictions,"subscription_alias"); resource_groups=self.feature_engine.aggregate(predictions,"resource_group_alias"); environments=self.feature_engine.aggregate(predictions,"environment")
        debt_scores=[row["operational_debt"]["score"] for row in predictions if row["operational_debt"]["score"] is not None]; debt_categories={name:round(sum(row["operational_debt"]["categories"][name] for row in predictions if row["operational_debt"]["categories"][name] is not None)/sum(row["operational_debt"]["categories"][name] is not None for row in predictions)) if any(row["operational_debt"]["categories"][name] is not None for row in predictions) else None for name in ("patch_debt","lifecycle_debt","ownership_debt","configuration_debt","security_debt")}
        proactive=[{"resource":row["resource"],"application":row["application"],"predicted_outcome":row["recommended_action"]["predicted_outcome"],"risk_reduction_estimate_percent":row["recommended_action"]["risk_reduction_estimate_percent"],"confidence":row["confidence"],"preventive_action":row["recommended_action"]["suggested_action"],"advisory_only":True} for row in predictions if row["forecast_30_day"]["score"]>=50]
        result={"predictions":predictions,"applications":applications,"business_services":services,"service_health_forecasts":service_health,"subscriptions":subscriptions,"resource_groups":resource_groups,"environments":environments,"operational_debt":{"portfolio_score":sum(debt_scores)//len(debt_scores) if debt_scores else None,"categories":debt_categories},"proactive_recommendations":proactive,"summary":{"resource_count":len(predictions),"elevated_30_day":sum(row["forecast_30_day"]["score"]>=50 for row in predictions),"critical_90_day":sum(row["forecast_90_day"]["score"]>=75 for row in predictions)},"freshness":self.freshness,"read_only":True}
        elapsed=self.clock()-started; self.telemetry.analysis_duration.record(elapsed); self._record_telemetry("prediction_latency",elapsed); self.telemetry.freshness.record(max((self._now()-datetime.fromisoformat(self.freshness)).total_seconds(),0)); return result

    def analyze(self):
        result=self._analysis(); collections=("predictions","applications","business_services","service_health_forecasts","subscriptions","resource_groups","environments","proactive_recommendations"); return self._bounded({**result,**{name:result[name][:self.max_output_items] for name in collections},"collection_metadata":{name:self._collection_metadata(result[name]) for name in collections}})

    def query(self,question):
        normalized=" ".join(question.strip().rstrip(".?!").casefold().split())
        if normalized not in self.QUERY_NAMES: raise ValueError("Unsupported predictive operations query")
        analysis=self._analysis(); predictions=analysis["predictions"]
        if normalized in {"what is likely to fail next","predict operational risk"}: candidates=predictions
        elif normalized in {"show unstable applications","show high risk applications"}: candidates=[row for row in analysis["applications"] if row["instability_score"]>=50]
        elif normalized=="show services accumulating debt": candidates=[row for row in analysis["business_services"] if row["operational_debt_score"] is not None and row["operational_debt_score"]>=25]
        elif normalized=="forecast incidents": candidates=[{"resource":row["resource"],"application":row["application"],"forecast_30_day":row["forecast_30_day"],"forecast_60_day":row["forecast_60_day"],"forecast_90_day":row["forecast_90_day"]} for row in predictions]
        elif normalized in {"show workloads requiring intervention","show high risk resources"}: candidates=[row for row in predictions if row["forecast_30_day"]["score"]>=50]
        elif normalized=="service stability forecast": candidates=analysis["service_health_forecasts"]
        elif normalized=="show compliance trends": candidates=[{"resource":row["resource"],"application":row["application"],"compliance_degradation_30_day":row["forecast_30_day"]["compliance_degradation_score"],"compliance_degradation_60_day":row["forecast_60_day"]["compliance_degradation_score"],"compliance_degradation_90_day":row["forecast_90_day"]["compliance_degradation_score"],"trend":row["trend"]} for row in predictions]
        elif normalized=="show operational debt": candidates=[{"resource":row["resource"],"application":row["application"],"operational_debt":row["operational_debt"]} for row in predictions]
        elif normalized=="show risk drivers": candidates=[{"resource":row["resource"],"application":row["application"],"risk_drivers":row["risk_drivers"],"contributors":row["contributors"],"evidence":row["evidence"]} for row in predictions]
        else: candidates=[{"resource":row["resource"],"trend":row["trend"]} for row in predictions]
        payload=candidates[:self.max_output_items]; return self._bounded({"query":normalized,"result":payload,"collection_metadata":{"result":self._collection_metadata(candidates)},"freshness":self.freshness,"read_only":True})

    def application_risk(self, application):
        name=str(application or "").strip()
        if not name: raise ValueError("Application name is required")
        analysis=self._analysis(); matches=[row for row in analysis["applications"] if row["name"].casefold()==name.casefold()]
        if not matches: raise ValueError("Application is not present in the governed predictive context")
        row=matches[0]
        return self._bounded({"application":row,"at_risk":row["instability_score"]>=50,"reasoning":"Application risk is the maximum evidence-backed workload forecast linked through governed context.","preventive_attention_required":row["instability_score"]>=50,"read_only":True,"freshness":self.freshness})

    def internal_planning_posture(self):
        result = {}
        for context in self.context_builder.all():
            trend = self.trend_engine.calculate(context["_resource_key"], self.history)
            features = self.feature_engine.build(context, trend)
            forecast = self.forecast_engine.forecast(features, 30)
            debt = self.debt_engine.profile(context, trend)["score"]
            result[context["_resource_key"]] = {
                "predictive_risk_score": forecast["score"],
                "operational_debt_score": debt,
            }
        return result

    def report(self,report_type):
        started=self.clock(); analysis=self._analysis(); result=self.summary_engine.generate(report_type,predictions=analysis["predictions"][:self.max_output_items],applications=analysis["applications"][:self.max_output_items],services=analysis["business_services"][:self.max_output_items],freshness=self.freshness,portfolio_summary=analysis["summary"],collection_metadata={name:self._collection_metadata(analysis[name]) for name in ("predictions","applications","business_services")}); self.telemetry.report_duration.record(self.clock()-started); return self._bounded(result)

    def _history(self,rows):
        result=[]; identities=set(); freshness=datetime.fromisoformat(self.freshness)
        numeric_fields=("patch_debt","lifecycle_risk_score","incident_count_30d","configuration_drift_count","ownership_coverage_score","security_debt_score","risk_score")
        for source in rows:
            row=dict(source); key=PredictiveContextBuilder.canonical_key(row.get("resource_key")); observed=self._timestamp(row.get("observed_at"),"history.observed_at")
            if not key: raise ValueError("Predictive history requires resource_key")
            if datetime.fromisoformat(observed)>freshness: raise ValueError("Predictive history exceeds snapshot freshness")
            identity=(key,observed)
            if identity in identities: raise ValueError("Duplicate predictive history")
            for field in numeric_fields:
                if field not in row or row[field] is None: continue
                if isinstance(row[field],bool) or not isinstance(row[field],int): raise TypeError(f"Predictive history {field} must be an integer")
                if row[field]<0: raise ValueError(f"Predictive history {field} must be nonnegative")
            evidence_present=any(field in row and row[field] is not None for field in numeric_fields)
            identities.add(identity); row.update(resource_key=key,observed_at=observed,_evidence_present=evidence_present); result.append(row)
        return result

    def _bounded(self,value):
        sanitized=IncidentIntelligence._sanitize_public(value)
        if len(json.dumps(sanitized,sort_keys=True,separators=(",",":")).encode())>self.max_serialized_bytes: raise ValueError("Predictive output exceeds configured bound")
        return sanitized

    def _record_telemetry(self,name,value):
        instrument=getattr(self.telemetry,name,None)
        if instrument is not None: instrument.record(value)

    def _collection_metadata(self, values):
        count=len(values); returned=min(count,self.max_output_items)
        return {"count":count,"returned":returned,"truncated":returned<count}

    def _now(self):
        value=self.now(); return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    @staticmethod
    def _timestamp(value,field):
        try: parsed=datetime.fromisoformat(str(value))
        except (TypeError,ValueError) as exc: raise ValueError(f"Predictive {field} must be ISO timestamp") from exc
        if parsed.tzinfo is None: parsed=parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC).isoformat().replace("+00:00","Z")
    @staticmethod
    def _first(value): return str(value[0].get("name") or "Unknown") if isinstance(value,list) and value and isinstance(value[0],dict) else "Unknown"
