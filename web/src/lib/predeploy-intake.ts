export const ARTIFACT_MAX_BYTES = 2 * 1024 * 1024;
const REDACTED = "[REDACTED]";
const SOURCES = ["terraform_plan", "bicep_what_if", "arm_diff", "github_pull_request", "azure_devops"];
type JsonValue = null | string | number | boolean | JsonValue[] | { [key: string]: JsonValue };
type JsonObject = { [key: string]: JsonValue };

/** Local inspection only; this never transmits or persists artifact values. */
export interface ArtifactInspection {
  payload: JsonObject;
  bytes: number;
  detectedSensitiveValues: number;
  withheldValues: number;
  redactedText: string;
}

function object(value: unknown): value is JsonObject {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function sensitiveName(value: string): boolean {
  return /password|passwd|secret|token|privatekey|connectionstring|authorization|accesskey|accountkey|clientkey|apikey|sharedkey|credential|sharedaccesssignature|^sas$/
    .test(value.toLowerCase().replace(/[^a-z0-9]/g, ""));
}

function validUnicode(value: string): boolean {
  return !Array.from(value).some(char => {
    const code = char.codePointAt(0)!;
    return code >= 0xd800 && code <= 0xdfff;
  });
}

function uniqueKeys(text: string) {
  const stack: (Set<string> | null)[] = [];
  let start = -1, escaped = false;
  for (let index = 0; index < text.length; index++) {
    const char = text[index];
    if (start >= 0) {
      if (escaped) { escaped = false; continue; }
      if (char === "\\") { escaped = true; continue; }
      if (char !== '"') continue;
      let next = index + 1;
      while (/\s/.test(text[next] ?? "") && next < text.length) next++;
      if (text[next] === ":") {
        const key: unknown = JSON.parse(text.slice(start, index + 1));
        const keys = stack.at(-1);
        if (typeof key === "string" && keys) {
          if (keys.has(key)) throw new Error("Duplicate JSON object keys are not supported.");
          keys.add(key);
        }
      }
      start = -1;
    } else if (char === '"') start = index;
    else if (char === "{" || char === "[") {
      stack.push(char === "{" ? new Set() : null);
      if (stack.length > 25) throw new Error("Artifact exceeds the 24-level structural limit.");
    }
    else if (char === "}" || char === "]") stack.pop();
  }
}

/** Validate a bounded source envelope and prepare explicit, reviewable local redaction. */
export function inspectArtifact(source: string, text: string): ArtifactInspection {
  if (!SOURCES.includes(source)) throw new Error("Unsupported change source.");
  const bytes = new TextEncoder().encode(text).length;
  if (bytes > ARTIFACT_MAX_BYTES) throw new Error("Artifact exceeds the 2 MiB UTF-8 limit.");
  let parsed: unknown;
  try { parsed = JSON.parse(text); }
  catch { throw new Error("The artifact is not valid JSON. Paste or choose a JSON plan or what-if result."); }
  uniqueKeys(text);
  if (!object(parsed)) throw new Error("The artifact must be a JSON object.");
  let nodes = 0, detectedSensitiveValues = 0, withheldValues = 0;

  function visit(value: JsonValue, depth: number, mask?: JsonValue, credential = false, metadata = false): JsonValue {
    if (++nodes > 50000 || depth > 24) throw new Error("Artifact exceeds the 24-level or 50000-value structural limit.");
    if (metadata && value !== null && typeof value !== "boolean" && !object(value) && !Array.isArray(value)) {
      throw new Error("Terraform sensitivity masks must contain only boolean, null, object or array values.");
    }
    if (typeof value === "string") {
      if (!validUnicode(value)) throw new Error("Artifact contains invalid Unicode.");
      if (value === REDACTED && !metadata) { withheldValues++; return value; }
    }
    let redact = false;
    if (!metadata && (mask === true || credential) && value !== null && value !== "") {
      detectedSensitiveValues++; redact = true;
    }
    let result = value;
    if (Array.isArray(value)) {
      result = value.map((child, index) => visit(child, depth + 1, Array.isArray(mask) ? mask[index] : undefined, false, metadata));
    } else if (object(value)) {
      const namedCredential = typeof value.name === "string" && sensitiveName(value.name);
      result = Object.fromEntries(Object.entries(value).map(([key, child]) => {
        if (Array.from(key).length > 256) throw new Error("Artifact object keys must be strings of at most 256 characters.");
        if (!validUnicode(key)) throw new Error("Artifact contains invalid Unicode.");
        const isMask = key === "before_sensitive" || key === "after_sensitive";
        const childMask = key === "before" || key === "after"
          ? value[`${key}_sensitive`] ?? (object(mask) ? mask[key] : undefined)
          : object(mask) ? mask[key] : undefined;
        return [key, visit(child, depth + 1, childMask, !isMask && (sensitiveName(key) || (namedCredential && key === "value")), metadata || isMask)];
      }));
    } else if (typeof value === "number" && (!Number.isFinite(value) || (Number.isInteger(value) && !Number.isSafeInteger(value)))) {
      throw new Error("Artifact numbers must be finite and integers must be JavaScript-safe.");
    }
    return redact ? REDACTED : result;
  }

  const redacted = visit(parsed, 0);
  const arrayKey = source === "terraform_plan" ? "resource_changes" : source === "github_pull_request" ? "files" : "changes";
  const arrays: JsonValue[] = Object.hasOwn(parsed, arrayKey) ? [parsed[arrayKey]] : [];
  if ((source === "bicep_what_if" || source === "arm_diff") && Object.hasOwn(parsed, "properties")) {
    if (!object(parsed.properties)) throw new Error("Artifact properties must be an object.");
    if (Object.hasOwn(parsed.properties, "changes")) arrays.push(parsed.properties.changes);
  }
  for (const entries of arrays) {
    if (!Array.isArray(entries) || entries.some(entry => !object(entry))) throw new Error(`Artifact ${arrayKey} must be an array of objects.`);
    if (entries.length > 500) throw new Error("Artifact may contain at most 500 changes or files.");
  }
  return { payload: parsed, bytes, detectedSensitiveValues, withheldValues, redactedText: JSON.stringify(redacted, null, 2) };
}
