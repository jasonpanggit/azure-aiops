import Link from "next/link";

export interface CopilotLauncherProps {
  /** Free-text context label shown to the user and passed as ?service=. */
  contextLabel?: string;
  /** Context-aware starter questions surfaced as quick links into Copilot. */
  starterQuestions: string[];
}

/**
 * Compact entry point into Operations Copilot for embedding on domain pages
 * (dashboard, network, vulnerabilities, incidents, remediation). Renders a
 * short set of context-aware starter questions that deep-link into the
 * Copilot page, which pre-fills scope from the query string. Keeps the full
 * chat UI centralized in /copilot rather than duplicated per page.
 */
export function CopilotLauncher({ contextLabel, starterQuestions }: CopilotLauncherProps) {
  const suffix = contextLabel ? `&service=${encodeURIComponent(contextLabel)}` : "";
  return (
    <aside className="copilot-launcher">
      <div className="copilot-launcher-header">
        <span className="copilot-launcher-mark">AI</span>
        <div>
          <h3>Ask Operations Copilot</h3>
          <p>Evidence-backed answers scoped to your access.</p>
        </div>
      </div>
      <div className="copilot-launcher-prompts">
        {starterQuestions.map((question) => (
          <Link
            key={question}
            className="copilot-launcher-prompt"
            href={`/copilot?q=${encodeURIComponent(question)}${suffix}`}
          >
            {question}
            <span>→</span>
          </Link>
        ))}
      </div>
    </aside>
  );
}
