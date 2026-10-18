"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { formatDateTime } from "@/lib/format";
import { scopeToSearchParams, type ScopeSelection } from "@/lib/scope";
import { serviceReliabilityApi } from "@/lib/services";
import type { ServiceComponent, ServiceObjectivePolicy, ServiceRequestMetrics } from "@/lib/service-reliability";
import type { Envelope } from "@/lib/types";

const number = (value: number | null, suffix = "") => value === null ? "Unknown" : `${new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(value)}${suffix}`;
const message = (reason: unknown) => reason instanceof Error ? reason.message : "Request could not be confirmed.";

/** Explicit shared targets and measured component requests, isolated from catalog/Copilot state. */
export function ServiceReliability({ scope }: { scope: ScopeSelection }) {
  const key = scopeToSearchParams(scope); key.sort();
  return <Workspace key={key.toString()} scope={scope} />;
}

function Workspace({ scope }: { scope: ScopeSelection }) {
  const [open, setOpen] = useState(false);
  return <section id="component-request-reliability" className="card service-reliability" aria-label="Component request reliability">
    <div className="card-header"><div><h2>Component request reliability</h2><p>Read measured requests against an explicit administrator target, not an incident-derived service health score.</p></div>
      <button type="button" className="button" aria-expanded={open} onClick={() => setOpen(value => !value)}>{open ? "Close request reliability" : "Open request reliability"}</button></div>
    {open && <Panel scope={scope} />}
  </section>;
}

