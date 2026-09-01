---
phase: 02-investigation-recommendation-and-approval
reviewed: 2026-09-01T18:12:12Z
depth: standard
files_reviewed: 9
files_reviewed_list:
  - src/api/routers/operations.py
  - src/api/models.py
  - src/intelligence/remediation/remediation_generator.py
  - src/intelligence/remediation/plan_repository.py
  - src/intelligence/remediation/business_decision.py
  - src/intelligence/remediation/approval_decisions.py
  - web/src/app/remediation/page.tsx
  - tests/test_api_remediation_approvals.py
  - tests/test_remediation_business_decision.py
findings:
  critical: 1
  warning: 3
  info: 2
  total: 6
status: issues_found
---

# Phase 02: Code Review Report

**Reviewed:** 2026-09-01T18:12:12Z  
**Depth:** standard  
**Files Reviewed:** 9  
**Status:** issues_found

## Summary

Phase 2 implementation introduces business-decision-informed remediation planning with Defender integration and approval workflows. Standard-depth review identified **1 critical security issue**, **3 warnings** around decision validation and hash determinism, and **2 informational findings** on test coverage and UI error handling.

**Key risk:** Approved/rejected/expired decision types receive inconsistent validation on the `expires_at` field, creating a potential audit trail integrity gap. The evidence digest used in action_version hash construction lacks stable serialization guarantees, risking spurious staleness detections. Test coverage gaps leave rejection and expiration decision paths underspecified.

All findings below must be addressed before Phase 3 execution.

---

## Critical Issues

### CR-01: Inconsistent expires_at Validation for Rejected/Expired Decisions

**File:** `src/api/routers/operations.py:335-354`

**Severity:** CRITICAL (Audit trail integrity, decision payload injection risk)

**Issue:**

The `record_remediation_decision` route validates `expires_at` only when `decision == "approved"` (line 343-344). For "rejected" and "expired" decisions, the field is accepted without validation and stored as-is with potential for empty or malformed values:

```python
# Line 335-354
expires_at = request.expires_at.strip()
revalidation_checks = [
    "plan_exists",
    "scope_authorized",
    "action_version_current",
    "execution_boundary_read_only",
    "defender_evidence_fresh",
]
if request.decision == "approved":
    expires_at = _future_expiry(request.expires_at)  # <- Only for approved
    revalidation_checks.append("approval_not_expired")
decision = planner.repository.decisions.append(
    plan=plan,
    decision=request.decision,
    approver=principal.subject,
    reason=request.reason,
    scope=operate_scope.to_dict(),
    action_version=current_version,
    expires_at=expires_at,  # <- Unvalidated for rejected/expired
    revalidation_checks=revalidation_checks,
)
```

**Attack Vector:** An operator could submit a rejection decision with a future-dated `expires_at` value, creating ambiguous audit entries (e.g., "rejected but expires in 30 days"). Downstream systems reading the decision record cannot distinguish between approval and rejection metadata without parsing the `decision` field separately.

**Data Integrity Impact:** The `RemediationDecisionStore` persists the expires_at value as-is (line 92 in `approval_decisions.py`), creating permanent audit trail pollution if malformed dates are submitted.

**Fix:**

