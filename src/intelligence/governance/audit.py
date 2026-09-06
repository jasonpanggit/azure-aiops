"""Access review packs and audit evidence exports.

Both features answer the same underlying question -- "prove to me who had
access to what, and when you observed it" -- so they share one module and one
provenance discipline.

Every pack records the engines it was built from, the scope it was generated
under, and the observation timestamp of the underlying data. A pack that
cannot state its provenance is not audit evidence; it is a spreadsheet.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import RLock
from typing import Any
from uuid import uuid4

_LOGGER = logging.getLogger(__name__)

#: Review packs supported today. Each targets a different audience and so
#: answers a different question, rather than being the same table relabelled.
REVIEW_AUDIENCES = ("service_owner", "security", "auditor")

#: Evidence packs the platform can produce from observed data.
EXPORT_KINDS = (
    "subscription_onboarding",
    "network_design",
    "firewall_nsg",
    "vulnerability_exposure",
    "identity",
    "remediation",
    "executive",
)

EXPOSURE_AUDIT_EVENT_TYPES = frozenset(
    {
        "exposure.review_handoff_created",
        "exposure.risk_exception_created",
        "remediation.execution_requested",
        "remediation.execution_retry_requested",
        "remediation.execution_supersede_requested",
        "remediation.execution_cancel_requested",
    }
)
_SENSITIVE_AUDIT_KEY_MARKERS = (
    "authorization",
    "client_secret",
    "credential",
    "password",
    "raw_error",
    "raw_provider_error",
    "secret",
    "token",
)


class ExposureAuditUnavailable(RuntimeError):
    """Stable failure raised when a sensitive event cannot be appended."""


@dataclass(frozen=True)
class ExposureAuditEvent:
    """Immutable evidence binding for an Exposure-sensitive transition."""

    event_id: str
    event_type: str
    subject: str
    tenant_id: str
    connection_ids: tuple[str, ...]
    scope: Mapping[str, Sequence[str]]
    target: Mapping[str, Any]
    generation: str
    evidence_refs: tuple[Mapping[str, Any], ...]
    decision: str
    reason: str
    result: str
    timestamp: str

    def __post_init__(self) -> None:
        event_id = _required_audit_text(self.event_id, "event_id")
        event_type = _required_audit_text(self.event_type, "event_type")
        if event_type not in EXPOSURE_AUDIT_EVENT_TYPES:
            raise ValueError(f"Unsupported Exposure audit event type: {event_type}")
        subject = _required_audit_text(self.subject, "subject")
        decision = _required_audit_text(self.decision, "decision")
        result = _required_audit_text(self.result, "result")
        timestamp = _required_audit_text(self.timestamp, "timestamp")
        try:
            parsed = datetime.fromisoformat(timestamp)
        except ValueError as exc:
            raise ValueError("Exposure audit timestamp must be ISO-8601") from exc
        if parsed.tzinfo is None:
            raise ValueError("Exposure audit timestamp must include a timezone")
        normalized_scope = {
            str(name): sorted(
                {
                    str(value)
                    for value in values
                    if str(value)
                }
            )
            for name, values in self.scope.items()
            if values
        }
        normalized_target = _safe_audit_mapping(self.target)
        normalized_evidence = tuple(
            _safe_audit_mapping(reference)
            for reference in self.evidence_refs
        )
        object.__setattr__(self, "event_id", event_id)
        object.__setattr__(self, "event_type", event_type)
        object.__setattr__(self, "subject", subject)
        object.__setattr__(
            self,
            "connection_ids",
            tuple(
                sorted(
                    {
                        str(value)
                        for value in self.connection_ids
                        if str(value)
                    }
                )
            ),
        )
        object.__setattr__(self, "scope", normalized_scope)
        object.__setattr__(self, "target", normalized_target)
        object.__setattr__(self, "evidence_refs", normalized_evidence)
        object.__setattr__(self, "decision", decision)
        object.__setattr__(self, "reason", str(self.reason or "").strip())
        object.__setattr__(self, "result", result)
        object.__setattr__(self, "timestamp", parsed.astimezone(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "subject": self.subject,
            "tenant_id": str(self.tenant_id or ""),
            "connection_ids": list(self.connection_ids),
            "scope": {
                name: list(values)
                for name, values in self.scope.items()
            },
            "target": dict(self.target),
            "generation": str(self.generation or ""),
            "evidence_refs": [
                dict(reference) for reference in self.evidence_refs
            ],
            "decision": self.decision,
            "reason": self.reason,
            "result": self.result,
            "timestamp": self.timestamp,
        }


class AppendOnlyExposureAuditLog:
    """Thread-safe append-only log with immutable event identities."""

    def __init__(self) -> None:
        self._events: dict[str, ExposureAuditEvent] = {}
        self._lock = RLock()

    def append(self, event: ExposureAuditEvent) -> ExposureAuditEvent:
        if not isinstance(event, ExposureAuditEvent):
            raise TypeError("Exposure audit log accepts ExposureAuditEvent only")
        with self._lock:
            previous = self._events.get(event.event_id)
            if previous is not None and previous != event:
                raise ValueError(
                    f"Exposure audit event {event.event_id} is immutable"
                )
            self._events[event.event_id] = event
        return event

    def rows(self) -> list[dict[str, Any]]:
        with self._lock:
            return [event.to_dict() for event in self._events.values()]


_EXPOSURE_AUDIT_LOG = AppendOnlyExposureAuditLog()


def new_exposure_audit_event(
    *,
    event_type: str,
    subject: str,
    tenant_id: str = "",
    connection_ids: Iterable[str] = (),
    scope: Mapping[str, Sequence[str]] | None = None,
    target: Mapping[str, Any] | None = None,
    generation: str = "",
    evidence_refs: Iterable[Mapping[str, Any]] = (),
    decision: str,
    reason: str = "",
    result: str,
    timestamp: str | None = None,
) -> ExposureAuditEvent:
    return ExposureAuditEvent(
        event_id=f"exposure-audit:{uuid4()}",
        event_type=event_type,
        subject=subject,
        tenant_id=tenant_id,
        connection_ids=tuple(connection_ids),
        scope=scope or {},
        target=target or {},
        generation=generation,
        evidence_refs=tuple(evidence_refs),
        decision=decision,
        reason=reason,
        result=result,
        timestamp=timestamp or _now(),
    )


def append_exposure_audit(context: Any, event: ExposureAuditEvent) -> None:
    """Append via the configured sink and fail closed with a stable error."""

    sink = getattr(context, "exposure_audit_append", None)
    try:
        if callable(sink):
            sink(event)
        else:
            _EXPOSURE_AUDIT_LOG.append(event)
    except Exception as exc:
        _LOGGER.error(
            "exposure_audit_append_failed event_type=%s",
            event.event_type,
        )
        raise ExposureAuditUnavailable(
            "Exposure audit append failed"
        ) from exc


def exposure_audit_rows() -> list[dict[str, Any]]:
    return _EXPOSURE_AUDIT_LOG.rows()


def _required_audit_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"Exposure audit {field_name} is required")
    return text


def _safe_audit_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    def normalize(item: Any, *, path: str) -> Any:
        if isinstance(item, Mapping):
            result: dict[str, Any] = {}
            for raw_key, child in item.items():
                key = str(raw_key)
                normalized_key = key.casefold().replace("-", "_")
                if any(
                    marker in normalized_key
                    for marker in _SENSITIVE_AUDIT_KEY_MARKERS
                ):
                    raise ValueError(
                        f"Exposure audit contains sensitive field at {path + key}"
                    )
                result[key] = normalize(child, path=f"{path}{key}.")
            return result
        if isinstance(item, list | tuple):
            return [
                normalize(child, path=f"{path}[]")
                for child in item
            ]
        if item is None or isinstance(item, str | int | float | bool):
            return item
        return str(item)

    return normalize(dict(value), path="")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _provenance(
    *,
    engines: Sequence[str],
    scope: Mapping[str, Any] | None,
    observed_at: str | None,
    warnings: Sequence[str] = (),
) -> dict[str, Any]:
    """The block that makes a pack defensible in an audit."""
    return {
        "generated_at": _now(),
        "source_engines": list(engines),
        "scope": dict(scope or {}),
        "observed_at": observed_at or "",
        "warnings": list(warnings),
    }


class AccessReviewBuilder:
    """Builds review packs for the three audiences that request them."""

    def __init__(
        self,
        *,
        identity_engine: Any,
        spn_engine: Any | None = None,
        scope: Mapping[str, Any] | None = None,
        observed_at: str | None = None,
    ) -> None:
        self._identity = identity_engine
        self._spn = spn_engine
        self._scope = scope
        self._observed_at = observed_at

    def build(self, audience: str) -> dict[str, Any]:
        if audience not in REVIEW_AUDIENCES:
            raise ValueError(f"Unsupported access review audience: {audience}")
        builder = {
            "service_owner": self._service_owner_pack,
            "security": self._security_pack,
            "auditor": self._auditor_pack,
        }[audience]
        pack = builder()
        pack["audience"] = audience
        pack["provenance"] = _provenance(
            engines=["identity_risk"] + (["spn_governance"] if self._spn else []),
            scope=self._scope,
            observed_at=self._observed_at,
            warnings=[] if self._spn else ["Service principal governance data was unavailable"],
        )
        return pack

    def _service_owner_pack(self) -> dict[str, Any]:
        """Who can change my service, and what should I revoke?

        Owners get a short actionable list, not the full estate: privileged
        and stale grants only, since those are the ones a service owner can
        reasonably be asked to make a decision about.
        """
        principals = [record.to_dict() for record in self._identity.principals()]
        actionable = [
            record for record in principals if record["privileged"] or record["stale"]
        ]
        return {
            "title": "Service owner access review",
            "instruction": (
                "Confirm each principal still requires this access. "
                "Revoke anything unrecognised or no longer required."
            ),
            "items": actionable,
            "item_count": len(actionable),
            "total_principal_count": len(principals),
            "summary": self._identity.summary(),
        }

    def _security_pack(self) -> dict[str, Any]:
        """Where is the concentrated risk across the onboarded estate?"""
        return {
            "title": "Security access review",
            "instruction": (
                "Review privileged access concentration, subscription ownership, "
                "and non-human identity sprawl."
            ),
            "privileged_principals": [
                record.to_dict()
                for record in self._identity.principals()
                if record.privileged
            ],
            "subscription_owners": self._identity.subscription_owners(),
            "non_human_identities": self._identity.non_human_identities(),
            "service_principal_credentials": (
                [record.to_dict() for record in self._spn.credentials()] if self._spn else []
            ),
            "summary": self._identity.summary(),
        }

    def _auditor_pack(self) -> dict[str, Any]:
        """The complete observed record, with gaps stated explicitly."""
        return {
            "title": "Auditor access review",
            "instruction": (
                "Complete observed record of role assignments within the "
                "onboarded subscription scope at the stated observation time."
            ),
            "principals": [record.to_dict() for record in self._identity.principals()],
            "subscription_owners": self._identity.subscription_owners(),
            "stale_access": self._identity.stale_access(),
            "service_principal_credentials": (
                [record.to_dict() for record in self._spn.credentials()] if self._spn else []
            ),
            "summary": self._identity.summary(),
            "coverage_note": (
                "Covers only subscriptions onboarded through an active connection. "
                "Principals with access granted outside these subscriptions are not observable."
            ),
        }


class AuditExportBuilder:
    """Assembles evidence packs from already-scoped source sections.

    Deliberately dumb about where data comes from: the caller resolves each
    section and hands it in. That keeps the builder testable and keeps scope
    enforcement in one place -- the router -- rather than duplicated here.
    """

    def __init__(
        self,
        *,
        scope: Mapping[str, Any] | None = None,
        observed_at: str | None = None,
    ) -> None:
        self._scope = scope
        self._observed_at = observed_at

    def build(
        self,
        kind: str,
        sections: Mapping[str, Any],
        *,
        engines: Iterable[str] = (),
        warnings: Iterable[str] = (),
    ) -> dict[str, Any]:
        if kind not in EXPORT_KINDS:
            raise ValueError(f"Unsupported audit export kind: {kind}")
        section_map = dict(sections)
        # An empty section is reported as present-but-empty rather than
        # omitted, so a reader can tell "nothing found" from "not collected".
        return {
            "kind": kind,
            "title": kind.replace("_", " ").title() + " evidence pack",
            "sections": section_map,
            "section_counts": {
                name: len(value) if isinstance(value, list | tuple) else 1
                for name, value in section_map.items()
            },
            "provenance": _provenance(
                engines=list(engines),
                scope=self._scope,
                observed_at=self._observed_at,
                warnings=list(warnings),
            ),
        }


__all__ = [
    "EXPORT_KINDS",
    "EXPOSURE_AUDIT_EVENT_TYPES",
    "REVIEW_AUDIENCES",
    "AccessReviewBuilder",
    "AppendOnlyExposureAuditLog",
    "AuditExportBuilder",
    "ExposureAuditEvent",
    "ExposureAuditUnavailable",
    "append_exposure_audit",
    "exposure_audit_rows",
    "new_exposure_audit_event",
]
