"""Offline production-readiness gates for SRE Agent selected-patch execution."""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFINITION = REPO_ROOT / "infra/sre-agent/patch-trigger.v1.json"
TRIGGER_FIXTURE = REPO_ROOT / "tests/fixtures/sre_agent_patch_trigger.sanitized.json"
AGENT_FIXTURE = REPO_ROOT / "tests/fixtures/sre_agent_patch_resource.sanitized.json"
RBAC_FIXTURE = REPO_ROOT / "tests/fixtures/sre_agent_patch_rbac.sanitized.json"
SECRET_FIXTURE = REPO_ROOT / "tests/fixtures/sre_agent_patch_secret.sanitized.json"
SECRET_VERSION = "00000000000000000000000000000001"
REAL_TRIGGER_ID = "b65d078b-a0f5-4b63-b1a9-70f18ae44ad8"
REAL_SECRET_VERSION = "bcaf1e13b0e2481782c1c8dfdd01cd05"
TRIGGER_ID = "trigger-selected-patch-v1"
TRIGGER_ORIGIN = "https://sre-agent-sredemo.sre.azure.com"
AGENT_ENDPOINT = (
    "https://sre-agent-sredemo--8b71343d.ba56c019.australiaeast.azuresre.ai"
)
TARGET_PREFIX = (
    "/subscriptions/a87a8e64-a52a-4aa8-a760-5e8919d23cd1/resourceGroups/rg-sredemo-dev"
)


