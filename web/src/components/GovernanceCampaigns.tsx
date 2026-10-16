"use client";

import { useEffect, useRef, useState } from "react";
import { useApi } from "@/hooks/useApi";
import {
  ACCESS_RECOMMENDATIONS, REVIEW_AUDIENCES,
  type AccessCampaign, type AccessCampaignCollection, type AccessCampaignDetail,
  type AccessRecommendation, type CampaignAddress, type CampaignClosure,
  type CampaignCreate, type CampaignDecisionRequest, type ReviewAudience,
} from "@/lib/access-campaigns";
import { downloadEvidenceJson, verifyEvidenceBytes } from "@/lib/audit-exports";
import { formatDateTime, titleize } from "@/lib/format";
import { scopeToSearchParams, type ScopeSelection } from "@/lib/scope";
import { governanceApi } from "@/lib/services";

type Review =
  | { action: "create"; body: CampaignCreate }
  | { action: "decide"; body: CampaignDecisionRequest }
  | { action: "complete" | "cancel"; body: CampaignClosure }
  | { action: "remove"; body: CampaignAddress };

/** Shared review work is isolated by all scope dimensions and mounted only on demand. */
export function GovernanceCampaigns({ scope }: { scope: ScopeSelection }) {
  const query = scopeToSearchParams(scope); query.sort();
  return <Workspace key={query.toString()} scope={scope} />;
}

function Workspace({ scope }: { scope: ScopeSelection }) {
  const [open, setOpen] = useState(false);
  const [readKey, setReadKey] = useState(0);
  return <section className="governance-retained governance-campaigns" aria-label="Access review campaigns">
    <h3>Access review campaigns</h3>
    <p>Assign a reviewer and deadline to frozen observed-principal evidence. Recommendations do not change Azure access, approve execution, or certify complete effective access.</p>
    <button className="button" aria-expanded={open} onClick={() => setOpen(value => !value)}>
      {open ? "Close campaigns" : "Open campaigns"}
    </button>
    {open && <Read key={readKey} scope={scope} reload={() => setReadKey(value => value + 1)} />}
  </section>;
}

function Read({ scope, reload }: { scope: ScopeSelection; reload: () => void }) {
  const result = useApi(signal => governanceApi.campaigns(scope, signal), []);
  if (result.loading) return <p role="status">Reading shared campaign records...</p>;
  if (result.error || !result.data?.data) return <div>
    <p role="alert">{result.error?.message ?? "Campaigns could not be read."} No empty workspace has been substituted.</p>
    <button className="button" onClick={reload}>Reload campaigns</button>
  </div>;
  return <Editor initial={result.data.data} scope={scope} reload={reload} />;
}

