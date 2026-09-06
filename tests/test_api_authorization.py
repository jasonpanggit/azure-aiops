"""Authorization separation for Exposure review and remediation mutations."""

from __future__ import annotations

from typing import get_type_hints

from api.dependencies import (
    ApprovePrincipal,
    OperatePrincipal,
    ReadScope,
    WritePrincipal,
)
from api.routers.operations import (
    read_remediation_decisions,
    record_remediation_decision,
)
from api.routers.remediation import (
    cancel_execution,
    create_exposure_handoff,
    execute_plan,
    exposure_handoffs,
    execution_diagnostics,
    retry_execution,
    supersede_execution,
)
from api.routers.vulnerability import (
    create_risk_exception,
    list_risk_exceptions,
)


def _hint(callable_, name: str):
    return get_type_hints(callable_, include_extras=True)[name]


def test_exposure_and_remediation_routes_keep_distinct_claims() -> None:
    assert _hint(exposure_handoffs, "scope") == ReadScope
    assert _hint(list_risk_exceptions, "scope") == ReadScope
    assert _hint(read_remediation_decisions, "scope") == ReadScope

    assert _hint(create_exposure_handoff, "principal") == WritePrincipal
    assert _hint(create_risk_exception, "principal") == WritePrincipal
    assert _hint(record_remediation_decision, "principal") == ApprovePrincipal

    for route in (
        execute_plan,
        retry_execution,
        cancel_execution,
        supersede_execution,
        execution_diagnostics,
    ):
        assert _hint(route, "principal") == OperatePrincipal
