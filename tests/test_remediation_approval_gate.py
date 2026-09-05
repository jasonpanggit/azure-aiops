from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from intelligence.remediation.approval_engine import (
    DEFAULT_ROLE_ID,
    MAX_POLICY_ID_LENGTH,
    MAX_ROLE_ID_LENGTH,
    MAX_ROLE_LENGTH,
    MAX_STAGE_LENGTH,
    ApprovalEngine,
    _normalized_role_identity,
)
from intelligence.remediation.approval_gate import (
    _staleness_reasons,
    authorize_role_attestation,
    is_self_approval,
    latest_decision_status,
    requirement_satisfaction,
)

NOW = datetime(2026, 6, 1, tzinfo=UTC)


def _requirement(
    role: str, policy_id: str = "change-control", stage: str = "Planning", *, role_id: str | None = None
) -> dict:
    row = {
        "policy_id": policy_id,
        "role": role,
        "stage": stage,
        "approval_evidence_required": ["Plan evidence reviewed"],
    }
    if role_id is not None:
        row["role_id"] = role_id
    return row


def _decision(
    *,
    role: str,
    decision: str = "approved",
    action_version: str = "av-1",
    approval_policy_version: str = "pv-1",
    snapshot_hash: str | None = None,
    expires_at: str = "",
    decided_at: str = "2026-01-01T00:00:00+00:00",
    approval_role_id: str | None = None,
    approver_roles: list[str] | None = None,
) -> dict:
    row = {
        "decision": decision,
        "approver_roles": (
            [str(r).casefold() for r in approver_roles]
            if approver_roles is not None
            else [role.casefold()]
        ),
        "action_version": action_version,
        "approval_policy_version": approval_policy_version,
        "expires_at": expires_at,
        "decided_at": decided_at,
    }
    if approval_role_id is not None:
        row["approval_role_id"] = approval_role_id.casefold()
    if snapshot_hash is not None:
        row["execution_snapshot"] = {"snapshot_hash": snapshot_hash}
    return row


# --------------------------------------------------------------------------
# requirement_satisfaction
# --------------------------------------------------------------------------


def test_two_role_requirement_with_one_matching_role_decision() -> None:
    requirements = [_requirement("Change Manager"), _requirement("Security Response Owner")]
    decisions = [_decision(role="security response owner")]

    rows = requirement_satisfaction(
        requirements,
        decisions,
        current_action_version="av-1",
        current_snapshot_hash="",
        policy_version="pv-1",
        now=NOW,
    )

    assert len(rows) == 2
    change_manager_row = next(r for r in rows if r["role"] == "Change Manager")
    security_row = next(r for r in rows if r["role"] == "Security Response Owner")
    assert change_manager_row["satisfied"] is False
    assert change_manager_row["unmet_reason"] == "wrong_role_decision"
    assert security_row["satisfied"] is True
    assert "unmet_reason" not in security_row


def test_no_decisions_at_all_is_pending_not_wrong_role() -> None:
    requirements = [_requirement("Change Manager")]

    rows = requirement_satisfaction(
        requirements,
        [],
        current_action_version="av-1",
        current_snapshot_hash="",
        policy_version="pv-1",
        now=NOW,
    )

    assert rows[0]["satisfied"] is False
    assert rows[0]["unmet_reason"] == "pending"


def test_stale_action_version_is_independently_attributed() -> None:
    requirements = [_requirement("Change Manager")]
    decisions = [_decision(role="change manager", action_version="av-OLD")]

    rows = requirement_satisfaction(
        requirements,
        decisions,
        current_action_version="av-1",
        current_snapshot_hash="",
        policy_version="pv-1",
        now=NOW,
    )

    assert rows[0]["satisfied"] is False
    assert rows[0]["unmet_reason"] == "stale_action_version"


def test_stale_evidence_snapshot_is_independently_attributed() -> None:
    requirements = [_requirement("Change Manager")]
    decisions = [_decision(role="change manager", snapshot_hash="old-hash")]

    rows = requirement_satisfaction(
        requirements,
        decisions,
        current_action_version="av-1",
        current_snapshot_hash="new-hash",
        policy_version="pv-1",
        now=NOW,
    )

    assert rows[0]["satisfied"] is False
    assert rows[0]["unmet_reason"] == "stale_evidence_snapshot"


def test_stale_policy_version_is_independently_attributed() -> None:
    requirements = [_requirement("Change Manager")]
    decisions = [_decision(role="change manager", approval_policy_version="pv-OLD")]

    rows = requirement_satisfaction(
        requirements,
        decisions,
        current_action_version="av-1",
        current_snapshot_hash="",
        policy_version="pv-1",
        now=NOW,
    )

    assert rows[0]["satisfied"] is False
    assert rows[0]["unmet_reason"] == "stale_policy_version"


