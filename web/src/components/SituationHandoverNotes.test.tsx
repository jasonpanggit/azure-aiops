import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { SituationNotesState } from "@/lib/types";
const { notes, appendNote } = vi.hoisted(() => ({ notes: vi.fn(), appendNote: vi.fn() }));
vi.mock("@/lib/services", () => ({ situationsApi: { notes, appendNote } }));
import { SituationHandoverNotes } from "./SituationHandoverNotes";

const initial: SituationNotesState = { schema_version: 1, situation_id: "situation-a", scope: {}, revision: 0, notes: [], can_append: true };
const props = { situationId: "situation-a", evidenceRunId: "run-1", scope: {} };

describe("durable Situation handover", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    notes.mockResolvedValue({ data: initial });
    appendNote.mockResolvedValue({ data: { ...initial, revision: 1, notes: [{
      note_id: "note-1", actor: "server-operator", revision: 1, evidence_run_id: "run-1",
      created_at: "2026-10-16T00:00:00Z", text: "Confirm ownership.",
    }] } });
  });
  it("appends the exact reviewed revision and preserves server attribution", async () => {
    render(<SituationHandoverNotes {...props} />);
    fireEvent.change(await screen.findByLabelText("Handover annotation"), { target: { value: "Confirm ownership." } });
    fireEvent.click(screen.getByRole("button", { name: "Append handover note" }));
    expect(await screen.findByText("server-operator · revision 1")).toBeInTheDocument();
    expect(appendNote).toHaveBeenCalledWith("situation-a", {}, {
      expected_revision: 0, evidence_run_id: "run-1", text: "Confirm ownership.",
    });
    expect(screen.getByLabelText("Handover annotation")).toHaveValue("");
  });
  it("retains drafts on conflict and requires explicit reload rather than replaying writes", async () => {
    appendNote.mockRejectedValue(new Error("Handover notes changed"));
    render(<SituationHandoverNotes {...props} />);
    fireEvent.change(await screen.findByLabelText("Handover annotation"), { target: { value: "Unsent annotation" } });
    fireEvent.click(screen.getByRole("button", { name: "Append handover note" }));
    await screen.findByText("Handover note was not saved");
    expect(screen.getByLabelText("Handover annotation")).toHaveValue("Unsent annotation");
    notes.mockResolvedValue({ data: { ...initial, revision: 1 } });
    fireEvent.click(screen.getByRole("button", { name: "Reload handover" }));
    await waitFor(() => expect(notes).toHaveBeenCalledTimes(2));
    expect(screen.getByLabelText("Handover annotation")).toHaveValue("Unsent annotation");
    expect(appendNote).toHaveBeenCalledTimes(1);
  });
  it("does not offer mutation to read-only users or treat missing storage as empty history", async () => {
    notes.mockResolvedValue({ data: { ...initial, can_append: false } });
    const view = render(<SituationHandoverNotes {...props} />);
    await screen.findByText(/Read-only handover access/);
    expect(screen.queryByLabelText("Handover annotation")).not.toBeInTheDocument();
    view.unmount();
    notes.mockRejectedValue(new Error("Storage unavailable"));
    render(<SituationHandoverNotes {...props} />);
    await screen.findByText("Handover history is unavailable");
    expect(screen.queryByText(/No handover notes have been recorded/)).not.toBeInTheDocument();
  });
  it("does not carry drafts or saved state across keyed scope changes", async () => {
    let finish: ((value: unknown) => void) | undefined;
    appendNote.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    const view = render(<SituationHandoverNotes key="scope-a" {...props} />);
    fireEvent.change(await screen.findByLabelText("Handover annotation"), { target: { value: "Scope A draft" } });
    fireEvent.click(screen.getByRole("button", { name: "Append handover note" }));
    view.rerender(<SituationHandoverNotes key="scope-b" {...props} scope={{ subscription: ["sub-b"] }} />);
    await act(async () => finish?.({ data: { ...initial, revision: 99 } }));
    expect(await screen.findByLabelText("Handover annotation")).toHaveValue("");
    expect(screen.queryByText(/History revision 99/)).not.toBeInTheDocument();
  });
});
