from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
import yaml
from azure.core.exceptions import ClientAuthenticationError

from fabric import catalog_cli
from fabric.auth import FabricAuthConfig

WORKSPACE = "2c1fea36-104d-4c26-86db-12e09e432b41"
ITEM = "f995229d-970e-44ec-8af5-df9e25261d19"


class Credential:
    closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def get_token(self, *scopes):
        return SimpleNamespace(token="never-print-this-token")


def _setup(monkeypatch, responses, *, workspace_id=WORKSPACE):
    calls = []
    loaded = []
    credential = Credential()
    config = SimpleNamespace(
        workspace_id=workspace_id,
        auth=FabricAuthConfig(mode="managed_identity"),
    )

    def load(path):
        loaded.append(path)
        return config

    def handler(request):
        calls.append(request)
        result = responses[len(calls) - 1]
        if isinstance(result, Exception):
            raise result
        if isinstance(result, int):
            return httpx.Response(result)
        return httpx.Response(200, json=result)

    http = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(catalog_cli.FabricRuntimeConfig, "load", load)
    monkeypatch.setattr(catalog_cli, "build_credential", lambda auth: credential)
    monkeypatch.setattr(catalog_cli.httpx, "Client", lambda **kwargs: http)
    return calls, loaded, credential, http


def _responses():
    return [
        {"value": [{
            "id": ITEM, "type": "Lakehouse", "displayName": "Indexed",
            "catalogEntryType": "FabricItem",
            "hierarchy": {"workspace": {"id": WORKSPACE}},
        }]},
        {"id": ITEM, "workspaceId": WORKSPACE, "type": "Lakehouse", "displayName": "Current"},
    ]


def test_cli_runs_real_bounded_verification_and_closes_resources(monkeypatch, capsys):
    calls, loaded, credential, http = _setup(monkeypatch, _responses())
    assert catalog_cli.main([
        "--config", "approved.yaml", "--page-size", "1", "--max-pages", "1",
        "--max-items", "1",
    ]) == 0
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert captured.err == ""
    assert report["status"] == "advisory_metadata_verified"
    assert report["authentication_mode"] == "managed_identity"
    assert report["evidence"]["authoritative"] is False
    assert report["evidence"]["requires_schema_verification"] is True
    assert report["evidence"]["verified_items"][0]["current"]["display_name"] == "Current"
    assert loaded == ["approved.yaml"]
    assert [request.method for request in calls] == ["POST", "GET"]
    assert json.loads(calls[0].content)["filter"] == (
        f"WorkspaceId eq '{WORKSPACE}' and Type ne 'Workspace'"
    )
    assert all(request.headers["x-ms-fabric-skill"] == "onelake-catalog-govern-cli" for request in calls)
    assert "never-print-this-token" not in captured.out + captured.err
    assert credential.closed and http.is_closed


@pytest.mark.parametrize("args,workspace", [
    (["--max-pages", "0"], WORKSPACE),
    (["--page-size", "1001"], WORKSPACE),
    (["--max-items", "-1"], WORKSPACE),
    ([], ""),
    ([], "not-a-workspace"),
])
def test_invalid_configuration_has_no_network_or_success(monkeypatch, capsys, args, workspace):
    calls, _, _, http = _setup(monkeypatch, [], workspace_id=workspace)
    assert catalog_cli.main(args) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {"status": "failed", "failure_stage": "configuration"}
    assert calls == []
    http.close()


