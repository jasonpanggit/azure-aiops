"""FinOps intelligence over observed Azure estate data.

Cost accountability without inventing numbers.

Azure Resource Graph does not carry billed cost. When the discovery pipeline
has synced Azure Cost Management actual-cost rows, this engine reports those
Azure-issued totals directly. Rather than synthesize plausible-looking spend, it
reports only what is genuinely observable:

* **Savings opportunity** comes from Azure Advisor's ``Cost`` recommendations,
  which carry a real, Azure-computed annual saving in their ``extendedProperties``.
* **Actual spend** comes from Cost Management Query API ``ActualCost`` rows.
* **Waste** comes from resources Advisor has flagged as idle/unused, plus
  deallocated compute and unattached disks visible in the inventory.
* **Attribution** maps each of those to subscription, application, business
  service, owner, and environment through the semantic layer.

Anything the platform cannot observe -- forecast, anomaly detection, and actual
spend when Cost Management is not synced -- is reported as ``unavailable`` with
a stated reason, not as zero and not as an estimate. A FinOps number a customer
cannot trace back to an Azure-issued figure is worse than no number at all.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

#: Advisor emits the annualized saving under one of these keys depending on
#: the recommendation family. Checked in order; first numeric wins.
_SAVINGS_KEYS = (
    "annualSavingsAmount",
    "savingsAmount",
    "annualSavings",
)
_CURRENCY_KEYS = ("savingsCurrency", "currency")

#: Resource states that represent paid-for-but-unused capacity.
_IDLE_POWER_STATES = frozenset({"deallocated", "stopped", "poweredoff"})

_ATTRIBUTION_DIMENSIONS = (
    "subscription",
    "application",
    "business_service",
    "owner",
    "environment",
)


def _as_float(value: Any) -> float | None:
    """Coerce an Advisor extended property to a float, or None if not numeric."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    # Advisor occasionally emits a placeholder negative or NaN; neither is a
    # defensible saving to show a customer.
    if number != number or number < 0:  # noqa: PLR0124 - NaN check
        return None
    return number


def _savings_rank(opportunity: SavingsOpportunity) -> float:
    """Order key for picking the best duplicate: quantified savings beat unquantified ones."""
    return opportunity.annual_savings if opportunity.annual_savings is not None else -1.0


def _currency_code(value: Any) -> str | None:
    """Return a normalized three-letter currency code when the source reports one."""
    code = str(value or "").strip().upper()
    return code if len(code) == 3 and code.isascii() and code.isalpha() else None


def _currency_summary(
    values: Iterable[tuple[float, str]],
) -> tuple[float | None, str, list[dict[str, Any]]]:
    """Aggregate only comparable values and retain unreported currency counts."""
    amounts: dict[str, list[float]] = {}
    unreported_count = 0
    for amount, currency in values:
        code = _currency_code(currency)
        if code is None:
            unreported_count += 1
        else:
            amounts.setdefault(code, []).append(amount)

    breakdown = [
        {
            "currency": code,
            "amount": round(sum(currency_amounts), 2),
            "count": len(currency_amounts),
        }
        for code, currency_amounts in sorted(amounts.items())
    ]
    if unreported_count:
        breakdown.append(
            {"currency": "unreported", "amount": None, "count": unreported_count}
        )

    if len(amounts) == 1 and unreported_count == 0:
        currency, currency_amounts = next(iter(amounts.items()))
        return round(sum(currency_amounts), 2), currency, breakdown
    if not amounts and not unreported_count:
        return None, "", breakdown
    if not amounts:
        return None, "unreported", breakdown
    return None, "mixed", breakdown


@dataclass(frozen=True)
class SavingsOpportunity:
    """One Advisor-issued cost recommendation, attributed to a business owner."""

    recommendation_id: str
    resource_id: str
    problem: str
    solution: str
    impact: str
    annual_savings: float | None
    currency: str
    attribution: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "recommendation_id": self.recommendation_id,
            "resource_id": self.resource_id,
            "problem": self.problem,
            "solution": self.solution,
            "impact": self.impact,
            "annual_savings": self.annual_savings,
            "currency": self.currency,
            "savings_source": "azure_advisor",
            **self.attribution,
        }


