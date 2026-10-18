import { describe, expect, it } from "vitest";
import { ARTIFACT_MAX_BYTES, inspectArtifact } from "./predeploy-intake";

describe("bounded local artifact intake", () => {
  it.each(["terraform_plan", "bicep_what_if", "arm_diff", "github_pull_request", "azure_devops"])("preserves unknowns for %s", source => {
    expect(inspectArtifact(source, "{}").payload).toEqual({});
  });
  it.each(["password", "CLIENT_SECRET", "access-token", "privateKey", "connection_string", "Authorization", "accountKey", "sas", "api_key", "sharedKey", "credentials"])("redacts %s explicitly", key => {
    const inspected = inspectArtifact("terraform_plan", JSON.stringify({ settings: { [key]: "fixture-private-value" } }));
    expect(inspected.detectedSensitiveValues).toBe(1);
    expect(inspected.redactedText).not.toContain("fixture-private-value");
    expect(inspected.payload.settings).toEqual({ [key]: "fixture-private-value" });
    const reviewed = inspectArtifact("terraform_plan", inspected.redactedText);
    expect(reviewed.detectedSensitiveValues).toBe(0);
    expect(reviewed.withheldValues).toBe(1);
  });
  it.each([
    { settings: [{ name: "DB_PASSWORD", value: "fixture-private-value" }] },
    { change: { after: { custom: "fixture-private-value" }, after_sensitive: { custom: true } } },
    { change: { before: [{ custom: "fixture-private-value" }], before_sensitive: [{ custom: true }] } },
    { change: { after: { custom: "fixture-private-value" }, after_sensitive: true } },
  ])("honors environment names and nested Terraform masks", payload => {
    const result = inspectArtifact("terraform_plan", JSON.stringify(payload));
    expect(result.detectedSensitiveValues).toBeGreaterThan(0);
    expect(result.redactedText).not.toContain("fixture-private-value");
    expect(inspectArtifact("terraform_plan", result.redactedText).detectedSensitiveValues).toBe(0);
  });
  it.each(["[]", "null", "42", '"text"', "{", '{"resource_changes":{}}', '{"resource_changes":[1]}',
    '{"value":1e400}', '{"value":9007199254740992}', '{"value":"\\ud800"}',
    '{"change":{"after_sensitive":{"custom":"not-a-mask"}}}'])("rejects invalid JSON or structure: %s", text => {
    expect(() => inspectArtifact("terraform_plan", text)).toThrow();
  });
  it("checks exact UTF-8, node, depth and cardinality boundaries", () => {
    const exact = JSON.stringify({ x: "é".repeat((ARTIFACT_MAX_BYTES - 8) / 2) });
    expect(inspectArtifact("terraform_plan", exact).bytes).toBe(ARTIFACT_MAX_BYTES);
    expect(() => inspectArtifact("terraform_plan", exact + " ")).toThrow("2 MiB");
    inspectArtifact("terraform_plan", JSON.stringify({ resource_changes: Array(500).fill({}) }));
    expect(() => inspectArtifact("terraform_plan", JSON.stringify({ resource_changes: Array(501).fill({}) }))).toThrow("500");
    inspectArtifact("terraform_plan", JSON.stringify({ x: Array(49998).fill(null) }));
    expect(() => inspectArtifact("terraform_plan", JSON.stringify({ x: Array(49999).fill(null) }))).toThrow("50000");
    let nested: object = { x: null };
    for (let index = 0; index < 23; index++) nested = { x: nested };
    inspectArtifact("terraform_plan", JSON.stringify(nested));
    expect(() => inspectArtifact("terraform_plan", JSON.stringify({ x: nested }))).toThrow("24-level");
  });
  it("does not mutate special object keys during local redaction", () => {
    const text = '{"__proto__":{"password":"fixture-private-value"}}';
    const result = inspectArtifact("terraform_plan", text);
    expect(Object.getOwnPropertyDescriptor(JSON.parse(result.redactedText), "__proto__")?.value).toEqual({ password: "[REDACTED]" });
    expect(Object.prototype).not.toHaveProperty("password");
  });
  it("rejects duplicate decoded keys but not identical names in separate objects or string contents", () => {
    expect(() => inspectArtifact("terraform_plan", '{"x":1,"\\u0078":2}')).toThrow("Duplicate");
    expect(() => inspectArtifact("terraform_plan", '{"a":{"x":1,"x":2}}')).toThrow("Duplicate");
    inspectArtifact("terraform_plan", '{"a":{"x":1},"b":{"x":2},"text":"{\\"x\\":1}"}');
  });
});
