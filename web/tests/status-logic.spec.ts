import { createHash } from "node:crypto";

import { expect, test } from "@playwright/test";

import type { RequestStatusNoun } from "../src/lib/nouns";
import { applyEvents, deriveView } from "../src/lib/status/derive";
import { ordinal, pickupEstimate, placeLine } from "../src/lib/status/estimate";
import type { RequestExampleNoun } from "../src/lib/status/example";
import { canonicalJson } from "../src/lib/status/receipts";
import type { StatusEvent, StatusRecord } from "../src/lib/status/types";
import { noun } from "./support/mocks";

// Pure logic, no page: the pick-up estimate (E06), the receipt formula and the rule that no step shows a state
// without the record behind it (E04).

const words = noun<RequestStatusNoun>("request-status");
const example = noun<RequestExampleNoun>("request-example");
const NOW = 1_800_000_000;
const options = {
  now: NOW,
  formatTime: (at: number) => String(at),
  formatClock: (at: number) => String(at),
  resultHref: (part: number) => `/r/${part}`,
};

test.describe("E06 pick-up estimate", () => {
  const recent = (n: number, gap = 3600) => Array.from({ length: n }, (_, i) => NOW - (i + 1) * gap);

  test("is the 25th to 75th percentile of the last 50 claim delays", () => {
    // 60 delays: the 10 oldest are huge and must be ignored; the last 50 run from 5 to 20 minutes.
    const old = Array.from({ length: 10 }, () => 50_000);
    const last = Array.from({ length: 50 }, (_, i) => 300 + (i * 900) / 49);
    const estimate = pickupEstimate({ claim_delays_s: [...old, ...last], claim_times: recent(60), as_of: NOW }, NOW);
    expect(estimate).not.toBeNull();
    // p25 = 300 + 0.25 * 900 = 525 s (8.75 min, rounded down); p75 = 975 s (16.25 min, rounded up).
    expect(estimate).toEqual({ low: 8, high: 17 });
  });

  test("is hidden with fewer than 10 claims in the last 7 days", () => {
    const delays = Array.from({ length: 50 }, () => 600);
    const times = [...recent(9), ...Array.from({ length: 41 }, (_, i) => NOW - 8 * 86_400 - i)];
    expect(pickupEstimate({ claim_delays_s: delays, claim_times: times, as_of: NOW }, NOW)).toBeNull();
  });

  test("is hidden when no claim happened in the last 24 hours", () => {
    const delays = Array.from({ length: 50 }, () => 600);
    const times = Array.from({ length: 50 }, (_, i) => NOW - 2 * 86_400 - i * 60);
    expect(pickupEstimate({ claim_delays_s: delays, claim_times: times, as_of: NOW }, NOW)).toBeNull();
  });

  test("reads '2nd in line · usually 5–20 min'", () => {
    const delays = [...Array.from({ length: 25 }, () => 300), ...Array.from({ length: 25 }, () => 1200)];
    // With 25 values of 5 min and 25 of 20 min, p25 is 5 min and p75 is 20 min exactly.
    const estimate = pickupEstimate({ claim_delays_s: delays, claim_times: recent(50, 1200), as_of: NOW }, NOW);
    expect(placeLine({ in_line: words.chips.in_line ?? "", estimate: words.chips.estimate ?? "" }, 2, estimate)).toBe(
      "2nd in line · usually 5–20 min",
    );
    expect(placeLine({ in_line: words.chips.in_line ?? "", estimate: words.chips.estimate ?? "" }, 2, null)).toBe("2nd in line");
    expect([1, 2, 3, 4, 11, 12, 13, 21, 22, 23].map(ordinal)).toEqual(["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd", "23rd"]);
  });
});

test("claim receipts are Tessera's formula on the claimed event", () => {
  const input = { namespace: "main", task_id: "rq-r_x-1", fencing_token: 1, claimed_at: 1793474821.467 };
  expect(canonicalJson(input)).toBe('{"claimed_at":1793474821.467,"fencing_token":1,"namespace":"main","task_id":"rq-r_x-1"}');
  const event = example.events.find((e) => e.type === "work_claimed");
  const part = example.events.find((e) => e.type === "planned")?.parts?.[0];
  const expected = createHash("sha256")
    .update(canonicalJson({ namespace: "main", task_id: part?.work_task_id, fencing_token: 1, claimed_at: event?.at }))
    .digest("hex");
  expect(event?.receipt).toBe(expected);
});

test.describe("E04 no step shows a state without its record", () => {
  test("every non-idle node names the receipt or record behind it, at every moment of the example", () => {
    for (const count of Object.values(example.moments)) {
      const record: StatusRecord = { mode: "example", request: example.request, events: example.events.slice(0, count), estimate: example.queue_estimate };
      const view = deriveView(record, words, options);
      const known = new Set(example.events.flatMap((e) => [e.receipt, e.ref]).filter(Boolean));
      for (const node of view.nodes) {
        if (node.state === "idle") continue;
        expect(node.evidence, `${node.id} at ${count}`).toBeTruthy();
        expect(known.has(node.evidence) || node.evidence === example.request.id, `${node.id}: ${node.evidence}`).toBe(true);
      }
    }
  });

  test("a fact without a receipt or a record changes nothing", () => {
    const planned = example.events.slice(0, 3);
    const unproven: StatusEvent = { type: "work_claimed", part: 1, at: NOW, worker: "someone" };
    const facts = applyEvents([...planned, unproven]);
    expect(facts.parts[0]?.work).toBe("waiting");
    const proven = applyEvents([...planned, { ...unproven, receipt: "a".repeat(64) }]);
    expect(proven.parts[0]?.work).toBe("working");
  });

  test("a live part stays open until its check is recorded on the public record", () => {
    const planned = example.events.slice(0, 3);
    const view = deriveView({ mode: "live", request: example.request, events: planned }, words, options);
    expect(view.nodes.find((n) => n.id === "queue-1")?.state).toBe("open");
    expect(view.nodes.find((n) => n.id === "worker-1")?.state).toBe("idle");
    const reviewed = deriveView(
      { mode: "live", request: example.request, events: [...planned, { type: "in_review", part: 1, at: null, ref: "eranos.requests/x part 1" }] },
      words,
      options,
    );
    expect(reviewed.nodes.find((n) => n.id === "review-1")?.state).toBe("working");
    expect(reviewed.nodes.find((n) => n.id === "review-1")?.evidence).toBe("eranos.requests/x part 1");
  });
});
