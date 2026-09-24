from pathlib import Path

from ontology_discovery.semantic_evolution import (
    GenerationPinnedProfile,
    SemanticEvolutionBatch,
)
from ontology_discovery.semantic_evolution_pipeline import (
    ProfileArtifactStore,
    SemanticEvolutionPipeline,
)


def test_pipeline_writes_local_artifacts_without_publication(tmp_path: Path) -> None:
    profile = GenerationPinnedProfile(
        profile_id="p", source_generation_id="g1", semantic_model_name="m",
        tables=("gold_exposure_facts",), profile_version="1"
    )
    result = SemanticEvolutionPipeline(ProfileArtifactStore(tmp_path)).run(
        batch=SemanticEvolutionBatch(profile=profile)
    )
    assert result["report"]["source_generation_id"] == "g1"
    assert (tmp_path / "semantic-candidate.json").exists()
    assert (tmp_path / "semantic-monitoring.json").exists()
