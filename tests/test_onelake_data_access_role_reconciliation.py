"""Deterministic OneLake data-access-role REST reconciliation tests.

Covers:
- payload preservation of unrelated roles
- exact least-privilege contract (Path=*, Action=Read, ManagedIdentity member)
- drift detection and failure closure
- ETag If-Match preconditions
- bounded retries with concurrency recomputation
- post-write GET verification and failure closure
"""

from __future__ import annotations

import copy
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# The module under test — will be created in the next commit.
from scripts.reconcile_onelake_data_access_roles import (
    COORDINATOR_SOURCE_PATH,
    COORDINATOR_SOURCE_ROLE_NAME,
    EVIDENCE_ROLE_NAME,
    MAX_RETRIES,
    DataAccessRoleReconciliationError,
    VerificationDriftError,
    build_desired_role,
    merge_roles,
    parse_contract,
    parse_coordinator_source_contract,
    reconcile_all_evidence_items,
    reconcile_coordinator_source,
    reconcile_item_roles,
    reconcile_workspace_viewer,
    verify_roles_match,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

OBJECT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TENANT_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
WORKSPACE_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
ITEM_ID = "dddddddd-dddd-dddd-dddd-dddddddddddd"

UNRELATED_ROLE: dict[str, Any] = {
    "name": "ExistingCustomRole",
    "decisionRules": [
        {
            "effect": "Permit",
            "permission": [
                {"attributeName": "Path", "attributeValueIncludedIn": ["/Tables/sales"]},
                {"attributeName": "Action", "attributeValueIncludedIn": ["Read"]},
            ],
        }
    ],
    "members": {
        "microsoftEntraMembers": [
            {
                "objectId": "99999999-9999-9999-9999-999999999999",
                "objectType": "User",
                "tenantId": TENANT_ID,
            }
        ],
        "fabricItemMembers": [],
    },
}

SECOND_UNRELATED_ROLE: dict[str, Any] = {
    "name": "AnotherRole",
    "decisionRules": [
        {
            "effect": "Permit",
            "permission": [
                {"attributeName": "Path", "attributeValueIncludedIn": ["/Files/reports"]},
                {"attributeName": "Action", "attributeValueIncludedIn": ["Read", "Write"]},
            ],
        }
    ],
    "members": {
        "microsoftEntraMembers": [],
        "fabricItemMembers": [
            {"fabricItemIdentifier": {"itemId": "some-item", "workspaceId": "some-ws"}},
        ],
    },
}


def _expected_evidence_role() -> dict[str, Any]:
    return build_desired_role(OBJECT_ID, TENANT_ID)


def _contract() -> dict[str, object]:
    names = (
        "ontology_discovery_state",
        "ontology_command",
        "ontology_dispatch",
        "ontology_publication",
        "ontology_rbac_validation",
    )
    return {
        "principal_object_id": OBJECT_ID,
        "principal_resource_id": (
            "/subscriptions/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/"
            "resourceGroups/rg/providers/Microsoft.ManagedIdentity/"
            "userAssignedIdentities/evidence"
        ),
        "tenant_id": TENANT_ID,
        "targets": {
            name: {
                "workspace_id": f"00000000-0000-0000-0000-00000000000{index}",
                "item_id": f"10000000-0000-0000-0000-00000000000{index}",
            }
            for index, name in enumerate(names, start=1)
        },
    }


def _coordinator_source_contract() -> dict[str, object]:
    return {
        "principal_object_id": OBJECT_ID,
        "principal_resource_id": (
            "/subscriptions/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/"
            "resourceGroups/rg/providers/Microsoft.ManagedIdentity/"
            "userAssignedIdentities/coordinator"
        ),
        "tenant_id": TENANT_ID,
        "workspace_id": WORKSPACE_ID,
        "item_id": ITEM_ID,
        "path": COORDINATOR_SOURCE_PATH,
    }


def test_contract_requires_exactly_five_isolated_targets() -> None:
    items, object_id, tenant_id, resource_id = parse_contract(_contract())

    assert len(items) == 5
    assert object_id == OBJECT_ID
    assert tenant_id == TENANT_ID
    assert resource_id.endswith("/userAssignedIdentities/evidence")

    invalid = _contract()
    invalid["targets"].pop("ontology_dispatch")
    with pytest.raises(
        DataAccessRoleReconciliationError,
        match="five exact",
    ):
        parse_contract(invalid)


def test_coordinator_source_contract_is_one_exact_read_path() -> None:
    parsed = parse_coordinator_source_contract(
        _coordinator_source_contract()
    )

    assert parsed[0] == OBJECT_ID
    assert parsed[3:] == (WORKSPACE_ID, ITEM_ID)
    desired = build_desired_role(
        OBJECT_ID,
        TENANT_ID,
        role_name=COORDINATOR_SOURCE_ROLE_NAME,
        paths=(COORDINATOR_SOURCE_PATH,),
    )
    path_permission = desired["decisionRules"][0]["permission"][0]
    assert path_permission["attributeValueIncludedIn"] == [
        COORDINATOR_SOURCE_PATH
    ]

    invalid = _coordinator_source_contract()
    invalid["path"] = "*"
    with pytest.raises(
        DataAccessRoleReconciliationError,
        match="path is not exact",
    ):
        parse_coordinator_source_contract(invalid)


def test_coordinator_source_reuses_exact_viewer_and_read_reconcilers() -> None:
    fake_client = MagicMock()
    context = MagicMock()
    context.__enter__.return_value = fake_client

    with (
        patch("httpx.Client", return_value=context),
        patch(
            "scripts.reconcile_onelake_data_access_roles.reconcile_workspace_viewer",
            return_value={"verified": True},
        ) as viewer,
        patch(
            "scripts.reconcile_onelake_data_access_roles.reconcile_item_roles",
            return_value={"verified": True},
        ) as role,
    ):
        result = reconcile_coordinator_source(
            contract=_coordinator_source_contract(),
            token_provider=lambda: "token",
            principal_type_provider=lambda _object, _resource: (
                "ManagedIdentity"
            ),
            dry_run=True,
        )

    assert result["status"] == "PASS"
    viewer.assert_called_once_with(
        client=fake_client,
        workspace_id=WORKSPACE_ID,
        object_id=OBJECT_ID,
        dry_run=True,
    )
    assert role.call_args.kwargs["role_name"] == COORDINATOR_SOURCE_ROLE_NAME
    assert role.call_args.kwargs["paths"] == (COORDINATOR_SOURCE_PATH,)


# ---------------------------------------------------------------------------
# build_desired_role: exact least-privilege contract
# ---------------------------------------------------------------------------


class TestBuildDesiredRole:
    def test_role_name_is_canonical(self) -> None:
        role = build_desired_role(OBJECT_ID, TENANT_ID)
        assert role["name"] == EVIDENCE_ROLE_NAME
        assert role["kind"] == "Policy"

    def test_single_permit_rule_with_wildcard_path_and_read_action(self) -> None:
        role = build_desired_role(OBJECT_ID, TENANT_ID)
        rules = role["decisionRules"]
        assert len(rules) == 1
        rule = rules[0]
        assert rule["effect"] == "Permit"
        perms = {
            p["attributeName"]: p["attributeValueIncludedIn"]
            for p in rule["permission"]
        }
        assert perms == {"Path": ["*"], "Action": ["Read"]}

    def test_single_managed_identity_member(self) -> None:
        role = build_desired_role(OBJECT_ID, TENANT_ID)
        members = role["members"]
        assert members["fabricItemMembers"] == []
        entra = members["microsoftEntraMembers"]
        assert len(entra) == 1
        assert entra[0] == {
            "objectId": OBJECT_ID,
            "objectType": "ManagedIdentity",
            "tenantId": TENANT_ID,
        }

    def test_rejects_empty_object_id(self) -> None:
        with pytest.raises(ValueError, match="objectId"):
            build_desired_role("", TENANT_ID)

    def test_rejects_empty_tenant_id(self) -> None:
        with pytest.raises(ValueError, match="tenantId"):
            build_desired_role(OBJECT_ID, "")


# ---------------------------------------------------------------------------
# merge_roles: unrelated role preservation
# ---------------------------------------------------------------------------


class TestMergeRoles:
    def test_preserves_unrelated_roles(self) -> None:
        existing = [copy.deepcopy(UNRELATED_ROLE)]
        desired = _expected_evidence_role()
        merged = merge_roles(existing, desired)
        unrelated_in_merged = [r for r in merged if r["name"] != EVIDENCE_ROLE_NAME]
        assert len(unrelated_in_merged) == 1
        assert unrelated_in_merged[0] == {
            key: value for key, value in UNRELATED_ROLE.items() if key != "eTag"
        }

    def test_preserves_multiple_unrelated_roles(self) -> None:
        existing = [copy.deepcopy(UNRELATED_ROLE), copy.deepcopy(SECOND_UNRELATED_ROLE)]
        desired = _expected_evidence_role()
        merged = merge_roles(existing, desired)
        unrelated = [r for r in merged if r["name"] != EVIDENCE_ROLE_NAME]
        assert len(unrelated) == 2

    def test_replaces_existing_evidence_role(self) -> None:
        old_evidence = _expected_evidence_role()
        old_evidence["decisionRules"][0]["permission"][1]["attributeValueIncludedIn"] = [
            "Read",
            "Write",
        ]
        existing = [copy.deepcopy(UNRELATED_ROLE), old_evidence]
        desired = _expected_evidence_role()
        merged = merge_roles(existing, desired)
        evidence_roles = [r for r in merged if r["name"] == EVIDENCE_ROLE_NAME]
        assert len(evidence_roles) == 1
        perms = {
            p["attributeName"]: p["attributeValueIncludedIn"]
            for p in evidence_roles[0]["decisionRules"][0]["permission"]
        }
        assert perms["Action"] == ["Read"]

    def test_adds_evidence_role_when_none_exists(self) -> None:
        existing = [copy.deepcopy(UNRELATED_ROLE)]
        desired = _expected_evidence_role()
        merged = merge_roles(existing, desired)
        evidence = [r for r in merged if r["name"] == EVIDENCE_ROLE_NAME]
        assert len(evidence) == 1

    def test_empty_existing_produces_only_desired(self) -> None:
        merged = merge_roles([], _expected_evidence_role())
        assert len(merged) == 1
        assert merged[0]["name"] == EVIDENCE_ROLE_NAME

    def test_does_not_mutate_input_list(self) -> None:
        existing = [copy.deepcopy(UNRELATED_ROLE)]
        original_len = len(existing)
        merge_roles(existing, _expected_evidence_role())
        assert len(existing) == original_len


# ---------------------------------------------------------------------------
# verify_roles_match: drift detection / failure closure
# ---------------------------------------------------------------------------


class TestVerifyRolesMatch:
    def test_passes_when_exact_match(self) -> None:
        desired = _expected_evidence_role()
        actual_roles = [copy.deepcopy(UNRELATED_ROLE), copy.deepcopy(desired)]
        verify_roles_match(actual_roles, desired)  # should not raise

    def test_fails_when_evidence_role_missing(self) -> None:
        desired = _expected_evidence_role()
        actual_roles = [copy.deepcopy(UNRELATED_ROLE)]
        with pytest.raises(VerificationDriftError, match="not found"):
            verify_roles_match(actual_roles, desired)

    def test_fails_when_action_widened(self) -> None:
        desired = _expected_evidence_role()
        widened = copy.deepcopy(desired)
        widened["decisionRules"][0]["permission"][1]["attributeValueIncludedIn"] = [
            "Read",
            "Write",
        ]
        with pytest.raises(VerificationDriftError, match="drift"):
            verify_roles_match([widened], desired)

    def test_fails_when_member_changed(self) -> None:
        desired = _expected_evidence_role()
        wrong_member = copy.deepcopy(desired)
        wrong_member["members"]["microsoftEntraMembers"][0]["objectType"] = "User"
        with pytest.raises(VerificationDriftError, match="drift"):
            verify_roles_match([wrong_member], desired)

    def test_accepts_omitted_object_type_only_with_entra_managed_identity_proof(
        self,
    ) -> None:
        desired = _expected_evidence_role()
        omitted = copy.deepcopy(desired)
        del omitted["members"]["microsoftEntraMembers"][0]["objectType"]

        with pytest.raises(VerificationDriftError, match="drift"):
            verify_roles_match([omitted], desired)

        verify_roles_match(
            [omitted],
            desired,
            verified_principal_type="ManagedIdentity",
        )

    def test_passes_with_additional_unrelated_roles(self) -> None:
        desired = _expected_evidence_role()
        actual = [
            copy.deepcopy(UNRELATED_ROLE),
            copy.deepcopy(SECOND_UNRELATED_ROLE),
            copy.deepcopy(desired),
        ]
        verify_roles_match(actual, desired)  # no raise


# ---------------------------------------------------------------------------
# reconcile_item_roles: ETag, dry-run, retry, verification
# ---------------------------------------------------------------------------


def _mock_get_response(
    roles: list[dict[str, Any]],
    etag: str = '"etag-1"',
    status_code: int = 200,
) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = {"value": roles}
    resp.headers = {"ETag": etag}
    resp.raise_for_status = MagicMock()
    return resp


def _mock_put_response(
    status_code: int = 200,
    etag: str = '"etag-2"',
) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = {"ETag": etag}
    resp.raise_for_status = MagicMock()
    return resp


class TestReconcileItemRolesETag:
    def test_sends_if_match_header_on_put(self) -> None:
        existing = [copy.deepcopy(UNRELATED_ROLE)]
        get_resp = _mock_get_response(existing, etag='"v42"')
        put_resp = _mock_put_response()
        verify_resp = _mock_get_response(
            [copy.deepcopy(UNRELATED_ROLE), _expected_evidence_role()],
            etag='"v43"',
        )

        client = MagicMock()
        client.get.side_effect = [get_resp, verify_resp]
        client.put.return_value = put_resp

        reconcile_item_roles(
            client=client,
            workspace_id=WORKSPACE_ID,
            item_id=ITEM_ID,
            object_id=OBJECT_ID,
            tenant_id=TENANT_ID,
            dry_run=False,
        )

        put_call = client.put.call_args
        assert put_call.kwargs.get("headers", {}).get("If-Match") == '"v42"'


def test_workspace_viewer_is_created_and_verified_without_broadening() -> None:
    client = MagicMock()
    missing = MagicMock()
    missing.json.return_value = {"value": []}
    missing.raise_for_status = MagicMock()
    created = MagicMock(status_code=201)
    verified = MagicMock()
    verified.json.return_value = {
        "value": [
            {
                "principal": {
                    "id": OBJECT_ID,
                    "type": "ServicePrincipal",
                },
                "role": "Viewer",
            }
        ]
    }
    verified.raise_for_status = MagicMock()
    client.get.side_effect = [missing, verified]
    client.post.return_value = created

    result = reconcile_workspace_viewer(
        client=client,
        workspace_id=WORKSPACE_ID,
        object_id=OBJECT_ID,
        dry_run=False,
    )

    assert result["verified"] is True
    assert client.post.call_args.kwargs["json"] == {
        "principal": {"id": OBJECT_ID, "type": "ServicePrincipal"},
        "role": "Viewer",
    }


def test_workspace_viewer_rejects_existing_broader_role() -> None:
    client = MagicMock()
    response = MagicMock()
    response.json.return_value = {
        "value": [
            {
                "principal": {
                    "id": OBJECT_ID,
                    "type": "ServicePrincipal",
                },
                "role": "Contributor",
            }
        ]
    }
    response.raise_for_status = MagicMock()
    client.get.return_value = response

    with pytest.raises(
        DataAccessRoleReconciliationError,
        match="non-Viewer",
    ):
        reconcile_workspace_viewer(
            client=client,
            workspace_id=WORKSPACE_ID,
            object_id=OBJECT_ID,
            dry_run=False,
        )


class TestReconcileItemRolesDryRun:
    def test_dry_run_does_not_put(self) -> None:
        existing = [copy.deepcopy(UNRELATED_ROLE)]
        get_resp = _mock_get_response(existing)
        client = MagicMock()
        client.get.return_value = get_resp

        result = reconcile_item_roles(
            client=client,
            workspace_id=WORKSPACE_ID,
            item_id=ITEM_ID,
            object_id=OBJECT_ID,
            tenant_id=TENANT_ID,
            dry_run=True,
        )

        client.put.assert_not_called()
        assert result["dry_run"] is True
        assert result["would_change"] is True

    def test_dry_run_no_change_when_already_exact(self) -> None:
        existing = [copy.deepcopy(UNRELATED_ROLE), _expected_evidence_role()]
        get_resp = _mock_get_response(existing)
        client = MagicMock()
        client.get.return_value = get_resp

        result = reconcile_item_roles(
            client=client,
            workspace_id=WORKSPACE_ID,
            item_id=ITEM_ID,
            object_id=OBJECT_ID,
            tenant_id=TENANT_ID,
            dry_run=True,
        )

        assert result["would_change"] is False


class TestReconcileItemRolesBoundedRetry:
    def test_retries_on_412_precondition_failed(self) -> None:
        """412 means ETag conflict — refetch and recompute."""
        existing = [copy.deepcopy(UNRELATED_ROLE)]
        get_resp_1 = _mock_get_response(existing, etag='"v1"')
        put_412 = MagicMock()
        put_412.status_code = 412
        put_412.raise_for_status.side_effect = Exception("412 Precondition Failed")

        get_resp_2 = _mock_get_response(existing, etag='"v2"')
        put_ok = _mock_put_response(etag='"v3"')
        verify_resp = _mock_get_response(
            [copy.deepcopy(UNRELATED_ROLE), _expected_evidence_role()],
            etag='"v3"',
        )

        client = MagicMock()
        client.get.side_effect = [get_resp_1, get_resp_2, verify_resp]
        client.put.side_effect = [put_412, put_ok, put_ok]

        result = reconcile_item_roles(
            client=client,
            workspace_id=WORKSPACE_ID,
            item_id=ITEM_ID,
            object_id=OBJECT_ID,
            tenant_id=TENANT_ID,
            dry_run=False,
        )

        assert result["retries"] == 1

    def test_fails_after_max_retries(self) -> None:
        existing = [copy.deepcopy(UNRELATED_ROLE)]
        put_412 = MagicMock()
        put_412.status_code = 412
        put_412.raise_for_status.side_effect = Exception("412")

        get_responses = [
            _mock_get_response(existing, etag=f'"v{i}"')
            for i in range(MAX_RETRIES + 2)
        ]
        client = MagicMock()
        client.get.side_effect = get_responses
        client.put.return_value = put_412

        with pytest.raises(DataAccessRoleReconciliationError, match="retries exhausted"):
            reconcile_item_roles(
                client=client,
                workspace_id=WORKSPACE_ID,
                item_id=ITEM_ID,
                object_id=OBJECT_ID,
                tenant_id=TENANT_ID,
                dry_run=False,
            )

    def test_retries_on_429_too_many_requests(self) -> None:
        existing = [copy.deepcopy(UNRELATED_ROLE)]
        get_resp = _mock_get_response(existing, etag='"v1"')
        put_429 = MagicMock()
        put_429.status_code = 429
        put_429.headers = {"Retry-After": "1"}
        put_429.raise_for_status.side_effect = Exception("429")

        put_ok = _mock_put_response(etag='"v2"')
        verify_resp = _mock_get_response(
            [copy.deepcopy(UNRELATED_ROLE), _expected_evidence_role()],
            etag='"v2"',
        )

        client = MagicMock()
        client.get.side_effect = [get_resp, get_resp, verify_resp]
        client.put.side_effect = [put_429, put_ok, put_ok]

        result = reconcile_item_roles(
            client=client,
            workspace_id=WORKSPACE_ID,
            item_id=ITEM_ID,
            object_id=OBJECT_ID,
            tenant_id=TENANT_ID,
            dry_run=False,
        )
        assert result["retries"] >= 1

    def test_does_not_retry_on_403(self) -> None:
        """Non-transient errors must fail closed immediately."""
        existing = [copy.deepcopy(UNRELATED_ROLE)]
        get_resp = _mock_get_response(existing, etag='"v1"')
        put_403 = MagicMock()
        put_403.status_code = 403
        put_403.raise_for_status.side_effect = Exception("403 Forbidden")

        client = MagicMock()
        client.get.return_value = get_resp
        client.put.return_value = put_403

        with pytest.raises(DataAccessRoleReconciliationError, match="non-retryable"):
            reconcile_item_roles(
                client=client,
                workspace_id=WORKSPACE_ID,
                item_id=ITEM_ID,
                object_id=OBJECT_ID,
                tenant_id=TENANT_ID,
                dry_run=False,
            )


class TestReconcileItemRolesPostWriteVerification:
    def test_verification_get_confirms_desired_state(self) -> None:
        existing = [copy.deepcopy(UNRELATED_ROLE)]
        get_resp = _mock_get_response(existing, etag='"v1"')
        put_resp = _mock_put_response(etag='"v2"')
        verify_resp = _mock_get_response(
            [copy.deepcopy(UNRELATED_ROLE), _expected_evidence_role()],
            etag='"v2"',
        )

        client = MagicMock()
        client.get.side_effect = [get_resp, verify_resp]
        client.put.return_value = put_resp

        result = reconcile_item_roles(
            client=client,
            workspace_id=WORKSPACE_ID,
            item_id=ITEM_ID,
            object_id=OBJECT_ID,
            tenant_id=TENANT_ID,
            dry_run=False,
        )

        assert result["verified"] is True
        assert client.get.call_count == 2
        assert client.put.call_count == 2
        dry_run_call, apply_call = client.put.call_args_list
        assert dry_run_call.kwargs["params"] == {"dryRun": "true"}
        assert "params" not in apply_call.kwargs

    def test_verification_rejects_unrelated_role_removal(self) -> None:
        existing = [copy.deepcopy(UNRELATED_ROLE)]
        get_resp = _mock_get_response(existing, etag='"v1"')
        put_resp = _mock_put_response(etag='"v2"')
        verify_resp = _mock_get_response(
            [_expected_evidence_role()],
            etag='"v2"',
        )

        client = MagicMock()
        client.get.side_effect = [get_resp, verify_resp]
        client.put.return_value = put_resp

        with pytest.raises(VerificationDriftError, match="unrelated"):
            reconcile_item_roles(
                client=client,
                workspace_id=WORKSPACE_ID,
                item_id=ITEM_ID,
                object_id=OBJECT_ID,
                tenant_id=TENANT_ID,
                dry_run=False,
            )

    def test_verification_failure_raises(self) -> None:
        existing = [copy.deepcopy(UNRELATED_ROLE)]
        get_resp = _mock_get_response(existing, etag='"v1"')
        put_resp = _mock_put_response(etag='"v2"')
        # Verify GET returns without the evidence role — drift
        verify_resp = _mock_get_response(
            [copy.deepcopy(UNRELATED_ROLE)],
            etag='"v2"',
        )

        client = MagicMock()
        client.get.side_effect = [get_resp, verify_resp]
        client.put.return_value = put_resp

        with pytest.raises(VerificationDriftError):
            reconcile_item_roles(
                client=client,
                workspace_id=WORKSPACE_ID,
                item_id=ITEM_ID,
                object_id=OBJECT_ID,
                tenant_id=TENANT_ID,
                dry_run=False,
            )


class TestReconcileItemRolesIdempotency:
    def test_already_converged_skips_put(self) -> None:
        """When existing roles already include the exact desired role, no PUT."""
        existing = [copy.deepcopy(UNRELATED_ROLE), _expected_evidence_role()]
        get_resp = _mock_get_response(existing, etag='"v1"')

        client = MagicMock()
        client.get.return_value = get_resp

        result = reconcile_item_roles(
            client=client,
            workspace_id=WORKSPACE_ID,
            item_id=ITEM_ID,
            object_id=OBJECT_ID,
            tenant_id=TENANT_ID,
            dry_run=False,
        )

        client.put.assert_not_called()
        assert result["already_converged"] is True
        assert result["verified"] is True


def test_batch_uses_in_memory_bearer_token() -> None:
    items, _, _, _ = parse_contract(_contract())
    fake_client = MagicMock()
    context = MagicMock()
    context.__enter__.return_value = fake_client

    with (
        patch("httpx.Client", return_value=context) as client_factory,
        patch(
            "scripts.reconcile_onelake_data_access_roles.reconcile_item_roles",
            return_value={"verified": True},
        ),
        patch(
            "scripts.reconcile_onelake_data_access_roles.reconcile_workspace_viewer",
            return_value={"verified": True},
        ),
    ):
        results = reconcile_all_evidence_items(
            items=items,
            object_id=OBJECT_ID,
            tenant_id=TENANT_ID,
            token_provider=lambda: "in-memory-token",
            dry_run=False,
        )

    assert len(results) == 5
    assert client_factory.call_args.kwargs["headers"] == {
        "Authorization": "Bearer in-memory-token"
    }

    with pytest.raises(
        DataAccessRoleReconciliationError,
        match="five isolated",
    ):
        reconcile_all_evidence_items(
            items=items[:-1],
            object_id=OBJECT_ID,
            tenant_id=TENANT_ID,
            token_provider=lambda: "in-memory-token",
        )
