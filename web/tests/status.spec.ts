import { expect, test, type Page } from "@playwright/test";

import type { RequestExampleNoun } from "../src/lib/status/example";
import { FakeTessera, LIVE, mockSite, noun } from "./support/mocks";

// The request flow on the hosted build: Send, the private link (E03), the status diagram bound to records (E04),
// motion from real facts only (E05), the Send morph (E07), the decision (E08) and the corner states (E10).

const example = noun<RequestExampleNoun>("request-example");
const KEY = `tsk_${"ab".repeat(32)}`;
const PRINCIPAL = `r_${"cd".repeat(16)}`;
const REQUEST_ID = `rq-${PRINCIPAL}-mvwv3xwe`;

async function stubClipboardForStatus(page: Page) {
  await page.evaluate(() => {
    const copied: string[] = [];
    Object.defineProperty(window, "copied", { value: copied, configurable: true });
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText: async (text: string) => void copied.push(text) },
      configurable: true,
    });
  });
}

async function fillRequest(page: Page) {
  await page.getByRole("button", { name: "Tenant deposit rules" }).click();
  await page.getByLabel("Your organization's name").fill("Riverside Tenant Clinic");
  await page.getByLabel("Type of organization").fill("Tenant legal-aid clinic");
  await page.getByRole("checkbox", { name: /private information/ }).check();
}

async function send(page: Page) {
  await page.getByRole("button", { name: "Send request", exact: true }).click();
  const again = page.getByRole("button", { name: "Send as a new request" });
  await again.waitFor({ timeout: 3000 }).catch(() => undefined);
  if (await again.isVisible()) await again.click();
}

