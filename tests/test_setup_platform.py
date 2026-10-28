"""Offline tests for setup ordering, opt-ins and SPN credential isolation."""

import importlib.util
import json
import os
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "setup_platform", ROOT / "infra/scripts/setup-platform.py"
)
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)

TENANT = "11111111-1111-1111-1111-111111111111"
CLIENT = "22222222-2222-2222-2222-222222222222"
WORKSPACE = "33333333-3333-3333-3333-333333333333"
LAKEHOUSE = "44444444-4444-4444-4444-444444444444"
ENVIRONMENT = {
    "AZURE_SUBSCRIPTION_ID": "55555555-5555-5555-5555-555555555555",
    "AZURE_TENANT_ID": TENANT,
    "AZURE_CLIENT_ID": CLIENT,
    "AZURE_CLIENT_SECRET": "test-secret-not-a-credential",
    "NEXT_PUBLIC_ENTRA_CLIENT_ID": CLIENT,
    "NEXT_PUBLIC_ENTRA_TENANT_ID": TENANT,
    "NEXT_PUBLIC_ENTRA_API_SCOPE": f"api://{CLIENT}/access_as_user",
    "AIOPS_ENTRA_API_AUDIENCE": CLIENT,
    "AIOPS_ENTRA_GRANTS_JSON": '{"admin@example.test":[{"role":"admin"}]}',
}
OUTPUTS = {
    "fabric_workspace_id": WORKSPACE,
    "fabric_lakehouse_id": LAKEHOUSE,
    "fabric_ontology_name": "Test_Operational_Ontology",
    "ontology_evidence_role_contract": None,
    "web_url": "https://test.example.test",
}
PLAN = {"resource_changes": []}


@pytest.fixture
def invocation(tmp_path, monkeypatch):
    env_file = tmp_path / "spn.env"
    env_file.write_text(
        "\n".join(f"{key}='{value}'" for key, value in ENVIRONMENT.items())
    )
    args = [
        "--apply",
        "--env-file",
        str(env_file),
        "--fabric-config",
        str(tmp_path / "fabric.yaml"),
        "--artifact-dir",
        str(tmp_path / "artifacts"),
    ]
    events = []

    def run(self, command, label, *, capture=False):
        events.append((command, label, self.environment.copy()))
        if command[:3] == ["terraform", "-chdir=infra/terraform", "show"]:
            return json.dumps(PLAN)
        if command[:1] == ["terraform"]:
            return json.dumps({key: {"value": value} for key, value in OUTPUTS.items()})
        if command[:2] == ["az", "login"]:
            directory = Path(self.environment["AZURE_CONFIG_DIR"])
            assert stat.S_IMODE(directory.stat().st_mode) == 0o700
        return ""

    monkeypatch.setattr(setup.Setup, "run", run)
    monkeypatch.setattr(setup.shutil, "which", lambda _: "/test/bin/tool")
    return args, events, tmp_path


def test_preview_is_offline_and_does_not_create_files(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        setup.subprocess,
        "run",
        lambda *a, **k: pytest.fail("Preview must not invoke any command"),
    )
    assert (
        setup.main(
            [
                "--env-file",
                str(tmp_path / "absent.env"),
                "--artifact-dir",
                str(tmp_path / "absent"),
            ]
        )
        == 0
    )
    assert not list(tmp_path.iterdir())
    assert "PREVIEW ONLY" in capsys.readouterr().out


