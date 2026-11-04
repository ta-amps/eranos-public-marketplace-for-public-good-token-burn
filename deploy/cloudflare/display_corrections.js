// Claims whose wording dropped a qualifier its source has. Pages and reads show the source's exact words instead; the
// stored record is never changed, and the shown record says which claims this touched.
const SHOWN_AS_QUOTES = { "RPT-RC676414-01": ["C1", "C2", "C3"] };

export function withExactQuotes(noun) {
  const report = noun?.value?.report;
  const ids = noun?.store === "eranos.solutions" && report ? SHOWN_AS_QUOTES[noun.key] : undefined;
  if (!ids || !Array.isArray(report.claims)) return noun;
  let summary = String(report.summary ?? "");
  const claims = report.claims.map((claim) => {
    const quote = claim?.citations?.[0]?.quote;
    if (!ids.includes(claim?.id) || !quote) return claim;
    summary = summary.replace(String(claim.text), quote);
    return { ...claim, text: quote, shown_as_quote: true };
  });
  return { ...noun, value: { ...noun.value, report: { ...report, claims, summary } } };
}
