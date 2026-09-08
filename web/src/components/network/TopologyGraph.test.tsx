import cytoscape from "cytoscape";
import { afterEach, describe, expect, it, vi } from "vitest";
import { buildTopologyEnvelope } from "@/test/network-fixtures";

import {
  STYLESHEET,
  applyHoverFocus,
  buildTopologyExport,
  clearHoverFocus,
  fitTopology,
  layoutFor,
  nextExportIdentity,
  layoutForTransition,
  syncFindingBadge,
} from "./TopologyGraph";

afterEach(() => {
  vi.unstubAllGlobals();
});

/**
 * Cytoscape validates stylesheet property values at instantiation and throws if
 * any are malformed, which takes the whole topology canvas down. Multi-layer
 * background values in particular must be space-separated, not comma-separated.
 * These tests mount the real stylesheet headlessly so a bad value fails here
 * instead of only in the browser.
 */
describe("topology stylesheet", () => {
  const badge =
    "data:image/svg+xml;utf8,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%3E%3C%2Fsvg%3E";

  function mount(elements: cytoscape.ElementDefinition[]) {
    return cytoscape({ headless: true, styleEnabled: true, style: STYLESHEET, elements });
  }

  it("mounts without invalid property values", () => {
    expect(() =>
      mount([{ data: { id: "a", kind: "hub", icon: "/azure-icons/vnet.svg" } }]),
    ).not.toThrow();
  });

  it("renders a badge as a second background layer alongside the service icon", () => {
    const cy = mount([{ data: { id: "a", kind: "hub", icon: "/azure-icons/vnet.svg", badge } }]);
    const node = cy.getElementById("a");

    expect(node.style("background-fit")).toBe("contain none");
    expect(node.style("background-image")).toBe(`/azure-icons/vnet.svg ${badge}`);
  });

  it("still renders a badge on a node that has no service icon", () => {
    const cy = mount([{ data: { id: "grp" } }, { data: { id: "a", parent: "grp", badge } }]);

    expect(cy.getElementById("a").style("background-image")).toBe(`none ${badge}`);
  });

  it("leaves an unbadged node with a single background layer", () => {
    const cy = mount([{ data: { id: "a", kind: "hub", icon: "/azure-icons/fw.svg" } }]);

    expect(cy.getElementById("a").style("background-image")).toBe("/azure-icons/fw.svg");
  });

  it("removes a stale badge when the node no longer has findings", () => {
    const cy = mount([{ data: { id: "a", kind: "hub", icon: "/azure-icons/vnet.svg", label: "hub" } }]);
    const node = cy.getElementById("a");

    syncFindingBadge(node, { severity: "critical", count: 1 });
    expect(node.style("background-image")).toContain("data:image/svg+xml");

    syncFindingBadge(node, undefined);

    expect(node.data("badge")).toBeUndefined();
    expect(node.style("background-image")).toBe("/azure-icons/vnet.svg");

    syncFindingBadge(node, { severity: "high", count: 2 });
    expect(node.style("background-image")).toContain("data:image/svg+xml");
  });

  it("clears a stale badge from a node that has no service icon", () => {
    const cy = mount([{ data: { id: "a" } }]);
    const node = cy.getElementById("a");

    syncFindingBadge(node, { severity: "critical", count: 1 });
    expect(node.style("background-image")).toContain("data:image/svg+xml");

    syncFindingBadge(node, undefined);

    expect(node.style("background-image")).toBe("none");
  });

  it("uses the role-aware title supplied by the badge map", () => {
    const cy = mount([{ data: { id: "a", kind: "resource", icon: "" } }]);
    const node = cy.getElementById("a");

    syncFindingBadge(node, {
      severity: "high",
      count: 2,
      title: "2 open findings affecting this resource (high)",
    });

    expect(node.data("badgeTitle")).toBe(
      "2 open findings affecting this resource (high)",
    );
  });
});

/**
 * Hovering the canvas background inside a compound subscription group used to
 * register as a hover on the group node itself. A group's closed neighbourhood
 * excludes its own descendants, so almost every element got faded and the whole
 * graph washed out without the user touching a node or edge.
 */
describe("topology hover highlight", () => {
  function mountGrouped() {
    return cytoscape({
      headless: true,
      styleEnabled: true,
      style: STYLESHEET,
      elements: [
        { data: { id: "grp" } },
        { data: { id: "a", parent: "grp", kind: "hub" } },
        { data: { id: "b", parent: "grp", kind: "hub" } },
        { data: { id: "c", parent: "grp", kind: "hub" } },
        { data: { id: "ab", source: "a", target: "b" } },
      ],
    });

  }

  it("keeps a group's children in focus when the group itself is focused", () => {
    const cy = mountGrouped();

    applyHoverFocus(cy, cy.getElementById("grp").closedNeighborhood());

    for (const id of ["a", "b", "c"]) {
      expect(cy.getElementById(id).hasClass("cy-hover-fade")).toBe(false);
    }
  });

  it("fades only elements outside the hovered node's neighbourhood", () => {
    const cy = mountGrouped();
    const a = cy.getElementById("a");

    applyHoverFocus(cy, a.closedNeighborhood());

    expect(a.hasClass("cy-hover-focus")).toBe(true);
    expect(cy.getElementById("b").hasClass("cy-hover-focus")).toBe(true);
    expect(cy.getElementById("c").hasClass("cy-hover-fade")).toBe(true);
  });

  it("never renders a group container as faded, so the canvas keeps structure", () => {
    const cy = mountGrouped();

    applyHoverFocus(cy, cy.getElementById("a").closedNeighborhood());

    expect(cy.getElementById("grp").style("opacity")).toBe("1");
  });

  it("leaves a faded node legible rather than washed out", () => {
    const cy = mountGrouped();

    applyHoverFocus(cy, cy.getElementById("a").closedNeighborhood());

    expect(Number(cy.getElementById("c").style("opacity"))).toBeGreaterThanOrEqual(0.3);
  });

  it("restores every element when the pointer leaves", () => {
    const cy = mountGrouped();
    applyHoverFocus(cy, cy.getElementById("a").closedNeighborhood());

    clearHoverFocus(cy);

    expect(cy.elements(".cy-hover-fade, .cy-hover-focus")).toHaveLength(0);
  });
});

