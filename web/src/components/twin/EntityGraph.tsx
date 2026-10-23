"use client";

import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import type { TwinEntity, TwinSnapshot } from "@/lib/types";

const RESULT_LIMIT = 30;
const NEIGHBOR_LIMIT = 12;
const EDGE_LIMIT = 32;

function label(value: string, limit = 28): string {
  return value.length > limit ? `${value.slice(0, limit - 3)}...` : value;
}

/** Explore a bounded, keyboard-accessible neighborhood of the loaded Twin only. */
export function EntityGraph({ snapshot, onSelectResource }: {
  snapshot: TwinSnapshot;
  onSelectResource: (id: string) => void;
}) {
  const markerId = useId().replaceAll(":", "");
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState("");
  const [selectedId, setSelectedId] = useState("");
  const canvasRef = useRef<HTMLDivElement>(null);
  const centerGraph = useCallback(() => {
    const canvas = canvasRef.current;
    if (canvas) canvas.scrollLeft = Math.max(0, (canvas.scrollWidth - canvas.clientWidth) / 2);
  }, []);
  useEffect(() => { centerGraph(); }, [selectedId, centerGraph]);
  const byId = useMemo(() => new Map(snapshot.entities.map(entity => [entity.id, entity])), [snapshot]);
  const selected = byId.get(selectedId);
  const kinds = useMemo(() => Array.from(new Set(snapshot.entities.map(entity => entity.kind))).sort(), [snapshot]);
  const results = useMemo(() => {
    const term = query.trim().toLocaleLowerCase();
    return snapshot.entities.filter(entity =>
      (!kind || entity.kind === kind)
      && (!term || `${entity.name} ${entity.id} ${entity.kind}`.toLocaleLowerCase().includes(term))
    ).sort((left, right) => left.id.localeCompare(right.id));
  }, [snapshot, query, kind]);
  const neighborhood = useMemo(() => {
    const links = snapshot.relationships.filter(relationship =>
      (relationship.source === selectedId || relationship.target === selectedId)
      && byId.has(relationship.source) && byId.has(relationship.target)
    ).sort((left, right) => left.id.localeCompare(right.id));
    const neighbors = Array.from(new Set(links.flatMap(link => [link.source, link.target])))
      .filter(id => id !== selectedId).sort();
    const shown = neighbors.slice(0, NEIGHBOR_LIMIT);
    const ids = new Set([selectedId, ...shown]);
    const visibleLinks = links.filter(link => ids.has(link.source) && ids.has(link.target));
    return {
      neighbors: shown.map(id => byId.get(id)!),
      neighborTotal: neighbors.length,
      links: visibleLinks.slice(0, EDGE_LIMIT),
      linkTotal: links.length,
    };
  }, [snapshot, selectedId, byId]);
  const positions = new Map([[selectedId, { x: 420, y: 250 }]]);
  neighborhood.neighbors.forEach((entity, index) => {
    positions.set(entity.id, { x: index < 6 ? 135 : 705, y: 50 + (index % 6) * 80 });
  });
  const rendered = selected ? [selected, ...neighborhood.neighbors] : [];

  function node(entity: TwinEntity) {
    const position = positions.get(entity.id)!;
    return <g
      key={entity.id}
      className="twin-entity-node"
      role="button"
      tabIndex={0}
      aria-label={`Graph node ${entity.name}, ${entity.kind.replaceAll("_", " ")}`}
      aria-pressed={entity.id === selectedId}
      transform={`translate(${position.x - 120} ${position.y - 26})`}
      onClick={() => setSelectedId(entity.id)}
      onKeyDown={event => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          setSelectedId(entity.id);
        }
      }}
    >
      <title>{entity.name} · {entity.id}</title>
      <rect width="240" height="54" rx="4" />
      <text x="12" y="22">{label(entity.name)}</text>
      <text className="twin-node-kind" x="12" y="41">{label(entity.kind.replaceAll("_", " "))}</text>
    </g>;
  }

  return <section className="card" aria-label="Twin entity explorer">
    <div className="card-header">
      <div><h2>Explore linked entities</h2><p>Search the loaded scope, focus a node and follow its observed relationships.</p></div>
    </div>
    <div className="card-body twin-entity-explorer">
      <div className="twin-entity-search">
        <label>Find entity
          <input type="search" value={query} maxLength={200} onChange={event => setQuery(event.target.value)} placeholder="Name, ID or type" />
        </label>
        <label>Entity type
          <select value={kind} onChange={event => setKind(event.target.value)}>
            <option value="">All types</option>
            {kinds.map(value => <option key={value} value={value}>{value.replaceAll("_", " ")}</option>)}
          </select>
        </label>
        <p className="muted" role="status">Showing {Math.min(results.length, RESULT_LIMIT)} of {results.length} matches in {snapshot.entities.length} loaded entities.</p>
        <div className="twin-entity-results" role="group" aria-label="Matching entities">
          {results.slice(0, RESULT_LIMIT).map(entity => <button
            key={entity.id}
            className="twin-entity-result"
            type="button"
            aria-label={`Explore ${entity.name}, ${entity.id}`}
            aria-pressed={entity.id === selectedId}
            onClick={() => setSelectedId(entity.id)}
          >
            <strong>{entity.name}</strong>
            <span>{entity.kind.replaceAll("_", " ")}</span>
            <small>{entity.id}</small>
          </button>)}
          {results.length === 0 ? <p>No entities match. Clear the search or choose another type.</p> : null}
        </div>
        {query || kind ? <button className="button" type="button" onClick={() => { setQuery(""); setKind(""); }}>Clear entity filters</button> : null}
      </div>
      <div className="twin-entity-detail">
        {!selected ? <div className="twin-entity-empty">
          <h3>Choose an entity to explore</h3>
          <p className="muted">Select an entity to draw its linked neighborhood. Nothing is selected automatically.</p>
          <p>Use the name or type filters to narrow the list, then select a result to review its observed relationships.</p>
        </div> : <>
          <div className="twin-entity-focus" aria-label="Focused entity">
            <h3>{selected.name}</h3>
            <p>{selected.id}</p>
            <p className="muted">{selected.kind.replaceAll("_", " ")} · {selected.confidence} confidence · entity fingerprint {selected.version}</p>
            {selected.kind === "resource" ? <button className="button" type="button" onClick={() => onSelectResource(selected.id)}>Use focused resource for review</button> : null}
          </div>
          <p className="muted" id={`${markerId}-coverage`}>
            Showing {neighborhood.neighbors.length} of {neighborhood.neighborTotal} direct neighbors and {neighborhood.links.length} of {neighborhood.linkTotal} incident links.
            {" "}Arrows preserve source-to-target direction, not causal failure or verified reachability. Filters affect the search list, not the focused neighborhood.
          </p>
          <div className="twin-entity-tools">
            <button className="button" type="button" onClick={centerGraph}>Center focused node</button>
            <span className="muted">Scroll horizontally to follow links, or open relationship details below.</span>
          </div>
          <div ref={canvasRef} className="twin-entity-canvas" role="region" aria-label="Scrollable entity graph" tabIndex={0} aria-describedby={`${markerId}-coverage`}>
            <svg viewBox="0 0 840 500" role="group" aria-label={`Linked neighborhood of ${selected.name}`}>
              <defs><marker id={markerId} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" /></marker></defs>
              {neighborhood.links.map(link => {
                const source = positions.get(link.source)!;
                const target = positions.get(link.target)!;
                if (link.source === link.target) return <path key={link.id}
                  className="twin-entity-self-link"
                  d={`M ${source.x - 45} ${source.y - 27} C ${source.x - 120} ${source.y - 110}, ${source.x + 120} ${source.y - 110}, ${source.x + 45} ${source.y - 30}`}
                  markerEnd={`url(#${markerId})`} />;
                const forward = source.x < target.x;
                return <line key={link.id} x1={source.x + (forward ? 121 : -121)} y1={source.y}
                  x2={target.x + (forward ? -125 : 125)} y2={target.y} markerEnd={`url(#${markerId})`} />;
              })}
              {rendered.map(node)}
            </svg>
          </div>
          {neighborhood.linkTotal === 0 ? <p>No confirmed links to other loaded entities. Unmapped dependencies remain unknown.</p> : null}
          <details className="twin-entity-links">
            <summary>Relationship details ({neighborhood.links.length} displayed)</summary>
            <ul>{neighborhood.links.map(link => <li key={link.id}>
              <button type="button" className="button" onClick={() => setSelectedId(link.source)}>{byId.get(link.source)!.name}</button>
              <span>{link.type.replaceAll("_", " ")} →</span>
              <button type="button" className="button" onClick={() => setSelectedId(link.target)}>{byId.get(link.target)!.name}</button>
              <small>{link.confidence} confidence</small>
            </li>)}</ul>
          </details>
        </>}
      </div>
    </div>
  </section>;
}
