"""Composition root and FastAPI request dependencies.

The API owns no business logic. It composes the existing service layer
(:class:`SubscriptionOnboardingService`, :class:`SemanticEngine`) and exposes it
over HTTP. Everything routes through the Semantic Knowledge Layer — no router
reads Fabric, ontology tables, or ARG directly.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Query, Request

from onboarding.service import SubscriptionOnboardingService
from semantic.semantic_engine import SemanticEngine

from .auth import Authenticator
from .errors import ApiError, ErrorCode
from .providers import ProviderRuntime, ProviderUnavailableError
from .rbac import Authorizer, Principal
from .scope import Scope
from .telemetry import ApiTelemetry


@dataclass
class ApiContext:
    """Everything a request handler may reach for."""

    onboarding: SubscriptionOnboardingService
    authenticator: Authenticator
    authorizer: Authorizer
    telemetry: ApiTelemetry
    # The semantic engine is built from an ontology snapshot, which is refreshed
    # out of band. A provider (rather than an instance) lets the process pick up
    # a new snapshot without a restart.
    semantic_provider: Callable[[], SemanticEngine] | None = None
    # Optional hybrid graph + live-state provider. It is selected only for
    # resource reads with an explicit subscription scope during migration.
    hybrid_resource_provider: (
        Callable[[str, list[str]], dict[str, Any]] | None
    ) = None
    hybrid_search_provider: Callable[[str, list[str]], dict[str, Any]] | None = None
    hybrid_business_service_provider: (
        Callable[[str, list[str]], dict[str, Any]] | None
    ) = None
    hybrid_impact_provider: Callable[[str, list[str]], dict[str, Any]] | None = None
    hybrid_risk_provider: Callable[[str, list[str]], dict[str, Any]] | None = None
    hybrid_network_provider: Callable[[list[str]], Any] | None = None
    hybrid_vulnerability_provider: Callable[[list[str]], Any] | None = None
    hybrid_incident_provider: Callable[[list[str]], Any] | None = None
    hybrid_remediation_provider: Callable[[list[str]], Any] | None = None
    hybrid_patching_provider: Callable[[list[str]], Any] | None = None
    hybrid_change_provider: Callable[[list[str]], Any] | None = None
    # Live resource-health utilization (CPU/disk/network) via Azure Monitor
    # Metrics. Resolved per request like the other hybrid providers since it
    # performs a live per-connection Azure call rather than reading a snapshot.
    hybrid_resource_health_provider: Callable[[list[str]], Any] | None = None
    # Same rationale for the intelligence engines: they are projections of a
    # snapshot, so they are resolved per request rather than pinned at startup.
    incident_provider: Callable[[], Any] | None = None
    remediation_provider: Callable[[], Any] | None = None
    network_provider: Callable[[], Any] | None = None
    vulnerability_provider: Callable[[], Any] | None = None
    # Compliance posture (policy/security deviations, configuration drift,
    # unapproved changes) is a projection of the same knowledge snapshot as
    # the other intelligence engines, so it is resolved per request too.
    change_provider: Callable[[], Any] | None = None
    # Patch remediation is the read projection (what's installable) plus the
    # guarded trigger path. It is resolved per request like the other
    # projections so a fresh snapshot is picked up without a restart.
    patching_provider: Callable[[], Any] | None = None
    # The bounded, approval-gated execution path for one already-approved
    # patch or explicit Defender configuration plan. Resolved per request (not pinned at
    # startup) so a fresh RemediationExecutionService always sees the
    # scope-selected remediation planner/patching provider used by preview and
    # approval.
    execution_provider: Callable[[Scope], Any] | None = None
    # Enterprise governance: FinOps, identity risk, and SPN governance are all
    # projections of the same ontology snapshot, so they follow the per-request
    # resolution rule above rather than being pinned at startup.
    governance_provider: Callable[[], Any] | None = None
    # Enterprise settings are a user-submitted mutation rather than a snapshot
    # projection, so like risk exceptions they use a direct store handle.
    settings_store: Any | None = None
    # The network design policy (rule-based, UI-editable) is likewise a
    # user-submitted mutation, not a snapshot projection, and is applied to
    # every rebuilt NetworkIntelligenceService via the same store handle.
    network_policy_store: Any | None = None
    # Best-effort live lookup for a single CVE id directly from NVD, used when
    # the CVE isn't already tied to a snapshot finding (e.g. a user searching
    # for a CVE the current environment hasn't observed yet). Returns None on
    # any failure or unknown id so callers can fall back to a 404.
    vulnerability_live_lookup: Callable[[str], dict[str, Any] | None] | None = None
    # Risk-acceptance/exception management for vulnerability findings. These
    # are user-submitted mutations (not snapshot projections), so they use
    # direct callables into the module-level store rather than a rebuilt
    # provider.
    risk_exception_list: Callable[[], list[Any]] | None = None
    risk_exception_add: Callable[[Any], None] | None = None
    risk_exception_revoke: Callable[[str], bool] | None = None
    # The Foundry prompt agent narrates retrieved context for the Copilot. It is
    # optional by design: a deployment without Foundry still serves every route,
    # with the Copilot degrading to retrieval-only answers.
    foundry_agent_provider: Callable[[], Any] | None = None
    provider_runtime: ProviderRuntime | None = None
    # Specialist agents for domain-specific analysis. Each resolves independently
    # using FoundryPromptAgent.from_env(specialist_id) to read per-agent env vars.
    # All are optional; missing specialists degrade to generic Copilot narration.
    network_agent_provider: Callable[[], Any] | None = None
    vulnerability_agent_provider: Callable[[], Any] | None = None
    patch_agent_provider: Callable[[], Any] | None = None
    incident_agent_provider: Callable[[], Any] | None = None
    change_agent_provider: Callable[[], Any] | None = None
    governance_agent_provider: Callable[[], Any] | None = None
    remediation_agent_provider: Callable[[], Any] | None = None
    executive_summary_agent_provider: Callable[[], Any] | None = None
    # Durable situation/evidence read model, resolved per request like the
    # semantic snapshot so a newly synchronized generation is visible.
    situation_provider: Callable[[], Any] | None = None
    # OS inventory is a read-only projection of the active immutable generation.
    inventory_provider: Callable[[], Any] | None = None
    inventory_read_port_provider: Callable[[], Any] | None = None
    fabric_iq_provider: Callable[[], Any] | None = None

    def resolve_provider(self, name: str, *, optional: bool = False) -> Any:
        """Resolve a provider through the managed runtime or legacy callable."""
        if self.provider_runtime is not None:
            try:
                return self.provider_runtime.get(name, optional=optional)
            except ProviderUnavailableError as exc:
                state = exc.provider_state
                raise ApiError(
                    ErrorCode.PROVIDER_UNAVAILABLE,
                    f"The {name} provider is {state.state}",
                    {
                        "capability": name,
                        "provider_state": state.state,
                        "retry_attempts": state.retry_attempts,
                        "next_retry_at": state.next_retry_at,
                    },
                ) from exc
        provider = (
            self.foundry_agent_provider
            if name == "copilot"
            else getattr(self, f"{name}_provider", None)
        )
        value = provider() if callable(provider) else None
        if value is None and not optional:
            raise ApiError(
                ErrorCode.PROVIDER_UNAVAILABLE,
                f"The {name} provider has no loaded snapshot",
                {"capability": name, "provider_state": "unavailable"},
            )
        return value

    def foundry_agent(self) -> Any | None:
        """Resolve the narration agent, or ``None`` when unavailable.

        Unlike :meth:`semantic`, a missing agent is not an error — the Copilot
        route reports it as a warning on an otherwise complete answer.
        """
        return self.resolve_provider("copilot", optional=True)

    def specialist_agent(self, agent_id: str) -> Any | None:
        """Resolve a specialist agent by id, or ``None`` when unavailable.

        Specialist agents (vulnerability, patch, incident, change, governance,
        remediation, executive_summary) are optional. Missing agents degrade to
        generic Copilot narration or retrieval-only responses.
        """
        agent_id = (agent_id or "").strip().lower()
        if agent_id in (
            "network",
            "vulnerability",
            "patch",
            "incident",
            "change",
            "governance",
            "remediation",
            "executive_summary",
        ):
            return self.resolve_provider(f"{agent_id}_agent", optional=True)
        return None

    def semantic(self) -> SemanticEngine:
        return self.resolve_provider("semantic")

    def inventory_read_port(self) -> Any:
        """Resolve the scope-enforcing identity read port.

        Consumers receive this contract rather than the inventory service so
        the service cannot be used to bypass the request's effective scope.
        """
        return self.resolve_provider("inventory_read_port")


def get_context(request: Request) -> ApiContext:
    context = getattr(request.app.state, "context", None)
    if context is None:
        raise ApiError(ErrorCode.INTERNAL, "API context is not configured")
    return context


Context = Annotated[ApiContext, Depends(get_context)]


def get_principal(request: Request, context: Context) -> Principal:
    """Authenticate the caller. Raises 401 when the caller cannot be identified."""
    return context.authenticator.authenticate(dict(request.headers))


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


ScopeBusinessService = Annotated[
    list[str] | None, Query(alias="business_service")
]
ScopeApplication = Annotated[list[str] | None, Query(alias="application")]
ScopeEnvironment = Annotated[list[str] | None, Query(alias="environment")]
ScopeSubscription = Annotated[list[str] | None, Query(alias="subscription")]
ScopeSubscriptionConnection = Annotated[
    list[str] | None, Query(alias="subscription_connection")
]
ScopeOwner = Annotated[list[str] | None, Query(alias="owner")]
ScopeSupportTeam = Annotated[list[str] | None, Query(alias="support_team")]
ScopeRegion = Annotated[list[str] | None, Query(alias="region")]
ScopeCriticality = Annotated[list[str] | None, Query(alias="criticality")]


def get_requested_scope(
    scope_business_service: ScopeBusinessService = None,
    scope_application: ScopeApplication = None,
    scope_environment: ScopeEnvironment = None,
    scope_subscription: ScopeSubscription = None,
    scope_subscription_connection: ScopeSubscriptionConnection = None,
    scope_owner: ScopeOwner = None,
    scope_support_team: ScopeSupportTeam = None,
    scope_region: ScopeRegion = None,
    scope_criticality: ScopeCriticality = None,
) -> Scope:
    """Parse scope from repeated query parameters, e.g.
    ``?environment=prod&business_service=retail+banking``.
    """
    values = {
        "business_service": scope_business_service,
        "application": scope_application,
        "environment": scope_environment,
        "subscription": scope_subscription,
        "subscription_connection": scope_subscription_connection,
        "owner": scope_owner,
        "support_team": scope_support_team,
        "region": scope_region,
        "criticality": scope_criticality,
    }
    return Scope.from_mapping({key: value for key, value in values.items() if value})


RequestedScope = Annotated[Scope, Depends(get_requested_scope)]


def read_scope(
    principal: CurrentPrincipal,
    context: Context,
    requested: RequestedScope,
) -> Scope:
    """The second RBAC enforcement point for read routes.

    Returns the requested scope narrowed to what the principal may see, so a
    handler physically cannot return out-of-scope rows.
    """
    return context.authorizer.effective_scope(principal, "read", requested)


ReadScope = Annotated[Scope, Depends(read_scope)]


@dataclass(frozen=True)
class Pagination:
    """Validated offset pagination for collection endpoints."""

    offset: int = 0
    limit: int = 100

    def to_dict(self, total: int) -> dict[str, int | None]:
        """Serialize page metadata without exposing implementation details."""
        next_offset = self.offset + self.limit
        return {
            "offset": self.offset,
            "limit": self.limit,
            "total": total,
            "next_offset": next_offset if next_offset < total else None,
        }


def get_pagination(
    offset: int = Query(0, ge=0, description="Zero-based offset into the collection"),
    limit: int = Query(100, ge=1, le=500, description="Maximum rows to return"),
) -> Pagination:
    """Parse the common page controls exposed on every collection route."""
    return Pagination(offset=offset, limit=limit)


Page = Annotated[Pagination, Depends(get_pagination)]


def require_operate(principal: CurrentPrincipal, context: Context) -> Principal:
    context.authorizer.require(principal, "operate")
    return principal


def require_write(principal: CurrentPrincipal, context: Context) -> Principal:
    context.authorizer.require(principal, "write")
    return principal


OperatePrincipal = Annotated[Principal, Depends(require_operate)]
WritePrincipal = Annotated[Principal, Depends(require_write)]
