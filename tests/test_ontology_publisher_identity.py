from __future__ import annotations

import ast
import base64
import json
from pathlib import Path

import pytest

from scripts.validate_ontology_publisher_rbac import (
    EXPECTED_ROLE_ACTIONS,
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


def _quoted_items(block: str) -> list[str]:
    return [
        ast.literal_eval(line.strip().rstrip(","))
        for line in block.splitlines()
        if line.strip().startswith('"')
    ]


def test_publisher_has_a_distinct_identity_and_narrow_custom_role() -> None:
    terraform = IDENTITY_TF.read_text(encoding="utf-8")
    role = _resource(terraform, "azurerm_role_definition", "ontology_publisher")
    assignment = _resource(
        terraform,
        "azurerm_role_assignment",
        "ontology_publisher",
    )
    actions = terraform.split(
        "ontology_publisher_data_actions = [", maxsplit=1
    )[1].split("]", maxsplit=1)[0]

    assert 'resource "azurerm_user_assigned_identity" "ontology_publisher"' in terraform
    assert _quoted_items(actions) == [
        "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read",
        "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/add/action",
        "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/write",
        "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/delete",
    ]
    assert "data_actions     = local.ontology_publisher_data_actions" in role
    assert "actions          = []" in role
    assert "Contributor" not in role
    assert "Owner" not in role
    assert "list" not in role.casefold()
    assert (
        "principal_id                     = "
        "azurerm_user_assigned_identity.ontology_publisher.principal_id"
        in assignment
    )


def test_api_coordinator_and_curator_do_not_receive_publisher_role_or_credential() -> None:
    identity = IDENTITY_TF.read_text(encoding="utf-8")
    job = JOB_TF.read_text(encoding="utf-8")
    foundry = FOUNDRY_TF.read_text(encoding="utf-8")
    api = _resource(
        CONTAINER_APPS_TF.read_text(encoding="utf-8"),
        "azurerm_container_app",
        "api",
    )
    assignment = _resource(
        identity,
        "azurerm_role_assignment",
        "ontology_publisher",
    )

    assert "ontology_coordinator" not in assignment
    assert "azurerm_user_assigned_identity.apps" not in assignment
    assert "azurerm_cognitive_account_project.ops" not in assignment
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


def test_publisher_has_no_model_or_read_generalization_grant() -> None:
    identity = IDENTITY_TF.read_text(encoding="utf-8")
    role = _resource(identity, "azurerm_role_definition", "ontology_publisher")
    assignment = _resource(
        identity,
        "azurerm_role_assignment",
        "ontology_publisher",
    )
    effective_grant = role + assignment

    assert "Cognitive Services" not in effective_grant
    assert "Foundry" not in effective_grant
    assert "OpenAI" not in effective_grant
    assert "Reader" not in assignment
    assert "Contributor" not in assignment
    assert "list" not in effective_grant.casefold()


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
            "mode": "managed_identity",
            "client_id": f"00000000-0000-0000-0000-{index:012d}",
            "object_id": f"10000000-0000-0000-0000-{index:012d}",
        }
    return {
        "non_production": True,
        "workspace_id": "20000000-0000-0000-0000-000000000001",
        "lakehouse_id": "30000000-0000-0000-0000-000000000001",
        "publisher_role_actions": list(EXPECTED_ROLE_ACTIONS),
        "identities": identities,
    }


class _MatrixTransport:
    def __init__(self, config: dict, *, ambiguous: bool = False, leaked: bool = False):
        self._identities = {
            entry["client_id"]: identity_class
            for identity_class, entry in config["identities"].items()
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
        claims = json.loads(
            base64.urlsafe_b64decode(token.split(".")[1] + "==")
        )
        identity_class = self._identities[claims["appid"]]
        self.calls.append((identity_class, method, url))
        correlation = {"x-ms-request-id": f"request-{len(self.calls)}"}
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


def test_live_matrix_requires_six_denials_and_publisher_stage_cas_rollback_cleanup() -> None:
    config = _config()
    transport = _MatrixTransport(config)

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
        for identity in ("api", "coordinator", "curator")
        for operation in ("stage_create_only", "pointer_cas")
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
    drifted["publisher_role_actions"].append(
        "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/list/action"
    )
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
