import { expect, test, type Locator, type Page } from "@playwright/test";

interface OntologyLifecycleSnapshot {
  connectionId: string;
  runWindow: string;
  runTerminalState: string;
  runCheckpoint: string;
  runGenerationLineage: string;
  reconciliation: string;
  activeGeneration: string;
  priorGeneration: string;
  generationValidation: string;
  authoritativeModelEdges: string;
  rollbackState: "enabled" | "disabled";
  evaluationSnapshot: string;
  evaluationGate: string;
  releaseEligibility: string;
  proposalDecisions: string[];
}

async function factValue(region: Locator, label: string): Promise<string> {
  const term = region.getByText(label, { exact: true });
  await expect(term).toBeVisible();
  const value = term.locator("..").locator("dd");
  await expect(value).toBeVisible();
  const text = (await value.innerText()).trim();
  expect(text).not.toBe("");
  return text;
}

async function selectOntologyConnection(
  page: Page,
  expectedConnectionId?: string,
): Promise<string> {
  await page.getByRole("tab", { name: "Ontology automation" }).click();
  const connection = page.getByRole("combobox", { name: "Connection" });
  await expect(connection).toBeEnabled();

  const connectionId =
    expectedConnectionId ??
    (await connection.locator("option:not([value=''])").first().getAttribute("value"));
  if (!connectionId) {
    throw new Error("An active connection authorized for the signed-in operator is required.");
  }

  await connection.selectOption(connectionId);
  await expect(connection).toHaveValue(connectionId);
  await expect(page.getByRole("tabpanel", { name: "Ontology automation" })).toBeVisible();
  return connectionId;
}

async function captureLifecycle(
  page: Page,
  connectionId: string,
): Promise<OntologyLifecycleSnapshot> {
  const panel = page.getByRole("tabpanel", { name: "Ontology automation" });

  const runHistory = panel.getByRole("region", { name: "Discovery run history" });
  await expect(runHistory).toBeVisible();
  const runRows = runHistory.getByRole("table").getByRole("row");
  await expect.poll(() => runRows.count()).toBeGreaterThan(1);
  const runCells = runRows.nth(1).getByRole("cell");
  await expect(runCells).toHaveCount(9);
  const runWindow = (await runCells.nth(1).innerText()).trim();
  const runTerminalState = (await runCells.nth(2).innerText()).trim();
  const runCheckpoint = (await runCells.nth(3).innerText()).trim();
  const runGenerationLineage = (await runCells.nth(5).innerText()).trim();
  expect(runWindow).not.toBe("");
  expect(runTerminalState).not.toBe("");
  expect(runCheckpoint).not.toBe("");
  expect(runCheckpoint).not.toBe("Not reported");
  expect(runGenerationLineage).not.toBe("");
  expect(runGenerationLineage).not.toContain("Not reported");

  const incremental = panel.getByRole("region", { name: "Incremental discovery" });
  const reconciliation = await factValue(incremental, "Last full reconciliation");
  expect(reconciliation).not.toBe("Not reported");

  const generation = panel.getByRole("region", { name: "Generation and publication" });
  const activeGeneration = await factValue(generation, "Active generation");
  const priorGeneration = await factValue(generation, "Prior generation");
  const generationValidation = await factValue(generation, "Validation");
  const authoritativeModelEdges = await factValue(
    generation,
    "Authoritative model edges",
  );
  expect(activeGeneration).not.toBe("Not reported");
  expect(priorGeneration).not.toBe("Not reported");
  expect(generationValidation).toBe("Passed");
  expect(authoritativeModelEdges).toBe("0");
  const rollback = generation.getByRole("button", { name: "Roll back generation" });
  await expect(rollback).toBeVisible();
  const rollbackState = (await rollback.isEnabled()) ? "enabled" : "disabled";

  const evaluation = panel.getByRole("region", {
    name: "Evaluation and relationship proposal agent",
  });
  const evaluationSnapshot = await factValue(evaluation, "Snapshot version");
  const evaluationGate = await factValue(evaluation, "Last evaluation gate");
  const releaseEligibility = await factValue(evaluation, "Release eligibility");
  expect(evaluationSnapshot).not.toBe("Not reported");
  expect(releaseEligibility).toMatch(/^Disabled\b/);

  const proposals = panel.getByRole("region", { name: "Relationship proposals" });
  await expect(
    proposals.getByText(
      "Review bounded model proposals without granting the browser publication authority.",
      { exact: true },
    ),
  ).toBeVisible();
  const proposalRows = proposals.getByRole("table").getByRole("row");
  await expect.poll(() => proposalRows.count()).toBeGreaterThan(1);
  const proposalRowCount = await proposalRows.count();
  const proposalDecisions: string[] = [];
  for (let index = 1; index < proposalRowCount; index += 1) {
    const decision = (await proposalRows.nth(index).getByRole("cell").nth(5).innerText())
      .trim()
      .toUpperCase();
    expect(["BLOCKED", "PENDING"]).toContain(decision);
    proposalDecisions.push(decision);
  }
  expect(proposalDecisions.length).toBeGreaterThan(0);

  return {
    connectionId,
    runWindow,
    runTerminalState,
    runCheckpoint,
    runGenerationLineage,
    reconciliation,
    activeGeneration,
    priorGeneration,
    generationValidation,
    authoritativeModelEdges,
    rollbackState,
    evaluationSnapshot,
    evaluationGate,
    releaseEligibility,
    proposalDecisions,
  };
}

test("preserves deployed ontology lifecycle and zero-model-edge guards after reload", async ({
  page,
}) => {
  await page.goto("/connections");
  await expect(page).toHaveURL(/^https:\/\/.+\/connections\/?(?:[?#].*)?$/);

  const connectionId = await selectOntologyConnection(page);
  const beforeReload = await captureLifecycle(page, connectionId);

  await page.reload();
  await expect(page).toHaveURL(/^https:\/\/.+\/connections\/?(?:[?#].*)?$/);
  await selectOntologyConnection(page, connectionId);
  const afterReload = await captureLifecycle(page, connectionId);

  expect(afterReload).toEqual(beforeReload);
});
