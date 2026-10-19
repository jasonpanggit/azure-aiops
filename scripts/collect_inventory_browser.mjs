#!/usr/bin/env node
/**
 * Read-only CDP capture of the real signed-in inventory UI. Uses Node 22 only;
 * never imports tokens, creates credentials, or submits a refresh/approval.
 */
import { createHash } from "node:crypto";
import { writeFile } from "node:fs/promises";
import { parseArgs } from "node:util";

const { values } = parseArgs({ options: {
  cdp: { type: "string" }, web: { type: "string" }, "api-origin": { type: "string" },
  subscription: { type: "string" }, generation: { type: "string" }, output: { type: "string" },
} });
for (const key of ["cdp", "web", "api-origin", "subscription", "generation", "output"]) {
  if (!values[key]) throw new Error(`Missing --${key}`);
}
const cdp = new URL(values.cdp);
if (!["127.0.0.1", "localhost", "[::1]"].includes(cdp.hostname) || cdp.protocol !== "http:") {
  throw new Error("CDP must be a loopback HTTP endpoint");
}
const web = new URL(values.web);
const api = new URL(values["api-origin"]);
if ([web, api].some(url => url.protocol !== "https:" || url.username || url.password)) {
  throw new Error("Web/API must be explicit HTTPS origins");
}
function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])]));
  }
  return value;
}
const digest = value => createHash("sha256").update(JSON.stringify(canonical(value))).digest("hex");
const record = {
  schema: "inventory-browser-v1", collected_at: new Date().toISOString(),
  web_origin: web.origin, api_origin: api.origin, families: {},
  screen_reader_acceptance: "unproved", collection_status: "blocked",
};
let socket;
let target;
let timer;
const pending = new Map();
let sequence = 0;
function call(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++sequence;
    const timeout = setTimeout(() => { pending.delete(id); reject(new Error("cdp_timeout")); }, 15000);
    pending.set(id, { resolve, reject, timeout });
    socket.send(JSON.stringify({ id, method, params }));
  });
}
let endpoint;
let responses = [];
try {
  const response = await fetch(new URL("/json/new?about:blank", cdp), {
    method: "PUT", signal: AbortSignal.timeout(5000),
  });
  if (!response.ok) throw new Error("cdp_target_unavailable");
  target = await response.json();
  socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    timer = setTimeout(() => reject(new Error("cdp_connect_timeout")), 5000);
    socket.addEventListener("open", () => { clearTimeout(timer); resolve(); }, { once: true });
    socket.addEventListener("error", () => reject(new Error("cdp_connect_failed")), { once: true });
  });
  socket.addEventListener("message", event => {
    const message = JSON.parse(String(event.data));
    if (message.id) {
      const item = pending.get(message.id);
      if (!item) return;
      clearTimeout(item.timeout);
      pending.delete(message.id);
      if (message.error) item.reject(new Error("cdp_command_failed"));
      else item.resolve(message.result);
    }
    if (message.method === "Fetch.requestPaused") {
      const request = message.params.request;
      const url = new URL(request.url);
      const blocked = url.pathname.startsWith("/api/v1/") && request.method !== "GET";
      void call(blocked ? "Fetch.failRequest" : "Fetch.continueRequest",
        { requestId: message.params.requestId, ...(blocked ? { errorReason: "BlockedByClient" } : {}) })
        .catch(() => { record.interception_failure = true; });
    }
    if (message.method === "Network.responseReceived") {
      const { response, requestId } = message.params;
      const url = new URL(response.url);
      if (url.pathname === `/api/v1/inventory/${endpoint}`) {
        responses.push({ requestId, origin: url.origin, status: response.status });
      }
    }
  });
  await call("Network.enable");
  await call("Page.enable");
  await call("Fetch.enable", { patterns: [{ urlPattern: "*/api/v1/*", requestStage: "Request" }] });
  for (const [family, tab] of [["os", "os"], ["software", "software"], ["paas", "azure"], ["resources", null]]) {
    endpoint = family;
    responses = [];
    const url = new URL(tab ? "/inventory" : "/inventory/assets", web);
    url.searchParams.set("subscription", values.subscription);
    if (tab) {
      url.searchParams.set("subscriptionFilter", values.subscription);
      url.searchParams.set("tab", tab);
      for (const prefix of ["os", "software", "azure"]) url.searchParams.set(`${prefix}PageSize`, "25");
    }
    await call("Page.navigate", { url: url.href });
    const deadline = Date.now() + 30000;
    let capture;
    while (Date.now() < deadline) {
      await new Promise(resolve => setTimeout(resolve, 500));
      const item = responses.at(-1);
      if (!item || item.status !== 200 || item.origin !== api.origin) continue;
      let payload;
      try {
        const result = await call("Network.getResponseBody", { requestId: item.requestId });
        payload = JSON.parse(result.base64Encoded ? Buffer.from(result.body, "base64").toString() : result.body);
      } catch { continue; }
      const data = payload.data;
      const rows = data?.resources ?? data?.groups;
      const scope = { subscription: [values.subscription.toLowerCase()] };
      if (!Array.isArray(rows) || data.generation_id !== values.generation ||
        digest(payload.scope) !== digest(scope) || digest(data.requested_scope) !== digest(scope) ||
        payload.pagination?.offset !== 0 || payload.pagination?.limit !== 25) continue;
      const body = await call("Runtime.evaluate", {
        expression: "({text:document.body.innerText,origin:location.origin,path:location.pathname})",
        returnByValue: true,
      });
      const rendered = body.result?.value;
      if (!rendered || rendered.origin !== web.origin ||
        rendered.path !== (tab ? "/inventory" : "/inventory/assets")) continue;
      const labels = rows.map(row => row.resource_name || row.os_name || row.software_name || row.resource_type || "");
      const matches = rows.length
        ? labels.every(label => label && rendered.text.includes(label))
        : /No matching|unavailable|not available|No .* observations/i.test(rendered.text);
      if (!matches) continue;
      capture = {
        scope, generation_id: data.generation_id, query_version: data.query_version,
        pagination: payload.pagination, rows_sha256: digest(rows),
        rendered_rows_match: true, visible_text_sha256: digest(rendered.text),
        page_rows: rows.length, captured_at: new Date().toISOString(),
      };
      break;
    }
    if (capture) record.families[family] = capture;
    else record.families[family] = { status: "blocked", reason: "authenticated_matching_page_not_observed" };
  }
  record.collection_status = Object.values(record.families).every(row => row.rendered_rows_match) &&
    !record.interception_failure ? "observed" : "blocked";
} catch {
  record.failure_code = "browser_or_authenticated_context_unavailable";
} finally {
  clearTimeout(timer);
  for (const item of pending.values()) clearTimeout(item.timeout);
  socket?.close();
  if (target?.id) {
    await fetch(new URL(`/json/close/${encodeURIComponent(target.id)}`, cdp),
      { signal: AbortSignal.timeout(5000) }).catch(() => {});
  }
  await writeFile(values.output, `${JSON.stringify(record, null, 2)}\n`, { mode: 0o600 });
}
process.exitCode = record.collection_status === "observed" ? 0 : 1;
