from __future__ import annotations

import hashlib
import json

from ontology.entity_builder import stable_version

from .predictive_intelligence import PredictiveIntelligence


class PredictiveEngine:
    """Requested facade over the governed explainable predictive implementation."""

    def __init__(self, intelligence: PredictiveIntelligence) -> None:
        self.intelligence = intelligence
        self._last_analysis = None

    @classmethod
    def from_intelligence(cls, intelligence: PredictiveIntelligence):
        return cls(intelligence)

    @classmethod
    def from_snapshot(cls, **snapshot):
        return cls(PredictiveIntelligence.from_snapshot(**snapshot))

    def analyze(self):
        self._last_analysis = self.intelligence.analyze()
        return self._last_analysis

    def knowledge_projection(self):
        analysis = self.intelligence._analysis()
        entities = []
        relationships = []
        for prediction in analysis["predictions"]:
            prediction_id = f"prediction:{prediction['prediction_id'].casefold()}"
            entities.append(self._entity(prediction_id, "Prediction", prediction["resource"]["name"]))
            for days in (30, 60, 90):
                forecast_id = f"{prediction_id}:forecast:{days}"
                entities.append(self._entity(forecast_id, "Forecast", f"{days}-day forecast"))
                relationships.append(self._relationship(prediction_id, "hasForecast", forecast_id))
            trend_id = f"{prediction_id}:trend"
            debt_id = f"{prediction_id}:debt"
            entities.append(self._entity(trend_id, "Trend", prediction["trend"]["direction"]))
            entities.append(self._entity(debt_id, "OperationalDebt", prediction["operational_debt"]["level"]))
            relationships.append(self._relationship(prediction_id, "hasTrend", trend_id))
            relationships.append(self._relationship(prediction_id, "accumulatesDebt", debt_id))
            for index, driver in enumerate(prediction["risk_drivers"], 1):
                driver_id = f"{prediction_id}:driver:{index}"
                entities.append(self._entity(driver_id, "RiskDriver", driver))
                relationships.append(self._relationship(prediction_id, "drivenBy", driver_id))
        entity_count=len(entities); relationship_count=len(relationships)
        entities=entities[:self.intelligence.max_output_items]
        known={row["resource_id"] for row in entities}
        relationships=[row for row in relationships if row["subject_id"] in known and row["object_id"] in known][:self.intelligence.max_output_items]
        return self.intelligence._bounded(
            {"entities": entities,"relationships": relationships,"collection_metadata":{"entities":self._metadata(entity_count,len(entities)),"relationships":self._metadata(relationship_count,len(relationships))},"freshness":self.intelligence.freshness,"read_only": True}
        )

    def _entity(self,identity,entity_type,name):
        identity=identity.casefold(); timestamp=self.intelligence.freshness
        row={"tenant_id":"not-applicable","subscription_id":"not-applicable","resource_id":identity,"timestamp":timestamp,"change_version":"","ingestion_run_id":"predictive-projection","entity_type":entity_type,"name":str(name)[:512],"resource_type":f"predictive/{entity_type.casefold()}","location":"","payload_json":"{}","lineage_json":"{}","semantic_metadata_json":json.dumps({"source":"Predictive Operations Intelligence"},sort_keys=True),"lifecycle_status":"active","valid_from":timestamp,"retired_at":"","ontology_version":"1"}
        row["change_version"]=stable_version({key:value for key,value in row.items() if key not in {"timestamp","ingestion_run_id","change_version","valid_from"}})
        return row

    def _relationship(self,subject,relationship_type,object_id):
        subject=subject.casefold(); object_id=object_id.casefold(); timestamp=self.intelligence.freshness
        digest=hashlib.sha256(f"{subject}|{relationship_type}|{object_id}".encode()).hexdigest()[:20]
        row={"tenant_id":"not-applicable","subscription_id":"not-applicable","resource_id":f"prediction-rel:{digest}","timestamp":timestamp,"change_version":"","ingestion_run_id":"predictive-projection","subject_id":subject,"subject_type":"Prediction","predicate":relationship_type,"relationship_type":relationship_type,"object_id":object_id,"object_type":{"hasForecast":"Forecast","hasTrend":"Trend","accumulatesDebt":"OperationalDebt","drivenBy":"RiskDriver"}[relationship_type],"confidence":1.0,"source":"Predictive Operations Intelligence","payload_json":"{}","lineage_json":"{}","lifecycle_status":"active","valid_from":timestamp,"retired_at":"","ontology_version":"1"}
        row["change_version"]=stable_version({key:value for key,value in row.items() if key not in {"timestamp","ingestion_run_id","change_version","valid_from"}})
        return row

    @staticmethod
    def _metadata(count,returned):
        return {"count":count,"returned":returned,"truncated":returned<count}
