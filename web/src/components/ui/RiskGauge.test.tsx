import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RiskGauge } from "./RiskGauge";

describe("RiskGauge", () => {
  it.each([
    [0, "Low", "#107c10"],
    [25, "Medium", "#8a6100"],
    [50, "High", "#c26400"],
    [75, "Critical", "#b42318"],
    [100, "Critical", "#b42318"],
  ])("keeps risk score %s consistent with its visible and accessible assessment", (score, label, color) => {
    render(<RiskGauge score={score} />);
    const image = screen.getByRole("img", { name: `Risk score: ${score} out of 100, ${label}` });
    expect(image.querySelectorAll("path")[1]).toHaveAttribute("stroke", color);
    expect(screen.getByText(`Risk score · ${label}`)).toBeVisible();
  });

  it.each([
    [0, "Needs attention", "#b42318"],
    [25, "Needs attention", "#b42318"],
    [50, "Fair", "#c26400"],
    [75, "Good", "#8a6100"],
    [100, "Excellent", "#107c10"],
  ])("keeps higher-is-better score %s consistent with its visible and accessible assessment", (score, label, color) => {
    render(<RiskGauge score={score} invert label="Posture" detail="Loaded evidence only" />);
    const image = screen.getByRole("img", { name: `Posture: ${score} out of 100, ${label}` });
    expect(image.querySelectorAll("path")[1]).toHaveAttribute("stroke", color);
    expect(screen.getByText(`Posture · ${label}`)).toBeVisible();
    expect(screen.getByText("Loaded evidence only")).toBeVisible();
  });

  it.each([[-20, 0, "Needs attention"], [120, 100, "Excellent"]])("clamps %s without reversing the assessment", (score, clamped, label) => {
    render(<RiskGauge score={score} invert />);
    expect(screen.getByRole("img", { name: `Risk score: ${clamped} out of 100, ${label}` })).toBeInTheDocument();
  });
});
