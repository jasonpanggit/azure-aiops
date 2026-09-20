"""Shared test setup for routes that intentionally exercise authorized canary."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from operations import copilot_canary_authorization, maf_orchestrator
from operations.copilot_canary_authorization import ValidatedCanaryAuthorization
from operations.maf_orchestrator import CopilotRolloutDecision
from operations.orchestration_service import OrchestrationService


def enable_authorized_canary(
    monkeypatch,
    *,
    canonical: bool = True,
    percentage: int = 10,
) -> None:
    """Install immutable test authority and deterministic bucket selection."""

    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "canary")
    monkeypatch.setenv("AIOPS_COPILOT_CANARY_PERCENTAGE", str(percentage))
    monkeypatch.setenv("AIOPS_COPILOT_ROLLBACK_MODE", "compatibility")
    monkeypatch.setenv("AIOPS_AGENT_ORCHESTRATION_MODE", "maf")
    authority = ValidatedCanaryAuthorization(
        authorization_id="test-reviewed-canary",
        manifest_sha256="a" * 64,
        source_revision="b" * 40,
        reviewed_tree_sha256="c" * 64,
        percentage=percentage,
        expires_at=datetime(2099, 1, 1, tzinfo=UTC),
    )
    monkeypatch.setattr(
        copilot_canary_authorization,
        "validate_canary_authorization",
        lambda **_kwargs: authority,
    )
    monkeypatch.setattr(
        maf_orchestrator,
        "require_canary_authorization_if_requested",
        lambda: authority,
    )
    monkeypatch.setattr(
        maf_orchestrator,
        "_canary_bucket",
        lambda _stable_key: 0 if canonical else 99,
    )


def rollout_decision_for_test(
    *, principal_subject: str = "operator-a"
) -> CopilotRolloutDecision:
    """Create a canonical canary decision for route-bound unit tests."""

    return CopilotRolloutDecision(
        mode="canary",
        canonical_enabled=True,
        shadow_enabled=False,
        reason="canary_selected",
        canary_bucket=0,
        authorization_id="test-reviewed-canary",
        authorization_manifest_sha256="a" * 64,
        reviewed_tree_sha256="c" * 64,
        stable_key_sha256=hashlib.sha256(
            principal_subject.encode("utf-8")
        ).hexdigest(),
        authorization_expires_at=datetime(2099, 1, 1, tzinfo=UTC),
    )


def canonical_authorizer_for_test(
    *,
    expected_principal: str | None = None,
):
    """Return a test-only validator injected at service construction."""

    def authorize(
        *,
        request: Any,
        principal_subject: str,
        stable_key: str,
        selection_snapshot: Any = None,
        canonical_selection_snapshot: Any = None,
    ) -> None:
        assert request is not None
        assert stable_key == principal_subject
        if expected_principal is not None:
            assert principal_subject == expected_principal

    return authorize


class AuthorizedOrchestrationService(OrchestrationService):
    """Test service with an explicitly injected canonical authorizer."""

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault(
            "canonical_authorizer",
            canonical_authorizer_for_test(),
        )
        super().__init__(**kwargs)


def route_authority_for_test(
    request,
    *,
    principal_subject: str = "operator-a",
    selection_snapshot=None,
    canonical_selection_snapshot=None,
):
    """Return no caller capability; authorization is injected into the service."""

    return
