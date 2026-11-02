import { expect, test, type Page } from "@playwright/test";

import { LIVE, mockSite, noun } from "./support/mocks";

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

  test("a planner claim that ran no model is shown as such while it plans", async ({ page }) => {
    await open(page, [RECEIVED, PLAN_CLAIMED], [], "open_for_build", true);
    await expect(page.locator("main")).toContainText("deterministic planner (no model)");
    expect(await page.locator("main").innerText()).not.toContain("Muse");
  });
});