function Editor({ initial, scope, reload }: { initial: AccessCampaignCollection; scope: ScopeSelection; reload: () => void }) {
  const [collection, setCollection] = useState(initial);
  const [detail, setDetail] = useState<AccessCampaignDetail | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [audience, setAudience] = useState<ReviewAudience | "">("");
  const [reviewer, setReviewer] = useState("");
  const [deadline, setDeadline] = useState("");
  const [principalId, setPrincipalId] = useState("");
  const [recommendation, setRecommendation] = useState<AccessRecommendation | "">("");
  const [reason, setReason] = useState("");
  const [closeReason, setCloseReason] = useState("");
  const [review, setReview] = useState<Review | null>(null);
  const [busy, setBusy] = useState(false);
  const [blocked, setBlocked] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), []);
  const writable = Number.isSafeInteger(collection.revision) && collection.revision >= 0
    && collection.revision < Number.MAX_SAFE_INTEGER;
  const locked = busy || blocked || !writable;
  const manager = collection.can_manage === true;
  const item = detail?.items.find(row => row.principal_id === principalId);
  const recorded = detail?.decisions.find(row => row.principal_id === principalId);
  const assigned = detail?.campaign.reviewer_subject === collection.current_subject;
  const canDecide = assigned && detail?.campaign.status === "open" && !recorded && !locked;

  function edit(change: () => void) { change(); setReview(null); setNotice(""); }
  function show(value: AccessCampaignDetail | null) {
    setDetail(value); setReview(null); setReason(""); setRecommendation(""); setCloseReason("");
    setPrincipalId(value?.items.find(row => !value.decisions.some(decision => decision.principal_id === row.principal_id))?.principal_id
      ?? value?.items[0]?.principal_id ?? "");
  }
  async function verified(row: AccessCampaign, revision: number, signal: AbortSignal) {
    const response = await governanceApi.campaign(scope, row.campaign_id, signal);
    const value = response.data;
    if (value.revision !== revision || value.campaign.campaign_id !== row.campaign_id
      || value.campaign.source_sha256 !== row.source_sha256) {
      throw new Error("Campaign details do not match the reviewed collection. Reload campaigns.");
    }
    await verifyEvidenceBytes(value.source_content, { sha256: row.source_sha256, size_bytes: row.source_size_bytes });
    return value;
  }
  async function inspect(row: AccessCampaign) {
    if (busy || request.current) return;
    const controller = new AbortController(); request.current = controller;
    setBusy(true); setError(""); setNotice(""); show(null);
    try {
      const value = await verified(row, collection.revision, controller.signal);
      if (!controller.signal.aborted) show(value);
    } catch (failure) {
      if (!controller.signal.aborted) {
        setError(failure instanceof Error ? failure.message : "Campaign evidence could not be verified.");
        setBlocked(true);
      }
    } finally {
      if (!controller.signal.aborted) { request.current = null; setBusy(false); }
    }
  }
  function reviewCreation() {
    if (locked || !manager || !audience || !title.trim() || !reviewer.trim()) return;
    const due = new Date(deadline);
    if (!Number.isFinite(due.valueOf()) || due.valueOf() <= Date.now() || due.valueOf() > Date.now() + 365 * 86400_000) {
      setError("Choose a future deadline within 365 days, in your local timezone."); return;
    }
    setError(""); setReview({ action: "create", body: {
      title: title.trim(), audience, reviewer_subject: reviewer.trim(),
      due_at: due.toISOString(), expected_revision: collection.revision,
    } });
  }
  async function confirm() {
    if (!review || locked || request.current) return;
    const selected = review;
    const controller = new AbortController(); request.current = controller;
    setBusy(true); setError(""); setNotice("");
    let acknowledged = false;
    try {
      const response = selected.action === "create"
        ? await governanceApi.createCampaign(scope, selected.body, controller.signal)
        : selected.action === "decide"
          ? await governanceApi.decideCampaign(scope, selected.body, controller.signal)
          : selected.action === "remove"
            ? await governanceApi.removeCampaign(scope, selected.body, controller.signal)
            : await governanceApi.closeCampaign(scope, selected.action, selected.body, controller.signal);
      if (controller.signal.aborted) return;
      acknowledged = true;
      const next = response.data;
      setCollection(next); show(null);
      const row = selected.action === "create" ? next.campaigns[0]
        : next.campaigns.find(row => row.campaign_id === selected.body.campaign_id);
      if (row) {
        const value = await verified(row, next.revision, controller.signal);
        if (controller.signal.aborted) return;
        show(value);
      }
      if (selected.action === "create") { setTitle(""); setAudience(""); setReviewer(""); setDeadline(""); setCreateOpen(false); }
      setNotice(selected.action === "remove"
        ? "Terminal stored copy removed. Downloaded records and Azure access are unchanged."
        : "Campaign change recorded. Recommendations are advisory; no Azure access was changed.");
    } catch (failure) {
      if (!controller.signal.aborted) {
        setBlocked(true); setReview(null); show(null);
        setError(`${acknowledged ? "Change acknowledged, but record recovery failed. " : ""}${failure instanceof Error ? failure.message : "The campaign operation was not confirmed."} Reload before another action. No request will be replayed automatically.`);
      }
    } finally {
      if (!controller.signal.aborted) { request.current = null; setBusy(false); }
    }
  }
  function download() {
    if (!detail || busy) return;
    try {
      downloadEvidenceJson(JSON.stringify({
        schema_version: 1, recorded_revision: detail.revision, scope: detail.scope,
        campaign: detail.campaign, source_content: detail.source_content, decisions: detail.decisions,
        boundary: "Advisory observed-principal review only; not complete effective access, RBAC mutation or execution approval.",
      }, null, 2) + "\n", `access-review-${detail.campaign.campaign_id}-r${detail.revision}.json`);
      setNotice("Point-in-time review handed to the browser. Check your downloads.");
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Review download could not start."); }
  }

  return <div className="governance-retained-content">
    <p>{collection.campaigns.length}/10 campaigns · Revision {collection.revision}. Deadline status as of {formatDateTime(collection.as_of)}; reload to refresh. No scheduled reminders are sent.</p>
    <p>Shared with authorized readers of this exact scope. Up to 100 captured principals per campaign, 512 KiB source and 6 MiB collection. Standard key redaction is not comprehensive DLP. No automatic expiry, eviction or immutable legal archive.</p>
    {error && <p role="alert">{error}</p>}
    {blocked && <p role="alert">Campaign mutations are locked until explicit reload. Historical records can still be opened.</p>}
    {notice && <p role="status">{notice}</p>}
    <button className="button" disabled={busy} onClick={reload}>Reload campaigns</button>
    {!writable && <p>Read only: this collection has no writable revision.</p>}
    {!manager ? <p>Creating and managing campaigns requires write authority over the entire selected scope. Assigned reviewers can record their own recommendations.</p> : <>
      <button className="button" disabled={busy} aria-expanded={createOpen} onClick={() => {
        setCreateOpen(value => !value); setReview(null);
      }}>{createOpen ? "Close new campaign" : "New campaign"}</button>
      {createOpen && <fieldset className="governance-campaign-form" disabled={locked}>
      <legend>New observed-access campaign</legend>
      <label>Campaign title<input maxLength={160} value={title} onChange={event => edit(() => setTitle(event.target.value))} /></label>
      <label>Review audience<select value={audience} onChange={event => edit(() => setAudience(REVIEW_AUDIENCES.find(value => value === event.target.value) ?? ""))}>
        <option value="">Select an audience</option>{REVIEW_AUDIENCES.map(value => <option key={value} value={value}>{titleize(value)}</option>)}
      </select></label>
      <label>Reviewer authentication subject<input maxLength={4096} value={reviewer} onChange={event => edit(() => setReviewer(event.target.value))} /></label>
      <button className="button" onClick={() => edit(() => setReviewer(collection.current_subject))}>Assign to me</button>
      <label>Review deadline (local time)<input type="datetime-local" value={deadline} onChange={event => edit(() => setDeadline(event.target.value))} /></label>
      <p>Use the exact authenticated subject, not a display name. Assignment is a declaration, not directory validation or a permission grant. Creation acquires new current evidence, not a displayed preview.</p>
      <button className="button" disabled={!audience || !title.trim() || !reviewer.trim() || !deadline || collection.campaigns.length >= 10} onClick={reviewCreation}>Review campaign creation</button>
      </fieldset>}
    </>}
    {collection.campaigns.length === 0 ? <p>No access campaigns in this exact scope.</p> : <ol className="governance-retained-list">
      {collection.campaigns.map(row => <li key={row.campaign_id}>
        <h4>{row.title}</h4>
        <p>{titleize(row.status)}{row.overdue ? " · Overdue" : ""} · {row.decided_count}/{row.item_count} captured principals reviewed · {titleize(row.audience)}</p>
        <p>Assigned subject: {row.reviewer_subject} · Due {formatDateTime(row.due_at)}</p>
        <button className="button" disabled={busy} onClick={() => void inspect(row)}>Open campaign {row.title}</button>
      </li>)}
    </ol>}
    {detail && <div className="governance-campaign-detail">
      <h4>{detail.campaign.title}: captured review</h4>
      <p>Created by {detail.campaign.created_by} at {formatDateTime(detail.campaign.created_at)}. Generated {formatDateTime(detail.campaign.generated_at)}; observed {detail.campaign.observed_at ? formatDateTime(detail.campaign.observed_at) : "Unknown"}. {detail.campaign.warning_count} source warnings preserved.</p>
      <p className="governance-retained-hash">Verified frozen source SHA-256 {detail.campaign.source_sha256}</p>
      <button className="button" disabled={busy} onClick={download}>Download point-in-time review</button>
      <details><summary>Frozen source JSON and warnings</summary><pre className="governance-retained-preview" tabIndex={0}>{detail.source_content}</pre></details>
      <label>Captured principal<select value={principalId} disabled={busy} onChange={event => edit(() => {
        setPrincipalId(event.target.value); setRecommendation(""); setReason("");
      })}>
        {detail.items.map(row => <option key={row.principal_id} value={row.principal_id}>{row.principal_id}{detail.decisions.some(value => value.principal_id === row.principal_id) ? " (reviewed)" : ""}</option>)}
      </select></label>
      {item && <div>
        <p>Observed roles: {item.roles.join(", ") || "None recorded"}. {item.assignment_count} observed assignments · {item.principal_type || "Unknown principal type"}. Privileged signal: {item.privileged ? "Flagged" : "Not flagged"}; stale signal: {item.stale ? "Flagged" : "Not flagged"}.</p>
        <p>Widest observed scope: {item.widest_scope || "Unknown"}. This aggregated principal record is not an individual-role recertification or complete effective-access calculation.</p>
      </div>}
      {recorded ? <p>Recorded {titleize(recorded.recommendation)} by {recorded.actor} at {formatDateTime(recorded.recorded_at)}: {recorded.reason}. Recommendations cannot be overwritten; create a new review if needed.</p> : <>
        {!assigned && <p>Only the assigned authenticated subject {detail.campaign.reviewer_subject} can record recommendations, including when the current viewer is an administrator.</p>}
        <label>Access recommendation<select value={recommendation} disabled={!canDecide} onChange={event => edit(() => setRecommendation(ACCESS_RECOMMENDATIONS.find(value => value === event.target.value) ?? ""))}>
          <option value="">Select a recommendation</option>{ACCESS_RECOMMENDATIONS.map(value => <option key={value} value={value}>{titleize(value)}</option>)}
        </select></label>
        <label>Recommendation rationale<textarea maxLength={1200} value={reason} disabled={!canDecide} onChange={event => edit(() => setReason(event.target.value))} /></label>
        <button className="button" disabled={!canDecide || !recommendation || !reason.trim() || !item} onClick={() => {
          if (recommendation && item) setReview({ action: "decide", body: {
            campaign_id: detail.campaign.campaign_id, expected_revision: collection.revision,
            principal_id: item.principal_id, recommendation, reason: reason.trim(),
          } });
        }}>Review recommendation</button>
      </>}
      {detail.campaign.closure && <p>{titleize(detail.campaign.status)} by {detail.campaign.closure.actor}: {detail.campaign.closure.reason}. Completion means every captured principal was reviewed, not that access was approved or revoked.</p>}
      {manager && (detail.campaign.status === "open" ? <div>
        <label>Campaign closure rationale<textarea value={closeReason} maxLength={1200} disabled={locked} onChange={event => edit(() => setCloseReason(event.target.value))} /></label>
        {(["complete", "cancel"] as const).map(action => <button className="button" key={action}
          disabled={locked || !closeReason.trim() || (action === "complete" && detail.campaign.decided_count !== detail.campaign.item_count)}
          onClick={() => setReview({ action, body: { campaign_id: detail.campaign.campaign_id, expected_revision: collection.revision, reason: closeReason.trim() } })}>
          {action === "complete" ? "Review completion" : "Review cancellation"}
        </button>)}
      </div> : <button className="button" disabled={locked} onClick={() => setReview({ action: "remove", body: { campaign_id: detail.campaign.campaign_id, expected_revision: collection.revision } })}>Review stored-copy removal</button>)}
    </div>}
    {review && <div className="governance-retained-review" role="region" aria-label="Campaign action review">
      <h4>{titleize(review.action)} review at revision {review.body.expected_revision}</h4>
      {review.action === "create" ? <p>Create {review.body.title} from newly composed {titleize(review.body.audience)} evidence. Assign {review.body.reviewer_subject}, due {review.body.due_at}.</p>
        : review.action === "decide" ? <p>{titleize(review.body.recommendation)} for {review.body.principal_id}: {review.body.reason}. This records advice only; it does not change access.</p>
          : review.action === "remove" ? <p>Remove only this terminal stored campaign copy. Downloaded records and source access remain unchanged.</p>
            : <p>{review.body.reason}. {review.action === "complete" ? "All captured principals must be reviewed. Completion is not certification or approval." : "Cancel this campaign without discarding its frozen source or recorded recommendations."}</p>}
      <button className="button button-primary" disabled={locked} onClick={() => void confirm()}>Confirm {review.action === "decide" ? "recommendation" : review.action === "create" ? "campaign creation" : review.action === "remove" ? "stored-copy removal" : review.action === "complete" ? "completion" : "cancellation"}</button>
      <button className="button" disabled={busy} onClick={() => setReview(null)}>Dismiss action review</button>
    </div>}
    {busy && <p role="status">Processing explicit campaign request...</p>}
  </div>;
}
