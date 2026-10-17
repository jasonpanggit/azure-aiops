"""Identity risk and SPN governance over observed RBAC data.

Answers the questions an access reviewer actually asks: who holds privileged
access, over how much of the estate, how stale is it, and which of those
principals are non-human credentials nobody owns.

All signal derives from ``authorizationresources`` role assignments and role
definitions synced through the same subscription-scoped connection as the
rest of the estate. That has one important consequence: this engine sees
exactly the subscriptions a connection is onboarded for. It never reports on
a tenant the customer has not onboarded, and a principal's "blast radius" is
always stated relative to observed scope rather than implied to be absolute.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

#: Roles that confer the ability to grant further access or to administer
#: everything in scope. Matched on role name, which is stable across tenants.
_PRIVILEGED_ROLE_NAMES = frozenset(
    {
        "owner",
        "contributor",
        "user access administrator",
        "role based access control administrator",
        "security admin",
    }
)

#: Actions that make a custom role privileged regardless of its name.
_PRIVILEGED_ACTIONS = frozenset(
    {
        "*",
        "microsoft.authorization/roleassignments/write",
        "microsoft.authorization/*",
        "microsoft.authorization/*/write",
    }
)

#: A grant untouched for this long is surfaced for review. Ninety days lines
#: up with the common quarterly access-review cadence.
STALE_ACCESS_DAYS = 90

#: Credentials expiring inside this window need rotation scheduled now.
CREDENTIAL_EXPIRY_WARNING_DAYS = 30

_NON_HUMAN_PRINCIPAL_TYPES = frozenset({"serviceprincipal", "managedidentity"})


def _parse_timestamp(value: Any) -> datetime | None:
    """Parse an Azure timestamp, returning None when absent or malformed."""
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _scope_breadth(scope: str) -> str:
    """Classify how much of the estate a grant scope covers."""
    trimmed = str(scope or "").strip("/").lower()
    if not trimmed:
        return "unknown"
    if trimmed.startswith("providers/microsoft.management/managementgroups"):
        return "management_group"
    segments = trimmed.split("/")
    if len(segments) <= 2:
        return "subscription"
    if len(segments) <= 4:
        return "resource_group"
    return "resource"


#: Ordered widest-first; used to rank a principal's largest grant.
_BREADTH_RANK = {
    "management_group": 4,
    "subscription": 3,
    "resource_group": 2,
    "resource": 1,
    "unknown": 0,
}


@dataclass(frozen=True)
class PrincipalRisk:
    """Aggregated access risk for one security principal."""

    principal_id: str
    principal_type: str
    assignment_count: int
    privileged: bool
    widest_scope: str
    widest_scope_breadth: str
    roles: tuple[str, ...]
    stale: bool
    last_changed: str
    blast_radius: dict[str, int] = field(default_factory=dict)
    risk_evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "principal_id": self.principal_id,
            "principal_type": self.principal_type,
            "assignment_count": self.assignment_count,
            "privileged": self.privileged,
            "widest_scope": self.widest_scope,
            "widest_scope_breadth": self.widest_scope_breadth,
            "roles": list(self.roles),
            "stale": self.stale,
            "last_changed": self.last_changed,
            "blast_radius": dict(self.blast_radius),
            "risk_evidence": dict(self.risk_evidence),
        }


@dataclass(frozen=True)
class ServicePrincipalGovernance:
    """Governance posture for one onboarding service principal credential."""

    credential_id: str
    connection_id: str
    connection_name: str
    client_id: str
    tenant_id: str
    subscription_id: str
    kind: str
    active: bool
    scopes: tuple[str, ...]
    expires_at: str
    days_to_expiry: int | None
    rotation_status: str
    secret_ref: str
    in_use: bool
    last_used: str
    # None means "could not be resolved", which is materially different from
    # zero assignments. A service principal's object id is what role
    # assignments reference; the client (application) id does not appear in
    # them, so without a recorded object id we must not imply we looked.
    observed_assignment_count: int | None
    assignment_lookup_state: str
    issues: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "credential_id": self.credential_id,
            "connection_id": self.connection_id,
            "connection_name": self.connection_name,
            "client_id": self.client_id,
            "tenant_id": self.tenant_id,
            "subscription_id": self.subscription_id,
            "kind": self.kind,
            "active": self.active,
            "scopes": list(self.scopes),
            "expires_at": self.expires_at,
            "days_to_expiry": self.days_to_expiry,
            "rotation_status": self.rotation_status,
            "secret_ref": self.secret_ref,
            "in_use": self.in_use,
            "last_used": self.last_used,
            "observed_assignment_count": self.observed_assignment_count,
            "assignment_lookup_state": self.assignment_lookup_state,
            "issues": list(self.issues),
        }


class IdentityRiskEngine:
    """Derives access risk from observed role assignments and definitions.

    Pure and I/O free, like the FinOps engine: callers pass already-scoped
    rows, so subscription isolation is a property of the caller's selection
    rather than something this class can accidentally widen.
    """

    def __init__(
        self,
        *,
        role_assignments: Iterable[Mapping[str, Any]] = (),
        role_definitions: Iterable[Mapping[str, Any]] = (),
        managed_identities: Iterable[Mapping[str, Any]] = (),
        now: datetime | None = None,
    ) -> None:
        self._assignments = [dict(row) for row in role_assignments]
        self._definitions = {
            str(row.get("id") or "").lower(): dict(row) for row in role_definitions
        }
        self._managed_identities = [dict(row) for row in managed_identities]
        self._now = now or datetime.now(UTC)

    def _role_name(self, assignment: Mapping[str, Any]) -> str:
        definition = self._definitions.get(
            str(assignment.get("roleDefinitionId") or "").lower()
        )
        if not definition:
            return ""
        return str(definition.get("roleName") or "")

    def _is_privileged(self, assignment: Mapping[str, Any]) -> bool:
        name = self._role_name(assignment).strip().lower()
        if name in _PRIVILEGED_ROLE_NAMES:
            return True
        definition = self._definitions.get(
            str(assignment.get("roleDefinitionId") or "").lower()
        )
        if not definition:
            return False
        actions = definition.get("actions")
        if not isinstance(actions, list):
            return False
        return any(str(action).strip().lower() in _PRIVILEGED_ACTIONS for action in actions)

    def _age_state(self, assignment: Mapping[str, Any]) -> str:
        text = str(assignment.get("updatedOn") or assignment.get("createdOn") or "").strip()
        try:
            changed = datetime.fromisoformat(text)
        except ValueError:
            return "unknown"
        if changed.tzinfo is None or changed.utcoffset() is None or changed > self._now:
            return "unknown"
        return "stale" if (self._now - changed).days > STALE_ACCESS_DAYS else "within_review_window"

    def _is_stale(self, assignment: Mapping[str, Any]) -> bool:
        return self._age_state(assignment) == "stale"

    def _risk_evidence(self, assignments: list[dict[str, Any]], privileged: bool) -> dict[str, Any]:
        unresolved = 0
        for assignment in assignments:
            definition = self._definitions.get(str(assignment.get("roleDefinitionId") or "").lower())
            actions = definition.get("actions") if definition else None
            if (
                not definition or not str(definition.get("roleName") or "").strip()
                or not isinstance(actions, list) or not actions
                or not all(isinstance(action, str) and action.strip() for action in actions)
            ):
                unresolved += 1
        states = [self._age_state(assignment) for assignment in assignments]
        return {
            "classification": "privileged_signal" if privileged else "incomplete" if unresolved else "no_classified_signal",
            "unresolved_role_assignments": unresolved,
            "unknown_age_assignments": states.count("unknown"),
            "stale_assignments": states.count("stale"),
            "age_evaluated_at": self._now.isoformat(),
            "effective_access": "not_evaluated",
        }

    def principals(self) -> list[PrincipalRisk]:
        """One risk record per principal, most privileged and widest first."""
        grouped: dict[str, list[dict[str, Any]]] = {}
        for assignment in self._assignments:
            principal_id = str(assignment.get("principalId") or "").strip()
            if not principal_id:
                continue
            grouped.setdefault(principal_id, []).append(assignment)

        records: list[PrincipalRisk] = []
        for principal_id, assignments in grouped.items():
            widest_scope = ""
            widest_breadth = "unknown"
            blast_radius: dict[str, int] = {}
            roles: set[str] = set()
            privileged = False
            latest: datetime | None = None

            for assignment in assignments:
                scope = str(assignment.get("assignmentScope") or "")
                breadth = _scope_breadth(scope)
                blast_radius[breadth] = blast_radius.get(breadth, 0) + 1
                if _BREADTH_RANK[breadth] > _BREADTH_RANK[widest_breadth]:
                    widest_breadth = breadth
                    widest_scope = scope
                name = self._role_name(assignment)
                if name:
                    roles.add(name)
                privileged = privileged or self._is_privileged(assignment)
                changed = _parse_timestamp(
                    assignment.get("updatedOn") or assignment.get("createdOn")
                )
                if changed and (latest is None or changed > latest):
                    latest = changed

            # A principal is stale if ANY of its grants is stale, not only
            # when every grant is: one recent assignment must never mask a
            # forgotten privileged grant sitting untouched alongside it.
            records.append(
                PrincipalRisk(
                    principal_id=principal_id,
                    principal_type=str(assignments[0].get("principalType") or "Unknown"),
                    assignment_count=len(assignments),
                    privileged=privileged,
                    widest_scope=widest_scope,
                    widest_scope_breadth=widest_breadth,
                    roles=tuple(sorted(roles)),
                    stale=any(self._is_stale(item) for item in assignments),
                    last_changed=latest.isoformat() if latest else "",
                    blast_radius=blast_radius,
                    risk_evidence=self._risk_evidence(assignments, privileged),
                )
            )

        records.sort(
            key=lambda record: (
                not record.privileged,
                -_BREADTH_RANK[record.widest_scope_breadth],
                -record.assignment_count,
                record.principal_id,
            )
        )
        return records

    def subscription_owners(self) -> list[dict[str, Any]]:
        """Principals holding Owner at subscription scope or wider."""
        owners: list[dict[str, Any]] = []
        for assignment in self._assignments:
            if self._role_name(assignment).strip().lower() != "owner":
                continue
            breadth = _scope_breadth(str(assignment.get("assignmentScope") or ""))
            if breadth not in {"subscription", "management_group"}:
                continue
            owners.append(
                {
                    "principal_id": str(assignment.get("principalId") or ""),
                    "principal_type": str(assignment.get("principalType") or "Unknown"),
                    "scope": str(assignment.get("assignmentScope") or ""),
                    "scope_breadth": breadth,
                    "subscription_id": str(assignment.get("subscriptionId") or ""),
                    "assigned_on": str(
                        assignment.get("createdOn") or assignment.get("updatedOn") or ""
                    ),
                    "stale": self._is_stale(assignment),
                    "age_state": self._age_state(assignment),
                }
            )
        owners.sort(key=lambda entry: (entry["subscription_id"], entry["principal_id"]))
        return owners

    def stale_access(self) -> list[dict[str, Any]]:
        """Assignments untouched beyond the review threshold."""
        stale = [
            {
                "assignment_id": str(assignment.get("id") or ""),
                "principal_id": str(assignment.get("principalId") or ""),
                "principal_type": str(assignment.get("principalType") or "Unknown"),
                "role": self._role_name(assignment),
                "scope": str(assignment.get("assignmentScope") or ""),
                "privileged": self._is_privileged(assignment),
                "last_changed": str(
                    assignment.get("updatedOn") or assignment.get("createdOn") or ""
                ),
                "threshold_days": STALE_ACCESS_DAYS,
            }
            for assignment in self._assignments
            if self._is_stale(assignment)
        ]
        stale.sort(key=lambda entry: (not entry["privileged"], entry["principal_id"]))
        return stale

    def non_human_identities(self) -> list[dict[str, Any]]:
        """Service principals and managed identities holding access.

        Managed identities observed in the inventory but holding no observed
        assignment are still listed, with a zero count -- an unused identity
        is itself a governance finding.
        """
        records = [
            record.to_dict()
            for record in self.principals()
            if record.principal_type.strip().lower() in _NON_HUMAN_PRINCIPAL_TYPES
        ]
        seen = {record["principal_id"] for record in records}

        for identity in self._managed_identities:
            principal_id = str(identity.get("principalId") or "").strip()
            if not principal_id or principal_id in seen:
                continue
            records.append(
                {
                    "principal_id": principal_id,
                    "principal_type": "ManagedIdentity",
                    "assignment_count": 0,
                    "privileged": False,
                    "widest_scope": "",
                    "widest_scope_breadth": "unknown",
                    "roles": [],
                    "stale": False,
                    "last_changed": "",
                    "blast_radius": {},
                    "resource_id": str(identity.get("id") or ""),
                    "name": str(identity.get("name") or ""),
                }
            )
        return records

    def summary(self) -> dict[str, Any]:
        principals = self.principals()
        return {
            "principal_count": len(principals),
            "privileged_principal_count": sum(1 for item in principals if item.privileged),
            "subscription_owner_count": len(self.subscription_owners()),
            "stale_assignment_count": len(self.stale_access()),
            "non_human_principal_count": len(self.non_human_identities()),
            "assignment_count": len(self._assignments),
            "stale_threshold_days": STALE_ACCESS_DAYS,
        }


class SpnGovernanceEngine:
    """Governance posture for the service principals used to onboard Azure.

    These are the credentials the platform itself holds, so unlike the RBAC
    view above this is fully knowable: the connection registry records owner,
    scope, expiry, and last successful use.
    """

    def __init__(
        self,
        connections: Iterable[Mapping[str, Any]],
        *,
        role_assignments: Iterable[Mapping[str, Any]] = (),
        now: datetime | None = None,
    ) -> None:
        self._connections = [dict(row) for row in connections]
        self._now = now or datetime.now(UTC)
        self._assignments_by_principal: dict[str, int] = {}
        for assignment in role_assignments:
            principal_id = str(assignment.get("principalId") or "").strip().lower()
            if principal_id:
                self._assignments_by_principal[principal_id] = (
                    self._assignments_by_principal.get(principal_id, 0) + 1
                )

    def credentials(self) -> list[ServicePrincipalGovernance]:
        records: list[ServicePrincipalGovernance] = []
        for connection in self._connections:
            credential = connection.get("credential")
            if not isinstance(credential, Mapping):
                continue

            expires_at = str(credential.get("expires_at") or "")
            expiry = _parse_timestamp(expires_at)
            days_to_expiry = (expiry - self._now).days if expiry else None
            rotation_status, issues = self._rotation_status(
                credential, days_to_expiry, expires_at
            )

            sync_state = connection.get("sync_state")
            sync_state = sync_state if isinstance(sync_state, Mapping) else {}
            last_used = str(
                sync_state.get("last_successful_sync")
                or sync_state.get("last_sync_at")
                or sync_state.get("lastSyncAt")
                or ""
            )

            client_id = str(credential.get("client_id") or "")
            # Role assignments reference the service principal's *object* id,
            # never its client/application id. Only count when we actually
            # hold that object id; otherwise say we could not resolve it.
            object_id = str(
                credential.get("object_id")
                or credential.get("principal_id")
                or credential.get("principalId")
                or credential.get("service_principal_object_id")
                or ""
            ).strip()
            if object_id:
                assignment_count: int | None = self._assignments_by_principal.get(
                    object_id.lower(), 0
                )
                lookup_state = "resolved"
            else:
                assignment_count = None
                lookup_state = "unresolved_no_object_id"
            records.append(
                ServicePrincipalGovernance(
                    credential_id=str(credential.get("credential_id") or ""),
                    connection_id=str(connection.get("connection_id") or ""),
                    connection_name=str(connection.get("name") or ""),
                    client_id=client_id,
                    tenant_id=str(
                        credential.get("tenant_id") or connection.get("tenant_id") or ""
                    ),
                    subscription_id=str(connection.get("subscription_id") or ""),
                    kind=str(credential.get("kind") or "service_principal"),
                    active=bool(credential.get("active", True)),
                    scopes=tuple(
                        str(scope) for scope in (credential.get("scopes") or ()) if scope
                    )
                    or ((str(credential.get("scope")),) if credential.get("scope") else ()),
                    expires_at=expires_at,
                    days_to_expiry=days_to_expiry,
                    rotation_status=rotation_status,
                    secret_ref=str(credential.get("secret_ref") or ""),
                    in_use=bool(last_used),
                    last_used=last_used,
                    observed_assignment_count=assignment_count,
                    assignment_lookup_state=lookup_state,
                    issues=tuple(issues),
                )
            )

        # Worst posture first so a reviewer sees what needs action immediately.
        order = {"expired": 0, "expiring_soon": 1, "unknown": 2, "healthy": 3}
        records.sort(
            key=lambda record: (
                order.get(record.rotation_status, 4),
                record.days_to_expiry if record.days_to_expiry is not None else 10**6,
                record.connection_name,
            )
        )
        return records

    def _rotation_status(
        self,
        credential: Mapping[str, Any],
        days_to_expiry: int | None,
        expires_at: str,
    ) -> tuple[str, list[str]]:
        issues: list[str] = []
        if not credential.get("secret_ref"):
            issues.append("Credential has no Key Vault secret reference recorded")
        if not credential.get("client_id"):
            issues.append("Credential has no client id recorded")

        if not expires_at:
            # Reported as unknown rather than healthy: an unknown expiry is a
            # governance gap, and calling it healthy would hide that.
            issues.append("Credential expiry is not recorded, so rotation cannot be verified")
            return "unknown", issues
        if days_to_expiry is None:
            issues.append("Credential expiry could not be parsed")
            return "unknown", issues
        if days_to_expiry < 0:
            issues.append(f"Credential expired {abs(days_to_expiry)} days ago")
            return "expired", issues
        if days_to_expiry <= CREDENTIAL_EXPIRY_WARNING_DAYS:
            issues.append(f"Credential expires in {days_to_expiry} days")
            return "expiring_soon", issues
        return "healthy", issues

    def summary(self) -> dict[str, Any]:
        credentials = self.credentials()
        counts: dict[str, int] = {}
        for record in credentials:
            counts[record.rotation_status] = counts.get(record.rotation_status, 0) + 1
        return {
            "credential_count": len(credentials),
            "expired_count": counts.get("expired", 0),
            "expiring_soon_count": counts.get("expiring_soon", 0),
            "unknown_expiry_count": counts.get("unknown", 0),
            "healthy_count": counts.get("healthy", 0),
            "unused_count": sum(1 for record in credentials if not record.in_use),
            "expiry_warning_days": CREDENTIAL_EXPIRY_WARNING_DAYS,
        }


__all__ = [
    "CREDENTIAL_EXPIRY_WARNING_DAYS",
    "STALE_ACCESS_DAYS",
    "IdentityRiskEngine",
    "PrincipalRisk",
    "ServicePrincipalGovernance",
    "SpnGovernanceEngine",
]