def test_all_orders_fresh_setup_and_passes_exact_image_flags(invocation):
    args, events, path = invocation
    assert setup.main(args + ["--image-tag", "release-1"]) == 0
    labels = [event[1] for event in events]
    assert labels.index("validate Terraform") < labels.index("provision infrastructure")
    assert (
        labels.index("plan infrastructure")
        < labels.index("inspect semantic model bootstrap gate")
        < labels.index("provision infrastructure")
    )
    assert labels.index("provision infrastructure") < labels.index(
        "publish governed remediation catalog"
    )
    assert labels.index("publish governed remediation catalog") < labels.index(
        "build and verify four platform images"
    )
    assert events[-1][0][-2:] == ["-var=deploy_images=true", "-var=image_tag=release-1"]
    provision_env = next(
        env for _, label, env in events if label == "provision infrastructure"
    )
    assert provision_env["AIOPS_DEFER_CATALOG_PUBLICATION"] == "true"
    assert "AIOPS_DEFER_CATALOG_PUBLICATION" not in events[-1][2]
    login_dir = Path(events[0][2]["AZURE_CONFIG_DIR"])
    assert not login_dir.exists()
    config_file = path / "fabric.yaml"
    assert stat.S_IMODE(config_file.stat().st_mode) == 0o600
    assert ENVIRONMENT["AZURE_CLIENT_SECRET"] not in config_file.read_text()
    config = yaml.safe_load(config_file.read_text())["fabric"]
    assert config["workspace_id"] == WORKSPACE
    assert config["ontology"]["ontology_name"] == OUTPUTS["fabric_ontology_name"]
    assert config["ontology"]["ontology_id"] == ""
    assert config["ontology"]["enabled"] is False
    assert not any(
        "Sync operational ontology" in cmd or "--publish" in cmd for cmd, _, _ in events
    )


def test_new_pilot_bound_model_is_blocked_before_apply(invocation, monkeypatch):
    args, events, _ = invocation
    monkeypatch.setitem(
        PLAN,
        "resource_changes",
        [
            {
                "type": "fabric_semantic_model",
                "name": "aiops",
                "change": {"actions": ["create"]},
            }
        ],
    )
    with pytest.raises(setup.SetupError, match="manual model bootstrap"):
        setup.main(args)
    assert not any(label == "provision infrastructure" for _, label, _ in events)
    assert not any("publish" in label or "build" in label for _, label, _ in events)


def test_existing_semantic_model_is_not_disabled(invocation, monkeypatch):
    args, events, _ = invocation
    monkeypatch.setitem(
        PLAN,
        "resource_changes",
        [
            {
                "type": "fabric_semantic_model",
                "name": "aiops",
                "change": {"actions": ["no-op"]},
            }
        ],
    )
    assert setup.main(args + ["--stage", "infrastructure"]) == 0
    assert any(label == "provision infrastructure" for _, label, _ in events)
    assert not any("enable_fabric_semantic_model=false" in cmd for cmd, _, _ in events)


def test_fabric_rerun_preserves_custom_settings(invocation):
    args, events, path = invocation
    setup.main(args + ["--stage", "fabric"])
    config_path = path / "fabric.yaml"
    data = yaml.safe_load(config_path.read_text())
    data["fabric"]["custom_policy"] = {"keep": True}
    config_path.write_text(yaml.safe_dump(data))
    events.clear()
    setup.main(args + ["--stage", "fabric"])
    assert yaml.safe_load(config_path.read_text())["fabric"]["custom_policy"] == {
        "keep": True
    }
    assert not any("deploy.sh" in " ".join(cmd) for cmd, _, _ in events)


def test_release_rejects_another_deployments_config_before_build(invocation):
    args, events, path = invocation
    (path / "fabric.yaml").write_text(
        yaml.safe_dump(
            {
                "fabric": {
                    "auth": {"mode": "service_principal"},
                    "workspace_id": LAKEHOUSE,
                }
            }
        )
    )
    with pytest.raises(setup.SetupError, match="different deployment"):
        setup.main(args + ["--stage", "release"])
    assert not any("build" in label for _, label, _ in events)


def test_mismatched_targets_do_not_overwrite_config(tmp_path):
    path = tmp_path / "fabric.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "fabric": {
                    "auth": {"mode": "service_principal"},
                    "workspace_id": LAKEHOUSE,
                }
            }
        )
    )
    original = path.read_bytes()
    with pytest.raises(setup.SetupError, match="different deployment"):
        setup.configure_fabric(path, OUTPUTS, ENVIRONMENT.copy(), None)
    assert path.read_bytes() == original