def _load_module():
    path = REPO_ROOT / "scripts/preflight_sre_agent_patch_execution.py"
    spec = importlib.util.spec_from_file_location(
        "preflight_sre_agent_patch_execution",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _fixture(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _real_live_trigger_row(module, **overrides: object) -> dict[str, object]:
    row = {
        "agent": None,
        "agentMode": "autonomous",
        "agentPrompt": module.canonical_trigger_body(_fixture(DEFINITION))["prompt"],
        "createdAt": "2026-09-16T01:00:00Z",
        "createdBy": "operator",
        "description": "",
        "executionCount": 0,
        "id": REAL_TRIGGER_ID,
        "lastExecutionTime": None,
        "modelTier": None,
        "name": "aiops-selected-patch-execution-v1",
        "threadId": "",
        "triggerEnabled": True,
        "triggerLastCalledAt": None,
        "triggerUrl": f"{TRIGGER_ORIGIN}/api/v1/httptriggers/trigger/{REAL_TRIGGER_ID}",
    }
    row.update(overrides)
    return row


def _refresh_rbac_provenance(module, payload: dict[str, object]) -> None:
    for capture in payload["assignmentCaptures"]:
        capture["rawRowCount"] = len(capture["rawAssignments"])
        capture["rawSha256"] = module._json_sha256(capture["rawAssignments"])
    for capture in payload["roleDefinitionCaptures"]:
        capture["rawSha256"] = module._json_sha256(capture["raw"])


def _ready_report(module):
    return module.build_readiness_report(
        definition=_fixture(DEFINITION),
        trigger_evidence=_fixture(TRIGGER_FIXTURE),
        agent_evidence=_fixture(AGENT_FIXTURE),
        rbac_evidence=_fixture(RBAC_FIXTURE),
        secret_evidence=_fixture(SECRET_FIXTURE),
        expected_trigger_id=TRIGGER_ID,
        expected_trigger_origin=TRIGGER_ORIGIN,
        expected_agent_endpoint=AGENT_ENDPOINT,
        target_prefix=TARGET_PREFIX,
    )


def _live_runner(module, *, sre_rows: list[object] | None = None):
    fixture = _fixture(RBAC_FIXTURE)
    subscription_id = module.SUBSCRIPTION_ID
    account_argv = (
        "az",
        "account",
        "list",
        "--all",
        "--refresh",
        "--only-show-errors",
        "-o",
        "json",
    )
    api_argv = (
        "az",
        "role",
        "assignment",
        "list",
        "--subscription",
        subscription_id,
        "--assignee-object-id",
        module.API_UAI_PRINCIPAL_ID,
        "--all",
        "--include-inherited",
        "--include-groups",
        "--only-show-errors",
        "-o",
        "json",
    )
    sre_argv = (
        "az",
        "role",
        "assignment",
        "list",
        "--subscription",
        subscription_id,
        "--assignee-object-id",
        module.SRE_UAI_PRINCIPAL_ID,
        "--all",
        "--include-inherited",
        "--include-groups",
        "--only-show-errors",
        "-o",
        "json",
    )
    api_inherited_argv = (
        "az",
        "role",
        "assignment",
        "list",
        "--subscription",
        subscription_id,
        "--assignee-object-id",
        module.API_UAI_PRINCIPAL_ID,
        "--scope",
        f"/subscriptions/{subscription_id}",
        "--include-inherited",
        "--include-groups",
        "--only-show-errors",
        "-o",
        "json",
    )
    sre_inherited_argv = (
        "az",
        "role",
        "assignment",
        "list",
        "--subscription",
        subscription_id,
        "--assignee-object-id",
        module.SRE_UAI_PRINCIPAL_ID,
        "--scope",
        f"/subscriptions/{subscription_id}",
        "--include-inherited",
        "--include-groups",
        "--only-show-errors",
        "-o",
        "json",
    )
    responses = {
        account_argv: [
            {
                "id": subscription_id,
                "tenantId": module.TENANT_ID,
                "state": "Enabled",
            }
        ],
        api_argv: fixture["assignmentCaptures"][0]["rawAssignments"],
        api_inherited_argv: fixture["assignmentCaptures"][0]["rawAssignments"],
        sre_argv: (
            fixture["assignmentCaptures"][1]["rawAssignments"]
            if sre_rows is None
            else sre_rows
        ),
        sre_inherited_argv: (
            fixture["assignmentCaptures"][1]["rawAssignments"]
            if sre_rows is None
            else sre_rows
        ),
    }
    for capture in fixture["roleDefinitionCaptures"]:
        raw = capture["raw"]
        role_id = raw["id"]
        argv = (
            "az",
            "role",
            "definition",
            "list",
            "--name",
            role_id.rsplit("/", 1)[-1],
            "--scope",
            f"/subscriptions/{subscription_id}",
            "--only-show-errors",
            "-o",
            "json",
        )
        responses[argv] = [raw]
    calls = []

    def runner(argv):
        command = tuple(argv)
        calls.append(command)
        payload = responses.get(command)
        if payload is None:
            return 2, b"", b"unexpected command"
        return 0, json.dumps(payload, separators=(",", ":")).encode(), b""

    return runner, calls, responses


def _collect_live(module, runner):
    return module.collect_live_rbac(
        runner=runner,
        target_prefix=TARGET_PREFIX,
    )


def _all_live_dependencies(module, *, deployed: bool = True):
    rbac_runner, calls, rbac_responses = _live_runner(module)
    agent = _fixture(AGENT_FIXTURE)["resource"]
    secret = _fixture(SECRET_FIXTURE)
    trigger_row = _real_live_trigger_row(
        module,
        id=TRIGGER_ID,
        triggerUrl=f"{TRIGGER_ORIGIN}/api/v1/httptriggers/trigger/{TRIGGER_ID}",
    )
    app_state = {
        "secrets": [
            {
                "name": module.SECRET_NAME,
                "keyVaultUrl": secret["metadata"]["id"],
                "identity": module.API_UAI_RESOURCE_ID,
            }
        ],
        "env": [
            {"name": "AIOPS_PATCH_EXECUTION", "value": "sre-agent", "secretRef": None},
            {
                "name": module.SECRET_ENVIRONMENT_VARIABLE,
                "value": None,
                "secretRef": module.SECRET_NAME,
            },
            {
                "name": "AIOPS_SRE_AGENT_TRIGGER_ID",
                "value": TRIGGER_ID,
                "secretRef": None,
            },
            {
                "name": "AIOPS_SRE_AGENT_TRIGGER_ORIGIN",
                "value": TRIGGER_ORIGIN,
                "secretRef": None,
            },
            {
                "name": "AIOPS_SRE_AGENT_ENDPOINT",
                "value": AGENT_ENDPOINT,
                "secretRef": None,
            },
            {
                "name": "AIOPS_SRE_AGENT_SUBSCRIPTION_ID",
                "value": module.SUBSCRIPTION_ID,
                "secretRef": None,
            },
            {
                "name": "AIOPS_SRE_AGENT_TARGET_PREFIX",
                "value": TARGET_PREFIX,
                "secretRef": None,
            },
            {
                "name": "AIOPS_SRE_AGENT_TRIGGER_SCOPE",
                "value": module.TRIGGER_SCOPE,
                "secretRef": None,
            },
            {
                "name": "AIOPS_SRE_AGENT_THREAD_SCOPE",
                "value": module.THREAD_SCOPE,
                "secretRef": None,
            },
        ],
    }

    def runner(argv):
        command = tuple(argv)
        if command in rbac_responses:
            return rbac_runner(command)
        calls.append(command)
        if command[:2] == ("az", "rest"):
            payload = agent
        elif command[:3] == ("az", "account", "get-access-token"):
            return 0, b"secret-token\n", b""
        elif command[:4] == ("az", "keyvault", "secret", "show"):
            payload = secret["metadata"]
        elif command[:3] == ("az", "containerapp", "show"):
            payload = app_state if deployed else {"secrets": [], "env": []}
        else:
            return 2, b"", b"unexpected command"
        return 0, json.dumps(payload, separators=(",", ":")).encode(), b""

    def requester(url, token):
        assert url == f"{AGENT_ENDPOINT}/api/v1/httptriggers"
        assert token == "secret-token"
        return 200, json.dumps([trigger_row], separators=(",", ":")).encode(), {}

    return runner, requester, calls, app_state


def test_canonical_render_and_hash_are_deterministic() -> None:
    module = _load_module()
    body = module.canonical_trigger_body(_fixture(DEFINITION))

    assert body["runMode"] == "Autonomous"
    assert body["threadGrouping"] == "NewThreadPerRun"
    assert body["payloadSchema"]["additionalProperties"] is False
    assert (
        module.canonical_hash(body)
        == "ce4b185c2faa25300b7e71a41fc4a91601fc4ebc56caeffeec24316c7b5d2a4b"
    )


def test_offline_sanitized_evidence_requires_fresh_live_collector() -> None:
    module = _load_module()

    report = _ready_report(module)

    assert report["status"] == "blocked"
    assert report["readinessSource"] == "component-validation"
    assert report["blockers"] == ["rbac: fresh live collector required"]
    assert report["checks"]["rbac"]["status"] == "offline-evidence-valid"
    assert report["mutationSupported"] is False
    assert report["liveMutationPerformed"] is False
    assert set(report["checks"]) == {"agent", "rbac", "secret", "trigger"}


def test_shared_builder_cannot_synthesize_a_production_ready_verdict() -> None:
    module = _load_module()
    report = module._build_readiness_report(
        definition=_fixture(DEFINITION),
        trigger_evidence=_fixture(TRIGGER_FIXTURE),
        agent_evidence=_fixture(AGENT_FIXTURE),
        rbac_validator=lambda: module._validate_rbac_contract(
            _fixture(RBAC_FIXTURE),
            target_prefix=TARGET_PREFIX,
        ),
        secret_evidence=_fixture(SECRET_FIXTURE),
        expected_trigger_id=TRIGGER_ID,
        expected_trigger_origin=TRIGGER_ORIGIN,
        expected_agent_endpoint=AGENT_ENDPOINT,
        target_prefix=TARGET_PREFIX,
    )

    assert report["status"] == "component-validation-passed"
    assert report["readinessSource"] == "component-validation"
    assert report["status"] not in {
        "ready-for-approved-enable-plan",
        "ready-for-approved-trigger-canary",
    }


def test_same_process_rbac_collector_still_requires_full_live_gate() -> None:
    module = _load_module()
    runner, calls, responses = _live_runner(module)

    report = _collect_live(module, runner)

    assert report["status"] == "live-rbac-valid"
    assert report["readinessSource"] == "live-fixed-command-collector"
    assert report["blockers"] == [
        "full live readiness collector required before canary"
    ]
    assert report["checks"]["rbac"]["status"] == "live-rbac-valid"
    assert report["rbacCollection"]["rawEvidenceRetainedInOutput"] is False
    assert len(calls) == 8
    account_calls = [call for call in calls if call[:3] == ("az", "account", "list")]
    assert account_calls == [
        (
            "az",
            "account",
            "list",
            "--all",
            "--refresh",
            "--only-show-errors",
            "-o",
            "json",
        )
    ]
    assignment_calls = [
        call for call in calls if call[:4] == ("az", "role", "assignment", "list")
    ]
    assert len(assignment_calls) == 4
    assert all(
        "--include-inherited" in call and "--include-groups" in call
        for call in assignment_calls
    )
    assert len([call for call in assignment_calls if "--all" in call]) == 2
    assert len([call for call in assignment_calls if "--scope" in call]) == 2
    role_calls = [
        call for call in calls if call[:4] == ("az", "role", "definition", "list")
    ]
    assert len(role_calls) == 3
    for provenance in report["commandProvenance"]:
        argv = tuple(provenance["argv"])
        raw = json.dumps(responses[argv], separators=(",", ":")).encode()
        assert provenance["exitCode"] == 0
        assert provenance["stdoutByteCount"] == len(raw)
        assert provenance["stdoutSha256"] == module.hashlib.sha256(raw).hexdigest()
        assert provenance["parsedRowCount"] == len(responses[argv])


@pytest.mark.parametrize(
    ("returncode", "stdout", "stderr", "message"),
    [
        (1, b"[]", b"", "failed"),
        (0, b"not-json", b"", "malformed"),
        (0, b"[]", b"warning", "stderr"),
    ],
)
def test_live_collector_rejects_command_failures(
    returncode: int,
    stdout: bytes,
    stderr: bytes,
    message: str,
) -> None:
    module = _load_module()

    with pytest.raises(module.ReadinessError, match=message):
        _collect_live(module, lambda _argv: (returncode, stdout, stderr))


def test_live_collector_omitted_required_assignment_cannot_return_ready() -> None:
    module = _load_module()
    runner, _calls, _responses = _live_runner(module, sre_rows=[])

    with pytest.raises(module.ReadinessError, match=module.PATCH_ROLE_NAME):
        _collect_live(module, runner)


def test_live_collector_commands_are_read_only() -> None:
    module = _load_module()
    runner, calls, _responses = _live_runner(module)

    _collect_live(module, runner)

    allowed = {
        ("az", "account", "list"),
        ("az", "role", "assignment", "list"),
        ("az", "role", "definition", "list"),
    }
    for call in calls:
        assert any(call[: len(prefix)] == prefix for prefix in allowed)
        assert not {
            "create",
            "delete",
            "set",
            "update",
            "write",
            "assign",
            "remove",
        }.intersection(part.casefold() for part in call)


def test_live_predeploy_collects_all_gates_with_fixed_commands() -> None:
    module = _load_module()
    runner, requester, calls, _app_state = _all_live_dependencies(module)
    secret_id = _fixture(SECRET_FIXTURE)["metadata"]["id"]

    report = module.collect_live_predeploy(
        runner=runner,
        http_requester=requester,
        definition=_fixture(DEFINITION),
        expected_trigger_id=TRIGGER_ID,
        expected_trigger_origin=TRIGGER_ORIGIN,
        expected_agent_endpoint=AGENT_ENDPOINT,
        secret_version=SECRET_VERSION,
        target_prefix=TARGET_PREFIX,
    )

    assert report["status"] == "ready-for-approved-enable-plan"
    assert report["readinessStage"] == "live-predeploy"
    assert report["blockers"] == []
    assert (
        "az",
        "rest",
        "--method",
        "get",
        "--url",
        module.AGENT_ARM_URL,
        "--only-show-errors",
        "-o",
        "json",
    ) in calls
    assert any(
        call[:3] == ("az", "account", "get-access-token")
        and call[call.index("--resource") + 1] == "https://azuresre.dev"
        for call in calls
    )
    secret_call = next(
        call for call in calls if call[:4] == ("az", "keyvault", "secret", "show")
    )
    assert secret_call[secret_call.index("--id") + 1] == secret_id
    assert "value" not in secret_call[secret_call.index("--query") + 1]
    http_provenance = next(
        row for row in report["commandProvenance"] if row["argv"][0] == "HTTP"
    )
    assert http_provenance["redirectsFollowed"] is False
    assert http_provenance["authorizationExcluded"] is True


def test_live_canary_requires_same_process_deployed_aca_state() -> None:
    module = _load_module()
    runner, requester, calls, _app_state = _all_live_dependencies(module)

    report = module.collect_live_canary(
        runner=runner,
        http_requester=requester,
        definition=_fixture(DEFINITION),
        expected_trigger_id=TRIGGER_ID,
        expected_trigger_origin=TRIGGER_ORIGIN,
        expected_agent_endpoint=AGENT_ENDPOINT,
        secret_version=SECRET_VERSION,
        target_prefix=TARGET_PREFIX,
    )

    assert report["status"] == "ready-for-approved-trigger-canary"
    assert report["readinessStage"] == "live-canary"
    app_call = next(
        call for call in calls if call[:3] == ("az", "containerapp", "show")
    )
    assert app_call[app_call.index("--subscription") + 1] == module.SUBSCRIPTION_ID
    assert (
        app_call[app_call.index("--resource-group") + 1]
        == module.API_CONTAINER_APP_RESOURCE_GROUP
    )
    assert app_call[app_call.index("--name") + 1] == module.API_CONTAINER_APP_NAME


def test_live_canary_blocks_when_deployed_aca_is_not_enabled() -> None:
    module = _load_module()
    runner, requester, _calls, _app_state = _all_live_dependencies(
        module,
        deployed=False,
    )

    report = module.collect_live_canary(
        runner=runner,
        http_requester=requester,
        definition=_fixture(DEFINITION),
        expected_trigger_id=TRIGGER_ID,
        expected_trigger_origin=TRIGGER_ORIGIN,
        expected_agent_endpoint=AGENT_ENDPOINT,
        secret_version=SECRET_VERSION,
        target_prefix=TARGET_PREFIX,
    )

    assert report["status"] == "blocked"
    assert report["readinessStage"] == "live-canary"
    assert report["checks"]["containerApp"]["status"] == "blocked"


@pytest.mark.parametrize(
    "argument",
    ["--agent-json", "--trigger-json", "--secret-json", "--definition"],
)
def test_production_live_modes_reject_fixture_replay_arguments(
    argument: str,
) -> None:
    module = _load_module()

    with pytest.raises(SystemExit) as excinfo:
        module.main(["live-predeploy", argument, str(AGENT_FIXTURE)])

    assert excinfo.value.code == 2


def test_trigger_http_failure_never_exposes_token() -> None:
    module = _load_module()
    runner, _requester, _calls, _app_state = _all_live_dependencies(module)
    token = "secret-token"

    with pytest.raises(module.ReadinessError) as excinfo:
        module.collect_live_predeploy(
            runner=runner,
            http_requester=lambda _url, observed: (_ for _ in ()).throw(
                RuntimeError(f"failure {observed}")
            ),
            definition=_fixture(DEFINITION),
            expected_trigger_id=TRIGGER_ID,
            expected_trigger_origin=TRIGGER_ORIGIN,
            expected_agent_endpoint=AGENT_ENDPOINT,
            secret_version=SECRET_VERSION,
            target_prefix=TARGET_PREFIX,
        )

    assert token not in str(excinfo.value)


@pytest.mark.parametrize(
    ("surface", "name", "value"),
    [
        ("env", "AIOPS_SRE_AGENT_TRIGGER_SCOPE", "wrong/.default"),
        ("env", "AIOPS_SRE_AGENT_THREAD_SCOPE", "wrong/.default"),
        ("secret", "identity", "/subscriptions/wrong/identity"),
    ],
)
def test_live_canary_rejects_scope_or_secret_identity_drift(
    surface: str,
    name: str,
    value: str,
) -> None:
    module = _load_module()
    runner, requester, _calls, app_state = _all_live_dependencies(module)
    if surface == "env":
        next(row for row in app_state["env"] if row["name"] == name)["value"] = value
    else:
        app_state["secrets"][0][name] = value

    report = module.collect_live_canary(
        runner=runner,
        http_requester=requester,
        definition=_fixture(DEFINITION),
        expected_trigger_id=TRIGGER_ID,
        expected_trigger_origin=TRIGGER_ORIGIN,
        expected_agent_endpoint=AGENT_ENDPOINT,
        secret_version=SECRET_VERSION,
        target_prefix=TARGET_PREFIX,
    )

    assert report["status"] == "blocked"
    assert report["checks"]["containerApp"]["status"] == "blocked"


def test_default_http_requester_disables_redirects_and_scrubs_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    observed = {}

    class Response:
        status = 200

        def __init__(self):
            self.headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b"[]"

    class Opener:
        def open(self, request, timeout):
            observed["request"] = request
            observed["timeout"] = timeout
            observed["authorization"] = request.headers["Authorization"]
            return Response()

    def build(handler):
        observed["handler"] = handler
        return Opener()

    monkeypatch.setattr(module, "build_opener", build)

    status, body, headers = module._http_requester(
        f"{AGENT_ENDPOINT}/api/v1/httptriggers",
        "sentinel-http-token",
    )

    assert status == 200
    assert body == b"[]"
    assert headers == {}
    assert observed["authorization"].endswith("sentinel-http-token")
    assert isinstance(observed["handler"], module._NoRedirect)
    assert observed["handler"].redirect_request(None, None, 302, "", {}, "") is None
    assert "Authorization" not in observed["request"].headers


def test_default_http_requester_scrubs_transport_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()

    class Opener:
        def open(self, _request, timeout):
            raise module.URLError("secret-token")

    monkeypatch.setattr(module, "build_opener", lambda _handler: Opener())

    with pytest.raises(module.ReadinessError) as excinfo:
        module._http_requester(
            f"{AGENT_ENDPOINT}/api/v1/httptriggers",
            "secret-token",
        )

    assert "secret-token" not in str(excinfo.value)


def test_live_collector_queries_both_principals_in_every_visible_subscription() -> None:
    module = _load_module()
    runner, calls, responses = _live_runner(module)
    other = "00000000-0000-0000-0000-000000000000"
    account_argv = next(
        command for command in responses if command[:3] == ("az", "account", "list")
    )
    responses[account_argv].append(
        {"id": other, "tenantId": module.TENANT_ID, "state": "Enabled"}
    )
    for principal_id in (
        module.API_UAI_PRINCIPAL_ID,
        module.SRE_UAI_PRINCIPAL_ID,
    ):
        responses[
            (
                "az",
                "role",
                "assignment",
                "list",
                "--subscription",
                other,
                "--assignee-object-id",
                principal_id,
                "--all",
                "--include-inherited",
                "--include-groups",
                "--only-show-errors",
                "-o",
                "json",
            )
        ] = []
        responses[
            (
                "az",
                "role",
                "assignment",
                "list",
                "--subscription",
                other,
                "--assignee-object-id",
                principal_id,
                "--scope",
                f"/subscriptions/{other}",
                "--include-inherited",
                "--include-groups",
                "--only-show-errors",
                "-o",
                "json",
            )
        ] = []

    report = _collect_live(module, runner)

    assert report["status"] == "live-rbac-valid"
    assignment_calls = [
        call for call in calls if call[:4] == ("az", "role", "assignment", "list")
    ]
    assert {
        (
            call[call.index("--subscription") + 1],
            call[call.index("--assignee-object-id") + 1],
        )
        for call in assignment_calls
    } == {
        (subscription_id, principal_id)
        for subscription_id in (module.SUBSCRIPTION_ID, other)
        for principal_id in (
            module.API_UAI_PRINCIPAL_ID,
            module.SRE_UAI_PRINCIPAL_ID,
        )
    }


def test_collect_live_rbac_cli_never_claims_canary_readiness(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_module()
    runner, _calls, _responses = _live_runner(module)
    monkeypatch.setattr(module, "_subprocess_runner", runner)

    code = module.main(
        [
            "collect-live-rbac",
            "--target-prefix",
            TARGET_PREFIX,
        ]
    )

    assert code == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "live-rbac-valid"
    assert result["readyForApprovedTriggerCanary"] is False
    assert result["blockers"] == [
        "full live readiness collector required before canary"
    ]


def test_live_collector_writes_only_non_authorizing_sanitized_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_module()
    runner, requester, _calls, _app_state = _all_live_dependencies(module)
    monkeypatch.setattr(module, "_subprocess_runner", runner)
    monkeypatch.setattr(module, "_http_requester", requester)
    output = tmp_path / "live-rbac.informational.json"

    code = module.main(
        [
            "live-canary",
            "--expected-trigger-id",
            TRIGGER_ID,
            "--expected-trigger-origin",
            TRIGGER_ORIGIN,
            "--expected-agent-endpoint",
            AGENT_ENDPOINT,
            "--secret-version",
            SECRET_VERSION,
            "--target-prefix",
            TARGET_PREFIX,
            "--evidence-output",
            str(output),
        ]
    )

    assert code == 0
    assert output.stat().st_mode & 0o777 == 0o600
    written = json.loads(output.read_text(encoding="utf-8"))
    assert written["classification"] == "informational-live-collector-output"
    assert written["authorizesReadinessWhenReimported"] is False
    assert "rawAssignments" not in json.dumps(written)
    assert json.loads(capsys.readouterr().out)["status"] == (
        "ready-for-approved-trigger-canary"
    )


def test_live_cli_without_optional_evidence_output_returns_success(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_module()
    runner, requester, _calls, _app_state = _all_live_dependencies(module)
    monkeypatch.setattr(module, "_subprocess_runner", runner)
    monkeypatch.setattr(module, "_http_requester", requester)

    code = module.main(
        [
            "live-predeploy",
            "--expected-trigger-id",
            TRIGGER_ID,
            "--expected-trigger-origin",
            TRIGGER_ORIGIN,
            "--expected-agent-endpoint",
            AGENT_ENDPOINT,
            "--secret-version",
            SECRET_VERSION,
            "--target-prefix",
            TARGET_PREFIX,
        ]
    )

    assert code == 0
    assert json.loads(capsys.readouterr().out)["status"] == (
        "ready-for-approved-enable-plan"
    )


def test_blocked_live_collector_does_not_write_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    runner, requester, _calls, _app_state = _all_live_dependencies(
        module,
        deployed=False,
    )
    monkeypatch.setattr(module, "_subprocess_runner", runner)
    monkeypatch.setattr(module, "_http_requester", requester)
    output = tmp_path / "blocked.json"

    code = module.main(
        [
            "live-canary",
            "--expected-trigger-id",
            TRIGGER_ID,
            "--expected-trigger-origin",
            TRIGGER_ORIGIN,
            "--expected-agent-endpoint",
            AGENT_ENDPOINT,
            "--secret-version",
            SECRET_VERSION,
            "--target-prefix",
            TARGET_PREFIX,
            "--evidence-output",
            str(output),
        ]
    )

    assert code == 2
    assert not output.exists()


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("runMode", "Review"),
        ("threadGrouping", "SameThread"),
        ("prompt", "Install available patches."),
        ("artifactVersion", "2.0"),
    ],
)
def test_trigger_drift_is_detected(field: str, replacement: object) -> None:
    module = _load_module()
    trigger = _fixture(TRIGGER_FIXTURE)
    trigger["trigger"][field] = replacement

    with pytest.raises(module.ReadinessError, match="drift detected"):
        module.validate_trigger_evidence(
            trigger,
            module.canonical_trigger_body(_fixture(DEFINITION)),
            expected_trigger_id=TRIGGER_ID,
            expected_trigger_origin=TRIGGER_ORIGIN,
        )


def test_trigger_payload_schema_mismatch_is_detected() -> None:
    module = _load_module()
    trigger = _fixture(TRIGGER_FIXTURE)
    trigger["trigger"]["payloadSchema"]["properties"]["operation"] = {
        "const": "assess_patches"
    }

    with pytest.raises(module.ReadinessError, match="drift detected"):
        module.validate_trigger_evidence(
            trigger,
            module.canonical_trigger_body(_fixture(DEFINITION)),
            expected_trigger_id=TRIGGER_ID,
            expected_trigger_origin=TRIGGER_ORIGIN,
        )


def test_real_live_trigger_shape_normalizes_and_passes_readiness() -> None:
    module = _load_module()
    normalized = module._normalize_live_trigger(
        [_real_live_trigger_row(module, description="")],
        expected_trigger_id=REAL_TRIGGER_ID,
        expected_trigger_origin=TRIGGER_ORIGIN,
    )

    result = module.validate_trigger_evidence(
        normalized,
        module.canonical_trigger_body(_fixture(DEFINITION)),
        expected_trigger_id=REAL_TRIGGER_ID,
        expected_trigger_origin=TRIGGER_ORIGIN,
        definition=_fixture(DEFINITION),
    )

    assert result["status"] == "trigger-ready"
    assert result["triggerId"] == REAL_TRIGGER_ID
    assert result["description"] == {
        "serverDescriptionAvailable": False,
        "serverDescriptionStatus": "not-returned-or-empty-by-live-api",
        "validatedAgainst": "canonical-definition-hash",
    }
    assert result["payloadSchema"] == {
        "status": "runtime-outbound-envelope-ready",
        "source": "src.operations.patching.sre_agent_adapter",
        "serverPayloadSchemaAvailable": False,
        "serverPayloadSchemaStatus": "not-returned-by-live-api",
        "validatedAgainst": "runtime-locked-outgoing-envelope",
    }


def test_real_live_trigger_row_uses_exact_observed_production_keys() -> None:
    module = _load_module()

    expected = {
        "agent",
        "agentMode",
        "agentPrompt",
        "createdAt",
        "createdBy",
        "description",
        "executionCount",
        "id",
        "lastExecutionTime",
        "modelTier",
        "name",
        "threadId",
        "triggerEnabled",
        "triggerLastCalledAt",
        "triggerUrl",
    }
    assert len(expected) == 15
    assert module.RAW_LIVE_TRIGGER_FIELDS == expected
    assert set(_real_live_trigger_row(module)) == expected


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"agentPrompt": "Install available patches."}, "trigger drift detected"),
        ({"agentMode": "review"}, "agentMode must be autonomous"),
        ({"triggerEnabled": False}, "trigger must be enabled"),
        ({"threadId": "shared-thread"}, "threadId must be empty"),
        ({"agent": "other-agent"}, "response agent must remain the default"),
        ({"description": "different description"}, "trigger drift detected"),
        ({"id": "wrong-trigger-id"}, "exact trigger once"),
        (
            {
                "triggerUrl": (
                    "https://evil.example/api/v1/httptriggers/trigger/"
                    f"{REAL_TRIGGER_ID}"
                )
            },
            "invocation origin does not match",
        ),
    ],
)
def test_real_live_trigger_shape_drift_fails_closed(
    overrides: dict[str, object],
    expected: str,
) -> None:
    module = _load_module()
    with pytest.raises(module.ReadinessError, match=expected):
        normalized = module._normalize_live_trigger(
            [_real_live_trigger_row(module, **overrides)],
            expected_trigger_id=REAL_TRIGGER_ID,
            expected_trigger_origin=TRIGGER_ORIGIN,
        )
        module.validate_trigger_evidence(
            normalized,
            module.canonical_trigger_body(_fixture(DEFINITION)),
            expected_trigger_id=REAL_TRIGGER_ID,
            expected_trigger_origin=TRIGGER_ORIGIN,
            definition=_fixture(DEFINITION),
        )


