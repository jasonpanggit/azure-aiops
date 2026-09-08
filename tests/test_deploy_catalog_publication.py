"""Deployment contract for governed remediation catalog publication."""

from pathlib import Path


def test_apply_publishes_catalog_before_revision_verification() -> None:
    source = Path("infra/scripts/deploy.sh").read_text()
    apply_block = source.split("  apply)", 1)[1].split("    ;;", 1)[0]

    terraform = apply_block.index("terraform apply")
    publication = apply_block.index("publish_governed_remediation_catalog")
    verification = apply_block.index("report_running_images")

    assert terraform < publication < verification
    assert "seed_remediation_catalog.py" not in apply_block


def test_deployment_publication_uses_the_application_cli() -> None:
    source = Path("infra/scripts/deploy.sh").read_text()
    function = source.split(
        "publish_governed_remediation_catalog() {", 1
    )[1].split("\n}", 1)[0]

    assert "-m onboarding.cli fabric" in function
    assert "Publish governed remediation catalog" in function
    assert "AZURE_CLIENT_SECRET" in function
