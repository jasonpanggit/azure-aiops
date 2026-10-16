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

from intelligence.governance.retained_exports import RetainedAuditExportStore
from intelligence.inventory.exports import InventoryExportStore
from network.history import NetworkHistoryStore
from network.intents import NetworkIntentStore
from onboarding.service import SubscriptionOnboardingService
from operations.overview_history import OverviewHistoryStore
from operations.predeploy_history import PredeployHistoryStore
from operations.resource_health_history import ResourceHealthHistoryStore
from operations.saved_views import SavedViewStore
from operations.service_portfolio import ServicePortfolioStore
from operations.service_reliability import ServiceObjectiveStore
from operations.specialist_manifest import LOCKED_SPECIALIST_IDS
from semantic.semantic_engine import SemanticEngine
from semantic.twin_history import TwinHistoryStore
from situations.deadlines import SituationDeadlineStore
from situations.notes import SituationNotesStore

from .auth import Authenticator
from .errors import ApiError, ErrorCode
from .providers import ProviderRuntime, ProviderUnavailableError
from .rbac import Authorizer, Principal
from .scope import Scope, subscription_ids_for_scope
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
    # Request-scoped governance reader for a selected connection. It captures
    # one immutable ontology generation before reading any export rows.
    governance_generation_provider: Callable[[Scope], Any] | None = None
    # Enterprise settings are a user-submitted mutation rather than a snapshot
    # projection, so like risk exceptions they use a direct store handle.
    settings_store: Any | None = None
    retained_audit_export_store: RetainedAuditExportStore | None = None
    compliance_policy_store: Any | None = None
    situation_notes_store: SituationNotesStore | None = None
    situation_deadline_store: SituationDeadlineStore | None = None
    execution_record_reader: Callable[[], list[dict[str, Any]]] | None = None
    inventory_export_store: InventoryExportStore | None = None
    overview_history_store: OverviewHistoryStore | None = None
    service_portfolio_store: ServicePortfolioStore | None = None
    service_objective_store: ServiceObjectiveStore | None = None
    service_request_metrics: Callable[[str, int, str], dict[str, Any]] | None = None
    resource_health_history_store: ResourceHealthHistoryStore | None = None
    network_intent_store: NetworkIntentStore | None = None
    network_history_store: NetworkHistoryStore | None = None
    saved_view_store: SavedViewStore | None = None
    predeploy_history_store: PredeployHistoryStore | None = None
    twin_history_store: TwinHistoryStore | None = None
    # The network design policy (rule-based, UI-editable) is likewise a
    # user-submitted mutation, not a snapshot projection, and is applied to
    # every rebuilt NetworkIntelligenceService via the same store handle.
    network_policy_store: Any | None = None
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
    exposure_query_provider: Callable[[], Any] | None = None
    # Stale Patch Priorities reads may enqueue one connection-scoped refresh.
    # The coordinator only schedules background work; request handlers never
    # run acquisition or publication inline.
    exposure_patch_refresh_provider: Callable[[], Any] | None = None
    exposure_read_port_provider: Callable[[], Any] | None = None
    exposure_ontology_provider: Callable[[Scope], Any] | None = None
    exposure_remediation_provider: Callable[[], Any] | None = None
    fabric_iq_provider: Callable[[], Any] | None = None
    # The autonomous background verification coordinator (Phase 03.4,
    # Recommendation 3) is a provider/callable -- not a pinned instance --
    # because it is only ever invoked once at app startup to obtain the one
    # long-lived coordinator instance the background thread drives; a test
    # context built without this provider simply never starts that thread
    # (mirrors provider_runtime's own optional-thread-start guard).
    verification_coordinator_provider: Callable[[], Any] | None = None
    # Scope-enforced durable ontology lifecycle facade. The API-facing value
    # intentionally has no DatasetStore publisher adapter or credential.
    ontology_discovery_provider: Callable[[], Any] | None = None

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
        if agent_id in LOCKED_SPECIALIST_IDS:
            return self.resolve_provider(f"{agent_id}_agent", optional=True)
        return None

    def semantic(self) -> SemanticEngine:
        return self.resolve_provider("semantic")

    def governance_snapshot(
        self,
        scope: Scope,
        *,
        require_generation: bool = True,
    ) -> Any:
        """Resolve one generation-pinned governance snapshot within ``scope``."""
        provider = (
            self.governance_generation_provider(scope)
            if self.governance_generation_provider is not None
            else self.resolve_provider("governance", optional=True)
        )
        if provider is None:
            raise ApiError(
                ErrorCode.PROVIDER_UNAVAILABLE,
                "Governance data is unavailable because no connection has synced yet",
                {"capability": "governance", "provider_state": "unavailable"},
            )
        snapshot = provider.scoped(scope)
        if require_generation and not snapshot.generation_available:
            raise ApiError(
                ErrorCode.PROVIDER_UNAVAILABLE,
                "Governance data is unavailable because no active connection has synced yet",
                {"capability": "governance", "provider_state": "unavailable"},
            )
        return snapshot

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


def live_subscription_ids(
    context: ApiContext,
    scope: Scope,
    *,
    default_all: bool = False,
) -> list[str]:
    """Map a page's authorized scope to active onboarded Azure connections."""
    if (
        not default_all
        and not scope.values("subscription")
        and not scope.values("subscription_connection")
    ):
        return []
    return subscription_ids_for_scope(
        scope,
        context.onboarding.registry.list(include_disabled=False),
        default_all=default_all,
    )


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


def require_approve(principal: CurrentPrincipal, context: Context) -> Principal:
    context.authorizer.require(principal, "approve")
    return principal


def require_write(principal: CurrentPrincipal, context: Context) -> Principal:
    context.authorizer.require(principal, "write")
    return principal


def require_maintain_ontology(
    principal: CurrentPrincipal, context: Context
) -> Principal:
    context.authorizer.require(principal, "maintain_ontology")
    return principal


OperatePrincipal = Annotated[Principal, Depends(require_operate)]
ApprovePrincipal = Annotated[Principal, Depends(require_approve)]
WritePrincipal = Annotated[Principal, Depends(require_write)]
MaintainOntologyPrincipal = Annotated[
    Principal, Depends(require_maintain_ontology)
]
