from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from api.rbac import ROLE_ADMIN, ROLE_APPROVER, ROLE_OPERATOR, ROLE_READER

# RBAC-capacity-compatible role identifier reserved for policies that
# *explicitly* opt into treating a role as satisfied by the bare RBAC
# ``approve`` action capacity (Phase 03.5 CR-01/CR-05 fix history --
# ``03.5-CONTEXT.md``: "Requirements carry stable policy/role identifiers,
# not presentation text alone"). ``ROLE_APPROVER`` ("approver") is the RBAC
# capacity every principal who successfully records a decision through
# ``record_remediation_decision`` is guaranteed to hold -- directly, or via
# the higher-privileged ``admin`` role.
#
# CR-05 correction: this id is no longer the *implicit default* for every
# unmapped organizational role -- the original CR-01 fix defaulted every
# role without an explicit ``role_ids`` entry to this one shared id, which
# silently collapsed every distinct organizational role (Change Manager,
# Business Service Owner, Change Advisory Board, ...) onto the same
# identity, so a single ``approve``-capable principal's one decision
# satisfied every requirement row on a plan. An unmapped role now gets a
# *distinct*, deterministic identity derived from its own policy_id/role
# text (see ``_normalized_role_identity`` below) instead. Only policies
# that *explicitly* declare ``role_ids: {"<role>": DEFAULT_ROLE_ID}`` (the
# two shipped single-role live patch/Defender-configuration policies in
# ``semantic/live_operations.py`` do this deliberately, for backward
# compatibility with deployments that have not configured a distinct
# per-role identity) are satisfied by the bare RBAC capacity.
DEFAULT_ROLE_ID = ROLE_APPROVER

# Reserved RBAC-capacity literal role identifiers (Phase 03.5 CR-06 fix). A
# role_id equal to one of these bare strings can only ever arise from an
# *explicit*, policy-authored ``role_ids`` mapping -- ``_normalized_role_identity``'s
# implicitly-derived ids always carry a ``:<digest>`` suffix (see below) and
# therefore can never coincidentally equal one of these bare literals.
# Reserved regardless of which of these currently grant an authorization
# bypass in ``approval_gate._RBAC_COMPATIBLE_ROLE_IDS`` (today only
# ``approver``/``admin`` do) -- ``operator``/``reader`` are reserved here too
# so a future RBAC-compatibility extension can never be silently pre-empted
# by an accidental catalog collision.
_RESERVED_ROLE_ID_SENTINELS = frozenset(
    {ROLE_READER, ROLE_OPERATOR, ROLE_APPROVER, ROLE_ADMIN}
)

# Phase 03.5 WR-06 fix: explicit, validated maximum lengths for the
# catalog identity-bearing fields (``policy_id``/``role``/``stage``) and
# the stored ``role_id`` itself. Before this fix, ``_row()`` silently
# truncated ``role``/``role_id``/``stage`` to 256/256/128 characters
# *after* ``requirements()`` had already used the untruncated values to
# decide row uniqueness and *after* an implicitly-derived ``role_id`` had
# already had its CR-06 digest suffix computed -- so a sufficiently long
# catalog-authored value could either (1) silently merge two genuinely
# distinct required-approval rows into one (the post-truncation
# ``unique()`` dict key collapsing two originally-distinct ``role``/
# ``stage`` strings), reopening the exact collision class CR-06 closed,
# or (2) truncate an implicitly-derived ``role_id``'s digest suffix away,
# corrupting the very collision resistance CR-06 relies on. These bounds
# are now validated -- with a clear, field-specific ``ValueError`` -- at
# policy construction time (``policy_id``, ``roles``, explicit
# ``role_ids``, all fully known once a policy dict is supplied) or at
# ``requirements()`` call time (``stage``, only known once
# ``action.deployment_stages`` is supplied), never silently truncated.
MAX_POLICY_ID_LENGTH = 200
MAX_ROLE_LENGTH = 200
MAX_STAGE_LENGTH = 128
# Stored schema limit for the (possibly digest-suffixed) ``role_id``
# field -- unchanged from the pre-existing ``_row()`` storage bound. An
# *explicit*, policy-authored ``role_ids`` value must fit within this
# bound outright (validated at construction, never truncated); an
# *implicitly derived* id (``_normalized_role_identity``) instead caps
# only its own human-readable slug prefix, so its digest suffix -- the
# part that actually carries collision resistance -- can never be
# truncated away.
MAX_ROLE_ID_LENGTH = 256


