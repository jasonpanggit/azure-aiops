import { describe, expect, it } from "vitest";
import { canPerform, highestRole, type Principal } from "@/lib/permissions";

const reader: Principal = { subject: "r@x.com", grants: [{ role: "reader" }] };
const operator: Principal = { subject: "o@x.com", grants: [{ role: "operator" }] };
const admin: Principal = { subject: "a@x.com", grants: [{ role: "admin" }] };

describe("permissions", () => {
  it("reader can only read", () => {
    expect(canPerform(reader, "read")).toBe(true);
    expect(canPerform(reader, "operate")).toBe(false);
    expect(canPerform(reader, "write")).toBe(false);
  });

  it("operator can read and operate but not write", () => {
    expect(canPerform(operator, "read")).toBe(true);
    expect(canPerform(operator, "operate")).toBe(true);
    expect(canPerform(operator, "write")).toBe(false);
  });

  it("admin can do everything", () => {
    expect(canPerform(admin, "read")).toBe(true);
    expect(canPerform(admin, "operate")).toBe(true);
    expect(canPerform(admin, "write")).toBe(true);
  });

  it("null principal can do nothing", () => {
    expect(canPerform(null, "read")).toBe(false);
  });

  it("highestRole picks the most privileged grant", () => {
    expect(highestRole(null)).toBeNull();
    expect(highestRole(reader)).toBe("reader");
    expect(
      highestRole({ subject: "mix@x.com", grants: [{ role: "reader" }, { role: "admin" }] })
    ).toBe("admin");
  });
});
