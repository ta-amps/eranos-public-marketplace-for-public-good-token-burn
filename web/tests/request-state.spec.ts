import { expect, test } from "@playwright/test";

import { LIVE, mockSite, noun } from "./support/mocks";

// F-UI-STALE-001 (Nov 2): the film's request was closed by a library reuse, yet its page said "Being sorted" and
// "In line", with every step "Waiting to start", while its own history said it was closed and answered from the
// library. The steps now come from the request's real state. These fixtures are the film request's own facts.

const PRINCIPAL = `r_${"ef".repeat(16)}`;
const REQUEST_ID = `rq-${PRINCIPAL}-mvywfy1j`;
const fact = (version: number, value: Record<string, unknown>, status = "open_for_build", at = 1_793_602_200) => ({
  version,
  created_at: at + version,
  value: { schema_version: 1, request_id: REQUEST_ID, status, event: { at: at + version, ...value } },
});

const RECEIVED = { type: "received", ref: REQUEST_ID };
const PLAN_CLAIMED = { type: "plan_claimed", ref: REQUEST_ID, worker: "dedicated worker 1 (run by ta-amps)", dedicated: true, method: "deterministic planner (no model)" };
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
const CLOSED = { type: "closed", receipt: "c".repeat(64), worker: "dedicated worker 1 (run by ta-amps)", dedicated: true };
const REOPENED = { type: "reopened", receipt: "d".repeat(64), reason: "The library answer did not fit this request." };
const TEXT = "What are the key food-safety rules for a community food pantry, with a source for every point?";

interface StatusWords {
  plain: {
    chip: Record<string, string>;
    reopened_note: string;
    bands: { status: Record<string, string>; reused: Record<string, string>; ready: Record<string, string> };
  };
}

test.describe("on the hosted build, a request's steps follow its real state", () => {
  test.use({ baseURL: LIVE });

  test("closed by a library reuse: the top and every step say it was answered from the library", async ({ page }) => {
    const words = noun<StatusWords>("request-status").plain;
    const facts = [RECEIVED, PLAN_CLAIMED, REUSED, CLOSED];
    await mockSite(page, {
      history: facts.map((value, i) => fact(i + 1, value, i === facts.length - 1 ? "closed" : "open_for_build")),
      request: { request_id: REQUEST_ID, status: "closed", text: TEXT, close_receipt: "c".repeat(64) },
    });
    await page.goto(`/requests/${REQUEST_ID}`);
    await expect(page.getByTestId("overall")).toHaveText(words.chip.reused ?? "");
    for (const n of [1, 2, 3, 4]) {
      const status = page.getByTestId(`band-status-${n}`);
      await expect(status).not.toHaveText(words.bands.status.upcoming ?? "");
      await expect(status).not.toHaveText(words.bands.status.sorting ?? "");
    }
    await expect(page.getByTestId("band-status-1")).toHaveText(words.bands.status.reused_sorted ?? "");
    await expect(page.getByTestId("band-status-2")).toHaveText(words.bands.status.reused_made ?? "");
    await expect(page.getByTestId("band-status-3")).toHaveText(words.bands.status.reused_checked ?? "");
    await expect(page.getByTestId("band-status-4")).toContainText((words.bands.status.reused_ready ?? "").split(" · ")[0] ?? "");
    // The last step is open and links the answer it reused; the track ends delivered, not "In line".
    await expect(page.getByTestId("band-toggle-4")).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByTestId("reused-ready")).toContainText(words.bands.ready.reused ?? "");
    await expect(page.getByTestId("reused-ready").getByRole("link")).toHaveAttribute("href", "/api/nouns/eranos.solutions/RPT-RC676414-01");
    await expect(page.getByTestId("request-track").locator('li[data-step="0"]')).toHaveAttribute("data-state", "done");
    await expect(page.getByTestId("request-track").locator('[aria-current="step"]')).toHaveCount(0);
    const main = await page.locator("main").innerText();
    expect(main).not.toContain(words.chip.planning ?? "Being sorted");
  });

  test("opened again after a wrong reuse: back in line, the reuse kept only in the history", async ({ page }) => {
    const words = noun<StatusWords>("request-status").plain;
    const facts = [RECEIVED, PLAN_CLAIMED, REUSED, CLOSED, REOPENED];
    await mockSite(page, {
      history: facts.map((value, i) => fact(i + 1, value, i === 3 ? "closed" : "open_for_build")),
      request: { request_id: REQUEST_ID, status: "open_for_build", text: TEXT },
    });
    await page.goto(`/requests/${REQUEST_ID}`);
    await expect(page.getByTestId("reopened-note")).toHaveText(words.reopened_note ?? "");
    await expect(page.getByTestId("overall")).not.toHaveText(words.chip.reused ?? "");
    await expect(page.getByTestId("overall")).not.toHaveText(words.chip.unfinished ?? "");
    // Step 1 is current again; nothing claims the library answered it.
    await expect(page.getByTestId("band-toggle-1")).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByTestId("band-status-1")).toHaveText(words.bands.status.sorting ?? "");
    await expect(page.getByTestId("reused-ready")).toHaveCount(0);
    await expect(page.getByTestId("request-track").locator('li[data-step="0"]')).toHaveAttribute("data-state", "now");
  });

  test("closed with no result: the steps it never reached say closed, not waiting to start", async ({ page }) => {
    const words = noun<StatusWords>("request-status").plain;
    const facts = [RECEIVED, PLAN_CLAIMED, CLOSED];
    await mockSite(page, {
      history: facts.map((value, i) => fact(i + 1, value, i === facts.length - 1 ? "closed" : "open_for_build")),
      request: { request_id: REQUEST_ID, status: "closed", text: TEXT, close_receipt: "c".repeat(64) },
    });
    await page.goto(`/requests/${REQUEST_ID}`);
    await expect(page.getByTestId("overall")).toHaveText(words.chip.unfinished ?? "");
    for (const n of [1, 2, 3, 4]) await expect(page.getByTestId(`band-status-${n}`)).toHaveText(words.bands.status.closed ?? "");
    await expect(page.getByTestId("request-track").locator('li[data-step="0"]')).toHaveAttribute("data-state", "closed");
    await expect(page.getByTestId("track-token")).toHaveCount(0);
  });
});
