from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from api.scope import Scope
from operations.observability_arg_reader import (
    ArgObservabilityReader,
)
from operations.observability_scenarios import evaluate_diagnostic_settings
from operations.workload_logging_policy import (
    POLICY_DOCUMENT,
    WorkloadLoggingPolicyStore,
    WorkloadLoggingPolicyUnavailable,
)
from storage.onelake_documents import DocumentSnapshot

NOW = datetime(2026, 10, 26, 9, 5, tzinfo=UTC)
OBSERVED_AT = "2026-10-26T09:00:00Z"
SCOPE = Scope.from_mapping({"subscription": ["sub-a"]})
VM1 = "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-1"
LOG_WORKSPACE = "log_analytics:workspace-123"
EXTERNAL_WORKSPACE = (
    "log_analytics:/subscriptions/sub-logs/resourceGroups/logging/providers/"
    "Microsoft.OperationalInsights/workspaces/central"
)


def policy(**changes):
    return {
        "schema_version": 1,
        "policy_id": "logging-policy-sub-a",
        "version": "2026.1",
        "revision": 7,
        "approval_status": "approved",
        "approved_by": "platform-logging-board",
        "approved_at": "2026-10-01T12:00:00Z",
        "valid_until": "2027-01-01T00:00:00Z",
        "scope": {"subscription_ids": ["sub-a"]},
        "supported_resource_types": ["Microsoft.Compute/virtualMachines"],
        "required_categories": {"Microsoft.Compute/virtualMachines": ["AuditEvent"]},
        "required_destinations": {"Microsoft.Compute/virtualMachines": [LOG_WORKSPACE]},
        "exceptions": [],
        **changes,
    }


class Documents:
    def __init__(self, payload=None):
        self.payload = payload
        self.paths = []

    def read_snapshot(self, path):
        self.paths.append(path)
        return (
            DocumentSnapshot(
                payload=self.payload or {},
                etag='"sha256:policy-revision"',
            )
            if self.payload is not None
            else DocumentSnapshot(payload={}, etag=None)
        )


class FailingDocuments:
    def read_snapshot(self, path):
        raise OSError("document store unavailable")


class DiagnosticClient:
    def __init__(self, settings=None, error=None):
        self.settings = [] if settings is None else settings
        self.error = error
        self.calls = []

    def list_resource_settings(self, resource_id, *, authorized_subscription_ids):
        self.calls.append((resource_id, authorized_subscription_ids))
        if self.error:
            raise self.error
        return self.settings


def inventory(resources=None, *, total=None, warnings=None):
    rows = (
        [
            {
                "resource_id": VM1,
                "resource_type": "Microsoft.Compute/virtualMachines",
                "subscription_id": "sub-a",
            }
        ]
        if resources is None
        else resources
    )
    return {
        "resources": rows,
        "total": len(rows) if total is None else total,
        "observed_at": OBSERVED_AT,
        "scope_qualification": {"status": "supported"},
        "warnings": [] if warnings is None else warnings,
    }


def configured_setting(workspace_id="workspace-123"):
    return {
        "properties": {
            "logs": [
                {"category": "AuditEvent", "enabled": True},
                {"category": "Other", "enabled": False},
            ],
            "workspaceId": workspace_id,
        }
    }


def test_category_groups_abstain_without_qualified_expansion():
    setting = configured_setting()
    setting["properties"]["logs"] = [{"categoryGroup": "allLogs", "enabled": True}]
    reader, _, _ = make_reader(policy(), DiagnosticClient([setting]))
    evidence = reader.read_diagnostic_settings(SCOPE, inventory())
    assert evidence.settings_complete is False
    assert evidence.unknown_resource_ids == (VM1,)
    with pytest.raises(ValueError, match="incomplete or stale"):
        evaluate_diagnostic_settings(inventory(), evidence, scope=SCOPE)


def test_categories_must_reach_each_present_required_destination():
    elsewhere = configured_setting("different-workspace")
    required_destination = configured_setting()
    required_destination["properties"]["logs"] = [
        {"category": "Other", "enabled": True}
    ]
    reader, _, _ = make_reader(
        policy(), DiagnosticClient([elsewhere, required_destination])
    )
    evidence = reader.read_diagnostic_settings(SCOPE, inventory())
    assessment = evaluate_diagnostic_settings(inventory(), evidence, scope=SCOPE)
    assert assessment["findings"]["count"] == 1
    finding = assessment["findings"]["items"][0]
    assert finding["missing_categories"] == ["auditevent"]
    assert finding["missing_categories_by_destination"] == {
        LOG_WORKSPACE: ["auditevent"]
    }


