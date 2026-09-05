"""Shared evidence-sensitive action-version helper.

One place computes ``action_version`` for every remediation action family
(Fabric/catalog, live patch, live Defender configuration) so approval
freshness can never diverge between planners (Phase 03.5, D-04 / REVIEW
recommendation 4: "Extract one action_version_for(...) helper... used by
both planners").

The digest is a pure function of caller-supplied content: action identity,
target identity, an action-family-specific ``scope`` payload, and evidence
citation content (``source_type``/``source_id``/``observed_at`` -- the
citation's own observation time, never ``datetime.now()``/``time.time()``).
Wall-clock time is never read anywhere in this module -- this is the hard
invariant that makes a stored ``action_version`` recomputable identically
from durable evidence alone, for audit, at any later time (D-04).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def _stable_evidence_digest(citations: list[dict[str, Any]]) -> str:
    """Compute a stable digest of evidence citation content.

    Returns a hex string that changes when citation content (``source_id``
    or ``observed_at``) changes but is stable across repeated calls with
    unchanged citations. An empty citation list produces a distinct,
    stable sentinel digest -- not equivalent to any nonempty-citation
    input -- so "no evidence" is itself a detectable, versioned state.

    A citation lacking ``source_id`` still contributes to the digest under
    a fallback identity derived from its own full content (WR-05 fix): the
    previous implementation silently dropped such citations entirely,
    which could collapse "one citation with unknown identity but a real
    observed_at" into the exact same digest as "zero evidence" whenever
    every citation in a call happened to lack ``source_id``. The fallback
    is content-derived, not positional, so the digest remains
    order-insensitive (a precondition the rest of this module documents).
    """
    if not citations:
        return hashlib.sha256(b"__no_evidence__").hexdigest()[:16]

    def _identity(citation: dict[str, Any]) -> str:
        source_id = citation.get("source_id")
        if source_id:
            return str(source_id)
        return "__no_source_id__:" + hashlib.sha256(
            json.dumps(citation, sort_keys=True, separators=(",", ":"), default=str).encode()
        ).hexdigest()[:16]

    sorted_citations = sorted(
        f"{c.get('source_type', '')}:{_identity(c)}:{c.get('observed_at', '')}"
        for c in citations
    )
    digest_input = "|".join(sorted_citations)
    return hashlib.sha256(digest_input.encode()).hexdigest()[:16]


def action_version_for(
    *,
    action_id: str,
    target_id: str,
    scope: Any,
    evidence_citations: list[dict[str, Any]],
) -> str:
    """Return a 16-hex-char, evidence-sensitive, wall-clock-blind version.

    ``scope`` is action-family-specific (e.g. a sorted list of missing KB
    ids for a patch action, a Defender recommendation string, or a dict of
    execution/rollback steps for a Fabric/catalog action) and is serialized
    deterministically via sorted-key JSON so it accepts a list, dict, or
    scalar without raising. Identical inputs (including citation order)
    always produce the byte-identical output, on any invocation, in any
    process -- there is no in-memory caching and no randomness.
    """
    scope_serialized = json.dumps(
        scope, sort_keys=True, separators=(",", ":"), default=str
    )
    canonical = {
        "action_id": action_id,
        "target_id": target_id,
        "scope": scope_serialized,
        "evidence_digest": _stable_evidence_digest(evidence_citations),
    }
    serialized = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode()).hexdigest()[:16]
