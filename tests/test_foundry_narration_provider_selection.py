import urllib.error

from api.routers.copilot import (
    _canonical_synthesis_agent,
    investigate_canonical,
    router,
)
from operations.foundry_agent import (
    FoundryAgentError,
    FoundryCircuitOpenError,
    FoundryCoordinatorSynthesisAgent,
    FoundryResponseContractError,
)
from operations.orchestration_service import _narration_failure_details


class _Context:
    def __init__(self) -> None:
        self.coordinator = object()
        self.executive = object()
        self.specialist_requests: list[str] = []

    def foundry_agent(self):
        return self.coordinator

    def specialist_agent(self, agent_id: str):
        self.specialist_requests.append(agent_id)
        return self.executive


def test_canonical_synthesis_selects_dedicated_executive_provider() -> None:
    context = _Context()

    narrator = _canonical_synthesis_agent(context)

    assert isinstance(narrator, FoundryCoordinatorSynthesisAgent)
    assert narrator.agent is context.executive
    assert narrator.agent is not context.coordinator
    assert context.specialist_requests == ["executive_summary"]


def test_canonical_investigation_route_keeps_its_endpoint() -> None:
    route = next(
        route
        for route in router.routes
        if getattr(route, "path", "") == "/api/v1/copilot/investigations"
    )

    assert route.endpoint is investigate_canonical


def test_provider_failure_diagnostics_use_only_controlled_categories() -> None:
    http_error = urllib.error.HTTPError(
        "https://redacted.invalid", 401, "sensitive provider text", {}, None
    )
    wrapped = FoundryAgentError("must never become a telemetry value")
    wrapped.__cause__ = http_error

    assert _narration_failure_details(wrapped) == (
        "http_error",
        "authorization",
    )
    assert _narration_failure_details(FoundryCircuitOpenError("sensitive")) == (
        "foundry_circuit_open",
        "circuit_open",
    )
    assert _narration_failure_details(FoundryResponseContractError("sensitive")) == (
        "contract_error",
        "response_contract",
    )