```python
def record_remediation_decision(
    plan_id: str,
    request: RemediationDecisionRequest,
    context: Context,
    scope: ReadScope,
    principal: OperatePrincipal,
) -> dict[str, Any]:
    operate_scope = context.authorizer.effective_scope(principal, "operate", scope)
    planner = _require(context, "remediation_provider", "remediation", operate_scope)
    plans = planner.generate_plans()
    plan = planner.repository.get(plan_id)
    if plan is None:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            "Remediation plan not found",
            details={"plan_id": plan_id},
        )
    scoped_plan = _filter_scoped(plan, operate_scope)
    if scoped_plan is _HIDDEN:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            "Remediation plan not found",
            details={"plan_id": plan_id},
        )
    current_version = str(plan.get("action_version") or "")
    if request.action_version != current_version:
        raise ApiError(
            ErrorCode.CONFLICT,
            "Remediation plan action version is stale",
            details={"plan_id": plan_id},
        )
    if not plan.get("read_only", True) or plan.get("execution_performed"):
        raise ApiError(
            ErrorCode.CONFLICT,
            "Remediation decisions cannot authorize or follow execution in this phase",
            details={"plan_id": plan_id},
        )
    
    # Validate expires_at ONLY for approved decisions; reject/expired must be empty
    expires_at = ""
    revalidation_checks = [
        "plan_exists",
        "scope_authorized",
        "action_version_current",
        "execution_boundary_read_only",
        "defender_evidence_fresh",
    ]
    if request.decision == "approved":
        expires_at = _future_expiry(request.expires_at)
        revalidation_checks.append("approval_not_expired")
    elif request.decision in ("rejected", "expired"):
        # Reject decisions must not carry expires_at metadata
        if request.expires_at.strip():
            raise ApiError(
                ErrorCode.INVALID_REQUEST,
                f"Decision '{request.decision}' must not include expires_at; use empty string",
            )
        expires_at = ""
    
    decision = planner.repository.decisions.append(
        plan=plan,
        decision=request.decision,
        approver=principal.subject,
        reason=request.reason,
        scope=operate_scope.to_dict(),
        action_version=current_version,
        expires_at=expires_at,
        revalidation_checks=revalidation_checks,
    )
    return envelope(
        decision,
        evidence=Evidence(
            source_engine="intelligence.RemediationPlanner",
            source_table="remediation_approval_decisions",
            timestamp=str(plans.get("generated_at") or ""),
            resource_id=plan_id,
            confidence=CONFIDENCE_MEDIUM,
        ),
        scope=operate_scope.to_dict(),
    )
```

---

## Warnings

### WR-01: Weak action_version Hash Determinism (List Serialization)

**File:** `src/intelligence/remediation/remediation_generator.py:90-92`

**Severity:** WARNING (Logic error risk: spurious staleness detections)

**Issue:**

The `action_version` hash includes `action.get('execution_steps')` as a raw list object, which is converted to string during hashing (line 90-92):

```python
action_version = hashlib.sha256(
    f"{action['action_id']}|{action.get('title')}|{action.get('execution_steps')}|{action.get('rollback_actions')}|{evidence_digest}".encode()
).hexdigest()[:16]
```

When a list is stringified with f-string formatting, Python uses `repr()`, which may vary across Python versions or pickle protocols. For example:

- `[{"step": "a"}]` → `"[{'step': 'a'}]"` (Python 3.9)
- `[{"step": "a"}]` → `"[{"step": "a"}]"` (Python 3.12+ with different repr)

**Risk:** If the same action is regenerated on a different Python version or after a minor change to list structure, the hash can change even though the action is semantically identical. This causes the approval check at line 323 in `operations.py` to reject valid approvals as "stale."

**Fix:**

Use stable JSON serialization for list/dict objects:

```python
import json

# Line 87-92
evidence_digest = self._stable_evidence_digest(evidence_citations)

# Ensure stable serialization of structured fields
def _stable_serialize(obj: Any) -> str:
    if isinstance(obj, (list, dict)):
        return json.dumps(obj, sort_keys=True, separators=(',', ':'))
    return str(obj)

action_version = hashlib.sha256(
    f"{action['action_id']}|{action.get('title')}|{_stable_serialize(action.get('execution_steps'))}|{_stable_serialize(action.get('rollback_actions'))}|{evidence_digest}".encode()
).hexdigest()[:16]
```

---

### WR-02: Missing Test Coverage for Rejected/Expired Decision Metadata

**File:** `tests/test_api_remediation_approvals.py:470-551`

**Severity:** WARNING (Test coverage gap: decision state underspecified)

