"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { StructuredData } from "@/components/ui/StructuredData";
import { useScope } from "@/lib/scope-context";
import { SavedViews } from "@/components/SavedViews";
import { contextApi } from "@/lib/services";
import { scopeToSearchParams } from "@/lib/scope";
import type { ScopeSelection } from "@/lib/scope";
import type { Envelope, SearchCapabilities, SearchResult } from "@/lib/types";

type SearchRecord = Record<string, unknown>;

function recordsFrom(result: SearchResult): SearchRecord[] {
  if (Array.isArray(result.results)) return result.results;
  if (Array.isArray(result.items)) return result.items;
  return [];
}

function textValue(record: SearchRecord, keys: string[], fallback = "Not observed"): string {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "string" && value.trim()) return value;
    if (typeof value === "number" || typeof value === "boolean") return String(value);
  }
  return fallback;
}

function navigationFor(record: SearchRecord, scope: ScopeSelection): { href: string; label: string } {
  const entityType = textValue(record, ["entity_type", "entityType", "kind", "type"], "record");
  const id = textValue(record, ["id", "resource_id", "principal_id", "incident_id", "name"], "");
  const encoded = encodeURIComponent(id);
  const normalized = entityType.toLowerCase();
  const params = scopeToSearchParams(scope);
  const scoped = (path: string, label: string) => ({ href: `${path}${params.size ? `?${params}` : ""}`, label });
  if (normalized.includes("incident") || normalized.includes("situation")) {
    return scoped(`/situations/${encoded}`, "Open situation");
  }
  if (normalized.includes("vulnerability") || normalized.includes("cve")) {
    return scoped(`/exposure/cves/${encoded}`, "Open exposure");
  }
  if (normalized.includes("businessservice") || normalized.includes("business service")) {
    return scoped(`/services/${encoded}`, "Open service");
  }
  params.set("type", entityType); params.set("value", id);
  return scoped("/investigate", "Open authorized context");
}

function keyAttributes(record: SearchRecord): Array<[string, string]> {
  const excluded = new Set([
    "id", "name", "title", "display_name", "entity_type", "entityType", "kind", "type",
    "resource_id", "principal_id", "incident_id", "subscription_id", "subscription_connection", "environment",
    "source", "source_engine", "source_table", "freshness", "observed_at", "live_observed_at",
    "ingested_at", "timestamp", "provenance", "properties", "payload_json",
  ]);
  return Object.entries(record)
    .filter(([key, value]) => !excluded.has(key) && value !== null && value !== undefined && typeof value !== "object")
    .slice(0, 4)
    .map(([key, value]) => [key.replaceAll("_", " "), String(value)]);
}

function scopeLabel(scope: Record<string, string[]>): string {
  const values = Object.entries(scope).flatMap(([dimension, entries]) =>
    entries.map((entry) => `${dimension.replaceAll("_", " ")}: ${entry}`),
  );
  return values.join(", ") || "Current authorized scope";
}

/**
 * Operational search that presents semantic entities and exact identity records
 * instead of raw payloads.
 *
 * Copilot disposition (Plan 11-16): `excluded`. Search is a pure
 * navigation/query aggregation surface -- Phase 11 defines no stable retained
 * evidence snapshot contract for search results, so this page renders no shared
 * Copilot launcher and carries no page adapter. Results deep-link to eligible
 * detail pages (situations, exposure, services, guided investigation) where a
 * reviewed adapter carries the evidence instead. Adding a stable retained
 * search-result snapshot later would require promoting this route to
 * `integrated` in the disposition registry (D-03).
 */
export default function SearchPage() {
  return (
    <Suspense fallback={null}>
      <SearchPageContent />
    </Suspense>
  );
}

