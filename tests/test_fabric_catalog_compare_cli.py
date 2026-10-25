from __future__ import annotations

import copy
import json
import os
import subprocess
import sys

import httpx
import pytest

from fabric import auth, catalog_compare_cli
from fabric.catalog_changes import compare_catalog_reports, validate_catalog_report
from fabric.config import FabricRuntimeConfig

WORKSPACE = "2c1fea36-104d-4c26-86db-12e09e432b41"
ITEM = "f995229d-970e-44ec-8af5-df9e25261d19"
SECOND = "bb479201-8ab1-4fde-ab6c-9f9a16477115"


def _report(*, current=False, item_id=ITEM, name="Item"):
    timestamp = "2026-10-25T01:00:00Z" if current else "2026-10-25T00:00:00Z"
    item = {
        "item_id": item_id, "item_type": "Lakehouse", "display_name": name,
        "description": "", "workspace_id": WORKSPACE,
    }
    return {
        "status": "advisory_metadata_verified",
        "authentication_mode": "managed_identity",
        "evidence": {
            "source": "onelake_catalog_verified_items",
            "coverage": "partial", "authoritative": False,
            "verification_scope": "item_metadata_only",
            "requires_direct_verification": False, "requires_schema_verification": True,
            "catalog": {
                "source": "onelake_catalog", "workspace_id": WORKSPACE,
                "observed_at": timestamp, "pages_fetched": 1,
                "search_complete": True, "coverage": "partial", "authoritative": False,
                "requires_direct_verification": True, "candidates": [copy.deepcopy(item)],
            },
            "verified_items": [{
                "current": item, "endpoint": f"/workspaces/{WORKSPACE}/items/{item_id}",
                "verified_at": timestamp, "catalog_metadata_changed": False,
            }],
        },
    }


@pytest.fixture(autouse=True)
def forbid_live_access(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Offline comparison must not configure or contact a provider")

    monkeypatch.setattr(FabricRuntimeConfig, "load", forbidden)
    monkeypatch.setattr(auth, "build_credential", forbidden)
    monkeypatch.setattr(httpx, "Client", forbidden)
    monkeypatch.setenv("AIOPS_FABRIC_CONFIG_JSON", "invalid-config-must-not-be-loaded")


def _inputs(tmp_path, before=None, after=None):
    baseline = tmp_path / "baseline.json"
    current = tmp_path / "current.json"
    baseline.write_text(json.dumps(before if before is not None else _report()), encoding="utf-8")
    current.write_text(
        json.dumps(after if after is not None else _report(current=True)), encoding="utf-8",
    )
    return baseline, current


@pytest.mark.parametrize("change", ["unchanged", "renamed", "replaced", "empty"])
def test_offline_comparison_reuses_validated_delta_without_input_writes(tmp_path, capsys, change):
    before = _report()
    after = _report(
        current=True, item_id=SECOND if change == "replaced" else ITEM,
        name="Renamed" if change == "renamed" else "Item",
    )
    if change == "empty":
        after["evidence"]["catalog"]["candidates"] = []
        after["evidence"]["verified_items"] = []
    baseline, current = _inputs(tmp_path, before, after)
    original = {path: path.read_bytes() for path in (baseline, current)}
    assert catalog_compare_cli.main(["--baseline", str(baseline), "--current", str(current)]) == 0
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert captured.err == ""
    assert report == {
        "status": "advisory_metadata_compared", "mode": "offline",
        "verification_performed": False,
        "metadata_delta": compare_catalog_reports(
            validate_catalog_report(json.dumps(before)),
            validate_catalog_report(json.dumps(after)),
        ),
    }
    delta = report["metadata_delta"]
    assert len(delta["unchanged"]) == (change == "unchanged")
    assert len(delta["changed"]) == (change == "renamed")
    assert len(delta["added"]) == (change == "replaced")
    assert len(delta["unresolved"]) == (change in {"replaced", "empty"})
    assert delta["retired"] == []
    assert delta["authoritative"] is False
    assert delta["requires_steward_review"] is True
    assert delta["requires_schema_verification"] is True
    assert {path: path.read_bytes() for path in original} == original
    assert set(tmp_path.iterdir()) == {baseline, current}


@pytest.mark.parametrize("target", ["baseline", "current"])
@pytest.mark.parametrize("failure", [
    "missing", "directory", "remote", "malformed", "utf8", "oversized",
    "multibyte-oversized", "duplicate", "deep", "inconsistent",
])
def test_invalid_saved_input_is_sanitized_without_partial_output(
    tmp_path, capsys, target, failure,
):
    baseline, current = _inputs(tmp_path)
    bad = baseline if target == "baseline" else current
    argument = str(bad)
    if failure == "missing":
        bad.unlink()
    elif failure == "directory":
        argument = str(tmp_path)
    elif failure == "remote":
        argument = "https://private-host/private-report?private-token"
    elif failure == "malformed":
        bad.write_text("private-invalid-report", encoding="utf-8")
    elif failure == "utf8":
        bad.write_bytes(b"\xff")
    elif failure == "oversized":
        bad.write_bytes(b"x" * 2_000_001)
    elif failure == "multibyte-oversized":
        bad.write_bytes(("\u00e9" * 1_000_001).encode("utf-8"))
    elif failure == "duplicate":
        bad.write_text('{"private-key":1,"private-key":2}', encoding="utf-8")
    elif failure == "deep":
        bad.write_text("[" * 2000 + "]" * 2000, encoding="utf-8")
    else:
        value = _report()
        value["evidence"]["verified_items"].clear()
        bad.write_text(json.dumps(value), encoding="utf-8")
    args = [
        "--baseline", argument if target == "baseline" else str(baseline),
        "--current", argument if target == "current" else str(current),
    ]
    assert catalog_compare_cli.main(args) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "status": "failed", "failure_stage": "saved_report_validation",
    }
    assert "private" not in captured.err