def test_expired_decision_is_independently_attributed() -> None:
    requirements = [_requirement("Change Manager")]
    decisions = [
        _decision(role="change manager", expires_at="2020-01-01T00:00:00+00:00")
    ]

    rows = requirement_satisfaction(
        requirements,
        decisions,
        current_action_version="av-1",
        current_snapshot_hash="",
        policy_version="pv-1",
        now=NOW,
    )

    assert rows[0]["satisfied"] is False
    assert rows[0]["unmet_reason"] == "expired"


def test_role_matching_is_casefolded() -> None:
    requirements = [_requirement("Change Manager")]
    decisions = [_decision(role="CHANGE MANAGER")]

    rows = requirement_satisfaction(
        requirements,
        decisions,
        current_action_version="av-1",
        current_snapshot_hash="",
        policy_version="pv-1",
        now=NOW,
    )

    assert rows[0]["satisfied"] is True


def test_empty_requirements_returns_empty_list() -> None:
    assert requirement_satisfaction(
        [],
        [_decision(role="change manager")],
        current_action_version="av-1",
        current_snapshot_hash="",
        policy_version="pv-1",
        now=NOW,
    ) == []


def test_does_not_mutate_input_requirements_or_decisions() -> None:
    requirements = [_requirement("Change Manager")]
    decisions = [_decision(role="change manager")]
    requirements_copy = [dict(r) for r in requirements]
    decisions_copy = [dict(d) for d in decisions]

    requirement_satisfaction(
        requirements,
        decisions,
        current_action_version="av-1",
        current_snapshot_hash="",
        policy_version="pv-1",
        now=NOW,
    )

    assert requirements == requirements_copy
    assert decisions == decisions_copy


# --------------------------------------------------------------------------
# latest_decision_status
# --------------------------------------------------------------------------


def test_no_decisions_returns_none_status() -> None:
    result = latest_decision_status(
        [],
        current_action_version="av-1",
        current_snapshot_hash="",
        policy_version="pv-1",
        now=NOW,
    )
    assert result == {"status": "none", "stale_reasons": [], "latest": None}


def test_most_recent_rejection_wins_over_earlier_approval() -> None:
    decisions = [
        _decision(role="change manager", decided_at="2026-01-01T00:00:00+00:00"),
        {
            "decision": "rejected",
            "approver_roles": ["change manager"],
            "action_version": "av-1",
            "approval_policy_version": "pv-1",
            "expires_at": "",
            "decided_at": "2026-02-01T00:00:00+00:00",
        },
    ]

    result = latest_decision_status(
        decisions,
        current_action_version="av-1",
        current_snapshot_hash="",
        policy_version="pv-1",
        now=NOW,
    )

    assert result["status"] == "rejected"


def test_most_recent_approved_but_expired_is_expired() -> None:
    decisions = [_decision(role="change manager", expires_at="2020-01-01T00:00:00+00:00")]

    result = latest_decision_status(
        decisions,
        current_action_version="av-1",
        current_snapshot_hash="",
        policy_version="pv-1",
        now=NOW,
    )

    assert result["status"] == "expired"


def test_most_recent_approved_failing_multiple_checks_reports_both_reasons_in_order() -> None:
    decisions = [
        _decision(
            role="change manager",
            action_version="av-OLD",
            approval_policy_version="pv-OLD",
        )
    ]

    result = latest_decision_status(
        decisions,
        current_action_version="av-1",
        current_snapshot_hash="",
        policy_version="pv-1",
        now=NOW,
    )

    assert result["status"] == "stale"
    assert result["stale_reasons"] == ["stale_action_version", "stale_policy_version"]


def test_most_recent_approved_passing_every_check_is_current() -> None:
    decisions = [_decision(role="change manager")]

    result = latest_decision_status(
        decisions,
        current_action_version="av-1",
        current_snapshot_hash="",
        policy_version="pv-1",
        now=NOW,
    )

    assert result["status"] == "current"
    assert result["stale_reasons"] == []


# --------------------------------------------------------------------------
# Shared-logic regression (Task 3)
# --------------------------------------------------------------------------


