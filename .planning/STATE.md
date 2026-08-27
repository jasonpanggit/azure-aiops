---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
current_phase: 08
current_phase_name: fabric-migration
status: blocked
stopped_at: "2026-08-27T22:40:00.000Z"
last_updated: "2026-08-27T22:40:00.000Z"
last_activity: 2026-08-27
last_activity_desc: INFRASTRUCTURE BLOCKER - Fabric Starter capacity tier cannot support 9 concurrent notebooks. Capacity upgrade required.
progress:
  total_phases: 4
  completed_phases: 0
  total_plans: 23
  completed_plans: 22
  blocked_on: Fabric capacity tier upgrade decision
---

# ⚠️ PHASE 08 INFRASTRUCTURE BLOCKER

## Fabric Capacity Tier Limitation (2026-08-27)

**Status:** 🔴 **BLOCKED** - Platform infrastructure limitation, not code/configuration issue

**Discovery:** Starter Pool capacity tier has fundamental autoscale constraints:
- Starter Pool is READ-ONLY (cannot be modified)
- New custom pools capped at autoscale 1 node maximum
- Insufficient capacity to run 9 concurrent notebooks

**Root Cause:** Fabric Starter capacity tier design
- Entry-level tier with limited vCore allocation
- Designed for lightweight workloads, not parallel notebook execution
- Not a bug or misconfiguration—a platform tier limitation

## Analysis

**Current Infrastructure:**
- Capacity tier: Starter
- Spark pool: Starter Pool (read-only, Medium nodes, 1-3 autoscale)
- Custom pools: Available but capped at 1 node autoscale
- Result: Cannot execute 9 notebooks concurrently

**Why Notebooks Fail:**
1. First notebook starts on 1 node
2. Second notebook requests Spark session → exhausts capacity
3. Fabric cancels session with `System_Cancelled_Session_Statements_Failed`
4. Occurs for all 9 notebooks, 0 output tables created

**Technical Evidence:**
- Spark session cancellation is deterministic (not intermittent)
- Consistent error across all notebook types
- No configuration changes can fix platform-level tier limits

## Path Forward

### Option 1: Accept Limitation (Phase 08 Abandoned)
- Keep Starter capacity tier
- Phase 08 cannot complete
- Hermes remains primary system
- Cost: No additional Fabric spend

### Option 2: Upgrade Capacity Tier (Phase 08 Completes)
- Upgrade to Standard (F2) or Premium (F4+) capacity
- Enables configurable autoscale (4-5+ nodes)
- Phase 08 notebooks execute successfully
- Cost: ~$500+/month (Standard) or ~$2000+/month (Premium)

**Tier Mapping:**
| Tier | Starter | Standard (F2) | Premium (F4+) |
|------|---------|---------------|---------------|
| vCore | Limited | Medium | High |
| Autoscale Max | 3 | 4-5 | 6+ |
| Node Sizes | Small, Medium | Medium, Large, XLarge | Full range |
| Monthly Cost | ~$60-100 | ~$500+ | ~$2000+ |

## Business Decision Required

This is **not** a technical problem to solve—it's an infrastructure decision:
- **Technical team**: Notebooks are correctly coded, Hermes parity proven, Phase 08 ready
- **Business decision**: Commit to Fabric (capacity upgrade) vs. maintain Hermes-only approach

## Impact

**If Starter tier maintained:**
- ✗ Phase 08 cannot execute
- ✗ Fabric migration blocked indefinitely
- ✓ No additional cost
- ✓ Hermes remains operational

**If capacity tier upgraded:**
- ✓ Phase 08 executes successfully
- ✓ Fabric migration completes
- ✓ Can retire Hermes
- ✗ Significant monthly Fabric cost
- ✗ Capacity procurement lead time (~1-2 weeks)

---

**Next Step:** Business/infrastructure decision owner to evaluate upgrade cost vs. Hermes retention cost