def make_reader(
    policy_document=None,
    diagnostic_client=None,
    *,
    connections=None,
):
    connection = SimpleNamespace(
        subscription_id="sub-a",
        connection_id="conn-a",
        is_active=True,
    )
    docs = Documents(policy_document)
    client = diagnostic_client or DiagnosticClient([configured_setting()])
    reader = ArgObservabilityReader(
        live_resources=object(),
        connections=lambda: [connection] if connections is None else connections,
        clock=lambda: NOW,
        diagnostic_client_factory=lambda _connection: client,
        logging_policy_store=WorkloadLoggingPolicyStore(
            docs,
            clock=lambda: NOW,
        ),
    )
    return reader, docs, client


def test_policy_document_requires_review_and_exact_subscription_scope():
    store = WorkloadLoggingPolicyStore(Documents(policy()), clock=lambda: NOW)
    accepted = store.read(subscription_ids=["sub-a"])
    assert accepted.policy_id == "logging-policy-sub-a"
    assert accepted.version == "2026.1"
    assert accepted.revision == 7
    assert accepted.approved_by == "platform-logging-board"
    assert accepted.freshness == "fresh"

    with pytest.raises(WorkloadLoggingPolicyUnavailable):
        store.read(subscription_ids=["sub-b"])
    with pytest.raises(WorkloadLoggingPolicyUnavailable):
        WorkloadLoggingPolicyStore(Documents(), clock=lambda: NOW).read(
            subscription_ids=["sub-a"]
        )


def test_policy_source_failure_is_unavailable_not_default_policy():
    store = WorkloadLoggingPolicyStore(FailingDocuments(), clock=lambda: NOW)
    with pytest.raises(WorkloadLoggingPolicyUnavailable):
        store.read(subscription_ids=["sub-a"])


@pytest.mark.parametrize(
    "changes",
    [
        {"approval_status": "draft"},
        {"approved_by": ""},
        {"scope": {"subscription_ids": ["sub-a", "sub-b"]}},
        {"required_categories": {"Microsoft.Compute/virtualMachines": []}},
        {"required_destinations": {"Microsoft.Compute/virtualMachines": []}},
        {
            "exceptions": [
                {
                    "resource_id": "/subscriptions/sub-b/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-x",
                    "categories": ["AuditEvent"],
                    "destinations": [],
                    "expires_at": "2027-01-01T00:00:00Z",
                    "approved_by": "reviewer",
                    "reason": "approved",
                }
            ]
        },
    ],
)
def test_malformed_or_unapproved_policy_is_unavailable(changes):
    store = WorkloadLoggingPolicyStore(
        Documents(policy(**changes)),
        clock=lambda: NOW,
    )
    with pytest.raises(WorkloadLoggingPolicyUnavailable):
        store.read(subscription_ids=["sub-a"])


def test_expired_approved_policy_is_stale_not_silently_defaulted():
    store = WorkloadLoggingPolicyStore(
        Documents(
            policy(
                approved_at="2025-10-01T12:00:00Z",
                valid_until="2026-01-01T00:00:00Z",
            )
        ),
        clock=lambda: NOW,
    )
    assert store.read(subscription_ids=["sub-a"]).freshness == "stale"


def test_policy_schema_version_rejects_boolean_integer_alias():
    store = WorkloadLoggingPolicyStore(
        Documents(policy(schema_version=True)),
        clock=lambda: NOW,
    )
    with pytest.raises(WorkloadLoggingPolicyUnavailable):
        store.read(subscription_ids=["sub-a"])


def test_diagnostic_settings_source_uses_existing_inventory_and_per_connection_arm_read():
    reader, docs, client = make_reader(policy())
    evidence = reader.read_diagnostic_settings(SCOPE, inventory())
    assessment = evaluate_diagnostic_settings(inventory(), evidence, scope=SCOPE)

    assert docs.paths == [POLICY_DOCUMENT]
    assert client.calls == [(VM1, {"sub-a"})]
    assert evidence.policy_id == "logging-policy-sub-a"
    assert evidence.policy_approved_by == "platform-logging-board"
    assert evidence.policy_revision == 7
    assert evidence.settings[0].categories == ("AuditEvent",)
    assert evidence.settings[0].destinations == (LOG_WORKSPACE,)
    # The snapshot's source age is not qualified; no result claims full health.
    assert assessment["status"] == "partial"
    assert assessment["findings"]["count"] == 0
    assert assessment["policy"]["version"] == "2026.1"
    assert assessment["policy"]["approved_by"] == "platform-logging-board"


def test_missing_category_and_destination_are_evaluated_from_explicit_policy():
    reader, _docs, _client = make_reader(policy(), DiagnosticClient([]))
    evidence = reader.read_diagnostic_settings(SCOPE, inventory())
    result = evaluate_diagnostic_settings(inventory(), evidence, scope=SCOPE)
    assert result["diagnostic_settings_coverage"]["missing_category_count"] == 1
    assert result["diagnostic_settings_coverage"]["missing_destination_count"] == 1
    assert result["diagnostic_settings_coverage"]["outcome"] == "gaps_found"
    assert result["status"] == "partial"