@pytest.mark.parametrize("bad_id", [None, "", "bad", str(setup.UUID(int=0))])
def test_incomplete_fabric_ids_fail_before_writing(tmp_path, bad_id):
    path = tmp_path / "fabric.yaml"
    with pytest.raises(setup.SetupError):
        setup.configure_fabric(
            path, {**OUTPUTS, "fabric_workspace_id": bad_id}, ENVIRONMENT.copy(), None
        )
    assert not path.exists()


def test_existing_non_spn_config_is_not_overwritten(tmp_path):
    path = tmp_path / "fabric.yaml"
    original = "fabric:\n  auth:\n    mode: managed_identity\n"
    path.write_text(original)
    with pytest.raises(setup.SetupError, match="non-SPN"):
        setup.configure_fabric(path, OUTPUTS, ENVIRONMENT.copy(), None)
    assert path.read_text() == original


def test_opt_in_sync_requires_source_before_login(invocation):
    args, events, _ = invocation
    with pytest.raises(setup.SetupError, match="--source-data-root"):
        setup.main(args + ["--sync-inventory"])
    assert events == []


def test_requested_fabric_features_use_real_source_and_publish_flag(invocation):
    args, events, path = invocation
    source = path / "normalized"
    source.mkdir()
    setup.main(
        args
        + [
            "--stage",
            "fabric",
            "--sync-inventory",
            "--source-data-root",
            str(source),
            "--publish-data-agent",
        ]
    )
    commands = [cmd for cmd, _, _ in events]
    assert any("Sync operational ontology" in cmd for cmd in commands)
    assert commands[-1][-1] == "--publish"
    config = yaml.safe_load((path / "fabric.yaml").read_text())["fabric"]
    assert config["source_data_root"] == str(source)


def test_validation_roles_run_preview_before_apply_and_remove_contract(
    invocation, monkeypatch
):
    args, events, _ = invocation
    monkeypatch.setitem(
        OUTPUTS, "ontology_evidence_role_contract", {"principal_object_id": CLIENT}
    )
    monkeypatch.setitem(
        OUTPUTS,
        "ontology_evidence_api_gateway_grants",
        {CLIENT: [{"role": "reader", "scope": {
            "subscription": [ENVIRONMENT["AZURE_SUBSCRIPTION_ID"]]
        }}]},
    )
    setup.main(args + ["--stage", "fabric"])
    role_commands = [
        cmd for cmd, _, _ in events if any("reconcile_onelake" in item for item in cmd)
    ]
    assert len(role_commands) == 2
    assert "--apply" not in role_commands[0]
    assert role_commands[1][-1] == "--apply"
    contract = Path(role_commands[0][role_commands[0].index("--contract-file") + 1])
    assert not contract.exists()


def test_missing_collector_api_grant_blocks_before_fabric_writes(invocation, monkeypatch):
    args, events, path = invocation
    monkeypatch.setitem(
        OUTPUTS, "ontology_evidence_role_contract", {"principal_object_id": CLIENT}
    )
    with pytest.raises(setup.SetupError, match="exactly reader"):
        setup.main(args + ["--stage", "fabric"])
    assert not (path / "fabric.yaml").exists()
    assert not any("publish" in label or "reconcile" in label for _, label, _ in events)


def test_disabled_fabric_is_skipped_without_config(invocation, monkeypatch):
    args, events, path = invocation
    monkeypatch.setitem(OUTPUTS, "fabric_workspace_id", None)
    monkeypatch.setitem(OUTPUTS, "fabric_lakehouse_id", None)
    setup.main(args)
    assert not (path / "fabric.yaml").exists()
    assert not any(
        "publish governed remediation catalog" == label for _, label, _ in events
    )


def test_explicit_fabric_stage_fails_when_fabric_disabled(invocation, monkeypatch):
    args, events, _ = invocation
    monkeypatch.setitem(OUTPUTS, "fabric_workspace_id", None)
    monkeypatch.setitem(OUTPUTS, "fabric_lakehouse_id", None)
    with pytest.raises(setup.SetupError, match="Fabric is disabled"):
        setup.main(args + ["--stage", "fabric"])
    assert not any("publish" in label for _, label, _ in events)