**Issue:**

The test suite includes a test for rejection decisions (`test_defender_plan_rejection_is_recorded_not_deleted`, line 476-499) but does not verify:

1. That rejected decisions **must not accept** an `expires_at` value
2. That expired decisions are handled identically to rejections
3. That reading back a rejected decision preserves the empty `expires_at` field

Current test (line 480-483):
```python
json={
    "decision": "rejected",
    "reason": "Risk too high for production",
    "action_version": plan["action_version"],
}
```

This omits `expires_at` entirely (defaults to empty string), but the API should **reject** requests that explicitly include a non-empty `expires_at` for rejected/expired decisions.

**Missing Tests:**

```python
def test_rejected_decision_rejects_expires_at_field(tmp_path) -> None:
    """A rejection decision must not accept expires_at."""
    client = _client(tmp_path)
    plan = _first_plan(client)

    response = client.post(
        f"/api/v1/remediation-plans/{plan['plan_id']}/decisions",
        headers=_auth(),
        json={
            "decision": "rejected",
            "reason": "Risk too high",
            "action_version": plan["action_version"],
            "expires_at": _future_expiry_datetime(),  # <- Should be rejected
        },
    )

    assert response.status_code == 400
    assert "expires_at" in response.json()["error"]["message"].lower()

def test_expired_decision_handling(tmp_path) -> None:
    """An expired decision must be recorded and stored."""
    client = _client(tmp_path)
    plan = _first_plan(client)

    response = client.post(
        f"/api/v1/remediation-plans/{plan['plan_id']}/decisions",
        headers=_auth(),
        json={
            "decision": "expired",
            "reason": "Approval period lapsed",
            "action_version": plan["action_version"],
        },
    )

    assert response.status_code == 201
    decision = response.json()["data"]
    assert decision["decision"] == "expired"
    assert decision["expires_at"] == ""
```

---

### WR-03: Empty Evidence Digest Weakens action_version Determinism

**File:** `src/intelligence/remediation/remediation_generator.py:72-92`

**Severity:** WARNING (Logic correctness: evidence staleness detection)

**Issue:**

When a plan is generated for a resource with no correlated Defender case, the `evidence_citations` list is empty (line 81). The `_stable_evidence_digest()` method returns an empty string for empty citations (line 223-235):

```python
evidence_citations = list((case or {}).get("evidence_citations") or [])
secure_score_improvement = self._secure_score_improvement(case, action)
...
evidence_digest = self._stable_evidence_digest(evidence_citations)
```

When `evidence_digest` is empty and two identical actions are regenerated, their `action_version` will be identical even if evidence availability changes between generations. This breaks the freshness detection mechanism:

1. Plan A: action_id="fix-1", evidence_digest="" → action_version="abcd1234"
2. New Defender evidence appears for the same resource
3. Plan B: action_id="fix-1", evidence_digest="efgh5678" → action_version="xyzt9999"
4. But if both plans lack evidence initially, both produce action_version="abcd1234"

**Impact:** Approvals made on plans with empty evidence cannot be distinguished from regenerated plans that acquire Defender evidence. The approval route treats this as "current" when it should be "stale."

**Root Cause:** The evidence digest should always be present in the hash, even for empty evidence lists. Use a sentinel value or hash an explicit "no evidence" marker.

**Fix:**

```python
@staticmethod
def _stable_evidence_digest(citations: list[dict[str, Any]]) -> str:
    """Compute a stable digest of the evidence citations.
    
    Returns a hex string that changes when citations change but is stable
    across regenerations when citations are unchanged. Used in action_version
    to make approval freshness detectable.
    
    Empty citation list produces a distinct digest (not empty string) so that
    absence of evidence is detectable as a change.
    """
    if not citations:
        # Use a stable sentinel for "no evidence" so empty→nonempty is detectable
        return hashlib.sha256(b"__no_evidence__").hexdigest()[:16]
    
    # Sort by source_type and source_id to ensure stable ordering
    sorted_citations = sorted(
        [
            f"{c.get('source_type', '')}:{c.get('source_id', '')}:{c.get('observed_at', '')}"
            for c in citations
            if c.get("source_id")
        ]
    )
    digest_input = "|".join(sorted_citations)
    return hashlib.sha256(digest_input.encode()).hexdigest()[:16]
```

