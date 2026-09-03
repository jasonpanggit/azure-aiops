const { chromium } = require("/usr/local/lib/node_modules/@playwright/test");
const { execFileSync } = require("node:child_process");
const fs = require("node:fs");

(async () => {
  const webUrl = "https://aiops-dev-web.greenpond-732382e3.australiaeast.azurecontainerapps.io/remediation";
  const arcDemoTarget = process.env.TARGET_ARC === "1";
  const apiScope = "api://306c1437-0e7d-43bd-940b-79b878166331/.default";
  const tenantId = "ffc83107-fcc0-4d2e-8798-d582da36505e";
  const clientId = "306c1437-0e7d-43bd-940b-79b878166331";
  const token = execFileSync("az", [
    "account", "get-access-token", "--scope", apiScope, "--query", "accessToken", "-o", "tsv",
  ], { encoding: "utf8" }).trim();
  const homeAccountId = `authorized-operator.${tenantId}`;
  const environment = "login.microsoftonline.com";
  const accountKey = `msal.3|${homeAccountId}|${environment}|${tenantId}`.toLowerCase();
  const target = `api://${clientId}/access_as_user`;
  const accessTokenKey = `msal.3|${homeAccountId}|${environment}|AccessToken|${clientId}|${tenantId}|${target}||`.toLowerCase();
  const expiresOn = String(Math.floor(Date.now() / 1000) + 3600);
  const account = {
    homeAccountId, environment, realm: tenantId, localAccountId: "authorized-operator",
    username: "authorized-operator", authorityType: "MSSTS",
  };
  const accessToken = {
    homeAccountId, environment, credentialType: "AccessToken", clientId, secret: token,
    realm: tenantId, target, cachedAt: String(Math.floor(Date.now() / 1000)),
    expiresOn, extendedExpiresOn: expiresOn, tokenType: "Bearer",
  };
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  // This run uses the real, already-authorized API bearer at the request
  // boundary. Abort only the synthetic MSAL iframe probe so the deployed
  // app's existing null-token path fails fast instead of waiting for Entra;
  // the API continues to authenticate and authorize every request normally.
  await context.route(/https:\/\/login\.microsoftonline\.com\//, (route) => route.abort());
  await context.addInitScript(({ accountKey, account, accessToken, accessTokenKey }) => {
    sessionStorage.setItem("msal.3.account.keys", JSON.stringify([accountKey]));
    sessionStorage.setItem(accountKey, JSON.stringify(account));
    sessionStorage.setItem(`msal.3.token.keys.${accessToken.clientId}`, JSON.stringify([accessTokenKey]));
    sessionStorage.setItem(accessTokenKey, JSON.stringify(accessToken));
  }, { accountKey, account, accessToken, accessTokenKey });
  const page = await context.newPage();
  await context.route("**/api/v1/**", async (route) => {
    const headers = { ...route.request().headers(), authorization: `Bearer ${token}` };
    await route.continue({ headers });
  });
  const evidence = {
    url: webUrl, console: [], pageErrors: [], requestFailures: [], requests: [],
    responses: [], screenshots: [], ui: {},
  };
  page.on("console", (message) => evidence.console.push({ type: message.type(), text: message.text() }));
  page.on("pageerror", (error) => evidence.pageErrors.push(String(error)));
  page.on("request", (request) => {
    if (request.url().includes("/api/") || request.url().includes("/login")) {
      evidence.requests.push({
        method: request.method(), url: request.url(),
        hasAuthorization: Boolean(request.headers().authorization),
      });
    }
  });
  page.on("requestfailed", (request) => {
    if (request.url().includes("/api/") || request.url().includes("/login")) {
      evidence.requestFailures.push({
        method: request.method(), url: request.url(), failure: request.failure(),
      });
    }
  });
  page.on("response", async (response) => {
    if (!response.url().includes("/api/") && !response.url().includes("/login")) return;
    const entry = { status: response.status(), url: response.url() };
    try {
      const body = await response.text();
      entry.body = body.slice(
        0,
        response.url().includes("/remediation-plans") ? 50000 : 10000,
      );
    } catch (error) {
      entry.bodyError = String(error);
    }
    evidence.responses.push(entry);
  });
  const persist = () => fs.writeFileSync(
    ".planning/ui-reviews/remediation-e2e-live.json", JSON.stringify(evidence, null, 2),
  );

  await page.goto(webUrl, { waitUntil: "networkidle", timeout: 60000 });
  await page.waitForTimeout(120000);
  await page.screenshot({ path: ".planning/ui-reviews/remediation-e2e-live-select.png", fullPage: true });
  evidence.screenshots.push("remediation-e2e-live-select.png");
  evidence.ui.select = (await page.locator("body").innerText()).slice(0, 5000);
  evidence.ui.sessionStorageKeys = await page.evaluate(() => Object.keys(sessionStorage));

  const planResponse = evidence.responses.find((response) => (
    response.status === 200
    && response.url.endsWith("/api/v1/remediation-plans?offset=0&limit=100")
  ));
  let planPayload = null;
  try {
    planPayload = planResponse ? JSON.parse(planResponse.body) : null;
  } catch {
    planPayload = null;
  }
  const plans = Array.isArray(planPayload?.data?.plans) ? planPayload.data.plans : [];
  const planText = (plan) => JSON.stringify(plan).toLowerCase();
  const isAzureVm = (plan) => String(
    plan?.resource?.id || plan?.resource_key || "",
  ).toLowerCase().includes("/providers/microsoft.compute/virtualmachines/");
  const isDefenderRelated = (plan) => /defender for (cloud|endpoint|servers)|microsoft defender|azure defender/.test(planText(plan));
  const isArcPatchVm1 = (plan) => (
    String(plan?.title || "").toLowerCase() === "patch vm1"
    && String(plan?.resource?.id || plan?.resource_key || "").toLowerCase()
      .includes("/providers/microsoft.hybridcompute/machines/vm1")
  );
  const eligibleVmPlans = arcDemoTarget
    ? plans.filter(isArcPatchVm1)
    : plans.filter((plan) => isAzureVm(plan) && isDefenderRelated(plan));
  const closestDefenderPlans = plans.filter(isDefenderRelated).map((plan) => ({
    plan_id: plan.plan_id,
    title: plan.title,
    action_id: plan.action_id,
    resource_id: plan.resource?.id || plan.resource_key || "",
    resource_type: plan.resource?.resource_type || plan.resource?.entity_type || "",
    defender_recommendations: plan.defender_recommendations || [],
    defender_mapping: plan.defender_mapping || {},
  }));
  evidence.ui.targetSelection = {
    available_plan_count: plans.length,
    eligible_azure_vm_defender_plan_count: eligibleVmPlans.length,
    eligible_azure_vm_defender_plans: eligibleVmPlans.map((plan) => ({
      plan_id: plan.plan_id, title: plan.title,
      resource_id: plan.resource?.id || plan.resource_key || "",
      action_id: plan.action_id,
    })),
    closest_defender_plans: closestDefenderPlans,
  };
  const targetPlan = eligibleVmPlans[0] || null;
  if (!targetPlan) {
    evidence.ui.noEligibleTarget = arcDemoTarget
      ? "No deployed Arc Patch vm1 plan was rendered."
      : "No deployed plan combines an Azure VM resource with a Defender for Cloud/Endpoint/Servers recommendation.";
    persist();
    console.log(JSON.stringify({
      result: "no_eligible_azure_vm_defender_fix",
      targetSelection: evidence.ui.targetSelection,
      ui: evidence.ui.select,
      requests: evidence.requests,
      responses: evidence.responses,
      console: evidence.console,
      pageErrors: evidence.pageErrors,
      requestFailures: evidence.requestFailures,
      screenshots: evidence.screenshots,
    }, null, 2));
    await browser.close();
    process.exitCode = 3;
    return;
  }
  const planButton = page.locator("button.plan-row").filter({
    hasText: String(targetPlan.title || targetPlan.plan_id),
  }).first();
  if (!(await planButton.count())) {
    evidence.ui.targetButtonMissing = targetPlan;
    persist();
    console.log(JSON.stringify(evidence, null, 2));
    await browser.close();
    process.exitCode = 2;
    return;
  }
  await planButton.click();
  evidence.ui.afterPlanClick = (await page.locator("body").innerText()).slice(0, 7000);
  persist();
  try {
    await page.getByRole("button", { name: "Continue to approval" }).waitFor({ state: "visible", timeout: 120000 });
  } catch (error) {
    evidence.ui.workflowTimeout = (await page.locator("body").innerText()).slice(0, 7000);
    evidence.ui.workflowWaitError = String(error);
    persist();
    console.log(JSON.stringify(evidence, null, 2));
    await browser.close();
    process.exitCode = 4;
    return;
  }
  evidence.ui.review = (await page.locator("body").innerText()).slice(0, 7000);
  persist();
  await page.getByRole("button", { name: "Continue to approval" }).click();
  await page.screenshot({ path: ".planning/ui-reviews/remediation-e2e-live-approve.png", fullPage: true });
  evidence.screenshots.push("remediation-e2e-live-approve.png");
  evidence.ui.approve = (await page.locator("body").innerText()).slice(0, 5000);
  persist();
  await page.getByLabel("Rationale").fill("Authorized operator approval for the exact reviewed remediation snapshot.");
  await page.getByLabel("Expires").fill("2099-12-31");
  await page.getByRole("button", { name: "Record decision" }).click();
  const reviewAndRun = page.getByRole("button", { name: "Review and run" });
  await reviewAndRun.waitFor({ state: "visible", timeout: 120000 });
  evidence.ui.afterApproval = (await page.locator("body").innerText()).slice(0, 6000);
  persist();
  await reviewAndRun.click();
  await page.screenshot({ path: ".planning/ui-reviews/remediation-e2e-live-confirm.png", fullPage: true });
  evidence.screenshots.push("remediation-e2e-live-confirm.png");
  evidence.ui.confirm = (await page.locator("body").innerText()).slice(0, 5000);
  await page.getByRole("button", { name: "Confirm run" }).click();
  await page.waitForTimeout(30000);
  await page.screenshot({ path: ".planning/ui-reviews/remediation-e2e-live-verify.png", fullPage: true });
  evidence.screenshots.push("remediation-e2e-live-verify.png");
  evidence.ui.verify = (await page.locator("body").innerText()).slice(0, 7000);
  persist();
  const retryButton = page.getByRole("button", { name: "Retry approved snapshot" });
  try {
    await page.getByRole("heading", { name: "Provider verification" }).waitFor({
      state: "visible",
      timeout: 180000,
    });
  } catch (error) {
    evidence.ui.verifyWaitError = String(error);
    evidence.ui.verifyAfterWait = (await page.locator("body").innerText()).slice(0, 7000);
    persist();
    console.log(JSON.stringify(evidence, null, 2));
    await browser.close();
    process.exitCode = 5;
    return;
  }
  evidence.ui.verify = (await page.locator("body").innerText()).slice(0, 7000);
  persist();
  if (await retryButton.count()) {
    const retryResponse = page.waitForResponse(
      (response) => response.url().includes("/executions/") && response.url().endsWith("/retry")
        && response.status() === 202,
      { timeout: 120000 },
    );
    await retryButton.click();
    await retryResponse;
    await page.waitForTimeout(60000);
    await page.screenshot({ path: ".planning/ui-reviews/remediation-e2e-live-retry-verify.png", fullPage: true });
    evidence.screenshots.push("remediation-e2e-live-retry-verify.png");
    evidence.ui.retryVerify = (await page.locator("body").innerText()).slice(0, 7000);
    persist();
  }
  console.log(JSON.stringify({
    ui: evidence.ui, requests: evidence.requests, responses: evidence.responses,
    console: evidence.console, pageErrors: evidence.pageErrors,
    requestFailures: evidence.requestFailures, screenshots: evidence.screenshots,
  }, null, 2));
  await browser.close();
})().catch((error) => {
  console.error(error.stack || String(error));
  process.exitCode = 1;
});
