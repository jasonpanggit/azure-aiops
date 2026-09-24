import pytest

from fabric.config import FabricRuntimeConfig
from ontology_discovery.semantic_evolution import (
    AdditiveStructuralProposal,
    GenerationPinnedProfile,
    SafeMetadataProposal,
    SemanticEvidence,
    SemanticEvolutionBatch,
)


def test_generation_pinning_and_unsafe_metadata_rejection() -> None:
    profile = GenerationPinnedProfile(
        profile_id="p",
        source_generation_id="g1",
        semantic_model_name="m",
        tables=("gold_exposure_facts",),
        profile_version="1",
    )
    with pytest.raises(ValueError):
        SafeMetadataProposal(
            proposal_id="x", source_generation_id="g1", table="t",
            field="identity", value="x", evidence_ids=("e",)
        )
    with pytest.raises(ValueError):
        SemanticEvolutionBatch(
            profile=profile,
            evidence=(SemanticEvidence(
                evidence_id="e", source_generation_id="g2", table="gold_exposure_facts",
                kind="description", details="x"
            ),),
        )


def test_structural_contract_rejects_scope_changes() -> None:
    with pytest.raises(ValueError):
        AdditiveStructuralProposal(
            proposal_id="x", source_generation_id="g1", kind="relationship",
            table="gold_exposure_facts", definition={"scope": "all"},
            evidence_ids=("e",),
        )


def test_runtime_configuration_is_default_off_and_strict(tmp_path) -> None:
    path = tmp_path / "fabric.yaml"
    path.write_text(
        """
fabric:
  workspace_name: workspace
  lakehouse_name: lakehouse
"""
    )
    config = FabricRuntimeConfig.load(path)
    assert config.ops_semantic_evolution.enabled is False

    path.write_text(
        """
fabric:
  workspace_name: workspace
  lakehouse_name: lakehouse
  ops_semantic_evolution:
    enabled: true
    adapter: unsupported
"""
    )
    with pytest.raises(ValueError, match="adapter"):
        FabricRuntimeConfig.load(path)
