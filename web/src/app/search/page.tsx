"use client";

import { useState } from "react";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { StructuredData } from "@/components/ui/StructuredData";
import { useScope } from "@/lib/scope-context";
import { contextApi, SUPPORTED_SEARCH_PHRASES } from "@/lib/services";
import type { Envelope, SearchResult } from "@/lib/types";

/** Intent-driven search that presents semantic entities instead of raw payloads. */
export default function SearchPage() {
  const { scope } = useScope();
  const [query, setQuery] = useState("");
  const [envelope, setEnvelope] = useState<Envelope<SearchResult> | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

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
        title="Search"
        description="Find business and operational context using governed, supported intents in the current operating scope."
      />
      <div className="search-hero card">
        <div className="search-hero-form">
          <input
            className="form-control"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => event.key === "Enter" && runSearch()}
            placeholder="Find production applications, failed patches, or missing ownership"
          />
          <button type="button" className="button button-primary" onClick={() => runSearch()} disabled={loading || !query.trim()}>
            {loading ? "Searching…" : "Search"}
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

      {error && <StatePanel title="Search could not answer this request" message={error} tone="error" />}
      {!error && loading && <StatePanel title="Searching operational context" message="Applying the intent to the current scope." tone="loading" />}
      {!error && !loading && envelope && (
        <section className="search-results">
          <div className="section-heading">
            <div>
              <h2>{envelope.data.results.length} results</h2>
              <p>Interpreted as <StatusBadge label={envelope.data.intent} tone="info" compact /></p>
            </div>
          </div>
          {envelope.data.results.length === 0 ? (
            <StatePanel title="No matching operational context" message="The request was understood, but no entities matched the current scope." />
          ) : (
            <div className="search-result-grid">
              {envelope.data.results.map((result, index) => (
                <article className="card" key={String(result.id ?? result.name ?? index)}>
                  <div className="card-body"><StructuredData value={result} /></div>
                </article>
              ))}
            </div>
          )}
        </section>
      )}
    </div>
  );
}
