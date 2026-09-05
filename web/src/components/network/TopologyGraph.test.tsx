import cytoscape from "cytoscape";
import { describe, expect, it } from "vitest";

import {
  STYLESHEET,
  applyHoverFocus,
  clearHoverFocus,
  layoutForTransition,
  syncFindingBadge,
} from "./TopologyGraph";

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
});
