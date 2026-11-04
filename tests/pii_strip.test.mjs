import assert from "node:assert/strict";
import { test } from "node:test";
import { stripPii, stripPiiForDisplay } from "../deploy/cloudflare/pii_strip.js";

// The module itself is tested with the shim, its first home. This is how Eranos uses it: result text loses personal data;
// a source's own quote keeps public contact details; a digest-bound record and identifiers stay exactly as stored.
test("Eranos display", () => {
  const data = {
    id: "PRC-29023C-01",
    report: "Ask ana@gmail.com or call 617-204-8831. See 2 CFR 200.329.",
    claims: [{ quote: "Call 1-800-373-7888 for help.", url: "https://example.org/a", text: "reach 0917-123-4567" }],
    record: { blob_sha256: "abc", note: "ana@gmail.com" },
  };
  const out = stripPiiForDisplay(data);
  assert.equal(out.id, data.id);
  assert.equal(out.report, "Ask [email] or call [phone]. See 2 CFR 200.329.");
  assert.equal(out.claims[0].quote, data.claims[0].quote);
  assert.equal(out.claims[0].text, "reach [phone]");
  assert.deepEqual(out.record, data.record);
  assert.equal(stripPii("250-500 words"), "250-500 words");
});
