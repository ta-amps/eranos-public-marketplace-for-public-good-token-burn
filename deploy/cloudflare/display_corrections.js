// Corrections to what pages and reads show of delivered reports. A stored record is never changed, and a shown record
// says what was changed. From a read of every delivered report on Nov 4; the list is in COORDINATION.
const SHOWN_AS_QUOTES = { "RPT-RC676414-01": ["C1", "C2", "C3"] };
const OFF_TOPIC = {
  "RPT-RC676414-01": ["C5", "C6"],
  "RPT-R418249C-01": ["C5"],
  "RPT-R4834064-01": ["C1", "C2", "C3", "C4"],
  "RPT-R53372FA-01": ["C2"],
  "RPT-R7B15D81-01": ["C2"],
};
const TAKEN_OFF = new Set([
  "RPT-R9CE6D53-01",
  "RPT-R709418C-01",
  "RPT-RD865E06-01",
  "RPT-RF92DA4E-01",
  "RPT-RF0D3C3D-01",
  "RPT-R1087361-01",
  "RPT-R2629BD5-01",
  "RPT-R30F07F9-01",
  "RPT-R364D880-01",
  "RPT-R3DC7D0A-01",
  "RPT-R662CA2B-01",
  "RPT-R7E76ADA-01",
  "RPT-R7EF1806-01",
  "RPT-R81E610E-01",
  "RPT-R89864E8-01",
  "RPT-R8A6EAE9-01",
  "RPT-R8F5EC63-01",
  "RPT-R9C79B12-01",
  "RPT-RA1FAFC6-01",
  "RPT-RD9152EF-01",
  "RPT-RB7F38AF-01",
  "RPT-RC80830D-01",
]);
const TAKEN_OFF_NOTE = "We took this report off display: its sources didn't answer the question. Please ask again, with a link to a page you trust if you have one.";
const COUNT_LINE = /^\d+ cited points? from \d+ public sources?\./;

function countLine(claims, sources) {
  return `${claims.length} cited point${claims.length === 1 ? "" : "s"} from ${sources.length} public source${sources.length === 1 ? "" : "s"}.`;
}

export function withExactQuotes(noun) {
  const report = noun?.value?.report;
  if (noun?.store !== "eranos.solutions" || !report || !Array.isArray(report.claims)) return noun;
  if (TAKEN_OFF.has(noun.key)) {
    return { ...noun, value: { ...noun.value, report: { ...report, claims: [], sources: [], summary: TAKEN_OFF_NOTE, taken_off_display: true } } };
  }
  const exact = SHOWN_AS_QUOTES[noun.key] ?? [];
  const off = OFF_TOPIC[noun.key] ?? [];
  if (!exact.length && !off.length) return noun;
  let summary = String(report.summary ?? "");
  const claims = [];
  for (const claim of report.claims) {
    if (off.includes(claim?.id)) {
      summary = summary.replace(String(claim.text), "");
      continue;
    }
    const quote = claim?.citations?.[0]?.quote;
    if (exact.includes(claim?.id) && quote) {
      summary = summary.replace(String(claim.text), quote);
      claims.push({ ...claim, text: quote, shown_as_quote: true });
    } else {
      claims.push(claim);
    }
  }
  const cited = new Set(claims.flatMap((claim) => (claim?.citations ?? []).map((c) => c.source)));
  const sources = Array.isArray(report.sources) ? report.sources.filter((source) => cited.has(source?.id)) : [];
  if (off.length) {
    summary = summary.replace(COUNT_LINE, countLine(claims, sources)).replace(/\s+/g, " ").trim();
    // The summary quotes the first claims: when all of those came off, the first one left takes their place.
    if (claims[0] && !claims.some((claim) => summary.includes(String(claim.text)))) {
      summary = summary.replace(COUNT_LINE, (line) => `${line} ${claims[0].text}`);
    }
  }
  return { ...noun, value: { ...noun.value, report: { ...report, claims, sources, summary } } };
}

/** A report taken off display isn't listed at all. */
export function isListed(record) {
  return !TAKEN_OFF.has(record?.key);
}
