from __future__ import annotations

from datetime import datetime


class PredictiveTrendEngine:
    def calculate(self, resource_key, history):
        rows=sorted([row for row in history if row["resource_key"]==resource_key and row.get("_evidence_present")],key=lambda row:(row["observed_at"],row.get("observation_id",""),int(row.get("risk_score") or 0)))
        if len(rows)<2:
            return {"observation_count":len(rows),"history_span_days":0,"patch_debt_growth":None,"lifecycle_exposure_growth":None,"incident_growth":None,"drift_growth":None,"ownership_coverage_growth":None,"security_debt_growth":None,"risk_growth":None,"growth_index":None,"direction":"Unknown"}
        first,last=rows[0],rows[-1]
        values={"patch_debt_growth":self._delta(first,last,"patch_debt"),"lifecycle_exposure_growth":self._delta(first,last,"lifecycle_risk_score"),"incident_growth":self._delta(first,last,"incident_count_30d"),"drift_growth":self._delta(first,last,"configuration_drift_count"),"ownership_coverage_growth":self._delta(first,last,"ownership_coverage_score"),"security_debt_growth":self._delta(first,last,"security_debt_score"),"risk_growth":self._delta(first,last,"risk_score")}
        degrading = [
            values[field]
            for field in (
                "patch_debt_growth",
                "lifecycle_exposure_growth",
                "incident_growth",
                "drift_growth",
                "security_debt_growth",
                "risk_growth",
            )
        ]
        if values["ownership_coverage_growth"] is not None:
            degrading.append(-values["ownership_coverage_growth"])
        known_degrading=[value for value in degrading if value is not None]
        growth=min(sum(max(value,0) for value in known_degrading)//4,20)
        improving = any(value < 0 for value in known_degrading)
        direction="Degrading" if growth>0 else "Improving" if improving else "Stable"
        span=max((datetime.fromisoformat(last["observed_at"])-datetime.fromisoformat(first["observed_at"])).total_seconds()/86400,0)
        return {"observation_count":len(rows),"history_span_days":round(span,2),**values,"growth_index":growth,"direction":direction}

    @staticmethod
    def _delta(first,last,field):
        if field not in first or field not in last or first[field] is None or last[field] is None:
            return None
        return int(last[field])-int(first[field])
