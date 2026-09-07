import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const navigation = vi.hoisted(() => ({
  pathname: "/exposure",
  params: new URLSearchParams(),
  suspend: false,
}));

vi.mock("next/navigation", () => ({
  usePathname: () => navigation.pathname,
  useSearchParams: () => {
    if (navigation.suspend) {
      throw new Promise(() => undefined);
    }
    return navigation.params;
  },
}));

import ExposureLayout from "./layout";

function renderLayout() {
  return render(
    <ExposureLayout>
      <main>Exposure content</main>
    </ExposureLayout>,
  );
}

describe("ExposureLayout", () => {
  beforeEach(() => {
    navigation.pathname = "/exposure";
    navigation.params = new URLSearchParams();
    navigation.suspend = false;
  });

  it("renders an accessible fallback while route search parameters resolve", () => {
    navigation.suspend = true;

    renderLayout();

    expect(screen.getByRole("status")).toHaveTextContent("Loading exposure view…");
    expect(screen.queryByText("Exposure content")).not.toBeInTheDocument();
  });

  it.each([
    ["/exposure", "Overview"],
    ["/exposure/defender-posture", "Defender posture"],
    ["/exposure/patch-priorities", "Patch priorities"],
  ])("marks only %s as the current ordinary navigation link", (pathname, label) => {
    navigation.pathname = pathname;
    renderLayout();

    const nav = screen.getByRole("navigation", { name: "Exposure views" });
    const links = screen.getAllByRole("link");

    expect(nav).toContainElement(screen.getByRole("link", { name: label }));
    expect(links).toHaveLength(3);
    expect(links.filter((link) => link.getAttribute("aria-current") === "page")).toEqual([
      screen.getByRole("link", { name: label }),
    ]);
    for (const link of links) {
      expect(link).not.toHaveAttribute("role", "tab");
      expect(link).not.toHaveAttribute("aria-selected");
      expect(link).not.toHaveAttribute("tabindex", "-1");
    }
  });

  it("keeps every view link in sequential keyboard focus order", async () => {
    const user = userEvent.setup();
    renderLayout();

    await user.tab();
    expect(screen.getByRole("link", { name: "Overview" })).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("link", { name: "Defender posture" })).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("link", { name: "Patch priorities" })).toHaveFocus();
  });

  it.each(["/exposure/cves/CVE-2026-0001", "/exposure/kbs/KB600001"])(
    "defaults direct detail route %s to Patch priorities",
    (pathname) => {
      navigation.pathname = pathname;
      renderLayout();

      expect(screen.getByRole("link", { name: "Patch priorities" })).toHaveAttribute(
        "aria-current",
        "page",
      );
    },
  );

  it.each([
    ["/exposure/defender-posture", "Defender posture"],
    ["/exposure/patch-priorities", "Patch priorities"],
  ])("uses canonical detail origin %s", (origin, label) => {
    navigation.pathname = "/exposure/cves/CVE-2026-0001";
    navigation.params = new URLSearchParams({ origin });
    renderLayout();

    expect(screen.getByRole("link", { name: label })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it.each([
    "https://evil.example/exposure/defender-posture",
    "/exposure",
    "/exposure/defender-posture/../patch-priorities",
    "defender-posture",
  ])("rejects non-canonical detail origin %s", (origin) => {
    navigation.pathname = "/exposure/kbs/KB600001";
    navigation.params = new URLSearchParams({ origin });
    renderLayout();

    expect(screen.getByRole("link", { name: "Patch priorities" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getAllByRole("link").filter((link) => link.hasAttribute("aria-current"))).toHaveLength(1);
  });
});