@pytest.mark.parametrize("failure", [
    403, 404,
    {"id": ITEM, "workspaceId": WORKSPACE, "type": "Ontology", "displayName": "Wrong"},
    httpx.ReadError("secret-response-fragment"),
])
def test_later_failure_never_prints_partial_or_sensitive_details(monkeypatch, capsys, failure):
    responses = _responses()
    responses[1] = failure
    if isinstance(failure, httpx.ReadError):
        responses.extend([failure] * 4)
    _, _, credential, http = _setup(monkeypatch, responses)
    # Disable waits without changing production retry behavior.
    original = catalog_cli.FabricClient
    monkeypatch.setattr(
        catalog_cli, "FabricClient",
        lambda *args, **kwargs: original(*args, **kwargs, sleep=lambda _: None),
    )
    assert catalog_cli.main([]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    expected = {
        "status": "failed", "failure_stage": "catalog_verification",
    }
    if isinstance(failure, int):
        expected["http_status"] = failure
    assert json.loads(captured.err) == expected
    assert credential.closed and http.is_closed


def test_http_failure_reports_status_but_no_sensitive_response_or_request(monkeypatch, capsys):
    request = httpx.Request(
        "POST", "https://api.fabric.microsoft.com/v1/catalog/search?private-query",
        headers={"Authorization": "Bearer private-token"},
    )
    response = httpx.Response(
        403, request=request,
        json={"errorCode": "Forbidden", "message": "private-service-body"},
    )
    failure = httpx.HTTPStatusError("private-exception-message", request=request, response=response)
    _setup(monkeypatch, [failure])
    assert catalog_cli.main([]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "status": "failed", "failure_stage": "catalog_verification", "http_status": 403,
    }


def test_credential_failure_is_sanitized(monkeypatch, capsys):
    _setup(monkeypatch, [])

    def build(auth):
        raise ClientAuthenticationError("secret-credential-detail")

    monkeypatch.setattr(catalog_cli, "build_credential", build)
    assert catalog_cli.main([]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {"status": "failed", "failure_stage": "authentication"}


@pytest.mark.parametrize("failure", [
    OSError("private-config-path"),
    yaml.YAMLError("private-config-content"),
    ValueError("private-config-value"),
])
def test_configuration_read_failure_is_sanitized(monkeypatch, capsys, failure):
    def load(path):
        raise failure

    monkeypatch.setattr(catalog_cli.FabricRuntimeConfig, "load", load)
    assert catalog_cli.main([]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {"status": "failed", "failure_stage": "configuration"}


def test_cli_uses_existing_config_environment(monkeypatch, capsys):
    _, loaded, _, _ = _setup(monkeypatch, [{"value": []}])
    monkeypatch.setenv("AIOPS_FABRIC_CONFIG", "runtime.yaml")
    assert catalog_cli.main([]) == 0
    assert loaded == ["runtime.yaml"]
    assert json.loads(capsys.readouterr().out)["evidence"]["coverage"] == "partial"


def _baseline():
    return {
        "status": "advisory_metadata_verified", "authentication_mode": "managed_identity",
        "evidence": {
            "source": "onelake_catalog_verified_items",
            "coverage": "partial", "authoritative": False,
            "verification_scope": "item_metadata_only",
            "requires_direct_verification": False, "requires_schema_verification": True,
            "verified_items": [],
            "catalog": {
                "source": "onelake_catalog", "workspace_id": WORKSPACE,
                "observed_at": "2020-01-01T00:00:00Z", "pages_fetched": 1,
                "search_complete": True, "coverage": "partial", "authoritative": False,
                "requires_direct_verification": True, "candidates": [],
            },
        },
    }


def test_cli_baseline_produces_advisory_delta_without_writing_it(monkeypatch, capsys, tmp_path):
    path = tmp_path / "baseline.json"
    raw = json.dumps(_baseline())
    path.write_text(raw)
    _setup(monkeypatch, _responses())
    assert catalog_cli.main(["--baseline", str(path)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["metadata_delta"]["added"][0]["item_id"] == ITEM
    assert report["metadata_delta"]["retired"] == []
    assert report["metadata_delta"]["authoritative"] is False
    assert path.read_text() == raw
    assert "metadata_delta" not in report["evidence"]


@pytest.mark.parametrize("mode", [
    "invalid", "scope", "auth", "missing", "oversized", "remote", "deep",
])
def test_bad_baseline_fails_before_network(monkeypatch, capsys, tmp_path, mode):
    path = tmp_path / "baseline.json"
    baseline = _baseline()
    if mode == "scope":
        baseline["evidence"]["catalog"]["workspace_id"] = ITEM
    if mode == "auth":
        baseline["authentication_mode"] = "service_principal"
    raw = "invalid" if mode == "invalid" else json.dumps(baseline)
    if mode == "oversized":
        raw = "x" * 2_000_001
    if mode == "deep":
        raw = "[" * 2000 + "]" * 2000
    if mode != "missing":
        path.write_text(raw)
    calls, _, _, http = _setup(monkeypatch, [])
    def forbid_credential(auth):
        raise AssertionError("Invalid baseline must fail before credential construction")

    monkeypatch.setattr(catalog_cli, "build_credential", forbid_credential)
    argument = "https://not-a-local-baseline" if mode == "remote" else str(path)
    assert catalog_cli.main(["--baseline", argument]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {"status": "failed", "failure_stage": "configuration"}
    assert calls == []
    http.close()


def test_comparison_failure_emits_no_partial_success(monkeypatch, capsys, tmp_path):
    baseline = _baseline()
    baseline["evidence"]["catalog"]["observed_at"] = "2099-01-01T00:00:00Z"
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps(baseline))
    calls, _, credential, http = _setup(monkeypatch, _responses())
    assert catalog_cli.main(["--baseline", str(path)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "status": "failed", "failure_stage": "catalog_comparison",
    }
    assert len(calls) == 2
    assert credential.closed and http.is_closed


def test_cli_comparison_report_can_be_reused_as_next_baseline(monkeypatch, capsys, tmp_path):
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps(_baseline()))
    with monkeypatch.context() as first:
        _setup(first, _responses())
        assert catalog_cli.main(["--baseline", str(path)]) == 0
    report = json.loads(capsys.readouterr().out)
    path.write_text(json.dumps(report))
    with monkeypatch.context() as second:
        _setup(second, _responses())
        assert catalog_cli.main(["--baseline", str(path)]) == 0
    next_report = json.loads(capsys.readouterr().out)
    assert next_report["metadata_delta"]["unchanged"] == [ITEM]
    assert next_report["metadata_delta"]["changed"] == []
    assert next_report["metadata_delta"]["retired"] == []