def test_requirement_satisfaction_and_latest_decision_status_share_one_staleness_predicate() -> None:
    decision = _decision(role="change manager", action_version="av-OLD")

    direct_reasons = _staleness_reasons(
        decision,
        current_action_version="av-1",
        current_snapshot_hash="",
        policy_version="pv-1",
    )

    requirements = [_requirement("Change Manager")]
    req_rows = requirement_satisfaction(
        requirements,
        [decision],
        current_action_version="av-1",
        current_snapshot_hash="",
        policy_version="pv-1",
        now=NOW,
    )
    status = latest_decision_status(
        [decision],
        current_action_version="av-1",
        current_snapshot_hash="",
        policy_version="pv-1",
        now=NOW,
    )

    assert direct_reasons == ["stale_action_version"]
    assert req_rows[0]["unmet_reason"] == direct_reasons[0]
    assert status["stale_reasons"] == direct_reasons


def test_is_self_approval_casefolds_and_strips() -> None:
    assert is_self_approval("  Alice@Example.com ", "alice@example.com") is True
    assert is_self_approval("alice@example.com", "bob@example.com") is False
    assert is_self_approval("", "") is False
    assert is_self_approval("alice@example.com", "") is False


# --------------------------------------------------------------------------
# Phase 03.5 CR-05: distinct, machine-checkable per-role attestation
#
# CR-05 found that ApprovalEngine.DEFAULT_ROLE_ID collapsed every unmapped
# organizational role onto the same shared id, so any single decision from
# any single ``approve``-capable principal satisfied every distinct-role
# requirement row on a plan. The fix (a) gives every unmapped role a
# distinct, deterministic id, and (b) makes a decision attest exactly one
# role via the new ``approval_role_id`` field -- ``approver_roles`` is kept
# only for legacy read-compatibility, mapped only when doing so is
# unambiguous for the plan's own set of distinct role ids.
# --------------------------------------------------------------------------


def test_two_roles_cannot_execute_after_one_decision() -> None:
    """A single new-format decision attesting one role never satisfies a
    second, distinct-role requirement row -- even when both rows are on
    the same plan and the decision is otherwise fully valid/current."""
    requirements = [
        _requirement("Change Manager", policy_id="p1", role_id="p1:change-manager"),
        _requirement("Security Response Owner", policy_id="p1", role_id="p1:security-owner"),
    ]
    decisions = [_decision(role="ignored", approval_role_id="p1:change-manager")]

    rows = requirement_satisfaction(
        requirements,
        decisions,
        current_action_version="av-1",
        current_snapshot_hash="",
        policy_version="pv-1",
        now=NOW,
    )

    satisfied_by_role = {row["role"]: row["satisfied"] for row in rows}
    assert satisfied_by_role == {"Change Manager": True, "Security Response Owner": False}
    unmet = next(row for row in rows if row["role"] == "Security Response Owner")
    assert unmet["unmet_reason"] == "wrong_role_decision"


def test_two_correctly_role_attested_decisions_satisfy() -> None:
    """Two decisions, each attesting its own distinct role, together
    satisfy a two-role plan -- genuine multi-stakeholder governance."""
    requirements = [
        _requirement("Change Manager", policy_id="p1", role_id="p1:change-manager"),
        _requirement("Security Response Owner", policy_id="p1", role_id="p1:security-owner"),
    ]
    decisions = [
        _decision(role="ignored", approval_role_id="p1:change-manager", decided_at="2026-01-01T00:00:00+00:00"),
        _decision(role="ignored", approval_role_id="p1:security-owner", decided_at="2026-01-01T00:00:01+00:00"),
    ]

    rows = requirement_satisfaction(
        requirements,
        decisions,
        current_action_version="av-1",
        current_snapshot_hash="",
        policy_version="pv-1",
        now=NOW,
    )

    assert all(row["satisfied"] for row in rows), rows


def test_one_generic_approver_cannot_impersonate_unmapped_org_role_in_production_policy() -> None:
    """A legacy (or new-format) decision recorded only under the bare RBAC
    ``approver`` capacity must never satisfy a real production
    Fabric/catalog policy's distinct, unmapped organizational role."""
    fixture = json.loads(
        Path("tests/fixtures/sample_remediation_planning.json").read_text()
    )["approval_policies"]
    engine = ApprovalEngine(fixture)
    action = {"deployment_stages": ["Production"]}
    resource = {"environment": "Production", "business_criticality": "Mission Critical"}
    risk = {"execution_risk": {"score": 60}}
    requirements = engine.requirements(resource, action, risk)
    assert len(requirements) > 1
    assert not any(row["role_id"] == "approver" for row in requirements), (
        "fixture policies must not already declare an 'approver'-compatible role_id"
    )

    # A bare-capacity legacy decision (no approval_role_id -- only the RBAC
    # capacity strings CR-01's route fix always records).
    legacy_bare_capacity = _decision(role="ignored", approver_roles=["approver", "admin"])
    # A new-format decision that (incorrectly) tried to attest the bare
    # capacity string itself, rather than one of this plan's real distinct
    # role ids.
    new_format_bare_capacity = _decision(role="ignored", approval_role_id="approver")

    for decisions in ([legacy_bare_capacity], [new_format_bare_capacity]):
        rows = requirement_satisfaction(
            requirements,
            decisions,
            current_action_version="av-1",
            current_snapshot_hash="",
            policy_version="pv-1",
            now=NOW,
        )
        assert not any(row["satisfied"] for row in rows), (decisions, rows)


