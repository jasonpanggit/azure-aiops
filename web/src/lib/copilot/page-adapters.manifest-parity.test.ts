import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  COPILOT_ROUTE_DISPOSITIONS,
  COPILOT_ROUTE_STARTER_HINTS,
} from "./page-adapters";

// The committed, versioned specialist manifest is the single cross-language
// authority: the Python backend loads this exact file
// (tests/test_orchestration_parity.py), and this gate proves the browser page
// adapters never drift from it. Frontend-only hints, permissive subset checks,
// and misspelled/duplicate/unknown mappings must all fail (D-03, D-05, D-06).
const REPO_ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..", "..");
const MANIFEST_PATH = join(REPO_ROOT, "src", "operations", "specialists.v1.json");

interface ManifestSpecialist {
  id: string;
  display_name: string;
  purpose: string;
  ui_metadata: Record<string, unknown>;
  operations_mcp_tools: string[];
  page_mappings: string[];
  primary_page_mappings?: string[];
  page_tool_grants?: Record<string, string[]>;
}
interface Manifest {
  specialists: ManifestSpecialist[];
}

const manifest = JSON.parse(readFileSync(MANIFEST_PATH, "utf8")) as Manifest;

/**
 * Mirror of `SpecialistManifest.page_mapping_projection`: page -> specialist
 * ids, stable manifest order with the specialist whose id equals the page name
 * sorted first (Array.prototype.sort is stable, so ties keep append order).
 */
function projectPageMappings(
  specialists: Array<{
    id: string;
    page_mappings: string[];
    primary_page_mappings?: string[];
  }>,
): Record<string, string[]> {
  const pages = new Map<string, string[]>();
  const byId = new Map(
    specialists.map((specialist) => [specialist.id, specialist]),
  );
  for (const specialist of specialists) {
    for (const page of specialist.page_mappings) {
      const owners = pages.get(page) ?? [];
      owners.push(specialist.id);
      pages.set(page, owners);
    }
  }
  const projection: Record<string, string[]> = {};
  for (const [page, owners] of Array.from(pages.entries())) {
    projection[page] = [...owners].sort(
      (left, right) => {
        const priority = (specialistId: string) => Number(
          specialistId !== page
          && !(byId.get(specialistId)?.primary_page_mappings ?? []).includes(page),
        );
        return priority(left) - priority(right);
      },
    );
  }
  return projection;
}

function sameSet(left: readonly string[], right: readonly string[]): boolean {
  if (left.length !== right.length) return false;
  const sortedLeft = [...left].sort();
  const sortedRight = [...right].sort();
  return sortedLeft.every((value, index) => value === sortedRight[index]);
}

const rawProjection = projectPageMappings(manifest.specialists);

const manifestSpecialistIds = manifest.specialists.map((specialist) => specialist.id);
const manifestSpecialistIdSet = new Set(manifestSpecialistIds);
const manifestGrants = new Map(
  manifest.specialists.map((specialist) => [
    specialist.id,
    new Set(specialist.operations_mcp_tools),
  ]),
);

const integratedRoutes = Object.entries(COPILOT_ROUTE_DISPOSITIONS).filter(
  ([, disposition]) => disposition.kind === "integrated",
);