def test_failure_stops_subsequent_steps_and_cleans_login(invocation, monkeypatch):
    args, events, _ = invocation
    original = setup.Setup.run

    def fail(self, cmd, label, *, capture=False):
        if label == "provision infrastructure":
            raise setup.SetupError("test provisioning failure")
        return original(self, cmd, label, capture=capture)

    monkeypatch.setattr(setup.Setup, "run", fail)
    with pytest.raises(setup.SetupError, match="provisioning failure"):
        setup.main(args)
    assert not Path(events[0][2]["AZURE_CONFIG_DIR"]).exists()
    assert not any("build" in label for _, label, _ in events)


def test_env_parser_is_literal_and_does_not_execute(tmp_path):
    path = tmp_path / "settings"
    path.write_text(
        "# comment\nexport KEY='$(touch should-not-exist)'\nJSON='{\"x\":1}'\n"
    )
    assert setup.read_env(path) == {
        "KEY": "$(touch should-not-exist)",
        "JSON": '{"x":1}',
    }


def test_diagnostics_redact_login_secret(monkeypatch, capsys):
    monkeypatch.setattr(
        setup.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(
            a[0], 1, "", ENVIRONMENT["AZURE_CLIENT_SECRET"]
        ),
    )
    with pytest.raises(setup.SetupError, match="exit 1"):
        setup.Setup(ENVIRONMENT).run(["az", "login"], "SPN login", capture=True)
    assert ENVIRONMENT["AZURE_CLIENT_SECRET"] not in capsys.readouterr().err


def test_symlink_config_is_not_followed(tmp_path):
    target = tmp_path / "target"
    target.write_text("original")
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(setup.SetupError, match="symlink"):
        setup.private_write(link, "replacement")
    assert target.read_text() == "original"


def test_deploy_without_fabric_does_not_require_fabric_config(tmp_path):
    script = tmp_path / "infra/scripts/deploy.sh"
    script.parent.mkdir(parents=True)
    script.write_text((ROOT / "infra/scripts/deploy.sh").read_text())
    terraform = tmp_path / "infra/terraform"
    (terraform / ".terraform").mkdir(parents=True)
    env_file = tmp_path / "spn.env"
    env_file.write_text(
        "\n".join(f"{key}='{value}'" for key, value in ENVIRONMENT.items())
    )
    tools = tmp_path / "bin"
    tools.mkdir()
    fake_tf = tools / "terraform"
    fake_tf.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = output ]; then printf "{}"; fi\n'
        'if [ "$1" = console ]; then\n'
        "  read expression\n"
        '  if [ "$expression" = var.copilot_rollout_mode ]; then\n'
        "    printf '\"compatibility\"'\n"
        "  else\n"
        "    printf '\"\"'\n"
        "  fi\n"
        "fi\n"
    )
    fake_tf.chmod(0o700)
    result = subprocess.run(
        ["bash", str(script), "apply"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "PATH": f"{tools}:{os.environ['PATH']}",
            "AIOPS_ENV_FILE": str(env_file),
            "AIOPS_DEPLOYER_OBJECT_ID": CLIENT,
            "AIOPS_CAPTURE_APIM_SNAPSHOT": "false",
            "AIOPS_API_AUTHORIZATION_RELEASE": "0",
        },
    )
    assert result.returncode == 0, result.stderr
    assert "Fabric disabled" in result.stdout


def test_both_mcp_apps_have_bootstrap_images():
    for filename in ("mcp_server.tf", "azure_mcp_server.tf"):
        source = (ROOT / "infra/terraform" / filename).read_text()
        image_line = next(line for line in source.splitlines() if "image  =" in line)
        assert "var.deploy_images ?" in image_line
        assert ": local.placeholder_image" in image_line


def test_main_manages_ai_ops_agent_not_the_old_pilot_semantic_model():
    source = (ROOT / "infra/terraform/fabric.tf").read_text()
    assert 'resource "fabric_semantic_model" "aiops"' not in source
    assert 'resource "fabric_data_agent" "ai_ops"' in source
    assert 'resource "fabric_workspace_role_assignment" "terraform_deployer"' in source
