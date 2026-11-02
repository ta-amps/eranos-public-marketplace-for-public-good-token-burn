/**
 * Addresses the pages link to. GitHub's ta-amps organization answers 404 since its suspension, so source links
 * point at Agora's source mirror, which serves each repository as an archive with its commit and SHA-256.
 */

export const AGORA_URL = "https://agora.eranosforgood.org/";
/** Agora's overview deck, at its nouns-and-verbs section. Agora has no how-it-works page yet, so links here say "deck". */
export const AGORA_HOW_IT_WORKS_URL = `${AGORA_URL}decks/overview-and-architecture/#nouns-and-verbs`;
export const AGORA_SOURCE_URL = `${AGORA_URL}source/`;
/** The seed-pack library, browsable on Agora. */
export const PACK_LIBRARY_URL = `${AGORA_URL}library/`;
