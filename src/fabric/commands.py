from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any


class FabricCommandService:
    SUPPORTED = (
        "Sync Azure inventory to OneLake",
        "Refresh inventory lakehouse",
        "Show ingestion status",
        "Show last Fabric sync",
        "Validate inventory data",
        "Sync operational ontology",
        "Show ontology health",
        "Publish governed remediation catalog",
    )

    def __init__(self, sync_service) -> None:
        self.sync_service = sync_service

    def execute(self, command: str, *, replay_source_run_id: str = "") -> dict[str, Any]:
        normalized = " ".join(command.strip().rstrip(".?!").casefold().split())
        if normalized in {
            "sync azure inventory to onelake",
            "refresh inventory lakehouse",
            "sync operational ontology",
        }:
            result = self.sync_service.sync(replay_source_run_id=replay_source_run_id)
            return asdict(result) if is_dataclass(result) else dict(result)
        if normalized == "show ingestion status":
            rows = self.sync_service.status()
            latest = max(rows, key=lambda row: str(row.get("timestamp") or ""), default={})
            return {"runs": len(rows), "latest": latest}
        if normalized == "show last fabric sync":
            rows = [row for row in self.sync_service.status() if row.get("status") == "completed"]
            return max(rows, key=lambda row: str(row.get("timestamp") or ""), default={})
        if normalized == "validate inventory data":
            reports = [report.to_dict() for report in self.sync_service.validate_current()]
            return {
                "passed": all(report.get("passed") for report in reports),
                "reports": reports,
            }
        if normalized == "show ontology health":
            return self.sync_service.ontology_health()
        if normalized == "publish governed remediation catalog":
            from fabric.remediation_catalog import publish_governed_catalog

            return publish_governed_catalog(
                onelake=self.sync_service.onelake,
                delta=self.sync_service.delta,
            ).to_dict()
        raise ValueError("Supported commands: " + "; ".join(self.SUPPORTED))
