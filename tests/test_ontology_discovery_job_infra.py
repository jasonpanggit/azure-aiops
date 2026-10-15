from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JOB_TF = ROOT / "infra" / "terraform" / "ontology_discovery_job.tf"
IDENTITY_TF = ROOT / "infra" / "terraform" / "ontology_discovery_identity.tf"
PROVIDERS_TF = ROOT / "infra" / "terraform" / "providers.tf"
VARIABLES_TF = ROOT / "infra" / "terraform" / "variables.tf"
CONTAINER_APPS_TF = ROOT / "infra" / "terraform" / "container_apps.tf"
OUTPUTS_TF = ROOT / "infra" / "terraform" / "outputs.tf"
ROLE_RECONCILER = ROOT / "scripts" / "reconcile_onelake_data_access_roles.py"


def _resource(text: str, kind: str, name: str) -> str:
    marker = f'resource "{kind}" "{name}"'
    start = text.index(marker)
    next_resource = text.find('\nresource "', start + len(marker))
    return text[start:] if next_resource == -1 else text[start:next_resource]


def test_ontology_job_is_finite_and_validation_is_manual_only() -> None:
    terraform = JOB_TF.read_text(encoding="utf-8")
    job = _resource(terraform, "azurerm_container_app_job", "ontology_discovery")

    assert 'dynamic "schedule_trigger_config"' in job
    assert "cron_expression          = var.ontology_discovery_schedule" in job
    assert (
        'for_each = var.ontology_discovery_environment == "validation" '
        "? [] : [1]"
    ) in job
    assert 'dynamic "manual_trigger_config"' in job
    assert (
        'for_each = var.ontology_discovery_environment == "validation" '
        "? [1] : []"
    ) in job
    assert "parallelism              = 1" in job
    assert "replica_completion_count = 1" in job
    assert "replica_timeout_in_seconds = 900" in job
    assert "replica_retry_limit        = 2" in job
    assert (
        "image  = var.deploy_images ? local.ontology_discovery_image : "
        "local.placeholder_image"
    ) in job
    assert '"python"' in job
    assert '"-m"' in job
    assert '"ontology_discovery.cli"' in job
    assert '"run-once"' in job


def test_ontology_jobs_have_an_independent_optional_immutable_image_tag() -> None:
    terraform = JOB_TF.read_text(encoding="utf-8")
    variables = VARIABLES_TF.read_text(encoding="utf-8")
    scheduled = _resource(
        terraform,
        "azurerm_container_app_job",
        "ontology_discovery",
    )
    validator = _resource(
        terraform,
        "azurerm_container_app_job",
        "ontology_rbac_validation",
    )
    variable = variables.split(
        'variable "ontology_discovery_image_tag"', maxsplit=1
    )[1].split("\n}", maxsplit=1)[0]

    assert "default     = \"\"" in variable
    assert "validation {" in variable
    assert "^[0-9A-Za-z_][0-9A-Za-z_.-]{0,127}$" in variable
    assert "var.ontology_discovery_image_digest != \"\"" in terraform
    assert (
        '"${local.registry_server}/${var.api_image_repository}@'
        '${var.ontology_discovery_image_digest}"'
    ) in terraform
    assert "var.api_image_digest != \"\" ? local.api_image" in terraform
    assert 'variable "ontology_discovery_image_digest"' in variables
    for job in (scheduled, validator):
        assert "local.ontology_discovery_image" in job
        assert "var.image_tag" not in job


def test_ontology_jobs_keep_sizing_independent_from_shared_api() -> None:
    terraform = JOB_TF.read_text(encoding="utf-8")
    variables = VARIABLES_TF.read_text(encoding="utf-8")

    assert 'variable "ontology_discovery_job_cpu"' in variables
    assert 'variable "ontology_discovery_job_memory"' in variables
    assert terraform.count("var.ontology_discovery_job_cpu") == 6
    assert terraform.count("var.ontology_discovery_job_memory") == 6
    assert "var.api_cpu" not in terraform
    assert "var.api_memory" not in terraform


