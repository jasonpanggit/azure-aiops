from __future__ import annotations

import base64
import hashlib
import json
import uuid
from pathlib import Path

import pytest

from scripts.validate_ontology_publisher_rbac import (
    EXPECTED_PUBLISHER_ROLE,
    AuthorizationEvidenceError,
    HttpResult,
    UrllibTransport,
    ValidationBlocked,
    _config_from_terraform_state,
    _correlation,
    main,
    validate_control_plane_audit,
    validate_live_authorization,
    validate_write_matrix,
)

ROOT = Path(__file__).resolve().parents[1]
IDENTITY_TF = ROOT / "infra" / "terraform" / "ontology_discovery_identity.tf"
JOB_TF = ROOT / "infra" / "terraform" / "ontology_discovery_job.tf"
FOUNDRY_TF = ROOT / "infra" / "terraform" / "foundry.tf"
CONTAINER_APPS_TF = ROOT / "infra" / "terraform" / "container_apps.tf"
FIXTURES = ROOT / "tests" / "fixtures" / "ontology_publisher_rbac"


def _resource(text: str, kind: str, name: str) -> str:
    marker = f'resource "{kind}" "{name}"'
    start = text.index(marker)
    next_resource = text.find('\nresource "', start + len(marker))
    return text[start:] if next_resource == -1 else text[start:next_resource]


def test_publisher_uses_the_least_broad_working_fabric_workspace_role() -> None:
    terraform = IDENTITY_TF.read_text(encoding="utf-8")
    assignment = _resource(
        terraform,
        "fabric_workspace_role_assignment",
        "ontology_publisher",
    )

    assert 'resource "azurerm_user_assigned_identity" "ontology_publisher"' in terraform
    assert 'role         = "Contributor"' in assignment
    assert (
        "workspace_id = fabric_workspace.ontology_rbac_validation[0].id"
        in assignment
    )
    assert "azurerm_user_assigned_identity.ontology_publisher.principal_id" in assignment
    assert 'type = "ServicePrincipal"' in assignment
    assert 'resource "azurerm_role_definition" "ontology_publisher"' not in terraform
    assert 'resource "azurerm_role_assignment" "ontology_publisher"' not in terraform
    assert "Admin" not in assignment
    assert "Member" not in assignment
    assert "Platform limitation" in terraform


def test_two_nonproduction_workspaces_isolate_state_and_validation_writers() -> None:
    identity = IDENTITY_TF.read_text(encoding="utf-8")
    job = JOB_TF.read_text(encoding="utf-8")
    foundry = FOUNDRY_TF.read_text(encoding="utf-8")
    fabric = (
        ROOT / "infra" / "terraform" / "fabric.tf"
    ).read_text(encoding="utf-8")
    api = _resource(
        CONTAINER_APPS_TF.read_text(encoding="utf-8"),
        "azurerm_container_app",
        "api",
    )
    publisher_assignment = _resource(
        identity,
        "fabric_workspace_role_assignment",
        "ontology_publisher",
    )
    production_assignment = _resource(
        fabric,
        "fabric_workspace_role_assignment",
        "apps",
    )
    coordinator_assignment = _resource(
        identity,
        "fabric_workspace_role_assignment",
        "ontology_coordinator_state",
    )
    scheduled_job = _resource(
        job,
        "azurerm_container_app_job",
        "ontology_discovery",
    )

    assert 'role         = "Contributor"' in publisher_assignment
    assert (
        "workspace_id = fabric_workspace.ontology_rbac_validation[0].id"
        in publisher_assignment
    )
    assert 'role         = "Contributor"' in coordinator_assignment
    assert (
        "workspace_id = fabric_workspace.ontology_discovery_state[0].id"
        in coordinator_assignment
    )
    assert "ontology_publisher" not in coordinator_assignment
    assert "ontology_coordinator" not in publisher_assignment
    assert 'role         = "Contributor"' in production_assignment
    assert "ontology_discovery_state" not in production_assignment
    assert "ontology_rbac_validation" not in production_assignment
    assert "ONTOLOGY_PUBLISHER" not in scheduled_job
    assert "ontology_publisher.client_id" not in scheduled_job
    assert "ONTOLOGY_PUBLISHER" not in api
    assert "ontology_publisher.client_id" not in api
    curator = _resource(
        foundry,
        "terraform_data",
        "foundry_ontology_curator_agent",
    )
    assert "ontology_publisher" not in curator
    assert "AZURE_CLIENT_SECRET" in curator  # deployer-only script credential
    assert "ONTOLOGY_PUBLISHER" not in curator