---

## Info

### IN-01: Misleading Error Message for expires_at Validation

**File:** `src/api/routers/operations.py:72-74`

**Severity:** INFO (Documentation: operator guidance)

**Issue:**

The error message at line 73 states:

```python
raise ApiError(
    ErrorCode.INVALID_REQUEST,
    "Approved remediation decisions require expires_at",
)
```

But this message appears only when `decision == "approved"` AND `expires_at` is empty. It does not mention that `expires_at` is *only required for* approved decisions, which may confuse operators who are submitting rejection decisions and see this message if they accidentally include the field.

**Suggested Improvement:**

```python
if request.decision == "approved":
    if not request.expires_at.strip():
        raise ApiError(
            ErrorCode.INVALID_REQUEST,
            "Approved remediation decisions must include expires_at (future-dated ISO-8601 timestamp); "
            "rejected and expired decisions must not include expires_at",
        )
    expires_at = _future_expiry(request.expires_at)
    revalidation_checks.append("approval_not_expired")
```

---

### IN-02: UI Decision Form Missing Validation for Rejected Decisions

**File:** `web/src/app/remediation/page.tsx:377-396`

**Severity:** INFO (UX: form state consistency)

**Issue:**

The `recordDecision` function at line 377 sends the decision payload to the API without client-side validation that `decisionExpiresAt` is empty when the decision is "rejected":

```typescript
const recordDecision = async () => {
    if (!selectedPlan?.action_version) return;
    setDecisionSubmitting(true);
    setDecisionError("");
    setDecisionResult(null);
    try {
      const result = await operationsApi.decideRemediationPlan(selectedPlan.plan_id, {
        decision: decisionChoice,
        reason: decisionReason.trim(),
        action_version: selectedPlan.action_version,
        expires_at: decisionExpiresAt.trim(),
      }, scope);
      setDecisionResult(result.data);
      setDecisionReason("");
    } catch (error) {
      setDecisionError(error instanceof Error ? error.message : String(error));
    } finally {
      setDecisionSubmitting(false);
    }
};
```

**Improvement:** Add client-side validation to empty `decisionExpiresAt` when decision is "rejected" or "expired", preventing unnecessary round-trip errors:

```typescript
const recordDecision = async () => {
    if (!selectedPlan?.action_version) return;
    
    // Validate: expires_at is only for approved decisions
    if (decisionChoice !== "approved" && decisionExpiresAt.trim()) {
        setDecisionError(`${decisionChoice} decisions must not include an expiry date.`);
        return;
    }
    if (decisionChoice === "approved" && !decisionExpiresAt.trim()) {
        setDecisionError("Approved decisions must include a future expiry date.");
        return;
    }
    
    setDecisionSubmitting(true);
    setDecisionError("");
    setDecisionResult(null);
    try {
      const result = await operationsApi.decideRemediationPlan(selectedPlan.plan_id, {
        decision: decisionChoice,
        reason: decisionReason.trim(),
        action_version: selectedPlan.action_version,
        expires_at: decisionExpiresAt.trim(),
      }, scope);
      setDecisionResult(result.data);
      setDecisionReason("");
    } catch (error) {
      setDecisionError(error instanceof Error ? error.message : String(error));
    } finally {
      setDecisionSubmitting(false);
    }
};
```

---

## Structural Findings (fallow)

None provided in this review cycle.

---

_Reviewed: 2026-09-01T18:12:12Z_  
_Reviewer: the agent (gsd-code-reviewer)_  
_Depth: standard_