function Panel({ scope }: { scope: ScopeSelection }) {
  const [policy, setPolicy] = useState<ServiceObjectivePolicy | null>(null);
  const [components, setComponents] = useState<ServiceComponent[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [query, setQuery] = useState("");
  const [appliedQuery, setAppliedQuery] = useState("");
  const [selected, setSelected] = useState("");
  const [target, setTarget] = useState("");
  const [window, setWindow] = useState<"" | 1 | 24 | 168>("");
  const [metrics, setMetrics] = useState<Envelope<ServiceRequestMetrics> | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [sourceError, setSourceError] = useState("");
  const [notice, setNotice] = useState("");
  const [confirmRemove, setConfirmRemove] = useState(false);
  const request = useRef<AbortController | null>(null);
  const objective = policy?.objectives.find(row => row.resource_id === selected);
  const component = components.find(row => row.resource_id === selected);

  const reload = useCallback(async () => {
    if (request.current) return;
    const controller = new AbortController(); request.current = controller;
    setBusy(true); setPolicy(null); setComponents([]); setTotal(0); setOffset(0);
    setSelected(""); setTarget(""); setWindow(""); setMetrics(null); setConfirmRemove(false);
    setError(""); setSourceError(""); setNotice(""); setAppliedQuery(""); setQuery("");
    const results = await Promise.allSettled([
      serviceReliabilityApi.objectives(scope, controller.signal),
      serviceReliabilityApi.components(scope, "", 0, controller.signal),
    ]);
    if (controller.signal.aborted) return;
    const [saved, source] = results;
    if (saved.status === "fulfilled") setPolicy(saved.value.data);
    else setError(`Objectives unavailable: ${message(saved.reason)} Reload before changing targets.`);
    if (source.status === "fulfilled") {
      setComponents(source.value.data.components); setTotal(source.value.pagination?.total ?? source.value.data.components.length);
    } else setSourceError(`Component inventory unavailable: ${message(source.reason)} No clean or empty estate is inferred.`);
    request.current = null; setBusy(false);
  }, [scope]);

  useEffect(() => {
    void reload();
    return () => { request.current?.abort(); request.current = null; };
  }, [reload]);

  function choose(identity: string) {
    setSelected(identity); setMetrics(null); setConfirmRemove(false); setNotice(""); setError("");
    const saved = policy?.objectives.find(row => row.resource_id === identity);
    setTarget(saved ? String(saved.success_target_basis_points / 100) : "");
    setWindow(saved?.window_hours ?? "");
  }

  async function search(nextOffset: number, text: string) {
    if (request.current) return;
    const controller = new AbortController(); request.current = controller;
    setBusy(true); setComponents([]); setSourceError(""); setMetrics(null); setSelected(""); setConfirmRemove(false);
    try {
      const response = await serviceReliabilityApi.components(scope, text, nextOffset, controller.signal);
      if (!controller.signal.aborted) {
        setComponents(response.data.components); setTotal(response.pagination?.total ?? response.data.components.length);
        setOffset(nextOffset); setAppliedQuery(text);
      }
    } catch (reason) {
      if (!controller.signal.aborted) { setTotal(0); setSourceError(`Component inventory unavailable: ${message(reason)}`); }
    } finally {
      if (!controller.signal.aborted) { request.current = null; setBusy(false); }
    }
  }

  async function act(kind: "save" | "remove" | "measure") {
    if (!policy || !selected || request.current) return;
    if (kind === "save" && (!window || !/^\d{1,3}(\.\d{1,2})?$/.test(target) || Number(target) <= 0 || Number(target) > 100)) {
      setError("Enter an explicit success target from 0.01% to 100%, with at most two decimal places, and select a window."); return;
    }
    const controller = new AbortController(); request.current = controller;
    setBusy(true); setError(""); setNotice(""); setMetrics(null); setConfirmRemove(false);
    try {
      if (kind === "measure") {
        const response = await serviceReliabilityApi.metrics(scope, selected, controller.signal);
        if (!controller.signal.aborted) setMetrics(response);
      } else {
        let response: Envelope<ServiceObjectivePolicy>;
        if (kind === "remove") response = await serviceReliabilityApi.remove(scope, selected, policy.revision, controller.signal);
        else {
          if (!window) throw new Error("Select an objective window before saving.");
          response = await serviceReliabilityApi.save(scope, {
            resource_id: selected, success_target_basis_points: Math.round(Number(target) * 100), window_hours: window,
          }, policy.revision, controller.signal);
        }
        if (!controller.signal.aborted) {
          setPolicy(response.data); setSelected(""); setTarget(""); setWindow("");
          setNotice(kind === "remove" ? "Declared objective removed. No Azure resource was changed." : "Declared objective saved. No telemetry read, Azure change or execution approval occurred.");
        }
      }
    } catch (reason) {
      if (!controller.signal.aborted) {
        setError(`${message(reason)} ${kind === "measure" ? "No successful measurement is asserted." : "Write outcome is unconfirmed; reload before retrying."}`);
        if (kind !== "measure") setPolicy(null);
      }
    } finally {
      if (!controller.signal.aborted) { request.current = null; setBusy(false); }
    }
  }

  return <div className="card-body">
    <p>Shared only within this exact effective scope. Up to 20 component objectives; no inherited or prefilled target. Administrators may save/remove; readers may recover declarations and query evidence. Source tags declare mappings, not verified service-wide coverage.</p>
    <div className="service-reliability-controls"><button className="button" disabled={busy} onClick={() => void reload()}>Reload reliability workspace</button>{busy && <span role="status">Working…</span>}</div>
    {error && <p role="alert">{error}</p>}{sourceError && <p role="alert">{sourceError}</p>}{notice && <p role="status">{notice}</p>}
    {policy && <p>Objective revision {policy.revision}; {policy.objectives.length}/20 declared. {policy.revision ? <>Last edited by {policy.updated_by} at {formatDateTime(policy.updated_at)}; this is not a full edit history.</> : "No target has been declared."}</p>}
    <form className="service-reliability-controls" onSubmit={event => { event.preventDefault(); void search(0, query); }}>
      <label>Find telemetry component<input value={query} maxLength={256} disabled={busy} onChange={event => setQuery(event.target.value)} /></label>
      <button className="button" disabled={busy} type="submit">Search components</button>
    </form>
    {!busy && !sourceError && <p>{components.length}/{total} matching published components loaded. Missing constrained metadata is excluded; no automatic query or cloud setup is performed.</p>}
    <label className="service-reliability-selection">Published component<select disabled={busy} value={component ? selected : ""} onChange={event => choose(event.target.value)}>
      <option value="">Select a component</option>{components.map(row => <option key={row.resource_id} value={row.resource_id}>{row.resource_name} · {row.business_service || "Unmapped service"} · {row.resource_id}</option>)}
    </select></label>
    {total > 25 && <div className="service-reliability-controls"><button className="button" disabled={busy || offset === 0} onClick={() => void search(Math.max(0, offset - 25), appliedQuery)}>Previous components</button>
      <span>Rows {offset + 1}–{offset + components.length} of {total}</span><button className="button" disabled={busy || offset + components.length >= total} onClick={() => void search(offset + 25, appliedQuery)}>Next components</button></div>}
    {policy && policy.objectives.length > 0 && <details><summary>Review saved objectives ({policy.objectives.length})</summary>
      <ul>{policy.objectives.map(row => <li key={row.resource_id}><button className="button" disabled={busy} onClick={() => choose(row.resource_id)}>Review {row.business_service} · {row.resource_id}</button><p>{row.success_target_basis_points / 100}% request success over {row.window_hours} hours. Current mapping/access is rechecked before every measured read.</p></li>)}</ul>
    </details>}
    {selected && <div className="service-reliability-review">
      <h3>Review this component</h3><p><code>{selected}</code></p>
      <p>{component ? <>Declared service: {component.business_service || "Unmapped; a declared service tag is required to save"}. Inventory observation: {formatDateTime(component.observed_at)}.</> : "Retained declaration selected; its current mapping is not confirmed by this component page."}</p>
      <form onSubmit={event => { event.preventDefault(); void act("save"); }}>
        <fieldset disabled={busy || !policy || !component?.business_service}>
          <legend>Administrator-declared objective</legend>
          <div className="service-reliability-controls"><label>Request success target (%)<input type="number" min="0.01" max="100" step="0.01" required value={target} onChange={event => { setTarget(event.target.value); setMetrics(null); }} /></label>
            <label>Objective window<select required value={window} onChange={event => {
              const next = Number(event.target.value);
              setWindow(next === 1 || next === 24 || next === 168 ? next : ""); setMetrics(null);
            }}>
              <option value="">Select a window</option><option value="1">1 hour</option><option value="24">24 hours</option><option value="168">7 days</option></select></label>
            <button className="button" type="submit" disabled={!window || !target}>Save declared objective</button></div>
        </fieldset>
      </form>
      <p>Measured reads use the saved target, not unsaved form fields. Save or restore the declared values before reading.</p>
      <div className="service-reliability-controls"><button className="button button-primary" disabled={busy || !objective || Math.round(Number(target) * 100) !== objective.success_target_basis_points || window !== objective.window_hours} onClick={() => void act("measure")}>Read measured requests</button>
        <button className="button" disabled={busy || !objective} onClick={() => setConfirmRemove(true)}>Remove declared objective</button></div>
      {!objective && <p>No saved objective for this selection in the exact scope. No target or measurement is assumed.</p>}
      {confirmRemove && <div role="group" aria-label="Confirm objective removal"><p>Remove this declared target at revision {policy?.revision}? No source resource is changed.</p>
        <button className="button" disabled={busy} onClick={() => void act("remove")}>Confirm remove objective</button><button className="button" onClick={() => setConfirmRemove(false)}>Cancel removal</button></div>}
    </div>}
    {metrics && <section aria-label="Measured component requests">
      <h3>Measured component requests</h3><p>{metrics.data.business_service} · policy revision {metrics.data.objective_policy_revision}; declared success target {metrics.data.objective.success_target_basis_points / 100}%.</p>
      <p>Query window: {formatDateTime(metrics.data.window_started_at)} to {formatDateTime(metrics.data.window_finished_at)}. First/last observed requests: {formatDateTime(metrics.data.aggregate.first_observed_at ?? "")} / {formatDateTime(metrics.data.aggregate.last_observed_at ?? "")}.</p>
      <dl className="service-reliability-values"><div><dt>Request success</dt><dd>{number(metrics.data.request_success_percent, "%")}</dd></div>
        <div><dt>Observed-record p95 duration</dt><dd>{number(metrics.data.p95_observed_record_duration_ms, " ms")}</dd></div>
        <div><dt>Allowed failed-request budget</dt><dd>{number(metrics.data.allowed_failed_requests)}</dd></div>
        <div><dt>Remaining failed-request budget</dt><dd>{number(metrics.data.remaining_failed_request_budget)}</dd></div>
        <div><dt>Budget consumed</dt><dd>{number(metrics.data.consumed_budget_percent, "%")}</dd></div></dl>
      <p>{metrics.data.aggregate.record_count} observed records; {metrics.data.aggregate.represented_count} represented requests; {metrics.data.aggregate.failed_count} reported failures.
        {" "}{metrics.data.sampling_estimated ? "Sample-weighted counts are estimates." : "No sampled records reported; instrumentation coverage remains unknown."}</p>
      <p>Quality gaps: {metrics.data.aggregate.unknown_success_records} unknown success; {metrics.data.aggregate.invalid_weight_records} invalid weights; {metrics.data.aggregate.invalid_duration_records} invalid durations; {metrics.data.aggregate.sampled_records} sampled records. A 100% target has zero allowed failures; consumed percentage is undefined. Negative remaining budget is retained, not clamped.</p>
      <p>{metrics.data.interpretation}</p><EvidenceBar evidence={metrics.evidence ?? []} warnings={metrics.warnings ?? []} />
    </section>}
    <p>Reliability evidence is loaded only on request and is not included in the catalog-only Copilot context or existing service brief. Missing telemetry, access, instrumentation and ingestion delay remain unknown; no service uptime, complete coverage or contractual certification is asserted.</p>
  </div>;
}
