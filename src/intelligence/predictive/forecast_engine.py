from __future__ import annotations


class ForecastEngine:
    def forecast(self, features, horizon_days):
        multiplier={30:0.5,60:0.75,90:1.0}[horizon_days]
        score=min(round(features["base_score"]+features["growth_index"]*multiplier),100)
        level="Critical" if score>=75 else "High" if score>=50 else "Moderate" if score>=25 else "Low"
        factors=features["factors"]; trend=features["trend"]
        incident=min(round(factors["incident_recurrence"]*5+self._positive(trend.get("incident_growth"))*10*multiplier),100)
        patch=min(round(factors["patch_debt"]*5+self._positive(trend.get("patch_debt_growth"))*4*multiplier),100)
        lifecycle=min(round(factors["lifecycle_exposure"]*10+self._positive(trend.get("lifecycle_exposure_growth"))*multiplier),100)
        drift=min(round(factors["configuration_drift"]*100/15+self._positive(trend.get("drift_growth"))*10*multiplier),100)
        compliance=min(round(max(patch,drift)*0.7+factors["change_volatility"]*3),100)
        band="4+" if incident>=75 else "2-3" if incident>=50 else "1" if incident>=25 else "0"
        return {"horizon_days":horizon_days,"score":score,"level":level,"likelihood":level,"incident_likelihood_score":incident,"estimated_incident_band":band,"patch_debt_risk_score":patch,"lifecycle_exposure_score":lifecycle,"configuration_drift_score":drift,"compliance_degradation_score":compliance,"ownership_risk_score":factors["ownership_gap"]*10,"forecast_type":"Scenario risk projection","basis":"Domain-specific current evidence plus observed growth; not a probability or guaranteed outcome."}

    @staticmethod
    def _positive(value):
        return max(int(value),0) if value is not None else 0