def _normalized_role_identity(*parts: str) -> str:
    """Deterministic, collision-resistant identity string for a role.

    Phase 03.5 CR-06 fix: the original implementation returned *only* a
    lossy, human-readable slug (lowercased, punctuation/whitespace
    collapsed to single hyphens, joined with ``:``). That slug is a
    many-to-one mapping -- e.g. raw ``policy_id`` values ``"P-1"`` and
    ``"P_1"`` (ordinary, distinct, human-authored strings) both slugify to
    ``"p-1"``, so two genuinely distinct policies requiring the same role
    text collapsed onto one identical ``role_id``, letting a single
    decision satisfy both (the exact defect class CR-05 was built to
    close, reproduced through CR-05's own new mechanism). A coincidental
    slug could also collapse onto a bare reserved RBAC sentinel (e.g.
    ``"approver"``), silently bypassing the org-claim/admin-override
    requirement with no record that anything unusual occurred.

    The identity returned now is ``"<readable-prefix>:<digest>"``, where:

    - ``<readable-prefix>`` is the same lossy slug as before (kept for
      human debuggability in logs/audit trails -- never used alone as the
      actual identity), falling back to the literal ``"role"`` when every
      part slugifies to empty.
    - ``<digest>`` is a 16-hex-char SHA-256 digest over the *exact, raw*
      (non-normalized) ``parts`` tuple, JSON-encoded (preserving each
      part's exact boundaries, so ``("ab", "c")`` and ``("a", "bc")`` can
      never collide by concatenation) -- mirroring the same
      canonical-digest approach ``action_version.py``'s
      ``_stable_evidence_digest`` already uses elsewhere in this phase for
      exactly this reason.

    Two distinct raw ``parts`` tuples can now never produce the same
    ``role_id`` except by cryptographic (SHA-256) coincidence, regardless
    of how similarly they slugify. The returned id can also never
    coincidentally equal a bare reserved RBAC sentinel (``"approver"``/
    ``"admin"``/``"operator"``/``"reader"`` -- see
    :data:`_RESERVED_ROLE_ID_SENTINELS`), since it always carries the
    ``:<digest>`` suffix and none of those reserved literals contain a
    colon. A reserved sentinel can therefore only ever be produced via an
    *explicit*, policy-authored ``role_ids`` opt-in -- never by this
    implicit derivation.

    Phase 03.5 WR-06 fix: the returned id is now also guaranteed to never
    exceed :data:`MAX_ROLE_ID_LENGTH` (the stored schema limit) --
    *without* ever truncating the ``:<digest>`` suffix. Only the
    human-readable slug ``<prefix>`` (kept purely for debuggability) is
    capped; the digest -- the part that actually carries collision
    resistance -- is always appended in full. This closes the second
    manifestation of WR-06: a sufficiently long ``policy_id``/``role``
    could previously push the *composed* ``"<prefix>:<digest>"`` string
    past ``_row()``'s downstream ``[:256]`` slice, silently truncating
    the digest itself away and reopening CR-06's own collision class.
    """
    slugged = []
    for part in parts:
        text = re.sub(r"[^a-z0-9]+", "-", str(part or "").strip().casefold()).strip("-")
        if text:
            slugged.append(text)
    prefix = ":".join(slugged) or "role"
    canonical = json.dumps([str(part or "") for part in parts], separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode()).hexdigest()[:16]
    suffix = f":{digest}"
    max_prefix_length = max(MAX_ROLE_ID_LENGTH - len(suffix), 0)
    if len(prefix) > max_prefix_length:
        prefix = prefix[:max_prefix_length]
    return f"{prefix}{suffix}"


