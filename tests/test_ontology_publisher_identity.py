from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from scripts.validate_ontology_publisher_rbac import (
    EXPECTED_CURATOR_TOOLS,
    EXPECTED_PUBLISHER_ROLE,
    AuthorizationEvidenceError,
    HttpResult,
    ValidationBlocked,
    main,
    validate_live_authorization,
)

ROOT = Path(__file__).resolve().parents[1]
IDENTITY_TF = ROOT / "infra" / "terraform" / "ontology_discovery_identity.tf"
JOB_TF = ROOT / "infra" / "terraform" / "ontology_discovery_job.tf"
FOUNDRY_TF = ROOT / "infra" / "terraform" / "foundry.tf"
CONTAINER_APPS_TF = ROOT / "infra" / "terraform" / "container_apps.tf"


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
    assert "azurerm_user_assigned_identity.ontology_publisher.principal_id" in assignment
    assert 'type = "ServicePrincipal"' in assignment
    assert 'resource "azurerm_role_definition" "ontology_publisher"' not in terraform
    assert 'resource "azurerm_role_assignment" "ontology_publisher"' not in terraform
    assert "Admin" not in assignment
    assert "Member" not in assignment
    assert "Platform limitation" in terraform


def test_no_other_identity_receives_fabric_workspace_contributor() -> None:
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
    api_assignment = _resource(
        fabric,
        "fabric_workspace_role_assignment",
        "apps",
    )

    assert 'role         = "Contributor"' in publisher_assignment
    assert 'role         = "Viewer"' in api_assignment
    assert "ontology_coordinator" not in fabric
    assert "azurerm_cognitive_account_project.ops" not in fabric
    assert "ONTOLOGY_PUBLISHER" not in job
    assert "ontology_publisher.client_id" not in job
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


def test_publisher_has_no_model_or_app_runtime_grant() -> None:
    identity = IDENTITY_TF.read_text(encoding="utf-8")
    job = JOB_TF.read_text(encoding="utf-8")
    validator = _resource(
        job,
        "azurerm_container_app_job",
        "ontology_rbac_validation",
    )

    assert "Cognitive Services" not in identity
    assert "Foundry" not in identity
    assert "OpenAI" not in identity
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
    identities = {}
    for index, identity_class in enumerate(
        ("api", "coordinator", "curator", "publisher"), start=1
    ):
        identities[identity_class] = {
            "object_id": f"10000000-0000-0000-0000-{index:012d}",
        }
        if identity_class != "curator":
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
        "curator_prompt_sha256": "a" * 64,
        "identities": identities,
    }


class _MatrixTransport:
    def __init__(self, config: dict, *, ambiguous: bool = False, leaked: bool = False):
        self._identities = {
            entry["client_id"]: identity_class
            for identity_class, entry in config["identities"].items()
            if "client_id" in entry
        }
        self.ambiguous = ambiguous
        self.leaked = leaked
        self.calls: list[tuple[str, str, str]] = []
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
        correlation = {"x-ms-request-id": f"request-{len(self.calls)}"}
        if "api.fabric.microsoft.com" in url:
            assignments = [
                {
                    "principal": {
                        "id": self._config["identities"]["publisher"]["object_id"]
                    },
                    "role": "Contributor",
                },
                {
                    "principal": {
                        "id": self._config["identities"]["api"]["object_id"]
                    },
                    "role": "Viewer",
                },
            ]
            return HttpResult(
                200,
                correlation,
                json.dumps({"value": assignments}).encode(),
            )
        if "/agents/aiops-ontology-curator-agent/versions" in url:
            definition = {
                "model": "gpt-5.4-mini",
                "instructions_sha256": "a" * 64,
                "tools": [
                    {
                        "type": "mcp",
                        "server_label": "operations-mcp",
                        "allowed_tools": list(EXPECTED_CURATOR_TOOLS),
                    }
                ],
            }
            return HttpResult(
                200,
                correlation,
                json.dumps({"value": [{"version": "7", "definition": definition}]}).encode(),
            )
        if identity_class != "publisher":
            if self.leaked:
                return HttpResult(201, {**correlation, "etag": '"leaked"'})
            return HttpResult(404 if self.ambiguous else 403, correlation)
        if method == "DELETE":
            if any(name in url for name in ("api-stage", "coordinator-stage", "curator-stage")):
                return HttpResult(404, correlation)
            return HttpResult(202, correlation)
        self.etag += 1
        return HttpResult(201, {**correlation, "etag": f'"etag-{self.etag}"'})


def _credentials(config: dict):
    def factory(spec):
        entry = config["identities"][spec.identity_class]
        return _Credential(entry["client_id"], entry["object_id"])

    return factory


def test_live_matrix_combines_four_denials_with_curator_structural_evidence() -> None:
    config = _config()
    transport = _MatrixTransport(config)
    transport._config = config

    report = validate_live_authorization(
        config,
        transport=transport,
        credential_factory=_credentials(config),
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
        ("structural_live", "workspace_writer_role", "absent"),
        ("structural_live", "deployed_tool_allowlist", "read_only"),
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


@pytest.mark.parametrize("status_kind", ["ambiguous", "write_succeeded"])
def test_nonpublisher_result_must_be_an_unambiguous_denial(status_kind: str) -> None:
    config = _config()
    transport = _MatrixTransport(
        config,
        ambiguous=status_kind == "ambiguous",
        leaked=status_kind == "write_succeeded",
    )
    transport._config = config

    with pytest.raises(AuthorizationEvidenceError, match="unambiguous denial"):
        validate_live_authorization(
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
        validate_live_authorization(missing, transport=_MatrixTransport(_config()))

    drifted = _config()
    drifted["publisher_role"]["role"] = "Admin"
    with pytest.raises(AuthorizationEvidenceError, match="does not match"):
        validate_live_authorization(drifted, transport=_MatrixTransport(drifted))

    mismatched = _config()

    def wrong_credential(spec):
        return _Credential("wrong-client", spec.object_id)

    with pytest.raises(AuthorizationEvidenceError, match="client identity mismatch"):
        validate_live_authorization(
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
    role_transport._config = config
    with pytest.raises(AuthorizationEvidenceError, match="curator.*writer role"):
        validate_live_authorization(
            config,
            transport=role_transport,
            credential_factory=_credentials(config),
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
    tool_transport._config = config
    with pytest.raises(AuthorizationEvidenceError, match="tool allowlist"):
        validate_live_authorization(
            config,
            transport=tool_transport,
            credential_factory=_credentials(config),
        )
