"""Shared, pure evaluation engine for remediation approval satisfaction.

Two public functions answer the two questions every later consumer in this
phase needs answered identically (Phase 03.5, D-01):

- ``requirement_satisfaction()``: is *this* ``approval_requirements`` row
  satisfied against the decisions on file, right now?
- ``latest_decision_status()``: what is the plan's overall latest-decision
  status (none/current/stale/rejected/expired)?
- ``policy_version_for()``: this plan's originating ``ApprovalEngine``'s
  live policy_version, if reachable (03.5 WR-02 fix) -- shared by both the
  read-side routes and the execution gate so neither can independently
  drift.

Both share one internal staleness predicate (``_staleness_reasons``) so the
execution-service gate (Plan 03.5-05) and the read-side routes (Plan
03.5-06) can never compute a different stale/current answer for the same
inputs -- closing REVIEW recommendation 4's "one decision suffices" /
snapshot-hash-only staleness gaps.

Neither function performs I/O or reads the wall clock itself -- ``now`` is
always caller-supplied, keeping both functions pure and independently
testable.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from api.rbac import ROLE_ADMIN, ROLE_APPROVER

# Closed, machine-readable vocabulary (03.5-UI-SPEC.md "Approval Requirement
# Contract" / "Stale Approval State Contract").
_REASON_PENDING = "pending"
_REASON_WRONG_ROLE = "wrong_role_decision"
_REASON_STALE_ACTION_VERSION = "stale_action_version"
_REASON_STALE_EVIDENCE_SNAPSHOT = "stale_evidence_snapshot"
_REASON_STALE_POLICY_VERSION = "stale_policy_version"
_REASON_EXPIRED = "expired"

# Role ids that every principal reaching the approve route already holds
# directly via the RBAC ``approve`` action capacity itself -- a policy
# that explicitly opts a role into one of these (the shipped single-role
# live patch/Defender-configuration policies do; see
# ``approval_engine.DEFAULT_ROLE_ID``) is satisfiable without any literal
# organizational role claim (Phase 03.5 CR-05 fix).
_RBAC_COMPATIBLE_ROLE_IDS = frozenset({ROLE_APPROVER, ROLE_ADMIN})


def is_self_approval(requested_by: str, approved_by: str) -> bool:
    """True exactly when both identities, casefolded/stripped, are equal and non-empty.

    Placed here (rather than in ``operations.patching.service``) because
    ``execution_service.py`` already imports from ``operations.patching.service``
    -- putting this helper in the reverse direction would invert an existing
    dependency. Both ``execution_service.py`` (same package) and
    ``operations/patching/service.py`` (a new, forward-compatible import)
    use this single definition, so the two enforcement points can never
    define self-approval differently (Phase 03.5, D-02).
    """
    left = str(requested_by or "").strip().casefold()
    right = str(approved_by or "").strip().casefold()
    return bool(left) and bool(right) and left == right


def _is_expired(decision: dict[str, Any], *, now: datetime) -> bool:
    expires_at = str(decision.get("expires_at") or "").strip()
    if not expires_at:
        return False
    try:
        expires = datetime.fromisoformat(expires_at)
    except ValueError:
        return False
    if expires.tzinfo is None and now.tzinfo is not None:
        now = now.replace(tzinfo=None)
    elif expires.tzinfo is not None and now.tzinfo is None:
        expires = expires.replace(tzinfo=None)
    return expires < now


def _staleness_reasons(
    decision: dict[str, Any],
    *,
    current_action_version: str,
    current_snapshot_hash: str,
    policy_version: str,
) -> list[str]:
    """Which staleness dimensions (if any) apply to this one decision.

    Order is significant -- action_version, then evidence_snapshot, then
    policy_version -- matching the Requirement Contract's documented
    ordering so joined-reason copy composes predictably. Both public
    functions in this module call this one predicate so they cannot
    silently diverge about what "stale" means for the same decision.
    """
    reasons: list[str] = []
    if str(decision.get("action_version") or "") != str(current_action_version or ""):
        reasons.append(_REASON_STALE_ACTION_VERSION)
    snapshot = decision.get("execution_snapshot") or {}
    decision_snapshot_hash = snapshot.get("snapshot_hash") if isinstance(snapshot, dict) else None
    if (
        decision_snapshot_hash is not None
        and current_snapshot_hash
        and str(decision_snapshot_hash) != str(current_snapshot_hash)
    ):
        reasons.append(_REASON_STALE_EVIDENCE_SNAPSHOT)
    if str(decision.get("approval_policy_version") or "") != str(policy_version or ""):
        reasons.append(_REASON_STALE_POLICY_VERSION)
    return reasons


def _decision_matches_role(
    decision: dict[str, Any], role_id: str, *, plan_role_ids: frozenset[str]
) -> bool:
    """Whether ``decision`` attests exactly the one required ``role_id``.

    Phase 03.5 CR-05 fix: a decision recorded through the current
    (``approval_role_id``-carrying) format attests *exactly one* role --
    matching is a simple, unambiguous equality check, so one decision can
    never satisfy more than one distinct requirement row.

    A decision recorded before this fix (no ``approval_role_id`` at all --
    only the legacy, potentially-multi-valued ``approver_roles`` list)
    falls back to membership matching, but *only when doing so is
    unambiguous for this plan's own requirement set*: if the decision's
    ``approver_roles``, intersected with every distinct ``role_id`` this
    plan's requirements actually use, resolves to more than one distinct
    role, the decision fails closed for *every* row rather than silently
    satisfying several -- this is what stops a legacy admin decision whose
    ``approver_roles`` happened to collapse onto the shared
    ``DEFAULT_ROLE_ID`` (the exact pre-fix defect) from ever being treated
    as attesting more than one organizational role. A legacy decision
    whose relevant-role intersection is empty (the common case for a
    genuinely multi-role Fabric/catalog plan, whose distinct role ids a
    bare ``["approver"]`` decision was never mapped to) simply never
    matches -- also fail-closed, never fail-open.
    """
    approval_role_id = str(decision.get("approval_role_id") or "").strip().casefold()
    if approval_role_id:
        return approval_role_id == role_id
    legacy_roles = {
        str(r).strip().casefold() for r in (decision.get("approver_roles") or ())
    }
    relevant = legacy_roles & plan_role_ids
    return len(relevant) == 1 and role_id in relevant


def requirement_satisfaction(
    requirements: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    *,
    current_action_version: str,
    current_snapshot_hash: str,
    policy_version: str,
    now: datetime,
) -> list[dict[str, Any]]:
    """Decorate each ``approval_requirements`` row with satisfied/unmet_reason.

    An empty ``requirements`` list returns ``[]``. Matching is keyed on each
    row's stable ``role_id`` (Phase 03.5 CR-01 fix) -- casefolded on both
    sides -- never the presentation ``role`` text. A requirement row
    produced before this fix (a durable plan generated by an older
    ``ApprovalEngine`` snapshot with no ``role_id`` key at all) falls back
    to matching on ``role`` so previously-generated plans remain evaluable
    rather than becoming permanently unsatisfiable after an upgrade
    (migration/default behavior).

    A decision satisfies at most one row (Phase 03.5 CR-05 fix): a
    current-format decision carries exactly one ``approval_role_id``,
    checked for exact equality against each row's own ``role_id``; a
    legacy decision (no ``approval_role_id``, only the older, possibly
    multi-valued ``approver_roles``) is mapped only when doing so is
    unambiguous for this plan's own set of distinct role ids -- see
    ``_decision_matches_role``. This closes the defect where the
    ``DEFAULT_ROLE_ID`` fallback (or an admin's broad ``approver_roles``)
    let one decision satisfy every distinct-role requirement row on a
    multi-role plan.

    Among matching-role ``approved`` decisions, the most recently
    ``decided_at`` one determines the row's outcome. A satisfied row
    additionally carries ``approver``/``decision_id`` identifying exactly
    which decision satisfied it, so a caller (the execution gate's
    self-approval check, CR-02; the web UI, CR-05) can show/check
    separation-of-duties against the decision that actually counted for
    *this* row, not the plan's single overall-latest decision.
    """
    if not requirements:
        return []
    plan_role_ids = frozenset(
        str(requirement.get("role_id") or requirement.get("role") or "")
        .strip()
        .casefold()
        for requirement in requirements
    )
    approved = [d for d in decisions if d.get("decision") == "approved"]
    rows: list[dict[str, Any]] = []
    for requirement in requirements:
        role_id = str(
            requirement.get("role_id") or requirement.get("role") or ""
        ).strip().casefold()
        matching = [
            d
            for d in approved
            if _decision_matches_role(d, role_id, plan_role_ids=plan_role_ids)
        ]
        if not matching:
            other_role_exists = bool(approved)
            reason = _REASON_WRONG_ROLE if other_role_exists else _REASON_PENDING
            rows.append({**requirement, "satisfied": False, "unmet_reason": reason})
            continue
        decision = max(matching, key=lambda d: str(d.get("decided_at") or ""))
        if _is_expired(decision, now=now):
            rows.append({**requirement, "satisfied": False, "unmet_reason": _REASON_EXPIRED})
            continue
        reasons = _staleness_reasons(
            decision,
            current_action_version=current_action_version,
            current_snapshot_hash=current_snapshot_hash,
            policy_version=policy_version,
        )
        if reasons:
            rows.append({**requirement, "satisfied": False, "unmet_reason": reasons[0]})
            continue
        rows.append(
            {
                **requirement,
                "satisfied": True,
                "approver": decision.get("approver"),
                "decision_id": decision.get("decision_id"),
            }
        )
    return rows


def latest_decision_status(
    decisions: list[dict[str, Any]],
    *,
    current_action_version: str,
    current_snapshot_hash: str,
    policy_version: str,
    now: datetime,
) -> dict[str, Any]:
    """Plan-level latest-decision status, sharing ``_staleness_reasons``.

    Returns ``{"status": ..., "stale_reasons": [...], "latest": dict|None}``
    per 03.5-UI-SPEC.md's Stale Approval State Contract. A later rejection
    is always authoritative over an earlier approval.
    """
    if not decisions:
        return {"status": "none", "stale_reasons": [], "latest": None}
    latest = max(decisions, key=lambda d: str(d.get("decided_at") or ""))
    if latest.get("decision") == "rejected":
        return {"status": "rejected", "stale_reasons": [], "latest": latest}
    if latest.get("decision") != "approved":
        return {"status": "none", "stale_reasons": [], "latest": latest}
    if _is_expired(latest, now=now):
        return {"status": "expired", "stale_reasons": [], "latest": latest}
    reasons = _staleness_reasons(
        latest,
        current_action_version=current_action_version,
        current_snapshot_hash=current_snapshot_hash,
        policy_version=policy_version,
    )
    if reasons:
        return {"status": "stale", "stale_reasons": reasons, "latest": latest}
    return {"status": "current", "stale_reasons": [], "latest": latest}


def policy_version_for(planner: Any) -> str:
    """Read a plan's originating ``ApprovalEngine.policy_version``, if reachable.

    Shared by the read-side routes (``api/routers/remediation.py``) and the
    execution gate (``execution_service.py::_check_approval_gate``, Phase
    03.5 WR-02 fix) so both consult the identical live policy_version
    definition rather than each independently reimplementing (or, as the
    execution gate previously did, reusing the very decision being
    evaluated's own recorded value -- a self-referential comparison that
    could never detect an actual policy change). For planners exposing no
    single reachable engine (e.g. ``LiveRemediationPlanner``'s two per-family
    engines), this is a documented interim ``""`` default -- never an
    error -- exactly as before.
    """
    generator = getattr(planner, "generator", None)
    engine = getattr(generator, "approvals", None)
    if engine is None:
        return ""
    return str(getattr(engine, "policy_version", "") or "")


def authorize_role_attestation(
    *,
    role_id: str,
    role_text: str,
    org_roles: Iterable[str],
    rbac_roles: Iterable[str],
) -> tuple[bool, bool]:
    """Whether a principal may record a decision attesting ``role_id`` now.

    Returns ``(authorized, admin_override)`` (Phase 03.5 CR-05 fix, closing
    the gap where a bare RBAC ``approve`` capacity silently satisfied every
    organizational role a policy required, with no record of who actually
    held what). ``authorized`` is True when either:

    - ``role_id`` is one of the RBAC-capacity-compatible ids (``approver``
      /``admin``) that a policy has explicitly opted into (see
      ``approval_engine.DEFAULT_ROLE_ID``) -- every principal who reaches
      the approve route already holds the underlying capacity directly, or
    - the principal literally holds ``role_text`` (casefolded) among its
      asserted organizational role claims (``org_roles``) -- genuine,
      non-override authorization.

    When neither is true but the principal holds the RBAC ``admin``
    capacity, attestation is still permitted -- but ``admin_override`` is
    True, so the caller records the override explicitly and truthfully
    (never silently treating an admin grant as if it were the literal
    organizational role). A principal with neither a matching claim nor
    ``admin`` is not authorized at all: ``(False, False)``.
    """
    normalized_role_id = str(role_id or "").strip().casefold()
    normalized_text = str(role_text or "").strip().casefold()
    rbac = {str(role).strip().casefold() for role in rbac_roles}
    claims = {str(role).strip().casefold() for role in org_roles}
    if normalized_role_id in _RBAC_COMPATIBLE_ROLE_IDS:
        return True, False
    if normalized_text and normalized_text in claims:
        return True, False
    if ROLE_ADMIN in rbac:
        return True, True
    return False, False
