import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { InvestigationHypothesisBoard } from "./InvestigationHypothesisBoard";
import type { InvestigationHypothesis, InvestigationTeamWorkspace } from "@/lib/investigation-workspaces";

const HYPOTHESIS: InvestigationHypothesis = {
  hypothesis_id: `hyp-${"b".repeat(32)}`, explanation: "A route change may explain the errors.",
  supporting: [{ source: "Incidents", reference: "inc-7", declared_version: "operator-v1", note: "Timing overlaps" }],
  contradicting: [{ source: "Network", reference: "gap-2", declared_version: "", note: "Some paths unaffected" }],
  unknowns: ["Whether traffic used this route"], disposition: "investigating", rationale: "Needs source confirmation",
  entry_type: "BusinessService", subject: "Original Payments", created_revision: 2, updated_revision: 3,
  actor: "editor", recorded_at: "2026-10-17T06:00:00Z",
};
const workspace = (hypotheses: InvestigationHypothesis[] = [], overrides: Partial<InvestigationTeamWorkspace> = {}): InvestigationTeamWorkspace => ({
  workspace_id: `wrk-${"a".repeat(32)}`, owner: "owner", scope: {}, latest_revision: 3,
  revision: {
    revision: 3, actor: "editor", recorded_at: HYPOTHESIS.recorded_at, change: "hypothesis_updated",
    view: { title: "Review", entry_type: "BusinessService", subject: "Different current subject", mode: "engineer" },
    readers: [], editors: ["editor"], hypotheses,
  },
  current_access: { readers: [], editors: ["editor"] }, can_edit: true, can_share: false,
  history: [], ...overrides,
});