@pytest.mark.parametrize("mutation", ["missing", "extra", "url-alias"])
def test_real_live_trigger_shape_must_be_exact(mutation: str) -> None:
    module = _load_module()
    row = _real_live_trigger_row(module)
    if mutation == "missing":
        del row["description"]
    elif mutation == "extra":
        row["unexpected"] = "field"
    else:
        row["url"] = row.pop("triggerUrl")

    with pytest.raises(module.ReadinessError, match="fields do not match"):
        module._normalize_live_trigger(
            [row],
            expected_trigger_id=REAL_TRIGGER_ID,
            expected_trigger_origin=TRIGGER_ORIGIN,
        )


@pytest.mark.parametrize("suffix", ["?api-version=1", "#fragment", "/extra"])
def test_real_live_trigger_url_must_be_exact(suffix: str) -> None:
    module = _load_module()
    row = _real_live_trigger_row(module)
    row["triggerUrl"] += suffix

    with pytest.raises(module.ReadinessError, match="invocation URL"):
        module._normalize_live_trigger(
            [row],
            expected_trigger_id=REAL_TRIGGER_ID,
            expected_trigger_origin=TRIGGER_ORIGIN,
        )


def test_runtime_outbound_envelope_drift_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    import src.operations.patching.sre_agent_adapter as adapter

    original = adapter.sre_agent_patch_envelope_contract

    def drifted_contract() -> dict[str, object]:
        contract = original()
        properties = contract["properties"]
        assert isinstance(properties, dict)
        properties["operation"] = {"const": "assess_patches"}
        return contract

    monkeypatch.setattr(adapter, "sre_agent_patch_envelope_contract", drifted_contract)
    normalized = module._normalize_live_trigger(
        [_real_live_trigger_row(module)],
        expected_trigger_id=REAL_TRIGGER_ID,
        expected_trigger_origin=TRIGGER_ORIGIN,
    )

    with pytest.raises(module.ReadinessError, match="runtime outbound.*drift"):
        module.validate_trigger_evidence(
            normalized,
            module.canonical_trigger_body(_fixture(DEFINITION)),
            expected_trigger_id=REAL_TRIGGER_ID,
            expected_trigger_origin=TRIGGER_ORIGIN,
            definition=_fixture(DEFINITION),
        )


