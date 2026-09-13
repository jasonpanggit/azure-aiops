"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { StructuredData } from "@/components/ui/StructuredData";
import { useScope } from "@/lib/scope-context";
import { contextApi, SUPPORTED_SEARCH_PHRASES } from "@/lib/services";
import type { Envelope, SearchResult } from "@/lib/types";

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

function navigationFor(record: SearchRecord): { href: string; label: string } {
  const entityType = textValue(record, ["entity_type", "entityType", "kind", "type"], "record");
  const id = textValue(record, ["id", "resource_id", "principal_id", "incident_id", "name"], "");
  const encoded = encodeURIComponent(id);
  const normalized = entityType.toLowerCase();
  if (normalized.includes("incident") || normalized.includes("situation")) {
    return { href: `/situations/${encoded}`, label: "Open situation" };
  }
  if (normalized.includes("vulnerability") || normalized.includes("cve")) {
    return { href: `/exposure/cves/${encoded}`, label: "Open exposure" };
  }
  if (normalized.includes("businessservice") || normalized.includes("business service")) {
    return { href: `/services/${encoded}`, label: "Open service" };
  }
  return { href: `/investigate?type=${encodeURIComponent(entityType)}&value=${encoded}`, label: "Open authorized context" };
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
  const { scope } = useScope();
  const [query, setQuery] = useState(params.get("q") || "");
  const [envelope, setEnvelope] = useState<Envelope<SearchResult> | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  // Other pages (e.g. Identity) deep-link here with a principal or
  // credential identifier via ?q=; run that search once on arrival.
  useEffect(() => {
    const initial = params.get("q");
    if (initial?.trim()) {
      runSearch(initial);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function runSearch(value = query) {
    if (!value.trim()) return;
    setQuery(value);
    setLoading(true);
    setError("");
    setEnvelope(null);
    try {
      setEnvelope(await contextApi.search(value, scope));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Search failed");
    } finally {
      setLoading(false);
    }
  }

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
            onKeyDown={(event) => event.key === "Enter" && runSearch()}
            placeholder="Find production applications, failed patches, or missing ownership"
          />
          <button type="button" className="button button-primary" onClick={() => runSearch()} disabled={loading || !query.trim()}>
            {loading ? "Finding records…" : "Find authorized records"}
          </button>
        </div>
        <div className="search-suggestions">
          <span>Try</span>
          {SUPPORTED_SEARCH_PHRASES.slice(0, 5).map((phrase) => (
            <button type="button" key={phrase} onClick={() => runSearch(phrase)}>
              {phrase}
            </button>
          ))}
        </div>
      </div>

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
              <h2>{recordsFrom(envelope.data).length} authorized records</h2>
              <p>Interpreted as <StatusBadge label={envelope.data.intent} tone="info" compact /></p>
            </div>
          </div>
          {recordsFrom(envelope.data).length === 0 ? (
            <StatePanel title="No authorized records found" message="The request was understood, but no entities matched the current operating scope." />
          ) : (
            <div className="search-result-grid">
              {recordsFrom(envelope.data).map((result, index) => {
                const entityType = textValue(result, ["entity_type", "entityType", "kind", "type"], "Operational record");
                const title = textValue(result, ["title", "name", "display_name", "resource_name", "principal_id", "id"], "Untitled record");
                const id = textValue(result, ["id", "resource_id", "principal_id", "incident_id"], "ID unavailable");
                const navigation = navigationFor(result);
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
        </section>
      )}
    </div>
  );
}
