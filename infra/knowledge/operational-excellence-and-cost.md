# Operational Excellence and Cost Standards

## Reliability
- Production workloads must span at least two Availability Zones in regions
  that support them; single-zone production deployment is a design gap
  unless the region has no zone support, in which case a documented
  cross-region DR plan substitutes.
- Every production service must define and monitor an SLO with an associated
  error budget; the absence of an SLO makes "is this degraded?" a subjective
  question the specialist cannot answer from data.
- Health probes/liveness checks must exist for every compute resource behind
  a load balancer or ingress; a resource with no health probe cannot be
  automatically removed from rotation when unhealthy.

## Cost management
- Idle resources (stopped-but-not-deallocated VMs, unattached managed disks,
  unused Public IPs) are a recurring cost-governance finding and should be
  flagged even when they present no security or reliability risk.
- Reserved Instances or Savings Plans should be evaluated for any workload
  with predictable, sustained (>70% average) utilization over a rolling
  30-day window; pay-as-you-go at that utilization level is a cost gap, not
  a design choice.
- Budgets and cost alerts must be configured per subscription or resource
  group with actionable thresholds (e.g., 80%/100%/120% of forecast), not
  left at the platform default of no alerting.

## Performance efficiency
- Autoscale rules must have both scale-out and scale-in conditions defined;
  scale-out-only configurations lead to permanent over-provisioning and are
  a cost and efficiency gap even though they pose no availability risk.
- Database and cache SKUs should be right-sized against observed utilization
  (CPU, memory, connections) over the trailing 30 days; a SKU provisioned at
  more than 3x observed peak utilization is over-provisioned absent a
  documented growth plan.

## Deployment and release safety
- Blue/green or canary release strategies are expected for any
  customer-facing production service; deploying directly to 100% of
  production traffic with no staged rollout is a deployment-safety gap.
- Every production deployment pipeline must include an automated rollback
  path; "roll forward only" is acceptable only when explicitly documented as
  an accepted risk for that specific workload.