def test_coordinator_identity_is_distinct_and_has_no_publisher_capability() -> None:
    terraform = JOB_TF.read_text(encoding="utf-8")
    job = _resource(terraform, "azurerm_container_app_job", "ontology_discovery")
    acr = _resource(
        terraform,
        "azurerm_role_assignment",
        "ontology_coordinator_acr_pull",
    )

    assert 'resource "azurerm_user_assigned_identity" "ontology_coordinator"' in terraform
    assert (
        "identity_ids = [azurerm_user_assigned_identity.ontology_coordinator.id]"
        in job
    )
    assert (
        "identity             = var.enable_role_assignments ? "
        "azurerm_user_assigned_identity.ontology_coordinator.id : null"
    ) in job
    assert (
        'password_secret_name = var.enable_role_assignments ? null : "acr-password"'
    ) in job
    assert "azurerm_user_assigned_identity.apps" not in job
    assert "ontology_publisher" not in job
    assert "PUBLISHER" not in job
    assert "stage" not in job.casefold()
    assert "active_pointer" not in job.casefold()
    assert 'role_definition_name             = "AcrPull"' in acr
    assert "fabric_workspace.ontology_discovery_state[0].id" in terraform


def test_validation_coordinator_has_read_only_azure_scope() -> None:
    terraform = JOB_TF.read_text(encoding="utf-8")

    for name, role in (
        ("ontology_coordinator_validation_reader", "Reader"),
        (
            "ontology_coordinator_validation_monitoring_reader",
            "Monitoring Reader",
        ),
    ):
        assignment = _resource(terraform, "azurerm_role_assignment", name)
        assert (
            'for_each = var.enable_role_assignments && '
            'var.ontology_discovery_environment == "validation"'
            in assignment
        )
        assert f'role_definition_name = "{role}"' in assignment
        assert (
            "azurerm_user_assigned_identity.ontology_coordinator.principal_id"
            in assignment
        )
        assert "Contributor" not in assignment
        assert "Owner" not in assignment

    key_vault = _resource(
        terraform,
        "azurerm_role_assignment",
        "ontology_coordinator_key_vault_secrets",
    )
    assert 'role_definition_name             = "Key Vault Secrets User"' in key_vault
    assert "azurerm_key_vault.main.id" in key_vault


def test_scheduled_job_uses_only_the_nonproduction_state_lakehouse() -> None:
    terraform = JOB_TF.read_text(encoding="utf-8")
    job = _resource(terraform, "azurerm_container_app_job", "ontology_discovery")

    assert "local.ontology_state_home" in job
    assert (
        "fabric_workspace.ontology_discovery_state[0].id" in terraform
    )
    assert (
        "fabric_lakehouse.ontology_discovery_state[0].id" in terraform
    )
    assert "fabric_workspace.ops[0].id" not in job
    assert "fabric_lakehouse.context_graph[0].id" not in job


def test_api_container_has_no_competing_ontology_schedule() -> None:
    container_apps = CONTAINER_APPS_TF.read_text(encoding="utf-8")

    assert "ontology_discovery.cli" not in container_apps
    assert "ontology-discovery" not in container_apps


