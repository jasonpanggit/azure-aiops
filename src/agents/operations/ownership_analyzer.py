from __future__ import annotations

from typing import Any


class OwnershipAnalyzer:
    def analyze(self, context: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(context, dict):
            raise TypeError("Operational ownership context must be a mapping")
        sections = context.get("sections") or {}
        if not isinstance(sections, dict):
            raise TypeError("Operational ownership sections must be a mapping")
        evidence_available = "ownership" in sections
        collections = {
            "ownership": sections.get("ownership") or [],
            "support_teams": sections.get("support_teams") or [],
            "business_services": sections.get("business_services") or [],
        }
        for name, rows in collections.items():
            if not isinstance(rows, list) or any(
                not isinstance(item, dict) for item in rows
            ):
                raise TypeError(f"Operational {name} must be a list of mappings")
        owners = list(collections["ownership"])
        support = list(collections["support_teams"])
        business_services = list(collections["business_services"])
        escalation = support or owners
        return {
            "owners": owners,
            "support_groups": support,
            "business_services": business_services,
            "coverage": (
                "Covered" if owners else "Missing" if evidence_available else "Unknown"
            ),
            "evidence_available": evidence_available,
            "escalation_path": escalation,
            "evidence": {
                "owner_count": len(owners),
                "support_group_count": len(support),
            },
            "data_sources": ["Semantic Knowledge Layer", "Fabric Ontology relationships"],
        }
