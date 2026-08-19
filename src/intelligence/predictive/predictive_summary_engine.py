from typing import ClassVar


class PredictiveSummaryEngine:
    REPORT_TYPES: ClassVar[set[str]]={"predictive_operations_summary","failure_risk_forecast","application_stability_report","business_service_risk_forecast","operational_debt_forecast","executive_predictive_brief"}
    def generate(self,report_type,*,predictions,applications,services,freshness,portfolio_summary=None,collection_metadata=None):
        normalized=report_type.strip().casefold().replace(" ","_")
        if normalized not in self.REPORT_TYPES: raise ValueError("Unsupported predictive operations report")
        elevated=[row for row in predictions if row["forecast_30_day"]["score"]>=50]
        summary=portfolio_summary or {}; total=int(summary.get("resource_count",len(predictions))); elevated_total=int(summary.get("elevated_30_day",len(elevated))); critical_total=int(summary.get("critical_90_day",sum(row['forecast_90_day']['score']>=75 for row in predictions)))
        headline=f"{total} workloads forecast; {elevated_total} elevated in 30 days; {critical_total} reach the critical operational-risk band in the 90-day scenario."
        focus={"predictive_operations_summary":predictions,"failure_risk_forecast":[{"resource":x["resource"],"forecast_30_day":x["forecast_30_day"],"forecast_60_day":x["forecast_60_day"],"forecast_90_day":x["forecast_90_day"],"failure_modes":x["predicted_failure_modes"]} for x in predictions],"application_stability_report":applications,"business_service_risk_forecast":services,"operational_debt_forecast":[{"resource":x["resource"],"application":x["application"],"operational_debt_score":x["operational_debt_score"],"trend":x["trend"]} for x in predictions],"executive_predictive_brief":{"headline":headline,"top_risks":predictions[:5],"applications":applications[:5],"business_services":services[:5]}}[normalized]
        return {"report_type":normalized,"headline":headline,"focus":focus,"portfolio_summary":{"resource_count":total,"elevated_30_day":elevated_total,"critical_90_day":critical_total},"collection_metadata":collection_metadata or {},"freshness":freshness,"read_only":True}