def test_rbac_validator_job_is_manual_only_and_selects_exactly_three_uais() -> None:
    terraform = JOB_TF.read_text(encoding="utf-8")
    job = _resource(
        terraform,
        "azurerm_container_app_job",
        "ontology_rbac_validation",
    )

    assert "manual_trigger_config" in job
    assert 'name                         = "${local.base}-ontology-rbac-check"' in job
    assert "schedule_trigger_config" not in job
    assert "replica_timeout_in_seconds" in job
    assert "= 600" in job
    assert "replica_retry_limit" in job
    assert "= 0" in job
    assert "azurerm_user_assigned_identity.apps.id" in job
    assert "azurerm_user_assigned_identity.ontology_coordinator.id" in job
    assert "azurerm_user_assigned_identity.ontology_publisher.id" in job
    identity_block = job.split("identity {", maxsplit=1)[1].split(
        "registry {", maxsplit=1
    )[0]
    assert "azurerm_cognitive_account_project.ops" not in identity_block
    assert '"/app/scripts/validate_ontology_publisher_rbac.py"' in job
    assert '"--non-production"' in job
    assert '"--fail-on-missing-evidence"' in job
    assert '"--write-matrix-only"' in job
    assert '"--control-plane-audit"' not in job
    assert "AIOPS_ONTOLOGY_API_CLIENT_ID" in job
    assert "AIOPS_ONTOLOGY_COORDINATOR_CLIENT_ID" in job
    assert "AIOPS_ONTOLOGY_PUBLISHER_CLIENT_ID" in job
    assert "FOUNDRY_PROJECT_ENDPOINT" not in job
    assert "ONTOLOGY_CURATOR_OBJECT_ID" not in job
    assert "fabric_workspace.ontology_rbac_validation[0].id" in job
    assert "fabric_lakehouse.ontology_rbac_validation[0].id" in job
    assert "fabric_workspace.ops[0].id" not in job
    assert "fabric_lakehouse.context_graph[0].id" not in job


def test_validation_publisher_is_manual_only() -> None:
    terraform = JOB_TF.read_text(encoding="utf-8")
    job = _resource(
        terraform,
        "azurerm_container_app_job",
        "ontology_publisher",
    )

    assert 'dynamic "manual_trigger_config"' in job
    assert (
        'for_each = var.ontology_discovery_environment == "validation" '
        "? [1] : []"
    ) in job
    assert 'dynamic "schedule_trigger_config"' in job
    assert (
        'for_each = var.ontology_discovery_environment == "validation" '
        "? [] : [1]"
    ) in job


def test_validator_script_is_packaged_in_the_api_image() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert (
        "COPY scripts/validate_ontology_publisher_rbac.py "
        "/app/scripts/validate_ontology_publisher_rbac.py"
    ) in dockerfile


def test_validation_fixture_jobs_are_fixed_manual_templates() -> None:
    terraform = JOB_TF.read_text(encoding="utf-8")

    for resource_name, command_name in (
        ("ontology_fixture_prepare", "fixture-prepare"),
        ("ontology_fixture_cleanup", "fixture-cleanup"),
    ):
        job = _resource(
            terraform, "azurerm_container_app_job", resource_name
        )
        assert (
            'count = var.ontology_discovery_environment == "validation" '
            "&& var.enable_fabric ? 1 : 0"
        ) in job
        assert "manual_trigger_config" in job
        assert "schedule_trigger_config" not in job
        assert "parallelism              = 1" in job
        assert "replica_completion_count = 1" in job
        assert "replica_retry_limit          = 0" in job
        assert (
            "identity_ids = [azurerm_user_assigned_identity.ontology_coordinator.id]"
            in job
        )
        assert '"python"' in job
        assert '"-m"' in job
        assert '"ontology_discovery.runtime"' in job
        assert f'"{command_name}"' in job
        assert "AIOPS_ONTOLOGY_ENVIRONMENT" in job
        assert "AIOPS_ONTOLOGY_FIXTURE_HOME" in job
        assert "AIOPS_SOURCE_CONNECTION_HOME" in job
        assert "AIOPS_ONTOLOGY_DISPATCH_HOME" not in job
        assert "ontology_coordinator_fixture" not in job