def test_nonproduction_workspaces_reuse_capacity_and_have_explicit_descriptions() -> None:
    identity = IDENTITY_TF.read_text(encoding="utf-8")

    state_workspace = _resource(
        identity,
        "fabric_workspace",
        "ontology_discovery_state",
    )
    state_lakehouse = _resource(
        identity,
        "fabric_lakehouse",
        "ontology_discovery_state",
    )
    validation_workspace = _resource(
        identity,
        "fabric_workspace",
        "ontology_rbac_validation",
    )
    validation_lakehouse = _resource(
        identity,
        "fabric_lakehouse",
        "ontology_rbac_validation",
    )

    for workspace in (state_workspace, validation_workspace):
        assert "capacity_id" in workspace
        assert "= data.fabric_capacity.main[0].id" in workspace
        assert "non-production" in workspace.casefold()
    for lakehouse in (state_lakehouse, validation_lakehouse):
        assert "non-production" in lakehouse.casefold()
    assert '"${local.base}-ontology-state"' in state_workspace
    assert '"${local.base}-ontology-rbac-validation"' in validation_workspace


def test_publisher_has_no_model_or_app_runtime_grant() -> None:
    identity = IDENTITY_TF.read_text(encoding="utf-8")
    job = JOB_TF.read_text(encoding="utf-8")
    validator = _resource(
        job,
        "azurerm_container_app_job",
        "ontology_rbac_validation",
    )
    publisher_assignment = _resource(
        identity,
        "fabric_workspace_role_assignment",
        "ontology_publisher",
    )

    assert "Cognitive Services" not in publisher_assignment
    assert "Foundry" not in publisher_assignment
    assert "OpenAI" not in publisher_assignment
    assert "ontology_publisher" in validator
    assert "AIOPS_HOME" not in validator
    assert "AIOPS_RUNTIME_MODE" not in validator


def _token(client_id: str, object_id: str) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').decode().rstrip("=")
    claims = base64.urlsafe_b64encode(
        json.dumps({"appid": client_id, "oid": object_id}).encode()
    ).decode().rstrip("=")
    return f"{header}.{claims}.signature"


class _Credential:
    def __init__(self, client_id: str, object_id: str) -> None:
        self.token = _token(client_id, object_id)
        self.closed = False

    def get_token(self, *_scopes: str, **_kwargs):
        return type("Token", (), {"token": self.token})()

    def close(self) -> None:
        self.closed = True


def _config() -> dict:
    curator_prompt = "proposal-only ontology curator"
    identities = {}
    for index, identity_class in enumerate(
        ("api", "coordinator", "curator", "publisher"), start=1
    ):
        identities[identity_class] = {
            "object_id": f"10000000-0000-0000-0000-{index:012d}",
        }
        if identity_class == "curator":
            identities[identity_class]["mode"] = "structural"
        else:
            identities[identity_class].update(
                {
                    "mode": "managed_identity",
                    "client_id": f"00000000-0000-0000-0000-{index:012d}",
                }
            )
    return {
        "non_production": True,
        "workspace_id": "20000000-0000-0000-0000-000000000001",
        "lakehouse_id": "30000000-0000-0000-0000-000000000001",
        "publisher_role": dict(EXPECTED_PUBLISHER_ROLE),
        "foundry_project_endpoint": "https://example.services.ai.azure.com/api/projects/test",
        "curator_agent_name": "aiops-ontology-curator-agent",
        "curator_model": "gpt-5.4-mini",
        "curator_prompt_sha256": hashlib.sha256(curator_prompt.encode()).hexdigest(),
        "curator_prompt": curator_prompt,
        "identities": identities,
    }