def test_same_origin_wrong_trigger_id_is_rejected() -> None:
    module = _load_module()

    with pytest.raises(module.ReadinessError, match="reviewed trigger ID"):
        module.validate_trigger_evidence(
            _fixture(TRIGGER_FIXTURE),
            module.canonical_trigger_body(_fixture(DEFINITION)),
            expected_trigger_id="different-trigger-id",
            expected_trigger_origin=TRIGGER_ORIGIN,
        )


def test_trigger_origin_is_independent_of_agent_endpoint() -> None:
    module = _load_module()
    result = module.validate_trigger_evidence(
        _fixture(TRIGGER_FIXTURE),
        module.canonical_trigger_body(_fixture(DEFINITION)),
        expected_trigger_id=TRIGGER_ID,
        expected_trigger_origin=TRIGGER_ORIGIN,
    )

    assert result["triggerId"] == TRIGGER_ID
    assert result["triggerOrigin"] == TRIGGER_ORIGIN
    with pytest.raises(module.ReadinessError, match="reviewed origin"):
        module.validate_trigger_evidence(
            _fixture(TRIGGER_FIXTURE),
            module.canonical_trigger_body(_fixture(DEFINITION)),
            expected_trigger_id=TRIGGER_ID,
            expected_trigger_origin=AGENT_ENDPOINT,
        )


