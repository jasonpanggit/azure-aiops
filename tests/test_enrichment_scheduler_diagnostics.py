from __future__ import annotations

import io
import json
from types import SimpleNamespace

import pytest

from scripts.refresh_exposure_enrichment import main


@pytest.mark.parametrize("stage", ["prefetch_build", "prefetch_run", "prefetch_report"])
@pytest.mark.parametrize(
    ("error", "category", "exit_code"),
    [
        (ValueError("secret-value"), "value_error", 2),
        (TimeoutError("secret-token"), "timeout_error", 1),
        (OSError("secret-path"), "os_error", 1),
        (RuntimeError("secret-provider-response"), "unexpected_error", 1),
    ],
)
def test_prefetch_failure_reports_safe_stage_and_category(stage, error, category, exit_code):
    def fail():
        raise error

    def factory(**_kwargs):
        if stage == "prefetch_build":
            fail()
        return SimpleNamespace(
            run=lambda **_: fail() if stage == "prefetch_run" else SimpleNamespace(to_dict=fail)
        )

    output = io.StringIO()
    assert main(
        ["--prefetch-generation"], prefetch_factory=factory, stdout=output
    ) == exit_code
    report = json.loads(output.getvalue())
    assert report["failure_stage"] == stage
    assert report["error_category"] == category
    assert report["status"] == "failed"
    assert report["outcomes"] == []
    assert "secret" not in output.getvalue()
    assert "Traceback" not in output.getvalue()


def test_conflicting_arguments_are_rejected_before_service_construction():
    def unexpected(**_kwargs):
        pytest.fail("Invalid arguments must not construct a prefetch service")

    output = io.StringIO()
    assert main(
        ["--prefetch-generation", "--force"],
        prefetch_factory=unexpected,
        stdout=output,
    ) == 2
    assert json.loads(output.getvalue()) == {
        "status": "failed",
        "safe_error_code": "invalid_refresh_contract",
        "outcomes": [],
        "failure_stage": "arguments",
        "error_category": "value_error",
    }


@pytest.mark.parametrize("stage", ["worker_build", "target_selection", "worker_refresh"])
def test_worker_failure_reports_operation_without_exception_text(stage):
    def fail(*_args, **_kwargs):
        raise RuntimeError("secret-store-response")

    def factory(**_kwargs):
        if stage == "worker_build":
            fail()
        return SimpleNamespace(
            cache=SimpleNamespace(records=fail),
            refresh=fail,
        )

    output = io.StringIO()
    arguments = ["--all-due"] if stage == "target_selection" else [
        "--source", "nvd", "--id", "CVE-2026-0001"
    ]
    assert main(arguments, worker_factory=factory, stdout=output) == 1
    report = json.loads(output.getvalue())
    assert report["failure_stage"] == stage
    assert report["error_category"] == "unexpected_error"
    assert "secret" not in output.getvalue()


def test_custom_exception_class_name_and_string_are_not_serialized():
    class SecretTenantTokenError(Exception):
        def __str__(self):
            return "private-exception-text"

    def factory(**_kwargs):
        raise SecretTenantTokenError()

    output = io.StringIO()
    assert main(
        ["--prefetch-generation"], prefetch_factory=factory, stdout=output
    ) == 1
    report = json.loads(output.getvalue())
    assert report["error_category"] == "unexpected_error"
    assert "SecretTenantTokenError" not in output.getvalue()
    assert "private-exception-text" not in output.getvalue()


def test_successful_prefetch_report_is_unchanged():
    original = {"status": "succeeded", "generation_id": "g1", "outcomes": []}
    output = io.StringIO()
    assert main(
        ["--prefetch-generation"],
        prefetch_factory=lambda **_: SimpleNamespace(
            run=lambda **_: SimpleNamespace(to_dict=lambda: original)
        ),
        stdout=output,
    ) == 0
    assert json.loads(output.getvalue()) == original


def test_report_write_failure_has_its_own_stage_when_output_recovers():
    class Output(io.StringIO):
        failed = False

        def write(self, value):
            if not self.failed:
                self.failed = True
                raise OSError("secret-output-path")
            return super().write(value)

    output = Output()
    assert main(
        ["--prefetch-generation"],
        prefetch_factory=lambda **_: SimpleNamespace(
            run=lambda **_: SimpleNamespace(to_dict=lambda: {"status": "succeeded"})
        ),
        stdout=output,
    ) == 1
    report = json.loads(output.getvalue())
    assert report["failure_stage"] == "report_write"
    assert report["error_category"] == "os_error"
    assert "secret" not in output.getvalue()