test.describe("on the hosted build", () => {
  test.use({ baseURL: LIVE });

  test("E03: Send opens /requests/<id>#k=<key>, the key never rides in a path or query, and a reload keeps it", async ({ page }) => {
    await mockSite(page);
    const tessera = new FakeTessera();
    await tessera.install(page);
    const urls: string[] = [];
    page.on("request", (r) => urls.push(r.url()));
    await page.goto("/nonprofits");
    await fillRequest(page);
    await send(page);
    await page.waitForFunction(() => location.pathname.startsWith("/requests/rq-"));
    const url = new URL(page.url());
    expect(url.pathname).toMatch(/^\/requests\/rq-r_[0-9a-f]{32}-[0-9a-z]+$/);
    await expect(page.getByTestId("request-status")).toBeVisible();
    // Once stored, the key leaves the address bar (filming, screen-sharing, synced history), and the page keeps
    // working from storage: the keyed button is there and copies the full private link.
    await expect.poll(() => page.evaluate(() => location.hash)).toBe("");
    await stubClipboardForStatus(page);
    await page.getByRole("button", { name: "Copy private link" }).click();
    expect(await page.evaluate(() => (window as unknown as { copied: string[] }).copied.at(-1))).toBe(`${new URL(page.url()).origin}${url.pathname}#k=${KEY}`);
    // The brief carries the requester's choices, so workers know what to produce.
    const filed = tessera.calls.find((c) => c.url.endsWith("/v1/tasks"));
    expect(filed?.body).toMatchObject({ queue: "eq01", kind: "request", brief: { output_type: "information", frequency: "one-off" } });
    expect(filed?.namespace).toBe("main");
    await page.reload();
    await expect(page.getByRole("button", { name: "Copy private link" })).toBeVisible();
    expect(await page.evaluate(() => location.hash)).toBe("");
    expect(urls.every((u) => !new URL(u).pathname.includes(KEY) && !new URL(u).search.includes(KEY))).toBe(true);
    expect(tessera.calls.filter((c) => c.method === "GET").every((c) => c.auth === `Bearer ${KEY}`)).toBe(true);
  });

  test("E03: without the private link the page is read-only, or says this browser lacks the link", async ({ page }) => {
    const plan = { request_id: REQUEST_ID, receipt: { claim_receipt: "e".repeat(64) }, parts: [{ part: 1, route: "public-only", text: "Summarize the laws.", legal: true, report_id: "RPT-RAAAAAAA-01" }] };
    await mockSite(page, { plan, request: { request_id: REQUEST_ID, status: "open_for_build", text: "Summarize the laws.", parts: { "1": { status: "open" } } } });
    await page.goto(`/requests/${REQUEST_ID}`);
    await expect(page.getByTestId("notice-read-only")).toContainText("You're viewing a public request.");
    await expect(page.getByRole("button", { name: "Copy private link" })).toHaveCount(0);
    await page.goto(`/requests/rq-${PRINCIPAL}-zzzz9999`);
    await page.unroute(`${LIVE}/api/**`);
    await mockSite(page);
    await page.reload();
    await expect(page.getByTestId("notice-key-missing")).toContainText("This browser doesn't have your private link.");
    await page.goto("/requests/not-a-request");
    await expect(page.getByTestId("notice-unknown")).toContainText("We can't find request not-a-request.");
  });

  test("E07: Send morphs the request box into the 'Your request' node, and skips the morph with reduced motion", async ({ page }) => {
    await mockSite(page);
    await new FakeTessera().install(page);
    await page.addInitScript(() => {
      const doc = document as Document & { startViewTransition?: (cb: () => void) => unknown; transitions?: number };
      const real = doc.startViewTransition?.bind(document);
      (window as unknown as { transitions: number }).transitions = 0;
      if (real) {
        doc.startViewTransition = (cb: () => void) => {
          (window as unknown as { transitions: number }).transitions += 1;
          return real(cb);
        };
      }
    });
    await page.goto("/nonprofits");
    expect(await page.locator("form.er-ask").evaluate((el) => getComputedStyle(el).viewTransitionName)).toBe("request");
    await fillRequest(page);
    await send(page);
    await page.waitForFunction(() => location.pathname.startsWith("/requests/rq-"));
    expect(await page.evaluate(() => (window as unknown as { transitions: number }).transitions)).toBe(1);
    // The box lands on the plain view's first stage, "Sent" (the diagram's request node in the technical view).
    expect(await page.locator('[data-step="0"]').evaluate((el) => getComputedStyle(el).viewTransitionName)).toBe("request");
    const duration = await page.evaluate(() => {
      const rule = [...document.styleSheets].flatMap((s) => [...s.cssRules]).find((r) => r.cssText.startsWith("::view-transition-group(request)"));
      return rule?.cssText ?? "";
    });
    expect(duration).toContain("var(--dur-deliberate)");
  });

  test("E07: with reduced motion the page simply navigates", async ({ browser }) => {
    const context = await browser.newContext({ baseURL: LIVE, reducedMotion: "reduce" });
    const page = await context.newPage();
    await mockSite(page);
    await new FakeTessera().install(page);
    await page.addInitScript(() => {
      (window as unknown as { transitions: number }).transitions = 0;
      const doc = document as Document & { startViewTransition?: (cb: () => void) => unknown };
      const real = doc.startViewTransition?.bind(document);
      if (real) doc.startViewTransition = (cb: () => void) => ((window as unknown as { transitions: number }).transitions += 1, real(cb));
    });
    await page.goto("/nonprofits");
    await fillRequest(page);
    await send(page);
    await page.waitForFunction(() => location.pathname.startsWith("/requests/rq-"));
    expect(await page.evaluate(() => (window as unknown as { transitions: number }).transitions)).toBe(0);
    await context.close();
  });

  test("E10: after 3 failed polls the page says live updates paused and moves nothing", async ({ page }) => {
    await mockSite(page, { publicFails: true });
    await page.addInitScript(() => {
      const calls: string[] = [];
      (window as unknown as { animateCalls: string[] }).animateCalls = calls;
      const real = Element.prototype.animate;
      Element.prototype.animate = function (...args: Parameters<Element["animate"]>) {
        calls.push((this as Element).className.toString());
        return real.apply(this, args);
      };
    });
    await page.goto(`/requests/${REQUEST_ID}`);
    // Polls run every 5 s; the third failure pauses live updates.
    await expect(page.getByTestId("notice-paused")).toContainText("Live updates paused.", { timeout: 20_000 });
    expect(await page.evaluate(() => (window as unknown as { animateCalls: string[] }).animateCalls.length)).toBe(0);
  });

  test("B2: the worker's recorded versions are the facts, and every node links the version that holds its receipt", async ({ page }) => {
    const now = Math.floor(Date.now() / 1000);
    const event = (version: number, value: Record<string, unknown>) => ({
      version,
      created_at: now - 300 + version,
      value: { schema_version: 1, request_id: REQUEST_ID, status: "open_for_build", event: { at: now - 300 + version, ...value } },
    });
    const history = [
      event(1, { type: "received", receipt: "a".repeat(64) }),
      event(2, { type: "planned", receipt: "b".repeat(64), parts: [{ part: 1, route: "public-only", text: "Summarize the laws.", report_id: "RPT-RAAAAAAA-01" }] }),
      event(3, { type: "work_claimed", part: 1, receipt: "c".repeat(64), worker: "volunteer-7", model: "llama-3.3-70b", lease_ends: now + 600 }),
    ];
    const seen = await mockSite(page, { history, request: { request_id: REQUEST_ID, status: "open_for_build", text: "Summarize the laws." } });
    await page.goto(`/requests/${REQUEST_ID}?view=technical`);
    await expect(page.locator('[data-node="worker-1"]')).toHaveAttribute("data-state", "working");
    await expect(page.locator('[data-node="worker-1"]')).toHaveAttribute("data-receipt", "c".repeat(64));
    await expect(page.locator('[data-node="worker-1"]')).toHaveAttribute("data-record", `/api/nouns/eranos.requests/${REQUEST_ID}/history#v3`);
    const unlinked = await page.$$eval("[data-node]", (nodes) =>
      nodes
        .filter((n) => n.getAttribute("data-state") !== "idle")
        .filter((n) => !(n.getAttribute("data-record") ?? "").startsWith("/api/nouns/eranos.requests/"))
        .map((n) => n.getAttribute("data-node")),
    );
    expect(unlinked).toEqual([]);
    expect(seen).toContain(`/api/nouns/eranos.requests/${REQUEST_ID}/history`);
    await expect(page.getByTestId("added-panel")).toHaveCount(0);
  });

  test("v6: when one of Eranos's own workers picks a part up, the plain view says so", async ({ page }) => {
    const now = Math.floor(Date.now() / 1000);
    const event = (version: number, value: Record<string, unknown>) => ({
      version,
      created_at: now - 300 + version,
      value: { schema_version: 1, request_id: REQUEST_ID, status: "open_for_build", event: { at: now - 300 + version, ...value } },
    });
    const history = [
      event(1, { type: "received", receipt: "a".repeat(64) }),
      event(2, { type: "planned", receipt: "b".repeat(64), parts: [{ part: 1, route: "public-only", text: "Summarize the laws.", report_id: "RPT-RAAAAAAA-01" }] }),
      event(3, { type: "work_claimed", part: 1, receipt: "c".repeat(64), worker: "eranos-worker-1", dedicated: true, model: "llama-3.2-3b" }),
    ];
    await mockSite(page, { history, request: { request_id: REQUEST_ID, status: "open_for_build", text: "Summarize the laws." } });
    await page.goto(`/requests/${REQUEST_ID}`);
    await expect(page.getByTestId("helper-1")).toContainText("One of Eranos\u2019s own workers");
    await expect(page.getByTestId("helper-1")).toContainText("no volunteer was free");
    await expect(page.getByTestId("plain-happened").locator("li").first()).toContainText("No volunteer was free, so one of Eranos\u2019s own workers started making it.");
  });

  test("B4: a published process package shows 'Download the process' with its SHA-256; an unreviewed one does not", async ({ page }) => {
    const processExample = noun<{ solution: Record<string, unknown> }>("request-example-process");
    const plan = { request_id: REQUEST_ID, receipt: { claim_receipt: "e".repeat(64) }, parts: [{ part: 1, route: "private-files", text: "A process.", kit_id: "PRC-35DE86-01" }] };
    const sha = "a".repeat(64);
    const published = { blob_sha256: sha, tags: ["kind:process", "status:verified"], review_receipt: "c".repeat(64), drafter_key_id: "kb_a", reviewer_key_id: "kb_b" };
    const solutions = { "PRC-35DE86-01": { ...processExample.solution, request_id: REQUEST_ID } };
    await mockSite(page, { plan, solutions, catalog: { "PRC-35DE86-01": published } });
    await page.goto(`/requests/${REQUEST_ID}/result?part=1`);
    const line = page.getByTestId("download-process");
    await expect(line.getByRole("link", { name: "Download the process" })).toHaveAttribute("href", `/p/${REQUEST_ID}/download`);
    await expect(line).toContainText(sha.slice(0, 12));
    await page.unroute(`${LIVE}/api/**`);
    await mockSite(page, { plan, solutions, catalog: { "PRC-35DE86-01": { ...published, reviewer_key_id: "kb_a" } } });
    await page.goto(`/requests/${REQUEST_ID}/result?part=1`);
    await expect(page.getByTestId("task-object")).toBeVisible();
    await expect(page.getByTestId("download-process")).toHaveCount(0);
  });

  test("E10: a request withdrawn by its key, a part sent back, and a sensitive kit waiting for sign-off", async ({ page }) => {
    const plan = {
      request_id: REQUEST_ID,
      receipt: { claim_receipt: "e".repeat(64) },
      parts: [
        { part: 1, route: "public-only", text: "Summarize the laws.", legal: true, report_id: "RPT-RAAAAAAA-01" },
        { part: 2, route: "private-files", text: "A process for our notes.", kit_id: "KIT-RBBBBBBB-02", needs_person_signoff: true },
      ],
    };
    const request = {
      request_id: REQUEST_ID,
      status: "open_for_build",
      text: "Summarize the laws. A process for our notes.",
      parts: { "1": { status: "needs_revision", findings: ["two points had no source"] }, "2": { status: "awaiting_steward" } },
    };
    await mockSite(page, { plan, request });
    const tessera = new FakeTessera();
    tessera.keys.set(KEY, PRINCIPAL);
    await tessera.install(page);
    await page.goto(`/requests/${REQUEST_ID}?view=technical#k=${KEY}`);
    await expect(page.getByTestId("notice-sent-back")).toContainText("Sent back: two points had no source");
    await expect(page.getByTestId("notice-signoff")).toContainText("This kit has steps only a person may do.");
    await expect(page.locator('[data-node="review-1"]')).toHaveAttribute("data-state", "sent_back");
    await expect(page.locator('[data-node="result-2"]')).toHaveAttribute("data-state", "person");
    tessera.taskState = "cancelled";
    await page.goto("about:blank");
    await page.goto(`/requests/${REQUEST_ID}?view=technical#k=${KEY}`);
    await expect(page.getByTestId("notice-withdrawn")).toContainText("Parts already finished stay on the record");
  });

  test("E08: deciding needs the requester key; 'Use this report' records it and shows the decision and the Agora link in the first 1280×480", async ({ page }) => {
    const report = example.solution.report;
    const plan = { request_id: REQUEST_ID, receipt: { claim_receipt: "e".repeat(64) }, parts: [{ part: 1, route: "public-only", text: "x", legal: true, report_id: report.report_id }] };
    await page.setViewportSize({ width: 1280, height: 480 });
    await mockSite(page, { plan, solutions: { [report.report_id]: { ...example.solution, request_id: REQUEST_ID } } });
    const tessera = new FakeTessera();
    await tessera.install(page);
    await page.goto(`/requests/${REQUEST_ID}/result?part=1`);
    await expect(page.getByTestId("decision-read-only")).toBeVisible();
    await expect(page.getByRole("button", { name: "Yes, use it" })).toHaveCount(0);
    expect(tessera.calls.filter((c) => c.method === "POST")).toEqual([]);

    tessera.keys.set(KEY, PRINCIPAL);
    await page.goto("about:blank");
    await page.goto(`/requests/${REQUEST_ID}/result?part=1#k=${KEY}`);
    await page.getByRole("button", { name: "Yes, use it" }).click();
    const recorded = page.getByTestId("decision-recorded");
    await expect(recorded).toContainText("You\u2019re using it.");
    await expect(recorded).toContainText("version 1");
    const write = tessera.calls.find((c) => c.method === "POST" && c.url.includes("/v1/stores/org.decisions/records/"));
    expect(write?.auth).toBe(`Bearer ${KEY}`);
    // Option A: the decision itself is a request task on eq01, which the worker records with a receipt.
    const task = tessera.calls.find((c) => c.url.endsWith("/v1/tasks"));
    expect(task?.body).toMatchObject({ queue: "eq01", kind: "request", brief: { decision: { request_id: REQUEST_ID, part: 1, choice: "use" } } });
    expect(task?.auth).toBe(`Bearer ${KEY}`);
    await expect(page.getByTestId("decision-task")).toBeVisible();
    const link = recorded.getByRole("link", { name: /overview deck, on Agora/ });
    await expect(link).toBeVisible();
    for (const box of [await recorded.boundingBox(), await link.boundingBox()]) {
      expect(box && box.y + box.height <= 480 && box.x + box.width <= 1280).toBe(true);
    }
  });

  test("E08: 'Ask for changes' sends the part back in line with the note, as a request that follows this one", async ({ page }) => {
    const report = example.solution.report;
    const plan = { request_id: REQUEST_ID, receipt: { claim_receipt: "e".repeat(64) }, parts: [{ part: 1, route: "public-only", text: "x", legal: true, report_id: report.report_id, output_type: "information" }] };
    await mockSite(page, { plan, solutions: { [report.report_id]: { ...example.solution, request_id: REQUEST_ID } } });
    const tessera = new FakeTessera();
    tessera.keys.set(KEY, PRINCIPAL);
    await tessera.install(page);
    await page.goto(`/requests/${REQUEST_ID}/result?part=1#k=${KEY}`);
    await page.getByRole("button", { name: "Ask for changes" }).click();
    await page.getByLabel("What should change?").fill("Add the date each change takes effect.");
    await page.getByRole("button", { name: "Send my changes" }).click();
    await expect(page.getByTestId("decision-revising")).toContainText("Your note is filed as task");
    const filed = tessera.calls.find((c) => c.url.endsWith("/v1/tasks"));
    expect(filed?.body).toMatchObject({
      queue: "eq01",
      kind: "request",
      brief: { decision: { request_id: REQUEST_ID, part: 1, choice: "changes", note: "Add the date each change takes effect." } },
    });
  });
});

