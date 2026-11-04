import { expect, test, type Page } from "@playwright/test";

import { LIVE, mockSite, noun, snapshot } from "./support/mocks";

// F-UI-STALE-001 and the review of 8d8f50a (G1, G2, N11): a request's steps, its details view and its history follow
// its real state. A library answer shows as checked only after a different key checked that it fits this request
// (reuse_checked, F-REUSE-001); a close settles the plan; a step that ran no model is never credited with one.
// These fixtures are the film request's own facts.

const PRINCIPAL = `r_${"ef".repeat(16)}`;
const REQUEST_ID = `rq-${PRINCIPAL}-mvywfy1j`;
const fact = (version: number, value: Record<string, unknown>, status = "open_for_build", at = 1_793_602_200) => ({
  version,
  created_at: at + version,
  value: { schema_version: 1, request_id: REQUEST_ID, status, event: { at: at + version, ...value } },
});

const RECEIVED = { type: "received", ref: REQUEST_ID };
const PLAN_CLAIMED = {
  type: "plan_claimed",
  ref: REQUEST_ID,
  worker: "dedicated worker 1 (run by ta-amps)",
  dedicated: true,
  method: "deterministic planner (no model)",
};
const REUSED = {
  type: "delivered",
  part: 1,
  ref: "eranos.solutions/RPT-RC676414-01",
  result_id: "RPT-RC676414-01",
  reason: "Found an existing reviewed answer: no new work and no new tokens.",
  summary: { model_tokens: 0, new_verbs: 0, reused: true, score: 0.7143 },
  worker: "dedicated worker 1 (run by ta-amps)",
  dedicated: true,
};
const FITS = {
  type: "reuse_checked",
  receipt: "e".repeat(64),
  verdict: "fits",
  checker_role: "dedicated worker 3 (run by ta-amps)",
  model: "muse-spark-1.3",
  similarity: 0.93,
  ref: "eranos.solutions/RPT-RC676414-01",
};
const CLOSED = { type: "closed", receipt: "c".repeat(64), worker: "dedicated worker 1 (run by ta-amps)", dedicated: true };
const REOPENED = { type: "reopened", receipt: "d".repeat(64), reason: "The library answer did not fit this request." };
const TEXT = "What are the key food-safety rules for a community food pantry, with a source for every point?";

interface StatusWords {
  about: Record<string, string>;
  log: Record<string, string>;
  plain: {
    chip: Record<string, string>;
    reopened_note: string;
    reopened_note_reason: string;
    reuse_rejected_note: string;
    no_result?: { title: string; why_no_sources: string; why_never_tried: string; can_do: string[] };
    bands: { status: Record<string, string>; reused: Record<string, string>; ready: Record<string, string> };
  };
}

async function open(page: Page, facts: Record<string, unknown>[], closedAt: number[], status: string, technical = false): Promise<void> {
  await mockSite(page, {
    history: facts.map((value, i) => fact(i + 1, value, closedAt.includes(i) ? "closed" : "open_for_build")),
    request: { request_id: REQUEST_ID, status, text: TEXT, ...(status === "closed" ? { close_receipt: "c".repeat(64) } : {}) },
  });
  await page.goto(`/requests/${REQUEST_ID}${technical ? "?view=technical" : ""}`);
}

const station = (page: Page, n: number) => page.getByTestId("request-track").locator(`li[data-step="${n}"]`);

