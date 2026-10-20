"""Offline provider selection and production ownership contracts."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ontology_discovery import runtime
from ontology_discovery.planner_capabilities import (
    PlannerSelection,
    UnsupportedPlannerCapability,
    provider_receipt,
    select_planner,
)


def test_native_unsupported_denies_before_transport() -> None:
    transport = AsyncMock()
    with pytest.raises(UnsupportedPlannerCapability) as failure:
        select_planner(requested_provider="native")
        asyncio.run(transport({}))
    assert failure.value.reason_code == "native_public_operation_unavailable"
    assert failure.value.reason_codes == (
        "native_public_operation_unavailable",
        "native_unattended_identity_unsupported",
        "native_structured_output_unavailable",
    )
    transport.assert_not_called()
    assert "insufficient_evidence" not in str(failure.value)


def test_default_foundry_and_explicit_fallback_provenance() -> None:
    default = select_planner()
    assert default.requested_provider == default.selected_provider == "foundry"
    assert default.fallback_reason is None
    fallback = select_planner(
        requested_provider="native", allow_foundry_fallback=True,
        execution_class="simulated",
    )
    assert fallback.requested_provider == "native"
    assert fallback.selected_provider == "foundry"
    assert fallback.fallback_reason == "native_public_operation_unavailable"
    assert fallback.execution_class == "simulated"


def _environment(tmp_path: Path) -> dict[str, str]:
    return {
        "AIOPS_ONTOLOGY_ENVIRONMENT": "validation",
        "AIOPS_CONNECTION_HOME": str(tmp_path / "connections"),
        "AIOPS_ONTOLOGY_COMMAND_HOME": str(tmp_path / "commands"),
        "AIOPS_ONTOLOGY_STATE_HOME": str(tmp_path / "state"),
        "AIOPS_ONTOLOGY_DISPATCH_HOME": str(tmp_path / "dispatch"),
        "FOUNDRY_PROJECT_ENDPOINT": "https://example.services.ai.azure.com/api/projects/p",
        "FOUNDRY_ONTOLOGY_AGENT_NAME": "ontology-curator",
        "FOUNDRY_ONTOLOGY_AGENT_VERSION": "7",
        "AIOPS_CONFIG_PATH": str(tmp_path / "unused.yaml"),
    }


@pytest.mark.parametrize("closeable", [False, True])
def test_composition_injection_is_external_and_keeps_environment_requirements(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, closeable: bool,
) -> None:
    class External:
        async def propose(self, run, evidence):
            raise AssertionError("composition must not dispatch")

    external = External()
    close = AsyncMock()
    if closeable:
        external.aclose = close
    monkeypatch.setattr(runtime.ConnectorConfig, "load", lambda path: object())
    built = runtime.build_production_runtime(
        environ=_environment(tmp_path), owner="offline", curator=external,
    )
    assert built.processor.curator is external
    assert built.processor.policy.shadow_mode is True
    asyncio.run(built.aclose())
    close.assert_not_called()
    invalid = _environment(tmp_path)
    del invalid["FOUNDRY_ONTOLOGY_AGENT_VERSION"]
    with pytest.raises(ValueError, match="FOUNDRY_ONTOLOGY_AGENT_VERSION"):
        runtime.build_production_runtime(
            environ=invalid, owner="offline", curator=external,
        )


def test_composition_closes_owned_version_pinned_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    default = AsyncMock()
    factory = pytest.MonkeyPatch()
    calls = []

    def construct(**kwargs):
        calls.append(kwargs)
        return default

    monkeypatch.setattr(runtime.ConnectorConfig, "load", lambda path: object())
    factory.setattr(runtime, "OntologyCurator", construct)
    try:
        built = runtime.build_production_runtime(
            environ=_environment(tmp_path), owner="offline",
        )
        asyncio.run(built.aclose())
    finally:
        factory.undo()
    assert calls[0]["agent_version"] == "7"
    default.aclose.assert_awaited_once()


def test_native_selection_cannot_be_forged_at_composition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runtime.ConnectorConfig, "load", lambda path: object())
    external = AsyncMock()
    forged = PlannerSelection(
        requested_provider="native", selected_provider="native",
        fallback_reason=None, execution_class="live",
    )
    with pytest.raises(UnsupportedPlannerCapability):
        runtime.build_production_runtime(
            environ=_environment(tmp_path), owner="offline",
            curator=external, planner_selection=forged,
        )
    external.propose.assert_not_called()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"requested_provider": "untrusted-secret-provider"},
        {"requested_provider": "native", "allow_foundry_fallback": "true"},
        {"execution_class": "native-success"},
    ],
)
def test_invalid_server_selection_is_closed_and_sanitized(kwargs) -> None:
    with pytest.raises(ValueError) as failure:
        select_planner(**kwargs)
    assert "untrusted-secret-provider" not in str(failure.value)


def test_fallback_requires_closed_reason_at_invocation() -> None:
    forged = PlannerSelection(
        requested_provider="native", selected_provider="foundry",
        fallback_reason=None, execution_class="imported",
    )
    with pytest.raises(ValueError, match="invalid_planner_fallback"):
        forged.require_supported()


@pytest.mark.parametrize("model", ["gpt-4.1", "", None, "secret\nvalue", "x" * 129])
def test_receipt_binds_only_bounded_model_metadata(model) -> None:
    curator = SimpleNamespace(last_attempt={"model": model})
    receipt = provider_receipt(
        selection=select_planner(), curator=curator, result={"proposals": []},
    )
    if model == "gpt-4.1":
        assert receipt["model"] == model
        curator.last_attempt["model"] = "gpt-other"
        assert receipt["model"] == model
    else:
        assert "model" not in receipt
