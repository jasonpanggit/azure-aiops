from __future__ import annotations

import json
from typing import Any


class ComplianceAnalyzer:
    def analyze(self, context: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(context, dict):
            raise TypeError("Operational compliance context must be a mapping")
        sections = context.get("sections") or {}
        if not isinstance(sections, dict):
            raise TypeError("Operational compliance sections must be a mapping")
        compliance = sections.get("compliance") or sections.get("patching") or {}
        patch_status = sections.get("patch_status") or {}
        if not isinstance(patch_status, dict):
            raise TypeError("Operational patch status must be a mapping")
        if isinstance(compliance, list):
            if any(not isinstance(item, dict) for item in compliance):
                raise TypeError("Operational compliance rows must be mappings")
            compliance = self._dedupe(compliance)
            statuses = {
                str(item.get("status") or "unknown").casefold()
                for item in compliance
                if isinstance(item, dict)
            }
            status = (
                "failed"
                if statuses & {"failed", "noncompliant", "non-compliant", "error"}
                else "compliant"
                if statuses and statuses <= {"compliant", "succeeded", "success"}
                else "unknown"
            )
            failed = sum(
                self._count(item.get("failed_patch_count"), "failed_patch_count")
                for item in compliance
            )
        elif isinstance(compliance, dict):
            status = str(compliance.get("status") or "unknown").casefold()
            if self._count(
                compliance.get("noncompliant_count"), "noncompliant_count"
            ) > 0:
                status = "noncompliant"
            failed = self._count(
                compliance.get("failed_patch_count")
                if compliance.get("failed_patch_count") is not None
                else patch_status.get("failed_resource_count"),
                "failed_patch_count",
            )
        else:
            raise TypeError("Operational compliance evidence must be a mapping or list")
        valid_statuses = {
            "unknown",
            "pending",
            "inprogress",
            "in progress",
            "compliant",
            "succeeded",
            "success",
            "failed",
            "noncompliant",
            "non-compliant",
            "error",
        }
        if status not in valid_statuses:
            raise ValueError("Operational compliance status is invalid")
        return {
            "status": status,
            "failed_patch_count": failed,
            "compliant": status.casefold() in {"compliant", "succeeded", "success"},
            "evidence": {"status": status, "failed_patch_count": failed},
            "data_sources": ["Semantic Knowledge Layer", "OneLake patch compliance facts"],
        }

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