class _MatrixTransport:
    def __init__(
        self,
        config: dict,
        *,
        ambiguous: bool = False,
        leaked: bool = False,
        server_correlation: bool = True,
    ):
        self._config = config
        self._identities = {
            entry["client_id"]: identity_class
            for identity_class, entry in config["identities"].items()
            if "client_id" in entry
        }
        self.ambiguous = ambiguous
        self.leaked = leaked
        self.server_correlation = server_correlation
        self.calls: list[tuple[str, str, str]] = []
        self.client_request_ids: list[str] = []
        self.etag = 0

    def request(
        self,
        method: str,
        url: str,
        *,
        token: str,
        headers: dict[str, str],
        body: bytes = b"",
    ) -> HttpResult:
        claims = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
        identity_class = self._identities[claims["appid"]]
        self.calls.append((identity_class, method, url))
        client_request_id = str(uuid.uuid4())
        self.client_request_ids.append(client_request_id)
        correlation = (
            {"x-ms-request-id": f"request-{len(self.calls)}"}
            if self.server_correlation
            else {}
        )
        if "api.fabric.microsoft.com" in url:
            return HttpResult(
                200,
                correlation,
                (FIXTURES / "workspace_role_assignments.json").read_bytes(),
                client_request_id,
            )
        if "/agents/aiops-ontology-curator-agent/versions" in url:
            return HttpResult(
                200,
                correlation,
                (FIXTURES / "curator_versions.json").read_bytes(),
                client_request_id,
            )
        if identity_class != "publisher":
            if self.leaked:
                return HttpResult(
                    201,
                    {**correlation, "etag": '"leaked"'},
                    client_request_id=client_request_id,
                )
            return HttpResult(
                404 if self.ambiguous else 403,
                correlation,
                client_request_id=client_request_id,
            )
        if method == "DELETE":
            if any(name in url for name in ("api-stage", "coordinator-stage", "curator-stage")):
                return HttpResult(
                    404,
                    correlation,
                    client_request_id=client_request_id,
                )
            return HttpResult(
                202,
                correlation,
                client_request_id=client_request_id,
            )
        self.etag += 1
        return HttpResult(
            201,
            {**correlation, "etag": f'"etag-{self.etag}"'},
            client_request_id=client_request_id,
        )


def _credentials(config: dict):
    def factory(spec):
        entry = config["identities"][spec.identity_class]
        return _Credential(entry["client_id"], entry["object_id"])

    return factory


def _deployer(config: dict) -> _Credential:
    config["deployer_client_id"] = config["identities"]["api"]["client_id"]
    return _Credential(
        config["deployer_client_id"],
        config["identities"]["api"]["object_id"],
    )


def test_live_matrix_combines_four_denials_with_curator_structural_evidence() -> None:
    config = _config()
    transport = _MatrixTransport(config)

    report = validate_live_authorization(
        config,
        transport=transport,
        credential_factory=_credentials(config),
        deployer_credential=_deployer(config),
    )

    assert report["status"] == "passed"
    evidence = report["evidence"]
    denied = [row for row in evidence if row["result"] == "denied"]
    assert {
        (row["identity_class"], row["operation"]) for row in denied
    } == {
        (identity, operation)
        for identity in ("api", "coordinator")
        for operation in ("stage_create_only", "pointer_cas")
    }
    curator = [
        row
        for row in evidence
        if row["identity_class"] == "curator"
    ]
    assert {
        (row["evidence_kind"], row["operation"], row["result"])
        for row in curator
    } == {
        ("control_plane_live", "workspace_writer_role", "absent"),
        ("control_plane_live", "deployed_tool_allowlist", "read_only"),
    }
    publisher_operations = {
        row["operation"]
        for row in evidence
        if row["identity_class"] == "publisher"
    }
    assert {
        "pointer_baseline",
        "stage_create_only",
        "pointer_cas",
        "rollback_cas",
        "canary_cleanup",
    } <= publisher_operations
    serialized = json.dumps(report)
    for forbidden in (
        "onelake.blob.fabric.microsoft.com",
        "workspace_id",
        "lakehouse_id",
        "client_id",
        "object_id",
        "Bearer ",
    ):
        assert forbidden not in serialized
    assert all(
        row["correlation_evidence"].startswith("sha256:") for row in evidence
    )


def test_job_write_matrix_never_calls_control_plane_apis() -> None:
    config = _config()
    transport = _MatrixTransport(config)

    report = validate_write_matrix(
        config,
        transport=transport,
        credential_factory=_credentials(config),
    )

    assert report["mode"] == "write-matrix-only"
    assert all(
        "api.fabric.microsoft.com" not in url and "/agents/" not in url
        for _identity, _method, url in transport.calls
    )
    assert not any(
        row["identity_class"] == "curator" for row in report["evidence"]
    )


def test_deployer_control_plane_audit_never_calls_onelake() -> None:
    config = _config()
    transport = _MatrixTransport(config)

    report = validate_control_plane_audit(
        config,
        transport=transport,
        credential=_deployer(config),
    )

    assert report["mode"] == "control-plane-audit"
    assert all(
        "onelake.blob.fabric.microsoft.com" not in url
        for _identity, _method, url in transport.calls
    )
    assert {
        (row["identity_class"], row["operation"], row["result"])
        for row in report["evidence"]
    } == {
        ("publisher", "workspace_writer_role", "contributor"),
        ("api", "workspace_writer_role", "absent"),
        ("coordinator", "workspace_writer_role", "absent"),
        ("curator", "workspace_writer_role", "absent"),
        ("curator", "deployed_tool_allowlist", "read_only"),
    }


