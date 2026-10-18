import { createHash, webcrypto } from "node:crypto";
import { afterEach, describe, expect, it, vi } from "vitest";
import { verifyAuditCapture, type AuditCaptureDetail } from "./audit-exports";

const content = '{"label":"Café"}\n';
const detail: AuditCaptureDetail = {
  content, redaction: "standard_secret_keys",
  manifest: {
    export_id: "a".repeat(32), kind: "identity", captured_at: "", generated_at: "", observed_at: "",
    size_bytes: Buffer.byteLength(content), warning_count: 0,
    sha256: createHash("sha256").update(content).digest("hex"),
  },
};

describe("retained audit exact-byte verification", () => {
  afterEach(() => vi.unstubAllGlobals());
  it("verifies UTF-8 bytes including the final newline, not JS character count", async () => {
    vi.stubGlobal("crypto", webcrypto);
    expect(detail.content.length).not.toBe(detail.manifest.size_bytes);
    await expect(verifyAuditCapture(detail)).resolves.toBeUndefined();
  });
  it("rejects mismatched byte count and same-size tampering", async () => {
    vi.stubGlobal("crypto", webcrypto);
    await expect(verifyAuditCapture({ ...detail, content: content.trim() })).rejects.toThrow("byte count");
    await expect(verifyAuditCapture({ ...detail, content: content.replace("label", "LABEL") })).rejects.toThrow("checksum");
  });
  it("fails closed without browser crypto", async () => {
    vi.stubGlobal("crypto", undefined);
    await expect(verifyAuditCapture(detail)).rejects.toThrow("cannot verify");
  });
});
