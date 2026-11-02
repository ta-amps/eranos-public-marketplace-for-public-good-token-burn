import { expect, test, type Page } from "@playwright/test";

import { FakeTessera, LIVE, mockSite } from "./support/mocks";

// Practice case: an example, not a real person or case.
// All APIs are answered in memory. Unmatched external traffic and every unmatched write are blocked.
async function fillRequest(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Tenant deposit rules" }).click();
  await page.locator("textarea[data-field='need']").fill("Create an example inventory for a neighborhood seed exchange. Practice case: an example, not a real person or case.");
  await page.getByLabel(/Your organization[’']s name/).fill("Example neighborhood group");
  await page.getByLabel("Type of organization").fill("Community group");
  await page.getByRole("checkbox", { name: /private information/ }).check();
}

test.describe("the request form owns one attempt and respects a wait", () => {
  test.use({ baseURL: LIVE });

  test.beforeEach(async ({ context, page }) => {
    await context.route("**/*", (route) => {
      const request = route.request();
      return new URL(request.url()).origin === LIVE && ["GET", "HEAD"].includes(request.method())
        ? route.continue()
        : route.abort("blockedbyclient");
    });
    await mockSite(page);
  });

  test("two submit events during a slow library read produce one saved request and one task", async ({ page }) => {
    let release!: () => void;
    const held = new Promise<void>((resolve) => { release = resolve; });
    let libraryReads = 0;
    await page.route(`${LIVE}/api/catalog?view=page`, async (route) => {
      libraryReads++;
      await held;
      await route.fulfill({ json: { kits: [] } });
    });
    const tessera = new FakeTessera();
    await tessera.install(page);
    await page.goto("/nonprofits");
    await fillRequest(page);
    await page.getByTestId("request-box").evaluate((form: HTMLFormElement) => {
      form.requestSubmit();
      form.requestSubmit();
    });
    await expect.poll(() => libraryReads).toBe(1);
    await expect(page.getByRole("button", { name: "Sending...", exact: true })).toBeDisabled();
    expect(tessera.calls.filter((call) => call.method === "POST")).toHaveLength(0);
    release();
    await expect(page.getByTestId("request-status")).toBeVisible();
    expect(tessera.calls.filter((call) => call.method === "POST" && call.url.endsWith("/v1/session/requester"))).toHaveLength(1);
    expect(tessera.calls.filter((call) => call.method === "POST" && call.url.includes("/v1/stores/org.requests/records/"))).toHaveLength(1);
    expect(tessera.calls.filter((call) => call.method === "POST" && call.url.endsWith("/v1/tasks"))).toHaveLength(1);
  });

  test("Enter and a direct submit preserve a rate-limit wait; expiry enables one retry", async ({ page }) => {
    await page.clock.install();
    await page.route(`${LIVE}/api/catalog?view=page`, (route) => route.fulfill({ json: { kits: [] } }));
    const tessera = new FakeTessera();
    tessera.signupFailure = { status: 429, code: "rate_limited", detail: "Fixture rate limit", retryAfter: 60 };
    await tessera.install(page);
    await page.goto("/nonprofits");
    await fillRequest(page);
    const send = page.getByRole("button", { name: "Send request", exact: true });
    await send.click();
    const problem = page.getByTestId("request-problem");
    await expect(problem).toBeVisible();
    const message = await problem.innerText();
    await expect(send).toBeDisabled();
    await page.getByLabel("Type of organization").press("Enter");
    await page.getByTestId("request-box").evaluate((form: HTMLFormElement) => form.requestSubmit());
    await expect(problem).toHaveText(message);
    expect(tessera.calls.filter((call) => call.method === "POST")).toHaveLength(1);
    tessera.signupFailure = null;
    await page.clock.fastForward(61_000);
    await expect(problem).toHaveCount(0);
    await expect(send).toBeEnabled();
    await send.click();
    await expect(page.getByTestId("request-status")).toBeVisible();
    expect(tessera.calls.filter((call) => call.method === "POST" && call.url.endsWith("/v1/tasks"))).toHaveLength(1);
  });
});