def test_legacy_decision_fails_closed_when_ambiguous_across_distinct_roles() -> None:
    """A legacy decision (no approval_role_id) whose approver_roles
    intersects more than one of this plan's distinct role ids must satisfy
    NONE of them -- fail closed, never guess which one it meant (this is
    the exact mechanism that let CR-05's DEFAULT_ROLE_ID collapse turn one
    admin decision into "every role satisfied")."""
    requirements = [
        _requirement("Change Manager", policy_id="p1", role_id="approver"),
        _requirement("Security Response Owner", policy_id="p1", role_id="admin"),
    ]
    # This decision's approver_roles intersects BOTH distinct role ids on
    # this plan -- ambiguous.
    ambiguous = _decision(role="ignored", approver_roles=["approver", "admin"])

    rows = requirement_satisfaction(
        requirements,
        [ambiguous],
        current_action_version="av-1",
        current_snapshot_hash="",
        policy_version="pv-1",
        now=NOW,
    )

    assert not any(row["satisfied"] for row in rows), rows


def test_legacy_decision_maps_only_when_unambiguous() -> None:
    """A legacy decision whose approver_roles intersects exactly one of
    this plan's distinct role ids still correctly satisfies that one row
    -- pre-fix single-role plans (and the shipped RBAC-compatible live
    patch/Defender-configuration policies) remain satisfiable without any
    directory-backed role-claim migration."""
    requirements = [_requirement("Change approver", policy_id="live-patch-change-approval", role_id="approver")]
    unambiguous = _decision(role="ignored", approver_roles=["approver"])

    rows = requirement_satisfaction(
        requirements,
        [unambiguous],
        current_action_version="av-1",
        current_snapshot_hash="",
        policy_version="pv-1",
        now=NOW,
    )

    assert rows[0]["satisfied"] is True


def test_authorize_role_attestation_rbac_compatible_role_id_needs_no_claim() -> None:
    authorized, admin_override = authorize_role_attestation(
        role_id="approver", role_text="Change approver", org_roles=(), rbac_roles=("approver",)
    )
    assert (authorized, admin_override) == (True, False)


def test_authorize_role_attestation_literal_org_claim_is_not_an_override() -> None:
    authorized, admin_override = authorize_role_attestation(
        role_id="p1:change-manager",
        role_text="Change Manager",
        org_roles=("change manager",),
        rbac_roles=("approver",),
    )
    assert (authorized, admin_override) == (True, False)


def test_authorize_role_attestation_admin_without_claim_is_an_explicit_override() -> None:
    """Phase 03.5 CR-05 fix: an admin who holds no literal organizational
    role claim may still attest a distinct role -- but this must be
    recorded truthfully as an explicit override, never silently treated as
    if the admin held the literal claim."""
    authorized, admin_override = authorize_role_attestation(
        role_id="p1:change-manager", role_text="Change Manager", org_roles=(), rbac_roles=("admin",)
    )
    assert (authorized, admin_override) == (True, True)


def test_authorize_role_attestation_refuses_a_principal_with_neither_claim_nor_admin() -> None:
    authorized, admin_override = authorize_role_attestation(
        role_id="p1:change-manager", role_text="Change Manager", org_roles=(), rbac_roles=("approver",)
    )
    assert (authorized, admin_override) == (False, False)


# --------------------------------------------------------------------------
# CR-06: collision-resistant role identity derivation
# --------------------------------------------------------------------------