def test_control_plane_config_is_resolved_from_deployed_terraform_state(
    tmp_path: Path,
) -> None:
    config = _config()
    resources = []

    def add(resource_type: str, name: str, attributes: dict) -> None:
        resources.append(
            {
                "type": resource_type,
                "name": name,
                "instances": [{"attributes": attributes}],
            }
        )

    add(
        "azurerm_user_assigned_identity",
        "apps",
        {
            "client_id": config["identities"]["api"]["client_id"],
            "principal_id": config["identities"]["api"]["object_id"],
        },
    )
    add(
        "azurerm_user_assigned_identity",
        "ontology_coordinator",
        {
            "client_id": config["identities"]["coordinator"]["client_id"],
            "principal_id": config["identities"]["coordinator"]["object_id"],
        },
    )
    add(
        "azurerm_user_assigned_identity",
        "ontology_publisher",
        {
            "client_id": config["identities"]["publisher"]["client_id"],
            "principal_id": config["identities"]["publisher"]["object_id"],
        },
    )
    add(
        "azurerm_cognitive_account_project",
        "ops",
        {"identity": [{"principal_id": config["identities"]["curator"]["object_id"]}]},
    )
    add(
        "fabric_workspace",
        "ontology_rbac_validation",
        {"id": config["workspace_id"]},
    )
    add(
        "fabric_lakehouse",
        "ontology_rbac_validation",
        {"id": config["lakehouse_id"]},
    )
    add(
        "terraform_data",
        "foundry_ontology_curator_agent",
        {
            "triggers_replace": {
                "endpoint": config["foundry_project_endpoint"],
                "agent_name": config["curator_agent_name"],
                "model": config["curator_model"],
                "instructions": config["curator_prompt_sha256"],
            }
        },
    )
    state_path = tmp_path / "terraform.tfstate"
    state_path.write_text(json.dumps({"resources": resources}), encoding="utf-8")

    resolved = _config_from_terraform_state(
        {},
        state_path,
        env={"AZURE_CLIENT_ID": config["identities"]["api"]["client_id"]},
    )

    assert resolved["workspace_id"] == config["workspace_id"]
    assert resolved["lakehouse_id"] == config["lakehouse_id"]
    assert resolved["identities"]["curator"]["mode"] == "structural"
    assert resolved["publisher_role"] == EXPECTED_PUBLISHER_ROLE
    assert resolved["curator_prompt_sha256"] == config["curator_prompt_sha256"]


def test_missing_server_correlation_uses_unique_hashed_client_request_ids() -> None:
    config = _config()
    transport = _MatrixTransport(config, server_correlation=False)

    report = validate_write_matrix(
        config,
        transport=transport,
        credential_factory=_credentials(config),
    )

    correlations = [row["correlation_evidence"] for row in report["evidence"]]
    assert report["status"] == "passed"
    assert len(transport.client_request_ids) == len(set(transport.client_request_ids))
    assert len(set(correlations)) == len(correlations)
    assert all(value.startswith("sha256:") for value in correlations)
    serialized = json.dumps(report)
    assert all(value not in serialized for value in transport.client_request_ids)


@pytest.mark.parametrize("client_request_id", ["", "constant", "not-a-uuid"])
def test_correlation_rejects_missing_or_malformed_operation_context(
    client_request_id: str,
) -> None:
    with pytest.raises(
        AuthorizationEvidenceError,
        match="operation lacks correlation evidence",
    ):
        _correlation(
            HttpResult(
                status=403,
                headers={},
                client_request_id=client_request_id,
            )
        )


