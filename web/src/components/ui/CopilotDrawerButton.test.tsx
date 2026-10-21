import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CopilotDrawerButton } from "./CopilotDrawerButton";

describe("CopilotDrawerButton", () => {
  it("is an icon-first accessible launcher with a tooltip", () => {
    const onClick = vi.fn();
    render(<CopilotDrawerButton onClick={onClick} label="Ask about this page" />);
    const button = screen.getByRole("button", { name: "Ask about this page" });
    expect(button).toHaveClass("button", "button-ai", "copilot-drawer-trigger");
    expect(button).toHaveAttribute("title", "Ask about this page");
    fireEvent.click(button);
    expect(onClick).toHaveBeenCalledOnce();
  });
});
