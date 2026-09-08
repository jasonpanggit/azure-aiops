from __future__ import annotations

import io
import json
import stat
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from scripts import collect_ontology_maintenance_evidence as collector

API_URL = "https://api.private.example.test/service"
API_AUDIENCE = "api://ontology-maintenance"
CONNECTION_ID = "non-production-connection-cloud-id"
MAINTENANCE_TOKEN = "maintenance.jwt.secret"
GENERAL_OPERATOR_TOKEN = "general.operator.jwt.secret"


class FakeTransport:
    def __init__(
        self,
        responses: list[collector.HttpResult | Exception],
    ) -> None:
        self.responses = list(responses)
        self.requests: list[dict[str, Any]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        token: str,
        body: bytes | None = None,
    ) -> collector.HttpResult:
        self.requests.append(
            {
                "method": method,
                "url": url,
                "token": token,
                "body": body,
            }
        )
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _response(status: int, payload: Mapping[str, Any]) -> collector.HttpResult:
    return collector.HttpResult(
        status=status,
        body=json.dumps(payload).encode("utf-8"),
    )


def _accepted(status: int = 202) -> collector.HttpResult:
    return _response(
        status,
        {
            "data": {
                "command_id": "ODC-CLOUD-COMMAND-ID",
                "connection_id": CONNECTION_ID,
                "type": "mark_full_reconciliation_due",
                "status": "pending",
                "revision": 0,
                "created_at": "2026-09-08T00:00:00+00:00",
                "updated_at": "2026-09-08T00:00:00+00:00",
                "raw_cloud_id": "must-not-be-retained",
            },
            "scope": {"subscription": "raw-subscription-id"},
        },
    )


@pytest.fixture
def azure_config_dir(tmp_path: Path) -> Path:
    path = tmp_path / "deployer-azure"
    path.mkdir()
    path.chmod(0o700)
    return path


def _config(azure_config_dir: Path) -> collector.CollectionConfig:
    return collector.CollectionConfig(
        api_url=API_URL,
        api_audience=API_AUDIENCE,
        azure_config_dir=azure_config_dir,
        output_path=azure_config_dir.parent / "maintenance-evidence.json",
    )


def _runner_spy(calls: list[dict[str, Any]]):
    def run(
        command: list[str],
        *,
        check: bool,
        capture_output: bool,
        text: bool,
        timeout: int,
        env: Mapping[str, str],
    ) -> subprocess.CompletedProcess[str]:
        calls.append({"command": command, "env": dict(env), "timeout": timeout})
        assert check is True
        assert capture_output is True
        assert text is True
        return subprocess.CompletedProcess(command, 0, MAINTENANCE_TOKEN + "\n", "")

    return run


def _environment() -> dict[str, str]:
    return {
        "PATH": "/safe/bin",
        "KEEP_ME": "safe",
        "AZURE_CLIENT_ID": "ambient-client",
        "AZURE_TENANT_ID": "ambient-tenant",
        "AZURE_CONFIG_DIR": "/ambient/config",
        "ARM_CLIENT_SECRET": "ambient-secret",
        collector.GENERAL_OPERATOR_TOKEN_ENV: GENERAL_OPERATOR_TOKEN,
    }


def test_token_acquisition_uses_only_mode_0700_cli_context(
    azure_config_dir: Path,
) -> None:
    calls: list[dict[str, Any]] = []
    transport = FakeTransport(
        [
            _response(
                200,
                {"data": {"incremental": {"reconciliation_control": {"revision": 4}}}},
            ),
            _response(403, {"error": {"code": "forbidden"}}),
            _accepted(),
        ]
    )

    report = collector.collect_evidence(
        _config(azure_config_dir),
        {"connection_id": CONNECTION_ID},
        env=_environment(),
        runner=_runner_spy(calls),
        transport=transport,
        nonce_factory=lambda: "fixed-nonce",
    )

    assert report["status"] == "PASS"
    assert calls[0]["command"] == [
        "az",
        "account",
        "get-access-token",
        "--resource",
        API_AUDIENCE,
        "--query",
        "accessToken",
        "--output",
        "tsv",
    ]
    isolated = calls[0]["env"]
    assert isolated["AZURE_CONFIG_DIR"] == str(azure_config_dir.resolve())
    assert isolated["KEEP_ME"] == "safe"
    assert collector.GENERAL_OPERATOR_TOKEN_ENV not in isolated
    assert all(
        not key.startswith(("AZURE_", "ARM_")) or key == "AZURE_CONFIG_DIR"
        for key in isolated
    )
    assert report["azure_context_status"] == "isolated"
    assert report["ambient_credentials_status"] == "removed"


