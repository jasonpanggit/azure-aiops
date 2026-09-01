---
phase: 02-investigation-recommendation-and-approval
fixed_at: 2026-09-01T18:19:00.000Z
review_path: .planning/phases/02-investigation-recommendation-and-approval/02-REVIEW.md
iteration: 1
findings_in_scope: 6
fixed: 5
skipped: 1
status: all_fixed
---

# Phase 02: Code Review Fix Report

**Fixed at:** 2026-09-01T18:19:00.000Z  
**Source review:** .planning/phases/02-investigation-recommendation-and-approval/02-REVIEW.md  
**Iteration:** 1

**Summary:**
- Findings in scope: 6 (1 Critical, 3 Warnings, 2 Info)
- Fixed: 5
- Skipped: 1

## Fixed Issues

### CR-01: Inconsistent expires_at Validation for Rejected/Expired Decisions

**Severity:** CRITICAL (Audit trail integrity, decision payload injection risk)

**Files modified:** `src/api/routers/operations.py`  
**Commit:** 622871ba

**Applied fix:**

1. Updated `_future_expiry()` error message to clarify that `expires_at` is required only for approved decisions (IN-01 addressed as part of this fix).
2. Modified `record_remediation_decision()` to explicitly validate and reject non-empty `expires_at` for rejected/expired decisions:
   - For "approved" decisions: validate and process `expires_at` as before
   - For "rejected"/"expired" decisions: raise `ApiError` if `expires_at` is non-empty, set to empty string
3. Test results: All 22 approval workflow tests pass, including new test coverage (WR-02)

**Verification:** Syntax check passed; targeted pytest on approvals suite confirms CR-01 validation prevents expired/rejected decisions from accepting expires_at metadata.

---

### WR-01: Weak action_version Hash Determinism (List Serialization)

**Severity:** WARNING (Logic error risk: spurious staleness detections)

**Files modified:** `src/intelligence/remediation/remediation_generator.py`  
**Commit:** bc102e1f

**Applied fix:**

1. Added `import json` to support stable JSON serialization
2. Implemented `_stable_serialize()` static method that converts lists/dicts to deterministic JSON format using `json.dumps(obj, sort_keys=True, separators=(',', ':'))`
3. Updated `action_version` hash computation to use `_stable_serialize()` for `execution_steps` and `rollback_actions` fields
4. This ensures Python version independence and fixes repr() variability across versions

**Verification:** Syntax check passed; business decision tests (25 tests) confirm action_version hashing remains stable.

---

### WR-03: Empty Evidence Digest Weakens action_version Determinism

**Severity:** WARNING (Logic correctness: evidence staleness detection)

**Files modified:** `src/intelligence/remediation/remediation_generator.py`  
**Commit:** bc102e1f

**Applied fix:**

1. Updated `_stable_evidence_digest()` to return a stable sentinel hash for empty citations instead of empty string:
   - Empty citations: `hashlib.sha256(b"__no_evidence__").hexdigest()[:16]`
   - No citations → non-empty evidence_citations: different action_version, freshness detected
2. Fallback case when sorted citations are empty also returns sentinel (defensive)
3. Maintains existing stable ordering for non-empty citations

**Verification:** Syntax check passed; evidence-related tests pass; action_version now correctly changes when evidence becomes available.

---

### WR-02: Missing Test Coverage for Rejected/Expired Decision Metadata

**Severity:** WARNING (Test coverage gap: decision state underspecified)

**Files modified:** `tests/test_api_remediation_approvals.py`  
**Commit:** 8681773d

**Applied fix:**

Added two new test cases to verify rejected/expired decision validation:

1. **`test_rejected_decision_rejects_expires_at_field`**: Verifies that posting a rejection with a non-empty `expires_at` returns HTTP 400 with error message mentioning "expires_at"
2. **`test_expired_decision_handling`**: Verifies that expired decisions are recorded successfully with empty `expires_at` field

**Test results:** Both new tests pass (2/2); full test suite now includes 22 tests covering all decision types.

**Verification:** Tests execute without errors; coverage gap closed.

---

### IN-02: UI Decision Form Missing Validation for Rejected Decisions

**Severity:** INFO (UX: form state consistency)

**Files modified:** `web/src/app/remediation/page.tsx`  
**Commit:** 2be6ed3c

**Applied fix:**

Added client-side validation to `recordDecision()` function:

1. If decision is "rejected" or "expired" and `expires_at` is non-empty: show error "X decisions must not include an expiry date."
2. If decision is "approved" and `expires_at` is empty: show error "Approved decisions must include a future expiry date."
3. Validation runs before API call, preventing unnecessary round-trip errors

**Verification:** TypeScript syntax check passed; validation improves UX by providing immediate feedback before server submission.

---

## Skipped Issues

### IN-01: Misleading Error Message for expires_at Validation

**Status:** ADDRESSED (as part of CR-01)

**File:** `src/api/routers/operations.py:68-75`

**Reason:** The error message improvement suggested in IN-01 was incorporated into the CR-01 fix. The `_future_expiry()` error message now reads:

```
"Approved remediation decisions must include expires_at (future-dated ISO-8601 timestamp); 
rejected and expired decisions must not include expires_at"
```

This clarifies all three decision types (approved required, rejected/expired prohibited) in a single message, addressing both CR-01 audit trail integrity and IN-01 operator guidance. No separate commit needed.

---

## Test Results

**Test suite status:** All tests passing

| Test Suite | Command | Result |
|-----------|---------|--------|
| Remediation Approvals | `uv run pytest tests/test_api_remediation_approvals.py -q` | ✓ 22/22 PASSED |
| New CR-01 tests | `uv run pytest tests/test_api_remediation_approvals.py::test_rejected_decision_rejects_expires_at_field tests/test_api_remediation_approvals.py::test_expired_decision_handling -q` | ✓ 2/2 PASSED |
| Business Decision | `uv run pytest tests/test_remediation_business_decision.py -q` | ✓ 25/25 PASSED |
| Evidence tests | `uv run pytest tests/ -k evidence -q` | ✓ PASSED |

**Commit graph (main branch):**
```
2be6ed3c fix(02): IN-02 add UI client-side validation for rejected/expired decisions
8681773d fix(02): WR-02 add test coverage for rejected/expired decision validation
bc102e1f fix(02): WR-01, WR-03 stable action_version hash with evidence sentinel
622871ba fix(02): CR-01 inconsistent expires_at validation for rejected/expired decisions
```

---

## Next Steps

1. ✓ All 6 in-scope findings addressed (5 fixed, 1 integrated into fix)
2. ✓ All tests passing
3. Ready for Phase 2 verification checkpoint
4. Proceed to Phase 3 (Safe Remediation Execution) after checkpoint approval

---

_Fixed: 2026-09-01T18:19:00Z_  
_Fixer: gsd-code-fixer agent_  
_Iteration: 1_
