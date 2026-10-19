"""Read-only compatibility queries for the onboarding Operations Copilot.

Identity comes exclusively from ``InventoryReadPort``. Patch assessments remain
patch-domain evidence and are joined to the identity projection by resource ID.
Failure queries use the same authorized identity join as compliance/EOL queries.
"""

from __future__ import annotations

from typing import Any

from api.scope import Scope
from onboarding.inventory_read_adapter import InventoryReadAdapter


class ContextQueryService:
    SUPPORTED = (
        "show me all vms",
        "show me non-compliant servers",
        "show servers approaching os eol",
        "show patch failures",
    )

    def __init__(
        self,
        output_dir: str | None = None,
        *,
        inventory_adapter: InventoryReadAdapter | None = None,
        inventory_port: Any | None = None,
        scope: Scope | None = None,
        patch_reader: Any | None = None,
    ) -> None:
        if inventory_adapter is None:
            if inventory_port is not None:
                inventory_adapter = InventoryReadAdapter(inventory_port, output_dir)
            elif output_dir is not None:
                inventory_adapter = InventoryReadAdapter.from_output_dir(output_dir)
            else:
                raise TypeError("ContextQueryService requires an InventoryReadPort")
        self._adapter = inventory_adapter
        self._scope = scope or Scope()
        self._patch_reader = patch_reader

    def answer(self, question: str) -> dict[str, Any]:
        intent = " ".join(question.lower().strip().rstrip(".?").split())
        if intent == "show me all vms":
            items = [
                _public_server(row)
                for row in self._servers()
                if row.get("source_type") != "arc"
            ]
        elif intent == "show me non-compliant servers":
            items = self._non_compliant()
        elif intent == "show servers approaching os eol":
            items = self._eol_servers()
        elif intent == "show patch failures":
            servers = self._servers_by_id()
            items = [
                _public_assessment(row)
                for row in self._patch_rows()
                if str(row.get("targetResourceId") or "").casefold() in servers
                and _failed(row)
            ]
        else:
            raise ValueError("Supported questions: " + "; ".join(self.SUPPORTED))
        return {
            "question": question,
            "count": len(items),
            "items": sorted(
                items,
                key=lambda row: (
                    row.get("name") or row.get("displayName") or row.get("id") or ""
                ),
            ),
        }

    def _servers(self) -> list[dict[str, Any]]:
        return [
            row
            for row in self._adapter.resources(self._scope)
            if row.get("family") == "os"
        ]

    def _servers_by_id(self) -> dict[str, dict[str, Any]]:
        return {
            str(row.get("resource_id") or "").casefold(): row
            for row in self._servers()
            if row.get("resource_id")
        }

    def _patch_rows(self) -> list[dict[str, Any]]:
        if callable(self._patch_reader):
            return list(self._patch_reader() or [])
        return self._adapter.patch_assessments()

    def _non_compliant(self) -> list[dict[str, Any]]:
        servers = self._servers_by_id()
        output: list[dict[str, Any]] = []
        for assessment in self._patch_rows():
            status = str(assessment.get("status") or "").lower()
            counts = assessment.get("availablePatchCountByClassification") or {}
            if isinstance(counts, str):
                import json

                counts = json.loads(counts or "{}")
            missing = (
                sum(int(value or 0) for value in counts.values())
                if isinstance(counts, dict)
                else 0
            )
            non_compliant = any(
                term in status for term in ("noncompliant", "non-compliant", "fail", "error")
            )
            if non_compliant or missing > 0 or _has_failure_error(
                assessment.get("errorDetails")
            ):
                server = dict(
                    servers.get(str(assessment.get("targetResourceId") or "").casefold(), {})
                )
                if server:
                    server["patchStatus"] = assessment.get("status")
                    server["missingPatchCount"] = missing
                    output.append(_public_server(server))
        return _dedupe(output)

    def _eol_servers(self) -> list[dict[str, Any]]:
        servers = self._servers_by_id()
        output: list[dict[str, Any]] = []
        for recommendation in self._adapter.recommendations():
            text = f"{recommendation.get('problem', '')} {recommendation.get('solution', '')}".lower()
            if any(term in text for term in ("end of support", "end-of-support", "end of life", "eol", "retire")):
                server = dict(servers.get(str(recommendation.get("targetResourceId") or "").casefold(), {}))
                if server:
                    server["advisorProblem"] = recommendation.get("problem")
                    server["advisorSolution"] = recommendation.get("solution")
                    output.append(_public_server(server))
        return _dedupe(output)


def _failed(row: dict[str, Any]) -> bool:
    status = str(row.get("status") or "").lower()
    return any(term in status for term in ("fail", "error")) or _has_failure_error(
        row.get("errorDetails")
    )


def _has_failure_error(value: Any) -> bool:
    if not value:
        return False
    if isinstance(value, str):
        import json

        try:
            return _has_failure_error(json.loads(value or "{}"))
        except json.JSONDecodeError:
            return False
    if isinstance(value, list):
        return any(_has_failure_error(item) for item in value)
    if isinstance(value, dict):
        code = str(value.get("code") or "").lower()
        return (bool(code) and code not in {"success", "succeeded", "ok", "0"}) or _has_failure_error(
            value.get("details")
        )
    return False


def _public_server(row: dict[str, Any]) -> dict[str, Any]:
    values = {
        "id": row.get("resource_id"),
        "name": row.get("resource_name"),
        "entityType": "ArcServer" if row.get("source_type") == "arc" else "VirtualMachine",
        "resourceType": row.get("resource_type"),
        "subscriptionId": row.get("subscription_id"),
        "resourceGroup": row.get("resource_group"),
        "location": row.get("location"),
        "environment": row.get("environment"),
        "status": row.get("machine_status"),
        "osName": row.get("os_name"),
        "osVersion": row.get("os_version"),
        "patchStatus": row.get("patchStatus"),
        "missingPatchCount": row.get("missingPatchCount"),
        "advisorProblem": row.get("advisorProblem"),
        "advisorSolution": row.get("advisorSolution"),
        "lastObservedTimestamp": row.get("observed_at"),
    }
    return {key: value for key, value in values.items() if value not in (None, "")}


def _public_assessment(row: dict[str, Any]) -> dict[str, Any]:
    result = {
        key: row[key]
        for key in ("id", "name", "targetResourceId", "status", "lastModifiedDateTime", "lastObservedTimestamp")
        if key in row and row[key] not in (None, "")
    }
    errors = row.get("errorDetails") or {}
    if isinstance(errors, dict):
        if errors.get("code"):
            result["errorCode"] = errors["code"]
        if errors.get("message"):
            result["errorMessage"] = errors["message"]
    return result


def _dedupe(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return list({str(row.get("id")): row for row in rows}.values())
