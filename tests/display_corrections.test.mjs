import assert from "node:assert/strict";
import test from "node:test";

import { isListed, withExactQuotes } from "../deploy/cloudflare/display_corrections.js";

const noun = (key, store = "eranos.solutions") => ({
  store,
  key,
  value: {
    report: {
      summary: "2 cited points. Short one. Other one.",
      claims: [
        { id: "C1", text: "Short one.", citations: [{ quote: "The exact, longer words with their qualifier." }] },
        { id: "C4", text: "Other one.", citations: [{ quote: "Its own words." }] },
      ],
    },
  },
});

test("a listed claim and the summary show the source's exact words; the input is untouched", () => {
  const input = noun("RPT-RC676414-01");
  const shown = withExactQuotes(input);
  assert.equal(shown.value.report.claims[0].text, "The exact, longer words with their qualifier.");
  assert.equal(shown.value.report.claims[0].shown_as_quote, true);
  assert.equal(shown.value.report.claims[1].text, "Other one.");
  assert.match(shown.value.report.summary, /exact, longer words/);
  assert.doesNotMatch(shown.value.report.summary, /Short one/);
  assert.equal(input.value.report.claims[0].text, "Short one.");
});

test("any other report or store is returned as it is", () => {
  const other = noun("RPT-OTHER-01");
  assert.equal(withExactQuotes(other), other);
  const draft = noun("RPT-RC676414-01", "eranos.drafts");
  assert.equal(withExactQuotes(draft), draft);
  assert.equal(withExactQuotes(null), null);
});

test("an off-topic claim and the source only it cites come off display, and the count follows", () => {
  const input = noun("RPT-RC676414-01");
  input.value.report.claims.push({ id: "C5", text: "Off topic.", citations: [{ source: "S2", quote: "Off." }] });
  input.value.report.claims[0].citations[0].source = "S1";
  input.value.report.claims[1].citations[0].source = "S1";
  input.value.report.sources = [{ id: "S1" }, { id: "S2" }];
  input.value.report.summary = "3 cited points from 2 public sources. Short one.";
  const shown = withExactQuotes(input).value.report;
  assert.deepEqual(shown.claims.map((c) => c.id), ["C1", "C4"]);
  assert.deepEqual(shown.sources, [{ id: "S1" }]);
  assert.match(shown.summary, /^2 cited points from 1 public source\./);
  assert.equal(input.value.report.claims.length, 3);
});

test("a report taken off display shows only a plain note and isn't listed; the input is untouched", () => {
  const input = noun("RPT-R9CE6D53-01");
  const shown = withExactQuotes(input).value.report;
  assert.deepEqual(shown.claims, []);
  assert.deepEqual(shown.sources, []);
  assert.equal(shown.taken_off_display, true);
  assert.match(shown.summary, /off display/);
  assert.equal(input.value.report.claims.length, 2);
  assert.equal(isListed({ key: "RPT-R9CE6D53-01" }), false);
  assert.equal(isListed({ key: "RPT-OTHER-01" }), true);
});

test("when the first claims come off, the summary names one that stays", () => {
  const input = noun("RPT-R4834064-01");
  input.value.report.claims = [
    { id: "C1", text: "One.", citations: [{ source: "S1", quote: "q" }] },
    { id: "C2", text: "Two.", citations: [{ source: "S1", quote: "q" }] },
    { id: "C3", text: "Three.", citations: [{ source: "S1", quote: "q" }] },
    { id: "C4", text: "Four.", citations: [{ source: "S1", quote: "q" }] },
    { id: "C5", text: "Five stays.", citations: [{ source: "S2", quote: "q" }] },
  ];
  input.value.report.sources = [{ id: "S1" }, { id: "S2" }];
  input.value.report.summary = "5 cited points from 2 public sources. One. Two. Three.";
  const shown = withExactQuotes(input).value.report;
  assert.equal(shown.summary, "1 cited point from 1 public source. Five stays.");
});

test("the word rule is for our own jargon: a tax term stays on a page", async () => {
  const { default: list } = await import("../deploy/cloudflare/banned_words.generated.js");
  if (list.source === "fixture") return;
  const { makeNeutral } = await import("../deploy/cloudflare/display_words.js");
  const neutral = makeNeutral(list);
  assert.equal(neutral("Gross receipts under $50,000 a year"), "Gross receipts under $50,000 a year");
  assert.equal(neutral("Keep donation receipts on file"), "Keep donation receipts on file");
  assert.equal(neutral("Every worker keeps receipts"), "Every worker keeps records");
});