class ApprovalEngine:
    """Evaluates configurable approval policy and stage-gate requirements."""

    def __init__(self, policies: list[dict[str, Any]], *, max_policies: int = 100) -> None:
        if len(policies) > max_policies:
            raise ValueError("Approval policies exceed configured bound")
        identities: set[str] = set()
        self.policies = []
        # Phase 03.5 CR-06 fix: validated here, at construction time,
        # independent of any per-request resource/action/risk -- each
        # policy's own declared roles/role_ids/policy_id are already fully
        # known now (only ``action.deployment_stages``-derived stage-gate
        # rows require a later, per-``requirements()``-call check; see
        # there). Maps each resolved role_id (casefolded) to the one
        # (policy_id, role) pair that first produced it, so a *second*,
        # distinct role resolving to the same id is caught here -- fail
        # loud, at catalog-load time -- rather than silently letting one
        # decision satisfy two distinct requirement rows later. A resolved
        # id that is one of the reserved RBAC-capacity sentinels
        # (:data:`_RESERVED_ROLE_ID_SENTINELS`) is exempt: it can only be
        # reached via an *explicit* ``role_ids`` opt-in (never the
        # implicit digest-suffixed derivation), and more than one distinct
        # role deliberately opting into the same shared RBAC capacity is
        # the intended, explicitly-marked compatibility behavior, not a
        # collision.
        role_id_owners: dict[str, tuple[str, str]] = {}
        for source in policies:
            policy = dict(source)
            policy_id = str(policy.get("policy_id") or "").strip()
            if not policy_id or policy_id in identities:
                raise ValueError("Approval policies require unique policy_id")
            # Phase 03.5 WR-06 fix: validated -- and rejected with a clear,
            # field-specific message -- before this policy_id is ever used
            # to derive a role_id or a requirement row's identity, so an
            # overlong catalog-authored value can no longer silently reach
            # ``_row()``'s storage boundary and be truncated away there.
            if len(policy_id) > MAX_POLICY_ID_LENGTH:
                raise ValueError(
                    "Approval policy policy_id exceeds maximum length of "
                    f"{MAX_POLICY_ID_LENGTH} characters (got {len(policy_id)})"
                )
            self._validate_policy(policy)
            identities.add(policy_id)
            self.policies.append(policy)
            role_ids = policy.get("role_ids") or {}
            for role in policy.get("roles") or []:
                role_text = str(role)
                explicit = str(role_ids.get(role) or "").strip()
                role_id = explicit or _normalized_role_identity(policy_id, role_text)
                role_id_key = role_id.strip().casefold()
                if role_id_key in _RESERVED_ROLE_ID_SENTINELS:
                    continue
                owner = (policy_id, role_text)
                existing = role_id_owners.get(role_id_key)
                if existing is not None and existing != owner:
                    raise ValueError(
                        "Approval policies declare colliding role_id "
                        f"{role_id!r} for distinct roles {existing!r} and "
                        f"{owner!r}; give each role a distinct role_ids "
                        "entry, or explicitly opt into a reserved "
                        f"RBAC-compatible id ({sorted(_RESERVED_ROLE_ID_SENTINELS)!r}) "
                        "if one decision satisfying both is intentional"
                    )
                role_id_owners[role_id_key] = owner
        self._policy_version: str | None = None

    @property
    def policy_version(self) -> str:
        """Stable hash over this engine's (already validated) policy list.

        Identical policy lists produce the identical version regardless of
        input order; adding, removing, or editing a policy changes it.
        Cached on first access since ``self.policies`` never mutates after
        ``__init__`` (Phase 03.5, D-01).
        """
        if self._policy_version is None:
            canonical_policies = sorted(
                json.dumps(policy, sort_keys=True, separators=(",", ":"))
                for policy in self.policies
            )
            serialized = json.dumps(
                canonical_policies, separators=(",", ":")
            )
            self._policy_version = hashlib.sha256(serialized.encode()).hexdigest()[:16]
        return self._policy_version


    @staticmethod
    def _validate_policy(policy: dict[str, Any]) -> None:
        conditions = policy.get("conditions")
        roles = policy.get("roles")
        role_ids = policy.get("role_ids")
        if role_ids is not None and (
            not isinstance(role_ids, dict)
            or any(
                not isinstance(key, str)
                or not isinstance(value, str)
                or not str(value).strip()
                for key, value in role_ids.items()
            )
        ):
            raise ValueError(
                "Approval policy role_ids must be a mapping of role to non-empty stable id strings"
            )
        if role_ids is not None and any(
            len(str(value).strip()) > MAX_ROLE_ID_LENGTH for value in role_ids.values()
        ):
            # Phase 03.5 WR-06 fix: an *explicit*, policy-authored role_id
            # is never truncated -- it must fit within the stored schema
            # limit outright, or construction fails loud here, rather than
            # silently losing its distinguishing suffix inside ``_row()``.
            raise ValueError(
                "Approval policy role_ids value exceeds maximum length of "
                f"{MAX_ROLE_ID_LENGTH} characters"
            )
        if not isinstance(conditions, dict):
            raise TypeError("Approval policy conditions must be a mapping")
        unknown = set(conditions) - {
            "environment_in",
            "criticality_in",
            "minimum_execution_risk",
        }
        if unknown:
            raise ValueError("Approval policy contains unsupported conditions")
        for field in ("environment_in", "criticality_in"):
            if field in conditions and (
                not isinstance(conditions[field], list)
                or not conditions[field]
                or any(not str(value).strip() for value in conditions[field])
            ):
                raise ValueError(f"Approval policy {field} must be a non-empty list")
        minimum = conditions.get("minimum_execution_risk")
        if minimum is not None and (
            isinstance(minimum, bool)
            or not isinstance(minimum, int)
            or not 0 <= minimum <= 100
        ):
            raise ValueError(
                "Approval policy minimum_execution_risk must be an integer from 0 to 100"
            )
        if (
            not isinstance(roles, list)
            or not roles
            or any(not str(role).strip() for role in roles)
        ):
            raise ValueError("Approval policy roles must be a non-empty list")
        if any(len(str(role).strip()) > MAX_ROLE_LENGTH for role in roles):
            # Phase 03.5 WR-06 fix: rejected here, at construction time,
            # rather than silently truncated later inside ``_row()`` --
            # where two distinct overlong role strings sharing the first
            # MAX_ROLE_LENGTH characters could otherwise collapse onto the
            # identical stored ``role`` value and merge two genuinely
            # distinct required-approval rows into one with no error.
            raise ValueError(
                f"Approval policy role text exceeds maximum length of {MAX_ROLE_LENGTH} "
                "characters"
            )

    def requirements(
        self,
        resource: dict[str, Any],
        action: dict[str, Any],
        risk: dict[str, Any],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        # Phase 03.5 WR-06 fix: deployment stage names are only known here,
        # at call time (derived from ``action.deployment_stages``), never
        # at policy construction time -- so this is the only place their
        # length can be validated. Rejected here, up front, with a clear
        # message, rather than silently truncated later inside ``_row()``,
        # where two distinct overlong stage strings sharing the first
        # MAX_STAGE_LENGTH characters could otherwise collapse onto the
        # identical stored ``stage`` value and merge two genuinely
        # distinct required-approval rows into one with no error.
        stages = [str(stage) for stage in (action.get("deployment_stages") or [])]
        for stage in stages:
            if len(stage) > MAX_STAGE_LENGTH:
                raise ValueError(
                    "Deployment stage name exceeds maximum length of "
                    f"{MAX_STAGE_LENGTH} characters"
                )
        for stage in stages:
            # CR-05 fix: each deployment stage is its own distinct gate --
            # a CAB member's sign-off on "Development" must not be treated
            # as satisfying "Production" too. Stage-gate rows have no
            # policy of their own to declare an explicit ``role_ids``
            # mapping on, so their id is always the deterministic
            # per-stage identity, never the shared compatibility default.
            rows.append(
                self._row(
                    "stage-gate",
                    "Stage Gate Approver",
                    stage,
                    role_id=_normalized_role_identity("stage-gate", stage),
                )
            )
        for policy in self.policies:
            if not self._matches(policy.get("conditions") or {}, resource, risk):
                continue
            role_ids = policy.get("role_ids") or {}
            for role in policy.get("roles") or []:
                # CR-05 fix: a role with no explicit ``role_ids`` entry no
                # longer falls back to the single shared ``DEFAULT_ROLE_ID``
                # -- that silently collapsed every distinct organizational
                # role onto the same identity, letting one decision
                # satisfy every requirement row on a plan. It now gets a
                # distinct id deterministically derived from its own
                # policy_id/role text, so two different organizational
                # roles under the same or different policies never
                # collide. A policy that explicitly opts a role into the
                # shared ``DEFAULT_ROLE_ID`` (e.g. the shipped single-role
                # live patch/Defender-configuration policies, for RBAC
                # compatibility) is honored exactly as declared.
                role_id = (
                    str(role_ids[role]).strip()
                    if role in role_ids and str(role_ids[role]).strip()
                    else _normalized_role_identity(str(policy["policy_id"]), str(role))
                )
                rows.append(
                    self._row(
                        str(policy["policy_id"]),
                        str(role),
                        stages[-1] if stages else "Planning",
                        role_id=role_id,
                    )
                )
        unique = {
            (row["policy_id"], row["role"], row["stage"]): row for row in rows
        }
        final_rows = [unique[key] for key in sorted(unique)]
        # Phase 03.5 CR-06 fix: a second, per-call validation pass over the
        # *final* generated row set. The constructor already validates every
        # policy-declared role's own identity for uniqueness, but stage-gate
        # rows are derived from ``action.deployment_stages`` -- only known
        # here, at call time, never at construction time -- so this is the
        # only place a stage-gate id collision (or, defensively, any
        # remaining collision the constructor could not see) can be caught.
        # Exempts reserved RBAC-capacity sentinels for the identical reason
        # ``__init__`` does: those ids only ever arise from an explicit,
        # deliberate ``role_ids`` opt-in, and sharing one across distinct
        # rows is the intended compatibility behavior, not a collision.
        role_id_owners: dict[str, tuple[str, str, str]] = {}
        for row in final_rows:
            role_id_key = str(row["role_id"]).strip().casefold()
            if role_id_key in _RESERVED_ROLE_ID_SENTINELS:
                continue
            owner = (row["policy_id"], row["role"], row["stage"])
            existing = role_id_owners.get(role_id_key)
            if existing is not None and existing != owner:
                raise ValueError(
                    "Generated approval requirements declare colliding "
                    f"role_id {row['role_id']!r} for distinct rows "
                    f"{existing!r} and {owner!r}"
                )
            role_id_owners[role_id_key] = owner
        return final_rows

    @staticmethod
    def _matches(conditions, resource, risk) -> bool:
        environment = str(resource.get("environment") or "")
        criticality = str(resource.get("business_criticality") or "")
        if conditions.get("environment_in") and environment not in conditions["environment_in"]:
            return False
        if conditions.get("criticality_in") and criticality not in conditions["criticality_in"]:
            return False
        minimum = conditions.get("minimum_execution_risk")
        return not (
            minimum is not None
            and risk["execution_risk"]["score"] < int(minimum)
        )

    @staticmethod
    def _row(
        policy_id: str, role: str, stage: str, *, role_id: str = DEFAULT_ROLE_ID
    ) -> dict[str, Any]:
        resolved_role_id = str(role_id or DEFAULT_ROLE_ID).strip() or DEFAULT_ROLE_ID
        # Phase 03.5 WR-06 fix: no longer a blind ``[:256]`` slice here. By
        # the time a role_id reaches this point it has already been
        # validated to fit within MAX_ROLE_ID_LENGTH -- an *explicit*,
        # policy-authored id, bounded by ``_validate_policy`` at
        # construction time -- or *implicitly derived*, with
        # ``_normalized_role_identity`` itself capping only its
        # human-readable prefix so the collision-resistant digest suffix
        # is never truncated away. A role_id that somehow still exceeds
        # the stored schema limit here indicates an internal
        # identity-derivation defect, not ordinary overlength catalog
        # input to silently truncate away (which is exactly how CR-06's
        # digest suffix was being lost before this fix) -- fail loud
        # instead of corrupting it.
        if len(resolved_role_id) > MAX_ROLE_ID_LENGTH:
            raise ValueError(
                "Resolved role_id exceeds maximum stored length of "
                f"{MAX_ROLE_ID_LENGTH} characters; this indicates an "
                "internal role_id derivation defect, not catalog input"
            )
        return {
            "policy_id": policy_id,
            # Display-only presentation text. ``requirements()``'s own
            # ``_validate_policy``/stage-length checks already reject any
            # ``role``/``stage`` input long enough to reach this bound
            # (Phase 03.5 WR-06 fix), so this slice is now a defensive,
            # display-only cap -- it can no longer silently collapse two
            # distinct catalog-declared values onto the same truncated
            # value the way the pre-existing unconditional ``[:256]``/
            # ``[:128]`` slices could.
            "role": role[:MAX_ROLE_LENGTH],
            # Stable, RBAC-capacity-compatible identifier -- separate from
            # ``role``'s presentation text -- that satisfaction matching
            # actually keys on (approval_gate.py::requirement_satisfaction;
            # Phase 03.5 CR-01 fix).
            "role_id": resolved_role_id,
            "stage": stage[:MAX_STAGE_LENGTH],
            "status": "Required - Not Approved",
            "approval_evidence_required": [
                "Plan evidence reviewed",
                "Risk assessment accepted",
                "Rollback readiness verified",
                "Simulation result reviewed",
            ],
            "approval_recorded": False,
        }