test.describe("on the hosted build, a request's steps follow its real state", () => {
  test.use({ baseURL: LIVE });

  test("closed by a library answer nobody checked for it: similar, nothing made, not checked for this request", async ({ page }) => {
    const words = noun<StatusWords>("request-status");
    const w = words.plain;
    await open(page, [RECEIVED, PLAN_CLAIMED, REUSED, CLOSED], [3], "closed");
    await expect(page.getByTestId("overall")).toHaveText(w.chip.reused_unchecked ?? "");
    await expect(page.getByTestId("band-status-1")).toHaveText(w.bands.status.reused_sorted ?? "");
    await expect(page.getByTestId("band-status-2")).toHaveText(w.bands.status.reused_made ?? "");
    await expect(page.getByTestId("band-status-3")).toHaveText(w.bands.status.reuse_unchecked ?? "");
    await expect(page.getByTestId("band-status-4")).toContainText((w.bands.status.reused_ready ?? "").split(" · ")[0] ?? "");
    await expect(page.locator('[data-band="3"]')).not.toHaveAttribute("data-state", "done");
    // The answer step is open and links the answer; Made, In line for a check and Checked are passed, not done.
    await expect(page.getByTestId("band-toggle-4")).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByTestId("reused-ready").getByRole("link")).toHaveAttribute("href", "/api/nouns/eranos.solutions/RPT-RC676414-01");
    for (const n of [0, 1, 5]) await expect(station(page, n)).toHaveAttribute("data-state", "done");
    for (const n of [2, 3, 4]) await expect(station(page, n)).toHaveAttribute("data-state", "skipped");
    await page.getByTestId("band-toggle-3").click();
    await expect(page.getByTestId("reused-checked")).toHaveText(w.bands.reused.unchecked ?? "");
    const text = await page.locator("main").innerText();
    expect(text).not.toContain("Matched");
    expect(text).not.toContain(words.about.hosted ?? "in line for a volunteer");
  });

  test("a library answer a different key checked: step 3 done, Checked on the track, the checker named", async ({ page }) => {
    const w = noun<StatusWords>("request-status").plain;
    await open(page, [RECEIVED, PLAN_CLAIMED, REUSED, FITS, CLOSED], [4], "closed");
    await expect(page.getByTestId("overall")).toHaveText(w.chip.reused ?? "");
    await expect(page.locator('[data-band="3"]')).toHaveAttribute("data-state", "done");
    await expect(page.getByTestId("band-status-3")).toContainText((w.bands.status.reuse_fits ?? "").split(" · ")[0] ?? "");
    for (const n of [3, 4, 5]) await expect(station(page, n)).toHaveAttribute("data-state", "done");
    await expect(station(page, 2)).toHaveAttribute("data-state", "skipped");
    await page.getByTestId("band-toggle-3").click();
    await expect(page.getByTestId("reused-checked")).toContainText(w.bands.reused.fits ?? "");
    await expect(page.getByTestId("reused-checked")).toContainText("dedicated worker 3 (run by ta-amps)");
  });

  test("the details view of a library answer: no delivered part, its own history row, no model for the planner", async ({ page }) => {
    const words = noun<StatusWords>("request-status");
    await open(page, [RECEIVED, PLAN_CLAIMED, REUSED, CLOSED], [3], "closed", true);
    await expect(page.locator("main")).toContainText(words.log.closed_reused ?? "");
    await expect(page.locator("main")).toContainText(words.log.reused ?? "");
    const text = await page.locator("main").innerText();
    expect(text).not.toContain("Part 1 delivered");
    expect(text).not.toContain("All parts finished");
    expect(text).not.toMatch(/Split\s*0 parts/);
  });

  test("opened again after a library answer: back in line, the answer kept only in the history", async ({ page }) => {
    const w = noun<StatusWords>("request-status").plain;
    await open(page, [RECEIVED, PLAN_CLAIMED, REUSED, CLOSED, REOPENED], [3], "open_for_build");
    await expect(page.getByTestId("reopened-note")).toHaveText(w.reopened_note ?? "");
    await expect(page.getByTestId("overall")).not.toHaveText(w.chip.reused ?? "");
    await expect(page.getByTestId("band-toggle-1")).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByTestId("band-status-1")).toHaveText(w.bands.status.sorting ?? "");
    await expect(page.getByTestId("reused-ready")).toHaveCount(0);
    await expect(station(page, 0)).toHaveAttribute("data-state", "now");
  });

  test("opened again with no library answer: the note gives the recorded reason, not a wrong-answer story", async ({ page }) => {
    const w = noun<StatusWords>("request-status").plain;
    await open(page, [RECEIVED, PLAN_CLAIMED, CLOSED, REOPENED], [2], "open_for_build");
    await expect(page.getByTestId("reopened-note")).toHaveText((w.reopened_note_reason ?? "").replace("{reason}", REOPENED.reason));
  });

  test("a library answer, reopened, then closed again: closed with no result, nothing in line, nothing reused", async ({ page }) => {
    const words = noun<StatusWords>("request-status");
    const w = words.plain;
    const CLOSED_AGAIN = { ...CLOSED, receipt: "f".repeat(64) };
    await open(page, [RECEIVED, PLAN_CLAIMED, REUSED, CLOSED, REOPENED, CLOSED_AGAIN], [3, 5], "closed");
    await expect(page.getByTestId("overall")).toHaveText(w.chip.unfinished ?? "");
    for (const n of [1, 2, 3, 4]) await expect(page.getByTestId(`band-status-${n}`)).toHaveText(w.bands.status.closed ?? "");
    await expect(page.getByTestId("reused-ready")).toHaveCount(0);
    const text = await page.locator("main").innerText();
    expect(text).not.toContain(words.about.hosted ?? "in line for a volunteer");
    // The details' one-line summary reads only what happened since the reopen.
    await page.goto(`/requests/${REQUEST_ID}?view=technical`);
    await expect(page.locator("main")).toContainText(words.log.closed_unfinished ?? "");
    await expect(page.getByTestId("overall")).not.toHaveText(w.chip.reused ?? "");
  });

  test("closed with no result: closed steps, no token, and in the details no planning and no model for the planner", async ({ page }) => {
    const words = noun<StatusWords>("request-status");
    const w = words.plain;
    await open(page, [RECEIVED, PLAN_CLAIMED, CLOSED], [2], "closed");
    await expect(page.getByTestId("overall")).toHaveText(w.chip.unfinished ?? "");
    for (const n of [1, 2, 3, 4]) await expect(page.getByTestId(`band-status-${n}`)).toHaveText(w.bands.status.closed ?? "");
    await expect(station(page, 0)).toHaveAttribute("data-state", "closed");
    await expect(page.getByTestId("track-token")).toHaveCount(0);
    await page.goto(`/requests/${REQUEST_ID}?view=technical`);
    await expect(page.locator("main")).toContainText(words.log.closed_unfinished ?? "");
    const text = await page.locator("main").innerText();
    expect(text).not.toContain("Being worked on");
    expect(text).not.toContain("All parts finished");
    expect(text).not.toContain("Muse");
    expect(text).toContain(words.log.closed_unfinished ?? "");
  });

  test("closed with nothing delivered after searches: says what happened and what to do, with a way to ask again", async ({ page }) => {
    const w = noun<StatusWords>("request-status").plain;
    const receipt = (c: string) => c.repeat(64);
    const noClaims = { type: "work_released", part: 1, reason: "self-test failed: the report makes no cited claims; only 0 claims kept a verbatim quote", summary: { claims: 0 } };
    await open(
      page,
      [
        RECEIVED,
        PLAN_CLAIMED,
        { type: "work_claimed", part: 1, receipt: receipt("a") },
        { ...noClaims, receipt: receipt("b") },
        { type: "work_claimed", part: 1, receipt: receipt("c") },
        { ...noClaims, receipt: receipt("d") },
        CLOSED,
      ],
      [2],
      "closed",
    );
    const panel = page.getByTestId("no-result");
    await expect(panel).toContainText(w.no_result?.title ?? "missing");
    await expect(page.getByTestId("no-result-why")).toContainText((w.no_result?.why_no_sources ?? "").replace("{n}", "2"));
    await expect(panel.getByRole("listitem")).toHaveCount(w.no_result?.can_do.length ?? -1);
    await expect(page.getByTestId("no-result-again")).toHaveAttribute("href", /^\/nonprofits/);
  });

  test("closed with nothing delivered and no search that came back empty: it never says we searched", async ({ page }) => {
    const w = noun<StatusWords>("request-status").plain;
    await open(page, [RECEIVED, PLAN_CLAIMED, CLOSED], [2], "closed");
    await expect(page.getByTestId("no-result-why")).toContainText(w.no_result?.why_never_tried ?? "missing");
    await expect(page.getByTestId("no-result-why")).not.toContainText("searched");
  });

  // The worker loop's checked reuse (F-REUSE-001, worker-loop-next 6684c6c), in its exact order: planned (part 1, route
  // reuse_check), check_claimed, reuse_checked, then on "fits" a delivered with summary.reused, plan_claimed and closed.
  const RPT = "RPT-RC676414-01";
  const PLAN_REUSE_CHECK = {
    type: "planned",
    receipt: "b".repeat(64),
    worker: "dedicated worker 1 (run by ta-amps)",
    dedicated: true,
    parts: [{ part: 1, route: "reuse_check", text: TEXT, reused_from: { report_id: RPT }, review_task_id: "t-reuse-review-1" }],
  };
  const CHECK_CLAIMED = { type: "check_claimed", part: 1, receipt: "1".repeat(64), worker: "dedicated worker 3 (run by ta-amps)", dedicated: true, model: "muse-spark-1.3" };
  const verdict = (v: "fits" | "does_not_fit") => ({
    type: "reuse_checked",
    part: 1,
    receipt: "2".repeat(64),
    verdict: v,
    checker_role: "dedicated worker 3 (run by ta-amps)",
    model: "muse-spark-1.3",
    model_name: "Muse Spark 1.3",
    similarity: 0.83,
    ref: `eranos.solutions/${RPT}`,
  });
  const DELIVERED_REUSED = { type: "delivered", part: 1, ref: `eranos.solutions/${RPT}`, result_id: RPT, summary: { reused: true, score: 0.83 }, worker: "dedicated worker 1 (run by ta-amps)", dedicated: true };
  const PLAN_CLAIMED_AGAIN = { ...PLAN_CLAIMED, ref: undefined, receipt: "3".repeat(64) };
  const CLOSED_FINAL = { ...CLOSED, receipt: "4".repeat(64) };
  const NEW_PLAN = { type: "planned", receipt: "5".repeat(64), worker: "dedicated worker 1 (run by ta-amps)", dedicated: true, parts: [{ part: 1, route: "public-only", text: TEXT, report_id: "RPT-RNEWWORK-01" }] };

  test("a checked reuse, in the worker's order (fits): answered from the library, checked for this request", async ({ page }) => {
    const words = noun<StatusWords>("request-status");
    const w = words.plain;
    const facts = [RECEIVED, PLAN_CLAIMED, PLAN_REUSE_CHECK, CHECK_CLAIMED, verdict("fits"), DELIVERED_REUSED, PLAN_CLAIMED_AGAIN, CLOSED_FINAL];
    await open(page, facts, [7], "closed");
    await expect(page.getByTestId("overall")).toHaveText(w.chip.reused ?? "");
    await expect(page.locator('[data-band="3"]')).toHaveAttribute("data-state", "done");
    await expect(page.getByTestId("band-status-3")).toContainText((w.bands.status.reuse_fits ?? "").split(" · ")[0] ?? "");
    await expect(page.getByTestId("band-status-2")).toHaveText(w.bands.status.reused_made ?? "");
    for (const n of [3, 4, 5]) await expect(station(page, n)).toHaveAttribute("data-state", "done");
    await expect(station(page, 2)).toHaveAttribute("data-state", "skipped");
    await expect(page.getByTestId("reused-ready").getByRole("link")).toHaveAttribute("href", `/api/nouns/eranos.solutions/${RPT}`);
    // The details view: no new work, no "Part 1 delivered", the reuse check named.
    await page.goto(`/requests/${REQUEST_ID}?view=technical`);
    await expect(page.locator("main")).toContainText(words.log.reused ?? "");
    const text = await page.locator("main").innerText();
    expect(text).not.toContain("Part 1 delivered");
    expect(text).toContain(words.log.planned_reuse_check ?? "");
    expect(text).toContain(words.log.reuse_fits ?? "");
  });

  test("a checked reuse with the delivery before the verdict still counts the check", async ({ page }) => {
    const w = noun<StatusWords>("request-status").plain;
    const facts = [RECEIVED, PLAN_CLAIMED, PLAN_REUSE_CHECK, CHECK_CLAIMED, DELIVERED_REUSED, verdict("fits"), CLOSED_FINAL];
    await open(page, facts, [6], "closed");
    await expect(page.getByTestId("overall")).toHaveText(w.chip.reused ?? "");
    await expect(page.locator('[data-band="3"]')).toHaveAttribute("data-state", "done");
  });

  test("while the fit is checked: checking whether an earlier answer fits, nothing made, nothing delivered", async ({ page }) => {
    const words = noun<StatusWords>("request-status");
    const w = words.plain;
    await open(page, [RECEIVED, PLAN_CLAIMED, PLAN_REUSE_CHECK, CHECK_CLAIMED], [], "open_for_build");
    await expect(page.getByTestId("overall")).toHaveText(w.chip.reuse_checking ?? "");
    await expect(page.getByTestId("band-status-3")).toHaveText(w.bands.status.reuse_checking ?? "");
    await expect(page.getByTestId("band-toggle-3")).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByTestId("reused-checked")).toHaveText(w.bands.reused.checking ?? "");
    await expect(page.getByTestId("band-status-4")).toHaveText(w.bands.status.upcoming ?? "");
    await expect(station(page, 5)).not.toHaveAttribute("data-state", "done");
    await page.goto(`/requests/${REQUEST_ID}?view=technical`);
    await expect(page.locator("main")).toContainText(words.log.planned_reuse_check ?? "");
    expect(await page.locator("main").innerText()).not.toContain("Part 1 delivered");
  });

  test("does not fit: the library answer is rejected, the note says so, and the new work is followed", async ({ page }) => {
    const w = noun<StatusWords>("request-status").plain;
    const facts = [RECEIVED, PLAN_CLAIMED, PLAN_REUSE_CHECK, CHECK_CLAIMED, verdict("does_not_fit"), NEW_PLAN];
    await open(page, facts, [], "open_for_build");
    await expect(page.getByTestId("reuse-rejected-note")).toHaveText(w.reuse_rejected_note ?? "");
    await expect(page.getByTestId("overall")).not.toHaveText(w.chip.reused ?? "");
    await expect(page.getByTestId("overall")).not.toHaveText(w.chip.reuse_checking ?? "");
    await expect(page.getByTestId("reused-ready")).toHaveCount(0);
    // The new plan's part is waiting for a helper, as any planned part.
    await expect(page.locator('[data-band="1"]')).toHaveAttribute("data-state", "done");
    await expect(page.locator('[data-band="2"]')).toHaveAttribute("data-state", "now");
  });

  test("at 390 px no request state pushes the page sideways, and the passed stations read as not done", async ({ page }) => {
    test.setTimeout(60_000);
    await page.setViewportSize({ width: 390, height: 844 });
    const states: [string, Record<string, unknown>[], number[], string][] = [
      ["library answer, not checked", [RECEIVED, PLAN_CLAIMED, REUSED, CLOSED], [3], "closed"],
      ["library answer, checked", [RECEIVED, PLAN_CLAIMED, PLAN_REUSE_CHECK, CHECK_CLAIMED, verdict("fits"), DELIVERED_REUSED, PLAN_CLAIMED_AGAIN, CLOSED_FINAL], [7], "closed"],
      ["checking the fit", [RECEIVED, PLAN_CLAIMED, PLAN_REUSE_CHECK, CHECK_CLAIMED], [], "open_for_build"],
      ["did not fit", [RECEIVED, PLAN_CLAIMED, PLAN_REUSE_CHECK, CHECK_CLAIMED, verdict("does_not_fit"), NEW_PLAN], [], "open_for_build"],
      ["closed, no result", [RECEIVED, PLAN_CLAIMED, CLOSED], [2], "closed"],
      ["opened again", [RECEIVED, PLAN_CLAIMED, REUSED, CLOSED, REOPENED], [3], "open_for_build"],
    ];
    const wide: string[] = [];
    for (const [label, facts, closedAt, status] of states) {
      await page.unrouteAll();
      await open(page, facts, closedAt, status);
      await expect(page.getByTestId("overall")).toBeVisible();
      await page.waitForTimeout(300);
      for (const view of ["", "?view=technical"]) {
        if (view) await page.goto(`/requests/${REQUEST_ID}${view}`);
        await expect(page.getByTestId("overall")).toBeVisible();
        const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
        if (over > 0) wide.push(`${label}${view}: ${over}px`);
      }
    }
    expect(wide).toEqual([]);
    // Unchecked: "In line for a check" and "Checked" are not done, not "not needed".
    const words = noun<{ plain: { track: Record<string, string> } }>("request-status").plain.track;
    await page.unrouteAll();
    await open(page, [RECEIVED, PLAN_CLAIMED, REUSED, CLOSED], [3], "closed");
    await expect(station(page, 4)).toHaveAttribute("data-state", "skipped");
    await expect(station(page, 4)).toContainText(`(${words.not_done})`);
  });

  test("a planner claim that ran no model is shown as such while it plans", async ({ page }) => {
    await open(page, [RECEIVED, PLAN_CLAIMED], [], "open_for_build", true);
    await expect(page.locator("main")).toContainText("deterministic planner (no model)");
    expect(await page.locator("main").innerText()).not.toContain("Muse");
  });
});