def test_policy_ids_differing_only_by_hyphen_vs_underscore_produce_distinct_role_ids() -> None:
    """The reviewer's own P-1 / P_1 repro: two distinct, ordinary
    ``policy_id`` strings differing only by hyphen vs. underscore, both
    requiring the identical role text, must never collapse onto one
    ``role_id`` -- the exact CR-05 defect class, reproduced through
    CR-05's own new mechanism."""
    engine = ApprovalEngine(
        [
            {"policy_id": "P-1", "conditions": {}, "roles": ["Change Manager"]},
            {"policy_id": "P_1", "conditions": {}, "roles": ["Change Manager"]},
        ]
    )
    requirements = engine.requirements({}, {}, {"execution_risk": {"score": 0}})
    role_ids = [row["role_id"] for row in requirements]
    assert len(role_ids) == 2
    assert len(set(role_ids)) == 2, "distinct policy_ids must never share a role_id"

    # A single decision attesting one of the two ids must satisfy only the
    # one row it names -- never both.
    decision = _decision(role="ignored", approval_role_id=role_ids[0])
    rows = requirement_satisfaction(
        requirements,
        [decision],
        current_action_version="av-1",
        current_snapshot_hash="",
        policy_version="pv-1",
        now=NOW,
    )
    assert sum(1 for row in rows if row["satisfied"]) == 1


def test_role_texts_differing_only_by_case_or_punctuation_produce_distinct_role_ids() -> None:
    """Two role strings under the same policy that differ only by case or
    punctuation (a realistic human-authored catalog data-entry variance)
    must resolve to distinct, non-colliding role_ids."""
    engine = ApprovalEngine(
        [
            {
                "policy_id": "p1",
                "conditions": {},
                "roles": ["Change Manager", "change-manager", "CHANGE_MANAGER"],
            }
        ]
    )
    requirements = engine.requirements({}, {}, {"execution_risk": {"score": 0}})
    role_ids = {row["role_id"] for row in requirements}
    assert len(role_ids) == 3


def test_deployment_stage_names_differing_only_by_punctuation_produce_distinct_role_ids() -> None:
    """CR-06 manifestation 1 also applies to stage-gate rows: ``"Stage 1"``,
    ``"Stage_1"``, and ``"Stage-1"`` all slugified identically to
    ``"stage-1"`` pre-fix -- undermining the CR-05 comment's own stated
    intent that differently-spelled stages of the same gate must not
    collapse. They must now resolve to distinct role_ids."""
    engine = ApprovalEngine([{"policy_id": "p1", "conditions": {}, "roles": ["Role"]}])
    action = {"deployment_stages": ["Stage 1", "Stage_1", "Stage-1"]}
    requirements = engine.requirements({}, action, {"execution_risk": {"score": 0}})
    stage_rows = [row for row in requirements if row["policy_id"] == "stage-gate"]
    assert len(stage_rows) == 3
    assert len({row["role_id"] for row in stage_rows}) == 3


def test_reserved_approver_sentinel_can_no_longer_arise_from_coincidental_slug_collapse() -> None:
    """CR-06 manifestation 2, reproduced verbatim: a policy_id of
    ``"Approver"`` with a role that strips to empty after slugification
    (``"- - -"``) previously produced the bare reserved id ``"approver"``
    with no explicit role_ids opt-in -- silently bypassing the org-claim/
    admin-override requirement. It must no longer be able to."""
    engine = ApprovalEngine([{"policy_id": "Approver", "conditions": {}, "roles": ["- - -"]}])
    requirements = engine.requirements({}, {}, {"execution_risk": {"score": 0}})
    row = requirements[0]
    assert row["role_id"] not in {"approver", "admin", "operator", "reader"}

    # A bare RBAC approve capacity, with no literal org claim, must not be
    # authorized to attest this role -- it was never explicitly opted in.
    authorized, admin_override = authorize_role_attestation(
        role_id=row["role_id"], role_text=row["role"], org_roles=(), rbac_roles=("approver",)
    )
    assert (authorized, admin_override) == (False, False)


def test_construction_rejects_two_distinct_roles_explicitly_sharing_a_non_reserved_role_id() -> None:
    """Explicit ``role_ids`` remain supported, but two genuinely distinct
    roles explicitly declaring the identical *non-reserved* custom id is a
    real authoring mistake -- one decision could satisfy both -- and must
    be rejected at construction (catalog-load) time, not discovered later
    at evaluation time."""
    with pytest.raises(ValueError, match="colliding role_id"):
        ApprovalEngine(
            [
                {
                    "policy_id": "p1",
                    "conditions": {},
                    "roles": ["Role A"],
                    "role_ids": {"Role A": "custom-shared-id"},
                },
                {
                    "policy_id": "p2",
                    "conditions": {},
                    "roles": ["Role B"],
                    "role_ids": {"Role B": "custom-shared-id"},
                },
            ]
        )


