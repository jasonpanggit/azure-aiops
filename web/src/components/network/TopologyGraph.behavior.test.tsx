import { act, cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { buildTopologyEnvelope } from "@/test/network-fixtures";
import type { TopologyExportContext } from "./TopologyGraph";

const cytoscapeProbe = vi.hoisted(() => ({
  factory: Object.assign(vi.fn(), { use: vi.fn() }),
}));

vi.mock("cytoscape", () => ({
  default: cytoscapeProbe.factory,
}));

vi.mock("cytoscape-fcose", () => ({
  default: {},
}));

import TopologyGraph from "./TopologyGraph";

class ResizeObserverDouble {
  static instances: ResizeObserverDouble[] = [];

  readonly observe = vi.fn();
  readonly disconnect = vi.fn();

  constructor(private readonly callback: ResizeObserverCallback) {
    ResizeObserverDouble.instances.push(this);
  }

  trigger(width: number, height: number) {
    this.callback(
      [
        {
          contentRect: { width, height },
        } as ResizeObserverEntry,
      ],
      this as unknown as ResizeObserver,
    );
  }
}

function collectionDouble() {
  const collection = {
    length: 0,
    addClass: vi.fn(),
    difference: vi.fn(),
    descendants: vi.fn(),
    forEach: vi.fn(),
    nonempty: vi.fn(() => false),
    removeClass: vi.fn(),
    style: vi.fn(),
    toArray: vi.fn(() => []),
    union: vi.fn(),
  };
  collection.addClass.mockReturnValue(collection);
  collection.difference.mockReturnValue(collection);
  collection.descendants.mockReturnValue(collection);
  collection.removeClass.mockReturnValue(collection);
  collection.style.mockReturnValue(collection);
  collection.union.mockReturnValue(collection);
  return collection;
}

function coreDouble() {
  const collection = collectionDouble();
  const run = vi.fn();
  const core = {
    animate: vi.fn(),
    batch: vi.fn((callback: () => void) => callback()),
    destroy: vi.fn(),
    edges: vi.fn(() => collection),
    elements: vi.fn(() => collection),
    fit: vi.fn(),
    getElementById: vi.fn(() => collection),
    height: vi.fn(() => 300),
    layout: vi.fn(() => ({ run })),
    nodes: vi.fn(() => collection),
    off: vi.fn(),
    on: vi.fn(),
    png: vi.fn(() => "data:image/png;base64,"),
    resize: vi.fn(),
    width: vi.fn(() => 400),
    zoom: vi.fn(() => 1),
  };
  return { core, run };
}

const exportContext: TopologyExportContext = {
  scope: null,
  detailLevel: "summary",
  coverage: {
    total: 2,
    returned: 2,
    truncated: false,
    badgePageBudget: 4,
    badgeFetchExhausted: true,
    badgeReturned: 0,
    badgeTotal: 0,
    renderedNodes: 2,
    totalNodes: 2,
    renderedRelationships: 1,
    totalRelationships: 1,
    droppedRelationships: 0,
  },
  filters: {
    search: "",
    filterMode: false,
    showServices: true,
    showFindings: true,
    showDisconnectedContext: false,
    showUnattachedPrivateLinkCandidates: false,
    showRelationshipLabels: false,
  },
  evidence: null,
  warnings: null,
  knowledgeVersion: null,
  graphFreshness: null,
};

function renderGraph() {
  const double = coreDouble();
  cytoscapeProbe.factory.mockReset();
  cytoscapeProbe.factory.mockReturnValue(double.core);
  const view = render(
    <TopologyGraph
      topology={buildTopologyEnvelope().data.topology}
      search=""
      showServices
      selectedId=""
      onSelect={vi.fn()}
      exportContext={exportContext}
    />,
  );
  const observer = ResizeObserverDouble.instances.at(-1);
  expect(observer).toBeDefined();
  return { ...view, ...double, observer: observer! };
}

describe("TopologyGraph browser integration behavior", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    ResizeObserverDouble.instances = [];
    vi.stubGlobal("ResizeObserver", ResizeObserverDouble);
    vi.stubGlobal(
      "matchMedia",
      vi.fn(() => ({ matches: true })),
    );
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(400);
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(300);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllTimers();
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("performs resize only for a sub-threshold observer delta", () => {
    const { core, observer } = renderGraph();
    core.resize.mockClear();
    core.fit.mockClear();
    core.animate.mockClear();

    act(() => {
      observer.trigger(447, 347);
      vi.advanceTimersByTime(150);
    });

    expect(core.resize).toHaveBeenCalledTimes(1);
    expect(core.fit).not.toHaveBeenCalled();
    expect(core.animate).not.toHaveBeenCalled();
  });

  it("performs resize and fit for a supra-threshold observer delta", () => {
    const { core, observer } = renderGraph();
    core.resize.mockClear();
    core.fit.mockClear();

    act(() => {
      observer.trigger(449, 349);
      vi.advanceTimersByTime(150);
    });

    expect(core.resize).toHaveBeenCalledTimes(1);
    expect(core.fit).toHaveBeenCalledWith(undefined, 40);
  });

  it("disconnects the observer and clears a pending resize timer on teardown", () => {
    const { core, observer, unmount } = renderGraph();
    core.resize.mockClear();

    act(() => observer.trigger(500, 400));
    expect(vi.getTimerCount()).toBe(1);

    unmount();

    expect(observer.disconnect).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
    act(() => vi.advanceTimersByTime(150));
    expect(core.resize).not.toHaveBeenCalled();
  });

  it("does not pass a custom wheel option to Cytoscape", () => {
    renderGraph();

    expect(cytoscapeProbe.factory).toHaveBeenCalledTimes(1);
    const options = cytoscapeProbe.factory.mock.calls[0][0];
    expect(options).not.toHaveProperty("wheelSensitivity");
  });
});
