from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any


class PatchComplianceEngine:
    """Calculates resource and roll-up compliance from governed patch facts."""

    def resource_compliance(
        self,
        assessment: dict[str, Any] | None,
        installations: list[dict[str, Any]],
        *,
        now: datetime,
        policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        assessment_present = assessment is not None
        if assessment is not None and not isinstance(assessment, dict):
            raise TypeError("Patch assessment must be a mapping")
        if not isinstance(installations, list) or any(
            not isinstance(item, dict) for item in installations
        ):
            raise TypeError("Patch installations must be a list of mappings")
        if policy is not None and not isinstance(policy, dict):
            raise TypeError("Patch policy must be a mapping")
        assessment = assessment or {}
        succeeded = sum(
            str(item.get("status") or "").casefold() in {"succeeded", "success", "installed"}
            for item in installations
        )
        failed = sum(
            str(item.get("status") or "").casefold() in {"failed", "error"}
            for item in installations
        )
        unknown_installations = sum(
            str(item.get("status") or "").casefold()
            not in {"succeeded", "success", "installed", "failed", "error"}
            for item in installations
        )
        attempted = succeeded + failed
        success_pct = round(100 * succeeded / attempted, 2) if attempted else 0.0
        failure_pct = round(100 * failed / attempted, 2) if attempted else 0.0
        critical = self._count(
            assessment.get("missing_critical_updates"), "missing_critical_updates"
        )
        security = self._count(
            assessment.get("missing_security_updates"), "missing_security_updates"
        )
        unresolved = [
            item
            for item in installations
            if str(item.get("status") or "").casefold() in {"failed", "error"}
        ]
        dates = [self._date(item.get("published_at")) for item in unresolved]
        dates = [item for item in dates if item is not None]
        patch_age = max(((now - item).days for item in dates), default=0)
        score = 100
        score -= min(critical * 20, 40)
        score -= min(security * 10, 30)
        score -= min(failed * 10, 20)
        score -= min(max(patch_age - 30, 0) // 10 * 5, 20)
        status = str(assessment.get("status") or "unknown").casefold()
        valid_statuses = {
            "unknown",
            "pending",
            "inprogress",
            "in progress",
            "compliant",
            "succeeded",
            "success",
            "noupdatespending",
            "no updates pending",
            "failed",
            "error",
            "noncompliant",
            "non-compliant",
            "completedwithwarnings",
            "completed with warnings",
        }
        if status not in valid_statuses:
            raise ValueError("Patch assessment status is invalid")
        evidence_coverage = (
            "Missing"
            if not assessment_present
            else "Partial"
            if status
            in {"unknown", "pending", "inprogress", "in progress"}
            or unknown_installations
            else "Complete"
        )
        if evidence_coverage != "Complete":
            score = min(score, 40)
        if status in {
            "failed",
            "noncompliant",
            "non-compliant",
            "error",
            "completedwithwarnings",
            "completed with warnings",
        } and not (
            critical or security or failed
        ):
            score -= 25
        severity_order = {"critical": 4, "high": 3, "medium": 2, "low": 1}
        highest = max(
            (str(item.get("severity") or "Unknown") for item in unresolved),
            key=lambda value: severity_order.get(value.casefold(), 0),
            default="Unknown",
        )
        bounded_score = max(score, 0)
        policy = policy or {}
        minimum_score = self._count(
            policy.get("minimum_compliance_score"), "minimum_compliance_score"
        )
        if minimum_score > 100:
            raise ValueError("Patch minimum_compliance_score must not exceed 100")
        maximum_age = self._count(
            policy.get("max_patch_age_days"), "max_patch_age_days"
        )
        policy_compliant = (
            bounded_score >= minimum_score
            and (maximum_age <= 0 or patch_age <= maximum_age)
            if policy and evidence_coverage == "Complete"
            else None
        )
        return {
            "status": status,
            "evidence_coverage": evidence_coverage,
            "patch_success_percent": success_pct,
            "patch_failure_percent": failure_pct,
            "successful_update_count": succeeded,
            "attempted_update_count": attempted,
            "unknown_installation_count": unknown_installations,
            "missing_critical_updates": critical,
            "missing_security_updates": security,
            "unpatched": (
                bool(
                    critical
                    or security
                    or status
                    in {"failed", "noncompliant", "non-compliant", "error"}
                )
                if evidence_coverage == "Complete"
                else None
            ),
            "compliance_score": bounded_score,
            "patch_age_days": patch_age,
            "highest_severity": highest,
            "failed_update_count": failed,
            "failed_critical_update_count": sum(
                str(item.get("severity") or "").casefold() == "critical"
                or "critical" in str(item.get("category") or "").casefold()
                for item in unresolved
            ),
            "patch_policy": str(policy.get("name") or "Unknown"),
            "policy_compliant": policy_compliant,
            "compliance_debt": max(minimum_score - bounded_score, 0),
        }

    def rollups(self, rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        return {
            "subscriptions": self._group(rows, "subscription"),
            "applications": self._group(rows, "application"),
            "business_services": self._group(rows, "business_service"),
            "environments": self._group(rows, "environment"),
        }

    @staticmethod
    def _group(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            groups[str(row.get(key) or "Unknown")].append(row)
        result = []
        for name, items in groups.items():
            count = len(items)
            unpatched = sum(bool(item.get("unpatched")) for item in items)
            attempted = sum(int(item.get("attempted_update_count") or 0) for item in items)
            successful = sum(int(item.get("successful_update_count") or 0) for item in items)
            failed = sum(int(item.get("failed_update_count") or 0) for item in items)
            max_risk = max(int(item.get("risk_score") or 0) for item in items)
            result.append(
                {
                    "name": name,
                    "resource_count": count,
                    "unpatched_resource_count": unpatched,
                    "missing_critical_updates": sum(int(item.get("missing_critical_updates") or 0) for item in items),
                    "missing_security_updates": sum(int(item.get("missing_security_updates") or 0) for item in items),
                    "compliance_score": round(sum(int(item.get("compliance_score") or 0) for item in items) / count, 2),
                    "patch_success_percent": round(100 * successful / attempted, 2)
                    if attempted
                    else 0.0,
                    "patch_failure_percent": round(100 * failed / attempted, 2)
                    if attempted
                    else 0.0,
                    "risk_level": (
                        "Critical"
                        if max_risk >= 75
                        else "High"
                        if max_risk >= 50
                        else "Moderate"
                        if max_risk >= 25
                        else "Low"
                    ),
                }
            )
        return sorted(result, key=lambda item: (item["compliance_score"], item["name"]))

    @staticmethod
    def _date(value: Any) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value))
            return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _count(value: Any, field_name: str) -> int:
        if value is None:
            return 0
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"Patch {field_name} must be a non-negative integer")
        return value
