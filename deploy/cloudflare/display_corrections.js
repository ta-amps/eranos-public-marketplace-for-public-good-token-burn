// Claims whose wording dropped a qualifier its source has. Pages and reads show the source's exact words instead; the
// stored record is never changed, and the shown record says which claims this touched.
const SHOWN_AS_QUOTES = { "RPT-RC676414-01": ["C1", "C2", "C3"] };
// Claims from an off-topic source: off public display, and so is a source nothing else cites.
const OFF_TOPIC = { "RPT-RC676414-01": ["C5", "C6"] };

export function withExactQuotes(noun) {
  const report = noun?.value?.report;
  const ids = noun?.store === "eranos.solutions" && report ? SHOWN_AS_QUOTES[noun.key] : undefined;
  if (!ids || !Array.isArray(report.claims)) return noun;
  let summary = String(report.summary ?? "");
  const off = OFF_TOPIC[noun.key] ?? [];
  const claims = report.claims
    .filter((claim) => !off.includes(claim?.id))
    .map((claim) => {
      const quote = claim?.citations?.[0]?.quote;
      if (!ids.includes(claim?.id) || !quote) return claim;
      summary = summary.replace(String(claim.text), quote);
      return { ...claim, text: quote, shown_as_quote: true };
    });
  const cited = new Set(claims.flatMap((claim) => (claim?.citations ?? []).map((c) => c.source)));
  const sources = Array.isArray(report.sources) ? report.sources.filter((source) => cited.has(source?.id)) : report.sources;
  if (off.length && Array.isArray(sources)) {
    summary = summary.replace(
      /^\d+ cited points? from \d+ public sources?\./,
      `${claims.length} cited point${claims.length === 1 ? "" : "s"} from ${sources.length} public source${sources.length === 1 ? "" : "s"}.`,
    );
  }
  return { ...noun, value: { ...noun.value, report: { ...report, claims, sources, summary } } };
}
