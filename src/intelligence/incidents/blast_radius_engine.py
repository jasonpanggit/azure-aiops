from __future__ import annotations


class BlastRadiusEngine:
    """Builds bounded business and dependency blast-radius projections."""

    def __init__(self, *, max_items: int = 50) -> None:
        if isinstance(max_items, bool) or not isinstance(max_items, int) or max_items < 1:
            raise ValueError("Blast-radius item bound must be a positive integer")
        self.max_items = max_items

    def analyze(self, finding):
        applications = sorted(set(finding.get("impacted_applications") or []))[: self.max_items]
        services = sorted(set(finding.get("impacted_services") or []))[: self.max_items]
        business_services = sorted(set(finding.get("impacted_business_services") or []))[: self.max_items]
        owner = str(finding.get("owner") or "Unknown")
        support = str(finding.get("support_team") or "Unknown")
        dependency_tree = {
            "root": finding.get("resource"),
            "applications": applications,
            "services": services,
            "business_services": business_services,
            "upstream": (finding.get("upstream_dependencies") or [])[: self.max_items],
            "downstream": (finding.get("downstream_dependents") or [])[: self.max_items],
        }
        return {
            "applications": applications,
            "services": services,
            "business_services": business_services,
            "business_functions": (finding.get("business_functions") or [])[: self.max_items],
            "owners": [] if owner.casefold() == "unknown" else [owner],
            "support_teams": [] if support.casefold() == "unknown" else [support],
            "dependency_tree": dependency_tree,
            "application_count": len(applications),
            "service_count": len(services),
            "business_service_count": len(business_services),
        }
