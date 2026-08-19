from __future__ import annotations

from collections import defaultdict


class PredictiveFeatureEngine:
    def build(self, context, trend):
        incident_points = min(int(context["incident_count_30d"]) * 5, 20)
        patch_points = min(int(context["patch_risk_score"]) * 15 // 100 + min(int(context["patch_debt"]), 5), 20)
        lifecycle_points = min(int(context["lifecycle_risk_score"]) * 10 // 100, 10)
        drift_points = min(int(context["configuration_drift_count"]) * 3, 15)
        change_points = min(int(context["change_risk_score"]) * 10 // 100, 10)
        security_points = min(int(context["security_finding_count"]) * 4, 10)
        advisor_points = min(int(context["advisor_recommendation_count"]) * 2, 5)
        ownership_points = 10 if context["ownership_coverage"] is False else 0
        criticality_points = 10 if str(context["business_criticality"]).casefold()=="critical" else 6 if str(context["business_criticality"]).casefold()=="high" else 0
        factors={"incident_recurrence":incident_points,"patch_debt":patch_points,"lifecycle_exposure":lifecycle_points,"configuration_drift":drift_points,"change_volatility":change_points,"security_exposure":security_points,"advisor_exposure":advisor_points,"ownership_gap":ownership_points,"business_criticality":criticality_points}
        growth=min(max(int(trend.get("growth_index") or 0),0),20)
        return {"factors":factors,"base_score":min(sum(factors.values()),100),"growth_index":growth,"coverage":float(context.get("signal_coverage") or 0),"trend":trend}

    def aggregate(self, predictions, field):
        grouped=defaultdict(list)
        for item in predictions: grouped[str(item.get(field) or "Unknown")].append(item)
        rows=[]
        for name, items in grouped.items():
            max_score=max(row["forecast_30_day"]["score"] for row in items)
            known_debt=[
                row["operational_debt"]["score"]
                for row in items
                if row.get("operational_debt",{}).get("score") is not None
            ]
            debt=min(sum(known_debt)//len(known_debt),100) if known_debt else None
            rows.append({"name":name,"resource_count":len(items),"elevated_resource_count":sum(row["forecast_30_day"]["score"]>=50 for row in items),"instability_score":max_score,"operational_debt_score":debt,"forecast_level":self.level(max_score)})
        return sorted(rows,key=lambda row:(-row["instability_score"],row["name"]))

    @staticmethod
    def level(score): return "Critical" if score>=75 else "High" if score>=50 else "Moderate" if score>=25 else "Low"
