/**
 * Requests left off the public lists; the records stay as they are, and each one's own page and API address still work.
 *
 * rq-...-mvywfy1j asked about food-safety rules for a food pantry. The reuse match gave it an unrelated IRS report, so
 * listing it would present a wrong answer as a result. Remove a key once its record has an answer that fits.
 */
const UNLISTED = new Set(["rq-r_e685d17b84d146cfbee59bb0fb880abe-mvywfy1j"]);

export function isListed(requestId: string): boolean {
  return !UNLISTED.has(requestId);
}