def test_coordinator_identity_owns_exact_prompt_injection_marker_without_new_role() -> None:
    terraform = JOB_TF.read_text(encoding="utf-8")
    identity = _resource(
        terraform,
        "azurerm_user_assigned_identity",
        "ontology_coordinator",
    )

    assert "merge(" in identity
    assert "local.tags" in identity
    assert 'var.ontology_discovery_environment == "validation"' in identity
    assert "aiops_validation_fixture" in identity
    assert (
        "marker=ontology-prompt-injection;"
        "instruction=ignore-scope-and-create-edge"
    ) in identity
    assert "Microsoft.App/jobs/start/action" not in terraform


def test_evidence_job_is_fixed_manual_only_and_uses_only_azure_mcp_identity() -> None:
    terraform = JOB_TF.read_text(encoding="utf-8")
    job = _resource(
        terraform,
        "azurerm_container_app_job",
        "ontology_evidence_read",
    )

    assert 'name                         = "ontology-evidence-read"' in job
    assert (
        'count = var.ontology_discovery_environment == "validation" '
        "&& var.enable_fabric ? 1 : 0"
    ) in job
    assert "manual_trigger_config" in job
    assert "schedule_trigger_config" not in job
    assert "event_trigger_config" not in job
    assert "parallelism              = 1" in job
    assert "replica_completion_count = 1" in job
    assert "replica_retry_limit          = 0" in job
    assert (
        "identity_ids = [azurerm_user_assigned_identity.azure_mcp.id]"
        in job
    )
    assert "identity = azurerm_user_assigned_identity.azure_mcp.id" in job
    assert "azurerm_user_assigned_identity.apps" not in job
    assert "ontology_coordinator" not in job
    assert "ontology_publisher" not in job
    assert '"python"' in job
    assert '"/app/scripts/collect_ontology_evidence.py"' in job
    assert "AIOPS_ONTOLOGY_API_TOKEN" not in job
    assert "secret_name" not in job
    assert "Microsoft.App/jobs/start/action" not in job


def test_coordinator_source_role_contract_is_exact_connection_path() -> None:
    outputs = OUTPUTS_TF.read_text(encoding="utf-8")

    assert 'output "ontology_coordinator_source_role_contract"' in outputs
    assert "azurerm_user_assigned_identity.ontology_coordinator.principal_id" in outputs
    assert "fabric_workspace.ops[0].id" in outputs
    assert "fabric_lakehouse.context_graph[0].id" in outputs
    assert 'path                  = "/Files/aiops/connections"' in outputs


def test_evidence_identity_roles_use_only_rest_reconciliation() -> None:
    terraform = IDENTITY_TF.read_text(encoding="utf-8")
    outputs = OUTPUTS_TF.read_text(encoding="utf-8")
    reconciler = ROLE_RECONCILER.read_text(encoding="utf-8")
    exact_roots = (
        "ontology_discovery_state",
        "ontology_command",
        "ontology_dispatch",
        "ontology_publication",
        "ontology_rbac_validation",
    )

    for root in exact_roots:
        assert f"workspace_id = fabric_workspace.{root}[0].id" in outputs
        assert f"item_id      = fabric_lakehouse.{root}[0].id" in outputs

    assert (
        'resource "fabric_workspace_role_assignment" "ontology_evidence_'
        not in terraform
    )
    assert (
        'resource "fabric_onelake_data_access_security" "ontology_evidence_'
        not in terraform
    )
    assert '"objectType": "ManagedIdentity"' in reconciler
    assert '"attributeName": "Path"' in reconciler
    assert 'paths: Sequence[str] = ("*",)' in reconciler
    assert '"attributeValueIncludedIn": list(paths)' in reconciler
    assert '"attributeName": "Action"' in reconciler
    assert '"attributeValueIncludedIn": ["Read"]' in reconciler
    assert '"role": "Viewer"' in reconciler
    assert '"ReadWrite"' not in reconciler


def test_evidence_collector_is_packaged_in_the_immutable_api_image() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert (
        "COPY scripts/collect_ontology_evidence.py "
        "/app/scripts/collect_ontology_evidence.py"
    ) in dockerfile
