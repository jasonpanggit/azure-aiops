import { useRef, useState } from "react";
import { FluentProvider, webLightTheme } from "@fluentui/react-components";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import {
  RiskExceptionDialog,
  type RiskExceptionGovernanceContext,
  type RiskExceptionRecordResult,
  type RiskExceptionRevokeResult,
} from "./RiskExceptionDialog";

const recordDetails = {
  cveId: "CVE-2026-4242",
  targetScope: "3 virtual machines in subscription Production",
  affectedMetrics: ["Open exposure count", "Critical priority count"],
  evidenceFreshness: "Fresh as of 6 September 2026, 11:30 UTC",
  sessionApprover: "approver@example.com",
};

function renderDialog(node: React.ReactNode) {
  return render(<FluentProvider theme={webLightTheme}>{node}</FluentProvider>);
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

describe("RiskExceptionDialog record mode", () => {
  it("names exact scope and effects, owns approver identity, and focuses the required reason", async () => {
    renderDialog(
      <RiskExceptionDialog
        open
        mode="record"
        record={recordDetails}
        onOpenChange={() => {}}
        onRecord={vi.fn()}
      />,
    );

    expect(screen.getByRole("dialog", { name: "Record risk exception" })).toBeInTheDocument();
    expect(screen.getByText("CVE-2026-4242")).toBeInTheDocument();
    expect(screen.getByText("3 virtual machines in subscription Production")).toBeInTheDocument();
    expect(screen.getByText("Open exposure count")).toBeInTheDocument();
    expect(screen.getByText("Critical priority count")).toBeInTheDocument();
    expect(screen.getByText("Fresh as of 6 September 2026, 11:30 UTC")).toBeInTheDocument();
    expect(screen.getByLabelText("Session approver")).toHaveValue("approver@example.com");
    expect(screen.getByLabelText("Session approver")).toHaveAttribute("readonly");
    expect(screen.getByLabelText("Expiry (optional)")).toHaveAttribute("type", "datetime-local");
    expect(screen.getByRole("button", { name: "Record exception" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Keep reviewing" })).toBeEnabled();
    await waitFor(() => expect(screen.getByLabelText("Reason")).toHaveFocus());
  });

  it("prevents duplicate submission, retains values, and passes governance through unchanged", async () => {
    const user = userEvent.setup();
    const pending = deferred<RiskExceptionRecordResult>();
    const onRecord = vi.fn(() => pending.promise);
    const governance = {
      workflow: {
        approval: {
          allow_self_approval: true,
          requirements: [{ role_id: "security-owner", satisfied: true }],
        },
        blockers: [{ code: "evidence_partial" }],
        degradation: [{ source: "Defender", availability: "partial" }],
      },
      execution: {
        provider_submitted: true,
        submitted_attempt_count: 2,
        supersedes: "RME-1",
        superseded_by: "RME-3",
        evidence_reconciliation: { status: "pending" },
      },
      decision: {
        self_approved: false,
        approver_roles: ["Security Response Owner"],
        approval_role_id: "security-owner",
      },
    } as unknown as RiskExceptionGovernanceContext;

    renderDialog(
      <RiskExceptionDialog
        open
        mode="record"
        record={recordDetails}
        governance={governance}
        onOpenChange={() => {}}
        onRecord={onRecord}
      />,
    );

    await user.type(screen.getByLabelText("Reason"), "Compensating control is active");
    fireEvent.change(screen.getByLabelText("Expiry (optional)"), {
      target: { value: "2026-10-01T09:30" },
    });
    await user.click(screen.getByRole("button", { name: "Record exception" }));

    expect(onRecord).toHaveBeenCalledTimes(1);
    expect(onRecord).toHaveBeenCalledWith(expect.objectContaining({
      cveId: "CVE-2026-4242",
      reason: "Compensating control is active",
      expiresAt: "2026-10-01T09:30",
      approver: "approver@example.com",
      governance,
    }));
    expect(screen.getByRole("button", { name: "Recording exception…" })).toBeDisabled();
    expect(screen.getByLabelText("Reason")).toHaveValue("Compensating control is active");
    await user.click(screen.getByRole("button", { name: "Recording exception…" }));
    expect(onRecord).toHaveBeenCalledTimes(1);

    pending.resolve({
      status: "success",
      auditId: "AUD-4242",
      effectiveScope: recordDetails.targetScope,
      expiresAt: "2026-10-01T09:30",
      canRevoke: false,
      governance,
    });
    await screen.findByText("Risk exception recorded");
  });

  it("focuses an explicit failure alert and keeps entered values retryable", async () => {
    const user = userEvent.setup();
    const onRecord = vi.fn().mockRejectedValue(new Error("Audit service unavailable"));
    renderDialog(
      <RiskExceptionDialog
        open
        mode="record"
        record={recordDetails}
        onOpenChange={() => {}}
        onRecord={onRecord}
      />,
    );

    await user.type(screen.getByLabelText("Reason"), "Temporary compensating control");
    await user.click(screen.getByRole("button", { name: "Record exception" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Risk exception was not recorded");
    expect(alert).toHaveTextContent("Audit service unavailable");
    expect(alert).toHaveFocus();
    expect(screen.getByLabelText("Reason")).toHaveValue("Temporary compensating control");
    expect(screen.getByRole("button", { name: "Record exception" })).toBeEnabled();
  });

  it("preserves recorded truth when refreshing counts fails and focuses the audit result", async () => {
    const user = userEvent.setup();
    const onRefresh = vi.fn().mockRejectedValue(new Error("refresh unavailable"));
    renderDialog(
      <RiskExceptionDialog
        open
        mode="record"
        record={recordDetails}
        onOpenChange={() => {}}
        onRefresh={onRefresh}
        onRecord={vi.fn().mockResolvedValue({
          status: "success",
          auditId: "AUD-9000",
          effectiveScope: "Production subscription",
          expiresAt: null,
          canRevoke: true,
        } satisfies RiskExceptionRecordResult)}
      />,
    );

    await user.type(screen.getByLabelText("Reason"), "Accepted until vendor fix");
    await user.click(screen.getByRole("button", { name: "Record exception" }));

    const summary = await screen.findByRole("status");
    expect(summary).toHaveTextContent("Risk exception recorded");
    expect(summary).toHaveTextContent("Audit ID: AUD-9000");
    expect(summary).toHaveTextContent("Effective scope: Production subscription");
    expect(summary).toHaveTextContent(
      "Exception recorded; updated exposure counts could not be refreshed",
    );
    expect(summary).toHaveFocus();
    expect(screen.getByRole("button", { name: "Revoke risk exception" })).toBeInTheDocument();
  });

  it("closes on Escape and restores focus to the explicit invoker", async () => {
    const user = userEvent.setup();

    function Harness() {
      const [open, setOpen] = useState(false);
      const invokerRef = useRef<HTMLButtonElement>(null);
      return (
        <>
          <button ref={invokerRef} type="button" onClick={() => setOpen(true)}>
            Open risk exception
          </button>
          <RiskExceptionDialog
            open={open}
            mode="record"
            record={recordDetails}
            returnFocusRef={invokerRef}
            onOpenChange={setOpen}
            onRecord={vi.fn()}
          />
        </>
      );
    }

    renderDialog(<Harness />);
    const invoker = screen.getByRole("button", { name: "Open risk exception" });
    await user.click(invoker);
    await waitFor(() => expect(screen.getByLabelText("Reason")).toHaveFocus());
    await user.keyboard("{Escape}");
    await waitFor(() => expect(invoker).toHaveFocus());
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

describe("RiskExceptionDialog revoke mode", () => {
  const selectedExceptions = [
    { id: "REX-1", label: "CVE-2026-1001 on vm-1", targetScope: "vm-1" },
    { id: "REX-2", label: "CVE-2026-1002 on vm-2", targetScope: "vm-2" },
    { id: "REX-3", label: "CVE-2026-1003 on vm-3", targetScope: "vm-3" },
  ];

  it("confirms page-bounded selection, represented scope, and metric impact", async () => {
    renderDialog(
      <RiskExceptionDialog
        open
        mode="revoke"
        exceptions={selectedExceptions}
        representedScope="2 of 3 connections represented"
        onOpenChange={() => {}}
        onRevoke={vi.fn()}
      />,
    );

    expect(screen.getByRole("dialog", { name: "Revoke 3 risk exceptions" })).toBeInTheDocument();
    expect(
      screen.getByText(
        "Revoke 3 risk exceptions? Revoked findings will return to open-exposure and priority metrics. This action is audited.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Selected on this page")).toBeInTheDocument();
    expect(screen.getByText("2 of 3 connections represented")).toBeInTheDocument();
    for (const item of selectedExceptions) {
      expect(screen.getByText(item.label)).toBeInTheDocument();
    }
    await waitFor(() => expect(screen.getByRole("heading", { name: "Revoke 3 risk exceptions" })).toHaveFocus());
  });

  it("reports partial outcomes per item and keeps failed or unattempted rows selected", async () => {
    const user = userEvent.setup();
    const onSelectionChange = vi.fn();
    const result: RiskExceptionRevokeResult = {
      status: "partial",
      auditId: "AUD-REVOKE-1",
      outcomes: [
        { exceptionId: "REX-1", status: "succeeded" },
        { exceptionId: "REX-2", status: "failed", message: "Audit write rejected" },
        { exceptionId: "REX-3", status: "not_attempted", message: "Stopped after failure" },
      ],
    };

    renderDialog(
      <RiskExceptionDialog
        open
        mode="revoke"
        exceptions={selectedExceptions}
        representedScope="2 of 3 connections represented"
        onOpenChange={() => {}}
        onSelectionChange={onSelectionChange}
        onRevoke={vi.fn().mockResolvedValue(result)}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Revoke exceptions" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(
      "1 revoked, 1 failed, 1 not attempted. Failed and unattempted items remain selected.",
    );
    expect(alert).toHaveTextContent("REX-1 — Revoked");
    expect(alert).toHaveTextContent("REX-2 — Failed: Audit write rejected");
    expect(alert).toHaveTextContent("REX-3 — Not attempted: Stopped after failure");
    expect(alert).toHaveFocus();
    expect(onSelectionChange).toHaveBeenCalledWith(["REX-2", "REX-3"]);
    expect(screen.getByRole("button", { name: "Retry remaining exceptions" })).toBeEnabled();
  });

  it("conservatively marks omitted server outcomes not attempted and retains them", async () => {
    const user = userEvent.setup();
    const onSelectionChange = vi.fn();

    renderDialog(
      <RiskExceptionDialog
        open
        mode="revoke"
        exceptions={selectedExceptions}
        representedScope="2 of 3 connections represented"
        onOpenChange={() => {}}
        onSelectionChange={onSelectionChange}
        onRevoke={vi.fn().mockResolvedValue({
          status: "failure",
          message: "Revocation stopped after the first provider rejection.",
          outcomes: [
            { exceptionId: "REX-1", status: "succeeded" },
            { exceptionId: "REX-2", status: "failed", message: "Provider rejection" },
          ],
        } satisfies RiskExceptionRevokeResult)}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Revoke exceptions" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Revocation stopped after the first provider rejection.");
    expect(alert).toHaveTextContent(
      "REX-3 — Not attempted: No outcome was returned for this selected exception.",
    );
    expect(onSelectionChange).toHaveBeenCalledWith(["REX-2", "REX-3"]);
  });
});