def test_exception_is_scoped_approved_and_time_bounded():
    exception = {
        "resource_id": VM1,
        "categories": ["AuditEvent"],
        "destinations": [LOG_WORKSPACE],
        "expires_at": "2026-12-01T00:00:00Z",
        "approved_by": "security-reviewer",
        "reason": "approved workload exception",
    }
    reader, _, _ = make_reader(policy(exceptions=[exception]), DiagnosticClient([]))
    evidence = reader.read_diagnostic_settings(SCOPE, inventory())
    result = evaluate_diagnostic_settings(inventory(), evidence, scope=SCOPE)
    assert result["diagnostic_settings_coverage"]["missing_category_count"] == 0
    assert result["diagnostic_settings_coverage"]["missing_destination_count"] == 0
    assert result["policy"]["active_exception_count"] == 1


def test_external_destination_is_compared_but_never_traversed():
    external = EXTERNAL_WORKSPACE
    reader, _, client = make_reader(
        policy(required_destinations={"Microsoft.Compute/virtualMachines": [external]}),
        DiagnosticClient(
            [configured_setting(workspace_id=external.removeprefix("log_analytics:"))]
        ),
    )
    evidence = reader.read_diagnostic_settings(SCOPE, inventory())
    result = evaluate_diagnostic_settings(inventory(), evidence, scope=SCOPE)
    assert result["diagnostic_settings_coverage"]["missing_destination_count"] == 0
    assert client.calls == [(VM1, {"sub-a"})]
    assert all("sub-logs" not in resource_id for resource_id, _ in client.calls)


def test_out_of_scope_inventory_row_is_denied_before_arm_requests():
    reader, _, client = make_reader(policy())
    foreign = {
        "resource_id": VM1.replace("sub-a", "sub-b"),
        "resource_type": "Microsoft.Compute/virtualMachines",
        "subscription_id": "sub-b",
    }
    with pytest.raises(PermissionError):
        reader.read_diagnostic_settings(SCOPE, inventory([foreign]))
    assert client.calls == []


def test_conflicting_inventory_subscription_metadata_is_denied_before_arm():
    reader, _, client = make_reader(policy())
    mismatched = {
        **inventory()["resources"][0],
        "subscription_id": "sub-b",
    }
    with pytest.raises(PermissionError):
        reader.read_diagnostic_settings(SCOPE, inventory([mismatched]))
    assert client.calls == []


def test_incomplete_inventory_never_marks_settings_collection_complete():
    reader, _, _ = make_reader(policy())
    result = reader.read_diagnostic_settings(
        SCOPE,
        inventory(total=2),
    )
    assert result.settings_complete is False
    with pytest.raises(ValueError):
        evaluate_diagnostic_settings(inventory(total=2), result, scope=SCOPE)


def test_resource_read_bound_counts_unqueried_supported_resources_as_unknown():
    second_id = VM1.replace("vm-1", "vm-2")
    resources = [
        inventory()["resources"][0],
        {
            "resource_id": second_id,
            "resource_type": "Microsoft.Compute/virtualMachines",
            "subscription_id": "sub-a",
        },
    ]
    connection = SimpleNamespace(
        subscription_id="sub-a",
        connection_id="conn-a",
        is_active=True,
    )
    client = DiagnosticClient([configured_setting()])
    reader = ArgObservabilityReader(
        live_resources=object(),
        connections=lambda: [connection],
        clock=lambda: NOW,
        diagnostic_client_factory=lambda _connection: client,
        logging_policy_store=WorkloadLoggingPolicyStore(
            Documents(policy()),
            clock=lambda: NOW,
        ),
        max_diagnostic_resources=1,
    )
    evidence = reader.read_diagnostic_settings(SCOPE, inventory(resources))
    assert client.calls == [(VM1, {"sub-a"})]
    assert evidence.unknown_resource_ids == (second_id,)
    assert evidence.settings_complete is False


def test_missing_log_collection_is_malformed_not_an_empty_configuration():
    reader, _docs, _client = make_reader(
        policy(),
        DiagnosticClient([{"properties": {"workspaceId": "workspace-123"}}]),
    )
    evidence = reader.read_diagnostic_settings(SCOPE, inventory())
    assert evidence.settings_complete is False
    assert evidence.unknown_resource_ids == (VM1,)


@pytest.mark.parametrize(
    "status,field",
    [
        (403, "unreadable_resource_ids"),
        (404, "unknown_resource_ids"),
        (503, "unknown_resource_ids"),
    ],
)
def test_denied_missing_or_failed_arm_read_is_incomplete(status, field):
    from onboarding.azure_clients import DiagnosticSettingsReadError

    reader, _, _ = make_reader(
        policy(),
        DiagnosticClient(
            error=DiagnosticSettingsReadError("failed", status_code=status)
        ),
    )
    evidence = reader.read_diagnostic_settings(SCOPE, inventory())
    assert evidence.settings_complete is False
    assert getattr(evidence, field) == (VM1,)
    with pytest.raises(ValueError):
        evaluate_diagnostic_settings(inventory(), evidence, scope=SCOPE)