test.describe("E04 and E05: the example request", () => {
  test("RequestStatusPage v6: a progress strip and four bands in plain words; technical details switch on and off", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/requests/example?moment=review");
    const plain = page.getByTestId("plain-status");
    await expect(plain).toBeVisible();
    await expect(page.getByTestId("status-diagram")).toHaveCount(0);
    await expect(plain.locator("[data-step]")).toHaveText(["Sent", "Sorted", "Being made", "Being checked", "Ready for you", "In the library"]);
    await expect(plain.locator("[data-band]")).toHaveCount(4);
    await expect(plain.locator('[data-band="1"]')).toContainText("Sorted and split");
    await expect(plain.locator('[data-band="1"]')).toContainText("No private information found in the request");
    await expect(plain.locator('[data-band="3"]')).toHaveAttribute("data-state", "now");
    await expect(plain.locator('[data-band="3"]')).toContainText("The rule: the volunteer who made it can never approve it.");
    await expect(page.getByTestId("overall")).toHaveText(/Being checked|Made · waiting for a check/);
    const text = await plain.innerText();
    expect(text).not.toMatch(/\b[0-9a-f]{12,}\b|receipt|R-[A-Z0-9]{4}|wren-|kestrel-|heron-|\bnot yet\b|\bplanned\b/i);
    await expect(page.getByTestId("plain-happened").locator("li").first()).toContainText("second volunteer");
    await page.getByTestId("view-switch").click();
    await expect(page.getByTestId("status-diagram")).toBeVisible();
    await expect(page).toHaveURL(/view=technical/);
    await page.getByTestId("view-switch").click();
    await expect(page.getByTestId("plain-status")).toBeVisible();
    await expect(page).not.toHaveURL(/view=technical/);
    await page.goto("/requests/example?moment=your-turn");
    await expect(page.getByTestId("overall")).toHaveText("Ready for your team");
    await expect(plain.locator('[data-band="4"]')).toContainText("Does this work for your team?");
    await expect(page).toHaveTitle(/^Ready for you · Your request · Eranos$/);
  });

  test("RequestStatusPage v6: a part nobody has picked up says when one of Eranos's own workers will, and says so when one did", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/requests/example?moment=planned");
    const waiting = page.getByTestId("waiting-1");
    await expect(waiting).toContainText("Waiting for a volunteer");
    await expect(waiting).toContainText("one of Eranos\u2019s own workers will pick it up.");
  });



  const MOMENTS: Record<string, Record<string, string>> = {
    received: { request: "noun", plan: "waiting" },
    planned: { plan: "done", "queue-1": "waiting", "worker-1": "idle", "review-1": "idle", "result-1": "idle" },
    working: { "queue-1": "done", "worker-1": "working", "review-1": "idle" },
    review: { "worker-1": "done", "review-1": "working", "result-1": "idle" },
    "your-turn": { "review-1": "approved", "result-1": "yourturn" },
    decided: { "result-1": "decided" },
  };

  for (const [moment, expected] of Object.entries(MOMENTS)) {
    test(`E04 at '${moment}' the nodes carry the recorded states, each with its receipt`, async ({ page }) => {
      await page.setViewportSize({ width: 1280, height: 800 });
      await page.goto(`/requests/example?moment=${moment}&view=technical`);
      const diagram = page.getByTestId("status-diagram");
      await expect(diagram).toBeVisible();
      for (const [node, state] of Object.entries(expected)) {
        await expect(page.locator(`[data-node="${node}"]`), `${moment} ${node}`).toHaveAttribute("data-state", state);
      }
      const unbacked = await page.$$eval("[data-node]", (nodes) =>
        nodes.filter((n) => n.getAttribute("data-state") !== "idle" && !n.getAttribute("data-receipt")).map((n) => n.getAttribute("data-node")),
      );
      expect(unbacked).toEqual([]);
      const box = await diagram.boundingBox();
      expect(box && box.width <= 1280 && box.height <= 424).toBe(true);
      await expect(page.getByTestId("mode-line")).toContainText("Replayed at reading speed. Nothing here was sent.");
    });
  }

  test("B2: once a part is delivered, 'Added to the shared library' links only records that open", async ({ page, request }) => {
    await page.goto("/requests/example?moment=working&view=technical");
    await expect(page.getByTestId("status-diagram")).toBeVisible();
    await expect(page.getByTestId("added-panel")).toHaveCount(0);
    await page.goto("/requests/example?moment=your-turn&view=technical");
    const panel = page.getByTestId("added-panel");
    await expect(panel).toContainText("Added to the shared library");
    const hrefs = await panel.locator("a").evaluateAll((links) => links.map((a) => a.getAttribute("href") ?? ""));
    expect(hrefs.length).toBeGreaterThan(1);
    for (const href of hrefs) {
      if (href.startsWith("/snapshot/")) {
        expect((await request.get(href)).status(), href).toBe(200);
      } else {
        await page.goto(href);
        await expect(page.getByRole("heading", { level: 1 }), href).toBeVisible();
        await expect(page.getByText("Page not found"), href).toHaveCount(0);
      }
    }
  });

  test("E05: replaying the example starts exactly one animation per fact, then nothing moves", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.addInitScript(() => {
      const calls: { cls: string; keyframes: string }[] = [];
      (window as unknown as { animateCalls: typeof calls }).animateCalls = calls;
      const real = Element.prototype.animate;
      Element.prototype.animate = function (keyframes, options) {
        calls.push({ cls: (this as Element).className.toString(), keyframes: JSON.stringify(keyframes) });
        return real.call(this, keyframes, options);
      };
    });
    await page.goto("/requests/example?speed=4&view=technical");
    await expect(page.locator('[data-node="result-1"]')).toHaveAttribute("data-state", "decided", { timeout: 10_000 });
    await page.waitForTimeout(1500);
    const calls = await page.evaluate(() => (window as unknown as { animateCalls: { cls: string }[] }).animateCalls);
    expect(calls.length).toBe(example.events.length - 1);
    // The worker's pickup sends the request's information along the edge to the worker.
    expect(calls.some((c) => c.cls === "er-packet")).toBe(true);
    await page.waitForTimeout(10_000);
    expect(await page.evaluate(() => document.getAnimations().length)).toBe(0);
  });

  test("E05: with reduced motion every cue is an opacity change, no transform", async ({ browser }) => {
    const context = await browser.newContext({ reducedMotion: "reduce", viewport: { width: 1280, height: 800 } });
    const page = await context.newPage();
    await page.addInitScript(() => {
      const frames: string[] = [];
      (window as unknown as { frames: string[] }).frames = frames;
      const real = Element.prototype.animate;
      Element.prototype.animate = function (keyframes, options) {
        frames.push(JSON.stringify(keyframes));
        return real.call(this, keyframes, options);
      };
    });
    await page.goto("/requests/example?speed=4&view=technical");
    await expect(page.locator('[data-node="result-1"]')).toHaveAttribute("data-state", "decided", { timeout: 10_000 });
    const frames = await page.evaluate(() => (window as unknown as { frames: string[] }).frames);
    expect(frames.length).toBeGreaterThan(0);
    expect(frames.filter((f) => f.includes("transform"))).toEqual([]);
    await context.close();
  });
});
