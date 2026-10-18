"""Bounded server-acquired governed read projections; never model or browser evidence."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from api.scope import Scope
from operations.tools import TOOL_REGISTRY, call_tool

MAX_SOURCE_BYTES = 16 * 1024
MAX_CAPTURE_BYTES = 160 * 1024
CAPTURE_ID = r"^cap-[0-9a-f]{32}$"
ToolName = Literal[
    "business_service_context", "application_context", "risk_context", "impact_context",
    "network_topology", "firewall_nsg_gaps", "cve_exposure", "incidents",
    "remediation_plans", "cve_detail", "cve_attack_path",
]
COVERAGE = (
    "Governed read projection only. Tool lists may be bounded to 25 rows and sources may already be partial. "
    "Complete-estate coverage and cross-source atomicity are not established; no missing rows imply absence."
)


class CapturedSource(BaseModel):
    """A fixed source outcome with source provenance frozen at acquisition."""

    model_config = ConfigDict(extra="forbid", strict=True)
    tool: ToolName
    status: Literal["ok", "empty", "unavailable", "denied"]
    started_at: str
    finished_at: str
    data: JsonValue
    evidence: list[dict[str, JsonValue]] = Field(max_length=25)
    warning: str = Field(max_length=1200)
    coverage: Literal["bounded-governed-read-subset"] = "bounded-governed-read-subset"
    knowledge_version: str = Field(max_length=256)

    @model_validator(mode="after")
    def valid_capture(self):
        """Reject invalid collection clocks or retained payloads on every historical read."""
        started, finished = datetime.fromisoformat(self.started_at), datetime.fromisoformat(self.finished_at)
        if started.tzinfo is None or finished.tzinfo is None or finished < started:
            raise ValueError("Source collection timestamps are invalid")
        if self.status in {"denied", "unavailable"} and (self.data is not None or self.evidence):
            raise ValueError("Unavailable sources cannot retain decisive data or evidence")
        if len(json.dumps({"data": self.data, "evidence": self.evidence}, allow_nan=False).encode()) > MAX_SOURCE_BYTES:
            raise ValueError("Stored source exceeds its JSON/16 KiB limit")
        return self


def evidence_tools(entry_type: str, subject: str) -> list[tuple[str, dict]]:
    """Select an immutable read allowlist deterministically, never from caller tool names."""
    calls: list[tuple[str, dict]] = []
    if subject and entry_type in {"BusinessService", "Application"}:
        calls.append((
            "business_service_context" if entry_type == "BusinessService" else "application_context",
            {"name": subject},
        ))
        calls.extend([("risk_context", {"subject": subject}), ("impact_context", {"subject": subject})])
    elif subject and entry_type == "CVE":
        calls.extend([("cve_detail", {"cve_id": subject}), ("cve_attack_path", {"cve_id": subject})])
    calls.extend([
        ("network_topology", {}), ("firewall_nsg_gaps", {}),
        ("cve_exposure", {"business_service": subject} if entry_type == "BusinessService" and subject else {}),
        ("incidents", {"incident_id": subject} if entry_type == "Incident" and subject else {}),
        ("remediation_plans", {}),
    ])
    return calls


def collect_investigation_sources(
    context, scope: Scope, principal, *, entry_type: str, subject: str,
) -> list[CapturedSource]:
    """Acquire explicit current projections through the existing scoped read-tool boundary."""
    sources = []
    for name, args in evidence_tools(entry_type, subject):
        if not TOOL_REGISTRY[name].read_only:
            raise RuntimeError("Investigation evidence collection cannot invoke a mutating tool")
        started_at = datetime.now(UTC).isoformat()
        result = call_tool(name, args, context=context, scope=scope, principal=principal)
        finished_at = datetime.now(UTC).isoformat()
        status = result.status
        data = result.data if status in {"ok", "empty"} else None
        evidence = [row.to_dict() for row in result.evidence] if status in {"ok", "empty"} else []
        warning = result.warning
        version = data.get("knowledge_version") if isinstance(data, dict) else None
        version = version if isinstance(version, str) and len(version) <= 256 else "unknown"
        try:
            raw = json.dumps({"data": data, "evidence": evidence}, allow_nan=False).encode()
            if len(raw) > MAX_SOURCE_BYTES:
                raise ValueError("Projection exceeds retention bound")
        except (ValueError, TypeError, RecursionError):
            status, data, evidence, version = "unavailable", None, [], "unknown"
            warning = "Source projection could not be retained within its JSON/16 KiB bound; no data or provenance was substituted."
        if len(warning) > 1200:
            warning = warning[:1175] + " [warning truncated]"
        try:
            sources.append(CapturedSource(
                tool=name, status=status, started_at=started_at, finished_at=finished_at,
                data=data, evidence=evidence, warning=warning, knowledge_version=version,
            ))
        except ValueError as exc:
            raise RuntimeError("Governed source returned an invalid retention outcome") from exc
    return sources


def compare_investigation_sources(before: list[CapturedSource], after: list[CapturedSource]) -> list[dict]:
    """Compare paired bounded projections; unavailable evidence has no decisive data delta."""
    if [row.tool for row in before] != [row.tool for row in after]:
        raise ValueError("Retained and current projection contracts differ")
    return [
        {
            "tool": old.tool, "retained_status": old.status, "current_status": new.status,
            "data_changed": old.data != new.data
            if old.status in {"ok", "empty"} and new.status in {"ok", "empty"} else None,
            "provenance_changed": old.evidence != new.evidence,
            "retained_knowledge_version": old.knowledge_version,
            "current_knowledge_version": new.knowledge_version,
        }
        for old, new in zip(before, after, strict=True)
    ]
