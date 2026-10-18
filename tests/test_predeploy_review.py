"""Advisory CI review is exact-source, fail-closed, read-only and secret-safe."""

import importlib.util
import json
import subprocess
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
import yaml
from pydantic import ValidationError
from test_predeploy_history import _auth, _client, _create, _receipt, _retain

from operations.predeploy_history import AssessmentReceipt
from operations.predeploy_review import CIReviewContract, review_contract, review_digest


def _cli():
    spec = importlib.util.spec_from_file_location(
        "predeploy_review_cli", "scripts/predeploy-review.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _clear_receipt():
    return AssessmentReceipt.model_validate(
        {
            **_receipt().model_dump(),
            "verdict": "approve",
            "confidence": "high",
            "unknowns": [],
            "risk_level": "Low",
            "business_services": [],
        }
    )


def test_invalid_cli_arguments_are_failure_one_not_review_required(tmp_path, capsys):
    module = _cli()
    with pytest.raises(SystemExit) as error:
        module.main(["--unexpected-private-reader-fixture"])
    assert error.value.code == 1
    output = capsys.readouterr()
    assert not output.out and "private-reader-fixture" not in output.err


@pytest.mark.parametrize(
    "change",
    [
        {"verdict": "approve_with_conditions"},
        {"verdict": "require_review"},
        {"confidence": "medium"},
        {"confidence": "low"},
        {"confidence": "unknown"},
        {"unknowns": ["An unresolved source"]},
        {"traversal_truncated": True},
        {"risk_level": "High"},
        {"business_services": ["critical-service"]},
    ],
)
def test_any_declared_escalation_withholds_advisory_clear(change):
    receipt = AssessmentReceipt.model_validate(
        {**_clear_receipt().model_dump(), **change}
    )
    assert review_contract(receipt, {})["disposition"] == "review_required"


def test_contract_is_deterministic_and_any_evidence_drift_is_rejected():
    receipt = _clear_receipt()
    contract = review_contract(receipt, {"subscription": ["a", "b"]})
    assert contract == review_contract(receipt, {"subscription": ["a", "b"]})
    assert contract["deployment_authority"] == "none"
    assert contract["disposition"] == "advisory_clear"
    assert contract["receipt_sha256"] == review_digest(receipt.model_dump())
    for delta in (
        {"scope": {}},
        {"disposition": "review_required"},
        {"deployment_authority": "deploy"},
        {"schema_version": True},
        {"schema_version": 1.0},
        {"receipt_sha256": "f" * 64},
        {"review_sha256": "f" * 64},
        {"execute": True},
        {"receipt": {**contract["receipt"], "risk_score": receipt.risk_score + 1}},
    ):
        with pytest.raises(ValidationError):
            CIReviewContract.model_validate({**contract, **delta})


def test_destructive_rows_require_review_even_with_an_approve_summary():
    data = _clear_receipt().model_dump()
    data["changes"][0]["is_destructive"] = True
    assert (
        review_contract(AssessmentReceipt.model_validate(data), {})["disposition"]
        == "review_required"
    )


def test_api_export_is_reader_scoped_provider_free_and_expected_digest_bound(tmp_path):
    client, context, service, store = _client(tmp_path)
    query = [("subscription", "a"), ("subscription", "b"), ("region", "eastus")]
    assessment = _create(client, query)
    assert _retain(client, assessment, params=query).status_code == 201
    service._assessments.clear()
    context.semantic_provider = Mock(side_effect=AssertionError("No acquisition"))
    url = f"/api/v1/changes/retained-assessments/{assessment['assessment_id']}/review-contract"
    digest = ("artifact_sha256", assessment["artifact"]["sha256"])
    response = client.get(url, headers=_auth("history-reader"), params=[*query, digest])
    assert response.status_code == 200, response.text
    contract = CIReviewContract.model_validate(response.json()["data"])
    assert contract.scope == {"subscription": ["a", "b"], "region": ["eastus"]}
    assert contract.disposition == "review_required"
    assert store.read("owner", contract.scope)["revision"] == 1
    context.semantic_provider.assert_not_called()
    assert (
        client.get(
            url, headers=_auth(), params=[*query, ("artifact_sha256", "f" * 64)]
        ).status_code
        == 409
    )
    assert (
        client.get(
            url, headers=_auth("history-other"), params=[*query, digest]
        ).status_code
        == 404
    )
    assert client.get(url, headers=_auth(), params=[digest]).status_code == 404
    assert client.get(url, params=[*query, digest]).status_code == 401
    assert (
        client.get(
            url, headers=_auth(), params=[*query, ("artifact_sha256", "invalid")]
        ).status_code
        == 400
    )
    context.predeploy_history_store = None
    assert client.get(url, headers=_auth(), params=[*query, digest]).status_code == 503


def _runner(tmp_path, monkeypatch, receipt=None):
    module = _cli()
    monkeypatch.setenv("AIOPS_PREDEPLOY_API_URL", "https://review.example.test")
    monkeypatch.setenv("AIOPS_PREDEPLOY_REVIEW_TOKEN", "private-reader-fixture")
    monkeypatch.setattr(module, "_checkout_commit", lambda: "a" * 40)
    artifact = tmp_path / "plan.json"
    artifact.write_text(json.dumps({"resource_changes": []}))
    source = module.inspect_artifact("terraform_plan", {"resource_changes": []})
    receipt = receipt or _receipt()
    receipt = AssessmentReceipt.model_validate(
        {**receipt.model_dump(), "artifact_sha256": source["sha256"]}
    )
    scope = {"subscription": ["a", "b"], "region": ["eastus"]}
    contract = review_contract(receipt, scope)
    args = [
        "--artifact",
        str(artifact),
        "--source",
        "terraform_plan",
        "--assessment-id",
        receipt.assessment_id,
        "--review-sha256",
        contract["review_sha256"],
        "--scope-json",
        json.dumps(scope),
        "--repository",
        "owner/repo",
    ]
    return module, args, artifact, contract


@pytest.mark.parametrize("clear,expected", [(True, 0), (False, 2)])
def test_cli_outputs_bound_report_and_safe_summary_using_only_one_get(
    tmp_path, monkeypatch, capsys, clear, expected
):
    module, args, _, contract = _runner(
        tmp_path, monkeypatch, _clear_receipt() if clear else None
    )
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    requests = []

    def handler(request):
        requests.append(request)
        assert request.method == "GET" and not request.content
        assert request.headers["Authorization"] == "Bearer private-reader-fixture"
        assert request.url.params.get_list("subscription") == ["a", "b"]
        assert (
            request.url.params["artifact_sha256"]
            == contract["receipt"]["artifact_sha256"]
        )
        return httpx.Response(200, json={"data": contract, "scope": contract["scope"]})

    original = httpx.Client
    factory = Mock(
        side_effect=lambda **kwargs: original(
            transport=httpx.MockTransport(handler), **kwargs
        )
    )
    monkeypatch.setattr(module.httpx, "Client", factory)
    assert module.main(args) == expected
    output = capsys.readouterr()
    report = json.loads(output.out)
    assert report["local_checkout"] == {"repository": "owner/repo", "commit": "a" * 40}
    assert report["binding_sha256"] == review_digest(
        {key: value for key, value in report.items() if key != "binding_sha256"}
    )
    assert report["contract"] == contract
    assert "private-reader-fixture" not in output.out + output.err + summary.read_text()
    assert "No deployment authority" in summary.read_text()
    assert len(requests) == 1
    factory.assert_called_once_with(
        timeout=30.0,
        follow_redirects=False,
        trust_env=False,
        headers={"Accept-Encoding": "identity"},
    )


@pytest.mark.parametrize(
    "raw",
    [
        b'{"password":"do-not-send-this"}',
        b'{"a":1,"a":2}',
        b"[]",
        b'{"value":NaN}',
        b'{"value":9007199254740992}',
        b'{"value":"\\ud800"}',
        b"{" + b'"nested":{' * 30 + b'"a":1' + b"}" * 31,
        b" " * (2 * 1024 * 1024 + 1),
    ],
)
def test_cli_rejects_invalid_or_sensitive_local_input_before_network(
    tmp_path, monkeypatch, capsys, raw
):
    module, args, artifact, _ = _runner(tmp_path, monkeypatch)
    artifact.write_bytes(raw)
    factory = Mock(side_effect=AssertionError("Must not contact API"))
    monkeypatch.setattr(module.httpx, "Client", factory)
    assert module.main(args) == 1
    output = capsys.readouterr()
    assert not output.out and "do-not-send-this" not in output.err
    factory.assert_not_called()


@pytest.mark.parametrize("status", [301, 401, 403, 404, 409, 503])
def test_cli_does_not_follow_redirects_retry_or_echo_server_errors(
    tmp_path, monkeypatch, capsys, status
):
    module, args, _, _ = _runner(tmp_path, monkeypatch)
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            status,
            text="private-server-error",
            headers={"location": "https://untrusted.example.test"},
        )

    original = httpx.Client
    monkeypatch.setattr(
        module.httpx,
        "Client",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    assert module.main(args) == 1
    output = capsys.readouterr()
    assert (
        not output.out
        and "private-server-error" not in output.err
        and "private-reader-fixture" not in output.err
    )
    assert len(requests) == 1


@pytest.mark.parametrize(
    "change",
    ["scope", "identity", "artifact", "review", "digest", "size", "compressed"],
)
def test_cli_rejects_mismatched_or_unbounded_response(
    tmp_path, monkeypatch, capsys, change
):
    module, args, _, contract = _runner(tmp_path, monkeypatch)
    envelope = {"data": contract, "scope": contract["scope"]}
    if change == "scope":
        envelope["scope"] = {}
    elif change in ("identity", "artifact"):
        data = contract["receipt"].copy()
        data["assessment_id" if change == "identity" else "artifact_sha256"] = "b" * (
            32 if change == "identity" else 64
        )
        envelope["data"] = review_contract(
            AssessmentReceipt.model_validate(data), contract["scope"]
        )
    elif change == "digest":
        envelope["data"] = {**contract, "review_sha256": "b" * 64}
    elif change == "review":
        changed = {
            **contract["receipt"],
            "risk_score": contract["receipt"]["risk_score"] + 1,
        }
        envelope["data"] = review_contract(
            AssessmentReceipt.model_validate(changed), contract["scope"]
        )
    original = httpx.Client

    def handler(request):
        if change == "size":
            return httpx.Response(
                200,
                content=b" " * (512 * 1024 + 1),
                headers={"content-type": "application/json"},
            )
        if change == "compressed":
            return httpx.Response(
                200,
                headers={"content-encoding": "br", "content-type": "application/json"},
            )
        return httpx.Response(200, json=envelope)

    monkeypatch.setattr(
        module.httpx,
        "Client",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    assert module.main(args) == 1
    assert not capsys.readouterr().out


@pytest.mark.parametrize(
    "origin",
    [
        "http://review.example.test",
        "https://user:password@review.example.test",
        "https://review.example.test/api/v1",
        "https://review.example.test?token=private",
        "https://review.example.test#private",
        "https://review.example.test:8443",
        "https://review.example.test\n",
    ],
)
def test_cli_rejects_non_origin_or_untrusted_transport_configuration_before_network(
    tmp_path,
    monkeypatch,
    capsys,
    origin,
):
    module, args, _, _ = _runner(tmp_path, monkeypatch)
    monkeypatch.setenv("AIOPS_PREDEPLOY_API_URL", origin)
    factory = Mock(side_effect=AssertionError("No request"))
    monkeypatch.setattr(module.httpx, "Client", factory)
    assert module.main(args) == 1
    output = capsys.readouterr()
    assert "during HTTPS reader configuration" in output.err and not output.out
    assert "password" not in output.err and "private" not in output.err
    factory.assert_not_called()


def test_cli_never_overwrites_the_input_artifact_as_its_summary(
    tmp_path, monkeypatch, capsys
):
    module, args, artifact, _ = _runner(tmp_path, monkeypatch)
    before = artifact.read_bytes()
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(artifact))
    factory = Mock(side_effect=AssertionError("No request"))
    monkeypatch.setattr(module.httpx, "Client", factory)
    assert module.main(args) == 1
    assert artifact.read_bytes() == before and not capsys.readouterr().out
    factory.assert_not_called()


def test_cli_round_trip_against_actual_authorized_api_remains_read_only(
    tmp_path, monkeypatch, capsys
):
    client, _, service, store = _client(tmp_path)
    query = [("subscription", "a"), ("subscription", "b"), ("region", "eastus")]
    assessment = _create(client, query)
    assert _retain(client, assessment, params=query).status_code == 201
    scope = {"subscription": ["a", "b"], "region": ["eastus"]}
    before = store.read("owner", scope)
    receipt = AssessmentReceipt.model_validate(before["receipts"][0])
    module, args, _, _ = _runner(tmp_path, monkeypatch, receipt)
    monkeypatch.setenv("AIOPS_PREDEPLOY_REVIEW_TOKEN", "history-reader-fixture")
    service._assessments.clear()
    original = httpx.Client
    requests = []

    def handler(request):
        requests.append(request)
        response = client.request(
            request.method,
            request.url.path,
            params=request.url.params.multi_items(),
            headers={"Authorization": request.headers["Authorization"]},
        )
        return httpx.Response(response.status_code, json=response.json())

    monkeypatch.setattr(
        module.httpx,
        "Client",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    assert module.main(args) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["contract"]["receipt"] == before["receipts"][0]
    assert store.read("owner", scope) == before
    assert len(requests) == 1 and requests[0].method == "GET"


def test_checkout_binding_requires_actual_clean_commit_and_ci_identity(
    tmp_path, monkeypatch
):
    module = _cli()
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "--quiet"], check=True)
    source = tmp_path / "source.txt"
    source.write_text("trusted")
    subprocess.run(["git", "add", "source.txt"], check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.test",
            "commit",
            "--quiet",
            "-m",
            "fixture",
        ],
        check=True,
    )
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    monkeypatch.delenv("BUILD_SOURCEVERSION", raising=False)
    head = module._checkout_commit()
    assert len(head) == 40
    monkeypatch.setenv("GITHUB_SHA", "f" * 40)
    with pytest.raises(ValueError):
        module._checkout_commit()
    monkeypatch.setenv("GITHUB_SHA", head)
    monkeypatch.setenv("BUILD_SOURCEVERSION", "f" * 40)
    with pytest.raises(ValueError):
        module._checkout_commit()
    monkeypatch.setenv("BUILD_SOURCEVERSION", head)
    source.write_text("dirty")
    with pytest.raises(subprocess.CalledProcessError):
        module._checkout_commit()


