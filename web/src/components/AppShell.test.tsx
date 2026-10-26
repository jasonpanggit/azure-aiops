import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AppShell } from "./AppShell";

vi.mock("next/navigation", () => ({ usePathname: () => "/" }));
vi.mock("../lib/services", () => ({
  healthApi: { health: vi.fn().mockResolvedValue({ readiness: "ready" }) },
}));
vi.mock("./AccountMenu", () => ({ AccountMenu: () => <button>Account</button> }));
vi.mock("./ScopeSelector", () => ({ ScopeSelector: () => <button>Scope</button> }));
vi.mock("./RouteScopeBoundary", () => ({
  RouteScopeBoundary: ({ children }: { children: React.ReactNode }) => children,
}));

describe("AppShell navigation keyboard dismissal", () => {
  beforeEach(async () => {
    render(<AppShell><button>Page action</button></AppShell>);
    await waitFor(() => expect(screen.getByText("Knowledge current")).toBeInTheDocument());
  });

  it("connects the disclosure button to the existing navigation landmark", () => {
    const toggle = screen.getByRole("button", { name: "Toggle navigation" });
    const sidebar = screen.getByRole("complementary", { name: "Primary navigation" });
    expect(toggle).toHaveAttribute("aria-controls", sidebar.id);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("link", { name: "Home" })).toHaveAttribute("aria-current", "page");
  });

  it("opens with Enter, closes from a navigation link with Escape and restores focus", async () => {
    const user = userEvent.setup();
    const toggle = screen.getByRole("button", { name: "Toggle navigation" });
    toggle.focus();
    await user.keyboard("{Enter}");
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    screen.getByRole("link", { name: "Services" }).focus();
    await user.keyboard("{Escape}");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveFocus();
    expect(screen.queryByRole("button", { name: "Close navigation" })).not.toBeInTheDocument();
  });

  it("closes with Escape from the toggle and can reopen with Space", async () => {
    const user = userEvent.setup();
    const toggle = screen.getByRole("button", { name: "Toggle navigation" });
    await user.click(toggle);
    await user.keyboard("{Escape}");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await user.keyboard(" ");
    expect(toggle).toHaveAttribute("aria-expanded", "true");
  });

  it.each(["click", "Escape"])("restores focus when the backdrop is dismissed by %s", async (action) => {
    const user = userEvent.setup();
    const toggle = screen.getByRole("button", { name: "Toggle navigation" });
    await user.click(toggle);
    const backdrop = screen.getByRole("button", { name: "Close navigation" });
    if (action === "click") await user.click(backdrop);
    else {
      backdrop.focus();
      await user.keyboard("{Escape}");
    }
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveFocus();
  });

  it("does not consume Escape or move focus when navigation is closed", () => {
    const link = screen.getByRole("link", { name: "Services" });
    link.focus();
    expect(fireEvent.keyDown(link, { key: "Escape" })).toBe(true);
    expect(link).toHaveFocus();
  });

  it("leaves Escape on page controls to their own owner", async () => {
    await userEvent.click(screen.getByRole("button", { name: "Toggle navigation" }));
    const action = screen.getByRole("button", { name: "Page action" });
    action.focus();
    expect(fireEvent.keyDown(action, { key: "Escape" })).toBe(true);
    expect(action).toHaveFocus();
    expect(screen.getByRole("button", { name: "Toggle navigation" })).toHaveAttribute("aria-expanded", "true");
  });

  it("respects Escape already handled by a descendant", async () => {
    const toggle = screen.getByRole("button", { name: "Toggle navigation" });
    await userEvent.click(toggle);
    const link = screen.getByRole("link", { name: "Services" });
    link.addEventListener("keydown", (event) => event.preventDefault(), { once: true });
    fireEvent.keyDown(link, { key: "Escape" });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
  });

  it("does not move desktop navigation focus to a hidden toggle after a resize", async () => {
    const toggle = screen.getByRole("button", { name: "Toggle navigation" });
    await userEvent.click(toggle);
    toggle.style.display = "none";
    const link = screen.getByRole("link", { name: "Services" });
    link.focus();
    expect(fireEvent.keyDown(link, { key: "Escape" })).toBe(true);
    expect(link).toHaveFocus();
  });

  it("retains ordinary navigation-link dismissal without redirecting focus to the toggle", async () => {
    const toggle = screen.getByRole("button", { name: "Toggle navigation" });
    await userEvent.click(toggle);
    const link = screen.getByRole("link", { name: "Services" });
    link.addEventListener("click", (event) => event.preventDefault(), { once: true });
    await userEvent.click(link);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(link).toHaveFocus();
  });
});