def test_agent_endpoint_and_managed_resource_coverage_are_exact() -> None:
    module = _load_module()
    agent = _fixture(AGENT_FIXTURE)

    with pytest.raises(module.ReadinessError, match="reviewed endpoint"):
        module.validate_agent_resource(
            agent,
            expected_agent_endpoint="https://other.azuresre.ai",
            target_prefix=TARGET_PREFIX,
        )

    agent["resource"]["properties"]["knowledgeGraphConfiguration"][
        "managedResources"
    ] = [("/subscriptions/a87a8e64-a52a-4aa8-a760-5e8919d23cd1/resourceGroups/other")]
    with pytest.raises(module.ReadinessError, match="do not cover"):
        module.validate_agent_resource(
            agent,
            expected_agent_endpoint=AGENT_ENDPOINT,
            target_prefix=TARGET_PREFIX,
        )


def test_rbac_builder_binds_complete_raw_rows_and_definitions() -> None:
    module = _load_module()
    fixture = _fixture(RBAC_FIXTURE)
    assignments = [
        (
            capture["principalId"],
            capture["subscriptionId"],
            capture["rawAssignments"],
        )
        for capture in fixture["assignmentCaptures"]
    ]
    definitions = [capture["raw"] for capture in fixture["roleDefinitionCaptures"]]

    built = module.build_rbac_evidence(
        visible_subscription_ids=fixture["visibleTenantSubscriptionIds"],
        assignment_captures=assignments,
        role_definitions=definitions,
    )

    assert built == fixture
    result = module.validate_rbac_evidence(
        built,
        target_prefix=TARGET_PREFIX,
    )
    assert result["status"] == "offline-evidence-valid"
    assert result["blockers"] == ["fresh live collector required"]


def test_manually_normalized_assignment_arrays_are_rejected() -> None:
    module = _load_module()
    rbac = _fixture(RBAC_FIXTURE)
    rbac["principals"] = []
    del rbac["assignmentCaptures"]

    with pytest.raises(module.ReadinessError, match="fields do not match"):
        module.validate_rbac_evidence(rbac, target_prefix=TARGET_PREFIX)