def test_manual_workflow_keeps_credentials_on_trusted_main_and_has_no_execution():
    workflow = yaml.load(
        Path(".github/workflows/predeploy-review.yml").read_text(),
        Loader=yaml.BaseLoader,
    )
    assert set(workflow["on"]) == {"workflow_dispatch"}
    assert workflow["permissions"] == {"contents": "read"}
    job = workflow["jobs"]["review"]
    assert (
        job["if"]
        == "github.ref == 'refs/heads/main' && vars.AIOPS_PREDEPLOY_REVIEW_ENABLED == 'true'"
    )
    checkout, _, _, review, upload = job["steps"]
    assert checkout["with"] == {
        "ref": "${{ github.sha }}",
        "persist-credentials": "false",
    }
    assert "${{ inputs." not in review["run"]
    assert (
        review["env"]["AIOPS_PREDEPLOY_REVIEW_TOKEN"]
        == "${{ secrets.AIOPS_PREDEPLOY_REVIEW_TOKEN }}"
    )
    assert (
        upload["if"] == "always()"
        and upload["with"]["path"] == "${{ runner.temp }}/predeploy-review.json"
    )
    for step in job["steps"]:
        assert "az " not in step.get("run", "") and "terraform apply" not in step.get(
            "run", ""
        )
        if "run" in step:
            subprocess.run(["bash", "-n"], input=step["run"], text=True, check=True)
