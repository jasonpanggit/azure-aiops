"""Authentication principals and RBAC enforcement points.

Authorization is evaluated on two axes required by the platform: subscription
scope and business-service scope. A principal carries a set of grants; each
grant pairs a role with a scope. Enforcement happens at two points:

1. :meth:`Authorizer.require` — a coarse gate on the action (read/write/operate).
2. :meth:`Authorizer.effective_scope` — narrows the caller's requested scope to
   what their grants actually permit, so a permitted action can never return
   rows outside the principal's scope.

Both must be applied. The gate alone would let a reader of subscription A read
subscription B; the scope narrowing alone would let a reader mutate data.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .errors import ApiError, ErrorCode, forbidden
from .scope import GRANTABLE_DIMENSIONS, Scope

# Roles, ordered from least to most privileged.
ROLE_READER = "reader"
ROLE_OPERATOR = "operator"
ROLE_APPROVER = "approver"
ROLE_ONTOLOGY_MAINTAINER = "ontology_maintainer"
ROLE_ADMIN = "admin"

ROLES: tuple[str, ...] = (
    ROLE_READER,
    ROLE_OPERATOR,
    ROLE_APPROVER,
    ROLE_ONTOLOGY_MAINTAINER,
    ROLE_ADMIN,
)

# Actions the API gates on.
ACTION_READ = "read"
ACTION_OPERATE = "operate"
ACTION_APPROVE = "approve"
ACTION_MAINTAIN_ONTOLOGY = "maintain_ontology"
ACTION_WRITE = "write"

ACTIONS: tuple[str, ...] = (
    ACTION_READ,
    ACTION_OPERATE,
    ACTION_APPROVE,
    ACTION_MAINTAIN_ONTOLOGY,
    ACTION_WRITE,
)

# Which roles satisfy which action.
_ACTION_ROLES: dict[str, frozenset[str]] = {
    ACTION_READ: frozenset({ROLE_READER, ROLE_OPERATOR, ROLE_APPROVER, ROLE_ADMIN}),
    # Operate = run a sync, validate a connection, execute/retry/cancel
    # approved remediation work: state-changing but not registry-mutating.
    # ROLE_APPROVER deliberately does NOT satisfy operate (Phase 03.5, D-03).
    ACTION_OPERATE: frozenset({ROLE_OPERATOR, ROLE_ADMIN}),
    # Approve = record a remediation approval decision. ROLE_OPERATOR
    # deliberately does NOT satisfy approve -- this is the Phase 03.5, D-03
    # split that lets approve-only and operate-only principals be expressed
    # and enforced independently (REVIEW recommendation 4 / CR-04).
    ACTION_APPROVE: frozenset({ROLE_APPROVER, ROLE_ADMIN}),
    ACTION_MAINTAIN_ONTOLOGY: frozenset({ROLE_ONTOLOGY_MAINTAINER}),
    # Write = create/update/disable a connection, mutate the registry.
    ACTION_WRITE: frozenset({ROLE_ADMIN}),
}


@dataclass(frozen=True)
class Grant:
    """A role held over a scope."""

    role: str
    scope: Scope = field(default_factory=Scope.unrestricted)
    mcp_specialist_id: str = ""

    def __post_init__(self) -> None:
        role = str(self.role or "").strip().casefold()
        if role not in ROLES:
            raise ValueError(f"Unknown role {self.role!r}")
        object.__setattr__(self, "role", role)
        if not isinstance(self.scope, Scope):
            raise TypeError("Grant scope must be a Scope")
        unsupported = set(self.scope.dimensions) - set(GRANTABLE_DIMENSIONS)
        if unsupported:
            raise ValueError(
                "Grants may only be scoped by "
                f"{', '.join(GRANTABLE_DIMENSIONS)}; got {', '.join(sorted(unsupported))}"
            )
        specialist_id = str(self.mcp_specialist_id or "").strip().casefold()
        if specialist_id and not re.fullmatch(r"[a-z][a-z0-9_]{1,79}", specialist_id):
            raise ValueError("MCP specialist ID is invalid")
        object.__setattr__(self, "mcp_specialist_id", specialist_id)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> Grant:
        return cls(
            role=str(payload.get("role") or ""),
            scope=Scope.from_mapping(payload.get("scope")),
            mcp_specialist_id=str(payload.get("mcp_specialist_id") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"role": self.role, "scope": self.scope.to_dict()}
        if self.mcp_specialist_id:
            result["mcp_specialist_id"] = self.mcp_specialist_id
        return result


@dataclass(frozen=True)
class Principal:
    """An authenticated caller."""

    subject: str
    display_name: str = ""
    grants: tuple[Grant, ...] = ()
    # Literal organizational role claims held by this principal (Phase
    # 03.5 CR-05 fix) -- e.g. "Change Manager", "Business Service Owner"
    # -- distinct from ``grants``' coarse RBAC action capacities
    # (reader/operator/approver/admin). These are what
    # ``record_remediation_decision`` checks a principal against before
    # letting a decision attest a distinct-role ``approval_requirements``
    # row: an "approver" grant alone is only ever sufficient for the
    # RBAC-capacity-compatible ``DEFAULT_ROLE_ID`` rows a policy has
    # explicitly opted into (see ``approval_engine.DEFAULT_ROLE_ID``);
    # every other organizational role requires either a literal matching
    # claim here, or an explicit, truthfully-recorded ``admin`` override.
    # Casefolded/stripped/deduped/sorted for stable equality and hashing.
    org_roles: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        subject = str(self.subject or "").strip()
        if not subject:
            raise ValueError("Principal subject is required")
        object.__setattr__(self, "subject", subject)
        object.__setattr__(self, "display_name", str(self.display_name or subject))
        if not all(isinstance(grant, Grant) for grant in self.grants):
            raise TypeError("Principal grants must be Grant instances")
        object.__setattr__(self, "grants", tuple(self.grants))
        specialist_ids = {
            grant.mcp_specialist_id
            for grant in self.grants
            if grant.mcp_specialist_id
        }
        if len(specialist_ids) > 1:
            raise ValueError("Principal grants cannot bind multiple MCP specialists")
        normalized_org_roles = tuple(
            sorted(
                {
                    str(role).strip().casefold()
                    for role in self.org_roles or ()
                    if str(role or "").strip()
                }
            )
        )
        object.__setattr__(self, "org_roles", normalized_org_roles)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> Principal:
        return cls(
            subject=str(payload.get("subject") or ""),
            display_name=str(payload.get("display_name") or ""),
            grants=tuple(
                Grant.from_mapping(item) for item in payload.get("grants") or ()
            ),
            org_roles=tuple(str(role) for role in payload.get("org_roles") or ()),
        )

    def roles(self) -> frozenset[str]:
        return frozenset(grant.role for grant in self.grants)

    def grants_for(self, action: str) -> tuple[Grant, ...]:
        allowed = _ACTION_ROLES[action]
        return tuple(grant for grant in self.grants if grant.role in allowed)

    def mcp_specialist_id(self) -> str | None:
        """Return the specialist identity explicitly bound by trusted grants."""

        return next(
            (
                grant.mcp_specialist_id
                for grant in self.grants
                if grant.mcp_specialist_id
            ),
            None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "display_name": self.display_name,
            "grants": [grant.to_dict() for grant in self.grants],
            "org_roles": list(self.org_roles),
        }


class Authorizer:
    """Evaluates the two RBAC enforcement points."""

    def require(self, principal: Principal, action: str) -> tuple[Grant, ...]:
        """Gate an action. Raises :class:`ApiError` (403) when not permitted."""
        if action not in ACTIONS:
            raise ValueError(f"Unknown action {action!r}")
        grants = principal.grants_for(action)
        if not grants:
            raise forbidden(
                f"Principal {principal.subject!r} may not {action}; "
                f"requires one of: {', '.join(sorted(_ACTION_ROLES[action]))}"
            )
        return grants

    def effective_scope(
        self, principal: Principal, action: str, requested: Scope | None = None
    ) -> Scope:
        """Narrow a requested scope to what the principal's grants permit.

        The result is the requested scope intersected with the *union* of the
        principal's qualifying grant scopes. A principal holding an
        unrestricted grant for the action keeps the requested scope as-is.
        """
        grants = self.require(principal, action)
        requested = requested or Scope.unrestricted()
        if any(grant.scope.is_unrestricted() for grant in grants):
            return requested

        qualifying = [
            grant
            for grant in grants
            if all(
                not requested.values(dimension)
                or not grant.scope.values(dimension)
                or bool(
                    requested.values(dimension)
                    & grant.scope.values(dimension)
                )
                for dimension in GRANTABLE_DIMENSIONS
            )
        ]
        if not qualifying:
            raise forbidden(
                f"Principal {principal.subject!r} is not permitted the requested scope"
            )

        varying = {
            dimension: {
                tuple(sorted(grant.scope.values(dimension)))
                for grant in qualifying
                if grant.scope.values(dimension)
            }
            for dimension in GRANTABLE_DIMENSIONS
        }
        shapes = {
            tuple(
                dimension
                for dimension in GRANTABLE_DIMENSIONS
                if grant.scope.values(dimension)
            )
            for grant in qualifying
        }
        if len(shapes) > 1:
            raise forbidden(
                "Multiple scoped grants require an explicit scope that selects "
                "one compatible grant shape"
            )
        combinations = 1
        for values in varying.values():
            combinations *= max(len(values), 1)
        tuples = {
            tuple(
                tuple(sorted(grant.scope.values(dimension)))
                for dimension in GRANTABLE_DIMENSIONS
            )
            for grant in qualifying
        }
        if len(qualifying) > 1 and combinations > len(tuples):
            raise forbidden(
                "Multiple scoped grants require an explicit subscription or "
                "business-service request to avoid combining unrelated grants"
            )

        permitted: dict[str, frozenset[str]] = {}
        for dimension in GRANTABLE_DIMENSIONS:
            if any(not grant.scope.values(dimension) for grant in qualifying):
                continue
            union: frozenset[str] = frozenset()
            for grant in qualifying:
                union |= grant.scope.values(dimension)
            permitted[dimension] = union

        effective = requested.intersect(Scope(permitted))
        if not effective.is_satisfiable():
            raise forbidden(
                f"Principal {principal.subject!r} is not permitted the requested scope"
            )
        return effective

    def filter(
        self,
        scope: Scope,
        rows: Iterable[Mapping[str, Any]],
        *,
        attributes: Any = None,
    ) -> list[Mapping[str, Any]]:
        """Drop rows that fall outside a scope."""
        from .scope import scope_attributes

        project = attributes or scope_attributes
        if scope.is_unrestricted():
            return list(rows)
        return [row for row in rows if scope.matches(project(row))]


def unauthenticated(reason: str = "Authentication required") -> ApiError:
    return ApiError(ErrorCode.UNAUTHENTICATED, reason)
