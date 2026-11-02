/**
 * A hint while someone types, mirroring Tessera's own screen for personal and payment data
 * (deploy/cloudflare/cloud_access.js, the same rules as its Python side): email addresses outside the example
 * domains, identity and payment card numbers, bank account numbers (IBAN), phone numbers and street addresses.
 * It is only a hint. The server checks again when the request is sent, and neither catches everything.
 */

const EMAIL = /@(?!example\.(?:com|org|net)\b)[a-z0-9.-]+\.[a-z]{2,}/i;
const IDENTITY = /\b\d{3}-\d{2}-\d{4}\b/;
const CARD = /\b(?:\d[ -]?){13,19}\b/;
const IBAN = /\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b/g;
const PHONE = new RegExp(
  [
    String.raw`(?<![\w+])(?:\+\d{1,3}[ .-]?)?(?:\(\d{3}\)[ .-]?|\d{3}[ .-])\d{3}[ .-]\d{4}(?![\w-])`,
    String.raw`(?<![\w+])\+\d{1,3}(?:[ .-]?\d{2,4}){2,5}(?![\w-])`,
  ].join("|"),
);
const ADDRESS =
  /\b\d{1,5}[ \t]+(?:[A-Z][a-z]+[ \t]+){1,3}(?:Street|St|Avenue|Ave|Road|Rd|Lane|Ln|Drive|Dr|Boulevard|Blvd|Court|Ct|Way|Place|Pl)\b/;

/** Folds full-width and other decimal digits to ASCII, as Tessera's screenText does. */
function screenText(text: string): string {
  return text.normalize("NFKC").replace(/\p{Nd}/gu, (ch) => {
    if (ch >= "0" && ch <= "9") return ch;
    const cp = ch.codePointAt(0) ?? 0;
    let k = 0;
    while (k < 64 && /\p{Nd}/u.test(String.fromCodePoint(cp - k - 1))) k++;
    return String(k % 10);
  });
}

export type PersonalKind = "email" | "phone" | "identity" | "card" | "iban" | "address";

/** The kinds of personal data the text seems to hold, in a stable order. */
export function personalDataKinds(raw: string): PersonalKind[] {
  const text = screenText(raw);
  const kinds: PersonalKind[] = [];
  if (EMAIL.test(text)) kinds.push("email");
  if (PHONE.test(text)) kinds.push("phone");
  if (IDENTITY.test(text)) kinds.push("identity");
  else if (CARD.test(text)) kinds.push("card");
  if ([...text.matchAll(IBAN)].some((m) => (m[0].match(/[0-9]/g) ?? []).length >= 10)) kinds.push("iban");
  if (ADDRESS.test(text)) kinds.push("address");
  return kinds;
}

export function wordCount(text: string): number {
  return text.trim().split(/\s+/).filter(Boolean).length;
}

export type CaseHint = "named" | "birth" | "health";

const PERSON_WORD = String.raw`\b(?:client|patient|survivor|victim|resident|tenant|participant|child|youth|mother|father|caller)s?\b`;
const NAMED = new RegExp(`${PERSON_WORD}[^.!?\\n]{0,40}\\b[A-Z][a-z]+(?: [A-Z][a-z]+)?\\b|\\b[A-Z][a-z]+ [A-Z][a-z]+\\b[^.!?\\n]{0,30}${PERSON_WORD}`);
const BIRTH = /\b(?:DOB|d\.o\.b\.|date of birth|born (?:on|in) )|\b(?:0?[1-9]|[12]\d|3[01])[/.-](?:0?[1-9]|1[0-2])[/.-](?:19|20)\d{2}\b/i;
const HEALTH = /\b(?:diagnos\w*|HIV|AIDS|cancer|depress\w*|PTSD|schizophren\w*|bipolar|pregnan\w*|overdose|suicid\w*|disabilit\w*)\b/i;

/**
 * Likely case details: a client, patient or survivor word near a capitalised name, a date of birth, or a diagnosis.
 * It only warns. Names and case details are exactly what an automatic check can't recognise for sure, so it never
 * says a text is free of them.
 */
export function caseDetailHints(raw: string): CaseHint[] {
  const hints: CaseHint[] = [];
  if (NAMED.test(raw)) hints.push("named");
  if (BIRTH.test(raw)) hints.push("birth");
  if (HEALTH.test(raw)) hints.push("health");
  return hints;
}