def test_build_rbac_cli_ingests_raw_azure_lists(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_module()
    fixture = _fixture(RBAC_FIXTURE)
    visible = tmp_path / "visible.json"
    api_assignments = tmp_path / "api.json"
    sre_assignments = tmp_path / "sre.json"
    roles = tmp_path / "roles.json"
    visible.write_text(
        json.dumps(fixture["visibleTenantSubscriptionIds"]),
        encoding="utf-8",
    )
    api_assignments.write_text(
        json.dumps(fixture["assignmentCaptures"][0]["rawAssignments"]),
        encoding="utf-8",
    )
    sre_assignments.write_text(
        json.dumps(fixture["assignmentCaptures"][1]["rawAssignments"]),
        encoding="utf-8",
    )
    roles.write_text(
        json.dumps([capture["raw"] for capture in fixture["roleDefinitionCaptures"]]),
        encoding="utf-8",
    )

    code = module.main(
        [
            "build-rbac",
            "--visible-subscriptions-json",
            str(visible),
            "--api-inherited-assignment-json",
            f"{module.SUBSCRIPTION_ID}={api_assignments}",
            "--sre-inherited-assignment-json",
            f"{module.SUBSCRIPTION_ID}={sre_assignments}",
            "--role-definitions-json",
            str(roles),
            "--target-prefix",
            TARGET_PREFIX,
        ]
    )

    assert code == 0
    assert json.loads(capsys.readouterr().out) == {
        "status": "offline-evidence-valid",
        "blockers": ["fresh live collector required"],
        "rbacEvidence": fixture,
    }


@pytest.mark.parametrize(
    ("role_index", "field", "replacement"),
    [
        (0, "dataActions", ["Microsoft.App/agents/*"]),
        (0, "actions", ["Microsoft.App/agents/read"]),
        (
            1,
            "actions",
            ["Microsoft.Compute/virtualMachines/installPatches/action"],
        ),
        (1, "dataActions", ["Microsoft.App/agents/threads/read"]),
    ],
)
def test_custom_role_permissions_must_be_exact(
    role_index: int,
    field: str,
    replacement: list[str],
) -> None:
    module = _load_module()
    rbac = _fixture(RBAC_FIXTURE)
    rbac["roleDefinitionCaptures"][role_index]["raw"]["permissions"][0][field] = (
        replacement
    )
    _refresh_rbac_provenance(module, rbac)

    with pytest.raises(module.ReadinessError, match="permissions drifted"):
        module.validate_rbac_evidence(rbac, target_prefix=TARGET_PREFIX)


def test_custom_role_assignments_must_use_exact_scopes() -> None:
    module = _load_module()
    rbac = _fixture(RBAC_FIXTURE)
    rbac["assignmentCaptures"][0]["rawAssignments"][0]["scope"] = (
        f"/subscriptions/{module.SUBSCRIPTION_ID}"
    )
    _refresh_rbac_provenance(module, rbac)

    with pytest.raises(module.ReadinessError, match="exact scope"):
        module.validate_rbac_evidence(rbac, target_prefix=TARGET_PREFIX)


@pytest.mark.parametrize(
    ("capture_index", "assignment_index"),
    [(0, 0), (0, 1), (1, 0)],
)
def test_sensitive_same_role_assignment_at_broader_scope_is_rejected(
    capture_index: int,
    assignment_index: int,
) -> None:
    module = _load_module()
    rbac = _fixture(RBAC_FIXTURE)
    assignment = copy.deepcopy(
        rbac["assignmentCaptures"][capture_index]["rawAssignments"][assignment_index]
    )
    assignment["scope"] = f"/subscriptions/{module.SUBSCRIPTION_ID}"
    rbac["assignmentCaptures"][capture_index]["rawAssignments"].append(assignment)
    _refresh_rbac_provenance(module, rbac)

    with pytest.raises(module.ReadinessError, match="broader fallback"):
        module.validate_rbac_evidence(rbac, target_prefix=TARGET_PREFIX)


@pytest.mark.parametrize("mutation", ["missing", "extra"])
def test_raw_assignment_row_count_and_digest_reject_omission_or_extra(
    mutation: str,
) -> None:
    module = _load_module()
    rbac = _fixture(RBAC_FIXTURE)
    rows = rbac["assignmentCaptures"][0]["rawAssignments"]
    if mutation == "missing":
        rows.pop()
    else:
        rows.append(copy.deepcopy(rows[0]))

    with pytest.raises(module.ReadinessError, match="row count"):
        module.validate_rbac_evidence(rbac, target_prefix=TARGET_PREFIX)


def test_raw_assignment_digest_rejects_sanitized_rewrite() -> None:
    module = _load_module()
    rbac = _fixture(RBAC_FIXTURE)
    rbac["assignmentCaptures"][0]["rawAssignments"][0]["scope"] = (
        f"/subscriptions/{module.SUBSCRIPTION_ID}"
    )

    with pytest.raises(module.ReadinessError, match="digest"):
        module.validate_rbac_evidence(rbac, target_prefix=TARGET_PREFIX)


def test_raw_capture_rejects_missing_or_duplicate_query_coverage() -> None:
    module = _load_module()
    missing = _fixture(RBAC_FIXTURE)
    missing["assignmentCaptures"].pop()
    with pytest.raises(module.ReadinessError, match="do not cover"):
        module.validate_rbac_evidence(missing, target_prefix=TARGET_PREFIX)

    duplicate = _fixture(RBAC_FIXTURE)
    duplicate["assignmentCaptures"].append(
        copy.deepcopy(duplicate["assignmentCaptures"][0])
    )
    with pytest.raises(module.ReadinessError, match="duplicate principal/subscription"):
        module.validate_rbac_evidence(duplicate, target_prefix=TARGET_PREFIX)


def test_raw_capture_rejects_misattributed_principal() -> None:
    module = _load_module()
    rbac = _fixture(RBAC_FIXTURE)
    rbac["assignmentCaptures"][0]["rawAssignments"][0]["principalId"] = (
        module.SRE_UAI_PRINCIPAL_ID
    )
    _refresh_rbac_provenance(module, rbac)

    with pytest.raises(module.ReadinessError, match="misattributed"):
        module.validate_rbac_evidence(rbac, target_prefix=TARGET_PREFIX)


@pytest.mark.parametrize(
    ("name", "actions", "data_actions", "principal_index"),
    [
        ("Owner group", ["*"], [], 1),
        ("Contributor group", ["Microsoft.Compute/*"], [], 1),
        (
            "Patch wildcard group",
            ["Microsoft.HybridCompute/machines/*"],
            [],
            1,
        ),
        (
            "Thread wildcard group",
            [],
            ["Microsoft.App/agents/threads/*"],
            0,
        ),
    ],
)
def test_group_derived_broad_roles_block_effective_uai_access(
    name: str,
    actions: list[str],
    data_actions: list[str],
    principal_index: int,
) -> None:
    module = _load_module()
    fixture = _fixture(RBAC_FIXTURE)
    role_id = (
        f"/subscriptions/{module.SUBSCRIPTION_ID}/providers/"
        "Microsoft.Authorization/roleDefinitions/"
        f"40000000-0000-0000-0000-00000000000{principal_index}"
    )
    raw_role = {
        "id": role_id,
        "roleName": name,
        "assignableScopes": [f"/subscriptions/{module.SUBSCRIPTION_ID}"],
        "permissions": [
            {
                "actions": actions,
                "notActions": [],
                "dataActions": data_actions,
                "notDataActions": [],
            }
        ],
    }
    assignments = [
        (
            capture["principalId"],
            capture["subscriptionId"],
            list(capture["rawAssignments"]),
        )
        for capture in fixture["assignmentCaptures"]
    ]
    assignments[principal_index][2].append(
        {
            "scope": (
                TARGET_PREFIX if principal_index == 1 else module.AGENT_RESOURCE_ID
            ),
            "roleDefinitionId": role_id,
            "principalId": "50000000-0000-0000-0000-000000000001",
            "principalType": "Group",
            "condition": None,
        }
    )
    built = module.build_rbac_evidence(
        visible_subscription_ids=fixture["visibleTenantSubscriptionIds"],
        assignment_captures=assignments,
        role_definitions=[
            capture["raw"] for capture in fixture["roleDefinitionCaptures"]
        ]
        + [raw_role],
    )

    with pytest.raises(module.ReadinessError, match="broader fallback"):
        module.validate_rbac_evidence(built, target_prefix=TARGET_PREFIX)


def test_group_assignment_cannot_satisfy_required_direct_role() -> None:
    module = _load_module()
    rbac = _fixture(RBAC_FIXTURE)
    direct = rbac["assignmentCaptures"][1]["rawAssignments"][0]
    direct["principalId"] = "50000000-0000-0000-0000-000000000001"
    direct["principalType"] = "Group"
    _refresh_rbac_provenance(module, rbac)

    with pytest.raises(module.ReadinessError, match="must exist exactly once"):
        module.validate_rbac_evidence(rbac, target_prefix=TARGET_PREFIX)


def test_live_collector_blocks_management_group_inherited_group_owner() -> None:
    module = _load_module()
    runner, _calls, responses = _live_runner(module)
    management_group_scope = (
        "/providers/Microsoft.Management/managementGroups/mg-platform"
    )
    role_id = (
        f"{management_group_scope}/providers/Microsoft.Authorization/"
        "roleDefinitions/60000000-0000-0000-0000-000000000001"
    )
    inherited_argv = next(
        command
        for command in responses
        if command[:4] == ("az", "role", "assignment", "list")
        and command[command.index("--assignee-object-id") + 1]
        == module.SRE_UAI_PRINCIPAL_ID
        and "--scope" in command
    )
    responses[inherited_argv] = list(responses[inherited_argv]) + [
        {
            "id": f"{management_group_scope}/providers/Microsoft.Authorization/roleAssignments/assignment-1",
            "scope": management_group_scope,
            "roleDefinitionId": role_id,
            "principalId": "50000000-0000-0000-0000-000000000001",
            "principalType": "Group",
            "condition": None,
        }
    ]
    responses[
        (
            "az",
            "role",
            "definition",
            "list",
            "--name",
            "60000000-0000-0000-0000-000000000001",
            "--scope",
            management_group_scope,
            "--only-show-errors",
            "-o",
            "json",
        )
    ] = [
        {
            "id": role_id,
            "roleName": "Inherited Owner group",
            "assignableScopes": [management_group_scope],
            "permissions": [
                {
                    "actions": ["*"],
                    "notActions": [],
                    "dataActions": [],
                    "notDataActions": [],
                }
            ],
        }
    ]

    with pytest.raises(module.ReadinessError, match="broader fallback"):
        _collect_live(module, runner)


def test_raw_capture_rejects_non_inherited_and_out_of_subscription_rows() -> None:
    module = _load_module()
    not_inherited = _fixture(RBAC_FIXTURE)
    not_inherited["assignmentCaptures"][1]["includeInherited"] = False
    with pytest.raises(module.ReadinessError, match="include inherited"):
        module.validate_rbac_evidence(not_inherited, target_prefix=TARGET_PREFIX)

    outside = _fixture(RBAC_FIXTURE)
    outside["assignmentCaptures"][1]["rawAssignments"][0]["scope"] = (
        "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/x"
    )
    _refresh_rbac_provenance(module, outside)
    with pytest.raises(module.ReadinessError, match="outside"):
        module.validate_rbac_evidence(outside, target_prefix=TARGET_PREFIX)


def test_raw_capture_rejects_assignments_in_another_visible_subscription() -> None:
    module = _load_module()
    fixture = _fixture(RBAC_FIXTURE)
    other = "00000000-0000-0000-0000-000000000000"
    role_id = fixture["assignmentCaptures"][1]["rawAssignments"][0]["roleDefinitionId"]
    assignments = [
        (
            capture["principalId"],
            capture["subscriptionId"],
            list(capture["rawAssignments"]),
        )
        for capture in fixture["assignmentCaptures"]
    ]
    assignments.extend(
        [
            (module.API_UAI_PRINCIPAL_ID, other, []),
            (
                module.SRE_UAI_PRINCIPAL_ID,
                other,
                [
                    {
                        "scope": f"/subscriptions/{other}/resourceGroups/other",
                        "roleDefinitionId": role_id,
                        "principalId": module.SRE_UAI_PRINCIPAL_ID,
                        "principalType": "ServicePrincipal",
                        "condition": None,
                    }
                ],
            ),
        ]
    )
    built = module.build_rbac_evidence(
        visible_subscription_ids=[module.SUBSCRIPTION_ID, other],
        assignment_captures=assignments,
        role_definitions=[
            capture["raw"] for capture in fixture["roleDefinitionCaptures"]
        ],
    )

    with pytest.raises(module.ReadinessError, match="broader fallback"):
        module.validate_rbac_evidence(built, target_prefix=TARGET_PREFIX)


def test_role_definition_capture_rejects_unknown_missing_or_extra_roles() -> None:
    module = _load_module()
    unknown = _fixture(RBAC_FIXTURE)
    unknown["roleDefinitionCaptures"].pop()
    with pytest.raises(module.ReadinessError, match="unknown role"):
        module.validate_rbac_evidence(unknown, target_prefix=TARGET_PREFIX)

    extra = _fixture(RBAC_FIXTURE)
    raw = {
        "id": (
            f"/subscriptions/{module.SUBSCRIPTION_ID}/providers/"
            "Microsoft.Authorization/roleDefinitions/"
            "10000000-0000-0000-0000-000000000009"
        ),
        "roleName": "Unreferenced",
        "assignableScopes": [f"/subscriptions/{module.SUBSCRIPTION_ID}"],
        "permissions": [
            {
                "actions": ["Microsoft.Resources/subscriptions/read"],
                "notActions": [],
                "dataActions": [],
                "notDataActions": [],
            }
        ],
    }
    extra["roleDefinitionCaptures"].append(
        {"raw": raw, "rawSha256": module._json_sha256(raw)}
    )
    with pytest.raises(module.ReadinessError, match="one-for-one"):
        module.validate_rbac_evidence(extra, target_prefix=TARGET_PREFIX)


@pytest.mark.parametrize(
    ("name", "actions"),
    [
        ("Owner", ["*"]),
        ("Contributor", ["Microsoft.Compute/*"]),
        ("Custom patch wildcard", ["Microsoft.HybridCompute/machines/*"]),
    ],
)
def test_complete_raw_ingestion_cannot_hide_patch_wildcard_assignments(
    name: str,
    actions: list[str],
) -> None:
    module = _load_module()
    fixture = _fixture(RBAC_FIXTURE)
    role_id = (
        f"/subscriptions/{module.SUBSCRIPTION_ID}/providers/"
        "Microsoft.Authorization/roleDefinitions/"
        f"20000000-0000-0000-0000-00000000000{len(actions)}"
    )
    raw_role = {
        "id": role_id,
        "roleName": name,
        "assignableScopes": [f"/subscriptions/{module.SUBSCRIPTION_ID}"],
        "permissions": [
            {
                "actions": actions,
                "notActions": [],
                "dataActions": [],
                "notDataActions": [],
            }
        ],
    }
    assignments = [
        (
            capture["principalId"],
            capture["subscriptionId"],
            list(capture["rawAssignments"]),
        )
        for capture in fixture["assignmentCaptures"]
    ]
    assignments[1][2].append(
        {
            "scope": TARGET_PREFIX,
            "roleDefinitionId": role_id,
            "principalId": module.SRE_UAI_PRINCIPAL_ID,
            "principalType": "ServicePrincipal",
            "condition": None,
        }
    )
    roles = [capture["raw"] for capture in fixture["roleDefinitionCaptures"]] + [
        raw_role
    ]
    built = module.build_rbac_evidence(
        visible_subscription_ids=fixture["visibleTenantSubscriptionIds"],
        assignment_captures=assignments,
        role_definitions=roles,
    )

    with pytest.raises(module.ReadinessError, match="broader fallback"):
        module.validate_rbac_evidence(built, target_prefix=TARGET_PREFIX)


def test_complete_raw_ingestion_cannot_hide_thread_wildcard_assignment() -> None:
    module = _load_module()
    fixture = _fixture(RBAC_FIXTURE)
    role_id = (
        f"/subscriptions/{module.SUBSCRIPTION_ID}/providers/"
        "Microsoft.Authorization/roleDefinitions/"
        "30000000-0000-0000-0000-000000000001"
    )
    raw_role = {
        "id": role_id,
        "roleName": "SRE thread wildcard",
        "assignableScopes": [f"/subscriptions/{module.SUBSCRIPTION_ID}"],
        "permissions": [
            {
                "actions": [],
                "notActions": [],
                "dataActions": ["Microsoft.App/agents/threads/*"],
                "notDataActions": [],
            }
        ],
    }
    assignments = [
        (
            capture["principalId"],
            capture["subscriptionId"],
            list(capture["rawAssignments"]),
        )
        for capture in fixture["assignmentCaptures"]
    ]
    assignments[0][2].append(
        {
            "scope": module.AGENT_RESOURCE_ID,
            "roleDefinitionId": role_id,
            "principalId": module.API_UAI_PRINCIPAL_ID,
            "principalType": "ServicePrincipal",
            "condition": None,
        }
    )
    roles = [capture["raw"] for capture in fixture["roleDefinitionCaptures"]] + [
        raw_role
    ]
    built = module.build_rbac_evidence(
        visible_subscription_ids=fixture["visibleTenantSubscriptionIds"],
        assignment_captures=assignments,
        role_definitions=roles,
    )

    with pytest.raises(module.ReadinessError, match="broader fallback"):
        module.validate_rbac_evidence(built, target_prefix=TARGET_PREFIX)


def test_secret_metadata_binds_trigger_id_origin_and_canonical_hash() -> None:
    module = _load_module()
    secret = _fixture(SECRET_FIXTURE)
    result = module.validate_secret_evidence(
        secret,
        expected_secret_id=secret["secretReference"]["keyVaultSecretId"],
        expected_trigger_id=TRIGGER_ID,
        expected_trigger_origin=TRIGGER_ORIGIN,
        expected_canonical_hash=module.canonical_hash(
            module.canonical_trigger_body(_fixture(DEFINITION))
        ),
    )

    assert result["secretValueRead"] is False
    assert result["triggerId"] == TRIGGER_ID
    for tag in (
        module.SECRET_TAG_TRIGGER_ID,
        module.SECRET_TAG_TRIGGER_ORIGIN,
        module.SECRET_TAG_CANONICAL_HASH,
    ):
        drifted = _fixture(SECRET_FIXTURE)
        drifted["metadata"]["tags"][tag] = "drifted"
        with pytest.raises(module.ReadinessError, match="attestation"):
            module.validate_secret_evidence(
                drifted,
                expected_secret_id=drifted["secretReference"]["keyVaultSecretId"],
                expected_trigger_id=TRIGGER_ID,
                expected_trigger_origin=TRIGGER_ORIGIN,
                expected_canonical_hash=module.canonical_hash(
                    module.canonical_trigger_body(_fixture(DEFINITION))
                ),
            )


def test_secret_metadata_rejects_secret_values() -> None:
    module = _load_module()
    secret = _fixture(SECRET_FIXTURE)
    secret["metadata"]["value"] = "must-not-be-read"

    with pytest.raises(module.ReadinessError, match="secret field value"):
        module.validate_secret_evidence(
            secret,
            expected_secret_id=secret["secretReference"]["keyVaultSecretId"],
            expected_trigger_id=TRIGGER_ID,
            expected_trigger_origin=TRIGGER_ORIGIN,
            expected_canonical_hash=module.canonical_hash(
                module.canonical_trigger_body(_fixture(DEFINITION))
            ),
        )


@pytest.mark.parametrize(
    "secret_id",
    [
        (
            "https://aiops-dev-kv-g6ludc.vault.azure.net/"
            "secrets/sre-agent-http-trigger-url"
        ),
        (
            "https://aiops-dev-kv-g6ludc.vault.azure.net/"
            "secrets/wrong-name/00000000000000000000000000000001"
        ),
    ],
)
def test_secret_reference_requires_exact_name_and_version(secret_id: str) -> None:
    module = _load_module()
    secret = _fixture(SECRET_FIXTURE)
    secret["secretReference"]["keyVaultSecretId"] = secret_id

    with pytest.raises(module.ReadinessError, match="versioned Azure Key Vault URI"):
        module.validate_secret_evidence(
            secret,
            expected_secret_id=secret["secretReference"]["keyVaultSecretId"],
            expected_trigger_id=TRIGGER_ID,
            expected_trigger_origin=TRIGGER_ORIGIN,
            expected_canonical_hash=module.canonical_hash(
                module.canonical_trigger_body(_fixture(DEFINITION))
            ),
        )


def test_secret_metadata_version_must_equal_reference() -> None:
    module = _load_module()
    secret = _fixture(SECRET_FIXTURE)
    secret["metadata"]["id"] = secret["metadata"]["id"].rsplit("/", 1)[0] + "/other"

    with pytest.raises(module.ReadinessError, match="does not match"):
        module.validate_secret_evidence(
            secret,
            expected_secret_id=secret["secretReference"]["keyVaultSecretId"],
            expected_trigger_id=TRIGGER_ID,
            expected_trigger_origin=TRIGGER_ORIGIN,
            expected_canonical_hash=module.canonical_hash(
                module.canonical_trigger_body(_fixture(DEFINITION))
            ),
        )


def test_same_name_and_version_in_other_vault_is_rejected() -> None:
    module = _load_module()
    secret = _fixture(SECRET_FIXTURE)
    other_id = (
        "https://other-vault.vault.azure.net/secrets/"
        f"{module.SECRET_NAME}/{SECRET_VERSION}"
    )
    secret["secretReference"]["keyVaultSecretId"] = other_id
    secret["metadata"]["id"] = other_id

    with pytest.raises(module.ReadinessError, match="canonical Key Vault"):
        module._validate_secret_against_artifact(
            _fixture(DEFINITION),
            secret,
            expected_trigger_id=TRIGGER_ID,
            expected_trigger_origin=TRIGGER_ORIGIN,
            expected_canonical_hash=module.canonical_hash(
                module.canonical_trigger_body(_fixture(DEFINITION))
            ),
        )


@pytest.mark.parametrize(
    "origin",
    [
        "https://localhost",
        "https://127.0.0.1",
        "https://[::1]",
    ],
)
def test_preflight_origin_validation_matches_runtime(origin: str) -> None:
    module = _load_module()

    with pytest.raises(module.ReadinessError, match="public DNS"):
        module.validate_trigger_evidence(
            _fixture(TRIGGER_FIXTURE),
            module.canonical_trigger_body(_fixture(DEFINITION)),
            expected_trigger_id=TRIGGER_ID,
            expected_trigger_origin=origin,
        )


@pytest.mark.parametrize(
    "managed_scope",
    [
        ("/subscriptions/a87a8e64-a52a-4aa8-a760-5e8919d23cd1/resourceGroups"),
        (
            "/subscriptions/a87a8e64-a52a-4aa8-a760-5e8919d23cd1/"
            "resourceGroups/rg-sredemo-dev/not-a-provider/not-a-resource"
        ),
        (
            "/subscriptions/a87a8e64-a52a-4aa8-a760-5e8919d23cd1/"
            "resourceGroups/rg-sredemo-dev/"
        ),
        (
            " /subscriptions/a87a8e64-a52a-4aa8-a760-5e8919d23cd1/"
            "resourceGroups/rg-sredemo-dev"
        ),
    ],
)
def test_managed_resource_scope_must_be_canonical(managed_scope: str) -> None:
    module = _load_module()
    agent = _fixture(AGENT_FIXTURE)
    agent["resource"]["properties"]["knowledgeGraphConfiguration"][
        "managedResources"
    ] = [managed_scope]

    with pytest.raises(module.ReadinessError, match="canonical|ARM"):
        module.validate_agent_resource(
            agent,
            expected_agent_endpoint=AGENT_ENDPOINT,
            target_prefix=TARGET_PREFIX,
        )


def test_offline_modes_never_invoke_live_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    monkeypatch.setattr(
        module,
        "_subprocess_runner",
        lambda _argv: (_ for _ in ()).throw(
            AssertionError("offline mode invoked Azure CLI")
        ),
    )

    assert module.main(["render"]) == 0
    assert (
        module.main(
            [
                "verify",
                "--trigger-json",
                str(TRIGGER_FIXTURE),
                "--agent-json",
                str(AGENT_FIXTURE),
                "--rbac-json",
                str(RBAC_FIXTURE),
                "--secret-json",
                str(SECRET_FIXTURE),
                "--expected-trigger-id",
                TRIGGER_ID,
                "--expected-trigger-origin",
                TRIGGER_ORIGIN,
                "--expected-agent-endpoint",
                AGENT_ENDPOINT,
                "--target-prefix",
                TARGET_PREFIX,
            ]
        )
        == 2
    )


def test_cli_has_no_apply_or_mutation_mode() -> None:
    module = _load_module()

    with pytest.raises(SystemExit) as excinfo:
        module.main(["render", "--apply"])

    assert excinfo.value.code == 2


def test_readiness_report_accumulates_bound_trigger_and_secret_blockers() -> None:
    module = _load_module()
    trigger = _fixture(TRIGGER_FIXTURE)
    trigger["trigger"]["id"] = "wrong-trigger"
    secret = _fixture(SECRET_FIXTURE)
    secret["metadata"]["tags"][module.SECRET_TAG_TRIGGER_ID] = "wrong-trigger"

    report = module.build_readiness_report(
        definition=_fixture(DEFINITION),
        trigger_evidence=trigger,
        agent_evidence=_fixture(AGENT_FIXTURE),
        rbac_evidence=_fixture(RBAC_FIXTURE),
        secret_evidence=secret,
        expected_trigger_id=TRIGGER_ID,
        expected_trigger_origin=TRIGGER_ORIGIN,
        expected_agent_endpoint=AGENT_ENDPOINT,
        target_prefix=TARGET_PREFIX,
    )

    assert report["status"] == "blocked"
    assert len(report["blockers"]) == 3
    assert report["checks"]["trigger"]["status"] == "blocked"
    assert report["checks"]["secret"]["status"] == "blocked"
    assert report["checks"]["rbac"]["status"] == "offline-evidence-valid"