def test_transport_sends_unique_client_request_id_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_headers: list[dict[str, str]] = []

    class Response:
        status = 200

        def __init__(self) -> None:
            self.headers: dict[str, str] = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit: int) -> bytes:
            return b"{}"

    def urlopen(request, *, timeout):
        assert timeout == 30
        observed_headers.append(dict(request.header_items()))
        return Response()

    monkeypatch.setattr(
        "scripts.validate_ontology_publisher_rbac.urllib.request.urlopen",
        urlopen,
    )
    transport = UrllibTransport()
    first = transport.request(
        "GET",
        "https://example.test/first",
        token="secret-token",
        headers={},
    )
    second = transport.request(
        "GET",
        "https://example.test/second",
        token="secret-token",
        headers={},
    )

    assert uuid.UUID(first.client_request_id).version == 4
    assert uuid.UUID(second.client_request_id).version == 4
    assert first.client_request_id != second.client_request_id
    assert observed_headers[0]["X-ms-client-request-id"] == first.client_request_id
    assert observed_headers[1]["X-ms-client-request-id"] == second.client_request_id
    assert observed_headers[0]["X-ms-return-client-request-id"] == "true"
    assert _correlation(first).startswith("sha256:")


def test_server_correlation_is_preferred_over_client_request_id() -> None:
    result = HttpResult(
        status=403,
        headers={"x-ms-request-id": "server-request"},
        client_request_id=str(uuid.uuid4()),
    )

    assert _correlation(result) == "sha256:" + hashlib.sha256(
        b"server-request"
    ).hexdigest()


@pytest.mark.parametrize("status_kind", ["ambiguous", "write_succeeded"])
def test_nonpublisher_result_must_be_an_unambiguous_denial(status_kind: str) -> None:
    config = _config()
    transport = _MatrixTransport(
        config,
        ambiguous=status_kind == "ambiguous",
        leaked=status_kind == "write_succeeded",
    )

    with pytest.raises(AuthorizationEvidenceError, match="unambiguous denial"):
        validate_write_matrix(
            config,
            transport=transport,
            credential_factory=_credentials(config),
        )
    assert any(
        identity == "publisher" and method == "DELETE"
        for identity, method, _url in transport.calls
    )


def test_validator_rejects_missing_identity_role_drift_and_token_mismatch() -> None:
    missing = _config()
    del missing["identities"]["curator"]
    with pytest.raises(ValidationBlocked, match="exactly four"):
        validate_control_plane_audit(
            missing,
            transport=_MatrixTransport(_config()),
            credential=_deployer(missing),
        )

    drifted = _config()
    drifted["publisher_role"]["role"] = "Admin"
    with pytest.raises(AuthorizationEvidenceError, match="does not match"):
        validate_write_matrix(drifted, transport=_MatrixTransport(drifted))

    mismatched = _config()

    def wrong_credential(spec):
        return _Credential("wrong-client", spec.object_id)

    with pytest.raises(AuthorizationEvidenceError, match="client identity mismatch"):
        validate_write_matrix(
            mismatched,
            transport=_MatrixTransport(mismatched),
            credential_factory=wrong_credential,
        )


def test_cli_fails_closed_when_live_configuration_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("AIOPS_FABRIC_CONFIG", raising=False)

    assert main(["--non-production", "--fail-on-missing-evidence"]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "blocked"
    assert report["evidence"] == []


def test_curator_structural_evidence_fails_on_writer_role_or_extra_tool() -> None:
    config = _config()

    class UnsafeTransport(_MatrixTransport):
        def request(self, method, url, *, token, headers, body=b""):
            result = super().request(
                method,
                url,
                token=token,
                headers=headers,
                body=body,
            )
            if "api.fabric.microsoft.com" in url:
                assignments = json.loads(result.body)["value"]
                assignments.append(
                    {
                        "principal": {
                            "id": config["identities"]["curator"]["object_id"]
                        },
                        "role": "Contributor",
                    }
                )
                return HttpResult(
                    200,
                    result.headers,
                    json.dumps({"value": assignments}).encode(),
                )
            return result

    role_transport = UnsafeTransport(config)
    with pytest.raises(AuthorizationEvidenceError, match="curator.*writer role"):
        validate_control_plane_audit(
            config,
            transport=role_transport,
            credential=_deployer(config),
        )

    class ExtraToolTransport(_MatrixTransport):
        def request(self, method, url, *, token, headers, body=b""):
            result = super().request(
                method,
                url,
                token=token,
                headers=headers,
                body=body,
            )
            if "/agents/" in url:
                payload = json.loads(result.body)
                payload["value"][0]["definition"]["tools"][0]["allowed_tools"].append(
                    "publish_ontology"
                )
                return HttpResult(
                    200,
                    result.headers,
                    json.dumps(payload).encode(),
                )
            return result

    tool_transport = ExtraToolTransport(config)
    with pytest.raises(AuthorizationEvidenceError, match="tool allowlist"):
        validate_control_plane_audit(
            config,
            transport=tool_transport,
            credential=_deployer(config),
        )
