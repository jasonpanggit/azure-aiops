"""Regression tests for the non-authoritative Data Agent boundary."""

from __future__ import annotations

import inspect

from fabric_pipelines import ontology_pipeline
from fabric_pipelines import relationship_suggestions_contract as suggestion_contract


def test_authoritative_pipeline_has_no_data_agent_merge_input() -> None:
    parameters = inspect.signature(ontology_pipeline.run).parameters
    assert "approved_suggestion_rows" not in parameters
    assert not hasattr(ontology_pipeline, "merge_approved_relationship_suggestions")


def test_suggestion_contract_has_no_authoritative_conversion() -> None:
    assert not hasattr(
        suggestion_contract,
        "accepted_suggestion_to_relationship_row",
    )
    assert not hasattr(suggestion_contract, "ACCEPTED_SUGGESTION_STATUS")
    assert not hasattr(
        suggestion_contract,
        "APPROVED_SUGGESTION_RELATIONSHIP_SOURCE",
    )