def test_construction_rejects_two_roles_in_the_same_policy_sharing_a_non_reserved_role_id() -> None:
    """Same authoring mistake, within a single policy's own ``roles``
    list -- must also be rejected at construction."""
    with pytest.raises(ValueError, match="colliding role_id"):
        ApprovalEngine(
            [
                {
                    "policy_id": "p1",
                    "conditions": {},
                    "roles": ["Role A", "Role B"],
                    "role_ids": {"Role A": "custom-shared-id", "Role B": "custom-shared-id"},
                },
            ]
        )


def test_construction_allows_two_distinct_roles_explicitly_opting_into_the_same_reserved_sentinel() -> None:
    """The one legitimate exception: two distinct roles (even across
    different policies) may explicitly, deliberately opt into the same
    reserved RBAC-compatible sentinel (e.g. both wanting the bare
    ``approve`` capacity to satisfy them) -- this is the intended,
    explicitly-marked compatibility behavior CR-05 shipped, not a
    collision, and must not raise."""
    engine = ApprovalEngine(
        [
            {
                "policy_id": "p1",
                "conditions": {},
                "roles": ["Role A"],
                "role_ids": {"Role A": "approver"},
            },
            {
                "policy_id": "p2",
                "conditions": {},
                "roles": ["Role B"],
                "role_ids": {"Role B": "approver"},
            },
        ]
    )
    requirements = engine.requirements({}, {}, {"execution_risk": {"score": 0}})
    assert {row["role_id"] for row in requirements} == {"approver"}


def test_normalized_role_identity_is_deterministic_and_stable_across_calls() -> None:
    """The same raw inputs must always produce the identical id, on any
    call, in any process -- no caching, no randomness, no wall-clock
    dependency (mirroring ``action_version_for``'s own stability
    guarantee)."""
    first = _normalized_role_identity("P-1", "Change Manager")
    second = _normalized_role_identity("P-1", "Change Manager")
    assert first == second

    # Constructing a fresh engine from equivalent policy data must also
    # reproduce the identical role_id every time.
    policies = [{"policy_id": "p1", "conditions": {}, "roles": ["Change Manager"]}]
    ids = {
        ApprovalEngine(policies).requirements({}, {}, {"execution_risk": {"score": 0}})[0][
            "role_id"
        ]
        for _ in range(3)
    }
    assert len(ids) == 1


def test_live_single_role_policies_remain_satisfiable_by_the_bare_rbac_capacity() -> None:
    """Unchanged live single-role compatibility: the two shipped live
    patch/Defender-configuration policies explicitly opt their one role
    into ``DEFAULT_ROLE_ID`` (the bare RBAC ``approve`` capacity) -- this
    fix must not disturb that explicit opt-in path at all."""
    from semantic.live_operations import (
        _DEFAULT_CONFIGURATION_APPROVAL_POLICIES,
        _DEFAULT_PATCH_APPROVAL_POLICIES,
    )

    patch_engine = ApprovalEngine(_DEFAULT_PATCH_APPROVAL_POLICIES)
    configuration_engine = ApprovalEngine(_DEFAULT_CONFIGURATION_APPROVAL_POLICIES)
    risk = {"execution_risk": {"score": 0}}

    patch_requirements = patch_engine.requirements({}, {}, risk)
    configuration_requirements = configuration_engine.requirements({}, {}, risk)
    assert [row["role_id"] for row in patch_requirements] == [DEFAULT_ROLE_ID]
    assert [row["role_id"] for row in configuration_requirements] == [DEFAULT_ROLE_ID]

    decision = _decision(role="ignored", approver_roles=[DEFAULT_ROLE_ID])
    for requirements in (patch_requirements, configuration_requirements):
        rows = requirement_satisfaction(
            requirements,
            [decision],
            current_action_version="av-1",
            current_snapshot_hash="",
            policy_version="pv-1",
            now=NOW,
        )
        assert rows[0]["satisfied"] is True


# --------------------------------------------------------------------------
# WR-06: validated maximum lengths for policy_id/role/stage/explicit
# role_id, and digest-suffix-preserving truncation for implicitly-derived
# role_ids. Before this fix, ``_row()``'s ``[:256]``/``[:128]`` storage
# truncation ran *after* both requirement-row uniqueness (``unique()``'s
# dict key) and role_id derivation (``_normalized_role_identity``) had
# already used the untruncated value -- so a sufficiently long
# catalog-authored ``policy_id``/``role``/``stage`` could either silently
# merge two distinct required-approval rows into one (no error) or
# truncate an implicitly-derived id's CR-06 digest suffix away, reopening
# the exact collision class CR-06 closed.
# --------------------------------------------------------------------------