test.describe("a kit built from a request", () => {
  test.use({ baseURL: LIVE });
  const KIT = "KIT-HOTLINE-02";
  async function kitPage(page: Page, requestText: string): Promise<void> {
    await mockSite(page, {});
    const entry = snapshot<{ tags?: string[] }>(`catalog/${KIT}.json`);
    await page.route(new RegExp(`/api/catalog/${KIT}`), (route) =>
      route.fulfill({ json: { ...entry, tags: [...(entry.tags ?? []), `request:${REQUEST_ID}`] } }),
    );
    await page.route(new RegExp(`/api/requests/${REQUEST_ID}`), (route) => route.fulfill({ json: { value: { text: requestText } } }));
    await page.goto(`/catalog/${KIT}`);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  }

  test("a labeled test request: the kit says so and links to it", async ({ page }) => {
    await kitPage(page, "Clean our bed list. Test run, Nov 4.");
    const line = page.getByTestId("kit-from-test");
    await expect(line).toContainText("test request");
    await expect(line).toContainText("Clean our bed list. Test run, Nov 4.");
    await expect(line.getByRole("link")).toHaveAttribute("href", `/requests/${REQUEST_ID}`);
  });

  test("any other request: nothing says test", async ({ page }) => {
    await kitPage(page, "Clean our bed list.");
    await page.waitForTimeout(500);
    await expect(page.getByTestId("kit-from-test")).toHaveCount(0);
  });
});
