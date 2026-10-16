"use client";

import { useState } from "react";
import { formatDateTime } from "@/lib/format";
import type { DurableEvidence } from "@/lib/types";

function observedTime(value: string): number {
  return /(Z|[+-]\d{2}:\d{2})$/i.test(value) ? Date.parse(value) : Number.NaN;
}

/** Analyze observed sequence without attributing causation or inventing source history. */
export function SituationEvidenceTimeline({ evidence }: { evidence: DurableEvidence[] }) {
  const [source, setSource] = useState("");
  const [quality, setQuality] = useState("");
  const [after, setAfter] = useState("");
  const [before, setBefore] = useState("");
  const [earlierId, setEarlierId] = useState("");
  const [laterId, setLaterId] = useState("");
  const earlier = evidence.find(item => item.evidence_id === earlierId);
  const later = evidence.find(item => item.evidence_id === laterId);
  const validComparison = earlier && later && earlierId !== laterId
    && Number.isFinite(observedTime(earlier.observed_at)) && Number.isFinite(observedTime(later.observed_at))
    && observedTime(earlier.observed_at) <= observedTime(later.observed_at);
  const filtered = evidence.filter(item => (!source || item.source_family === source)
    && (!quality || item.quality === quality)
    && (!after || observedTime(item.observed_at) >= Date.parse(after))
    && (!before || observedTime(item.observed_at) <= Date.parse(before)))
    .sort((a, b) => {
      const left = observedTime(a.observed_at), right = observedTime(b.observed_at);
      if (!Number.isFinite(left)) return Number.isFinite(right) ? 1 : 0;
      if (!Number.isFinite(right)) return -1;
      return right - left;
    });
  const referenceDifference = (left: DurableEvidence, right: DurableEvidence) => {
    const others = new Set(right.resource_ids.map(id => id.toLowerCase()));
    return Array.from(new Set(left.resource_ids.filter(id => !others.has(id.toLowerCase()))));
  };
  return <section className="card timeline-card" aria-labelledby="timeline-heading">
    <div className="card-header"><div><h2 id="timeline-heading">Evidence timeline</h2>
      <p>Exact observed timestamps from durable source records. Sequence and reference differences do not establish causation or infrastructure changes.</p>
    </div></div>
    <div className="card-body">
      <div className="form-grid">
        <label className="form-field"><span>Timeline source</span><select className="form-control" value={source} onChange={event => setSource(event.target.value)}>
          <option value="">All sources</option>{Array.from(new Set(evidence.map(item => item.source_family))).sort().map(value => <option key={value}>{value}</option>)}
        </select></label>
        <label className="form-field"><span>Timeline quality</span><select className="form-control" value={quality} onChange={event => setQuality(event.target.value)}>
          <option value="">All qualities</option>{Array.from(new Set(evidence.map(item => item.quality))).sort().map(value => <option key={value}>{value}</option>)}
        </select></label>
        <label className="form-field"><span>Observed after (local time)</span><input className="form-control" type="datetime-local" value={after} onChange={event => setAfter(event.target.value)} /></label>
        <label className="form-field"><span>Observed before (local time)</span><input className="form-control" type="datetime-local" value={before} onChange={event => setBefore(event.target.value)} /></label>
      </div>
      <p>{filtered.length} of {evidence.length} observed records. Time filters exclude unknown timestamps.</p>
      {after && before && Date.parse(after) > Date.parse(before) && <p role="alert">The observed-after boundary is later than the observed-before boundary.</p>}
      <div className="timeline" aria-label="Filtered observed events">
        {filtered.map(item => <div className="timeline-event" key={item.evidence_id}>
          <span className="timeline-marker" aria-hidden="true" />
          <time dateTime={item.observed_at}>{formatDateTime(item.observed_at)}</time>
          <div style={{ gridColumn: "-2 / -1" }}>
            <strong>{item.source_family}</strong><span>{item.assertion || item.source_object_id}</span>
            <span>{item.quality} · {item.freshness} · <code>{item.evidence_id}</code></span>
          </div>
        </div>)}
        {!filtered.length && <p>No observed evidence matches these timeline filters.</p>}
      </div>
      <h3>Compare two observations</h3>
      <div className="form-grid">{([
        ["Earlier evidence", earlierId, setEarlierId], ["Later evidence", laterId, setLaterId],
      ] as const).map(([label, value, update]) => <label className="form-field" key={label}><span>{label}</span>
        <select className="form-control" value={value} onChange={event => update(event.target.value)}>
          <option value="">Select observed evidence</option>{evidence.map(item => <option value={item.evidence_id} key={item.evidence_id}>
            {item.source_family} · {formatDateTime(item.observed_at)} · {item.evidence_id}
          </option>)}
        </select>
      </label>)}</div>
      {earlier && later && (!validComparison
        ? <p role="alert">Choose two distinct records with known timestamps in chronological order.</p>
        : <div aria-label="Observed evidence comparison">
          <p>{observedTime(earlier.observed_at) === observedTime(later.observed_at)
            ? "Coincident timestamps; no ordering can be established."
            : "Observed sequence only, not a causal conclusion."}</p>
          <dl><dt>Earlier observation</dt><dd>{earlier.assertion || earlier.source_object_id} · {earlier.source_family} · {earlier.quality} · {earlier.freshness}</dd>
            <dt>Later observation</dt><dd>{later.assertion || later.source_object_id} · {later.source_family} · {later.quality} · {later.freshness}</dd>
            <dt>Resource references only in earlier observation</dt><dd>{referenceDifference(earlier, later).join(", ") || "None"}</dd>
            <dt>Resource references only in later observation</dt><dd>{referenceDifference(later, earlier).join(", ") || "None"}</dd>
          </dl>
        </div>)}
    </div>
  </section>;
}