def test_policy_id_at_max_length_is_accepted() -> None:
    """A ``policy_id`` exactly at the validated maximum must construct and
    generate requirements normally -- the bound must not be off-by-one in
    the rejecting direction."""
    policy_id = "P" * MAX_POLICY_ID_LENGTH
    engine = ApprovalEngine([{"policy_id": policy_id, "conditions": {}, "roles": ["Role A"]}])
    requirements = engine.requirements({}, {}, {"execution_risk": {"score": 0}})
    assert requirements[0]["policy_id"] == policy_id


def test_policy_id_over_max_length_is_rejected_with_a_clear_message() -> None:
    """A ``policy_id`` one character over the validated maximum must be
    refused at construction time with a message naming the offending
    field and its bound -- not silently truncated later inside ``_row()``."""
    policy_id = "P" * (MAX_POLICY_ID_LENGTH + 1)
    with pytest.raises(ValueError, match="policy_id exceeds maximum length"):
        ApprovalEngine([{"policy_id": policy_id, "conditions": {}, "roles": ["Role A"]}])


def test_role_text_at_max_length_is_accepted() -> None:
    """A role string exactly at the validated maximum must construct and
    generate requirements normally."""
    role = "R" * MAX_ROLE_LENGTH
    engine = ApprovalEngine([{"policy_id": "p1", "conditions": {}, "roles": [role]}])
    requirements = engine.requirements({}, {}, {"execution_risk": {"score": 0}})
    assert requirements[0]["role"] == role


def test_role_text_over_max_length_is_rejected_with_a_clear_message() -> None:
    """A role string one character over the validated maximum must be
    refused at construction time -- not silently truncated later, which
    is exactly what previously allowed two overlong-but-distinct roles to
    collapse onto the same stored ``role`` value (WR-06 manifestation 1)."""
    role = "R" * (MAX_ROLE_LENGTH + 1)
    with pytest.raises(ValueError, match="role text exceeds maximum length"):
        ApprovalEngine([{"policy_id": "p1", "conditions": {}, "roles": [role]}])


def test_deployment_stage_at_max_length_is_accepted() -> None:
    """A deployment stage name exactly at the validated maximum must
    generate a requirement row normally."""
    engine = ApprovalEngine([{"policy_id": "p1", "conditions": {}, "roles": ["Role A"]}])
    stage = "S" * MAX_STAGE_LENGTH
    requirements = engine.requirements(
        {}, {"deployment_stages": [stage]}, {"execution_risk": {"score": 0}}
    )
    stage_row = next(row for row in requirements if row["policy_id"] == "stage-gate")
    assert stage_row["stage"] == stage


def test_deployment_stage_over_max_length_is_rejected_with_a_clear_message() -> None:
    """A deployment stage name one character over the validated maximum
    must be refused, at ``requirements()`` call time (the only point its
    length is known), with a message naming the field -- not silently
    truncated later."""
    engine = ApprovalEngine([{"policy_id": "p1", "conditions": {}, "roles": ["Role A"]}])
    stage = "S" * (MAX_STAGE_LENGTH + 1)
    with pytest.raises(ValueError, match="Deployment stage name exceeds maximum length"):
        engine.requirements(
            {}, {"deployment_stages": [stage]}, {"execution_risk": {"score": 0}}
        )


def test_explicit_role_id_at_max_length_is_accepted() -> None:
    """An explicit, policy-authored ``role_ids`` value exactly at the
    stored schema limit must be honored verbatim, with no truncation."""
    role_id = "x" * MAX_ROLE_ID_LENGTH
    engine = ApprovalEngine(
        [
            {
                "policy_id": "p1",
                "conditions": {},
                "roles": ["Role A"],
                "role_ids": {"Role A": role_id},
            }
        ]
    )
    requirements = engine.requirements({}, {}, {"execution_risk": {"score": 0}})
    assert requirements[0]["role_id"] == role_id


def test_explicit_role_id_over_max_length_is_rejected_with_a_clear_message() -> None:
    """An explicit ``role_ids`` value one character over the stored
    schema limit must be refused at construction time -- never silently
    truncated, which would corrupt whatever distinguishing suffix the
    authoring deployment relied on."""
    role_id = "x" * (MAX_ROLE_ID_LENGTH + 1)
    with pytest.raises(ValueError, match="role_ids value exceeds maximum length"):
        ApprovalEngine(
            [
                {
                    "policy_id": "p1",
                    "conditions": {},
                    "roles": ["Role A"],
                    "role_ids": {"Role A": role_id},
                }
            ]
        )


