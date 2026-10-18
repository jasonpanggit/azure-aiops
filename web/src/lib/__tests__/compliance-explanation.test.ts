import { describe, expect, it } from "vitest";
import {
  candidateControlDomain, COMPLIANCE_DOMAINS, compareAssessment,
  explainPolicyChanges, findingDomain, frameworkEvidence,
  hasExplicitPublicAccess,
} from "../compliance-explanation";
import type { ComplianceDesignPolicy, ComplianceDeviation } from "../types";

const policy: ComplianceDesignPolicy = {
  name: "Test policy", requiredHubRouting: true, firewallInspectionRequired: true,
  environmentIsolationRequired: true, allowedPorts: "443",
  privateEndpointRequiredFor: "microsoft.sql", requiredDnsZones: "privatelink.database.windows.net",
  loggingRequired: true, ownerTag: "owner", allowCrossSubscriptionPeering: false,
};
const finding = { id: "finding-1", type: "missing_owner", severity: "medium", title: "Missing owner", detail: "Unmapped", resource: "resource-1" };
const deviation: ComplianceDeviation = {
  deviation_id: "deviation-1", kind: "policy", observed_at: "2026-10-16T06:00:00Z",
  severity: "high", control: "NS-1", status: "open", resource: "resource-1",
  application: "", business_service: "", environment: "", business_criticality: "", subscription: "sub-a",
};

describe("Compliance evidence explanations", () => {
  it.each([
    { public_network_access: "Disabled" }, { publicNetworkAccess: "Disabled" },
    { note: "public access is disabled" }, { public_ip: false }, { internetFacing: false },
    { public_network_access: "Enabled", publicNetworkAccess: "Disabled" }, {},
  ])("does not invent public access from disabled, absent or contradictory metadata: %j", details => {
    expect(hasExplicitPublicAccess(details)).toBe(false);
  });

  it("recognizes explicit normalized and Azure-style enabled settings", () => {
    expect(hasExplicitPublicAccess({ public_network_access: "Enabled" })).toBe(true);
    expect(hasExplicitPublicAccess({ publicNetworkAccess: " enabled " })).toBe(true);
  });

  it("explains only exact changed fields and unsupported intent boundaries", () => {
    const changes = explainPolicyChanges(policy, { ...policy, requiredHubRouting: false, environmentIsolationRequired: false });
    expect(changes.map(change => change.field)).toEqual(["requiredHubRouting", "environmentIsolationRequired"]);
    expect(changes.every(change => change.effect.includes("Declared intent only"))).toBe(true);
    expect(explainPolicyChanges(policy, policy)).toEqual([]);
    expect(changes[0]).toMatchObject({ before: true, after: false });
  });

  it("separates added, removed and reclassified findings by stable identity", () => {
    const result = compareAssessment([finding, { ...finding, id: "removed" }], [
      { ...finding, severity: "high" }, { ...finding, id: "added" },
    ]);
    expect(result.added.map(row => row.id)).toEqual(["added"]);
    expect(result.removed.map(row => row.id)).toEqual(["removed"]);
    expect(result.changed.map(row => row.id)).toEqual(["finding-1"]);
    expect(compareAssessment([finding], [finding])).toEqual({ added: [], removed: [], changed: [] });
  });

  it.each(["NS-1", "ns-12", " LT-4 "])("recognizes only explicit candidate control IDs: %s", control => {
    expect(candidateControlDomain(control)).toBe(control.trim().slice(0, 2).toUpperCase());
  });

  it.each(["Network security", "CIS 1.2", "NS-0", "NS-1 and IM-2", "NS-1: arbitrary prose", "ISO-27001", "constructor", "NS-1\nIM-2"])(
    "leaves ambiguous or unsupported framework labels unmapped: %j", control => {
      expect(candidateControlDomain(control)).toBeUndefined();
    },
  );

  it("retains accepted observations without claiming passed coverage or losing unmapped evidence", () => {
    const result = frameworkEvidence([finding, finding], new Set([finding.id]), [
      deviation, deviation, { ...deviation, deviation_id: "unknown", control: "Custom encryption standard" },
    ]);
    const assets = result.domains.find(domain => domain.id === "AM");
    expect(assets?.local).toHaveLength(1);
    expect(assets?.acceptedCount).toBe(1);
    expect(result.domains.find(domain => domain.id === "NS")?.governed).toHaveLength(1);
    expect(result.domains.find(domain => domain.id === "DP")?.governed).toEqual([]);
    expect(result.unmapped.map(row => row.deviation_id)).toEqual(["unknown"]);
    expect(result.domains).toHaveLength(12);
    expect(COMPLIANCE_DOMAINS.map(domain => domain.id)).toEqual(["NS", "IM", "PA", "DP", "AM", "LT", "IR", "PV", "ES", "BR", "DS", "GS"]);
    expect(findingDomain("unknown")).toBeUndefined();
    expect(findingDomain("constructor")).toBeUndefined();
  });
});