@pytest.mark.parametrize("failure", ["workspace", "auth", "chronology"])
def test_incompatible_reports_fail_comparison_atomically(tmp_path, capsys, failure):
    before = _report()
    after = _report(current=True)
    if failure == "workspace":
        after["evidence"]["catalog"]["workspace_id"] = SECOND
        after["evidence"]["catalog"]["candidates"] = []
        after["evidence"]["verified_items"] = []
    elif failure == "auth":
        after["authentication_mode"] = "service_principal"
    else:
        before = _report(current=True)
        after = _report()
    baseline, current = _inputs(tmp_path, before, after)
    assert catalog_compare_cli.main(["--baseline", str(baseline), "--current", str(current)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "status": "failed", "failure_stage": "catalog_comparison",
    }


def test_prior_derived_deltas_are_ignored_on_both_inputs(tmp_path, capsys):
    before, after = _report(), _report(current=True)
    before["metadata_delta"] = {"retired": ["untrusted"]}
    after["metadata_delta"] = {"authoritative": True}
    baseline, current = _inputs(tmp_path, before, after)
    assert catalog_compare_cli.main(["--baseline", str(baseline), "--current", str(current)]) == 0
    delta = json.loads(capsys.readouterr().out)["metadata_delta"]
    assert delta["unchanged"] == [ITEM]
    assert delta["retired"] == []
    assert delta["authoritative"] is False


@pytest.mark.parametrize("extra,expected", [(0, 0), (1, 1)])
def test_serialized_byte_limit_accepts_exact_boundary_only(tmp_path, capsys, extra, expected):
    baseline, current = _inputs(tmp_path)
    raw = baseline.read_bytes()
    baseline.write_bytes(raw + b" " * (2_000_000 + extra - len(raw)))
    assert baseline.stat().st_size == 2_000_000 + extra
    assert catalog_compare_cli.main([
        "--baseline", str(baseline), "--current", str(current),
    ]) == expected
    captured = capsys.readouterr()
    if expected == 0:
        assert json.loads(captured.out)["verification_performed"] is False
        assert captured.err == ""
    else:
        assert captured.out == ""
        assert json.loads(captured.err)["failure_stage"] == "saved_report_validation"


def test_module_entrypoint_works_without_config_credentials_or_network(tmp_path):
    baseline, current = _inputs(tmp_path)
    script = """
import runpy, socket, sys
from fabric import auth
from fabric.config import FabricRuntimeConfig
import httpx
def forbidden(*args, **kwargs):
    raise AssertionError("No provider access allowed")
FabricRuntimeConfig.load = forbidden
auth.build_credential = forbidden
httpx.Client = forbidden
socket.socket.connect = forbidden
socket.socket.connect_ex = forbidden
sys.argv = ["fabric.catalog_compare_cli", "--baseline", sys.argv[1], "--current", sys.argv[2]]
runpy.run_module("fabric.catalog_compare_cli", run_name="__main__")
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(baseline), str(current)],
        capture_output=True, text=True, env=dict(os.environ), timeout=30, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert json.loads(result.stdout)["verification_performed"] is False


@pytest.mark.parametrize("args", [
    [], ["--baseline", "a"], ["--current", "b"],
    ["--baseline", "a", "--current", "b", "--config", "ignored.yaml"],
])
def test_required_inputs_and_unsupported_live_options_are_usage_errors(capsys, args):
    with pytest.raises(SystemExit) as exc:
        catalog_compare_cli.main(args)
    assert exc.value.code == 2
    assert capsys.readouterr().out == ""