def test_two_long_policy_ids_sharing_a_common_prefix_produce_distinct_role_ids() -> None:
    """Two ``policy_id`` values at the maximum validated length, identical
    for all but their final character (a long shared prefix), must still
    resolve to distinct, non-colliding role_ids -- proving the digest is
    computed over the *exact* raw policy_id text, not a truncated or
    otherwise lossy prefix, even at the boundary of the validated bound."""
    base = "A" * (MAX_POLICY_ID_LENGTH - 1)
    policy_id_one = base + "1"
    policy_id_two = base + "2"
    engine = ApprovalEngine(
        [
            {"policy_id": policy_id_one, "conditions": {}, "roles": ["Change Manager"]},
            {"policy_id": policy_id_two, "conditions": {}, "roles": ["Change Manager"]},
        ]
    )
    requirements = engine.requirements({}, {}, {"execution_risk": {"score": 0}})
    role_ids = [row["role_id"] for row in requirements]
    assert len(role_ids) == 2
    assert len(set(role_ids)) == 2, "long, common-prefix policy_ids must never share a role_id"

    # A single decision attesting one of the two ids must satisfy only the
    # one row it names -- never both (mirrors the P-1/P_1 CR-06 proof, at
    # the length boundary rather than a short human-typo variant).
    decision = _decision(role="ignored", approval_role_id=role_ids[0])
    rows = requirement_satisfaction(
        requirements,
        [decision],
        current_action_version="av-1",
        current_snapshot_hash="",
        policy_version="pv-1",
        now=NOW,
    )
    assert sum(1 for row in rows if row["satisfied"]) == 1


def test_normalized_role_identity_preserves_digest_suffix_for_very_long_inputs() -> None:
    """The readable slug prefix may be capped for very long raw inputs,
    but the 16-hex-char SHA-256 digest suffix -- the part that actually
    carries collision resistance -- must always survive intact, and the
    total returned length must never exceed MAX_ROLE_ID_LENGTH (the
    stored schema limit)."""
    long_policy_id = "P" * MAX_POLICY_ID_LENGTH
    long_role = "R" * MAX_ROLE_LENGTH
    role_id = _normalized_role_identity(long_policy_id, long_role)
    assert len(role_id) <= MAX_ROLE_ID_LENGTH

    # The digest suffix is the last 17 characters (":" + 16 hex chars) and
    # must exactly match an independent computation over the same raw,
    # untruncated inputs.
    canonical = json.dumps([long_policy_id, long_role], separators=(",", ":"))
    expected_digest = hashlib.sha256(canonical.encode()).hexdigest()[:16]
    assert role_id.endswith(f":{expected_digest}")

    # Two distinct long inputs sharing an enormous common prefix (only
    # their very last character differs) must still produce distinct
    # ids -- the digest, not the (now-capped) prefix, is what guarantees
    # this.
    other_role_id = _normalized_role_identity(
        long_policy_id, "R" * (MAX_ROLE_LENGTH - 1) + "Z"
    )
    assert other_role_id != role_id


def test_two_roles_identical_for_first_256_characters_no_longer_silently_merge() -> None:
    """Reviewer's own WR-06 manifestation-1 repro: two role strings
    identical for their first 256 characters, differing only afterward,
    previously both truncated to the identical stored ``role`` value
    inside ``_row()`` and silently collapsed into a single required-
    approval row with no error of any kind. They must now be refused
    outright at construction, with a clear message naming the actual
    cause -- never silently merged."""
    role_one = "A" * 300 + "-suffix-one"
    role_two = "A" * 300 + "-suffix-two"
    with pytest.raises(ValueError, match="role text exceeds maximum length"):
        ApprovalEngine(
            [{"policy_id": "p1", "conditions": {}, "roles": [role_one, role_two]}]
        )


def test_overlong_policy_id_rejected_at_construction_not_as_an_unhandled_downstream_error() -> None:
    """Reviewer's own WR-06 manifestation-2 repro: a ~250+ character
    policy_id previously survived construction unrejected and only
    surfaced later, inside ``requirements()``'s own call-time uniqueness
    check, as a comparatively opaque 'colliding role_id' ``ValueError``
    that gave no hint the real root cause was the policy_id's length --
    and did so only for resources whose plan generation actually reached
    that policy, with no production caller catching it. It must now fail
    immediately, at construction time -- before any plan generation is
    ever attempted -- with a message that names the actual offending
    field and its bound."""
    policy_id = "P" * 260
    with pytest.raises(ValueError, match="policy_id exceeds maximum length"):
        ApprovalEngine(
            [{"policy_id": policy_id, "conditions": {}, "roles": ["Role A", "Role B"]}]
        )
