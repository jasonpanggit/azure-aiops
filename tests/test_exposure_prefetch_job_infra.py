from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TERRAFORM_DIR = ROOT / "infra" / "terraform"
CONTAINER_APPS_TF = TERRAFORM_DIR / "container_apps.tf"
VARIABLES_TF = TERRAFORM_DIR / "variables.tf"


def _block(source: str, header: str) -> str:
    start = source.index(header)
    opening = source.index("{", start)
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"Unterminated Terraform block: {header}")


def _assignment(block: str, name: str) -> str:
    match = re.search(rf"^\s*{re.escape(name)}\s*=\s*(.+)$", block, re.MULTILINE)
    assert match is not None, f"Missing {name}"
    return match.group(1).strip()


def test_prefetch_job_is_a_bounded_single_replica_schedule() -> None:
    terraform = CONTAINER_APPS_TF.read_text(encoding="utf-8")
    variables = VARIABLES_TF.read_text(encoding="utf-8")
    job = _block(
        terraform,
        'resource "azurerm_container_app_job" "exposure_prefetch"',
    )
    schedule = _block(job, "schedule_trigger_config")
    schedule_variable = _block(
        variables,
        'variable "exposure_prefetch_schedule"',
    )

    assert 'name                         = "${local.base}-exposure-prefetch"' in job
    assert _assignment(job, "replica_retry_limit") == "0"
    timeout = int(_assignment(job, "replica_timeout_in_seconds"))
    assert 0 < timeout <= 900
    assert _assignment(schedule, "cron_expression") == "var.exposure_prefetch_schedule"
    assert _assignment(schedule, "parallelism") == "1"
    assert _assignment(schedule, "replica_completion_count") == "1"
    assert 'default     = "*/10 * * * *"' in schedule_variable
    assert "[5-9]|1[0-5]" in schedule_variable


def test_prefetch_job_reuses_apps_runtime_contract() -> None:
    terraform = CONTAINER_APPS_TF.read_text(encoding="utf-8")
    job = _block(
        terraform,
        'resource "azurerm_container_app_job" "exposure_prefetch"',
    )

    assert "identity_ids = [azurerm_user_assigned_identity.apps.id]" in job
    assert "identity = azurerm_user_assigned_identity.apps.id" in job
    assert (
        "image  = var.deploy_images ? local.api_image : local.placeholder_image" in job
    )
    assert 'name  = "AIOPS_HOME"' in job
    assert "/Files/aiops" in job
    assert "AIOPS_CONNECTION_HOME" not in job
    assert 'name        = "NVD_API_KEY"' in job
    assert 'secret_name = "nvd-api-key"' in job
    assert '"/app/scripts/refresh_exposure_enrichment.py"' in job
    assert '"--prefetch-generation"' in job
    assert '"--max-items"' in job
    assert "tostring(var.exposure_enrichment_max_items)" in job


def test_prefetch_job_adds_no_fabric_table_authorization() -> None:
    terraform = CONTAINER_APPS_TF.read_text(encoding="utf-8")
    all_terraform = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(TERRAFORM_DIR.glob("*.tf"))
    )
    job = _block(
        terraform,
        'resource "azurerm_container_app_job" "exposure_prefetch"',
    )

    for forbidden in (
        "AIOPS_FABRIC_SQL",
        "FABRIC_SQL",
        "fabric_onelake_data_access_security",
        "role_definition",
    ):
        assert forbidden.casefold() not in job.casefold()
    assert 'resource "fabric_workspace_role_assignment" "exposure_prefetch"' not in (
        all_terraform
    )
    assert (
        'resource "fabric_onelake_data_access_security" "exposure_prefetch"'
        not in all_terraform
    )
    assert "fabric_workspace_role_assignment.apps" in job


def test_existing_six_hour_all_due_enrichment_job_is_retained() -> None:
    terraform = CONTAINER_APPS_TF.read_text(encoding="utf-8")
    variables = VARIABLES_TF.read_text(encoding="utf-8")
    job = _block(
        terraform,
        'resource "azurerm_container_app_job" "exposure_enrichment"',
    )
    schedule_variable = _block(
        variables,
        'variable "exposure_enrichment_schedule"',
    )

    assert 'name                         = "${local.base}-exposure-enrichment"' in job
    assert "cron_expression          = var.exposure_enrichment_schedule" in job
    assert '"/app/scripts/refresh_exposure_enrichment.py"' in job
    assert '"--all-due"' in job
    assert 'default     = "0 */6 * * *"' in schedule_variable
