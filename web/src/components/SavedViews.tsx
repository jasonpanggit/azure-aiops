"use client";

import Link from "next/link";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { savedViewsApi } from "@/lib/services";
import { scopeToSearchParams, type ScopeSelection } from "@/lib/scope";
import { savedViewHref, type SavedView, type SavedViewCollection, type SavedViewSettings } from "@/lib/saved-views";

interface Props {
  scope: ScopeSelection;
  current: SavedViewSettings;
  atFirstPage: boolean;
  onRestoreCurrent: () => void;
}

/** On-demand personal view recovery, isolated to the exact selected scope. */
export function SavedViews(props: Props) {
  const { scope, current } = props;
  const params = scopeToSearchParams(scope);
  params.sort();
  return <SavedViewsWorkspace key={`${current.kind}:${params}`} {...props} />;
}

function SavedViewsWorkspace(props: Props) {
  const { current } = props;
  const [open, setOpen] = useState(false);
  const title = current.kind === "search" ? "Saved search views" : "Saved triage views";
  return <section className="card saved-views" aria-label={title}>
    <div className="card-header">
      <div><h2>{title}</h2><p>Personal to your account and exact selected scope. Restoring fetches current evidence, not saved results.</p></div>
      <button type="button" className="button button-secondary" aria-expanded={open} onClick={() => setOpen(value => !value)}>
        {open ? "Close saved views" : "Open saved views"}
      </button>
    </div>
    {open && <SavedViewsPanel {...props} />}
  </section>;
}

function SavedViewsPanel({ scope, current, atFirstPage, onRestoreCurrent }: Props) {
  const [collection, setCollection] = useState<SavedViewCollection | null>(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const request = useRef<AbortController | null>(null);
  const id = useId();
  const currentReady = current.kind !== "search" || current.query.trim().length > 0;
  const views = collection?.views.filter(view => view.kind === current.kind) ?? [];

  const reload = useCallback(async () => {
    if (request.current) return;
    const controller = new AbortController();
    request.current = controller;
    setBusy(true); setError(""); setNotice(""); setCollection(null);
    try {
      const response = await savedViewsApi.read(scope, { signal: controller.signal });
      if (!controller.signal.aborted) setCollection(response.data);
    } catch (reason) {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Saved views could not be read.");
    } finally {
      if (!controller.signal.aborted) { request.current = null; setBusy(false); }
    }
  }, [scope]);

  useEffect(() => {
    void reload();
    return () => { request.current?.abort(); request.current = null; };
  }, [reload]);

  async function replace(next: SavedView[], message: string) {
    if (!collection || request.current) return;
    const controller = new AbortController();
    request.current = controller;
    setBusy(true); setError(""); setNotice("");
    try {
      const response = await savedViewsApi.replace(scope, collection.revision, next, { signal: controller.signal });
      if (!controller.signal.aborted) { setCollection(response.data); setNotice(message); }
    } catch (reason) {
      if (!controller.signal.aborted) {
        setCollection(null);
        setError(`${reason instanceof Error ? reason.message : "Update failed."} The update was not confirmed. Reload saved views before explicitly retrying.`);
      }
    } finally {
      if (!controller.signal.aborted) { request.current = null; setBusy(false); }
    }
  }

  return <div className="card-body saved-views-body" aria-busy={busy}>
    <p>Up to 20 Search and Situation views combined. Saved filters grant no access, schedule no searches, and retain no evidence, selection, approval or SLA. Avoid secrets in query text.</p>
    {error && <p role="alert">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    {busy && <p role="status">Loading or saving personal views...</p>}
    <button type="button" className="button button-secondary" disabled={busy} onClick={() => void reload()}>Reload saved views</button>
    {collection && <>
      <p>Revision {collection.revision}. {views.length} saved {views.length === 1 ? "view" : "views"} for this page; {collection.views.length}/20 total.
        {" "}{collection.updated_at ? `Last saved ${collection.updated_at}.` : "No views saved yet."}</p>
      <p>Save the {current.kind === "search" ? "submitted query and facets" : "current triage filters"}. Restoring always starts at the first page.</p>
      {!currentReady && <p>Submit a nonblank search query before saving or replacing a view.</p>}
      <form className="saved-views-form" onSubmit={event => {
        event.preventDefault();
        if (!busy && collection.views.length < 20 && name.trim() && currentReady) {
          void replace([...collection.views, { ...current, view_id: crypto.randomUUID(), name: name.trim() }], "View saved. No source query was performed.");
        }
      }}>
        <label className="form-field" htmlFor={`${id}-name`}>New view name
          <input className="form-control" id={`${id}-name`} value={name} maxLength={80} required
            disabled={busy} onChange={event => setName(event.target.value)} />
        </label>
        <button type="submit" className="button button-primary" disabled={busy || !currentReady || !name.trim() || collection.views.length >= 20}>Save current view</button>
      </form>
      {views.length ? <ul className="saved-views-list">{views.map(view => <li key={view.view_id}>
        <div>
          <Link href={savedViewHref(view, scope)} onClick={event => {
            if (atFirstPage && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey &&
                event.button === 0 && savedViewHref(view, scope) === savedViewHref(current, scope)) {
              event.preventDefault();
              onRestoreCurrent();
            }
          }}>{view.name}</Link>
          <p>{view.query || "All authorized situations"}</p>
          <details><summary>Saved filters</summary><dl>
            {Object.entries(view).filter(([key]) => !["view_id", "name", "kind", "query"].includes(key)).map(([key, value]) =>
              <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd>{value === null || value === "" ? "Not selected" : String(value)}</dd></div>)}
          </dl></details>
        </div>
        <div className="saved-views-actions">
          <button type="button" className="button button-secondary" disabled={busy || !currentReady}
            aria-label={`Replace ${view.name} with current filters`}
            onClick={() => void replace(collection.views.map(row => row.view_id === view.view_id ? { ...current, view_id: view.view_id, name: view.name } : row), "View filters replaced. No source query was performed.")}>Replace with current filters</button>
          <button type="button" className="button button-ghost" disabled={busy} aria-label={`Delete saved view ${view.name}`}
            onClick={() => void replace(collection.views.filter(row => row.view_id !== view.view_id), "Saved view deleted. Source records were not changed.")}>Delete view</button>
        </div>
      </li>)}</ul> : <p>No saved views for this page in the exact selected scope.</p>}
    </>}
  </div>;
}
