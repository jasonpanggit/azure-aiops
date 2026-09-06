"""Exposure handoff, risk-exception, and immutable-audit safety contracts."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
from typing import Any

import pytest

from api.app import create_app
from api.dependencies import ApiContext
from api.errors import ApiError
from api.models import ExposureReviewHandoffRequest, RiskExceptionCreateRequest
from api.rbac import Authorizer
from api.routers.remediation import create_exposure_handoff
from api.routers.vulnerability import create_risk_exception
from api.scope import Scope
from api.telemetry import ApiTelemetry
from intelligence.governance.audit import (
    AppendOnlyExposureAuditLog,
    ExposureAuditEvent,
)
from intelligence.remediation.action_catalog import (
    EXECUTABLE_ACTION_IDS,
    GOVERNED_REMEDIATION_ACTIONS,
)
from intelligence.remediation.defender_correlation import (
    DefenderRemediationCorrelator,
)
from onboarding.service import SubscriptionOnboardingService

EXPECTED_EXECUTABLE_ACTION_IDS = {
    "controlled-patch-recovery",
    "defender-enable-servers-plan-p1",
    "defender-enable-storage-plan-v2",
}


class _ExposureReadPort:
    def __init__(
        self,
        findings: list[dict[str, Any]],
        *,
        completeness: str = "complete",
        freshness: str = "current",
    ) -> None:
        self._findings = deepcopy(findings)
        self._completeness = completeness
        self._freshness = freshness

    def list_exposures(
        self,
        scope: Scope,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> dict[str, Any]:
        assert hasattr(scope, "matches")
        rows = deepcopy(self._findings[offset : offset + limit])
        return {
            "findings": rows,
            "read_model_generation_id": "generation-handoff-1",
            "returned_count": len(rows),
            "total_count": len(self._findings),
            "completeness": {
                "state": self._completeness,
                "represented_connections": 1,
                "expected_connections": 1,
            },
            "freshness": {
                "state": self._freshness,
                "as_of": "2026-09-06T08:00:00Z",
                "source_family": "defender",
                "threshold_seconds": 21_600,
            },
            "source_attribution": [
                {
                    "source_family": "defender",
                    "finding_count": len(rows),
                }
            ],
        }


def _server_finding() -> dict[str, Any]:
    return {
        "exposure_id": "exposure:server:1",
        "target_id": "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
        "target_kind": "server",
        "weakness_id": "CVE-2026-1001",
        "source_families": ["aum", "defender"],
        "completeness": "complete",
        "governed_action_id": "controlled-patch-recovery",
        "execution_eligible": True,
    }


def _container_finding(
    *,
    workload_state: str = "observed-exact-digest",
    completeness: str = "complete",
) -> dict[str, Any]:
    return {
        "exposure_id": "exposure:image:1",
        "target_id": "sha256:" + ("a" * 64),
        "target_kind": "container_image",
        "weakness_id": "CVE-2026-2001",
        "source_families": ["defender"],
        "completeness": completeness,
        "registry_id": "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.ContainerRegistry/registries/acr1",
        "image_repository": "platform/api",
        "workload_state": workload_state,
        "application_id": "application:checkout",
        "business_service_id": "service:payments",
        # Even a malicious/future row cannot turn a container into a server
        # execution by borrowing one of the three existing ids.
        "governed_action_id": "controlled-patch-recovery",
        "execution_eligible": True,
    }


def test_executable_registry_remains_exact_and_has_no_container_action() -> None:
    assert set(EXECUTABLE_ACTION_IDS) == EXPECTED_EXECUTABLE_ACTION_IDS
    assert {
        action_id
        for action_id, action in GOVERNED_REMEDIATION_ACTIONS.items()
        if action.executable
    } == EXPECTED_EXECUTABLE_ACTION_IDS
    assert all(
        "container" not in action_id.casefold()
        and "image" not in action_id.casefold()
        and "deployment" not in action_id.casefold()
        for action_id in GOVERNED_REMEDIATION_ACTIONS
    )


def test_server_execution_and_container_handoff_dispatch_are_separate() -> None:
    correlator = DefenderRemediationCorrelator.from_exposure_read_port(
        _ExposureReadPort([_server_finding(), _container_finding()])
    )

    cases = correlator.exposure_cases(Scope.unrestricted())
    server = next(row for row in cases if row["target_kind"] == "server")
    container = next(
        row for row in cases if row["target_kind"] == "container_image"
    )

    assert server["outcome"] == "governed_action"
    assert server["action_id"] == "controlled-patch-recovery"
    assert server["direct_execution_supported"] is True
    assert container["outcome"] == "review_handoff"
    assert container["action_id"] == ""
    assert container["direct_execution_supported"] is False
    assert container["read_model_generation_id"] == "generation-handoff-1"
    assert container["evidence_refs"] == [
        {
            "exposure_id": "exposure:image:1",
            "generation": "generation-handoff-1",
            "source_families": ["defender"],
        }
    ]
    assert container["freshness"]["threshold_seconds"] == 21_600
    assert container["review_handoff"]["registry_id"].endswith("/acr1")
    assert container["review_handoff"]["application_id"] == "application:checkout"
    assert container["review_handoff"]["business_service_id"] == "service:payments"
    assert container["review_handoff"]["safe_blast_radius_known"] is True


@pytest.mark.parametrize(
    ("completeness", "freshness", "expected_reason"),
    [
        ("partial", "current", "evidence_incomplete"),
        ("complete", "stale", "evidence_stale"),
    ],
)
def test_partial_or_stale_evidence_blocks_container_handoff(
    completeness: str,
    freshness: str,
    expected_reason: str,
) -> None:
    correlator = DefenderRemediationCorrelator.from_exposure_read_port(
        _ExposureReadPort(
            [_container_finding(completeness=completeness)],
            completeness=completeness,
            freshness=freshness,
        )
    )

    case = correlator.exposure_cases(Scope.unrestricted())[0]

    assert case["outcome"] == "no_safe_action"
    assert case["outcome_reason_code"] == expected_reason
    assert case["direct_execution_supported"] is False
    assert case["review_handoff"]["application_id"] == ""
    assert case["review_handoff"]["business_service_id"] == ""
    assert case["review_handoff"]["safe_blast_radius_known"] is False


def test_unknown_deployment_evidence_never_claims_application_or_blast_radius() -> None:
    correlator = DefenderRemediationCorrelator.from_exposure_read_port(
        _ExposureReadPort([_container_finding(workload_state="unknown")])
    )

    case = correlator.exposure_cases(Scope.unrestricted())[0]

    assert case["outcome"] == "no_safe_action"
    assert case["outcome_reason_code"] == "deployment_evidence_unknown"
    assert case["review_handoff"]["application_id"] == ""
    assert case["review_handoff"]["business_service_id"] == ""
    assert case["review_handoff"]["safe_blast_radius_known"] is False


def test_container_correlation_invokes_no_mutation_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def forbidden(*_args: Any, **_kwargs: Any) -> None:
        calls.append("mutation")
        raise AssertionError("container handoff invoked a mutation adapter")

    for name in (
        "_patch_execution_adapter",
        "_defender_configuration_adapter",
        "_container_image_builder",
        "_container_workload_mutator",
        "_container_deployment_client",
    ):
        monkeypatch.setattr("api.runtime." + name, forbidden, raising=False)

    correlator = DefenderRemediationCorrelator.from_exposure_read_port(
        _ExposureReadPort([_container_finding()])
    )
    case = correlator.exposure_cases(Scope.unrestricted())[0]

    assert case["outcome"] == "review_handoff"
    assert calls == []


def test_remediation_exposure_handoff_read_route_is_additive(tmp_path) -> None:
    context = ApiContext(
        onboarding=SubscriptionOnboardingService(tmp_path / "aiops"),
        authenticator=object(),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
    )
    paths = create_app(context).openapi()["paths"]

    assert "get" in paths["/api/v1/remediation/exposure-handoffs"]
    assert "post" in paths["/api/v1/remediation-plans/{plan_id}/decisions"]
    assert "/api/v1/remediation/plans/{plan_id}/decisions" not in paths


def test_exposure_audit_is_append_only_and_rejects_secret_fields() -> None:
    audit = AppendOnlyExposureAuditLog()
    event = ExposureAuditEvent(
        event_id="audit:event:1",
        event_type="exposure.review_handoff_created",
        subject="security-admin@example.com",
        tenant_id="tenant-a",
        connection_ids=("connection-a",),
        scope={"subscription": ["sub-a"]},
        target={
            "target_kind": "container_image",
            "target_id": "sha256:" + ("a" * 64),
        },
        generation="generation-handoff-1",
        evidence_refs=(
            {
                "exposure_id": "exposure:image:1",
                "generation": "generation-handoff-1",
            },
        ),
        decision="create_review_handoff",
        reason="Platform owner review required",
        result="recorded",
        timestamp="2026-09-06T08:00:00+00:00",
    )

    audit.append(event)
    audit.append(event)
    assert audit.rows() == [event.to_dict()]

    with pytest.raises(ValueError, match="immutable"):
        audit.append(
            ExposureAuditEvent(
                **{
                    **event.to_dict(),
                    "result": "changed",
                }
            )
        )
    with pytest.raises(ValueError, match="sensitive"):
        ExposureAuditEvent(
            **{
                **event.to_dict(),
                "event_id": "audit:event:secret",
                "target": {"client_secret": "must-not-be-recorded"},
            }
        )


def test_review_handoff_creation_is_evidence_bound_and_has_no_execution_transition() -> None:
    correlator = DefenderRemediationCorrelator.from_exposure_read_port(
        _ExposureReadPort([_container_finding()])
    )
    audit_events: list[dict[str, Any]] = []
    principal = type(
        "Principal",
        (),
        {
            "subject": "security-admin@example.com",
            "grants": (),
        },
    )()
    context = type(
        "Context",
        (),
        {
            "authorizer": type(
                "Authorizer",
                (),
                {
                    "effective_scope": lambda self, caller, action, requested=None: (
                        Scope.unrestricted()
                    )
                },
            )(),
            "exposure_remediation_provider": lambda self: correlator,
            "exposure_audit_append": lambda self, event: audit_events.append(
                event.to_dict()
            ),
        },
    )()

    response = create_exposure_handoff(
        ExposureReviewHandoffRequest(
            exposure_id="exposure:image:1",
            reason="Route to the owning platform team",
        ),
        context,
        principal,
    )

    assert response["data"]["outcome"] == "review_handoff"
    assert response["data"]["execution_transition"] is False
    assert response["data"]["direct_execution_supported"] is False
    assert len(audit_events) == 1
    event = audit_events[0]
    assert event["event_type"] == "exposure.review_handoff_created"
    assert event["subject"] == "security-admin@example.com"
    assert event["scope"] == {}
    assert event["target"]["target_kind"] == "container_image"
    assert event["generation"] == "generation-handoff-1"
    assert event["evidence_refs"][0]["exposure_id"] == "exposure:image:1"
    assert event["decision"] == "create_review_handoff"
    assert event["reason"] == "Route to the owning platform team"
    assert event["result"] == "recorded"


def test_audit_append_failure_blocks_review_handoff_with_safe_error() -> None:
    correlator = DefenderRemediationCorrelator.from_exposure_read_port(
        _ExposureReadPort([_container_finding()])
    )

    def fail_audit(_event: ExposureAuditEvent) -> None:
        raise RuntimeError("provider raw secret: super-secret-value")

    context = type(
        "Context",
        (),
        {
            "authorizer": type(
                "Authorizer",
                (),
                {
                    "effective_scope": lambda self, caller, action, requested=None: (
                        Scope.unrestricted()
                    )
                },
            )(),
            "exposure_remediation_provider": lambda self: correlator,
            "exposure_audit_append": fail_audit,
        },
    )()
    principal = type("Principal", (), {"subject": "admin@example.com"})()

    with pytest.raises(ApiError) as exc_info:
        create_exposure_handoff(
            ExposureReviewHandoffRequest(
                exposure_id="exposure:image:1",
                reason="Review required",
            ),
            context,
            principal,
        )

    assert exc_info.value.code.value == "upstream_unavailable"
    assert "super-secret-value" not in str(exc_info.value)


def test_risk_exception_is_evidence_bound_and_audit_precedes_storage() -> None:
    added: list[Any] = []
    audit_events: list[dict[str, Any]] = []
    finding = type(
        "Finding",
        (),
        {
            "cve_id": "CVE-2026-1001",
            "server_id": "server-1",
            "scope_attributes": lambda self: {"subscription": "sub-a"},
        },
    )()
    service = type(
        "Vulnerability",
        (),
        {
            "findings": [finding],
            "freshness": "2026-09-06T08:00:00Z",
            "read_model_generation_id": "generation-risk-1",
        },
    )()
    context = type(
        "Context",
        (),
        {
            "authorizer": type(
                "Authorizer",
                (),
                {
                    "effective_scope": lambda self, caller, action, requested=None: (
                        Scope.unrestricted()
                    )
                },
            )(),
            "hybrid_vulnerability_provider": None,
            "resolve_provider": lambda self, name: service,
            "risk_exception_add": lambda self, exception: added.append(exception),
            "exposure_audit_append": lambda self, event: audit_events.append(
                event.to_dict()
            ),
        },
    )()
    principal = type("Principal", (), {"subject": "admin@example.com"})()

    response = create_risk_exception(
        RiskExceptionCreateRequest(
            cve_id="CVE-2026-1001",
            server_id="server-1",
            reason="Compensating control approved",
            expires_at=(datetime.now(UTC) + timedelta(days=30)).isoformat(),
        ),
        context,
        principal,
    )

    assert len(added) == 1
    assert len(audit_events) == 1
    event = audit_events[0]
    assert event["event_type"] == "exposure.risk_exception_created"
    assert event["subject"] == "admin@example.com"
    assert event["target"] == {
        "target_kind": "server",
        "target_id": "server-1",
        "weakness_id": "CVE-2026-1001",
    }
    assert event["generation"] == "generation-risk-1"
    assert event["reason"] == "Compensating control approved"
    assert response["data"]["evidence_binding"]["generation"] == "generation-risk-1"

    context.exposure_audit_append = lambda _event: (_ for _ in ()).throw(
        RuntimeError("raw provider details")
    )
    with pytest.raises(ApiError):
        create_risk_exception(
            RiskExceptionCreateRequest(
                cve_id="CVE-2026-1001",
                server_id="server-1",
                reason="Must not persist after failed audit",
                expires_at=(datetime.now(UTC) + timedelta(days=1)).isoformat(),
            ),
            context,
            principal,
        )
    assert len(added) == 1


def test_risk_exception_rejects_expired_evidence_window() -> None:
    with pytest.raises(Exception, match="future"):
        create_risk_exception(
            RiskExceptionCreateRequest(
                cve_id="CVE-2026-1001",
                server_id="server-1",
                reason="Already expired",
                expires_at=(datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
            ),
            object(),
            object(),
        )


def test_audit_rows_are_json_safe_and_have_no_raw_provider_error() -> None:
    event = ExposureAuditEvent(
        event_id="audit:event:json",
        event_type="remediation.execution_requested",
        subject="operator@example.com",
        tenant_id="tenant-a",
        connection_ids=("connection-a",),
        scope={"subscription": ["sub-a"]},
        target={"target_kind": "server", "target_id": "server-1"},
        generation="generation-1",
        evidence_refs=({"evidence_id": "evidence-1"},),
        decision="execute",
        reason="approved",
        result="requested",
        timestamp="2026-09-06T08:00:00+00:00",
    )

    rendered = json.dumps(event.to_dict(), sort_keys=True)
    assert "raw_provider_error" not in rendered
    assert "secret" not in rendered.casefold()
