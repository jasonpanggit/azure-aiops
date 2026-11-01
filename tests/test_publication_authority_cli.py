import io
import json
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ontology_discovery.publication_authority_cli import (
    ValidationConfigError,
    load_validation_config,
    main,
    run_validation,
)


def _config(tmp_path):
    review = tmp_path / "review.json"
    revocations = tmp_path / "revocations.json"
    review.write_text("{}", encoding="utf-8")
    revocations.write_text("{}", encoding="utf-8")
    return {
        "schema": "publication-authority-validation/v1",
        "reader_client_id": "ad01e219-c3f5-40c7-85c3-7060a86a5bd7",
        "target_id": "191c9b47-2839-4983-97e8-2d8c6f1889eb",
        "sql_target": {
            "workspace_id": "4938f885-3e79-41b1-810a-80b55c01dbb7",
            "item_id": "b003a6fb-eb2a-4226-b079-6033be2ff354",
            "server": (
                "o45cujtupwcencjxrf6zruvbpi-qx4dqslzh2yudaikqc2vyao3w4."
                "database.fabric.microsoft.com"
            ),
            "database": (
                "aiops_publication_control_dev-b003a6fb-eb2a-4226-b079-6033be2ff354"
            ),
        },
        "fabric_item_metadata": {
            "type": "SQLDatabase",
            "id": "b003a6fb-eb2a-4226-b079-6033be2ff354",
            "workspaceId": "4938f885-3e79-41b1-810a-80b55c01dbb7",
            "properties": {
                "databaseName": (
                    "aiops_publication_control_dev-b003a6fb-eb2a-4226-b079-6033be2ff354"
                ),
                "serverFqdn": (
                    "o45cujtupwcencjxrf6zruvbpi-qx4dqslzh2yudaikqc2vyao3w4."
                    "database.fabric.microsoft.com"
                ),
            },
        },
        "expected_target": {
            "tenant_id": "262a3a77-7d74-4684-8937-897d98d2a17a",
            "subscription_id": "890c9bfc-d09c-4143-9ce5-465e75e3eecc",
            "connection_id": "demo",
            "workspace_id": "2c1fea36-104d-4c26-86db-12e09e432b41",
            "item_id": "191c9b47-2839-4983-97e8-2d8c6f1889eb",
            "definition_fingerprint": "sha256:" + "1" * 64,
        },
        "review_path": str(review),
        "revocation_path": str(revocations),
    }


def _write_config(tmp_path, value):
    path = tmp_path / "validation.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_load_config_requires_exact_target_metadata_and_absolute_sources(tmp_path):
    raw = _config(tmp_path)
    parsed = load_validation_config(_write_config(tmp_path, raw))
    assert parsed.reader_client_id == raw["reader_client_id"]
    assert parsed.expected_target == raw["expected_target"]

    raw["fabric_item_metadata"]["workspaceId"] = "00000000-0000-0000-0000-000000000000"
    with pytest.raises(ValidationConfigError, match="sql_target_invalid"):
        load_validation_config(_write_config(tmp_path, raw))


def test_load_config_rejects_unknown_fields_and_relative_paths(tmp_path):
    raw = _config(tmp_path)
    raw["authority_client_id"] = "must-not-be-configurable"
    with pytest.raises(ValidationConfigError, match="config_invalid"):
        load_validation_config(_write_config(tmp_path, raw))

    del raw["authority_client_id"]
    raw["review_path"] = "relative/review.json"
    with pytest.raises(ValidationConfigError, match="review_path_invalid"):
        load_validation_config(_write_config(tmp_path, raw))


def test_load_config_rejects_noncanonical_identity_pins(tmp_path):
    raw = _config(tmp_path)
    raw["reader_client_id"] = "not-a-uuid"
    with pytest.raises(ValidationConfigError, match="config_invalid"):
        load_validation_config(_write_config(tmp_path, raw))


def test_run_validation_uses_read_only_validator_and_reader_identity(
    tmp_path, monkeypatch
):
    import ontology_discovery.publication_authority_cli as cli

    config = load_validation_config(_write_config(tmp_path, _config(tmp_path)))
    credential = Mock()
    captured = {}

    class ReadOnlyIssuer:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def validate(self, operation):
            captured["operation"] = operation
            return "a" * 64

        def issue(self, operation):
            raise AssertionError("read-only CLI must never issue")

    monkeypatch.setattr(cli, "PublicationAuthorityIssuer", ReadOnlyIssuer)
    monkeypatch.setattr(
        cli,
        "SqlPublicationControl",
        lambda target, token, **kwargs: (
            captured.update(target=target, credential=token, **kwargs) or object()
        ),
    )
    release_reader = SimpleNamespace(trust_context=object())
    digest = run_validation(config, release_reader, lambda client_id: credential)

    assert digest == "a" * 64
    assert captured["operation"] == "admit"
    assert captured["expected_client_id"] == config.reader_client_id
    assert "authority" not in captured
    credential.close.assert_called_once_with()


def test_main_is_default_off_without_config(tmp_path):
    stdout, stderr = io.StringIO(), io.StringIO()
    result = main([], environ={}, stdout=stdout, stderr=stderr)

    assert result == 2
    assert json.loads(stderr.getvalue()) == {
        "reason": "publication_validation_config_required",
        "status": "FAIL",
    }
    assert stdout.getvalue() == ""


def test_main_disables_pooling_and_fails_closed_without_trust(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path, _config(tmp_path))
    pyodbc = SimpleNamespace(pooling=True)
    monkeypatch.setitem(sys.modules, "pyodbc", pyodbc)
    stdout, stderr = io.StringIO(), io.StringIO()

    result = main(
        [],
        environ={
            "ONTOLOGY_PUBLICATION_VALIDATION_CONFIG": str(config_path),
        },
        stdout=stdout,
        stderr=stderr,
        reader_factory=lambda env: None,
    )

    assert result == 1
    assert pyodbc.pooling is False
    assert json.loads(stderr.getvalue()) == {
        "reason": "maintenance_trust_config_required",
        "status": "FAIL",
    }
    assert stdout.getvalue() == ""


def test_main_rejects_nonempty_arguments_before_runtime_setup():
    stderr = io.StringIO()
    result = main(
        ["issue"],
        environ={},
        stdout=io.StringIO(),
        stderr=stderr,
    )

    assert result == 2
    assert json.loads(stderr.getvalue()) == {
        "reason": "publication_validation_arguments_unsupported",
        "status": "FAIL",
    }
