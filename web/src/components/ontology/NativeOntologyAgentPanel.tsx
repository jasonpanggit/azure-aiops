"use client";

import { StatePanel } from "@/components/ui/StatePanel";
import { useApi } from "@/hooks/useApi";
import type { ScopeSelection } from "@/lib/scope";
import { ontologyAutomationApi } from "@/lib/services";

const DISCOVERY_PROMPT = "In Plan mode, inspect the bound sources for new tables, columns, schema drift and evidence-backed relationships. Preserve existing stable IDs and intentional inverse relationships. Show the source tables, columns and keys supporting each proposed change, validation results and a draft preview. Do not apply changes.";

/** Native Plan-mode navigation; this component never invokes Foundry or publishes. */
export function NativeOntologyAgentPanel({
  connectionId,
  scope,
}: {
  connectionId: string;
  scope: ScopeSelection;
}) {
  const capabilities = useApi(
    () => ontologyAutomationApi.agentCapabilities(connectionId, scope),
    [connectionId, JSON.stringify(scope)],
  );
  const native = capabilities.data?.data.native_interactive;

  return (
    <section id="ontology-automation-panel" role="tabpanel" aria-labelledby="ontology-automation-tab" tabIndex={0}>
      <h2>Native Fabric Ontology Agent</h2>
      <p>Discover, draft, validate and preview changes in the Fabric agent&apos;s Plan mode. Review the draft before switching to Act to apply it.</p>
      <p>Native querying, proposal authoring and publication are separate capabilities. Unattended native authoring is unavailable; no automatic Foundry fallback is used.</p>
      {capabilities.loading ? (
        <StatePanel title="Loading native entry point" message="Checking the configured target for this authorized connection." tone="loading" />
      ) : capabilities.error ? (
        <StatePanel title="Native entry point is unavailable" message={`${capabilities.error.message} No agent was invoked and Foundry was not selected.`} tone="error" />
      ) : native?.status === "configured_unverified" && native.portal_url ? (
        <>
          <a className="button button-primary" href={native.portal_url} target="_blank" rel="noopener noreferrer">Open native Ontology Agent in Fabric</a>
          <p>This configured link is not a live availability or execution check. Fabric uses your signed-in identity and its own permissions; the application&apos;s selected subscription scope does not constrain the Fabric conversation.</p>
        </>
      ) : (
        <StatePanel
          title={native?.status === "invalid_configuration" ? "Native target configuration is invalid" : "Native target is not configured"}
          message="Configure the explicit native workspace and ontology item. The legacy publisher target is not substituted, and no agent was invoked."
          tone="empty"
        />
      )}
      <h3>Suggested native discovery request</h3>
      <p>Open Ontology agent on the item, keep Plan selected, and submit this request:</p>
      <blockquote>{DISCOVERY_PROMPT}</blockquote>
      <p>Opening the link does not submit this request. Query results do not establish authoring or publication. Conversations are browser-session scoped; retain reviewed results before refreshing.</p>
    </section>
  );
}
