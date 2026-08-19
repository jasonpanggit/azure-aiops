from __future__ import annotations

import json
from typing import Any


class HealthAnalyzer:
    """Computes deterministic 0-100 operational health from semantic evidence."""

    def analyze(self, context: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(context, dict):
            raise TypeError("Operational health context must be a mapping")
        sections = context.get("sections") or {}
        risk = context.get("risk") or {}
        if not isinstance(sections, dict) or not isinstance(risk, dict):
            raise TypeError("Operational health sections and risk must be mappings")
        deductions: dict[str, int] = {}
        risk_value = risk.get("score")
        if risk_value is None:
            risk_score = 0
        elif (
            isinstance(risk_value, bool)
            or not isinstance(risk_value, int)
            or not 0 <= risk_value <= 100
        ):
            raise ValueError("Operational risk score must be an integer from 0 to 100")
        else:
            risk_score = risk_value
        if risk_score:
            deductions["operational_risk"] = min(40, round(risk_score * 0.4))
        health = sections.get("resource_health") or sections.get("health") or {}
        if isinstance(health, list):
            if any(not isinstance(item, dict) for item in health):
                raise TypeError("Operational health rows must be mappings")
            statuses = {
                str(item.get("status") or "").casefold()
                for item in health
                if isinstance(item, dict)
            }
            unhealthy = any(
                status and status not in {"available", "healthy", "running"}
                for status in statuses
            )
        elif isinstance(health, dict):
            status = str(health.get("status") or "").casefold()
            unhealthy = bool(status) and status not in {
                "available",
                "healthy",
                "running",
            }
            unhealthy = unhealthy or self._count(
                health.get("unhealthy_count"), "unhealthy_count"
            ) > 0
        else:
            raise TypeError("Operational health evidence must be a mapping or list")
        if unhealthy:
            deductions["unhealthy_state"] = 25
        compliance = sections.get("compliance") or sections.get("patching") or {}
        if isinstance(compliance, list):
            if any(not isinstance(item, dict) for item in compliance):
                raise TypeError("Operational compliance rows must be mappings")
            compliance_statuses = {
                str(item.get("status") or "").casefold()
                for item in compliance
            }
        elif isinstance(compliance, dict):
            compliance_statuses = {
                str(compliance.get("status") or "").casefold()
            }
            if self._count(
                compliance.get("noncompliant_count"), "noncompliant_count"
            ) > 0:
                compliance_statuses.add("noncompliant")
        else:
            raise TypeError("Operational compliance evidence must be a mapping or list")
        if compliance_statuses & {
            "failed",
            "noncompliant",
            "non-compliant",
            "error",
        }:
            deductions["patch_noncompliance"] = 15
        security = sections.get("security_findings") or []
        if not isinstance(security, list) or any(
            not isinstance(item, dict) for item in security
        ):
            raise TypeError("Operational security findings must be a list of mappings")
        security = self._dedupe(security)
        finding_count = len(security)
        if finding_count:
            deductions["security_exposure"] = min(20, finding_count * 10)
        ownership = sections.get("ownership")
        if ownership is not None and (
            not isinstance(ownership, list)
            or any(not isinstance(item, dict) for item in ownership)
        ):
            raise TypeError("Operational ownership must be a list of mappings")
        if isinstance(ownership, list) and not ownership:
            deductions["missing_ownership"] = 10
        evidence_flags = {
            "operational_risk": (
                risk.get("evidence_available") is not False
                and risk.get("score") is not None
            ),
            "resource_health": bool(health),
            "patch_compliance": bool(compliance)
            and compliance_statuses != {""}
            and compliance_statuses != {"unknown"},
            "security_exposure": "security_findings" in sections,
            "ownership": "ownership" in sections,
        }
        unknowns = [name for name, available in evidence_flags.items() if not available]
        observed = len(evidence_flags) - len(unknowns)
        evidence_coverage = (
            "Complete" if observed == len(evidence_flags) else "Partial" if observed >= 3 else "Limited"
        )
        if evidence_coverage == "Limited":
            deductions["evidence_uncertainty"] = 40
        elif evidence_coverage == "Partial":
            deductions["evidence_uncertainty"] = 10
        score = max(0, min(100, 100 - sum(deductions.values())))
        if unknowns:
            score = min(score, 79)
        category = self.category_for(score)
        return {
            "score": score,
            "category": category,
            "deductions": deductions,
            "reasoning": (
                "Health starts at 100 and subtracts only observed semantic risk, health, patch, security, and ownership factors. "
                "Absence of a negative finding is not proof of health; consult evidence_coverage and unknowns."
            ),
            "evidence_coverage": evidence_coverage,
            "unknowns": unknowns,
            "data_sources": ["Semantic Knowledge Layer", "Fabric Ontology", "OneLake governed facts"],
        }

    @staticmethod
    def category_for(score: int) -> str:
        if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 100:
            raise ValueError("Operational health score must be an integer from 0 to 100")
        if score >= 80:
            return "Healthy"
        if score >= 60:
            return "Warning"
        if score >= 40:
            return "Degraded"
        return "Critical"

    @staticmethod
    def _count(value: Any, field_name: str) -> int:
        if value is None:
            return 0
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"Operational {field_name} must be a non-negative integer")
        return value

    @staticmethod
    def _dedupe(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        unique: dict[str, dict[str, Any]] = {}
        for row in rows:
            key = json.dumps(row, sort_keys=True, separators=(",", ":"))
            unique[key] = row
        return list(unique.values())