describe("manifest / adapter specialist parity (COP-03, D-03, D-05, D-06)", () => {
  it("anchors every integrated route on a manifest page-mapping key with real owners", () => {
    for (const [route, disposition] of integratedRoutes) {
      if (disposition.kind !== "integrated") continue;
      const owners = rawProjection[disposition.pageKind];
      expect(owners, `${route} anchor "${disposition.pageKind}" is not a manifest page`).toBeDefined();
      expect(owners.length).toBeGreaterThan(0);
      for (const owner of owners) {
        expect(manifestSpecialistIdSet.has(owner)).toBe(true);
      }
    }
  });

  it("declares starter hints for exactly the integrated route set", () => {
    expect(Object.keys(COPILOT_ROUTE_STARTER_HINTS).sort()).toEqual(
      integratedRoutes.map(([route]) => route).sort(),
    );
  });

  it("maps every adapter starter hint to an authorized manifest specialist and granted tool", () => {
    for (const [route, hints] of Object.entries(COPILOT_ROUTE_STARTER_HINTS)) {
      expect(hints.length).toBeGreaterThan(0);
      for (const hint of hints) {
        expect(
          manifestSpecialistIdSet.has(hint.specialistId),
          `${route}: unknown specialist "${hint.specialistId}"`,
        ).toBe(true);
        if (hint.tool) {
          expect(
            manifestGrants.get(hint.specialistId)?.has(hint.tool),
            `${route}: "${hint.specialistId}" is not granted tool "${hint.tool}"`,
          ).toBe(true);
          const disposition = COPILOT_ROUTE_DISPOSITIONS[route];
          if (disposition.kind === "integrated") {
            const specialist = manifest.specialists.find(
              (entry) => entry.id === hint.specialistId,
            );
            const pageGrant = specialist?.page_tool_grants?.[disposition.pageKind];
            if (pageGrant) {
              expect(
                pageGrant.includes(hint.tool),
                `${route}: "${hint.tool}" is outside the page-specific grant`,
              ).toBe(true);
            }
          }
        }
      }
    }
  });

  it("keeps every Changes starter inside its exact manifest page and tool grant", () => {
    const disposition = COPILOT_ROUTE_DISPOSITIONS["/changes"];
    expect(disposition).toEqual({ kind: "integrated", pageKind: "changes" });
    if (disposition.kind !== "integrated") return;

    for (const hint of COPILOT_ROUTE_STARTER_HINTS["/changes"]) {
      const specialist = manifest.specialists.find(
        (entry) => entry.id === hint.specialistId,
      );
      expect(
        specialist?.page_mappings.includes(disposition.pageKind),
        `/changes: "${hint.specialistId}" is not granted page "${disposition.pageKind}"`,
      ).toBe(true);
      if (hint.tool) {
        expect(
          specialist?.page_tool_grants?.[disposition.pageKind]?.includes(hint.tool),
          `/changes: "${hint.tool}" lacks an explicit page-specific grant`,
        ).toBe(true);
      }
    }
  });

  it("keeps every Predeploy starter inside its exact manifest page and tool grant", () => {
    const disposition = COPILOT_ROUTE_DISPOSITIONS["/changes/predeploy"];
    expect(disposition).toEqual({
      kind: "integrated",
      pageKind: "changes_predeploy",
    });
    if (disposition.kind !== "integrated") return;

    for (const hint of COPILOT_ROUTE_STARTER_HINTS["/changes/predeploy"]) {
      const specialist = manifest.specialists.find(
        (entry) => entry.id === hint.specialistId,
      );
      expect(
        specialist?.page_mappings.includes(disposition.pageKind),
        `/changes/predeploy: "${hint.specialistId}" is not granted page "${disposition.pageKind}"`,
      ).toBe(true);
      if (hint.tool) {
        expect(
          specialist?.page_tool_grants?.[disposition.pageKind]?.includes(hint.tool),
          `/changes/predeploy: "${hint.tool}" lacks an explicit page-specific grant`,
        ).toBe(true);
      }
    }
  });

  it("references exactly the manifest specialist portfolio in both directions", () => {
    // Every specialist the UI can reach is a page-kind anchor owner or a starter
    // hint; every manifest specialist is reachable. Exact set equality catches
    // both an invented frontend specialist and an orphaned manifest specialist.
    const referenced = new Set<string>();
    for (const [, disposition] of integratedRoutes) {
      if (disposition.kind !== "integrated") continue;
      for (const owner of rawProjection[disposition.pageKind]) referenced.add(owner);
    }
    for (const hints of Object.values(COPILOT_ROUTE_STARTER_HINTS)) {
      for (const hint of hints) referenced.add(hint.specialistId);
    }
    expect(sameSet(Array.from(referenced), manifestSpecialistIds)).toBe(true);
  });

  it("keeps the known multi-owner manifest pages exact (owner-first order)", () => {
    // Pins the exact backend page_mapping_projection assertions so the TS mirror
    // cannot silently reorder or drop a co-owner.
    expect(rawProjection.remediation).toEqual(["remediation", "governance"]);
    expect(rawProjection.resource).toEqual(["governance", "resource_health_observability"]);
    expect(rawProjection.vulnerability).toEqual(["vulnerability", "patch"]);
    expect(rawProjection.incident).toEqual(["incident", "change"]);
    expect(rawProjection.network).toEqual(["network"]);
    expect(rawProjection.compliance).toEqual([
      "network",
      "vulnerability",
      "governance",
      "remediation",
    ]);
    expect(
      manifest.specialists.find((specialist) => specialist.id === "network")
        ?.page_tool_grants?.compliance,
    ).toEqual(["firewall_nsg_gaps"]);
    expect(
      manifest.specialists.find((specialist) => specialist.id === "vulnerability")
        ?.page_tool_grants?.compliance,
    ).toEqual(["cve_exposure"]);
  });
});

describe("parity gate rejects manifest / adapter drift", () => {
  it("rejects a starter hint that names an unknown or misspelled specialist", () => {
    expect(manifestSpecialistIdSet.has("network")).toBe(true);
    expect(manifestSpecialistIdSet.has("netwrok")).toBe(false);
    expect(manifestSpecialistIdSet.has("made_up_specialist")).toBe(false);
  });

  it("rejects a starter hint tool outside the owning specialist grant", () => {
    // network is not granted a vulnerability tool; governance is not granted a
    // network tool. An unauthorized (specialist, tool) hint must fail.
    expect(manifestGrants.get("network")?.has("cve_exposure")).toBe(false);
    expect(manifestGrants.get("governance")?.has("network_topology")).toBe(false);
  });

  it("detects an extra owner injected into a page mapping", () => {
    const mutated = JSON.parse(JSON.stringify(rawProjection)) as Record<string, string[]>;
    mutated.network = [...mutated.network, "finops"];
    expect(sameSet(mutated.network, rawProjection.network)).toBe(false);
  });

  it("detects a missing owner dropped from a page mapping", () => {
    const mutated = JSON.parse(JSON.stringify(rawProjection)) as Record<string, string[]>;
    mutated.remediation = mutated.remediation.filter((owner) => owner !== "governance");
    expect(sameSet(mutated.remediation, rawProjection.remediation)).toBe(false);
  });

  it("detects a specialist portfolio that gains or loses a member", () => {
    expect(sameSet([...manifestSpecialistIds, "ghost_specialist"], manifestSpecialistIds)).toBe(false);
    expect(sameSet(manifestSpecialistIds.slice(1), manifestSpecialistIds)).toBe(false);
  });
});
