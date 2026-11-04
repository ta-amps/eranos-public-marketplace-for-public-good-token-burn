import assert from "node:assert/strict";
import test from "node:test";

import { withExactQuotes } from "../deploy/cloudflare/display_corrections.js";

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