function SearchPageContent() {
  const params = useSearchParams();
  const router = useRouter();
  const { scope } = useScope();
  const [query, setQuery] = useState(params.get("q") || "");
  const [envelope, setEnvelope] = useState<Envelope<SearchResult> | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [capabilities, setCapabilities] = useState<SearchCapabilities | null>(null);
  const [capabilityError, setCapabilityError] = useState("");
  const requestId = useRef(0);
  const initialQuery = (params.get("q") || "").slice(0, 512);
  const entityType = (params.get("entity_type") || "").slice(0, 128);
  const sourceFilter = (params.get("source") || "").slice(0, 256);
  const requestedOffset = Number(params.get("offset") ?? 0);
  const offset = Number.isSafeInteger(requestedOffset) && requestedOffset >= 0 && requestedOffset <= 100000 ? requestedOffset : 0;

  useEffect(() => {
    let active = true;
    setCapabilities(null);
    setCapabilityError("");
    contextApi.searchCapabilities(scope)
      .then(result => { if (active) setCapabilities(result.data); })
      .catch((reason: unknown) => {
        if (active) setCapabilityError(reason instanceof Error ? reason.message : "Search readiness is unavailable");
      });
    return () => { active = false; };
  }, [scope]);

  function navigateSearch(value: string, patch: { entityType?: string; source?: string; offset?: number } = {}) {
    const trimmed = value.trim();
    if (!trimmed) return;
    const next = scopeToSearchParams(scope);
    next.set("q", trimmed.slice(0, 512));
    const nextType = patch.entityType ?? entityType;
    const nextSource = patch.source ?? sourceFilter;
    if (nextType) next.set("entity_type", nextType);
    if (nextSource) next.set("source", nextSource);
    if (patch.offset) next.set("offset", String(patch.offset));
    if (trimmed === initialQuery && nextType === entityType && nextSource === sourceFilter && (patch.offset ?? 0) === offset) {
      void runSearch(trimmed);
      return;
    }
    router.push(`/search?${next.toString()}`, { scroll: false });
  }

  const runSearch = useCallback(async (value: string) => {
    if (!value.trim()) return;
    const id = ++requestId.current;
    setQuery(value);
    setLoading(true);
    setError("");
    setEnvelope(null);
    try {
      const result = await contextApi.search(value, scope, { offset, limit: 25, entity_type: entityType, source: sourceFilter });
      if (id === requestId.current) setEnvelope(result);
    } catch (reason) {
      if (id === requestId.current) setError(reason instanceof Error ? reason.message : "Search failed");
    } finally {
      if (id === requestId.current) setLoading(false);
    }
  }, [scope, offset, entityType, sourceFilter]);

  useEffect(() => {
    setEnvelope(null);
    setError("");
    setLoading(false);
    setQuery(initialQuery);
    if (initialQuery.trim()) void runSearch(initialQuery);
    return () => { requestId.current += 1; };
  }, [initialQuery, runSearch]);

  return (
    <div className="page-container">
      <PageHeader
        eyebrow="Operational discovery"
        title="Find authorized records"
        description="Use a supported operational intent or an exact identity identifier to find scoped entities, understand how they were interpreted, and open the context you are authorized to see."
      />
      <div className="search-hero card">
        <div className="search-hero-form">
          <input
            className="form-control"
            aria-label="Operational search intent"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => event.key === "Enter" && !event.nativeEvent.isComposing && navigateSearch(query, { entityType: "", source: "" })}
            maxLength={512}
            placeholder="Find production applications, failed patches, or missing ownership"
          />
          <button type="button" className="button button-primary" onClick={() => navigateSearch(query, { entityType: "", source: "" })} disabled={loading || !query.trim()}>
            {loading ? "Finding records…" : "Find authorized records"}
          </button>
        </div>
        <p>Bookmark or share the submitted URL. Results are fetched again using the current authorized scope; the URL never grants access.</p>
        {capabilityError ? <StatePanel title="Search readiness is unavailable" message={capabilityError} tone="error" /> : !capabilities
          ? <p role="status">Checking search prerequisites...</p>
          : <div>
            {(["live", "semantic"] as const).map(mode => <div key={mode} className="search-suggestions">
              <span>{mode === "live" ? "Live resource search" : "Semantic intents"}: {capabilities[mode].state}</span>
              {capabilities[mode].phrases.map(phrase => <button
                type="button" key={phrase} disabled={!capabilities[mode].can_query}
                onClick={() => navigateSearch(phrase, { entityType: "", source: "" })}
              >{phrase}</button>)}
              <span>{capabilities[mode].prerequisite}</span>
            </div>)}
            <p>Exact identity lookup: {capabilities.identity.state}. {capabilities.identity.prerequisite}</p>
          </div>}
      </div>

      <SavedViews scope={scope} current={{ kind: "search", query: initialQuery, entity_type: entityType, source: sourceFilter }}
        atFirstPage={offset === 0} onRestoreCurrent={() => void runSearch(initialQuery)} />

      {envelope && (
        <EvidenceBar
          evidence={envelope.evidence}
          knowledgeVersion={envelope.knowledge_version}
          warnings={envelope.warnings}
        />
      )}

      {error && (
        <StatePanel
          title={error.toLowerCase().includes("supported") ? "Unsupported search intent" : "Search is unavailable"}
          message={error.toLowerCase().includes("supported") ? "This request is not one of the supported operational intents. Choose a supported intent below." : error}
          tone="error"
        />
      )}
      {!error && loading && <StatePanel title="Searching operational context" message="Applying the intent to the current scope." tone="loading" />}
      {!error && !loading && envelope && (
        <section className="search-results">
          <div className="section-heading">
            <div>
              <h2>{envelope.pagination?.total ?? recordsFrom(envelope.data).length} matching authorized records</h2>
              <p>Interpreted as <StatusBadge label={envelope.data.intent} tone="info" compact /></p>
              <p>Facets and totals cover {envelope.data.represented_count ?? recordsFrom(envelope.data).length} represented provider records, not an estate-wide inventory.
                {envelope.data.truncated ? " The source result is truncated; refine the search before treating coverage as complete." : ""}</p>
            </div>
            {envelope.data.facets && <div className="queue-toolbar">
              <label>Entity type<select value={entityType} onChange={event => navigateSearch(initialQuery, { entityType: event.target.value })}>
                <option value="">All represented types</option>
                {Object.entries(envelope.data.facets.entity_type).map(([name, count]) => <option key={name} value={name}>{name} ({count})</option>)}
              </select></label>
              <label>Source<select value={sourceFilter} onChange={event => navigateSearch(initialQuery, { source: event.target.value })}>
                <option value="">All represented sources</option>
                {Object.entries(envelope.data.facets.source).map(([name, count]) => <option key={name} value={name}>{name} ({count})</option>)}
              </select></label>
            </div>}
          </div>
          {recordsFrom(envelope.data).length === 0 ? (
            <StatePanel title="No authorized records found" message="The request was understood, but no entities matched the current operating scope." />
          ) : (
            <div className="search-result-grid">
              {recordsFrom(envelope.data).map((result, index) => {
                const entityType = textValue(result, ["entity_type", "entityType", "kind", "type"], "Operational record");
                const title = textValue(result, ["title", "name", "display_name", "resource_name", "principal_id", "id"], "Untitled record");
                const id = textValue(result, ["id", "resource_id", "principal_id", "incident_id"], "ID unavailable");
                const navigation = navigationFor(result, scope);
                const attributes = keyAttributes(result);
                const source = textValue(result, ["source", "source_engine", "source_table"], envelope.evidence[0]?.source_engine ?? envelope.evidence[0]?.source_table ?? "Source unavailable");
                const freshness = textValue(result, ["freshness", "observed_at", "live_observed_at", "timestamp"], envelope.evidence[0]?.freshness ?? envelope.evidence[0]?.timestamp ?? "Freshness unavailable");
                return (
                <article className="card search-result-card" key={`${id}-${index}`}>
                  <div className="card-body">
                    <div className="search-result-heading">
                      <StatusBadge label={entityType} tone="info" compact />
                      <span className="search-result-scope">{textValue(result, ["subscription_id", "subscription_connection", "environment"], scopeLabel(envelope.scope))}</span>
                    </div>
                    <h3>{title}</h3>
                    <code className="search-result-id" title={id}>{id}</code>
                    <dl className="search-result-facts">
                      <div><dt>Source</dt><dd>{source}</dd></div>
                      <div><dt>Freshness</dt><dd>{freshness}</dd></div>
                      {attributes.map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}
                    </dl>
                    <Link className="button button-secondary search-result-link" href={navigation.href}>{navigation.label} <span aria-hidden="true">→</span></Link>
                    <details className="search-result-raw">
                      <summary>View raw structured data</summary>
                      <StructuredData value={result} />
                    </details>
                  </div>
                </article>
                );
              })}
            </div>
          )}
          {envelope.pagination && <div className="table-footer">
            <span>{recordsFrom(envelope.data).length} loaded of {envelope.pagination.total} matching represented records</span>
            <button type="button" className="button" disabled={offset === 0} onClick={() => navigateSearch(initialQuery, { offset: Math.max(0, offset - 25) })}>Previous results</button>
            <button type="button" className="button" disabled={envelope.pagination.next_offset === null}
              onClick={() => navigateSearch(initialQuery, { offset: envelope.pagination?.next_offset ?? 0 })}>Next results</button>
          </div>}
        </section>
      )}
    </div>
  );
}