def test_authenticated_general_operator_403_is_required_before_maintenance(
    azure_config_dir: Path,
) -> None:
    transport = FakeTransport(
        [
            _response(200, {"data": {}}),
            _response(403, {"error": {"code": "forbidden"}}),
            _accepted(200),
        ]
    )

    report = collector.collect_evidence(
        _config(azure_config_dir),
        {"connection_id": CONNECTION_ID},
        env=_environment(),
        runner=_runner_spy([]),
        transport=transport,
        nonce_factory=lambda: "403-proof",
    )

    assert report["status"] == "PASS"
    assert report["general_operator_evidence"] == "authenticated_forbidden"
    assert report["general_operator_http_status"] == 403
    assert transport.requests[0]["token"] == GENERAL_OPERATOR_TOKEN
    assert transport.requests[1]["token"] == GENERAL_OPERATOR_TOKEN
    assert transport.requests[2]["token"] == MAINTENANCE_TOKEN


def test_unverifiable_403_fails_closed_without_maintenance_post(
    azure_config_dir: Path,
) -> None:
    transport = FakeTransport(
        [
            _response(200, {"data": {}}),
            _response(403, {"html": "proxy denied"}),
        ]
    )

    report = collector.collect_evidence(
        _config(azure_config_dir),
        {"connection_id": CONNECTION_ID},
        env=_environment(),
        runner=_runner_spy([]),
        transport=transport,
        nonce_factory=lambda: "unverified-denial",
    )

    assert report["status"] == "FAIL"
    assert report["failure_status"] == "general_operator_denial_unverified"
    assert report["general_operator_evidence"] == "unverified"
    assert len(transport.requests) == 2


def test_revision_conflict_is_parsed_safely_and_retried_once(
    azure_config_dir: Path,
) -> None:
    transport = FakeTransport(
        [
            _response(200, {"data": {"incremental": {"pending_count": 0}}}),
            _response(403, {"error": {"code": "forbidden"}}),
            _response(
                409,
                {
                    "error": {
                        "code": "conflict",
                        "message": f"do not retain {CONNECTION_ID}",
                        "details": {"current_revision": "7"},
                    }
                },
            ),
            _accepted(201),
        ]
    )

    report = collector.collect_evidence(
        _config(azure_config_dir),
        {"connection_id": CONNECTION_ID},
        env=_environment(),
        runner=_runner_spy([]),
        transport=transport,
        nonce_factory=lambda: "retry-proof",
    )

    maintenance_bodies = [
        json.loads(request["body"]) for request in transport.requests[2:]
    ]
    assert [body["expected_revision"] for body in maintenance_bodies] == [0, 7]
    assert (
        maintenance_bodies[0]["idempotency_key"]
        == maintenance_bodies[1]["idempotency_key"]
    )
    assert report["revision_source_status"] == "conflict_recovered"
    assert report["revision_conflict_count"] == 1
    assert report["maintenance_attempt_count"] == 2
    assert report["maintenance_http_status"] == 201


@pytest.mark.parametrize("rejected_status", [204, 400, 500])
def test_non_accepted_maintenance_statuses_fail_closed(
    azure_config_dir: Path,
    rejected_status: int,
) -> None:
    transport = FakeTransport(
        [
            _response(200, {"data": {}}),
            _response(403, {"error": {"code": "forbidden"}}),
            _response(rejected_status, {"error": "sensitive response body"}),
        ]
    )

    report = collector.collect_evidence(
        _config(azure_config_dir),
        {"connection_id": CONNECTION_ID},
        env=_environment(),
        runner=_runner_spy([]),
        transport=transport,
        nonce_factory=lambda: "rejected-status",
    )

    assert report["status"] == "FAIL"
    assert report["failure_status"] == "maintenance_not_accepted"
    assert "sensitive response body" not in json.dumps(report)


def test_revision_conflict_is_retried_only_once(
    azure_config_dir: Path,
) -> None:
    conflict = _response(
        409,
        {
            "error": {
                "code": "conflict",
                "details": {"current_revision": 8},
            }
        },
    )
    transport = FakeTransport(
        [
            _response(200, {"data": {}}),
            _response(403, {"error": {"code": "forbidden"}}),
            conflict,
            conflict,
        ]
    )

    report = collector.collect_evidence(
        _config(azure_config_dir),
        {"connection_id": CONNECTION_ID},
        env=_environment(),
        runner=_runner_spy([]),
        transport=transport,
        nonce_factory=lambda: "one-retry",
    )

    assert report["status"] == "FAIL"
    assert report["failure_status"] == "maintenance_not_accepted"
    assert len(transport.requests) == 4


