"""Deterministic pre-I/O policy for untrusted orchestration candidates."""

from __future__ import annotations

from dataclasses import dataclass

from api.scope import Scope
from operations.maf_orchestrator import reviewed_specialists_for_page
from operations.mcp_server import REVIEWED_TOOLS, validate_tool_arguments
from operations.orchestration_contract import (
    COVERAGE_CITATION_ID,
    CandidatePlan,
    InvestigationRequest,
)
from operations.specialist_manifest import (
    SpecialistManifest,
    load_specialist_manifest,
)
from operations.tools import TOOL_REGISTRY


class PolicyViolation(ValueError):
    """A reason-coded orchestration authorization rejection."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        super().__init__(f"{code}: {detail}" if detail else code)


@dataclass(frozen=True)
class PolicyLimits:
    """Hard limits applied before the first governed tool call."""

    max_specialists: int = 4
    max_tool_calls: int = 8
    max_dependency_depth: int = 4
    max_estimated_tokens: int = 16_000
    max_wall_seconds: float = 30


def _scope_within(requested: Scope, effective: Scope) -> bool:
    if effective.is_unrestricted():
        return True
    for dimension, effective_values in effective.dimensions.items():
        requested_values = requested.values(dimension)
        if not requested_values or not requested_values <= effective_values:
            return False
    return True


class OrchestrationPolicy:
    """Validate a complete candidate before execution can begin."""

    def __init__(
        self,
        *,
        manifest: SpecialistManifest | None = None,
        limits: PolicyLimits | None = None,
    ) -> None:
        self.manifest = manifest or load_specialist_manifest()
        self.limits = limits or PolicyLimits()

    def validate_request(
        self,
        request: InvestigationRequest,
        effective_scope: Scope,
    ) -> Scope:
        """Validate and return the caller-requested scope."""

        requested = Scope.from_mapping(request.requested_scope)
        if not requested.is_satisfiable() or not _scope_within(requested, effective_scope):
            raise PolicyViolation("scope_widening")
        return requested

    def validate(
        self,
        *,
        request: InvestigationRequest,
        candidate: CandidatePlan,
        effective_scope: Scope,
    ) -> CandidatePlan:
        """Validate specialist, grant, scope, budget, DAG, and citations."""

        self.validate_request(request, effective_scope)
        if candidate.mutation_intent or any(
            call.mutation
            for step in candidate.steps
            for call in step.tool_calls
        ):
            raise PolicyViolation("mutation_forbidden")
        if len(candidate.steps) > self.limits.max_specialists:
            raise PolicyViolation("budget_exceeded", "specialist count")
        tool_count = sum(len(step.tool_calls) for step in candidate.steps)
        if (
            tool_count > self.limits.max_tool_calls
            or candidate.estimated_tokens > self.limits.max_estimated_tokens
            or candidate.max_wall_seconds > self.limits.max_wall_seconds
        ):
            raise PolicyViolation("budget_exceeded")

        step_ids = [step.specialist_id for step in candidate.steps]
        if len(step_ids) != len(set(step_ids)):
            raise PolicyViolation("duplicate_specialist")
        evidence_ids = {
            COVERAGE_CITATION_ID,
            *(item.evidence_id for item in request.snapshot.evidence),
        }
        reviewed_specialists = set(
            reviewed_specialists_for_page(
                request.snapshot.page_kind,
                self.manifest.page_mapping_projection(),
            )
        )

        for step in candidate.steps:
            try:
                specialist = self.manifest.require(step.specialist_id)
            except ValueError as exc:
                raise PolicyViolation("unknown_specialist", step.specialist_id) from exc
            if step.specialist_id not in reviewed_specialists:
                raise PolicyViolation("page_not_granted", request.snapshot.page_kind)
            if not specialist.read_only:
                raise PolicyViolation("mutation_forbidden")
            page_tools = specialist.operations_tools_for_page(
                request.snapshot.page_kind
            )
            for dependency in step.depends_on:
                if dependency not in step_ids:
                    raise PolicyViolation("unknown_dependency", dependency)
            for call in step.tool_calls:
                if call.tool not in TOOL_REGISTRY or call.tool not in REVIEWED_TOOLS:
                    raise PolicyViolation("unknown_tool", call.tool)
                if call.tool not in specialist.operations_mcp_tools:
                    raise PolicyViolation("tool_not_granted", call.tool)
                if call.tool not in page_tools:
                    raise PolicyViolation("page_tool_not_granted", call.tool)
                try:
                    validate_tool_arguments(call.tool, call.arguments)
                except ValueError as exc:
                    raise PolicyViolation("invalid_arguments", call.tool) from exc
                if call.tool == "incidents" and call.arguments.get("scenario"):
                    from operations.incident_scenarios import validate_snapshot_binding

                    try:
                        validate_snapshot_binding(call.arguments, request.snapshot)
                    except ValueError as exc:
                        raise PolicyViolation("invalid_arguments", str(exc)) from exc
                if (
                    specialist.output_contract.requires_citations
                    and not call.citation_ids
                ):
                    raise PolicyViolation("citation_required", call.tool)
                if not set(call.citation_ids) <= evidence_ids:
                    raise PolicyViolation("foreign_citation", call.tool)

        self._validate_dag(candidate)
        return candidate

    def _validate_dag(self, candidate: CandidatePlan) -> None:
        dependencies = {
            step.specialist_id: tuple(step.depends_on)
            for step in candidate.steps
        }
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str, depth: int) -> None:
            if depth > self.limits.max_dependency_depth:
                raise PolicyViolation("budget_exceeded", "dependency depth")
            if node in visiting:
                raise PolicyViolation("dependency_cycle")
            if node in visited:
                return
            visiting.add(node)
            for dependency in dependencies[node]:
                visit(dependency, depth + 1)
            visiting.remove(node)
            visited.add(node)

        for specialist_id in dependencies:
            visit(specialist_id, 1)


__all__ = ["OrchestrationPolicy", "PolicyLimits", "PolicyViolation"]