describe("topology detail transitions", () => {
  it("keeps existing positions on every payload transition", () => {
    expect(layoutForTransition(40, true)).toMatchObject({ randomize: false });
    expect(layoutForTransition(1_000, true)).toMatchObject({ randomize: false });
  });

  it("chooses layout quality from connected nodes rather than hidden singleton context", () => {
    expect(layoutFor(103, 35)).toMatchObject({
      quality: "proof",
      randomize: true,
    });
  });

  describe("topology motion preferences", () => {
    it("queries matchMedia and fits immediately when reduced motion is requested", () => {
      const fit = vi.fn();
      const animate = vi.fn();
      const elements = vi.fn(() => ({ length: 1 }));
      vi.stubGlobal(
        "matchMedia",
        vi.fn(() => ({ matches: true })),
      );

      fitTopology({ fit, animate, elements } as unknown as cytoscape.Core);

      expect(window.matchMedia).toHaveBeenCalledWith(
        "(prefers-reduced-motion: reduce)",
      );
      expect(fit).toHaveBeenCalledWith(undefined, 40);
      expect(animate).not.toHaveBeenCalled();
    });
  });
});

describe("topology export provenance", () => {
  it("emits the ten declared keys in order with the previous topology nested last", () => {
    const topology = buildTopologyEnvelope().data.topology;
    const exportedAt = "2026-09-06T01:02:03.000Z";
    const payload = buildTopologyExport(
      topology,
      {
        scope: { subscriptions: ["sub-a"] },
        detailLevel: "summary",
        coverage: {
          total: 9,
          returned: 2,
          truncated: true,
          badgePageBudget: 4,
          badgeFetchExhausted: false,
          badgeReturned: 2,
          badgeTotal: 7,
          renderedNodes: 2,
          totalNodes: 9,
          renderedRelationships: 1,
          totalRelationships: 3,
          droppedRelationships: 2,
        },
        filters: {
          search: "prod",
          filterMode: true,
          showServices: false,
          showFindings: true,
        },
        evidence: [],
        warnings: ["partial"],
        knowledgeVersion: "kv-1",
        graphFreshness: null,
      },
      exportedAt,
    );

    expect(Object.keys(payload)).toEqual([
      "exported_at",
      "scope",
      "detail_level",
      "coverage",
      "filters",
      "evidence",
      "warnings",
      "knowledge_version",
      "graph_freshness",
      "topology",
    ]);
    expect(payload.topology).toEqual(topology);
    expect(payload.exported_at).toBe(exportedAt);
    expect(Number.isNaN(Date.parse(payload.exported_at))).toBe(false);
    expect(payload.coverage).toMatchObject({
      truncated: true,
      badge_page_budget: 4,
      badge_fetch_exhausted: false,
      nodes: { rendered: 2, total: 9 },
      relationships: { rendered: 1, total: 3, dropped: 2 },
    });
    expect(payload.filters).toEqual({
      search: "prod",
      filter_mode: true,
      show_services: false,
      show_findings: true,
    });
  });

  it("writes absent provenance fields as null rather than omitting them", () => {
    const topology = buildTopologyEnvelope().data.topology;
    const payload = buildTopologyExport(
      topology,
      {
        scope: null,
        detailLevel: "summary",
        coverage: {
          total: null,
          returned: null,
          truncated: false,
          badgePageBudget: 4,
          badgeFetchExhausted: true,
          badgeReturned: 0,
          badgeTotal: 0,
          renderedNodes: 0,
          totalNodes: null,
          renderedRelationships: 0,
          totalRelationships: null,
          droppedRelationships: 0,
        },
        filters: {
          search: "",
          filterMode: false,
          showServices: true,
          showFindings: true,
        },
        evidence: null,
        warnings: null,
        knowledgeVersion: null,
        graphFreshness: null,
      },
      "2026-09-06T01:02:03.000Z",
    );

    expect(payload.scope).toBeNull();
    expect(payload.evidence).toBeNull();
    expect(payload.warnings).toBeNull();
    expect(payload.knowledge_version).toBeNull();
    expect(payload.graph_freshness).toBeNull();
  });

  it("keeps real export time while suffixing same-second filename collisions", () => {
    const instant = new Date("2026-09-06T01:02:03.000Z");
    const json = nextExportIdentity("json", instant);
    const png = nextExportIdentity("png", instant);

    expect(json.exportedAt).toBe(instant.toISOString());
    expect(png.exportedAt).toBe(instant.toISOString());
    expect(json.filename).toMatch(
      /^network-topology-\d{8}-\d{6}\.json$/,
    );
    expect(png.filename).toMatch(
      /^network-topology-\d{8}-\d{6}-2\.png$/,
    );
    expect(json.filename).not.toBe(png.filename.replace(/\.png$/, ".json"));
    expect(json.filename.match(/\d{8}-\d{6}/)?.[0]).toHaveLength(15);
    expect(png.filename.match(/\d{8}-\d{6}/)?.[0]).toHaveLength(15);
  });
});