describe("operator hypothesis board", () => {
  it("is explicitly empty and unverified, without running an operation", () => {
    const save = vi.fn();
    render(<InvestigationHypothesisBoard workspace={workspace()} busy={false} onSave={save} />);
    expect(screen.getByText(/No explanations proposed in this revision/)).toBeInTheDocument();
    expect(screen.getByText(/not fetched, validated or retained evidence/)).toBeInTheDocument();
    expect(save).not.toHaveBeenCalled();
  });

  it("shows visible operator assertions and their original subject without dereferencing identifiers", () => {
    render(<InvestigationHypothesisBoard workspace={workspace([HYPOTHESIS])} busy={false} onSave={vi.fn()} />);
    fireEvent.click(screen.getByText("Explanation 1: investigating (operator assessment)"));
    expect(screen.getByText(HYPOTHESIS.explanation)).toBeInTheDocument();
    expect(screen.getByText("BusinessService: Original Payments")).toBeInTheDocument();
    expect(screen.getByText(/Declared version: Not supplied/)).toBeInTheDocument();
    expect(screen.getByText(HYPOTHESIS.unknowns[0])).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("creates one browser-known annotation only after explicit save", async () => {
    const save = vi.fn().mockResolvedValue(true);
    render(<InvestigationHypothesisBoard workspace={workspace()} busy={false} onSave={save} />);
    fireEvent.click(screen.getByRole("button", { name: "Propose explanation" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Proposed explanation" }), { target: { value: "A new explanation" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Unknowns (one per line, up to 8)" }), { target: { value: "Unknown one\n Unknown two " } });
    expect(save).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Save explanation revision" }));
    await waitFor(() => expect(save).toHaveBeenCalledOnce());
    expect(save).toHaveBeenCalledWith(expect.stringMatching(/^hyp-[0-9a-f]{32}$/), 3, {
      explanation: "A new explanation", supporting: [], contradicting: [], unknowns: ["Unknown one", "Unknown two"],
      disposition: "proposed", rationale: "",
    });
    await waitFor(() => expect(screen.queryByRole("textbox", { name: "Proposed explanation" })).not.toBeInTheDocument());
  });

  it("edits and dismisses a retained entry without deleting it or submitting attribution fields", async () => {
    const save = vi.fn().mockResolvedValue(true);
    render(<InvestigationHypothesisBoard workspace={workspace([HYPOTHESIS])} busy={false} onSave={save} />);
    fireEvent.click(screen.getByText("Explanation 1: investigating (operator assessment)"));
    fireEvent.click(screen.getByRole("button", { name: "Edit explanation 1" }));
    fireEvent.change(screen.getByRole("combobox", { name: "Operator disposition" }), { target: { value: "dismissed" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Disposition rationale" }), { target: { value: "Operator assessment rejects this explanation" } });
    fireEvent.click(screen.getByRole("button", { name: "Save explanation revision" }));
    await waitFor(() => expect(save).toHaveBeenCalledWith(HYPOTHESIS.hypothesis_id, 3, {
      explanation: HYPOTHESIS.explanation, supporting: HYPOTHESIS.supporting, contradicting: HYPOTHESIS.contradicting,
      unknowns: HYPOTHESIS.unknowns, disposition: "dismissed", rationale: "Operator assessment rejects this explanation",
    }));
    expect(screen.queryByRole("button", { name: /Delete/ })).not.toBeInTheDocument();
  });

  it("requires source identifiers, disposition rationale and bounded unknowns", async () => {
    const save = vi.fn();
    render(<InvestigationHypothesisBoard workspace={workspace()} busy={false} onSave={save} />);
    fireEvent.click(screen.getByRole("button", { name: "Propose explanation" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Proposed explanation" }), { target: { value: "Explanation" } });
    fireEvent.click(screen.getByRole("button", { name: "Add supporting reference" }));
    fireEvent.click(screen.getByRole("button", { name: "Save explanation revision" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("source and identifier");
    fireEvent.change(screen.getByRole("textbox", { name: "Source" }), { target: { value: "Incidents" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Reference identifier" }), { target: { value: "inc-1" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Operator disposition" }), { target: { value: "supported" } });
    fireEvent.click(screen.getByRole("button", { name: "Save explanation revision" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("rationale");
    fireEvent.change(screen.getByRole("textbox", { name: "Disposition rationale" }), { target: { value: "Operator interpretation only" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Unknowns (one per line, up to 8)" }), { target: { value: Array(9).fill("unknown").join("\n") } });
    fireEvent.click(screen.getByRole("button", { name: "Save explanation revision" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("at most 8 unknowns");
    expect(save).not.toHaveBeenCalled();
  });

  it("adds and removes distinct unverified references without executing anything", async () => {
    const save = vi.fn().mockResolvedValue(true);
    render(<InvestigationHypothesisBoard workspace={workspace()} busy={false} onSave={save} />);
    fireEvent.click(screen.getByRole("button", { name: "Propose explanation" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Proposed explanation" }), { target: { value: "Explanation" } });
    fireEvent.click(screen.getByRole("button", { name: "Add supporting reference" }));
    fireEvent.click(screen.getByRole("button", { name: "Remove supporting reference 1 from draft" }));
    fireEvent.click(screen.getByRole("button", { name: "Add contradicting reference" }));
    const reference = within(screen.getByRole("group", { name: "Contradicting reference 1" }));
    fireEvent.change(reference.getByRole("textbox", { name: "Source" }), { target: { value: "Network" } });
    fireEvent.change(reference.getByRole("textbox", { name: "Reference identifier" }), { target: { value: "gap-1" } });
    fireEvent.change(reference.getByRole("textbox", { name: "Declared source version" }), { target: { value: "operator-v1" } });
    fireEvent.change(reference.getByRole("textbox", { name: "Operator reference note" }), { target: { value: "Timing differs" } });
    fireEvent.click(screen.getByRole("button", { name: "Save explanation revision" }));
    await waitFor(() => expect(save).toHaveBeenCalledWith(expect.any(String), 3, expect.objectContaining({
      supporting: [], contradicting: [{ source: "Network", reference: "gap-1", declared_version: "operator-v1", note: "Timing differs" }],
    })));
  });

  it("retains known identity and draft after an unconfirmed write without automatic retry", async () => {
    const save = vi.fn().mockResolvedValue(false);
    render(<InvestigationHypothesisBoard workspace={workspace()} busy={false} onSave={save} />);
    fireEvent.click(screen.getByRole("button", { name: "Propose explanation" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Proposed explanation" }), { target: { value: "Keep this draft" } });
    fireEvent.click(screen.getByRole("button", { name: "Save explanation revision" }));
    await waitFor(() => expect(save).toHaveBeenCalledOnce());
    expect(screen.getByRole("textbox", { name: "Proposed explanation" })).toHaveValue("Keep this draft");
    expect(screen.getByText(/Known annotation identity:/)).toHaveTextContent(save.mock.calls[0][0]);
  });

  it("does not silently rebase a draft when the reviewed workspace revision changes", async () => {
    const save = vi.fn().mockResolvedValue(false);
    const record = workspace();
    const panel = render(<InvestigationHypothesisBoard workspace={record} busy={false} onSave={save} />);
    fireEvent.click(screen.getByRole("button", { name: "Propose explanation" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Proposed explanation" }), { target: { value: "Older review" } });
    panel.rerender(<InvestigationHypothesisBoard workspace={{ ...record, latest_revision: 4, revision: { ...record.revision, revision: 4 } }} busy={false} onSave={save} />);
    fireEvent.click(screen.getByRole("button", { name: "Save explanation revision" }));
    await waitFor(() => expect(save).toHaveBeenCalledWith(expect.any(String), 3, expect.objectContaining({ explanation: "Older review" })));
  });

  it.each(["reader", "history", "busy"])("withholds edits for %s state", state => {
    const record = workspace([HYPOTHESIS], state === "reader" ? { can_edit: false } : state === "history" ? { latest_revision: 4 } : {});
    render(<InvestigationHypothesisBoard workspace={record} busy={state === "busy"} onSave={vi.fn()} />);
    fireEvent.click(screen.getByText("Explanation 1: investigating (operator assessment)"));
    expect(screen.getByRole("button", { name: "Propose explanation" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Edit explanation 1" })).toBeDisabled();
  });

  it("caps reference entries and preserves explicit draft discard", async () => {
    const save = vi.fn();
    render(<InvestigationHypothesisBoard workspace={workspace()} busy={false} onSave={save} />);
    fireEvent.click(screen.getByRole("button", { name: "Propose explanation" }));
    for (let index = 0; index < 6; index += 1) fireEvent.click(screen.getByRole("button", { name: "Add supporting reference" }));
    expect(screen.getByRole("button", { name: "Add supporting reference" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Discard annotation draft" }));
    expect(screen.queryByRole("textbox", { name: "Proposed explanation" })).not.toBeInTheDocument();
    expect(save).not.toHaveBeenCalled();
  });

  it("shows secure identity generation failure rather than inventing an unsafe identifier", async () => {
    const original = crypto.randomUUID;
    Object.defineProperty(crypto, "randomUUID", { configurable: true, value: undefined });
    try {
      render(<InvestigationHypothesisBoard workspace={workspace()} busy={false} onSave={vi.fn()} />);
      fireEvent.click(screen.getByRole("button", { name: "Propose explanation" }));
      expect(await screen.findByRole("alert")).toHaveTextContent("Secure hypothesis identity generation is unavailable");
    } finally { Object.defineProperty(crypto, "randomUUID", { configurable: true, value: original }); }
  });

  it("does not clear an in-flight draft just because the parent is busy", async () => {
    let finish!: (value: boolean) => void;
    const save = vi.fn().mockImplementation(() => new Promise<boolean>(resolve => { finish = resolve; }));
    const record = workspace();
    const panel = render(<InvestigationHypothesisBoard workspace={record} busy={false} onSave={save} />);
    fireEvent.click(screen.getByRole("button", { name: "Propose explanation" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Proposed explanation" }), { target: { value: "Preserve while waiting" } });
    fireEvent.click(screen.getByRole("button", { name: "Save explanation revision" }));
    panel.rerender(<InvestigationHypothesisBoard workspace={record} busy onSave={save} />);
    expect(screen.getByRole("textbox", { name: "Proposed explanation" })).toBeDisabled();
    expect(screen.getByRole("textbox", { name: "Proposed explanation" })).toHaveValue("Preserve while waiting");
    await act(async () => finish(false));
    expect(screen.getByRole("textbox", { name: "Proposed explanation" })).toHaveValue("Preserve while waiting");
  });
});
