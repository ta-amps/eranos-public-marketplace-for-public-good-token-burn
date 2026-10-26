const BANNED = [
  "criminal",
  "criminals",
  "trafficker",
  "traffickers",
  "scammer",
  "scammers",
  "fraudster",
  "fraudsters",
  "perpetrator",
  "perpetrators",
  "culprit",
  "culprits",
  "guilty",
] as const;

export function findBannedWords(text: string): string[] {
  const lower = text.toLowerCase();
  return BANNED.filter((word) => new RegExp(`\\b${word}\\b`, "i").test(lower));
}