@pytest.mark.parametrize("accepted_status", [200, 201, 202])
def test_only_success_statuses_with_durable_authorized_command_are_accepted(
    azure_config_dir: Path,
    accepted_status: int,
) -> None:
    transport = FakeTransport(
        [
            _response(
                200,
                {"data": {"reconciliation_control": {"revision": 3}}},
            ),
            _response(403, {"error": {"code": "forbidden"}}),
            _accepted(accepted_status),
        ]
    )

    report = collector.collect_evidence(
        _config(azure_config_dir),
        {"connection_id": CONNECTION_ID},
        env=_environment(),
        runner=_runner_spy([]),
        transport=transport,
        nonce_factory=lambda: "accepted-proof",
    )

    posted = json.loads(transport.requests[-1]["body"])
    assert posted == {
        "expected_revision": 3,
        "reason": collector.MAINTENANCE_REASON,
        "idempotency_key": "phase13-plan20-accepted-proof",
        "cadence_seconds": collector.MAINTENANCE_CADENCE_SECONDS,
    }
    assert report["maintenance_http_status"] == accepted_status
    assert report["maintenance_command_status"] == "pending"
    assert report["durability_status"] == "verified"
    assert report["authorization_status"] == "verified"
    assert report["coordinator_job_start_count"] == 0


def test_report_redacts_all_live_values_and_response_content(
    azure_config_dir: Path,
) -> None:
    transport = FakeTransport(
        [
            _response(200, {"data": {}}),
            _response(403, {"error": {"code": "forbidden"}}),
            _response(
                202,
                {
                    "data": {
                        "command_id": "raw-cloud-command-id",
                        "connection_id": CONNECTION_ID,
                        "type": "mark_full_reconciliation_due",
                        "status": "pending",
                        "revision": 0,
                        "created_at": "2026-09-08T00:00:00+00:00",
                        "updated_at": "2026-09-08T00:00:00+00:00",
                    },
                    "error": "raw-response-error",
                    "scope": {"subscription": "raw-cloud-scope"},
                },
            ),
        ]
    )

    report = collector.collect_evidence(
        _config(azure_config_dir),
        {"connection_id": CONNECTION_ID},
        env=_environment(),
        runner=_runner_spy([]),
        transport=transport,
        nonce_factory=lambda: "redaction-proof",
    )

    serialized = json.dumps(report, sort_keys=True)
    forbidden_values = (
        API_URL,
        API_AUDIENCE,
        CONNECTION_ID,
        MAINTENANCE_TOKEN,
        GENERAL_OPERATOR_TOKEN,
        "raw-cloud-command-id",
        "raw-response-error",
        "raw-cloud-scope",
        "phase13-plan20-redaction-proof",
    )
    assert all(value not in serialized for value in forbidden_values)
    assert report["target_hash"].startswith("sha256:")
    assert report["connection_hash"].startswith("sha256:")
    assert report["maintenance_command_hash"].startswith("sha256:")


def test_missing_general_operator_token_records_unavailable_and_makes_no_calls(
    azure_config_dir: Path,
) -> None:
    transport = FakeTransport([])

    def unexpected_runner(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("Azure CLI must not run without denial credentials")

    report = collector.collect_evidence(
        _config(azure_config_dir),
        {"connection_id": CONNECTION_ID},
        env={"PATH": "/safe/bin"},
        runner=unexpected_runner,
        transport=transport,
    )

    assert report["status"] == "FAIL"
    assert report["general_operator_evidence"] == "unavailable"
    assert report["failure_status"] == "general_operator_token_missing"
    assert report["request_count"] == 0
    assert transport.requests == []


def test_cli_persists_sanitized_unavailable_evidence_and_exits_nonzero(
    azure_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = azure_config_dir.parent / "missing-token-evidence.json"
    monkeypatch.delenv(collector.GENERAL_OPERATOR_TOKEN_ENV, raising=False)
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(json.dumps({"connection_id": CONNECTION_ID})),
    )

    exit_code = collector.main(
        [
            "--api-url",
            API_URL,
            "--api-audience",
            API_AUDIENCE,
            "--azure-config-dir",
            str(azure_config_dir),
            "--output",
            str(output),
        ]
    )

    report = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 2
    assert report["status"] == "FAIL"
    assert report["general_operator_evidence"] == "unavailable"
    assert report["failure_status"] == "general_operator_token_missing"
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    serialized = json.dumps(report)
    assert API_URL not in serialized
    assert API_AUDIENCE not in serialized
    assert CONNECTION_ID not in serialized


def test_connection_id_is_accepted_only_from_bounded_stdin_contract() -> None:
    contract = collector.load_contract(
        io.StringIO(json.dumps({"connection_id": CONNECTION_ID}))
    )
    assert contract == {"connection_id": CONNECTION_ID}

    with pytest.raises(collector.EvidenceCollectionError):
        collector.load_contract(
            io.StringIO(
                json.dumps(
                    {
                        "connection_id": CONNECTION_ID,
                        "token": "must-never-be-accepted",
                    }
                )
            )
        )


def test_non_private_azure_cli_directory_is_rejected(tmp_path: Path) -> None:
    azure_home = tmp_path / "azure"
    azure_home.mkdir()
    azure_home.chmod(0o755)

    with pytest.raises(
        collector.EvidenceCollectionError,
        match="azure_config_dir_not_private",
    ):
        collector.validate_azure_config_dir(azure_home)

    assert stat.S_IMODE(azure_home.stat().st_mode) == 0o755
