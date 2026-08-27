"""Access review packs and audit evidence exports.

Both features answer the same underlying question -- "prove to me who had
access to what, and when you observed it" -- so they share one module and one
provenance discipline.

Every pack records the engines it was built from, the scope it was generated
under, and the observation timestamp of the underlying data. A pack that
cannot state its provenance is not audit evidence; it is a spreadsheet.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

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
    "REVIEW_AUDIENCES",
    "AccessReviewBuilder",
    "AuditExportBuilder",
]
