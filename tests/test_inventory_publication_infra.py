"""Source contracts for isolated inventory producer release configuration."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INFRA = ROOT / "infra" / "terraform"
SOURCE = (INFRA / "inventory_publication_job.tf").read_text(encoding="utf-8")


def _variable(name: str) -> str:
    return SOURCE.split(f'variable "{name}" {{', 1)[1].split("\n}", 1)[0]


def test_producer_defaults_remain_manual_without_native_or_refresh_opt_in():
    assert 'default     = ""' in _variable("inventory_publication_schedule")
    assert "default     = false" in _variable(
        "inventory_publication_native_registry_mapping",
    )
    assert "default = null" in _variable("inventory_publication_graph_refresh_target")
    assert "var.inventory_publication_graph_refresh_target == null ? {}" in SOURCE
    assert 'var.inventory_publication_schedule == "" ? [1] : []' in SOURCE
    assert 'var.inventory_publication_schedule != "" ? [1] : []' in SOURCE


def test_refresh_target_is_atomic_and_validated_before_runtime():
    target = _variable("inventory_publication_graph_refresh_target")
    assert "workspace_id" in target and "graph_model_id" in target
    assert "type = object({" in target
    assert "can(regex(" in target and "alltrue([" in target
    assert "var.inventory_publication_graph_refresh_target == null ? true" in target
    assert "AIOPS_GRAPH_REFRESH_WORKSPACE_ID" in SOURCE
    assert "AIOPS_GRAPH_REFRESH_GRAPH_MODEL_ID" in SOURCE
    assert 'for_each = local.inventory_publication_graph_refresh_env' in SOURCE
    assert "name  = env.key" in SOURCE and "value = env.value" in SOURCE


def test_native_pair_opt_in_never_enables_definition_publication():
    config = SOURCE.split("inventory_publication_runtime_config =", 1)[1].split(
        "inventory_publication_graph_refresh_env =", 1,
    )[0]
    assert "merge(local.fabric_publisher_runtime_config" in config
    assert "var.inventory_publication_native_registry_mapping ? false" in config
    assert config.count('var.inventory_publication_native_registry_mapping ? ""') == 2
    assert "native_registry_mapping = var.inventory_publication_native_registry_mapping" in config
    assert "jsonencode({ fabric = local.inventory_publication_runtime_config })" in SOURCE


def test_image_pin_is_immutable_and_changes_only_inventory_job():
    image = _variable("inventory_publication_image_digest")
    assert 'default     = ""' in image
    assert "^sha256:[0-9a-f]{64}$" in image
    assert "local.inventory_publication_image" in SOURCE
    assert "var.api_image_repository}@${var.inventory_publication_image_digest}" in SOURCE
    consumers = {
        path.name for path in INFRA.glob("*.tf")
        if "var.inventory_publication_image_digest" in path.read_text()
        or "local.inventory_publication_runtime_config" in path.read_text()
        or "local.inventory_publication_graph_refresh_env" in path.read_text()
    }
    assert consumers == {"inventory_publication_job.tf"}


def test_job_keeps_finite_single_replica_execution_and_publisher_identity():
    assert "replica_timeout_in_seconds   = 3600" in SOURCE
    assert "replica_retry_limit          = 0" in SOURCE
    assert SOURCE.count("parallelism              = 1") == 2
    assert SOURCE.count("replica_completion_count = 1") == 2
    assert "azurerm_user_assigned_identity.ontology_publisher.id" in SOURCE
    assert '["python", "-m", "intelligence.inventory.publication_cli"]' in SOURCE
    assert "ignore_changes" not in SOURCE


def test_dev_overlay_preserves_reviewed_live_release_not_generic_defaults():
    profile = (INFRA / "environments/dev.native-ontology.tfvars").read_text()
    assert '"F8"' in profile
    assert '"30 14 * * *"' in profile
    assert "inventory_publication_native_registry_mapping" in profile
    assert "sha256:fbb773f73cfe115c2720b9c49a3353fe95b0a7ac24cbaa4621d04aa58d8762f9" in profile
    assert 'workspace_id   = "2c1fea36-104d-4c26-86db-12e09e432b41"' in profile
    assert 'graph_model_id = "e4aa8669-82d3-4ef4-9241-47252fca23fd"' in profile
    assert "enable_fabric_ontology_item" not in profile
    assert "enable_fabric_publisher_ontology_item" not in profile