@dataclass(frozen=True)
class WasteItem:
    """A resource observed to be provisioned but not doing work."""

    resource_id: str
    resource_type: str
    reason: str
    detected_by: str
    attribution: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_id": self.resource_id,
            "resource_type": self.resource_type,
            "reason": self.reason,
            "detected_by": self.detected_by,
            **self.attribution,
        }


class FinOpsEngine:
    """Derives cost accountability signal from observed estate data.

    The engine is deliberately pure: callers hand it already-scoped rows and
    it returns already-scoped results. It performs no I/O and holds no
    credentials, so subscription isolation is enforced entirely by whoever
    selects the input rows.
    """

    def __init__(
        self,
        *,
        advisor_recommendations: Iterable[Mapping[str, Any]] = (),
        cost_actuals: Iterable[Mapping[str, Any]] = (),
        resources: Iterable[Mapping[str, Any]] = (),
    ) -> None:
        self._advisor = [dict(row) for row in advisor_recommendations]
        self._cost_actuals = [dict(row) for row in cost_actuals]
        self._resources = [dict(row) for row in resources]

    @staticmethod
    def _attribution(row: Mapping[str, Any]) -> dict[str, str]:
        """Project a row onto the business dimensions FinOps reports against."""
        # Imported lazily: scope lives in the API layer and importing it at
        # module scope would invert the dependency direction.
        from api.scope import scope_attributes

        attributes = scope_attributes(row)
        return {
            dimension: attributes[dimension]
            for dimension in _ATTRIBUTION_DIMENSIONS
            if dimension in attributes
        }

    @staticmethod
    def _extended(row: Mapping[str, Any]) -> dict[str, Any]:
        properties = row.get("properties")
        if not isinstance(properties, Mapping):
            return {}
        extended = properties.get("extendedProperties")
        return dict(extended) if isinstance(extended, Mapping) else {}

    def _is_cost_recommendation(self, row: Mapping[str, Any]) -> bool:
        return str(row.get("category") or "").strip().lower() == "cost"

    def actual_spend(self) -> dict[str, Any] | None:
        """Observed billed spend from Cost Management actual-cost rows."""
        rows = [
            row
            for row in self._cost_actuals
            if _as_float(row.get("cost")) is not None
        ]
        if not rows:
            return None
        total, currency, currency_totals = _currency_summary(
            [
                (_as_float(row.get("cost")) or 0.0, str(row.get("currency") or ""))
                for row in rows
            ]
        )
        usage_dates = sorted(str(row.get("usageDate") or row.get("usage_date") or "") for row in rows)
        return {
            "actual_spend": total,
            "actual_spend_currency": currency,
            "actual_spend_currency_totals": currency_totals,
            "actual_spend_source": "azure_cost_management",
            "actual_spend_period_start": usage_dates[0] if usage_dates else "",
            "actual_spend_period_end": usage_dates[-1] if usage_dates else "",
            "actual_spend_record_count": len(rows),
        }

    def savings_opportunities(self) -> list[SavingsOpportunity]:
        """Advisor cost recommendations, richest saving first.

        Recommendations without a numeric saving are still returned -- the
        action is real even when Azure declines to quantify it -- but with
        ``annual_savings`` left as None rather than coerced to zero, so the
        UI can distinguish "no saving" from "saving not quantified".
        """
        opportunities_by_key: dict[tuple[str, str, str, str, str], SavingsOpportunity] = {}
        for row in self._advisor:
            if not self._is_cost_recommendation(row):
                continue
            extended = self._extended(row)
            savings: float | None = None
            for key in _SAVINGS_KEYS:
                savings = _as_float(extended.get(key))
                if savings is not None:
                    break
            currency = ""
            for key in _CURRENCY_KEYS:
                if extended.get(key):
                    currency = _currency_code(extended[key]) or ""
                    break
            opportunity = SavingsOpportunity(
                recommendation_id=str(row.get("id") or ""),
                resource_id=str(row.get("targetResourceId") or ""),
                problem=str(row.get("problem") or ""),
                solution=str(row.get("solution") or ""),
                impact=str(row.get("impact") or ""),
                annual_savings=savings,
                currency=currency,
                attribution=self._attribution(row),
            )
            # Advisor can return repeated records for the same logical
            # recommendation -- e.g. a stale evaluation alongside a refreshed
            # one -- with the savings estimate drifting slightly between
            # them. These represent the same underlying opportunity, so
            # collapse them into a single row and keep the highest savings
            # figure rather than showing near-identical duplicates.
            key = (
                opportunity.resource_id,
                opportunity.problem,
                opportunity.solution,
                opportunity.impact,
                opportunity.currency,
            )
            existing = opportunities_by_key.get(key)
            if existing is None or _savings_rank(opportunity) > _savings_rank(existing):
                opportunities_by_key[key] = opportunity
        opportunities = list(opportunities_by_key.values())
        opportunities.sort(
            key=lambda item: (item.annual_savings is None, -(item.annual_savings or 0.0))
        )
        return opportunities

    def waste(self) -> list[WasteItem]:
        """Resources that are provisioned but not delivering value.

        Two independent detectors, each traceable to an observed fact rather
        than a heuristic guess:

        1. Advisor flagged the resource as idle or unused.
        2. The inventory shows compute deallocated or a disk unattached.
        """
        items: dict[str, WasteItem] = {}

        for row in self._advisor:
            if not self._is_cost_recommendation(row):
                continue
            problem = str(row.get("problem") or "").lower()
            solution = str(row.get("solution") or "").lower()
            text = f"{problem} {solution}"
            if not any(term in text for term in ("idle", "unused", "unattached", "delete")):
                continue
            resource_id = str(row.get("targetResourceId") or "")
            if not resource_id:
                continue
            items[resource_id] = WasteItem(
                resource_id=resource_id,
                resource_type="",
                reason=str(row.get("problem") or "Flagged as idle or unused"),
                detected_by="azure_advisor",
                attribution=self._attribution(row),
            )

        for row in self._resources:
            resource_id = str(row.get("id") or "")
            if not resource_id or resource_id in items:
                continue
            reason = self._inventory_waste_reason(row)
            if reason is None:
                continue
            items[resource_id] = WasteItem(
                resource_id=resource_id,
                resource_type=str(row.get("type") or row.get("resourceType") or ""),
                reason=reason,
                detected_by="resource_inventory",
                attribution=self._attribution(row),
            )

        return sorted(items.values(), key=lambda item: item.resource_id)

    @staticmethod
    def _inventory_waste_reason(row: Mapping[str, Any]) -> str | None:
        resource_type = str(row.get("type") or row.get("resourceType") or "").lower()
        properties = row.get("properties")
        properties = properties if isinstance(properties, Mapping) else {}

        if resource_type == "microsoft.compute/disks":
            state = str(properties.get("diskState") or "").lower()
            if state == "unattached":
                return "Managed disk is unattached and still incurring storage cost"
            return None

        if resource_type == "microsoft.network/publicipaddresses":
            # An unassociated public IP with a Standard SKU bills hourly.
            if not properties.get("ipConfiguration"):
                return "Public IP address is not associated with any resource"
            return None

        if resource_type in {
            "microsoft.compute/virtualmachines",
            "microsoft.hybridcompute/machines",
        }:
            for key in ("powerState", "extended", "instanceView"):
                value = properties.get(key)
                text = str(value).lower() if value is not None else ""
                if any(state in text for state in _IDLE_POWER_STATES):
                    return "Virtual machine is deallocated but retains billable resources"
            return None

        return None

    def summary(self) -> dict[str, Any]:
        """Roll savings and waste up, with explicit gaps for what is unknown."""
        opportunities = self.savings_opportunities()
        quantified = [item for item in opportunities if item.annual_savings is not None]
        total, currency, currency_totals = _currency_summary(
            [
                (item.annual_savings or 0.0, item.currency)
                for item in quantified
            ]
        )
        waste_items = self.waste()

        actual = self.actual_spend()
        unavailable = []
        if actual is None:
            unavailable.append(
                {
                    "metric": "actual_spend",
                    "reason": (
                        "No Cost Management actual-cost rows were synced for this scope. "
                        "Grant Cost Management Query access and run discovery."
                    ),
                }
            )
        elif actual["actual_spend"] is None:
            unavailable.append(
                {
                    "metric": "actual_spend",
                    "reason": (
                        "Cost Management rows report multiple or missing currencies. "
                        "Amounts remain separated; no foreign-exchange conversion is applied."
                    ),
                }
            )
        if quantified and total is None:
            unavailable.append(
                {
                    "metric": "identified_annual_savings",
                    "reason": (
                        "Advisor savings use multiple or missing currencies. "
                        "Amounts remain separated; no foreign-exchange conversion is applied."
                    ),
                }
            )
        unavailable.extend(
            [
                {
                    "metric": "realized_savings",
                    "reason": (
                        "No verified remediation-to-resource change is linked to "
                        "comparable pre-change and post-change Cost Management actuals. "
                        "Spend movement alone is not evidence of realized savings."
                    ),
                },
                {
                    "metric": "cost_forecast",
                    "reason": "Forecast requires a longer historical billed-cost baseline than discovery currently publishes.",
                },
                {
                    "metric": "cost_anomaly",
                    "reason": "Anomaly detection requires historical billed-cost trend analysis, which is not implemented yet.",
                },
            ]
        )

        summary = {
            "identified_annual_savings": total,
            "currency": currency,
            "identified_annual_savings_currency_totals": currency_totals,
            "savings_opportunity_count": len(opportunities),
            "quantified_opportunity_count": len(quantified),
            "waste_item_count": len(waste_items),
            "unavailable_metrics": unavailable,
        }
        if actual is not None:
            summary.update(actual)
        return summary

    def by_dimension(self, dimension: str) -> list[dict[str, Any]]:
        """Group identified savings and waste by a business dimension."""
        if dimension not in _ATTRIBUTION_DIMENSIONS:
            raise ValueError(f"Unsupported FinOps dimension: {dimension}")

        buckets: dict[str, dict[str, Any]] = {}

        def bucket(key: str) -> dict[str, Any]:
            return buckets.setdefault(
                key,
                {
                    dimension: key,
                    "savings_opportunity_count": 0,
                    "waste_item_count": 0,
                    "_savings": [],
                },
            )

        for opportunity in self.savings_opportunities():
            entry = bucket(opportunity.attribution.get(dimension) or "unattributed")
            entry["savings_opportunity_count"] += 1
            if opportunity.annual_savings is not None:
                entry["_savings"].append((opportunity.annual_savings, opportunity.currency))

        for item in self.waste():
            bucket(item.attribution.get(dimension) or "unattributed")["waste_item_count"] += 1

        for entry in buckets.values():
            total, currency, currency_totals = _currency_summary(entry.pop("_savings"))
            entry["identified_annual_savings"] = total
            entry["currency"] = currency
            entry["identified_annual_savings_currency_totals"] = currency_totals

        return sorted(
            buckets.values(),
            key=lambda entry: (
                entry["identified_annual_savings"] is None,
                -(entry["identified_annual_savings"] or 0.0),
                entry[dimension],
            ),
        )


__all__ = ["FinOpsEngine", "SavingsOpportunity", "WasteItem"]
